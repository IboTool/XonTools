"""Acceptance (XONFORGE_SPEC.md §8). A document is accepted when its skeleton passes the solver, its rendering passes
the structural checks and the scans, a human accepted it if it was queued for review, and its rendering kept to the
retry cap. The solver and the checks are run again here, on the stored skeleton and rendering, rather than read from
the record. A scan passes when it found nothing and its clean results are trusted, having caught its canaries
(§7.2). A base is accepted when all its variants are: consistent twins, planted variants and trap variants are kept
together (§8). A document is accepted only into a corpus of its own mode (xonforge/modes.py): a pipeline-test document
is excluded from any corpus of record, and a pipeline test takes only its own documents.

A planted variant is derived from its consistent twin's document, and a trap variant from its planted variant's (the
user's item 2 of 2026-09-25, xonforge/docs/decisions.md): its acceptance takes that document too, and checks that the
text is the same outside the re-rendered sentences. A document one of whose scans has no pattern for one of its
attributes waits, never accepted, with a reason that says so (fail closed, the user's item 6). Acceptance never
imports the engine diagnostics or reads their output (§7.5), which tests/xonforge/test_xonforge_corpus.py checks.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from xonforge import modes
from xonforge.render.renderer import derivation_problems, doc_id
from xonforge.render.schema import Document, Rendering, SpanEntry
from xonforge.review.decisions import Entry
from xonforge.skeleton.schema import Base, Skeleton
from xonforge.solver.solver import Unsupported, check_skeleton
from xonforge.verify import scans
from xonforge.verify.canaries import ScanTrust
from xonforge.verify.checks import check
from xonforge.verify.structural import whole

RETRY_CAP = 5    # §5.4's constant


class Verdict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str                            # a document's id, or a base's
    accepted: bool
    reasons: tuple[str, ...] = ()      # why it is not accepted


def latest_decisions(entries: Sequence[Entry], run: str) -> dict[str, str]:
    """Each document's latest human decision in the run, from the decision log."""
    return {e.doc_id: e.decision for e in entries if e.kind == "decision" and e.run == run}


def accept(skeleton: Skeleton, document: Document, *, mode: str, trust: Mapping[str, ScanTrust], queued: bool,
           decision: str | None = None, source: Document | None = None) -> Verdict:
    """``mode``: the mode of the corpus the document would enter; ``queued``: whether the document went to the human
    review queue; ``decision``: a human's latest decision on it, if any; ``source``: for a derived variant, the
    document it was derived from."""
    modes.check(mode)
    reasons = []
    if document.mode != mode:
        reasons.append("a pipeline-test document is excluded from any corpus of record"
                       if document.mode == modes.PIPELINE_TEST else
                       "a document made for a corpus of record is not accepted into a pipeline test")
    if document.doc_id != doc_id(skeleton) or document.skeleton_digest != skeleton.digest():
        reasons.append("the document does not render this skeleton")
    try:
        reasons += [f"the solver: {p}" for p in check_skeleton(skeleton)]
    except Unsupported as exc:
        reasons.append(f"the solver: {exc}")
    reasons += [f"the derivation: {p}" for p in derivation_problems(skeleton, document, source)]
    if document.status != "rendered" or document.text is None:
        reasons.append("the rendering did not pass its checks")
    else:
        rendering = Rendering(text=document.text,
                              spans=[SpanEntry(fact=f, span=s) for f, s in document.spans.items()])
        reasons += [f"a check fails: {p}" for p in check(skeleton, rendering, document.rules)]
        if whole(skeleton, rendering):
            for s in scans.SCANS:
                if not scans.applies(s, skeleton):
                    continue
                if not (trust.get(s) and trust[s].trusted):
                    reasons.append(f"the {s} scan's clean result is not trusted: it has not caught every canary "
                                   "registered for it, or none is registered")
                uncovered = [a for a in scans.relevant(s, skeleton) if not scans.covers(s, a)]
                if uncovered:
                    reasons.append(f"waits for a scan pattern: the {s} scan has no pattern for "
                                   f"{', '.join(uncovered)}, and a document is not accepted until it has")
    if len(document.attempts) > min(document.rules.retry_cap, RETRY_CAP):
        reasons.append(f"the rendering took {len(document.attempts)} attempts, more than the retry cap")
    if queued and decision != "accept":
        reasons.append("queued for human review and not accepted by a human"
                       + (f" (the decision: {decision})" if decision else ""))
    return Verdict(id=document.doc_id, accepted=not reasons, reasons=tuple(reasons))


def accept_base(base: Base, verdicts: Mapping[str, Verdict]) -> Verdict:
    """A base is accepted when every one of its variants is."""
    variants = [base.consistent, *base.planted, *base.trap_only]
    reasons = []
    for v in variants:
        verdict = verdicts.get(doc_id(v))
        if verdict is None:
            reasons.append(f"{doc_id(v)} has no verdict")
        elif not verdict.accepted:
            reasons.append(f"{doc_id(v)} is not accepted")
    return Verdict(id=base.base_id, accepted=not reasons, reasons=tuple(reasons))
