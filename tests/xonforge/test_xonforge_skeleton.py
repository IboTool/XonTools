"""XonForge's v0 skeleton generators (XONFORGE_SPEC.md §5.1-5.2, §5.4; §14, step 2, with the user's step 2 decisions
in CHANGELOG_EXPERIMENTS.md and those of 2026-09-25 in xonforge/docs/decisions.md), checked by the solver, and
`python -m xonforge skeletons`. Never calls an API."""
import itertools
import random

import pytest

from xonforge.cli import main
from xonforge.skeleton.catalog import VALUES
from xonforge.skeleton.generators import PLANT_TYPES, Knobs, feasible, generate
from xonforge.solver import check_base, satisfiable

CYCLES = ["order_cycle", "equality_break", "binary_parity"]
KNOBS = [Knobs(), Knobs(cycle_length=4), Knobs(cycle_length=5, attributes=3, distractors=1),
         Knobs(cycle_length=3, entities=12, distractors=2), Knobs(cycle_length=6, entities=12, attributes=8,
                                                                  distractors=3),
         Knobs(cycle_length=4, entities=10, attributes=3, distractors=2, same_attribute_distractors=True),
         Knobs(cycle_length=5, entities=7, attributes=2, distractors=1, same_attribute_distractors=True)]
NEGATION_KNOBS = [Knobs(), Knobs(entities=3, distractors=1), Knobs(entities=6, attributes=3, distractors=3),
                  Knobs(entities=5, attributes=4, distractors=2, same_attribute_distractors=True)]
CASES = [(t, k) for t in CYCLES for k in KNOBS] + [("direct_negation", k) for k in NEGATION_KNOBS]


def _id(case):
    t, k = case
    return (f"{t}-k{k.cycle_length}-n{k.entities}-a{k.attributes}-d{k.distractors}"
            f"{'-same' if k.same_attribute_distractors else ''}")


def test_v0_builds_all_four_of_its_plant_types():
    assert PLANT_TYPES == ("order_cycle", "equality_break", "binary_parity", "direct_negation")
    with pytest.raises(ValueError, match="v0's plant types"):
        generate("no_such_plant", seed=1, genre="g")
    with pytest.raises(ValueError, match="genre"):
        generate("order_cycle", seed=1, genre="")


@pytest.mark.parametrize("case", CASES, ids=[_id(c) for c in CASES])
def test_every_base_passes_the_solver_and_its_twin_differs_in_one_planted_fact(case):
    plant_type, knobs = case
    for seed in range(1, 41):
        base = generate(plant_type, seed=seed, genre="g", knobs=knobs, premise_share=0.5)
        assert check_base(base) == [], (base.base_id, check_base(base))
        twin, planted = base.consistent, base.planted[0]
        plant, params = planted.plant, planted.plant.params
        k = 2 if plant_type == "direct_negation" else knobs.cycle_length
        n = knobs.entities or (1 if plant_type == "direct_negation" else k)
        assert plant.type == plant_type and len(plant.facts) == k and isinstance(params["twin_seed"], int)
        differs = [f.id for f, g in zip(twin.facts, planted.facts) if f != g]
        assert differs == params["differs_from_twin"] and len(differs) == 1 and differs[0] in plant.facts
        assert twin.twin_facts == plant.facts and planted.twin_facts == () and base.trap_only == ()
        assert twin.arity_fact == planted.arity_fact and twin.premise_status == planted.premise_status
        extra = [f for f in planted.facts if f.attribute == params["attribute"] and f.id not in plant.facts
                 and f.id != planted.arity_fact]
        assert not extra or knobs.same_attribute_distractors
        assert all({f.subject, f.object}.isdisjoint(params["entities"]) for f in extra)
        assert len(planted.facts) == k * (1 + knobs.distractors) + (planted.arity_fact is not None)
        assert len(planted.entities) == n and len(planted.attributes) == knobs.attributes
        assert {e.id for e in planted.entities} == {x for f in planted.facts for x in (f.subject, f.object) if x}
        assert planted.difficulty == twin.difficulty == {
            "cycle_length": k, "entities": n, "attributes": knobs.attributes,
            "distractor_density": knobs.distractors, "same_attribute_distractors": knobs.same_attribute_distractors}
        kinds = {a.key: a.kind for a in planted.attributes}
        assert kinds[params["attribute"]] == ("ordinal" if plant_type == "order_cycle" else "categorical")
        assert (planted.arity_fact is not None) == (plant_type == "binary_parity")
        assert (planted.premise_status is not None) == (plant_type == "direct_negation")
        if plant_type in ("order_cycle", "equality_break"):
            relations = sorted(f.relation for f in planted.facts if f.id in plant.facts)
            twin_relations = sorted(f.relation for f in twin.facts if f.id in plant.facts)
            if plant_type == "order_cycle":
                assert relations == twin_relations == ["greater"] * k
            else:
                assert relations == ["different"] + ["same"] * (k - 1)
                assert twin_relations == ["different"] * 2 + ["same"] * (k - 2)


@pytest.mark.parametrize("knobs", KNOBS, ids=[_id(("binary_parity", k)) for k in KNOBS])
def test_binary_parity_needs_its_arity_fact_and_its_twin_keeps_two_values(knobs):
    for seed in range(1, 41):
        base = generate("binary_parity", seed=seed, genre="g", knobs=knobs)
        twin, planted = base.consistent, base.planted[0]
        plant, params, k = planted.plant, planted.plant.params, knobs.cycle_length
        facts = {f.id: f for f in planted.facts}
        stated = facts[planted.arity_fact]
        assert (stated.kind, stated.subject, stated.attribute, stated.value) == \
            ("premise", None, params["attribute"], 2)
        assert planted.arity_fact not in plant.facts and stated in twin.facts
        assert next(a for a in planted.attributes if a.key == params["attribute"]).arity == 2
        d = params["differences"]
        assert d % 2 == 1 and 3 <= d <= k
        assert sorted(facts[f].relation for f in plant.facts) == ["different"] * d + ["same"] * (k - d)
        twin_facts = {f.id: f for f in twin.facts}
        assert sorted(twin_facts[f].relation for f in plant.facts) == ["different"] * (d - 1) + ["same"] * (k - d + 1)
        (changed,) = params["differs_from_twin"]
        assert (facts[changed].relation, twin_facts[changed].relation) == ("different", "same")
        attributes = {a.key: a for a in planted.attributes}
        assert satisfiable([facts[f] for f in plant.facts], attributes)
        assert not satisfiable([facts[f] for f in (*plant.facts, planted.arity_fact)], attributes)


@pytest.mark.parametrize("knobs", KNOBS, ids=[_id(("binary_parity", k)) for k in KNOBS])
def test_binary_parity_s_arity_control_trap_states_three_values_and_fools_a_naive_reading(knobs):
    for seed in range(1, 21):
        base = generate("binary_parity", seed=seed, genre="g", knobs=knobs, traps=("arity_control",))
        assert check_base(base) == [], (base.base_id, check_base(base))
        planted, (variant,) = base.planted[0], base.trap_only
        (trap,) = variant.traps
        assert trap.type == "arity_control" and trap.facts == (*planted.plant.facts, planted.arity_fact)
        assert trap.naive["reading"] == "the attribute has two values"
        assert sorted(trap.naive["contradiction"]) == sorted(planted.plant.facts)
        assert [f.id for f, g in zip(planted.facts, variant.facts) if f != g] == [planted.arity_fact]
        assert next(f for f in variant.facts if f.id == variant.arity_fact).value == 3
        attributes = {a.key: a for a in variant.attributes}
        assert attributes[planted.plant.params["attribute"]].arity == 3 and satisfiable(variant.facts, attributes)
        plain = generate("binary_parity", seed=seed, genre="g", knobs=knobs)
        assert plain.trap_only == () and plain.planted[0].facts == planted.facts and plain.base_id != base.base_id


def test_v0_s_one_trap_partners_binary_parity_only():
    with pytest.raises(ValueError, match="direct_negation's partner, not binary_parity's"):
        generate("binary_parity", seed=1, genre="g", traps=("quoted_speech",))
    with pytest.raises(ValueError, match="binary_parity's partner, not order_cycle's"):
        generate("order_cycle", seed=1, genre="g", traps=("arity_control",))
    with pytest.raises(ValueError, match="asked for once"):
        generate("binary_parity", seed=1, genre="g", traps=("arity_control", "arity_control"))


def test_a_base_records_the_level_its_knobs_were_drawn_for():
    base, plain = generate("order_cycle", seed=1, genre="g", level=2), generate("order_cycle", seed=1, genre="g")
    assert base.consistent.difficulty["level"] == base.planted[0].difficulty["level"] == 2
    assert "level" not in plain.planted[0].difficulty and base.base_id != plain.base_id
    assert base.planted[0].facts == plain.planted[0].facts
    for bad in (0, 4, True, "2"):
        with pytest.raises(ValueError, match="levels are 1, 2 and 3"):
            generate("order_cycle", seed=1, genre="g", level=bad)


def test_feasible_says_exactly_which_knobs_the_generator_can_build():
    grid = itertools.product(PLANT_TYPES, (3, 4, 6), (None, 4, 7, 12), (2, 3, 8), range(4), (False, True))
    seen = set()
    for plant_type, k, n, a, d, same in grid:
        try:
            knobs = Knobs(cycle_length=k, entities=n, attributes=a, distractors=d, same_attribute_distractors=same)
        except ValueError:
            continue
        try:
            generate(plant_type, seed=1, genre="g", knobs=knobs, premise_share=0.5)
            built = True
        except ValueError:
            built = False
        assert feasible(plant_type, knobs) is built, (plant_type, knobs)
        seen.add(built)
    assert seen == {True, False}


@pytest.mark.parametrize("knobs", NEGATION_KNOBS, ids=[_id(("direct_negation", k)) for k in NEGATION_KNOBS])
def test_direct_negation_s_twin_changes_only_the_negated_value(knobs):
    for seed in range(1, 41):
        base = generate("direct_negation", seed=seed, genre="g", knobs=knobs, premise_share=0.5)
        twin, planted = base.consistent, base.planted[0]
        params = planted.plant.params
        assert planted.plant.facts == (params["negated_claim"], params["negation"])
        assert params["differs_from_twin"] == [params["negation"]]
        facts, twin_facts = {f.id: f for f in planted.facts}, {f.id: f for f in twin.facts}
        claim, negation, twin_negation = facts[params["negated_claim"]], facts[params["negation"]], \
            twin_facts[params["negation"]]
        assert claim == twin_facts[params["negated_claim"]] and not claim.negated
        assert claim.kind == ("premise" if planted.premise_status == "premise" else "value")
        assert claim.subject == params["entities"][0] and claim.value in VALUES[params["attribute"]]
        assert negation.model_dump(exclude={"value"}) == twin_negation.model_dump(exclude={"value"})
        assert (negation.kind, negation.negated, negation.value) == ("value", True, claim.value)
        assert twin_negation.value != claim.value and twin_negation.value in VALUES[params["attribute"]]
        assert [f.id for f in planted.facts] == [f.id for f in twin.facts]


def test_the_recorded_twin_seed_reproduces_what_the_twin_changes():
    for seed in range(1, 21):
        for plant_type in PLANT_TYPES:
            base = generate(plant_type, seed=seed, genre="g", knobs=Knobs(cycle_length=5), premise=False
                            if plant_type == "direct_negation" else None)
            planted, twin = base.planted[0], base.consistent
            plant, params = planted.plant, planted.plant.params
            rng = random.Random(params["twin_seed"])
            (changed,) = params["differs_from_twin"]
            position = plant.facts.index(changed)
            facts = {f.id: f for f in planted.facts}
            if plant_type == "order_cycle":
                assert position == rng.randrange(5)
            elif plant_type == "equality_break":
                assert position == rng.randrange(4)
            elif plant_type == "binary_parity":
                apart = [i for i, f in enumerate(plant.facts) if facts[f].relation == "different"]
                assert position == rng.choice(apart)
            else:
                values = [w for w in VALUES[params["attribute"]] if w != facts[changed].value]
                rng.shuffle(values)
                assert next(f for f in twin.facts if f.id == changed).value == values[0]


def test_the_negated_claim_is_a_premise_in_the_configured_share_and_the_status_is_recorded():
    def statuses(**kw):
        return [generate("direct_negation", seed=s, genre="g", **kw).consistent.premise_status for s in range(1, 201)]

    assert set(statuses(premise_share=0)) == {"not_premise"} and set(statuses(premise_share=1)) == {"premise"}
    assert set(statuses(premise_share=0.5)) == {"premise", "not_premise"}
    assert set(statuses(premise=True, premise_share=0)) == {"premise"}
    yes, no = (generate("direct_negation", seed=3, genre="g", premise=p) for p in (True, False))
    assert yes.base_id != no.base_id and yes.planted[0].premise_status == "premise"
    for kw, message in [({}, "needs premise, or premise_share"), ({"premise_share": 1.5}, "from 0 to 1"),
                        ({"premise_share": True}, "from 0 to 1"), ({"premise": 1}, "premise is True or False")]:
        with pytest.raises(ValueError, match=message):
            generate("direct_negation", seed=1, genre="g", **kw)
    with pytest.raises(ValueError, match="only direct_negation's claim can be a premise"):
        generate("order_cycle", seed=1, genre="g", premise=True)
    assert generate("order_cycle", seed=1, genre="g", premise_share=0.3).consistent.premise_status is None


def test_same_attribute_distractors_are_a_setting_that_is_off_by_default():
    assert Knobs().same_attribute_distractors is False
    on = Knobs(cycle_length=3, entities=9, attributes=2, distractors=3, same_attribute_distractors=True)
    used = 0
    for plant_type in PLANT_TYPES:
        for seed in range(1, 31):
            base = generate(plant_type, seed=seed, genre="g", knobs=on, premise_share=0.5)
            assert check_base(base) == []
            planted = base.planted[0]
            params = planted.plant.params
            extra = [f for f in planted.facts if f.attribute == params["attribute"]
                     and f.id not in planted.plant.facts and f.id != planted.arity_fact]
            assert all({f.subject, f.object}.isdisjoint(params["entities"]) for f in extra)
            used += bool(extra)
            off = generate(plant_type, seed=seed, genre="g", knobs=Knobs(cycle_length=3, entities=9, distractors=3),
                           premise_share=0.5).planted[0]
            assert not [f for f in off.facts if f.attribute == params["attribute"] and f.id not in off.plant.facts
                        and f.id != off.arity_fact]
    assert used >= 60


def test_the_same_arguments_give_the_same_base_and_other_seeds_other_bases():
    knobs = Knobs(cycle_length=4, entities=5, attributes=3, distractors=2)
    for plant_type in PLANT_TYPES:
        a, b = (generate(plant_type, seed=7, genre="g", knobs=knobs, premise_share=0.5) for _ in range(2))
        assert a == b and a.planted[0].digest() == b.planted[0].digest()
        assert a.base_id.startswith(f"{plant_type}-7-")
        others = {generate(plant_type, seed=s, genre="g", knobs=knobs, premise_share=0.5).planted[0].digest()
                  for s in range(8, 20)}
        assert len(others) == 12 and a.planted[0].digest() not in others
        assert generate(plant_type, seed=7, genre="h", knobs=knobs, premise_share=0.5).base_id != a.base_id


def test_the_solver_discards_a_base_whose_twin_is_not_consistent():
    base = generate("equality_break", seed=3, genre="g")
    broken = base.model_copy(update={"consistent": base.consistent.model_copy(
        update={"facts": base.planted[0].facts})})
    assert check_base(broken) and check_base(broken)[0].startswith("consistent twin: ")


@pytest.mark.parametrize("fields, message", [
    ({"cycle_length": 2}, "cycle_length is from 3 to 6"), ({"cycle_length": 7}, "cycle_length is from 3 to 6"),
    ({"entities": 13}, "entities is from 3 to 12"), ({"attributes": 1}, "attributes is from 2 to 8"),
    ({"attributes": 9}, "attributes is from 2 to 8"), ({"distractors": 4}, "distractors is from 0 to 3"),
    ({"distractors": True}, "distractors is from 0 to 3"), ({"cycle_length": 5, "entities": 4}, "needs 5 entities"),
    ({"same_attribute_distractors": 1}, "same_attribute_distractors is True or False"),
])
def test_the_knobs_stay_within_the_spec_s_ranges(fields, message):
    with pytest.raises(ValueError, match=message):
        Knobs(**fields)


def test_knobs_that_no_world_can_satisfy_are_refused():
    with pytest.raises(ValueError, match="distinct pairs"):
        generate("order_cycle", seed=1, genre="g", knobs=Knobs(distractors=3))
    with pytest.raises(ValueError, match="to mention each"):
        generate("order_cycle", seed=1, genre="g", knobs=Knobs(entities=12, distractors=1))
    with pytest.raises(ValueError, match="distinct pairs"):
        generate("direct_negation", seed=1, genre="g", knobs=Knobs(distractors=1), premise=True)


def test_python_dash_m_xonforge_skeletons_reports_every_type(capsys):
    assert main(["skeletons", "--genre", "g", "--count", "3", "--cycle-length", "4", "--attributes", "3"]) == 0
    out = capsys.readouterr().out
    for t in PLANT_TYPES:
        assert f"{t}: 3 bases, 3 kept, 0 discarded." in out
    assert "premise share 0.5" in out and "same-attribute distractors off" in out and "arity fact" in out
    assert main(["skeletons", "--genre", "g", "--type", "direct_negation", "--premise-share", "1", "--count",
                 "4"]) == 0
    rows = [line for line in capsys.readouterr().out.splitlines() if line.startswith("direct_negation  direct_")]
    assert len(rows) == 4 and all(" premise " in r and "not premise" not in r for r in rows)
    assert main(["skeletons", "--genre", "g", "--type", "equality_break", "--entities", "6", "--distractors", "2",
                 "--same-attribute-distractors"]) == 0
    assert "same-attribute distractors on" in capsys.readouterr().out
    assert main(["skeletons", "--genre", "g", "--type", "binary_parity", "--count", "2", "--arity-control"]) == 0
    rows = [line for line in capsys.readouterr().out.splitlines() if line.startswith("binary_parity  binary_")]
    assert len(rows) == 2 and all("arity_control: a naive reading flags" in r and "the trap holds" in r for r in rows)


def test_python_dash_m_xonforge_skeletons_reports_each_type_s_error_and_goes_on(capsys):
    assert main(["skeletons", "--genre", "g", "--distractors", "3"]) == 2
    out = capsys.readouterr().out
    assert "order_cycle: stopped at seed 1: 9 distractor facts need 9 distinct pairs" in out
    assert "direct_negation: stopped at seed 1: 6 distractor facts need 6 distinct pairs" in out
    assert "equality_break: 0 bases, 0 kept, 0 discarded." in out
    assert main(["skeletons", "--genre", "g", "--premise-share", "2"]) == 2
    assert "error: the premise share is from 0 to 1, not 2.0" in capsys.readouterr().out
