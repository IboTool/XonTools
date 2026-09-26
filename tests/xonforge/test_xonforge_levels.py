"""XonForge's difficulty levels (the user's item 4 of 2026-09-25, xonforge/docs/decisions.md): bundles of the §5.4
knobs, drawn from a seed. Never calls an API."""
import pytest

from xonforge.levels import LEVELS, Level, combinations, draw
from xonforge.skeleton.generators import PLANT_TYPES, feasible, generate
from xonforge.solver import check_base


def test_the_levels_are_the_user_s_bundles():
    assert LEVELS == {
        1: Level(words=(150, 300), cycle_length=(3, 4), explicitness=("stated",), distractors=(0, 1),
                 same_attribute_distractors=False, lexical_variety="low", entities=(3, 5), attributes=(2, 3),
                 spread="any"),
        2: Level(words=(400, 800), cycle_length=(3, 5), explicitness=("stated", "paraphrased"), distractors=(1, 2),
                 same_attribute_distractors=True, lexical_variety="medium", entities=(5, 8), attributes=(3, 5),
                 spread="half"),
        3: Level(words=(1000, 3000), cycle_length=(4, 6), explicitness=("paraphrased",), distractors=(2, 3),
                 same_attribute_distractors=True, lexical_variety="high", entities=(8, 12), attributes=(5, 8),
                 spread="quarters"),
    }


@pytest.mark.parametrize("level", sorted(LEVELS))
@pytest.mark.parametrize("plant_type", PLANT_TYPES)
def test_each_level_offers_only_knobs_within_it_that_the_generator_can_build(level, plant_type):
    lv, options = LEVELS[level], combinations(level, plant_type)
    assert options and len(set(options)) == len(options)
    for knobs in options:
        assert feasible(plant_type, knobs)
        assert lv.entities[0] <= knobs.entities <= lv.entities[1]
        assert lv.attributes[0] <= knobs.attributes <= lv.attributes[1]
        assert lv.distractors[0] <= knobs.distractors <= lv.distractors[1]
        assert knobs.same_attribute_distractors is lv.same_attribute_distractors
        assert knobs.cycle_length == lv.cycle_length[0] if plant_type == "direct_negation" else \
            lv.cycle_length[0] <= knobs.cycle_length <= lv.cycle_length[1]
    for seed in range(1, 6):
        knobs, _ = draw(level, plant_type, seed)
        base = generate(plant_type, seed=seed, genre="g", knobs=knobs, premise_share=0.5, level=level)
        assert check_base(base) == [] and base.planted[0].difficulty["level"] == level


@pytest.mark.parametrize("level", sorted(LEVELS))
def test_a_draw_is_the_same_for_the_same_seed_and_stays_within_the_level(level):
    lv = LEVELS[level]
    draws = [draw(level, "binary_parity", seed) for seed in range(200)]
    assert draws[:20] == [draw(level, "binary_parity", seed) for seed in range(20)]
    for knobs, rules in draws:
        assert knobs in combinations(level, "binary_parity")
        assert lv.words[0] <= rules.words <= lv.words[1] and rules.words % 10 == 0
        assert rules.explicitness in lv.explicitness and rules.lexical_variety == lv.lexical_variety
        assert (rules.spread, rules.level, rules.min_spacing) == (lv.spread, level, 1)
    assert {r.explicitness for _, r in draws} == set(lv.explicitness)
    assert len({k for k, _ in draws}) > 1 and len({r.words for _, r in draws}) > 1


def test_only_the_three_levels_and_known_plant_types_are_drawn():
    with pytest.raises(ValueError, match="levels are 1, 2, 3, not 4"):
        draw(4, "order_cycle", 1)
    with pytest.raises(ValueError, match="not a plant type"):
        draw(1, "no_such_plant", 1)
