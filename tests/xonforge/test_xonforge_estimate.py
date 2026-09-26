"""XonForge's cost estimate (XONFORGE_SPEC.md §4.2; §14, step 7): offline, from the run configuration, the prompts the
calls would send, and the price table. Never calls an API."""
import dataclasses

import pytest

from xon_common.providers.base import Price
from xonforge import cli, registry
from xonforge import estimate as estimates
from xonforge.estimate import BaseSpec, Tally
from xonforge.review import blind, calibration

SETTINGS = {"tokens_per_word": 1.3, "tokenizer_factor": {"claude-sonnet-5": 1.3}}
THINKING = {"render": 4000, "derive": 2000, "review": 2000}


def bases(n, plant_type="order_cycle", trap=False):
    return [BaseSpec(plant_type, 1, seed, trap) for seed in range(1, n + 1)]


def test_the_calls_are_one_rendering_per_twin_one_derivation_per_variant_and_every_review_with_its_canaries():
    kw = {"renderers": ["claude-sonnet"], "reviewers": ["claude-opus", "claude-fable"],
          "review_prompts": list(blind.PROMPTS), "thinking": THINKING, "premise_share": 0.5}
    once = estimates.plan(bases(12), attempts=1, **kw)
    assert once.documents == 24 and once.reviewed_items == 24 + 2 * (calibration.DEFECT_CANARIES
                                                                     + calibration.CLEAN_CANARIES)
    assert once.tallies["claude-sonnet"].calls == 24
    assert once.tallies["claude-opus"].calls == once.tallies["claude-fable"].calls == 2 * once.reviewed_items
    assert once.tallies["claude-sonnet"].thinking_tokens == 12 * 4000 + 12 * 2000
    every = estimates.plan(bases(12), attempts=5, **kw)
    assert every.tallies["claude-sonnet"].calls == 5 * 24
    assert every.tallies["claude-sonnet"].input_words == pytest.approx(5 * once.tallies["claude-sonnet"].input_words)
    assert every.tallies["claude-opus"].calls == once.tallies["claude-opus"].calls
    trapped = estimates.plan(bases(2, "binary_parity", trap=True), attempts=1, **kw)
    assert trapped.documents == 6 and trapped.tallies["claude-sonnet"].calls == 6
    one = estimates.plan(bases(3), attempts=1, **{**kw, "review_prompts": ["contradiction_only"]})
    assert one.tallies["claude-opus"].calls == one.reviewed_items == 6 + 7
    with pytest.raises(ValueError, match="needs its renderers"):
        estimates.plan(bases(1), attempts=1, **{**kw, "renderers": []})


def test_a_tally_is_priced_with_the_tokenizer_factor_and_thinking_billed_as_output():
    entry = dataclasses.replace(registry.load_entries()[0], model="claude-sonnet-5",
                                price=Price(input_per_mtok=2.0, output_per_mtok=10.0))
    t = Tally()
    t.add(1, 1000, 1000, 1000)
    tokens = 1000 * 1.3 * 1.3
    assert estimates.tokens(1000, entry, SETTINGS) == pytest.approx(tokens)
    assert estimates.usd(t, entry, SETTINGS) == pytest.approx((tokens * 2 + (tokens + 1000) * 10) / 1e6)
    assert estimates.usd(t, entry, SETTINGS, with_thinking=False) == pytest.approx((tokens * 2 + tokens * 10) / 1e6)
    other = dataclasses.replace(entry, model="another-model")
    assert estimates.tokens(1000, other, SETTINGS) == pytest.approx(1300)
    assert estimates.usd(t, dataclasses.replace(entry, price=None), SETTINGS) is None


def test_the_estimate_command_prints_each_entry_against_its_caps_and_calls_nothing(capsys):
    assert cli.main(["estimate", "sample", "--bases", "order_cycle:1:2", "--bases", "direct_negation:1:1"]) == 0
    out = capsys.readouterr().out
    assert "Offline: no call is made." in out and "Run configuration sample, mode pipeline_test. 6 documents" in out
    for name in ("claude-sonnet", "claude-opus", "claude-fable"):
        assert name in out
    assert "Thinking assumed per call (not measured)" in out and "Run cap: $20.00." in out
    for bad in ("order_cycle:4:2", "order_cycle:1", "cycle:1:2"):
        assert cli.main(["estimate", "sample", "--bases", bad]) == 2
        assert capsys.readouterr().out.startswith("error: ")
