"""One cached, budgeted, retried and logged call to one provider entry (XONFORGE_SPEC.md §4.2, §11).

A request answered before is answered from the cache. In a dry run a request is answered only from the cache, so a
pipeline whose calls were recorded runs offline. Otherwise the call reserves its worst case in the budget, is sent
(transport retries resend the identical request; see retry.py), is charged for what it used, is checked for a
refusal, a truncation and the schema, and is cached. Every step is a line in the call log. Nothing is ever
substituted: an unavailable provider raises ProviderUnavailable.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass

from pydantic import BaseModel, ValidationError

from .budget import Budget, BudgetPaused
from .cache import ResponseCache
from .calllog import MAX_TEXT, CallLog
from .hashing import request_hash, request_key
from .providers.base import (Adapter, DryRunMissing, OutputInvalid, ProviderError, ProviderUnavailable, Refusal,
                             Truncated, Usage)
from .retry import RetryPolicy, send_with_retries
from .schema import parse_json


@dataclass(frozen=True)
class Result:
    text: str
    parsed: BaseModel | None
    usage: Usage
    cost_usd: float
    latency_s: float
    request_id: str | None
    stop: str
    provider: str
    model: str
    key: str
    source: str                 # "api" or "cache"
    transport_retries: int = 0


class Caller:
    def __init__(self, adapter: Adapter, *, cache: ResponseCache | None, budget: Budget, log: CallLog,
                 retry: RetryPolicy, run: str = "", dry_run: bool = False, chars_per_token: float = 2.5,
                 sleep=time.sleep, clock=time.perf_counter):
        """``cache`` None: nothing is read from or written to a cache (the startup check's test call)."""
        self.adapter, self.cache, self.budget, self.log, self.retry = adapter, cache, budget, log, retry
        self.run, self.dry_run, self.chars_per_token = run, dry_run, float(chars_per_token)
        self.sleep, self.clock = sleep, clock

    def input_estimate(self, body: dict) -> int:
        """The request's input tokens, estimated from its length as sent (JSON syntax included, so it errs high)."""
        return math.ceil(len(json.dumps(body, ensure_ascii=False)) / self.chars_per_token)

    def complete(self, *, system: str, user: str, max_tokens: int, schema: type[BaseModel] | None = None,
                 params=None, thinking: bool = False, tag: str = "", attempt: int = 1) -> Result:
        """``attempt``: a later attempt at the same request gets its own key and answer (hashing.request_key)."""
        if len(tag) > MAX_TEXT:
            raise ValueError(f"A call's tag is an id of at most {MAX_TEXT} characters, not text.")
        a, e = self.adapter, self.adapter.entry
        body = a.request(system=system, user=user, max_tokens=max_tokens, schema=schema, thinking=thinking,
                         params=params)
        key = request_key(body, attempt)
        base = {"run": self.run, "provider": e.name, "kind": e.provider, "model": e.model, "tag": tag,
                "request": key[:16], "attempt": attempt, "max_tokens": int(max_tokens),
                "schema": None if schema is None else schema.__name__, "reasoning": a.reasoning_label(thinking),
                "temperature": (params or {}).get("temperature") if e.capabilities.sampling else None}
        t0 = self.clock()

        def since() -> float:
            return round(self.clock() - t0, 3)

        hit = self.cache.get(e.name, key) if self.cache is not None else None
        if hit is not None:
            parsed = self._stored(hit["output"], schema, tag)
            self.log.write(**base, source="cache", cache_hit=True, duration_s=since())
            return Result(hit["output"] if schema is None else json.dumps(hit["output"], ensure_ascii=False), parsed,
                          Usage(**hit["usage"]), 0.0, since(), hit.get("request_id"), hit["stop"], e.name, e.model,
                          key, "cache")
        if self.dry_run:
            self.log.write(**base, source="dry-run", error="DryRunMissing", duration_s=since())
            raise DryRunMissing(f"Dry run: the call tagged {tag!r} to {e.name} is not in the cache.")
        ok, why = a.status()
        if not ok:
            self.log.write(**base, source="unavailable", error="ProviderUnavailable", duration_s=since())
            raise ProviderUnavailable(f"{e.name} is unavailable: {why}.")
        estimate = self.input_estimate(body)
        worst_usd = None if e.price is None else e.price.usd(
            estimate, int(max_tokens), cache_write_tokens=estimate if e.price.cache_write > 1 else 0)
        try:
            hold = self.budget.reserve(e.name, estimate + int(max_tokens), worst_usd)
        except BudgetPaused:
            self.log.write(**base, source="budget", error="BudgetPaused", duration_s=since())
            raise

        def retried(n, err, wait_s):
            self.log.write(**base, source="retry", status=err.status if err.status is not None else "no response",
                           retry=n, wait_s=wait_s)

        try:
            raw, retries = send_with_retries(lambda: a.send(body), a.transport_error, self.retry, retried, self.sleep)
        except Exception as exc:
            self.budget.release(hold)
            self.log.write(**base, source="api", error=type(exc).__name__, duration_s=since())
            raise
        try:
            reply = a.reply(raw)
        except Exception:
            self.budget.release(hold)
            self.log.write(**base, source="api", error="UnreadableResponse", duration_s=since())
            raise
        u = reply.usage
        cost = 0.0 if e.price is None else e.price.usd(u.input_tokens, u.output_tokens, u.cache_read_tokens,
                                                        u.cache_write_tokens)
        self.budget.charge(hold, reply.usage.total, cost)
        spent = {**asdict(reply.usage), "cost_usd": round(cost, 6), "stop_reason": reply.stop[:MAX_TEXT],
                 "request_id": (reply.request_id or "")[:MAX_TEXT] or None, "retry": retries or None}
        try:
            if reply.stop == "refusal":
                raise Refusal(f"{e.name} declined the call tagged {tag!r}.")
            if reply.stop == "max_tokens":
                raise Truncated(f"The response of {e.name} to the call tagged {tag!r} hit max_tokens = "
                                f"{int(max_tokens)}, which covers reasoning plus output.")
            parsed = None if schema is None else self._validated(reply.text, schema, tag)
        except ProviderError as exc:
            self.log.write(**base, source="api", error=type(exc).__name__, duration_s=since(), **spent)
            raise
        output = reply.text if schema is None else parsed.model_dump(mode="json")
        record = {"request": key, "provider": e.name, "kind": e.provider, "model": e.model, "tag": tag,
                  "schema": base["schema"], "output": output, "usage": asdict(reply.usage), "stop": reply.stop,
                  "request_id": reply.request_id, "cost_usd": cost}
        if attempt > 1:
            record.update(attempt=int(attempt), sent=request_hash(body))
        if self.cache is not None:
            self.cache.put(e.name, key, record)
        self.log.write(**base, source="api", duration_s=since(), **spent)
        return Result(reply.text, parsed, reply.usage, cost, since(), reply.request_id, reply.stop, e.name, e.model,
                      key, "api", retries)

    @staticmethod
    def _validated(text: str, schema: type[BaseModel], tag: str) -> BaseModel:
        try:
            return parse_json(text, schema)
        except ValidationError as exc:
            raise OutputInvalid(f"The response to the call tagged {tag!r} does not match {schema.__name__}: "
                                f"{exc.error_count()} validation errors.") from None

    @staticmethod
    def _stored(output, schema: type[BaseModel] | None, tag: str):
        if schema is None:
            return None
        try:
            return schema.model_validate(output)
        except ValidationError as exc:
            raise OutputInvalid(f"The cached response for the call tagged {tag!r} does not match "
                                f"{schema.__name__}: {exc.error_count()} validation errors.") from None
