"""The renderer's check (XONFORGE_SPEC.md §6): the structural checks (§7.1), then the scans (§7.2), whose problems are
quoted back to the next attempt; and ``finalize``, which records on a rendered document what was measured (§5.4) and
what each scan found, covered and was trusted for.

The scans leave the planted sentences out, so they run only on a rendering whose planted sentences are each one whole
sentence of the text; until then their results would mix planted and unplanted sentences, and the span problems
already ask for a new attempt.
"""
from __future__ import annotations

from xonforge.render.schema import Document, Rendering, RenderRules, ScanRecord, SpanEntry
from xonforge.skeleton.schema import Skeleton

from . import scans
from .canaries import ScanTrust
from .structural import measure, structural, whole


def check(skeleton: Skeleton, rendering: Rendering, rules: RenderRules) -> list[str]:
    """Every problem with the rendering, worded for the renderer; empty when it passes."""
    problems = structural(skeleton, rendering, rules)
    if whole(skeleton, rendering):
        problems += scans.problems(skeleton, scans.scan(skeleton, rendering))
    return problems


def finalize(skeleton: Skeleton, document: Document, trust: dict[str, ScanTrust]) -> Document:
    """The document with its measurements and scan records; unchanged if no attempt returned a text."""
    if document.text is None:
        return document
    rendering = Rendering(text=document.text, spans=[SpanEntry(fact=f, span=s) for f, s in document.spans.items()])
    hits = scans.scan(skeleton, rendering) if whole(skeleton, rendering) else {}
    records = tuple(ScanRecord(scan=s,
                               result=("not_applicable" if not scans.applies(s, skeleton)
                                       else "not_run" if s not in hits else "hits" if hits[s] else "clean"),
                               trusted=bool(trust.get(s) and trust[s].trusted),
                               uncovered=tuple(a for a in scans.relevant(s, skeleton) if not scans.covers(s, a)))
                    for s in scans.SCANS)
    return document.model_copy(update={"measured": measure(skeleton, rendering), "scans": records})
