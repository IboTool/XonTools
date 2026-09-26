"""The minimal consistency engine (XON_A1_MINIMAL_ENGINE.md): A1's verdict clauses (a) direct and (c) entity, with
A1's thresholds and claim-kind rules, on the claims, relations and entity relations A1 extracted for a document.
Not computed: claim-graph balance, lambda_min, clamped harmony, residuals, culprits, anchoring. Each reported
contradiction is its own localization: a direct contradiction names its two claims, an entity contradiction the
claims whose relations form it, with the attribute, the entities and the smallest confidence.

Standard library only, and no LLM calls: the module imports neither NumPy, SciPy, V1 nor ``xon.llm.client``.
Clause (c) is A1's own entity logic (``entity_consistency.py``, shared by both engines). Clause (a) reads the
relations the way A1 builds its signed claim graph (``claims.build_signed_graph``): a pair is unordered, the first
relation given for a pair is the one kept, and confidence is clipped to [0, 1] with NaN read as 0. Inputs are read
by attribute, so A1's schema objects and plain dataclasses both work.

Engine versions (XON_A1_REV2_2_PRECISION.md §2): under "2.2" the entity statements go through rev. 2.2's derivation
(``build_entity_graph_v22``), a "tension" relation is not a contradiction, and both clauses use the threshold the
caller passes (config.relation_threshold("minimal", "2.2"); this module cannot import the config).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .entity_consistency import (ASSERTING_KINDS, CONFIDENCE_MIN, EntityContradiction, EntityGraph,
                                 build_entity_graph, build_entity_graph_v22, eligible_relations, find_contradictions)

CLAUSES = ("direct", "entity")
VERSIONS = ("2.1", "2.2")


@dataclass
class MinimalReport:
    verdict_inconsistent: bool
    verdict_clauses: list[str]                          # subset of CLAUSES, in that order
    direct_contradictions: list[tuple[int, int]]        # claim id pairs
    entity_contradictions: list[EntityContradiction]
    unscored_pairs: int                                 # carried from A1's relation scoring


def _weight(confidence) -> float:
    c = float(confidence)
    return 0.0 if math.isnan(c) else min(max(c, 0.0), 1.0)


def direct_contradictions(claims, relations, threshold: float = CONFIDENCE_MIN) -> list[tuple[int, int]]:
    """Clause (a): the claim pairs joined by a contradicts relation with confidence >= threshold whose two claims are
    asserted or premises, in pair order. Claim ids must be 0..n-1 in order and a relation must join two distinct
    claims, as in A1."""
    claims = list(getattr(claims, "claims", claims))
    n = len(claims)
    if [c.id for c in claims] != list(range(n)):
        raise ValueError("claim ids must be 0..n-1 in order")
    first = {}
    for r in getattr(relations, "relations", relations):
        a, b = sorted((int(r.a), int(r.b)))
        if not 0 <= a < b < n:
            raise ValueError(f"relation ({r.a}, {r.b}) does not join two distinct claims")
        first.setdefault((a, b), r)
    kinds = [c.kind for c in claims]
    return [(a, b) for (a, b), r in sorted(first.items())
            if r.relation == "contradicts" and _weight(r.confidence) >= threshold
            and kinds[a] in ASSERTING_KINDS and kinds[b] in ASSERTING_KINDS]


def entity_contradictions(entities: EntityGraph | None, kinds: list[str],
                          threshold: float = CONFIDENCE_MIN) -> list[EntityContradiction]:
    """Clause (c): the contradictions among the entity relations with confidence >= threshold stated by asserted or
    premise claims (``kinds``: the claims' kinds by id)."""
    if entities is None:
        return []
    return find_contradictions(entities, eligible_relations(entities, kinds, threshold, ASSERTING_KINDS))


def analyze_minimal(claims, relations, entity_spec, *, unscored_pairs: int = 0, engine_version: str = "2.1",
                    threshold: float = CONFIDENCE_MIN) -> MinimalReport:
    """The minimal engine's report on one document: inconsistent iff clause (a) or clause (c) fires. ``entity_spec``
    is A1's extracted entity graph, or under "2.2" what its entity steps returned (development iteration 0's
    statements are read too; None: no entity relations);
    ``unscored_pairs`` is the number of requested pairs A1's relation scoring left without a relation."""
    if engine_version not in VERSIONS:
        raise ValueError(f"unknown engine version {engine_version!r}; expected one of {VERSIONS}")
    claims = list(getattr(claims, "claims", claims))
    direct = direct_contradictions(claims, relations, threshold)
    build = build_entity_graph_v22 if engine_version == "2.2" else build_entity_graph
    entities = None if entity_spec is None else build(entity_spec, n_claims=len(claims))
    entity = entity_contradictions(entities, [c.kind for c in claims], threshold)
    clauses = [c for c, found in zip(CLAUSES, (direct, entity)) if found]
    return MinimalReport(bool(clauses), clauses, direct, entity, int(unscored_pairs))


def minimal_report_to_dict(report: MinimalReport) -> dict:
    """JSON-ready form of a report."""
    d = asdict(report)
    d["direct_contradictions"] = [list(p) for p in report.direct_contradictions]
    return d
