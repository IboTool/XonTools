"""What a reviewed batch comes to (XONFORGE_SPEC.md §7.3, §7.4; the user's items 7 to 9 of 2026-09-25,
xonforge/docs/decisions.md): the reviewer's score on the batch's canaries, whether it may certify the batch clean, and
each document's flags for the human queue:

- every conflict it reported that does not match the document's plant (matching.py). A consistent twin and a trap
  variant have no plant, so every conflict reported on them is flagged;
- no usable reply: refused, truncated, or not of the reply's shape;
- a batch it may not certify (a recall below 4/5): its flags still go to humans, and so does every document of the
  batch, which it cannot certify clean.

A document is reviewed only when every reviewer of the run has reviewed it with every prompt of the run
(``missing``); a review that is missing is a flag too, so that no document is accepted without its review.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from xon_common.caller import Result
from xonforge.render.schema import Document
from xonforge.skeleton.schema import Skeleton
from xonforge.verify.structural import exempt_ids

from .blind import Batch
from .calibration import DEFECT_CANARIES, CanaryScore, ReviewCanary, caught, certifiable, score
from .matching import found


class BatchOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    batch_id: str
    reviewer: str
    prompt: str
    score: CanaryScore
    certifiable: bool
    flags: dict[str, tuple[str, ...]]      # per document of the batch, possibly none
    plants_found: tuple[str, ...] = ()     # the planted documents whose plant the reviewer reported


def plant_sentences(skeleton: Skeleton, document: Document) -> tuple[str, ...]:
    """A planted variant's plant, by its sentences: those of its planted facts and of its arity fact. The other
    variants have none."""
    if skeleton.variant != "planted":
        return ()
    return tuple(document.spans[f] for f in exempt_ids(skeleton) if f in document.spans)


def _conflicts(result: Result | Exception) -> list | None:
    if isinstance(result, Exception) or result.parsed is None:
        return None
    return list(result.parsed.conflicts)


def _quoted(conflict) -> str:
    return " / ".join(f'"{s}"' for s in conflict.statements) + f" ({conflict.explanation})"


def _uncertified(s: CanaryScore) -> str:
    if not s.defects:
        why = f"{s.reviewer}'s batch held no defect canary"
    elif s.defects < DEFECT_CANARIES:
        why = f"{s.reviewer}'s batch held {s.defects} defect canaries, fewer than {DEFECT_CANARIES}"
    else:
        why = f"{s.reviewer}'s recall on its batch's defect canaries was {s.caught}/{s.defects}, below 4/5"
    return f"{why}, so it cannot certify this document clean"


def outcome(batch: Batch, results: Mapping[str, Result | Exception], *, plants: Mapping[str, Sequence[str]],
            canaries: Mapping[str, ReviewCanary]) -> BatchOutcome:
    """``results``: blind.review's, by review id; ``plants``: each document's plant sentences (plant_sentences), by
    document id; ``canaries``: the batch's canaries, by id."""
    if batch.reviewer is None or batch.prompt is None:
        raise ValueError(f"batch {batch.batch_id} does not record its reviewer and prompt")
    missing = [i.review_id for i in batch.items if i.review_id not in results]
    if missing:
        raise ValueError(f"batch {batch.batch_id} has no result for {len(missing)} of its items")
    who = f"{batch.reviewer}, with the {batch.prompt} prompt,"
    flags: dict[str, tuple[str, ...]] = {}
    judged: dict[str, bool] = {}
    found_plant: list[str] = []
    for item in batch.items:
        conflicts = _conflicts(results[item.review_id])
        if item.kind == "canary":
            judged[item.ref] = conflicts is not None and caught(canaries[item.ref],
                                                                [c.statements for c in conflicts])
            continue
        if conflicts is None:
            reply = results[item.review_id]
            why = type(reply).__name__ if isinstance(reply, Exception) else "no parsed reply"
            flags[item.ref] = (f"{who} returned no usable reply ({why})",)
            continue
        plant = list(plants.get(item.ref, ()))
        matched = [c for c in conflicts if plant and found(c.statements, plant)]
        if matched:
            found_plant.append(item.ref)
        flags[item.ref] = tuple(f"{who} reported a conflict that is not the plant's: {_quoted(c)}"
                                for c in conflicts if c not in matched)
    s = score(batch.reviewer, batch.batch_id, [canaries[i.ref] for i in batch.items if i.kind == "canary"], judged)
    ok = certifiable(s)
    if not ok:
        flags = {d: f + (_uncertified(s),) for d, f in flags.items()}
    return BatchOutcome(batch_id=batch.batch_id, reviewer=batch.reviewer, prompt=batch.prompt, score=s,
                        certifiable=ok, flags=flags, plants_found=tuple(found_plant))


def missing(doc_ids: Sequence[str], outcomes: Sequence[BatchOutcome], reviewers: Sequence[str],
            prompts: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """Per document, the reviews it lacks: every reviewer of the run with every prompt of the run."""
    done = {(d, o.reviewer, o.prompt) for o in outcomes for d in o.flags}
    return {d: tuple(f"no review by {r} with the {p} prompt" for r in reviewers for p in prompts
                     if (d, r, p) not in done) for d in doc_ids}


def reviewer_flags(doc_ids: Sequence[str], outcomes: Sequence[BatchOutcome], reviewers: Sequence[str],
                   prompts: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """Per document, every flag of its reviews and every review it lacks: what queue.flagged takes."""
    lacking = missing(doc_ids, outcomes, reviewers, prompts)
    return {d: tuple(f for o in outcomes for f in o.flags.get(d, ())) + lacking[d] for d in doc_ids}
