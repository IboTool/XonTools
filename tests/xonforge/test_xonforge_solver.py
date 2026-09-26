"""XonForge's solver (XONFORGE_SPEC.md §5.5, §13: "consistent twins satisfiable; planted variants unsatisfiable with
the exact minimal contradiction set"), on hand-built skeletons. Never calls an API."""
import pytest
from pydantic import ValidationError

from xonforge.skeleton.schema import Attribute, Base, Entity, Fact, Plant, Skeleton, Trap
from xonforge.solver import (Unsupported, check_base, check_skeleton, minimal_contradiction, naive_contradiction,
                             satisfiable)
from xonforge.solver.solver import NAIVE_READING

ATTRIBUTES = {"age": Attribute(key="age", kind="ordinal"), "height": Attribute(key="height", kind="ordinal"),
              "team": Attribute(key="team", kind="categorical")}
ENTITIES = tuple(Entity(id=e, name=e.upper(), pronoun="they") for e in "abcdefg")


def rel(fid, s, relation, o, attribute="age", kind="relation"):
    return Fact(id=fid, kind=kind, subject=s, attribute=attribute, relation=relation, object=o)


def val(fid, s, value, negated=False, attribute="team", kind="value"):
    return Fact(id=fid, kind=kind, subject=s, attribute=attribute, value=value, negated=negated)


def sat(*facts):
    return satisfiable(facts, ATTRIBUTES)


def skeleton(facts, plant=None, variant=None, **fields):
    return Skeleton(base_id="b", variant=variant or ("planted" if plant else "consistent"), genre="g",
                    entities=ENTITIES, attributes=tuple(ATTRIBUTES.values()), facts=tuple(facts),
                    plant=None if plant is None else Plant(type="order_cycle", facts=tuple(plant)), seed=1, **fields)


# ------------------------------------------------------------------------------------------ order
def test_an_order_cycle_cannot_hold_and_an_acyclic_order_can():
    assert not sat(rel("1", "a", "greater", "b"), rel("2", "b", "greater", "c"), rel("3", "c", "greater", "a"))
    assert sat(rel("1", "a", "greater", "b"), rel("2", "b", "greater", "c"), rel("3", "a", "greater", "c"))
    six = [rel(str(i), x, "greater", y) for i, (x, y) in enumerate(zip("abcdef", "bcdefa"))]
    assert not sat(*six) and sat(*six[:-1])


def test_an_order_within_an_equality_class_cannot_hold():
    assert not sat(rel("1", "a", "same", "b"), rel("2", "a", "greater", "b"))
    assert not sat(rel("1", "a", "greater", "b"), rel("2", "b", "same", "c"), rel("3", "c", "greater", "a"))
    assert not sat(rel("1", "a", "same", "b"), rel("2", "a", "different", "b"))


def test_facts_about_different_attributes_never_interact():
    assert sat(rel("1", "a", "greater", "b"), rel("2", "b", "greater", "c"), rel("3", "c", "greater", "a", "height"))
    assert sat(rel("1", "a", "same", "b", "team"), rel("2", "a", "different", "b", "height"))


# ------------------------------------------------------------------------------------------ equality
def test_an_equality_break_cannot_hold_whatever_the_number_of_values():
    assert not sat(rel("1", "a", "same", "b", "team"), rel("2", "b", "same", "c", "team"),
                   rel("3", "c", "different", "a", "team"))
    assert sat(rel("1", "a", "same", "b", "team"), rel("2", "b", "different", "c", "team"),
               rel("3", "c", "different", "a", "team"))


def test_three_differences_can_hold_when_no_number_of_values_is_stated():
    assert sat(rel("1", "a", "different", "b", "team"), rel("2", "b", "different", "c", "team"),
               rel("3", "c", "different", "a", "team"))


# ------------------------------------------------------------------------------------------ values
def test_a_claim_and_its_negation_cannot_both_hold():
    assert not sat(val("1", "a", "red"), val("2", "a", "red", negated=True))
    assert sat(val("1", "a", "red"), val("2", "a", "blue", negated=True))
    assert not sat(val("1", "a", "red", kind="premise"), val("2", "a", "red", negated=True))


def test_each_entity_has_one_value_and_equal_entities_share_it():
    assert not sat(val("1", "a", "red"), val("2", "a", "blue"))
    assert not sat(val("1", "a", "red"), val("2", "b", "red"), rel("3", "a", "different", "b", "team"))
    assert not sat(rel("1", "a", "same", "b", "team"), val("2", "a", "red"), val("3", "b", "red", negated=True))
    assert sat(val("1", "a", "red"), val("2", "b", "blue"), rel("3", "a", "different", "b", "team"))


# ------------------------------------------------------------------------------------------ stated numbers of values
def arity(fid, n, attribute="team"):
    return Fact(id=fid, kind="premise", subject=None, attribute=attribute, value=n)


def team(fid, s, relation, o):
    return rel(fid, s, relation, o, "team")


def ring(pattern):
    """Entities a, b, c, ... in a cycle, relation i "different" where pattern[i] is "d" and "same" where it is "s"."""
    names = "abcdefg"[:len(pattern)]
    return [team(str(i), x, "different" if p == "d" else "same", y)
            for i, (p, x, y) in enumerate(zip(pattern, names, names[1:] + names[:1]), 1)]


def test_an_odd_cycle_of_differences_cannot_hold_with_two_values_only():
    assert not sat(*ring("ddd"), arity("9", 2))
    assert sat(*ring("ddd")) and sat(*ring("ddd"), arity("9", 3))
    assert sat(*ring("dds"), arity("9", 2))                      # binary parity's twin: A != B, B != C, A = C


@pytest.mark.parametrize("pattern, holds", [("dddd", True), ("ddddd", False), ("ddds", False), ("dddss", False),
                                            ("dddds", True), ("dddddd", True), ("ddsdds", True)])
def test_with_two_values_a_cycle_holds_exactly_when_its_differences_are_even(pattern, holds):
    assert sat(*ring(pattern), arity("9", 2)) is holds
    assert sat(*ring(pattern))


def test_named_values_count_toward_the_stated_number():
    a_red, b_blue = val("1", "a", "red"), val("2", "b", "blue")
    assert sat(arity("9", 2), a_red, b_blue, team("3", "c", "different", "a"))
    assert not sat(arity("9", 2), a_red, b_blue, team("3", "c", "different", "a"), team("4", "c", "different", "b"))
    assert not sat(arity("9", 2), a_red, b_blue, val("3", "c", "green"))
    assert sat(arity("9", 3), a_red, b_blue, val("3", "c", "green"))
    apart = [team("3", "a", "different", "b"), team("4", "b", "different", "c")]
    assert not sat(arity("9", 2), a_red, *apart, val("5", "c", "blue"))
    assert sat(arity("9", 2), a_red, *apart, val("5", "c", "red"))


def test_two_numbers_of_values_for_one_attribute_cannot_both_hold():
    assert not sat(arity("8", 2), arity("9", 3))
    assert sat(arity("8", 2), arity("9", 2), *ring("dds"))
    assert sat(arity("8", 2), *ring("ddd")[:2], rel("5", "a", "different", "c", "age"))


def test_the_minimal_contradiction_of_a_parity_cycle_includes_the_stated_number():
    facts = [*ring("ddd"), rel("4", "a", "greater", "b"), arity("9", 2), team("5", "d", "same", "e")]
    assert minimal_contradiction(facts, ATTRIBUTES) == ("1", "2", "3", "9")


def test_a_negated_value_on_an_attribute_whose_number_of_values_is_stated_is_refused():
    with pytest.raises(Unsupported, match="not decided"):
        sat(arity("9", 2), val("1", "a", "red", negated=True))
    with pytest.raises(Unsupported, match="categorical attributes only"):
        sat(arity("9", 2, attribute="age"))


@pytest.mark.parametrize("attribute, fact, why", [
    (Attribute(key="team", kind="categorical"), Fact(id="1", kind="event", subject="a", attribute="team"), "role"),
    (Attribute(key="team", kind="categorical"), val("1", "a", "red").model_copy(update={"time": "March"}), "role"),
    (Attribute(key="team", kind="ordinal"), val("1", "a", "red"), "categorical attributes only"),
])
def test_what_the_solver_still_refuses_is_refused_not_guessed(attribute, fact, why):
    with pytest.raises(Unsupported, match=why):
        satisfiable([fact], {"team": attribute})


# ------------------------------------------------------------------------------------------ minimal sets
def test_the_minimal_contradiction_is_the_cycle_and_not_the_facts_around_it():
    facts = [rel("1", "a", "greater", "b"), rel("2", "d", "greater", "e"), rel("3", "b", "greater", "c"),
             rel("4", "a", "same", "d", "team"), rel("5", "c", "greater", "a")]
    assert minimal_contradiction(facts, ATTRIBUTES) == ("1", "3", "5")
    assert minimal_contradiction(facts[:4], ATTRIBUTES) is None


CYCLE = [rel("1", "a", "greater", "b"), rel("2", "b", "greater", "c"), rel("3", "c", "greater", "a")]


def test_a_planted_variant_passes_only_if_its_plant_is_its_only_contradiction():
    extra = [rel("4", "d", "greater", "e", "height")]
    assert check_skeleton(skeleton(CYCLE + extra, plant=["1", "2", "3"])) == []
    assert check_skeleton(skeleton(CYCLE + extra, plant=["1", "2", "4"])) == [
        "the plant's facts can all be true", "without the planted fact 4, the facts 1, 2, 3 still cannot all be true"]
    accidental = [rel("5", "d", "same", "e", "team"), rel("6", "d", "different", "e", "team")]
    assert check_skeleton(skeleton(CYCLE + accidental, plant=["1", "2", "3"])) == [
        f"without the planted fact {i}, the facts 5, 6 still cannot all be true" for i in "123"]
    assert check_skeleton(skeleton(CYCLE + extra, plant=["1", "2", "3", "4"])) == [
        "without the planted fact 4, the facts 1, 2, 3 still cannot all be true"]


def test_a_consistent_variant_passes_only_if_all_its_facts_can_hold():
    assert check_skeleton(skeleton(CYCLE[:2])) == []
    assert check_skeleton(skeleton(CYCLE)) == ["the consistent variant's facts 1, 2, 3 cannot all be true"]


def test_a_planted_variant_differs_from_its_twin_only_in_the_plant():
    facts = CYCLE[:2] + [rel("3", "a", "greater", "c"), rel("4", "d", "greater", "e", "height")]
    twin = skeleton(facts, twin_facts=("1", "2", "3"))
    planted = skeleton(CYCLE + [rel("4", "d", "greater", "e", "height")], plant=["1", "2", "3"])
    assert check_base(Base(base_id="b", consistent=twin, planted=(planted,))) == []
    moved = skeleton(CYCLE + [rel("4", "e", "greater", "d", "height")], plant=["1", "2", "3"])
    assert check_base(Base(base_id="b", consistent=twin, planted=(moved,))) == [
        "planted variant 1: differs from the consistent twin outside its plant, in facts 4"]
    bad_twin = skeleton(CYCLE + [rel("4", "d", "greater", "e", "height")], twin_facts=("1", "2", "3"))
    assert check_base(Base(base_id="b", consistent=bad_twin, planted=(planted,))) == [
        "consistent twin: the consistent variant's facts 1, 2, 3 cannot all be true"]


def test_a_twin_records_its_counterparts_of_the_plant_s_facts():
    planted = skeleton(CYCLE + [rel("4", "d", "greater", "e", "height")], plant=["1", "2", "3"])
    facts = CYCLE[:2] + [rel("3", "a", "greater", "c"), rel("4", "d", "greater", "e", "height")]
    assert check_base(Base(base_id="b", consistent=skeleton(facts), planted=(planted,))) == [
        "consistent twin: its twin_facts are none, and the plants' facts 1, 2, 3"]
    assert check_base(Base(base_id="b", consistent=skeleton(facts, twin_facts=("1", "2")), planted=(planted,))) == [
        "consistent twin: its twin_facts are 1, 2, and the plants' facts 1, 2, 3"]
    with pytest.raises(ValidationError, match="only a consistent twin has twin_facts"):
        skeleton(CYCLE, plant=["1", "2", "3"], twin_facts=("1",))
    with pytest.raises(ValidationError, match="distinct facts of the skeleton"):
        skeleton(facts, twin_facts=("1", "9"))
    with pytest.raises(ValidationError, match="apart from the twin's facts"):
        parity(ring("dds"), twin_facts=("1", "2", "9"))


PARITY_ATTRIBUTES = (Attribute(key="age", kind="ordinal"), Attribute(key="team", kind="categorical", arity=2))


def parity(facts, plant=None, arity_fact="9", **fields):
    return Skeleton(base_id="b", variant="planted" if plant else "consistent", genre="g", entities=ENTITIES,
                    attributes=PARITY_ATTRIBUTES, facts=(*facts, arity("9", 2)), arity_fact=arity_fact,
                    plant=None if plant is None else Plant(type="binary_parity", facts=tuple(plant)), seed=1, **fields)


def test_a_parity_plant_needs_its_arity_fact_and_every_planted_fact():
    assert check_skeleton(parity(ring("ddd"), plant=["1", "2", "3"])) == []
    assert check_skeleton(parity(ring("dds"))) == []
    assert check_skeleton(parity(ring("ddd"), plant=["1", "2", "3"], arity_fact=None)) == [
        "the plant's facts can all be true"]
    assert check_skeleton(parity(ring("ssd"), plant=["1", "2", "3"])) == [
        "without the arity fact 9, the facts 1, 2, 3 still cannot all be true"]
    assert check_skeleton(parity(ring("ddd") + [team("4", "d", "different", "e")], plant=["1", "2", "4"])) == [
        "the plant's facts with the arity fact can all be true",
        "without the planted fact 4, the facts 1, 2, 3, 9 still cannot all be true"]


def test_a_parity_twin_shares_the_arity_fact_and_differs_only_in_the_plant():
    base = Base(base_id="b", consistent=parity(ring("dds"), twin_facts=("1", "2", "3")),
                planted=(parity(ring("ddd"), plant=["1", "2", "3"]),))
    assert check_base(base) == []
    with pytest.raises(ValidationError, match="arity fact and premise status"):
        Base(base_id="b", consistent=parity(ring("dds"), arity_fact=None),
             planted=(parity(ring("ddd"), plant=["1", "2", "3"]),))


NAIVE = {"reading": NAIVE_READING, "contradiction": ["1", "2", "3"]}


def trap(facts, *, values=3, trap_facts=("1", "2", "3", "9"), naive=NAIVE):
    """binary parity's arity_control trap variant (the user's item 20): the facts, and fact 9 stating the number of
    values of team, three unless ``values`` says otherwise."""
    attributes = (Attribute(key="age", kind="ordinal"), Attribute(key="team", kind="categorical", arity=values))
    return Skeleton(base_id="b", variant="trap_only", genre="g", entities=ENTITIES, attributes=attributes,
                    facts=(*facts, arity("9", values)), arity_fact="9", seed=1,
                    traps=(Trap(type="arity_control", facts=trap_facts, naive=naive),))


def test_an_arity_control_trap_holds_read_correctly_and_its_facts_are_a_naive_reading_s_only_contradiction():
    good = trap(ring("ddd"))
    assert check_skeleton(good) == [] and satisfiable(good.facts, {a.key: a for a in good.attributes})
    assert naive_contradiction(good, good.traps[0]) == ("1", "2", "3")
    assert check_skeleton(trap(ring("ddd"), naive={"reading": NAIVE_READING, "contradiction": ["1", "2"]})) == [
        "the arity_control trap: the naive reading (the attribute has two values) flags 1, 2, 3, and the trap "
        "records 1, 2"]
    assert check_skeleton(trap(ring("ddd"), naive={})) == [
        "the arity_control trap: the naive reading (the attribute has two values) flags 1, 2, 3, and the trap "
        "records nothing"]
    even = trap(ring("dddd"), trap_facts=("1", "2", "3", "4", "9"), naive={})
    assert check_skeleton(even) == ["the arity_control trap: a naive reading finds no contradiction",
                                    "the arity_control trap's naive reading: the trap's facts with the arity fact "
                                    "can all be true"]
    accidental = trap(ring("ddd") + [team("4", "d", "same", "e"), team("5", "d", "different", "e")])
    problems = check_skeleton(accidental)
    assert problems[0] == "read correctly, the trap variant's facts 4, 5 cannot all be true"
    assert "the arity_control trap's naive reading: without the planted fact 1, the facts 4, 5 still cannot all be " \
           "true" in problems


def test_a_trap_variant_differs_from_its_planted_variant_only_in_the_arity_fact():
    twin, planted = parity(ring("dds"), twin_facts=("1", "2", "3")), parity(ring("ddd"), plant=["1", "2", "3"])
    assert check_base(Base(base_id="b", consistent=twin, planted=(planted,), trap_only=(trap(ring("ddd")),))) == []
    moved = trap(ring("ddd") + [rel("4", "d", "greater", "e")])
    assert check_base(Base(base_id="b", consistent=twin, planted=(planted,), trap_only=(moved,))) == [
        "trap variant 1: differs from its planted variant outside the arity fact, in facts 4"]
    elsewhere = trap(ring("ddd") + [team("4", "d", "different", "e")], trap_facts=("1", "2", "4", "9"))
    assert "trap variant 1: the arity_control trap's facts are no planted variant's plant" in check_base(
        Base(base_id="b", consistent=twin, planted=(planted,), trap_only=(elsewhere,)))
    wider = trap(ring("ddd")).model_copy(update={"attributes": (Attribute(key="age", kind="ordinal", unit="years"),
                                                                Attribute(key="team", kind="categorical", arity=3))})
    with pytest.raises(ValidationError, match="share the base's id, seed, genre, entities, attributes"):
        Base(base_id="b", consistent=twin, planted=(planted,), trap_only=(wider,))


def test_an_unknown_trap_is_refused_and_a_trap_belongs_on_a_trap_only_variant():
    trap_only = Skeleton(base_id="b", variant="trap_only", genre="g", entities=ENTITIES,
                         attributes=tuple(ATTRIBUTES.values()), facts=tuple(CYCLE[:2]),
                         traps=(Trap(type="not_a_trap", facts=("1",)),), seed=1)
    with pytest.raises(Unsupported, match="not_a_trap"):
        check_skeleton(trap_only)
    in_planted = skeleton(CYCLE, plant=["1", "2", "3"]).model_copy(
        update={"traps": (Trap(type="arity_control", facts=("1",)),)})
    with pytest.raises(Unsupported, match="trap-only"):
        check_skeleton(in_planted)


# ------------------------------------------------------------------------------------------ the schema
@pytest.mark.parametrize("fields, message", [
    ({"kind": "relation", "relation": "greater"}, "needs an object"),
    ({"kind": "value", "relation": "same", "object": "b"}, "has no relation"),
    ({"kind": "value"}, "names its value"),
    ({"kind": "relation", "relation": "same", "object": "a"}, "two different entities"),
    ({"kind": "relation", "relation": "same", "object": "b", "negated": True}, "not negated"),
])
def test_a_fact_has_the_shape_of_its_kind(fields, message):
    with pytest.raises(ValidationError, match=message):
        Fact(id="1", subject="a", attribute="age", **fields)


@pytest.mark.parametrize("fields", [{"kind": "value", "value": 2}, {"kind": "premise", "value": 1},
                                    {"kind": "premise", "value": "two"}, {"kind": "premise", "value": 2.0},
                                    {"kind": "premise", "value": True},
                                    {"kind": "premise", "value": 2, "negated": True}])
def test_only_a_premise_stating_a_number_of_values_has_no_subject(fields):
    with pytest.raises(ValidationError, match="has no subject"):
        Fact(id="1", subject=None, attribute="team", **fields)
    assert arity("1", 2).states_arity and not val("1", "a", "red").states_arity


@pytest.mark.parametrize("attributes, facts, fields, message", [
    (PARITY_ATTRIBUTES, [arity("9", 2, attribute="age")], {}, "states the number of values of a categorical"),
    ((Attribute(key="team", kind="categorical", arity=3),), [arity("9", 2)], {}, "the attribute's arity repeats it"),
    (PARITY_ATTRIBUTES, [arity("8", 2), arity("9", 2)], {}, "at most one fact states the number of values of team"),
    (PARITY_ATTRIBUTES, [team("1", "a", "same", "b")], {}, "has an arity only when a fact states it"),
    (PARITY_ATTRIBUTES, [arity("9", 2), team("1", "a", "same", "b")], {"arity_fact": "1"}, "arity_fact names a fact"),
    (PARITY_ATTRIBUTES, [arity("9", 2), *ring("ddd")],
     {"arity_fact": "9", "variant": "planted", "plant": Plant(type="binary_parity", facts=("1", "2", "3", "9"))},
     "recorded apart from the plant's facts"),
])
def test_a_stated_number_of_values_is_recorded_once_and_agrees_with_its_attribute(attributes, facts, fields, message):
    with pytest.raises(ValidationError, match=message):
        Skeleton(**{"base_id": "b", "variant": "consistent", "genre": "g", "entities": ENTITIES,
                    "attributes": attributes, "facts": tuple(facts), "seed": 1, **fields})


@pytest.mark.parametrize("facts, plant, variant, message", [
    ([rel("1", "a", "greater", "z")], None, "consistent", "names an entity"),
    ([rel("1", "a", "greater", "b", "weight")], None, "consistent", "names an attribute"),
    ([rel("1", "a", "greater", "b", "team")], None, "consistent", "orders a non-ordinal"),
    ([rel("1", "a", "greater", "b"), rel("1", "b", "greater", "c")], None, "consistent", "fact ids are unique"),
    (CYCLE, None, "planted", "only a planted variant, has a plant"),
    (CYCLE, ["1", "9"], "planted", "lists distinct facts"),
])
def test_a_skeleton_refers_only_to_what_it_has(facts, plant, variant, message):
    with pytest.raises(ValidationError, match=message):
        Skeleton(base_id="b", variant=variant, genre="g", entities=ENTITIES, attributes=tuple(ATTRIBUTES.values()),
                 facts=tuple(facts), plant=None if plant is None else Plant(type="order_cycle", facts=tuple(plant)),
                 seed=1)


def test_a_base_keeps_variants_of_one_world_together():
    twin, planted = skeleton(CYCLE[:2]), skeleton(CYCLE, plant=["1", "2", "3"])
    with pytest.raises(ValidationError, match="share the base's id, seed, genre, entities, attributes"):
        Base(base_id="b", consistent=twin, planted=(planted.model_copy(update={"genre": "other"}),))
    with pytest.raises(ValidationError, match="arity fact and premise status"):
        Base(base_id="b", consistent=twin, planted=(planted.model_copy(update={"premise_status": "premise"}),))
    with pytest.raises(ValidationError, match="at least one planted variant"):
        Base(base_id="b", consistent=twin, planted=())
    assert skeleton(CYCLE).digest() == skeleton(CYCLE).digest() != skeleton(CYCLE[:2]).digest()
