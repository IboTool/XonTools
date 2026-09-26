"""L1-var's raw responses (CHANGELOG_EXPERIMENTS.md, A1): every call of every repetition is saved to its own folder,
never to tests/fixtures, with the record the cache would hold, so the variance analysis can be recomputed from that
folder alone with no API calls. Fixture recording stays off for L1-var: fixtures come only from the L1 run of record."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

from .client import LLM, SCHEMA_TOO_COMPLEX, LLMError, fixture_path, request_hash


class SavedRejection(Exception):
    """A saved rejected output schema, raised as the API raised it (client.schema_too_complex reads it so)."""
    status_code = 400


class RawSaver:
    """While active, saves each call `llm` completes: the cached record (request hash, tag, model, kind, schema,
    output, usage, stop_reason) plus the document, the repetition and the call's position. A no-op without a folder.
    Calls may complete concurrently (rev. 2.2); positions still follow completion order."""

    def __init__(self, llm: LLM, raw_dir: Path | str | None):
        self.llm, self.raw_dir = llm, None if raw_dir is None else Path(raw_dir)
        self.doc_id, self.repetition, self.saved = None, None, 0
        self._lock = threading.Lock()

    def at(self, doc_id: str, repetition: int) -> None:
        self.doc_id, self.repetition = doc_id, repetition

    def __enter__(self) -> RawSaver:
        if self.raw_dir is not None:
            self._record = self.llm._record
            self.llm._record = self._save
        return self

    def __exit__(self, *exc) -> None:
        if self.raw_dir is not None:
            del self.llm._record

    def _save(self, tag: str, key: str, record: dict) -> None:
        path = fixture_path(tag, self.raw_dir)
        with self._lock:
            if path.exists():
                raise LLMError(f"An L1-var response is already saved at {path}; L1-var writes to a new folder.")
            self.saved += 1
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(dict(record, doc_id=self.doc_id, repetition=self.repetition, call=self.saved),
                                       indent=1, ensure_ascii=False), encoding="utf-8")
        self._record(tag, key, record)


class SavedResponses:
    """An SDK client that answers from a folder of saved L1-var responses, by the hash of the request sent and in
    call order (a re-score sends its first attempt's request again). A request with no saved response left is an
    error, never an API call; a saved rejection of the request's output schema is raised again."""

    def __init__(self, raw_dir: Path | str):
        saved = sorted((json.loads(p.read_text("utf-8")) for p in Path(raw_dir).glob("*.json")), key=lambda r: r["call"])
        if not saved:
            raise LLMError(f"No saved L1-var responses in {raw_dir}.")
        self.models = {r["model"] for r in saved}
        self.pending: dict[str, list[dict]] = {}
        for r in saved:
            self.pending.setdefault(r.get("sent", r["request"]), []).append(r)
        self.messages = self
        self._lock = threading.Lock()

    def create(self, **body):
        key = request_hash(body)
        with self._lock:
            if not self.pending.get(key):
                raise LLMError(f"No saved L1-var response left for request {key[:16]}.")
            r = self.pending[key].pop(0)
        if r.get("rejected"):
            raise SavedRejection(f"{SCHEMA_TOO_COMPLEX} (saved L1-var response {key[:16]})")
        u = r["usage"]
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=r["output"] if r["kind"] == "text" else json.dumps(r["output"]))],
            stop_reason=r["stop_reason"],
            usage=SimpleNamespace(input_tokens=u["input_tokens"], output_tokens=u["output_tokens"],
                                  output_tokens_details={"thinking_tokens": u["thinking_tokens"]}))

    def left_over(self) -> int:
        return sum(map(len, self.pending.values()))
