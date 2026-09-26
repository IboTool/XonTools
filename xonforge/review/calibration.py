"""Reviewer calibration on canaries (XONFORGE_SPEC.md §7.3; the user's items 5, 8 and 9 of 2026-09-25,
xonforge/docs/decisions.md).

Each batch holds 5 defect canaries and 2 clean ones, drawn with a seed that the batch records, covering the defect kinds
on the batch's attributes where the registry allows, and shuffled in under opaque ids (blind.py). Per reviewer and
batch: the recall on the defect canaries and the false alarms on the clean ones, as exact fractions, with the canaries
missed and flagged. A reviewer caught a defect canary if one of the conflicts it reported matches the canary's defect
(matching.py); it raised a false alarm on a clean canary if it reported any conflict there. A batch is certifiable
only if the reviewer's recall is 4/5 or more, with no rounding; a reviewer that cannot certify its batch still has its
flags passed to humans.

A review canary is a JSON file in xonforge/canaries/review/, holding one canary or a list of them: ``id``, ``kind``
(``defect`` or ``clean``), ``text`` and ``source``, and for a defect canary ``defect`` (what it is), ``defect_kind``,
``attributes`` (XonForge's attribute keys the defect is on) and ``defect_sentences`` (its sentences, verbatim in the
text). Item 5: defect canaries are small synthetic documents and the real defects the L1 scans found; clean canaries
are L1's 60 consistent documents. No canary comes from, or goes into, a sealed or judged split.
"""
from __future__ import annotations

import json
import random
from fractions import Fraction
from pathlib import Path
from typing import Collection, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, model_validator

from .matching import found

FOLDER = Path(__file__).resolve().parents[1] / "canaries" / "review"
DEFECT_CANARIES = 5
CLEAN_CANARIES = 2
RECALL_MIN = Fraction(4, 5)
DEFECT_KINDS = ("superlative", "order_cycle", "same_different", "negation", "parity")


class ReviewCanary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    kind: Literal["defect", "clean"]
    text: str
    defect: str | None = None
    defect_kind: Literal["superlative", "order_cycle", "same_different", "negation", "parity"] | None = None
    attributes: tuple[str, ...] = ()
    defect_sentences: tuple[str, ...] = ()
    source: str = "synthetic"

    @model_validator(mode="after")
    def _described(self) -> ReviewCanary:
        described = (bool(self.defect), self.defect_kind is not None, bool(self.attributes),
                     bool(self.defect_sentences))
        if self.kind == "defect" and not all(described):
            raise ValueError(f"canary {self.id}: a defect canary says what its defect is, its kind, the attributes "
                             "it is on and its sentences")
        if self.kind == "clean" and any(described):
            raise ValueError(f"canary {self.id}: a clean one has no defect")
        missing = [s for s in self.defect_sentences if self.text.count(s) != 1]
        if missing:
            raise ValueError(f"canary {self.id}: each defect sentence occurs once in the text, verbatim; these do "
                             f"not: {' / '.join(missing)}")
        return self


class CanaryScore(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reviewer: str
    batch_id: str
    defects: int
    caught: int
    clean: int
    false_alarms: int
    missed: tuple[str, ...] = ()      # the defect canaries the reviewer missed
    alarms: tuple[str, ...] = ()      # the clean canaries it flagged

    @property
    def recall(self) -> Fraction | None:
        return Fraction(self.caught, self.defects) if self.defects else None

    @property
    def false_alarm_rate(self) -> Fraction | None:
        return Fraction(self.false_alarms, self.clean) if self.clean else None


def load(folder: str | Path | None = None) -> list[ReviewCanary]:
    folder = Path(folder) if folder is not None else FOLDER
    canaries = []
    for p in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        body = json.loads(p.read_text(encoding="utf-8"))
        canaries += [ReviewCanary.model_validate(c) for c in (body if isinstance(body, list) else [body])]
    ids = [c.id for c in canaries]
    if len(set(ids)) != len(ids):
        raise ValueError("each review canary has an id of its own")
    return canaries


def _by_kind(group: list[ReviewCanary], n: int) -> list[ReviewCanary]:
    """Up to n of the group, taking each defect kind in turn so that the kinds are covered before any repeats."""
    queues: dict[str, list[ReviewCanary]] = {}
    for c in group:
        queues.setdefault(c.defect_kind, []).append(c)
    out: list[ReviewCanary] = []
    while len(out) < n and any(queues.values()):
        for q in queues.values():
            if q and len(out) < n:
                out.append(q.pop(0))
    return out


def draw(pool: Sequence[ReviewCanary], attributes: Collection[str], seed: int) -> list[ReviewCanary]:
    """A batch's canaries, drawn with the seed: 5 defect canaries, first those on the batch's attributes, one of each
    defect kind in turn, then others the same way; and 2 clean canaries."""
    defects = sorted((c for c in pool if c.kind == "defect"), key=lambda c: c.id)
    clean = sorted((c for c in pool if c.kind == "clean"), key=lambda c: c.id)
    if len(defects) < DEFECT_CANARIES or len(clean) < CLEAN_CANARIES:
        raise ValueError(f"a batch holds {DEFECT_CANARIES} defect canaries and {CLEAN_CANARIES} clean ones, and the "
                         f"registry has {len(defects)} and {len(clean)}")
    rng = random.Random(f"xonforge:canaries:{seed}")
    relevant = [c for c in defects if set(c.attributes) & set(attributes)]
    others = [c for c in defects if c not in relevant]
    rng.shuffle(relevant)
    rng.shuffle(others)
    chosen = _by_kind(relevant, DEFECT_CANARIES)
    chosen += _by_kind(others, DEFECT_CANARIES - len(chosen))
    return chosen + rng.sample(clean, CLEAN_CANARIES)


def caught(canary: ReviewCanary, conflicts: Sequence[Sequence[str]]) -> bool:
    """``conflicts``: the statements of each conflict the reviewer reported on the canary. A defect canary is caught
    if one of them matches its defect; a clean canary is flagged if there is any."""
    if canary.kind == "clean":
        return bool(conflicts)
    return any(found(statements, canary.defect_sentences) for statements in conflicts)


def score(reviewer: str, batch_id: str, canaries: Sequence[ReviewCanary], flagged: Mapping[str, bool]) -> CanaryScore:
    """``flagged``: per canary id, whether the reviewer caught the canary's defect (a defect canary) or reported any
    conflict (a clean one). Every canary of the batch needs a judgement."""
    unjudged = [c.id for c in canaries if c.id not in flagged]
    if unjudged:
        raise ValueError(f"no judgement for the canaries {', '.join(unjudged)}")
    defects = [c for c in canaries if c.kind == "defect"]
    clean = [c for c in canaries if c.kind == "clean"]
    missed = tuple(c.id for c in defects if not flagged[c.id])
    alarms = tuple(c.id for c in clean if flagged[c.id])
    return CanaryScore(reviewer=reviewer, batch_id=batch_id, defects=len(defects), caught=len(defects) - len(missed),
                       clean=len(clean), false_alarms=len(alarms), missed=missed, alarms=alarms)


def certifiable(s: CanaryScore) -> bool:
    """Whether the reviewer may certify its batch clean: a recall of 4/5 or more on the batch's 5 defect canaries."""
    return s.defects >= DEFECT_CANARIES and s.recall is not None and s.recall >= RECALL_MIN
