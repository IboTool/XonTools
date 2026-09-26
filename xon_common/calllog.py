"""The spend and call log (XONFORGE_SPEC.md §4.2, §11): one JSON line for each call answered, sent, retried or held
back. It holds no prompt, response or document text and no key, so it may be committed, like A1's cache/llm/log.jsonl:
only the fields below are written, each a number, a boolean, None or a short string.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

FIELDS = frozenset({"run", "provider", "kind", "model", "tag", "request", "attempt", "source", "cache_hit",
                    "max_tokens", "schema", "reasoning", "temperature", "input_tokens", "output_tokens",
                    "thinking_tokens", "cache_read_tokens", "cache_write_tokens", "cost_usd", "duration_s",
                    "stop_reason", "request_id", "error", "status", "retry", "wait_s"})
MAX_TEXT = 80   # a tag, an id, a model or an error's class name is shorter; a quote from a document may not be


class CallLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, **fields) -> dict:
        unknown = sorted(set(fields) - FIELDS)
        if unknown:
            raise ValueError(f"not a call-log field: {', '.join(unknown)}")
        for name, value in fields.items():
            if not (value is None or isinstance(value, (bool, int, float))
                    or (isinstance(value, str) and len(value) <= MAX_TEXT)):
                raise ValueError(f"the call-log field {name} must be a number, a boolean, None or a string of at "
                                 f"most {MAX_TEXT} characters")
        row = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
               **{k: v for k, v in fields.items() if v is not None}}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def spent(self, run: str) -> dict[str, tuple[int, float]]:
        """Tokens and dollars each provider entry has used in the run, from the calls it answered (refused,
        truncated and invalid answers included), so that a resumed run's budget starts where the interrupted one
        stopped."""
        out: dict[str, tuple[int, float]] = {}
        for row in self.rows():
            if row.get("run") == run and row.get("source") == "api" and "input_tokens" in row:
                tokens, usd = out.get(row["provider"], (0, 0.0))
                out[row["provider"]] = (tokens + row["input_tokens"] + row.get("output_tokens", 0),
                                        usd + row.get("cost_usd", 0.0))
        return out
