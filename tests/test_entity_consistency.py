"""A1 entity-relation graph (XON_A1_CONSISTENCY.md §4.7, rev. 2.1) on hand-built entity graphs. Offline."""
import pytest

from xon.llm.baselines import pairwise_only
from xon.llm.claims import build_signed_graph
from xon.llm.consistency import CONFIDENCE_MIN, analyze
from xon.llm.entity_consistency import (build_entity_graph, eligible_relations, find_contradictions,
                                        normalize_relation)
from xon.llm.schemas import Attribute, Claim, Entity, EntityGraphSpec, EntityRelation, Relation

ORDER_CYCLE = [(0, "age", "greater", "ana", "ben"), (1, "age", "greater", "ben", "cy"),
               (2, "age", "greater", "cy", "ana")]
DIFFERENT_TRIANGLE = [(0, "team", "different", "ana", "ben"), (1, "team", "different", "ben", "cy"),
                      (2, "team", "different", "ana", "cy")]


def spec(relations, arity=None):
    """relations: (claim_id, attribute, kind, a, b[, confidence]); arity: attribute -> arity or list of arities."""
    rels = [EntityRelation(claim_id=c, attribute=att, kind=k, a=a, b=b, confidence=rest[0] if rest else 0.9)
            for c, att, k, a, b, *rest in relations]
    atts = [Attribute(key=key, arity=v, arity_span=f"{key} has {v} values.")
            for key, vs in (arity or {}).items() for v in ([vs] if isinstance(vs, str) else vs)]
    names = sorted({r.a for r in rels} | {r.b for r in rels})
    return EntityGraphSpec(entities=[Entity(id=e, mentions=[e.title()]) for e in names], attributes=atts,
                           relations=rels)


def found(relations, arity=None, n_claims=None):
    return find_contradictions(build_entity_graph(spec(relations, arity), n_claims))


def assert_closed_cycle(eg, c):
    """Consecutive entities (closing back to the first) are joined by the listed relations, in order."""
    assert len(c.entities) == len(c.relations) and len(set(c.entities)) == len(c.entities)
    for k, i in enumerate(c.relations):
        r = eg.relations[i]
        assert {r.a, r.b} == {c.entities[k], c.entities[(k + 1) % len(c.entities)]} or r.a == r.b


# ------------------------------------------------------------------------------------------ order
def test_an_order_three_cycle_is_a_contradiction():
    eg = build_entity_graph(spec(ORDER_CYCLE))
    [c] = find_contradictions(eg)
    assert (c.type, c.attribute, c.entities, c.relations, c.claim_ids) == \
        ("order_cycle", "age", ["ana", "ben", "cy"], [0, 1, 2], [0, 1, 2])
    assert_closed_cycle(eg, c)


def test_an_acyclic_order_is_not():
    assert found([(0, "age", "greater", "ana", "ben"), (1, "age", "greater", "ben", "cy"),
                  (2, "age", "greater", "ana", "cy")]) == []


@pytest.mark.parametrize("arity", ["binary", "multi", "unknown"])
def test_greater_between_equal_entities_is_a_contradiction(arity):
    [c] = found([(0, "height", "greater", "ana", "ben"), (1, "height", "same", "ben", "ana")], {"height": arity})
    assert c.type == "order_cycle" and c.entities == ["ana", "ben"] and c.relations == [0, 1]
    [c] = found([(0, "height", "greater", "ana", "ana")])
    assert c.type == "order_cycle" and c.entities == ["ana"]


def test_the_shortest_order_cycle_is_reported():
    four = [(0, "age", "greater", "a", "b"), (1, "age", "greater", "b", "c"), (2, "age", "greater", "c", "d"),
            (3, "age", "greater", "d", "a")]
    three = [(4, "age", "greater", "x", "y"), (5, "age", "greater", "y", "z"), (6, "age", "greater", "z", "x")]
    [c] = found(four + three)
    assert c.claim_ids == [4, 5, 6]
    got = found(four + [(r[0], "rank", *r[2:]) for r in three])
    assert [(c.attribute, len(c.relations)) for c in got] == [("age", 4), ("rank", 3)]


def test_order_cycles_run_through_equality():
    eg = build_entity_graph(spec([(0, "age", "greater", "ana", "ben"), (1, "age", "same", "ben", "cy"),
                                  (2, "age", "greater", "cy", "ana")]))
    [c] = find_contradictions(eg)
    assert c.type == "order_cycle" and sorted(c.relations) == [0, 1, 2]
    assert_closed_cycle(eg, c)


# ------------------------------------------------------------------------------------------ equality and arity
@pytest.mark.parametrize("arity", ["binary", "multi", "unknown", None])
def test_an_equality_break_is_a_contradiction_for_every_arity(arity):
    rels = [(0, "team", "same", "ana", "ben"), (1, "team", "same", "ben", "cy"), (2, "team", "different", "ana", "cy")]
    eg = build_entity_graph(spec(rels, {"team": arity} if arity else None))
    [c] = find_contradictions(eg)
    assert c.type == "different_within_class" and c.entities == ["ana", "ben", "cy"] and c.relations == [0, 1, 2]
    assert_closed_cycle(eg, c)


@pytest.mark.parametrize("arity, flagged", [("binary", True), ("multi", False), ("unknown", False), (None, False)])
def test_three_different_on_a_triangle_depends_on_arity(arity, flagged):
    eg = build_entity_graph(spec(DIFFERENT_TRIANGLE, {"team": arity} if arity else None))
    got = find_contradictions(eg)
    assert bool(got) == flagged
    if flagged:
        [c] = got
        assert c.type == "binary_parity" and sorted(c.relations) == [0, 1, 2] and c.claim_ids == [0, 1, 2]
        assert_closed_cycle(eg, c)


def test_binary_parity_runs_over_equality_classes():
    odd = [(0, "team", "different", "ana", "ben"), (1, "team", "same", "ben", "dan"),
           (2, "team", "different", "dan", "cy"), (3, "team", "different", "cy", "ana")]
    eg = build_entity_graph(spec(odd, {"team": "binary"}))
    [c] = find_contradictions(eg)
    assert c.type == "binary_parity" and sorted(c.relations) == [0, 1, 2, 3] and len(c.entities) == 4
    assert_closed_cycle(eg, c)
    square = [(0, "team", "different", "a", "b"), (1, "team", "different", "b", "c"),
              (2, "team", "different", "c", "d"), (3, "team", "different", "d", "a")]
    assert found(square, {"team": "binary"}) == []


def test_arity_is_binary_only_if_every_entry_says_so():
    eg = build_entity_graph(spec(DIFFERENT_TRIANGLE, {"team": ["binary", "multi"], "age": ["binary", "unknown"],
                                                      "side": ["binary", "binary"]}))
    assert eg.arity == {"team": "multi", "age": "unknown", "side": "binary"}
    assert eg.arity_span["team"] == "team has multi values." and eg.arity_of("colour") == "unknown"
    assert found(DIFFERENT_TRIANGLE, {"team": ["binary", "multi"]}) == []


# ------------------------------------------------------------------------------------------ direction
def test_younger_is_normalized_to_older():
    r = normalize_relation(EntityRelation(claim_id=0, attribute="Younger", kind="greater", a="Ben", b="Ana",
                                          confidence=0.9))
    assert (r.attribute, r.a, r.b) == ("age", "ana", "ben")
    r = normalize_relation(EntityRelation(claim_id=0, attribute="younger", kind="same", a="Ben", b="Ana",
                                          confidence=0.9))
    assert (r.attribute, r.a, r.b) == ("age", "ben", "ana")
    mixed = [(0, "younger", "greater", "ben", "ana"), (1, "age", "greater", "ben", "cy"),
             (2, "older", "greater", "cy", "ana")]
    [c] = found(mixed)
    assert c.attribute == "age" and c.claim_ids == [0, 1, 2]
    assert found(mixed[:2] + [(2, "younger", "greater", "cy", "ana")]) == []   # ana > ben > cy, ana > cy
    eg = build_entity_graph(spec(mixed, {"younger": "multi"}))
    assert eg.arity == {"age": "multi"}


# ------------------------------------------------------------------------------------------ localization, eligibility
def test_claims_and_confidence_of_a_contradiction():
    rels = [(4, "age", "greater", "ana", "ben", 0.9), (4, "age", "greater", "ben", "cy", 0.6),
            (7, "age", "greater", "cy", "ana", 0.8)]
    [c] = found(rels)
    assert c.claim_ids == [4, 7] and c.min_confidence == pytest.approx(0.6)


def test_relations_naming_no_claim_are_dropped():
    eg = build_entity_graph(spec(ORDER_CYCLE + [(9, "age", "greater", "dan", "ana")]), n_claims=3)
    assert eg.dropped == 1 and len(eg.relations) == 3


def test_verdict_uses_confident_relations_from_asserted_or_premise_claims():
    eg = build_entity_graph(spec(ORDER_CYCLE[:2] + [(2, "age", "greater", "cy", "ana", 0.3)]))
    assert eligible_relations(eg, ["asserted"] * 3, CONFIDENCE_MIN) == {0, 1}
    assert eligible_relations(build_entity_graph(spec(ORDER_CYCLE)), ["asserted", "premise", "quoted"],
                              CONFIDENCE_MIN) == {0, 1}
    sg = engine_graph(["asserted", "premise", "quoted"])
    rep = analyze(sg, build_entity_graph(spec(ORDER_CYCLE), 3))
    assert [c.type for c in rep.entity_contradictions] == ["order_cycle"]   # reported on all relations
    assert not rep.verdict_inconsistent and rep.verdict_entity_contradictions == []


def engine_graph(kinds):
    claims = [Claim(id=i, text=t, span=t, kind=k) for i, (t, k) in enumerate(zip(
        ["Ana is older than Ben.", "Ben is older than Cy.", "Cy is older than Ana."], kinds))]
    unrelated = [Relation(a=a, b=b, relation="unrelated", confidence=0.9, rationale="different people")
                 for a, b in ((0, 1), (0, 2), (1, 2))]
    return build_signed_graph(claims, unrelated)


def test_ana_ben_cy_is_an_entity_contradiction_the_pairwise_baseline_misses():
    sg = engine_graph(["asserted"] * 3)
    rep = analyze(sg, build_entity_graph(spec(ORDER_CYCLE), 3))
    assert rep.verdict_inconsistent and rep.verdict_clauses == ["entity"]
    [c] = rep.verdict_entity_contradictions
    assert c.type == "order_cycle" and c.claim_ids == [0, 1, 2]
    assert rep.balanced and rep.n_edges == 0 and pairwise_only(sg) == (False, [])


@pytest.mark.parametrize("arity, flagged", [("multi", False), ("binary", True)])
def test_three_teams_versus_two_teams(arity, flagged):
    sg = engine_graph(["asserted"] * 3)
    rep = analyze(sg, build_entity_graph(spec(DIFFERENT_TRIANGLE, {"team": arity}), 3))
    assert rep.verdict_inconsistent == flagged and rep.verdict_clauses == (["entity"] if flagged else [])
