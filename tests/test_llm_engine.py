"""A1 pipeline (text -> claims, relations, entity relations -> report) with a scripted client. Never calls the API."""
import json
import math

import pytest

from llm_fakes import ANA_CLAIMS, ANA_ENTITIES, ANA_TEXT, MALFORMED_RATIONALE, ScriptedClient
from xon.llm.baselines import llm_direct, pairwise_only
from xon.llm.claims import (ALL_PAIRS_MAX, BLIND_CHECK_FRAC, PAIRS_PER_CALL, _score_batches, extract_claims,
                            malformed_rationale, text_tag)
from xon.llm.client import API_KEY_ENV, LLM, RECORD_ENV
from xon.llm.engine import analysis_to_dict, analyze_text, rescored, with_evidence
from xon.llm.prompts import relate_system

PREMISE_TEXT = "Assume the meeting is on Monday. The meeting is on Tuesday. The room was booked for Tuesday."
PREMISE_CLAIMS = [("The meeting is on Monday.", "premise"), ("The meeting is on Tuesday.", "asserted"),
                  ("The room was booked for Tuesday.", "asserted")]
PREMISE_RELATIONS = {(0, 1): ("contradicts", 0.95), (1, 2): ("supports", 0.8)}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.delenv(RECORD_ENV, raising=False)


def llm_for(tmp_path, client=None, name="cache"):
    return LLM(cache_dir=tmp_path / name, client=client, fixture_dir=tmp_path / "fixtures")


def test_the_pipeline_finds_the_order_cycle_the_pairwise_baseline_misses(tmp_path):
    client = ScriptedClient(ANA_CLAIMS, entities=ANA_ENTITIES)
    a = analyze_text(llm_for(tmp_path, client), ANA_TEXT)
    assert client.calls == ["extract", "relate", "entities"] and a.tag == text_tag(ANA_TEXT)
    assert a.pairs == [(0, 1), (0, 2), (1, 2)] and a.pair_info["mode"] == "all"
    r = a.report
    assert r.verdict_inconsistent and r.verdict_clauses == ["entity"]
    [c] = r.verdict_entity_contradictions
    assert c.type == "order_cycle" and c.claim_ids == [0, 1, 2]
    assert pairwise_only(a.graph) == (False, [])
    assert a.diagnostics["pairs_missing"] == [] and a.diagnostics["entity_relations"] == 3
    assert r.llm_usage["api_calls"] == 3


def test_extraction_renumbers_and_normalizes(tmp_path):
    client = ScriptedClient([("A holds.", "Asserted"), ("   ", "asserted"), ("B holds.", "PREMISE")])
    claims = extract_claims(llm_for(tmp_path, client), "A holds. B holds.", tag="t")
    assert [(c.id, c.text, c.kind) for c in claims.claims] == [(0, "A holds.", "asserted"), (1, "B holds.", "premise")]


def test_marking_evidence_makes_no_llm_call_and_keeps_the_first_report(tmp_path):
    client = ScriptedClient(PREMISE_CLAIMS, PREMISE_RELATIONS)
    a = analyze_text(llm_for(tmp_path, client), PREMISE_TEXT, label="Report 1")
    calls = list(client.calls)
    b = with_evidence(a, [2], label="Report 2")
    assert client.calls == calls
    assert b.relations is a.relations and b.claims is a.claims and b.graph is a.graph
    assert a.report.clamp_set == [0] and b.report.clamp_set == [0, 2] and b.evidence == [2] and a.evidence == []
    assert b.report.harmony < a.report.harmony < 1              # claim 2 clamped pulls claim 1 against the premise
    assert a.report.verdict_clauses == b.report.verdict_clauses == ["direct"]


def test_rescoring_with_world_knowledge_scores_relations_only(tmp_path):
    client = ScriptedClient(ANA_CLAIMS, entities=ANA_ENTITIES, wk_relations={(0, 2): ("contradicts", 0.7)})
    llm = llm_for(tmp_path, client)
    a = analyze_text(llm, ANA_TEXT, world_knowledge=False)
    b = rescored(llm, a, True, label="Report 2")
    assert client.calls == ["extract", "relate", "entities", "relate-wk"]
    assert not a.world_knowledge and b.world_knowledge
    assert b.claims is a.claims and b.entity_spec is a.entity_spec
    assert a.report.n_edges == 0 and b.report.n_edges == 1 and b.report.verdict_clauses == ["direct", "entity"]
    assert a.report.verdict_clauses == ["entity"]


def test_more_than_25_claims_use_proposed_pairs_plus_a_blind_check(tmp_path):
    n = ALL_PAIRS_MAX + 5
    claims = [(f"Claim number {i}.", "asserted") for i in range(n)]
    proposed = [(0, 1), (2, 3), (5, 4), (40, 1)]
    text = " ".join(t for t, _ in claims)

    def run(seed, name):
        client = ScriptedClient(claims, proposed=proposed)
        return analyze_text(llm_for(tmp_path, client, name), text, seed=seed), client

    a, client = run(0, "a")
    rest = n * (n - 1) // 2 - 3
    blind = math.ceil(BLIND_CHECK_FRAC * rest)
    assert a.pair_info["mode"] == "proposed + blind check" and a.pair_info["proposed"] == 3
    assert a.pair_info["invalid_proposed"] == 1 and len(a.pair_info["blind"]) == blind
    assert {(0, 1), (2, 3), (4, 5)} <= set(a.pairs) and len(a.pairs) == 3 + blind
    assert client.calls.count("pairs") == 1 and client.calls.count("relate") == math.ceil((3 + blind) / PAIRS_PER_CALL)
    assert a.diagnostics["blind_pairs"] == blind and a.diagnostics["blind_pairs_related"] == 0
    assert run(0, "b")[0].pairs == a.pairs                     # deterministic for a seed
    assert run(1, "c")[0].pairs != a.pairs


def test_pairs_left_out_and_relations_not_asked_for(tmp_path):
    extra = [{"a": 0, "b": 1, "relation": "contradicts", "confidence": 0.9, "rationale": "asked twice"},
             {"a": 1, "b": 7, "relation": "supports", "confidence": 0.9, "rationale": "not asked"}]
    client = ScriptedClient(ANA_CLAIMS, {(0, 1): ("supports", 0.8)}, omit={(0, 2)}, extra=extra)
    a = analyze_text(llm_for(tmp_path, client), ANA_TEXT)
    assert a.diagnostics["pairs_missing"] == [(0, 2)] and a.diagnostics["relations_ignored"] == 2
    assert [(x.a, x.b, x.relation) for x in a.relations.relations] == [(0, 1, "supports"), (1, 2, "unrelated")]
    assert a.graph.edges.tolist() == [[0, 1]]


def test_each_pair_is_judged_on_its_own_and_reasoned_before_its_label():
    rule = ("Judge each pair using only its two statements, ignoring every other statement in the list, even if they "
            "seem relevant.")
    for wk in (False, True):
        system = relate_system(wk)
        assert rule in system
        assert system.index("rationale is one sentence") < system.index("relation is the label") < \
            system.index("confidence is your confidence")


def test_a_rationale_holding_a_fragment_of_json_is_malformed():
    assert malformed_rationale(MALFORMED_RATIONALE)                     # Test 1, pair (1, 7)
    for garbled in ('A implies B. "relation": "supports"', "They conflict. confidence: 0.3", "A holds {B}"):
        assert malformed_rationale(garbled)
    for clean in ("Priya's arrival order doesn't relate to what Lena brought.",
                  'Both use "older" about different people, so neither bears on the other.',
                  "If Ana won (as A says), B's claim that Ben won cannot hold: there is one winner."):
        assert not malformed_rationale(clean)


def test_a_malformed_rationale_is_scored_again_once_on_its_own(tmp_path):
    client = ScriptedClient(ANA_CLAIMS, entities=ANA_ENTITIES, answers={(0, 2): [
        ("contradicts", 0.85, MALFORMED_RATIONALE), ("unrelated", 0.9, "Each compares a different pair of people.")]})
    a = analyze_text(llm_for(tmp_path, client), ANA_TEXT)
    assert client.calls == ["extract", "relate", "relate", "entities"]
    assert client.asked == [[(0, 1), (0, 2), (1, 2)], [(0, 2)]]
    assert "Ben is older than Cy." not in client.bodies[2]["messages"][0]["content"]
    [x] = a.diagnostics["relations_rescored"]
    assert (x["a"], x["b"], x["outcome"]) == (0, 2, "replaced")
    assert x["first"]["relation"] == "contradicts" and x["second"]["relation"] == "unrelated"
    assert [(r.a, r.b, r.relation) for r in a.relations.relations] == [(0, 1, "unrelated"), (0, 2, "unrelated"),
                                                                        (1, 2, "unrelated")]
    assert a.diagnostics["pairs_missing"] == a.diagnostics["pairs_unscored_malformed"] == []
    assert a.report.verdict_clauses == ["entity"] and pairwise_only(a.graph) == (False, [])
    tags = [json.loads(line)["tag"] for line in (tmp_path / "cache" / "log.jsonl").read_text("utf-8").splitlines()]
    assert f"{a.tag}-relate-rescore-000-002" in tags


@pytest.mark.parametrize("second", [("contradicts", 0.85, MALFORMED_RATIONALE), None],
                         ids=["malformed again", "left out"])
def test_a_pair_malformed_again_or_left_out_on_its_own_stays_unscored(tmp_path, second):
    client = ScriptedClient(ANA_CLAIMS, entities=ANA_ENTITIES,
                            answers={(0, 2): [("contradicts", 0.85, MALFORMED_RATIONALE), second]})
    a = analyze_text(llm_for(tmp_path, client), ANA_TEXT)
    assert client.calls == ["extract", "relate", "relate", "entities"]          # no third try
    [x] = a.diagnostics["relations_rescored"]
    assert x["outcome"] == "unscored" and (x["second"] is None) == (second is None)
    assert a.diagnostics["pairs_missing"] == a.diagnostics["pairs_unscored_malformed"] == [(0, 2)]
    assert [(r.a, r.b) for r in a.relations.relations] == [(0, 1), (1, 2)]
    assert a.report.n_edges == 0 and a.report.verdict_clauses == ["entity"]


def test_a_rescore_bypasses_the_cache_when_its_batch_does(tmp_path):
    first = ("contradicts", 0.85, MALFORMED_RATIONALE)
    client = ScriptedClient(ANA_CLAIMS, answers={(0, 2): [first, ("unrelated", 0.9, "Clean."), first, None]})
    llm = llm_for(tmp_path, client)
    claims = extract_claims(llm, ANA_TEXT, tag="t")
    outcomes = [_score_batches(llm, claims, [(0, 1), (0, 2), (1, 2)], tag="t", world_knowledge=False,
                               bypass_cache=True)[2][0]["outcome"] for _ in range(2)]
    assert outcomes == ["replaced", "unscored"] and client.calls.count("relate") == 4 and llm.usage["cache_hits"] == 0


def test_evidence_must_name_claims(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        analyze_text(llm_for(tmp_path, ScriptedClient(ANA_CLAIMS, entities=ANA_ENTITIES)), ANA_TEXT, evidence=[7])


def test_dry_run_replays_recorded_fixtures(tmp_path, monkeypatch):
    monkeypatch.setenv(RECORD_ENV, "1")
    live = analyze_text(llm_for(tmp_path, ScriptedClient(ANA_CLAIMS, entities=ANA_ENTITIES)), ANA_TEXT)
    monkeypatch.delenv(RECORD_ENV)
    dry = llm_for(tmp_path, None, "elsewhere")
    assert dry.dry_run
    replay = analyze_text(dry, ANA_TEXT)
    assert dry.usage["fixture_hits"] == 3 and dry.usage["api_calls"] == 0 and dry.usage["stale_fixtures"] == 0
    assert replay.report.verdict_clauses == live.report.verdict_clauses == ["entity"]
    assert replay.claims == live.claims and replay.relations == live.relations


def test_llm_direct_baseline(tmp_path):
    client = ScriptedClient(ANA_CLAIMS, contradictions=[["Ana is older than Ben.", "Cy is older than Ana."]])
    llm = llm_for(tmp_path, client)
    on = llm_direct(llm, ANA_TEXT, tag=text_tag(ANA_TEXT))
    off = llm_direct(llm, ANA_TEXT, tag=text_tag(ANA_TEXT), thinking=False)
    assert on.inconsistent and on.thinking and not off.thinking and len(on.contradictions) == 1
    first, second = client.bodies
    assert "thinking" not in first and first["max_tokens"] == llm.cfg.llm_max_tokens_direct
    assert second["thinking"] == {"type": "disabled"} and second["max_tokens"] == llm.cfg.llm_max_tokens_direct_no_thinking
    assert not llm_direct(llm_for(tmp_path, ScriptedClient(ANA_CLAIMS), "none"), ANA_TEXT, tag="t").inconsistent


def test_the_analysis_exports_to_json(tmp_path):
    a = analyze_text(llm_for(tmp_path, ScriptedClient(PREMISE_CLAIMS, PREMISE_RELATIONS)), PREMISE_TEXT)
    d = json.loads(json.dumps(analysis_to_dict(a)))
    assert d["claims"][0]["kind"] == "premise" and d["report"]["clamp_set"] == [0]
    assert {"label", "model", "world_knowledge", "tag", "evidence", "relations", "entity_relations",
            "pair_selection", "diagnostics"} <= set(d)
