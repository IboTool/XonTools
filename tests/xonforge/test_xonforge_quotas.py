"""XonForge step 6 (XONFORGE_SPEC.md §8, §9): quotas and splits, with the user's items 12 to 15 of 2026-09-25
(xonforge/docs/decisions.md). Offline."""
from collections import Counter
from fractions import Fraction

import pytest

from xonforge.corpus import splits
from xonforge.corpus.quotas import NO_TRAP, Progress, give_up_after, largest_remainder, plan, quotas
from xonforge.skeleton.generators import Knobs, generate


# ------------------------------------------------------------------------------------------ rounding (item 13)
def test_largest_remainder_sums_exactly_and_gives_what_is_left_to_the_largest_remainders():
    assert largest_remainder(7, {"a": 5, "b": 3, "c": 2}, seed=0) == {"a": 4, "b": 2, "c": 1}
    assert largest_remainder(10, {"a": Fraction(1, 3), "b": Fraction(2, 3)}, seed=0) == {"a": 3, "b": 7}
    for total in range(0, 40):
        parts = largest_remainder(total, {"a": 1, "b": 1, "c": 1}, seed=total)
        assert sum(parts.values()) == total and max(parts.values()) - min(parts.values()) <= 1


def test_a_tie_is_broken_by_the_seed_the_same_way_every_time():
    draws = [largest_remainder(1, {"a": 1, "b": 1}, seed=s) for s in range(20)]
    assert draws == [largest_remainder(1, {"a": 1, "b": 1}, seed=s) for s in range(20)]
    assert {k for d in draws for k, v in d.items() if v} == {"a", "b"}


def test_largest_remainder_refuses_a_negative_total_or_weights_that_divide_nothing():
    for total, weights in ((-1, {"a": 1}), (3, {}), (3, {"a": -1, "b": 2}), (3, {"a": 0})):
        with pytest.raises(ValueError, match="divided by weights"):
            largest_remainder(total, weights, seed=0)


# ------------------------------------------------------------------------------------------ quotas (item 12)
def test_the_target_is_a_full_cross_of_plant_type_level_and_provider_balanced_by_default():
    units = plan(24, plant_types=["order_cycle", "binary_parity"], levels=[1, 2],
                 providers=["anthropic", "openai", "google"], genres=["office memo", "club newsletter"], seed=3)
    assert len(units) == 24 and set(quotas(units).values()) == {2} and len(quotas(units)) == 12
    assert Counter(u.genre for u in units) == {"office memo": 12, "club newsletter": 12}
    for cell in quotas(units):
        assert sorted(u.genre for u in units if u.cell == cell) == ["club newsletter", "office memo"]
    assert {u.trap for u in units} == {NO_TRAP}
    assert units == plan(24, plant_types=["order_cycle", "binary_parity"], levels=[1, 2],
                         providers=["anthropic", "openai", "google"], genres=["office memo", "club newsletter"], seed=3)


def test_a_dimension_may_be_weighted_and_the_cells_still_sum_to_the_target():
    units = plan(10, plant_types={"order_cycle": 3, "binary_parity": 1}, levels=[1], providers=["anthropic"],
                 genres={"office memo": 1}, seed=0)
    by_type = Counter(u.plant_type for u in units)
    assert sum(by_type.values()) == 10 and sorted(by_type.values()) in ([2, 8], [3, 7])


def test_a_trap_quota_goes_only_to_the_plant_types_that_admit_the_trap():
    units = plan(8, plant_types=["order_cycle", "binary_parity"], levels=[1], providers=["anthropic"],
                 genres=["office memo"], traps={NO_TRAP: 1, "arity_control": 1}, seed=0)
    assert Counter((u.plant_type, u.trap) for u in units) == {("order_cycle", NO_TRAP): 4,
                                                              ("binary_parity", NO_TRAP): 2,
                                                              ("binary_parity", "arity_control"): 2}


# ------------------------------------------------------------------------------------------ unfillable (item 14)
def test_a_cell_is_unfillable_after_max_10_or_3_times_its_quota_attempts_and_nothing_is_redistributed():
    assert (give_up_after(1), give_up_after(3), give_up_after(4), give_up_after(10)) == (10, 10, 12, 30)
    small, large = ("order_cycle", 1, "anthropic"), ("binary_parity", 1, "anthropic")
    p = Progress({small: 2, large: 4})
    for _ in range(9):
        p.record(small, filled=False)
    assert p.unfillable() == [] and small in p.open()
    p.record(small, filled=False)
    assert p.unfillable() == [small] and p.open() == [large]
    with pytest.raises(ValueError, match="filled or unfillable, and takes no more attempts"):
        p.record(small, filled=True)
    for _ in range(4):
        p.record(large, filled=True)
    assert p.open() == [] and p.quotas == {small: 2, large: 4}
    assert p.report() == ["the cell order_cycle × 1 × anthropic is unfillable: 0 of its 2 filled after 10 attempts; "
                          "nothing is redistributed, the user decides"]
    with pytest.raises(ValueError, match="no quota for the cell"):
        p.record(("equality_break", 1, "anthropic"), filled=True)


# ------------------------------------------------------------------------------------------ splits (item 15)
def strata():
    return {**{f"b{n:04d}": ("order_cycle", 1) for n in range(20)},
            **{f"c{n:04d}": ("binary_parity", 2) for n in range(7)}}


def test_splits_are_stratified_by_plant_type_and_level_with_largest_remainder_counts():
    out = splits.assign(strata(), seed=5, mode="record")
    counts = Counter((strata()[b], s) for b, s in out.items())
    assert {s: counts[(("order_cycle", 1), s)] for s in ("development", "calibration", "test")} == {
        "development": 10, "calibration": 3, "test": 7}
    assert {s: counts[(("binary_parity", 2), s)] for s in ("development", "calibration", "test")} == {
        "development": 4, "calibration": 1, "test": 2}
    assert "judged" not in out.values() and set(out) == set(strata())


def test_the_split_seed_draws_the_same_splits_every_time_and_another_seed_others():
    assert splits.assign(strata(), seed=5, mode="record") == splits.assign(strata(), seed=5, mode="record")
    assert splits.assign(strata(), seed=5, mode="record") != splits.assign(strata(), seed=6, mode="record")


def test_a_pipeline_test_gives_its_own_proportions_and_never_a_test_or_judged_share():
    with pytest.raises(ValueError, match="a pipeline test's run gives its proportions"):
        splits.assign(strata(), seed=5, mode="pipeline_test")
    for barred in ("test", "judged"):
        with pytest.raises(ValueError, match=f"never enters a sealed or judged split, and a proportion is given for "
                                             f"{barred}"):
            splits.assign(strata(), seed=5, mode="pipeline_test",
                          proportions={"development": Fraction(1, 2), barred: Fraction(1, 2)})
    out = splits.assign(strata(), seed=5, mode="pipeline_test",
                        proportions={"development": Fraction(3, 4), "calibration": Fraction(1, 4)})
    assert set(out.values()) == {"development", "calibration"}
    with pytest.raises(ValueError, match="the splits are"):
        splits.assign(strata(), seed=5, mode="record", proportions={"train": 1})
    with pytest.raises(ValueError, match="names its mode"):
        splits.assign(strata(), seed=5, mode="test")


def test_a_base_s_stratum_is_its_plant_type_and_level_and_every_variant_goes_with_it():
    knobs = Knobs(entities=5, distractors=1)
    bases = [generate("order_cycle", seed=s, genre="office memo", knobs=knobs, level=1) for s in (1, 2)]
    bases += [generate("binary_parity", seed=3, genre="office memo", knobs=knobs, level=2)]
    assert [splits.stratum(b) for b in bases] == [("order_cycle", 1), ("order_cycle", 1), ("binary_parity", 2)]
    out = splits.assign_bases(bases, seed=1, mode="record")
    assert set(out) == {b.base_id for b in bases}
