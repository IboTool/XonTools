"""The only module that talks to the Anthropic API (XON_A1_CONSISTENCY.md §2).

The SDK reads the API key from the environment itself: this module only checks whether it is set, and never passes,
stores or logs it. Without it the client runs in dry-run mode and answers from recorded fixtures.

Structured output: the Pydantic schema goes out as ``output_config.format`` through ``messages.create()``, so that
the stop reason is checked before validating; ``messages.parse()`` validates inside the SDK and raises on a refused
or truncated response before its stop reason can be read. The schema is not run through the SDK's
``transform_schema``: in SDK 0.84 it moves ``enum`` into the description, although the API enforces ``enum``.

Rev. 2.2 (XON_A1_REV2_2_PRECISION.md §4.2): calls may run concurrently (budget, usage, log and fixtures are shared
under a lock), the system prompt may carry a prompt-cache breakpoint, and a development pass may send its first
attempts as one Message Batch (``BatchRunner``), each result cached under the key its synchronous request has.

Rev. 2.2's entity calls (§5.3, §5.7) ask for adaptive thinking by name (``thinking="adaptive"``), and send output
schemas generated per document. When the API will not compile such a schema (a 400, "Schema is too complex for
compilation"), the call raises LLMSchemaRejected; the rejection is cached and recorded like an answer, so a replay
takes the same fallback without asking again.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, TypeAdapter, ValidationError

from ..config import (DEFAULT, LLM_BATCH_PRICE_MULT, LLM_CACHE_READ_MULT, LLM_CACHE_READ_MULT_DEFAULT,
                      LLM_CACHE_WRITE_MULT, LLM_CAPABILITIES, LLM_MODELS, LLM_PRICES_USD_PER_MTOK, XonConfig)

API_KEY_ENV = "ANTHROPIC_API_KEY"
RECORD_ENV = "XON_LLM_RECORD"
FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"
LOG_NAME = "log.jsonl"
RETRY_STATUS = (429, 529)   # rate limited, overloaded
RETRY_ERRORS = ("APIConnectionError",)   # the SDK's failures with no response, its APITimeoutError included
# JSON-schema keywords structured outputs reject (Claude docs, "JSON Schema limitations"; minItems only 0 or 1)
UNSUPPORTED_KEYWORDS = frozenset({"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
                                  "minLength", "maxLength", "maxItems", "uniqueItems"})

_SDK = None                 # the process's one anthropic.Anthropic()


class LLMError(RuntimeError):
    """A call that did not produce a usable response."""


class BudgetExceeded(LLMError):
    """The call could take the session's token total past the budget."""


class DryRunMissingFixture(LLMError):
    """Dry-run mode and no recorded fixture for the call's tag."""


class LLMRefusal(LLMError):
    """The model declined (stop_reason "refusal")."""


class LLMTruncated(LLMError):
    """The response hit max_tokens (stop_reason "max_tokens")."""


class LLMOutputInvalid(LLMError):
    """The response did not validate against the requested schema."""


class LLMSchemaRejected(LLMError):
    """The API would not compile the call's output schema (SCHEMA_TOO_COMPLEX)."""


SCHEMA_TOO_COMPLEX = "Schema is too complex for compilation"


def schema_too_complex(exc) -> bool:
    """The API's 400 for an output schema past its internal grammar limits or its compilation timeout (Claude docs,
    structured outputs, schema complexity limits)."""
    message = str(exc).lower()
    return getattr(exc, "status_code", None) == 400 and "schema" in message and (
        "too complex" in message or "compil" in message)


def api_key_is_set() -> bool:
    return bool(os.environ.get(API_KEY_ENV))


def fixture_path(tag: str, fixture_dir: str | Path | None = None) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", tag).strip("._")[:150] or "untagged"
    return Path(fixture_dir if fixture_dir is not None else FIXTURE_DIR) / f"{safe}.json"


def output_schema(schema: type[BaseModel]) -> dict:
    """The JSON schema sent as output_config.format: the model's schema with additionalProperties false on every
    object, as the API requires."""
    def strict(node, where: str):
        if isinstance(node, list):
            return [strict(v, where) for v in node]
        if not isinstance(node, dict):
            return node
        bad = sorted(UNSUPPORTED_KEYWORDS & node.keys()) + (["minItems"] if node.get("minItems", 0) > 1 else [])
        if bad:
            raise ValueError(f"{schema.__name__}{where} uses {', '.join(bad)}, which structured outputs reject")
        out = {k: (v if k == "properties" else strict(v, f"{where}.{k}")) for k, v in node.items()}
        if "properties" in node:
            out["properties"] = {name: strict(v, f"{where}.{name}") for name, v in node["properties"].items()}
        if out.get("type") == "object":
            out["additionalProperties"] = False
        return out
    return strict(TypeAdapter(schema).json_schema(), "")


def request_hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def request_key(body: dict, attempt: int = 1) -> str:
    """The cache key: the request's hash. A later attempt at the same request (rev. 2.2 scores a malformed pair
    again with the same request) is keyed with its attempt number, so each attempt has its own cached answer."""
    return request_hash(body) if attempt == 1 else request_hash({"attempt": int(attempt), "request": body})


def _system_text(system) -> str:
    return system if isinstance(system, str) else "".join(block.get("text", "") for block in system)


def transient(exc) -> bool:
    """A transport failure worth retrying (XON_A1_REV2_2_PRECISION.md §4.2): rate limited, overloaded or another 5xx
    status, a timeout, or no connection. Any other error, a 400 among them, is raised at once."""
    status = getattr(exc, "status_code", None)
    if status in RETRY_STATUS or (isinstance(status, int) and 500 <= status < 600):
        return True
    return any(c.__name__ in RETRY_ERRORS for c in type(exc).__mro__)


def _retry_after(exc) -> float:
    """The server's retry-after header in seconds, 0 if absent or unreadable."""
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        return max(float(headers.get("retry-after") or 0.0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _sdk():
    global _SDK
    if _SDK is None:
        import anthropic
        _SDK = anthropic.Anthropic(max_retries=0)  # reads the key from the environment; retries are done here
    return _SDK


def _usage_of(resp) -> dict:
    """input_tokens counts every input token, cached or not; the cache writes and reads among them are added only
    when there are any, so a response without prompt caching gives the same record as before rev. 2.2."""
    u = getattr(resp, "usage", None)

    def get(obj, name):
        return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)

    write, read = int(get(u, "cache_creation_input_tokens") or 0), int(get(u, "cache_read_input_tokens") or 0)
    details = get(u, "output_tokens_details")
    usage = {"input_tokens": int(get(u, "input_tokens") or 0) + write + read,
             "output_tokens": int(get(u, "output_tokens") or 0),
             "thinking_tokens": int((get(details, "thinking_tokens") if details is not None else 0) or 0)}
    if write or read:
        usage.update(cache_write_tokens=write, cache_read_tokens=read)
    return usage


def cost_usd(model: str, usage: dict, batch: bool = False) -> float:
    """The call's price: uncached input at the input price, cache writes at 1.25x and reads at 0.1x of it, output at
    the output price, all halved for a batch."""
    price_in, price_out = LLM_PRICES_USD_PER_MTOK[model]
    write, read = usage.get("cache_write_tokens", 0), usage.get("cache_read_tokens", 0)
    read_mult = LLM_CACHE_READ_MULT.get(model, LLM_CACHE_READ_MULT_DEFAULT)
    cost = ((usage["input_tokens"] - write - read) * price_in + write * price_in * LLM_CACHE_WRITE_MULT
            + read * price_in * read_mult + usage["output_tokens"] * price_out) / 1e6
    return cost * (LLM_BATCH_PRICE_MULT if batch else 1.0)


class LLM:
    """Cached, budgeted and logged calls to one Claude model (§2.1).

    ``client`` replaces the SDK client (tests pass a fake); ``fixture_dir`` replaces ``FIXTURE_DIR``.
    """

    def __init__(self, model: str | None = None, cache_dir: str | Path = "cache/llm", budget_tokens: int | None = None,
                 cfg: XonConfig = DEFAULT, client=None, fixture_dir: str | Path | None = None, sleep=time.sleep):
        self.cfg = cfg
        self.model = model or cfg.llm_model
        self.cache_dir = Path(cache_dir)
        self.budget_tokens = int(cfg.llm_budget_tokens if budget_tokens is None else budget_tokens)
        self.fixture_dir = fixture_dir
        self.dry_run = client is None and not api_key_is_set()
        self._client = client
        self._sleep = sleep
        self._recorded: dict[str, str] = {}
        self._lock = threading.RLock()
        self._reserved = 0          # tokens reserved by calls in flight
        self._usage = {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "calls": 0, "api_calls": 0,
                       "cache_hits": 0, "fixture_hits": 0, "stale_fixtures": 0, "estimated_cost_usd": 0.0,
                       "cache_write_tokens": 0, "cache_read_tokens": 0, "batch_calls": 0, "transport_retries": 0}

    # ------------------------------------------------------------------ public interface
    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, name: str) -> None:
        if name not in LLM_CAPABILITIES:
            raise ValueError(f"unknown model {name!r}; the configured models are {', '.join(LLM_MODELS)}")
        self._model = name

    @property
    def spent_tokens(self) -> int:
        return self._usage["input_tokens"] + self._usage["output_tokens"]

    @property
    def usage(self) -> dict:
        return dict(self._usage, spent_tokens=self.spent_tokens, budget_tokens=self.budget_tokens)

    def thinking_mode(self, thinking: bool | str) -> str:
        caps = LLM_CAPABILITIES[self.model]
        if thinking == "adaptive" and caps["thinking_adaptive"]:
            return "adaptive"
        if thinking:
            return caps["thinking_default"]
        return "disabled" if caps["thinking_can_disable"] else "adaptive (cannot be disabled)"

    def request(self, *, system: str, user: str, max_tokens: int, thinking: bool | str,
                schema: type[BaseModel] | None = None, cache_system: bool = False) -> dict:
        """The messages.create() body; the cache key is its hash. thinking: False disables thinking where the model
        allows it, True leaves the model's default (no thinking field), "adaptive" asks for adaptive thinking at the
        default effort by name, on models that accept it (the others keep their default). cache_system puts a
        prompt-cache breakpoint on the system prompt (the API caches nothing below the model's minimum cacheable
        length, silently)."""
        caps = LLM_CAPABILITIES[self.model]
        body = {"model": self.model, "max_tokens": int(max_tokens),
                "system": ([{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if cache_system
                           else system),
                "messages": [{"role": "user", "content": user}]}
        if caps["sampling"]:
            body["temperature"] = float(self.cfg.llm_temperature)
        if thinking == "adaptive":
            if caps["thinking_adaptive"]:
                body["thinking"] = {"type": "adaptive"}
        elif not thinking and caps["thinking_can_disable"]:
            body["thinking"] = {"type": "disabled"}
        if schema is not None:
            body["output_config"] = {"format": {"type": "json_schema", "schema": output_schema(schema)}}
        return body

    def parse(self, *, system: str, user: str, schema: type[BaseModel], max_tokens: int = 2048,
              thinking: bool | str = False, tag: str = "", bypass_cache: bool = False, cache_system: bool = False,
              attempt: int = 1) -> BaseModel:
        body = self.request(system=system, user=user, max_tokens=max_tokens, thinking=thinking, schema=schema,
                            cache_system=cache_system)
        return self._call(body, schema, tag, thinking, bypass_cache, attempt)

    def is_cached(self, key: str) -> bool:
        return (self.cache_dir / f"{key}.json").exists()

    def text(self, *, system: str, user: str, max_tokens: int = 1024, thinking: bool = False, tag: str = "",
             bypass_cache: bool = False) -> str:
        body = self.request(system=system, user=user, max_tokens=max_tokens, thinking=thinking)
        return self._call(body, None, tag, thinking, bypass_cache)

    def clear_cache(self) -> int:
        """Delete the cached responses (the call log stays); returns how many were deleted."""
        paths = list(self.cache_dir.glob("*.json")) if self.cache_dir.exists() else []
        for p in paths:
            p.unlink()
        return len(paths)

    # ------------------------------------------------------------------ one call
    def _entry(self, body: dict, key: str, schema, tag: str, thinking: bool) -> dict:
        return {"tag": tag, "model": self.model, "kind": "text" if schema is None else "parse",
                "schema": None if schema is None else schema.__name__, "max_tokens": body["max_tokens"],
                "thinking": self.thinking_mode(thinking), "temperature": body.get("temperature"), "request": key[:16]}

    def _call(self, body: dict, schema, tag: str, thinking: bool, bypass_cache: bool, attempt: int = 1):
        key = request_key(body, attempt)
        entry = self._entry(body, key, schema, tag, thinking)
        kind = entry["kind"]
        t0 = time.perf_counter()
        if not bypass_cache:
            hit = self._read_cache(key)
            if hit is not None:
                with self._lock:
                    self._usage["calls"] += 1
                    self._usage["cache_hits"] += 1
                if hit.get("rejected"):
                    self._log(entry, "cache", t0, error="LLMSchemaRejected")
                    self._record(tag, key, hit)
                    raise self._rejection(tag)
                value = self._validated(hit["output"], schema, tag)
                self._log(entry, "cache", t0)
                self._record(tag, key, hit)
                return value
        if self.dry_run:
            return self._from_fixture(entry, key, kind, schema, tag, t0)
        try:
            reserve = self._check_budget(body)
        except BudgetExceeded:
            self._log(entry, "budget", t0, error="BudgetExceeded")
            raise
        try:
            resp = self._create(body, entry)
        except Exception as exc:
            self._release(reserve)
            if schema is not None and schema_too_complex(exc):
                with self._lock:
                    self._usage["calls"] += 1
                    self._usage["api_calls"] += 1       # a rejected request is not billed
                self._log(entry, "api", t0, error="LLMSchemaRejected")
                record = {"request": key, "tag": tag, "model": self.model, "kind": kind, "schema": entry["schema"],
                          "rejected": SCHEMA_TOO_COMPLEX, "usage": {"input_tokens": 0, "output_tokens": 0,
                                                                    "thinking_tokens": 0}}
                if not bypass_cache:
                    self._write_cache(key, record)
                self._record(tag, key, record)
                raise self._rejection(tag) from exc
            self._log(entry, "api", t0, error=type(exc).__name__)
            raise
        return self._accept(resp, body, key, entry, schema, tag, t0, bypass_cache, reserve=reserve, attempt=attempt)

    @staticmethod
    def _rejection(tag: str) -> LLMSchemaRejected:
        return LLMSchemaRejected(f"The API would not compile the output schema of the call tagged {tag!r} "
                                 f"({SCHEMA_TOO_COMPLEX}).")

    def _accept(self, resp, body: dict, key: str, entry: dict, schema, tag: str, t0: float, bypass_cache: bool,
                reserve: int = 0, batch_id: str | None = None, attempt: int = 1):
        """A response from the API: charged, checked (refusal, truncation, schema), cached, logged and recorded. A
        later attempt's record also holds its attempt number and the hash of the request sent, which it shares with
        the first attempt."""
        usage = _usage_of(resp)
        self._charge(usage, release=reserve, batch=batch_id is not None)
        stop = getattr(resp, "stop_reason", None)
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        try:
            if stop == "refusal":
                raise LLMRefusal(f"The model declined the call tagged {tag!r} (stop_reason refusal).")
            if stop == "max_tokens":
                raise LLMTruncated(f"The response to the call tagged {tag!r} hit max_tokens = {body['max_tokens']} "
                                   "(which covers thinking plus output); raise it in the config.")
            output = text if schema is None else self._validated_json(text, schema, tag).model_dump(mode="json")
        except LLMError as exc:
            self._log(entry, "api", t0, usage=usage, stop_reason=stop, error=type(exc).__name__, batch_id=batch_id)
            raise
        record = {"request": key, "tag": tag, "model": self.model, "kind": entry["kind"], "schema": entry["schema"],
                  "output": output, "usage": usage, "stop_reason": stop}
        if attempt > 1:
            record.update(attempt=int(attempt), sent=request_hash(body))
        if batch_id is not None:
            record["batch_id"] = batch_id
        if not bypass_cache:
            self._write_cache(key, record)
        self._log(entry, "api", t0, usage=usage, stop_reason=stop, batch_id=batch_id)
        self._record(tag, key, record)
        return self._validated(output, schema, tag)

    def _create(self, body: dict, entry: dict | None = None):
        """messages.create with up to cfg.llm_retries retries, on transport failures only (``transient``), waiting at
        least as long as the server's retry-after. Each retry is logged on its own line (source "retry"); it is not a
        re-score."""
        client = self._client if self._client is not None else _sdk()
        delay = float(self.cfg.llm_backoff_s)
        retries = int(self.cfg.llm_retries)
        for attempt in range(retries + 1):
            try:
                return client.messages.create(**body)
            except Exception as exc:
                if not transient(exc) or attempt == retries:
                    raise
                status = getattr(exc, "status_code", None) or type(exc).__name__
                wait = max(delay, _retry_after(exc))
            with self._lock:
                self._usage["transport_retries"] += 1
            if entry is not None:
                self._log(entry, "retry", time.perf_counter(), status=status, retry=attempt + 1, wait_s=wait)
            self._sleep(wait)
            delay *= 2

    def reserve_of(self, body: dict) -> int:
        """Tokens a call could use: its input, estimated from its length, plus max_tokens."""
        chars = len(_system_text(body["system"])) + sum(len(m["content"]) for m in body["messages"])
        if "output_config" in body:
            chars += len(json.dumps(body["output_config"]))
        return math.ceil(chars / float(self.cfg.llm_chars_per_token)) + int(body["max_tokens"])

    def _check_budget(self, body: dict, reserve: int | None = None) -> int:
        """Reserves what the call (or a batch, with its total) could use, counting the calls in flight; raises
        BudgetExceeded if that could take the session past its budget."""
        reserve = self.reserve_of(body) if reserve is None else int(reserve)
        with self._lock:
            if self.spent_tokens + self._reserved + reserve > self.budget_tokens:
                raise BudgetExceeded(
                    f"This call could use up to {reserve:,} tokens (estimated input plus max_tokens), and "
                    f"{self.spent_tokens:,} of this session's {self.budget_tokens:,}-token budget are spent"
                    + (f" ({self._reserved:,} more reserved by calls in flight)" if self._reserved else "")
                    + ". Raise the budget to continue.")
            self._reserved += reserve
        return reserve

    def _release(self, reserve: int) -> None:
        with self._lock:
            self._reserved -= reserve

    def _charge(self, usage: dict, release: int = 0, batch: bool = False) -> None:
        with self._lock:
            self._reserved -= release
            u = self._usage
            u["calls"] += 1
            u["api_calls"] += 1
            u["batch_calls"] += int(batch)
            for k in ("input_tokens", "output_tokens", "thinking_tokens"):
                u[k] += usage[k]
            u["cache_write_tokens"] += usage.get("cache_write_tokens", 0)
            u["cache_read_tokens"] += usage.get("cache_read_tokens", 0)
            u["estimated_cost_usd"] += cost_usd(self.model, usage, batch)

    # ------------------------------------------------------------------ validation, fixtures, cache, log
    @staticmethod
    def _validated_json(text: str, schema, tag: str) -> BaseModel:
        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            raise LLMOutputInvalid(f"The response to the call tagged {tag!r} does not match {schema.__name__}: "
                                   f"{exc.error_count()} validation errors.") from exc

    @staticmethod
    def _validated(output, schema, tag: str):
        if schema is None:
            return str(output)
        try:
            return schema.model_validate(output)
        except ValidationError as exc:
            raise LLMOutputInvalid(f"The stored response for the call tagged {tag!r} does not match "
                                   f"{schema.__name__}: {exc.error_count()} validation errors.") from exc

    def _from_fixture(self, entry: dict, key: str, kind: str, schema, tag: str, t0: float):
        path = fixture_path(tag, self.fixture_dir)
        if not tag or not path.exists():
            self._log(entry, "fixture", t0, error="DryRunMissingFixture")
            raise DryRunMissingFixture(
                f"Dry-run mode ({API_KEY_ENV} is not set in the environment): no recorded fixture for the call "
                f"tagged {tag!r} (looked for {path}). Set {API_KEY_ENV} to call the API; with {RECORD_ENV}=1 every "
                "call is also recorded as a fixture.")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("kind") != kind:
            raise DryRunMissingFixture(f"The fixture for the call tagged {tag!r} holds a {data.get('kind')} "
                                       f"response, not a {kind} response.")
        value = None if data.get("rejected") else self._validated(data["output"], schema, tag)
        stale = data.get("request") != key
        with self._lock:
            self._usage["calls"] += 1
            self._usage["fixture_hits"] += 1
            self._usage["stale_fixtures"] += int(stale)
        if data.get("rejected"):
            self._log(entry, "fixture", t0, fixture_stale=stale, error="LLMSchemaRejected")
            raise self._rejection(tag)
        self._log(entry, "fixture", t0, fixture_stale=stale)
        return value

    def _record(self, tag: str, key: str, record: dict) -> None:
        if os.environ.get(RECORD_ENV) != "1":
            return
        if not tag:
            raise LLMError(f"With {RECORD_ENV}=1 every call needs a tag (the fixture's file name).")
        with self._lock:
            if self._recorded.get(tag, key) != key:
                raise LLMError(f"The fixture tag {tag!r} was already recorded for a different request in this "
                               "session.")
            path = fixture_path(tag, self.fixture_dir)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
            self._recorded[tag] = key

    def _read_cache(self, key: str) -> dict | None:
        path = self.cache_dir / f"{key}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        except (OSError, json.JSONDecodeError):
            return None

    def _write_cache(self, key: str, record: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_dir / f"{key}.{threading.get_ident()}.tmp"
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.cache_dir / f"{key}.json")

    def _log(self, entry: dict, source: str, t0: float, usage: dict | None = None, **extra) -> None:
        """One line per call: no prompt text and no key."""
        usage = usage or {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
        row = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **entry,
               "source": source, "cache_hit": source == "cache", **usage,
               "duration_s": round(time.perf_counter() - t0, 3),
               **{k: v for k, v in extra.items() if v is not None}}
        with self._lock:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with open(self.cache_dir / LOG_NAME, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")


# ------------------------------------------------------------------------------------------ Message Batches
BATCH_MAX_REQUESTS = 100_000        # Claude docs, batch processing: at most 100,000 requests or 256 MB per batch
BATCH_ENDED = "ended"


def _field(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


class BatchRunner:
    """A development pass's first attempts as one Message Batch at half price (XON_A1_REV2_2_PRECISION.md §4.2).

    ``run(calls)`` takes (body, schema, tag, thinking) for each call, sends the ones not cached yet, waits for the
    batch to end, and passes each succeeded result through the same checks as a synchronous response, caching it
    under the key the synchronous request has; the pipeline then answers from the cache. Failed, expired or
    rejected results are logged and left to the synchronous calls. The whole batch's worst case (input estimates plus
    max_tokens) must fit the session's budget before it is sent. The batch id and each request's key and tag, never
    its text, are kept in ``state_path``, so a wait that is interrupted resumes on the same batch."""

    def __init__(self, llm: LLM, state_path: str | Path, *, poll_s: float = 60.0, log=print, sleep=time.sleep):
        self.llm, self.state_path, self.poll_s, self.log, self.sleep = llm, Path(state_path), poll_s, log, sleep

    def run(self, calls) -> dict:
        llm = self.llm
        if llm.dry_run:
            raise LLMError(f"A batch needs the API ({API_KEY_ENV} is not set in the environment).")
        by_key = {request_key(body): (body, schema, tag, thinking) for body, schema, tag, thinking in calls}
        state = json.loads(self.state_path.read_text("utf-8")) if self.state_path.exists() else None
        client = llm._client if llm._client is not None else _sdk()
        hold = 0
        if state is None or state.get("ingested"):
            todo = [k for k in by_key if not llm.is_cached(k)]
            if not todo:
                return {"batch_id": None, "requests": 0}
            if len(todo) > BATCH_MAX_REQUESTS:
                raise LLMError(f"{len(todo):,} requests exceed a batch's {BATCH_MAX_REQUESTS:,}.")
            hold = llm._check_budget({}, reserve=sum(llm.reserve_of(by_key[k][0]) for k in todo))
            try:
                batch = client.messages.batches.create(
                    requests=[{"custom_id": k, "params": by_key[k][0]} for k in todo])
            except Exception:
                llm._release(hold)
                raise
            state = {"batch_id": _field(batch, "id"), "model": llm.model, "requests": len(todo),
                     "keys": {k: by_key[k][2] for k in todo}, "ingested": False,
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            self._save(state)
            self.log(f"Batch {state['batch_id']}: {len(todo):,} requests sent.")
        elif state["model"] != llm.model:
            raise LLMError(f"The batch in {self.state_path} is for {state['model']}, not {llm.model}.")
        try:
            return self._finish(client, state, by_key)
        finally:
            llm._release(hold)

    def _finish(self, client, state: dict, by_key: dict) -> dict:
        llm, batch_id = self.llm, state["batch_id"]
        while True:
            batch = client.messages.batches.retrieve(batch_id)
            if _field(batch, "processing_status") == BATCH_ENDED:
                break
            counts = _field(batch, "request_counts")
            self.log(f"Batch {batch_id}: {_field(batch, 'processing_status')}"
                     + (f", {_field(counts, 'succeeded', 0)} succeeded, {_field(counts, 'processing', 0)} processing"
                        if counts is not None else "") + ".")
            self.sleep(self.poll_s)
        outcome = {"succeeded": 0, "errored": 0, "expired": 0, "canceled": 0, "rejected": 0, "unknown": 0}
        for item in client.messages.batches.results(batch_id):
            key, result = _field(item, "custom_id"), _field(item, "result")
            kind = _field(result, "type")
            if key not in by_key:
                outcome["unknown"] += 1
                continue
            body, schema, tag, thinking = by_key[key]
            entry = llm._entry(body, key, schema, tag, thinking)
            if kind != "succeeded":
                outcome[kind if kind in outcome else "unknown"] += 1
                llm._log(entry, "batch", time.perf_counter(), error=f"batch result {kind}", batch_id=batch_id)
                continue
            if llm.is_cached(key):          # ingested before an interruption
                continue
            try:
                llm._accept(_field(result, "message"), body, key, entry, schema, tag, time.perf_counter(),
                            bypass_cache=False, batch_id=batch_id)
                outcome["succeeded"] += 1
            except LLMError:
                outcome["rejected"] += 1
        state.update(ingested=True, outcome=outcome)
        self._save(state)
        self.log(f"Batch {batch_id}: " + ", ".join(f"{n} {k}" for k, n in outcome.items() if n) + ".")
        return {"batch_id": batch_id, "requests": state["requests"], **outcome}

    def _save(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=1), "utf-8")
