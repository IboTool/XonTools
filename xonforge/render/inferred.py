"""Inferred facts (XONFORGE_SPEC.md §5.4; the user's item 3). An arithmetic, time or location conclusion is not a
sentence of its own. Its map entry names the verbatim spans it follows from and the solver's derivation. v0 facts
have no derivation, so their documents record none.
"""
from __future__ import annotations

from xonforge.skeleton.schema import Skeleton

from .schema import InferredSpan


def inferred_map(skeleton: Skeleton, spans: dict[str, str]) -> dict[str, InferredSpan]:
    """One entry per fact that carries a derivation and whose support spans are in ``spans``."""
    out = {}
    for fact in skeleton.facts:
        if not fact.derivation:
            continue
        support = tuple(spans[i] for i in fact.support if spans.get(i, "").strip())
        if not support:
            continue
        out[fact.id] = InferredSpan(mode="inferred", support_spans=support, derivation=fact.derivation)
    return out
