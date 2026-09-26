"""The human review queue (XONFORGE_SPEC.md §7.4; the user's item 10 of 2026-09-25, xonforge/docs/decisions.md).
Queued: every document with a flag from the checks, the scans or the reviewers (§7.1 to §7.3), every document that
used the full retry cap, and a random share of the unflagged ones, each with the reasons it is queued.

Reviewer flags come from the reviewed batches (outcome.py), passed in per document. The random share: from the
unflagged documents sorted by id, ceil(0.10 × n) are drawn without replacement, at least 1 (at least 2 in the
20-document sample, or every unflagged document if there are fewer), with the run's seed, which is logged in the
decision log before any review (decisions.py). Queue items quote flags, which can quote the document, so the queue is
kept under the cache directory's parent, in reviews/queue/<run>.json.
"""
from __future__ import annotations

import json
import math
import os
import random
from fractions import Fraction
from pathlib import Path
from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, TypeAdapter

from xonforge import locations
from xonforge.render.schema import Document

from .decisions import DecisionLog

SHARE = Fraction(1, 10)
SAMPLE_MIN = 2


class QueueItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    run: str
    doc_id: str
    reasons: tuple[str, ...]


def reasons(document: Document, reviewer_flags: Sequence[str] = ()) -> list[str]:
    """Why a document goes to a human: its rendering flags (every attempt used, checks still failing), a scan's hits,
    and the reviewers' flags."""
    out = list(document.flags)
    out += [f"the {r.scan} scan found hits" for r in document.scans if r.result == "hits"]
    out += [f"a reviewer flagged: {f}" for f in reviewer_flags]
    return out


def flagged(run: str, documents: Sequence[Document],
            reviewer_flags: Mapping[str, Sequence[str]] | None = None) -> list[QueueItem]:
    reviewer_flags = reviewer_flags or {}
    unknown = sorted(set(reviewer_flags) - {d.doc_id for d in documents})
    if unknown:
        raise ValueError(f"reviewer flags for documents not given: {', '.join(unknown)}")
    items = [QueueItem(run=run, doc_id=d.doc_id, reasons=tuple(reasons(d, reviewer_flags.get(d.doc_id, ()))))
             for d in documents]
    return [i for i in items if i.reasons]


def random_share(unflagged: Sequence[str], seed: int, *, sample: bool = False) -> list[str]:
    """The unflagged documents drawn for a human's spot check, sorted by id."""
    ids = sorted(set(unflagged))
    n = min(len(ids), max(math.ceil(SHARE * len(ids)), SAMPLE_MIN if sample else 1))
    return sorted(random.Random(f"xonforge:spot-check:{seed}").sample(ids, n))


def queue(run: str, documents: Sequence[Document], reviewer_flags: Mapping[str, Sequence[str]], log: DecisionLog,
          *, sample: bool = False) -> list[QueueItem]:
    """The run's queue: its flagged documents, then its random share of the unflagged ones, drawn with the seed the
    decision log holds for the run."""
    seed = log.seed(run)
    if seed is None:
        raise ValueError(f"run {run} has no sample seed in the decision log; it is logged before any review")
    items = flagged(run, documents, reviewer_flags)
    chosen = random_share([d.doc_id for d in documents if d.doc_id not in {i.doc_id for i in items}], seed,
                          sample=sample)
    return items + [QueueItem(run=run, doc_id=d, reasons=(
        f"drawn for a spot check: the random share of unflagged documents, with the run's seed {seed}",))
                    for d in chosen]


class QueueStore:
    def __init__(self, root: str | Path | None = None):
        self.root = locations.outside_worktrees(
            root if root is not None else locations.text_log_dir() / "reviews" / "queue", "review queue")

    def path(self, run: str) -> Path:
        if not run or any(c in run for c in '/\\:*?"<>|') or run in (".", ".."):
            raise ValueError(f"a run is a plain file name, not {run!r}")
        return self.root / f"{run}.json"

    def save(self, run: str, items: Sequence[QueueItem]) -> Path:
        if any(i.run != run for i in items):
            raise ValueError(f"every item saved in run {run}'s queue belongs to run {run}")
        path = self.path(run)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps([i.model_dump() for i in items], indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return path

    def load(self, run: str) -> list[QueueItem]:
        path = self.path(run)
        return TypeAdapter(list[QueueItem]).validate_json(path.read_text(encoding="utf-8")) if path.exists() else []
