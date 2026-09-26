"""Step 0 of A1 rev. 2.2 (XON_A1_REV2_2_PRECISION.md §7.1): why a planted relation that the L1 diagnostic counted as
not extracted correctly was missed, and a corrected matching rule, report-only.

A miss goes to the first class that fits:
1. scoring artifact: the extraction closes the planted cycle in the engine (``planted_cycle_closes``), although the
   diagnostic's matching rule (``evaluation.relations_extracted``) counted the relation as wrong;
2. not extracted: no entity relation comes from a claim matched to the planted sentence;
3. direction flip: a relation from such a claim has the planted kind and the planted entities, the other way round;
4. id mismatch: a relation from such a claim has the planted kind and entities that are the planted ones or variants
   of them (the planted name is a whole word of the id or of a mention), at least one only a variant;
5. wrong relation: anything else, a different kind or different entities.
The matching rule ignores attribute keys, so a relation under a variant attribute key counts as extracted; whether the
planted cycle closes shows those.

The corrected rule is the run of record's, except that a planted relation stated the other way round also counts when
the planted cycle closes: the mirror image of a cycle is a cycle. The run of record's reported figures stay as they
are.
"""
from __future__ import annotations

from itertools import product

from .entity_consistency import EntityGraph, canonical_key
from .evaluation import _is, matched_relations, relations_extracted, span_matches
from .schemas import ClaimList

CLASSES = ("scoring artifact", "not extracted", "direction flip", "id mismatch", "wrong relation")
CONTRADICTION_TYPES_OF = {"order_cycle": ("order_cycle",), "equality_break": ("different_within_class",),
                          "binary_parity": ("binary_parity",)}


def claims_matching(claims: ClaimList, sentence: str) -> set[int]:
    return {c.id for c in claims.claims if span_matches(c.span, sentence)}


def _field(contradiction, name: str):
    return contradiction[name] if isinstance(contradiction, dict) else getattr(contradiction, name)


def planted_cycle_reported(record: dict, claims: ClaimList, contradictions) -> bool:
    """Whether one of the engine's entity contradictions (dicts or objects with ``type`` and ``claim_ids``) is of the
    planted type and holds a claim matched to every planted sentence."""
    groups = [claims_matching(claims, rel["sentence"]) for rel in record["relations"]]
    return bool(groups) and any(_field(c, "type") in CONTRADICTION_TYPES_OF[record["cycle_type"]]
                                and all(g & set(_field(c, "claim_ids")) for g in groups) for c in contradictions)


def _one_cycle(edges) -> bool:
    succ = {}
    for r in edges:
        if r.a in succ:
            return False
        succ[r.a] = r.b
    if set(succ) != set(succ.values()):
        return False
    start = node = next(iter(succ))
    for n in range(1, len(edges) + 1):
        node = succ[node]
        if node == start:
            return n == len(edges)
    return False


def order_cycle_closes(relations: list[dict], claims: ClaimList, eg: EntityGraph) -> bool:
    """Whether one "greater" relation stated by a claim matched to each planted sentence, all on one attribute, chain
    round the planted entities, one way or the other (the planted cycle or its mirror image). The engine reports only
    the shortest contradiction on an attribute, so a cycle can close without being the one reported."""
    options = []
    for rel in relations:
        ids = claims_matching(claims, rel["sentence"])
        options.append([r for r in eg.relations if r.claim_id in ids and r.kind == "greater"
                        and ((_is(eg, r.a, rel["a"]) and _is(eg, r.b, rel["b"]))
                             or (_is(eg, r.a, rel["b"]) and _is(eg, r.b, rel["a"])))])
    return bool(options) and any(len({r.attribute for r in edges}) == 1 and _one_cycle(edges)
                                 for edges in product(*options))


def planted_cycle_closes(record: dict, claims: ClaimList, eg: EntityGraph, contradictions) -> bool:
    """An order cycle by ``order_cycle_closes``; the other cycle types, whose contradictions also depend on equality
    classes and the number of values, by the engine's report (``planted_cycle_reported``)."""
    if record["cycle_type"] == "order_cycle":
        return order_cycle_closes(record["relations"], claims, eg)
    return planted_cycle_reported(record, claims, contradictions)


def _resembles(eg: EntityGraph, entity: str, name: str) -> bool:
    key = canonical_key(name)
    return any(f"_{key}_" in f"_{w}_" for w in [entity, *(canonical_key(m) for m in eg.mentions.get(entity, ()))])


def classify_miss(rel: dict, claims: ClaimList, eg: EntityGraph, closes: bool) -> str:
    if closes:
        return "scoring artifact"
    ids = claims_matching(claims, rel["sentence"])
    stated = [r for r in eg.relations if r.claim_id in ids]
    if not stated:
        return "not extracted"
    kind = [r for r in stated if r.kind == rel["kind"]]
    if any(_is(eg, r.a, rel["b"]) and _is(eg, r.b, rel["a"]) for r in kind):
        return "direction flip"
    if any(_resembles(eg, r.a, x) and _resembles(eg, r.b, y) for r in kind for x, y in ((rel["a"], rel["b"]),
                                                                                         (rel["b"], rel["a"]))):
        return "id mismatch"
    return "wrong relation"


def misses(record: dict, claims: ClaimList, eg: EntityGraph, contradictions) -> list[dict]:
    """The planted relations of one document that the matching rule counts as not extracted: each with its class, the
    claims matched to its sentence, and the entity relations those claims state."""
    closes = planted_cycle_closes(record, claims, eg, contradictions)
    out = []
    for rel, found in zip(record["relations"], relations_extracted(record["relations"], claims, eg)):
        if not found:
            ids = claims_matching(claims, rel["sentence"])
            out.append({"relation": rel, "class": classify_miss(rel, claims, eg, closes), "claims": sorted(ids),
                        "stated": [r for r in eg.relations if r.claim_id in ids]})
    return out


def relations_extracted_corrected(record: dict, claims: ClaimList, eg: EntityGraph, contradictions) -> list[bool]:
    found = relations_extracted(record["relations"], claims, eg)
    if not planted_cycle_closes(record, claims, eg, contradictions):
        return found
    return [f or bool(matched_relations(rel, claims, eg)) for rel, f in zip(record["relations"], found)]
