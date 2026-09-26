"""v1 plant types, traps and the fact audit (XONFORGE_SPEC.md §5.2-§5.5, §5.3b, §7.4b, §13, §14 step 8). Offline."""
import json

import pytest

from xonforge.levels import LEVELS, combinations, draw
from xonforge.render.phrasing import statement
from xonforge.render.schema import Rendering, RenderRules, SpanEntry
from xonforge.skeleton.catalog import JUDGED_PLANTS, V1_PLANT_TYPES
from xonforge.skeleton.generators import TRAP_PLANTS, Knobs, generate
from xonforge.solver import check_base, minimal_contradiction, naive_contradiction, satisfiable
from xonforge.verify.audit import disagreements, prompt, require_other_model, audit
from xonforge.verify.checks import check

from xonforge_fakes import FakeClient, anthropic_response, caller, entry

RULES = RenderRules(words=300, explicitness="stated", lexical_variety="low", min_spacing=2)
FILLER = "Item {} on the agenda was the printer schedule for the coming week at the main office."
TRAPS = tuple(TRAP_PLANTS)


def _fit(r):
    return RULES.model_copy(update={"words": min(3000, max(150, len(r.text.split())))})


def _rendering(skeleton):
    parts, entries = [], []
    filler = iter(FILLER.format(i) for i in range(1, 1000))
    for fact in skeleton.facts:
        sentence = statement(fact, skeleton)
        sentence = sentence[0].upper() + sentence[1:] + "."
        parts += [next(filler) for _ in range(3)] + [sentence]
        entries.append(SpanEntry(fact=fact.id, span=sentence))
    text = " ".join(parts + [next(filler), next(filler)])
    return Rendering(text=text, spans=entries)


def _attrs(skeleton):
    return {a.key: a for a in skeleton.attributes}


@pytest.mark.parametrize("plant_type", V1_PLANT_TYPES)
def test_each_plant_has_a_satisfiable_twin_and_the_right_planted_variant(plant_type):
    for seed in range(1, 6):
        base = generate(plant_type, seed=seed, genre="memo", knobs=Knobs())
        assert check_base(base) == [], (base.base_id, check_base(base))
        twin, planted = base.consistent, base.planted[0]
        attrs = _attrs(planted)
        assert satisfiable(twin.facts, attrs)
        if plant_type in JUDGED_PLANTS:
            assert satisfiable(planted.facts, attrs)
            assert planted.plant.params["ground"] == "judged"
            if plant_type == "implicature_tension":
                assert planted.plant.params["soft"] is True
        else:
            assert minimal_contradiction(planted.facts, attrs) is not None
            assert not satisfiable(planted.facts, attrs)
        differs = [f.id for f, g in zip(twin.facts, planted.facts) if f != g]
        assert differs == planted.plant.params["differs_from_twin"] and len(differs) == 1
        assert twin.twin_facts == planted.plant.facts and base.trap_only == ()
        names = [e.name for e in planted.entities]
        if plant_type == "coreference_trap":
            assert names.count("Sam") == 2


@pytest.mark.parametrize("trap", TRAPS)
def test_each_trap_holds_when_read_correctly_and_a_naive_reading_is_recorded(trap):
    if trap == "arity_control":
        base = generate("binary_parity", seed=1, genre="memo", knobs=Knobs(), traps=(trap,))
    else:
        host = TRAP_PLANTS[trap][0]
        base = generate(host, seed=1, genre="memo", knobs=Knobs(), traps=(trap,))
    assert check_base(base) == [], (trap, check_base(base))
    skeleton = base.trap_only[0]
    recorded = skeleton.traps[0]
    assert naive_contradiction(skeleton, recorded) == tuple(recorded.naive["contradiction"])
    assert satisfiable(skeleton.facts, _attrs(skeleton))
    for variant in (base.consistent, base.planted[0], skeleton):
        assert check(variant, _rendering(variant), _fit(_rendering(variant))) == [], trap


@pytest.mark.parametrize("level", sorted(LEVELS))
@pytest.mark.parametrize("plant_type", V1_PLANT_TYPES)
def test_each_level_can_draw_a_v1_plant(level, plant_type):
    assert combinations(level, plant_type)
    knobs, _ = draw(level, plant_type, 1)
    base = generate(plant_type, seed=1, genre="memo", knobs=knobs, level=level)
    assert check_base(base) == [] and base.planted[0].difficulty["level"] == level


def test_a_rendering_of_every_v1_plant_passes_the_checks():
    for plant_type in V1_PLANT_TYPES:
        base = generate(plant_type, seed=1, genre="memo", knobs=Knobs())
        for skeleton in (base.consistent, base.planted[0]):
            rendering = _rendering(skeleton)
            assert check(skeleton, rendering, _fit(rendering)) == [], plant_type


def test_judged_plants_go_to_the_judged_split_and_a_pipeline_test_refuses_them():
    from fractions import Fraction

    from xonforge.corpus import splits

    base = generate("causal_inconsistency", seed=1, genre="memo", knobs=Knobs(), level=1)
    out = splits.assign_bases([base], seed=1, mode="record")
    assert out == {base.base_id: "judged"}
    with pytest.raises(ValueError, match="judged split"):
        splits.assign({base.base_id: ("causal_inconsistency", 1)}, seed=1, mode="pipeline_test",
                      proportions={"development": Fraction(1, 1)})


def test_the_fact_audit_flags_only_a_disagreement_with_the_span_map(tmp_path):
    base = generate("order_cycle", seed=1, genre="memo")
    skeleton = base.planted[0]
    spans = {f.id: "A sentence." for f in skeleton.facts}
    marks = {f.id: "stated" for f in skeleton.facts}
    assert disagreements(skeleton, spans, marks) == []
    marks[skeleton.facts[0].id] = "absent"
    assert "has a span and the audit marks it absent" in disagreements(skeleton, spans, marks)[0]
    missing = {f.id: "" for f in skeleton.facts}
    implied = {f.id: "implied" for f in skeleton.facts}
    assert all("has no span" in p for p in disagreements(skeleton, missing, implied))
    with pytest.raises(ValueError, match="different from the renderer"):
        require_other_model("claude-sonnet", "claude-sonnet")
    text = prompt(skeleton, "Ada wrote the memo.")
    assert skeleton.facts[0].id in text and "Ada wrote the memo." in text
    body = {"facts": [{"fact": f.id, "status": "stated"} for f in skeleton.facts]}
    fake = FakeClient(anthropic_response(text=json.dumps(body)))
    made = caller(tmp_path, entry(model="auditor"), fake)
    assert audit(made, skeleton, "Ada wrote the memo.", spans, renderer_model="renderer",
                 auditor_model="auditor") == []
