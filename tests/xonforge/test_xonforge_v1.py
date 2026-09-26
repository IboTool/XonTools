"""v1 plants, traps, judged types and resolvable hard negatives (XONFORGE_SPEC.md §5.2, §5.3, §5.3b).

Every generated base passes the solver. A planted variant's plant is its only contradiction, except a judged plant,
which is satisfiable and labeled. A trap holds when read correctly, and the naive reading's only contradiction is
the plant. Never calls an API.
"""
import pytest

from xonforge.render.inferred import inferred_map
from xonforge.render.phrasing import statement
from xonforge.skeleton.generators import TRAP_PLANTS, V1_PLANT_TYPES, generate
from xonforge.skeleton.plants_v1 import JUDGED
from xonforge.solver import check_base


@pytest.mark.parametrize("plant_type", V1_PLANT_TYPES)
def test_every_v1_base_passes_the_solver(plant_type):
    for seed in range(1, 6):
        base = generate(plant_type, seed=seed, genre="g")
        assert check_base(base) == [], (base.base_id, check_base(base))
        planted = base.planted[0]
        assert planted.plant.type == plant_type
        if plant_type in JUDGED:
            assert planted.plant.params["ground_truth"] == "judged"
        else:
            assert "ground_truth" not in planted.plant.params


@pytest.mark.parametrize("trap", sorted(TRAP_PLANTS))
def test_every_trap_holds_read_correctly_and_fools_only_a_naive_reading(trap):
    plant_type = TRAP_PLANTS[trap][0]
    for seed in range(1, 4):
        base = generate(plant_type, seed=seed, genre="g", traps=(trap,), premise_share=0.0)
        assert check_base(base) == [], (base.base_id, trap, check_base(base))
        variant = base.trap_only[0]
        recorded = variant.traps[0]
        assert recorded.type == trap
        assert set(recorded.naive["contradiction"]) == set(recorded.facts) - {variant.arity_fact}


def test_every_v1_fact_has_a_wording_and_a_derivation_becomes_an_inferred_entry():
    for plant_type in V1_PLANT_TYPES:
        base = generate(plant_type, seed=1, genre="g")
        skeleton = base.planted[0]
        for fact in skeleton.facts:
            said = statement(fact, skeleton)
            assert said and "None" not in said
        spans = {f.id: statement(f, skeleton) + "." for f in skeleton.facts if not f.derivation}
        inferred = inferred_map(skeleton, spans)
        derived = [f for f in skeleton.facts if f.derivation]
        assert set(inferred) == {f.id for f in derived}
        for fact in derived:
            assert inferred[fact.id].mode == "inferred" and inferred[fact.id].derivation == fact.derivation
            assert inferred[fact.id].support_spans
