"""The log of human decisions (XONFORGE_SPEC.md §7.4): append-only and hash-chained. Each entry carries the hash of
the entry before it, and its own hash covers all its fields and that link, so that altering, removing, inserting or
reordering an entry breaks the chain from there on. Removing entries from the end leaves a shorter chain that still
holds; only a head hash kept elsewhere shows it, so ``verify`` returns the head. Decisions carry reasons, which are
text, so the log lives under the cache directory's parent, in reviews/decisions.jsonl, like every file that holds
text.

Two kinds of entry: a decision on a document (accept, regenerate or discard, with a reason), and a run's seed, logged
once per run and kind of seed, and before any decision on the run. The sample seed draws the random share of
unflagged documents for human review (queue.random_share), and is logged before any flag exists (§7.4) and before any
review (the user's item 10 of 2026-09-25), that is, before the run renders. The quota seed breaks the quotas' rounding
ties (corpus/quotas.py) and the split seed draws the splits (corpus/splits.py); both are logged before generation
(the user's items 13 and 15).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from xonforge import locations

GENESIS = "0" * 64
SEEDS = {"sample_seed": "sample seed", "quota_seed": "quota seed", "split_seed": "split seed"}


class ChainBroken(RuntimeError):
    """The log is not the chain it was written as."""


class Entry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    seq: int
    time: str
    kind: Literal["decision", "sample_seed", "quota_seed", "split_seed"]
    run: str
    doc_id: str | None = None
    decision: Literal["accept", "regenerate", "discard"] | None = None
    reason: str | None = None
    reviewer: str | None = None
    seed: int | None = None
    prev: str
    hash: str

    @model_validator(mode="after")
    def _shape(self) -> Entry:
        if self.kind == "decision":
            if not (self.doc_id and self.decision and self.reason and self.reason.strip()) or self.seed is not None:
                raise ValueError("a decision names its document, the decision and a reason, and no seed")
        elif self.seed is None or any(x is not None for x in (self.doc_id, self.decision, self.reason)):
            raise ValueError(f"a {SEEDS[self.kind]} entry holds the seed and nothing of a decision")
        return self


def entry_hash(fields: dict) -> str:
    """The SHA-256 of an entry's fields, its own hash left out, as canonical JSON."""
    body = {k: v for k, v in fields.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


class DecisionLog:
    def __init__(self, path: str | Path | None = None, clock: Callable[[], datetime] | None = None):
        self.path = locations.outside_worktrees(
            path if path is not None else locations.text_log_dir() / "reviews" / "decisions.jsonl", "decision log")
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def entries(self) -> list[Entry]:
        """Every entry, once the whole chain is verified."""
        if not self.path.exists():
            return []
        out, prev = [], GENESIS
        for n, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                raw = json.loads(line)
                entry = Entry.model_validate(raw)
            except (json.JSONDecodeError, ValidationError) as exc:
                raise ChainBroken(f"{self.path}, line {n}: not an entry ({type(exc).__name__})") from None
            if entry.seq != n - 1 or entry.prev != prev or entry.hash != entry_hash(raw):
                raise ChainBroken(f"{self.path}, line {n}: the chain breaks here")
            out.append(entry)
            prev = entry.hash
        return out

    def verify(self) -> tuple[int, str]:
        """The number of entries and the head hash; raises ChainBroken where the chain breaks."""
        entries = self.entries()
        return len(entries), entries[-1].hash if entries else GENESIS

    def _append(self, **fields) -> Entry:
        entries = self.entries()
        fields = {"seq": len(entries), "time": self.clock().isoformat(timespec="seconds"),
                  "prev": entries[-1].hash if entries else GENESIS, **fields}
        body = {name: fields.get(name) for name in Entry.model_fields if name != "hash"}
        entry = Entry.model_validate({**body, "hash": entry_hash(body)})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(entry.model_dump_json() + "\n")
            f.flush()
            os.fsync(f.fileno())
        return entry

    def decide(self, run: str, doc_id: str, decision: str, reason: str, reviewer: str | None = None) -> Entry:
        return self._append(kind="decision", run=run, doc_id=doc_id, decision=decision, reason=reason,
                            reviewer=reviewer)

    def log_seed(self, run: str, seed: int, kind: str = "sample_seed") -> Entry:
        if kind not in SEEDS:
            raise ValueError(f"the seeds are {', '.join(SEEDS)}, not {kind!r}")
        entries = self.entries()
        if any(e.run == run and e.kind == kind for e in entries):
            raise ValueError(f"run {run} already has its {SEEDS[kind]}")
        if any(e.run == run and e.kind == "decision" for e in entries):
            raise ValueError(f"run {run} already has decisions; its {SEEDS[kind]} comes before any flag exists")
        return self._append(kind=kind, run=run, seed=seed)

    def seed(self, run: str, kind: str = "sample_seed") -> int | None:
        return next((e.seed for e in self.entries() if e.run == run and e.kind == kind), None)
