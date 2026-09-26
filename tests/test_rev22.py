"""A1 rev. 2.2 (XON_A1_REV2_2_PRECISION.md §9): rev. 2.1 kept verbatim, the tension label, one pair per call, the
malformed-output rule, transport retries, the comparative lexicon and the derivation, the entity steps (thinking,
per-document schemas and their fallback, the coverage net), the threshold rule, the minimal engine under rev. 2.2,
prompt caching and batches, concurrency within the budget, the development pass's runner, diagnostics and L1-var
replay, and Step 0's classes and script. Never calls the API."""
import importlib.util
import json
import math
import os
import random
import re
import subprocess
import sys
import textwrap
import threading
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from llm_fakes import (ANA_CLAIMS, ANA_ENTITIES_V22, ANA_TEXT, MALFORMED_RATIONALE, NO_STATEMENTS, ScriptedClient,
                       call_kind, single_pair, system_text)
from test_consistency_eval import GARBLED, Oracle, _numbered, sample
from xon.config import (DEFAULT, ENGINE_VERSIONS, RELATION_THRESHOLD_V2_1, RELATION_THRESHOLD_V2_2, XonConfig,
                        relation_threshold)
from xon.llm import devpass, minimal, prompts
from xon.llm.baselines import pairwise_only
from xon.llm.claims import (build_signed_graph, extract_entity_steps_v22, planned_requests_v22, run_concurrently,
                            score_pairs_v22, text_tag, v22_tag)
from xon.llm.client import (API_KEY_ENV, LLM, RECORD_ENV, SCHEMA_TOO_COMPLEX, BatchRunner, BudgetExceeded, _usage_of,
                            cost_usd, output_schema, request_hash, request_key)
from xon.llm.comparatives import LEXICON, lexicon_sense, lexicon_words_in, normalize_comparative
from xon.llm.consistency import analyze, report_to_dict
from xon.llm.corpus import NAMES, SAMPLE_BASES, TOPICS
from xon.llm.devpass import (CARRIED, LABEL, TAUS, dev_markdown, dev_row, diagnostics, planned_calls,
                             replay_l1var_v22, run_corpus_dev, run_document_dev, run_l1var_v22, score_l1var_v22,
                             select_threshold, tau_key, threshold_curve, threshold_rule)
from xon.llm.engine import analysis_to_dict, analyze_text, rescored, with_evidence
from xon.llm.entity_consistency import CONFIDENCE_MIN, build_entity_graph, build_entity_graph_v22, find_contradictions
from xon.llm.evaluation import document_row, relations_extracted, run_corpus
from xon.llm.minimal import analyze_minimal
from xon.llm.order_misses import misses, order_cycle_closes, planted_cycle_reported, relations_extracted_corrected
from xon.llm.schemas import (Attribute, Claim, ClaimList, Entity, EntityCoverageV22, EntityGraphSpec,
                             EntityGraphSpecV22, EntityRelation, EntityRelationsV22, EntityStepsV22, InventoryV22,
                             OrderStatement, RelationListV22, RelationV22, document_schema)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "consistency" / "corpus.jsonl"
RECORD_RUN = ROOT / "results" / "a1-20260924-232324"
USAGE = {"input_tokens": 100, "output_tokens": 40, "thinking_tokens": 0}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.delenv(RECORD_ENV, raising=False)


def claims_of(*texts, kinds=None):
    kinds = kinds or ["asserted"] * len(texts)
    return ClaimList(claims=[Claim(id=i, text=t, span=t, kind=k) for i, (t, k) in enumerate(zip(texts, kinds))])


def rel22(*rels):
    return RelationListV22(relations=[RelationV22(a=a, b=b, rationale="Hand-built.", relation=label, confidence=conf)
                                      for a, b, label, conf in rels])


def _answer(same_different=(), orders=(), extremes=(), senses=(), unsupported=(), none=None) -> dict:
    def conf(t, n):
        return t[n] if len(t) > n else 0.9

    out = {"same_different": [{"claim_id": r[0], "attribute": r[1], "kind": r[2], "a": r[3], "b": r[4],
                               "confidence": conf(r, 5)} for r in same_different],
           "orders": [{"claim_id": o[0], "attribute": o[1], "subject": o[2], "comparative": o[3], "object": o[4],
                       "confidence": conf(o, 5)} for o in orders],
           "extremes": [{"claim_id": e[0], "attribute": e[1], "entity": e[2], "comparative": e[3],
                         "restriction": e[5] if len(e) > 5 else None, "confidence": conf(e, 4)} for e in extremes],
           "senses": [{"attribute": a, "comparative": c, "greater_side": s} for a, c, s in senses],
           "unsupported_order_claims": list(unsupported)}
    return out if none is None else {**out, "none": [{"claim_id": c, "reason": r} for c, r in none]}


def statements(attributes=(), same_different=(), orders=(), extremes=(), senses=(), unsupported=(), *, entities=(),
               coverage=None, uncovered=(), matched=None, iteration=1):
    """What rev. 2.2's entity steps return, from tuples, confidence 0.9 unless a later element gives it; with
    iteration=0, development iteration 0's single answer instead. attributes: (key, order_kind[, arity]);
    same_different: (claim, attribute, kind, a, b); orders: (claim, attribute, subject, comparative, object);
    extremes: (claim, attribute, entity, comparative[, confidence[, restriction]]); senses: (attribute, comparative,
    greater_side). The inventory lists the entities of every statement and ``entities``. coverage: the follow-up's
    answer for the claims in ``uncovered``, as keyword arguments of the same form plus none=[(claim, reason)];
    matched: the claims holding a lexicon word (default: the uncovered ones)."""
    cov = dict(coverage or {})
    none = cov.pop("none", ())
    everything = {k: [*v, *cov.get(k, ())] for k, v in (("same_different", same_different), ("orders", orders),
                                                          ("extremes", extremes))}
    names = sorted({*entities} | {x for r in everything["same_different"] for x in r[3:5]}
                   | {x for o in everything["orders"] for x in (o[2], o[4])} | {e[2] for e in everything["extremes"]})
    inventory = {"entities": [{"id": n, "mentions": [n.title()]} for n in names],
                 "attributes": [{"key": a[0], "arity": a[2] if len(a) > 2 else "unknown", "arity_span": None,
                                 "order_kind": a[1],
                                 "other_greater_means": "a higher standing" if a[1] == "other" else None}
                                for a in attributes]}
    relations = _answer(same_different, orders, extremes, senses, unsupported)
    if iteration == 0:
        return EntityGraphSpecV22.model_validate({**inventory, **relations})
    return EntityStepsV22.model_validate({
        "inventory": inventory, "relations": relations,
        "coverage": None if coverage is None else _answer(**cov, none=none),
        "lexicon_matched": sorted(set(uncovered if matched is None else matched)), "uncovered": list(uncovered),
        "schema_fallback": []})


def response(out, usage=None):
    u = usage or USAGE
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(out))], stop_reason="end_turn",
                           usage=SimpleNamespace(input_tokens=u["input_tokens"], output_tokens=u["output_tokens"],
                                                 output_tokens_details=None))


def fake_llm(path, client, **kw):
    return LLM(cache_dir=path / "cache", client=client, fixture_dir=path / "fixtures",
               sleep=kw.pop("sleep", lambda s: None), **kw)


def log_rows(path):
    return [json.loads(line) for line in (path / "cache" / "log.jsonl").read_text("utf-8").splitlines()]


def _script(name):
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), ROOT / "scripts" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------------------------------ versions (§2)
def test_both_versions_are_known_and_rev_2_1_keeps_its_threshold():
    assert ENGINE_VERSIONS == ("2.1", "2.2") and XonConfig().llm_engine_version == "2.1"
    assert RELATION_THRESHOLD_V2_1 == CONFIDENCE_MIN == 0.5
    for method in ("engine", "minimal", "pairwise"):
        assert relation_threshold(method, "2.1") == 0.5
        frozen = RELATION_THRESHOLD_V2_2[method]
        assert relation_threshold(method, "2.2") == (0.5 if frozen is None else frozen)
    with pytest.raises(ValueError, match="engine version"):
        relation_threshold("engine", "3.0")
    with pytest.raises(ValueError, match="method"):
        relation_threshold("direct", "2.2")


def test_rev_2_1_requests_hash_as_they_did_when_its_fixtures_were_recorded(tmp_path):
    """The 12-document subset replays from rev. 2.1's recorded fixtures with no stale fixture: every rev. 2.1 request
    body is byte for byte the one recorded."""
    records = [r for r in map(json.loads, CORPUS.read_text("utf-8").splitlines()) if r["base"] in SAMPLE_BASES]
    llm = LLM(cache_dir=tmp_path / "cache")
    run_corpus(llm, records, log=lambda s: None)
    u = llm.usage
    assert u["calls"] > 0 and u["fixture_hits"] == u["calls"] and u["stale_fixtures"] == 0 and u["api_calls"] == 0


@pytest.mark.slow
def test_rev_2_1_recomputes_the_run_of_records_files_byte_for_byte(tmp_path, monkeypatch):
    """§2: l1.json, l1b.json and documents.jsonl recomputed from the cache by rev. 2.1's evaluation script (engine
    version 2.1) are byte-identical to the run of record's. Read-only: the call log is not appended."""
    if not (RECORD_RUN / "l1.json").exists() or not (ROOT / "cache" / "llm").is_dir():
        pytest.skip("needs the run of record's folder and its cache")
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(LLM, "_log", lambda self, *args, **kwargs: None)
    out = tmp_path / "out"
    assert _script("run_consistency_eval.py").main(["--budget", "0", "--out", str(out)]) == 0
    for name in ("l1.json", "l1b.json", "documents.jsonl"):
        assert (out / name).read_bytes() == (RECORD_RUN / name).read_bytes(), name
    assert json.loads((out / "run.json").read_text("utf-8"))["usage"]["api_calls"] == 0


# ------------------------------------------------------------------------------------------ fix R1: tension (§3)
def test_the_rev_2_2_relation_prompt_defines_four_labels_and_the_ordinary_reading_rule():
    for wk in (False, True):
        s = prompts.relate_system_v2_2(wk)
        assert all(f'"{label}"' in s for label in ("supports", "contradicts", "tension", "unrelated"))
        assert "cannot both be true as written" in s and "look for an ordinary reading" in s
        assert "different times, occasions, objects or people, or loose everyday wording" in s
        assert all(x in s for x in prompts.EXAMPLE_TENSION + prompts.EXAMPLE_CONTRADICTS)
        # the world-knowledge switch reads as rev. 2.1's
        on, off = prompts.relate_system(True).splitlines(), prompts.relate_system(False).splitlines()
        switch = [line for line in (on if wk else off) if line not in (off if wk else on)]
        assert switch and all(line in s for line in switch)
    assert prompts.RELATE_SYSTEM_V2_2 == prompts.relate_system_v2_2(False)


def test_the_worked_examples_share_no_name_topic_or_content_word_with_the_l1_corpus():
    def words(s):
        return set(re.findall(r"[a-z']+", s.lower()))

    function_words = {"a", "all", "at", "in", "on", "the", "was"}
    content = words(" ".join(prompts.EXAMPLE_TENSION + prompts.EXAMPLE_CONTRADICTS)) - function_words
    assert content and not content & {n.lower() for n in NAMES}
    assert not content & set().union(*map(words, TOPICS))
    vocabulary = set().union(*(words(json.loads(line)["text"]) for line in CORPUS.read_text("utf-8").splitlines()
                               if line.strip()))
    assert not content & vocabulary, sorted(content & vocabulary)


def test_tension_makes_no_edge_and_changes_nothing_but_the_tension_list():
    claims = claims_of("A.", "B.", "C.", "D.", kinds=["asserted", "asserted", "premise", "asserted"])
    base = [(0, 1, "contradicts", 0.9), (1, 2, "supports", 0.8), (0, 2, "supports", 0.9), (2, 3, "contradicts", 0.7)]
    without = build_signed_graph(claims, rel22(*base))
    with_tension = build_signed_graph(claims, rel22(*base, (0, 3, "tension", 0.95), (3, 1, "tension", 0.6)))
    assert np.array_equal(with_tension.edges, without.edges) and np.array_equal(with_tension.sign, without.sign)
    assert np.array_equal(with_tension.weight, without.weight)
    r0, r1 = analyze(without), analyze(with_tension)
    d0, d1 = report_to_dict(r0), report_to_dict(r1)
    assert d1.pop("tension_pairs") == [{"a": 0, "b": 3, "rationale": "Hand-built.", "confidence": 0.95},
                                       {"a": 3, "b": 1, "rationale": "Hand-built.", "confidence": 0.6}]
    assert d0.pop("tension_pairs") == [] and d0 == d1
    assert r1.verdict_clauses == ["direct", "claim_balance"]
    assert pairwise_only(with_tension) == pairwise_only(without) == (True, [(0, 1), (2, 3)])
    assert minimal.direct_contradictions(claims, rel22((0, 1, "tension", 0.99))) == []
    # a tension label is the pair's relation: a later contradicts for the same pair is a duplicate, not an edge
    sg = build_signed_graph(claims_of("A.", "B."), rel22((0, 1, "tension", 0.9), (1, 0, "contradicts", 0.9)))
    assert len(sg.edges) == 0 and sg.duplicates == 1 and len(sg.tension) == 1


def test_a_rev_2_2_analysis_carries_its_version_threshold_tension_and_derivation(tmp_path):
    fake = ScriptedClient(ANA_CLAIMS, entities_v22=ANA_ENTITIES_V22, relations_v22={(0, 1): ("tension", 0.8)})
    llm = fake_llm(tmp_path, fake)
    a = analyze_text(llm, ANA_TEXT, engine_version="2.2")
    tau = relation_threshold("engine", "2.2")
    assert (a.engine_version, a.threshold, a.report.engine_version, a.report.threshold) == ("2.2", tau, "2.2", tau)
    assert a.report.verdict_clauses == ["entity"] and a.report.direct_contradictions == []
    assert a.report.tension_pairs == [{"a": 0, "b": 1, "rationale": "scripted", "confidence": 0.8}]
    assert a.diagnostics["tension_pairs"] == [(0, 1)]
    assert a.diagnostics["entity_derivation"]["order_kind"] == {"age": "magnitude"}
    d = analysis_to_dict(a)
    assert (d["engine_version"], d["threshold"]) == ("2.2", tau) and len(d["derived_entity_relations"]) == 3
    assert d["iteration"] == 1 and d["entity_relations"]["lexicon_matched"] == [0, 1, 2]
    tag = text_tag(ANA_TEXT)
    # every claim holds "older" and has a statement, so there is no coverage call
    assert {r["tag"] for r in log_rows(tmp_path)} == {f"{tag}-v22-extract", f"{tag}-v22-entities-inventory",
                                                      f"{tag}-v22-entities-relations",
                                                      *(f"{tag}-v22-relate-{p}" for p in ("000-001", "000-002",
                                                                                          "001-002"))}
    b = with_evidence(a, [0], "b")
    c = rescored(llm, a, True, "c")
    assert {(x.engine_version, x.threshold) for x in (b, c)} == {("2.2", tau)}
    assert c.report.tension_pairs == a.report.tension_pairs
    assert fake.calls.count("relate-v22-wk") == 3 and fake.calls.count("relate-v22") == 3
    # rev. 2.1 of the same text: its own relation calls, the same claims (a cache hit), no tension
    r21 = analyze_text(llm, ANA_TEXT, engine_version="2.1")
    assert (r21.engine_version, r21.threshold) == ("2.1", 0.5) and fake.calls.count("extract") == 1
    assert "tension_pairs" not in r21.diagnostics and "derived_entity_relations" not in analysis_to_dict(r21)
    with pytest.raises(ValueError, match="engine version"):
        analyze_text(llm, ANA_TEXT, engine_version="2.3")


# ------------------------------------------------------------------------------------------ fix R2: one pair per call (§4)
def test_a_relation_request_holds_its_pairs_two_statements_and_nothing_else(tmp_path):
    rng = random.Random(22)
    for trial in range(5):
        n = rng.randint(2, 9)
        texts = [f"{rng.choice(NAMES)} noted item {rng.getrandbits(48):012x}." for _ in range(n)]
        fake = ScriptedClient([(t, "asserted") for t in texts])
        pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
        score_pairs_v22(fake_llm(tmp_path / str(trial), fake), claims_of(*texts), pairs, tag="doc-v22",
                        world_knowledge=bool(trial % 2), concurrency=3)
        assert sorted(single_pair(b["messages"][0]["content"]) for b in fake.bodies) == pairs
        for body in fake.bodies:
            user = body["messages"][0]["content"]
            a, b = single_pair(user)
            assert user == f"A (claim {a}): {texts[a]}\nB (claim {b}): {texts[b]}"
            assert not any(t in system_text(body["system"]) for t in texts)
            assert body["system"][0]["cache_control"] == {"type": "ephemeral"} and len(body["messages"]) == 1


def test_a_malformed_or_off_pair_answer_is_scored_once_more_then_left_unscored(tmp_path):
    claims = claims_of("A one.", "B two.", "C three.", "D four.")
    fake = ScriptedClient([(c.text, "asserted") for c in claims.claims], answers={
        (0, 1): [("contradicts", 0.8, MALFORMED_RATIONALE), ("contradicts", 0.7, "Fine.")],
        (0, 2): [("supports", 0.8, MALFORMED_RATIONALE), ("supports", 0.8, MALFORMED_RATIONALE)],
        (1, 2): [None, ("unrelated", 0.9, "Fine.")],
        (2, 3): [None, None]})
    llm = fake_llm(tmp_path, fake)
    pairs = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
    relations, off_pair, rescores = score_pairs_v22(llm, claims, pairs, tag="doc-v22", world_knowledge=False)
    assert [(r.a, r.b) for r in relations.relations] == [(0, 1), (0, 3), (1, 2), (1, 3)]
    assert (relations.relations[0].confidence, relations.relations[0].rationale) == (0.7, "Fine.")
    assert off_pair == 3 and len(fake.calls) == 6 + 4
    assert [(x["a"], x["b"], x["reason"], x["outcome"]) for x in rescores] == [
        (0, 1, "malformed", "replaced"), (0, 2, "malformed", "unscored"), (1, 2, "other pair", "replaced"),
        (2, 3, "other pair", "unscored")]
    assert rescores[0]["first"]["rationale"] == MALFORMED_RATIONALE and rescores[0]["second"]["rationale"] == "Fine."
    rows = log_rows(tmp_path)
    assert sum(r["tag"].startswith("doc-v22-relate-rescore-") for r in rows) == 4
    # each attempt is cached under its own key: the same request again is answered from the cache, both attempts
    assert score_pairs_v22(llm, claims, pairs, tag="doc-v22", world_knowledge=False) == (relations, 3, rescores)
    assert len(fake.calls) == 10
    first = llm.request(system=prompts.relate_system_v2_2(False), user=prompts.relate_single_user(claims, (0, 1)),
                        max_tokens=llm.cfg.llm_max_tokens_relate_single, thinking=False, schema=RelationV22,
                        cache_system=True)
    assert llm.is_cached(request_key(first)) and llm.is_cached(request_key(first, 2))
    assert request_key(first) == request_hash(first) != request_key(first, 2)
    record = json.loads((tmp_path / "cache" / f"{request_key(first, 2)}.json").read_text("utf-8"))
    assert (record["attempt"], record["sent"]) == (2, request_hash(first))


def test_transport_failures_are_retried_and_logged_apart_from_rescores(tmp_path):
    class Flaky:
        def __init__(self, *items):
            self.items, self.messages = list(items), self

        def create(self, **body):
            item = self.items.pop(0)
            if isinstance(item, Exception):
                raise item
            return response(item)

    class Status(Exception):
        def __init__(self, status):
            super().__init__(status)
            self.status_code, self.response = status, SimpleNamespace(headers={})

    connection_error = type("APIConnectionError", (Exception,), {})     # named as the SDK's; its timeout subclasses it
    timeout_error = type("APITimeoutError", (connection_error,), {})
    ok = {"a": 0, "b": 1, "rationale": "Fine.", "relation": "supports", "confidence": 0.9}
    waits = []
    llm = fake_llm(tmp_path, Flaky(Status(429), Status(502), timeout_error(), ok), sleep=waits.append)
    relations, off_pair, rescores = score_pairs_v22(llm, claims_of("A.", "B."), [(0, 1)], tag="doc-v22",
                                                    world_knowledge=False)
    assert len(relations.relations) == 1 and rescores == [] and off_pair == 0
    assert waits == [2.0, 4.0, 8.0] and llm.usage["transport_retries"] == 3 and llm.usage["api_calls"] == 1
    assert [r["source"] for r in log_rows(tmp_path)] == ["retry", "retry", "retry", "api"]
    llm = fake_llm(tmp_path / "b", Flaky(Status(400), ok))
    with pytest.raises(Status):
        score_pairs_v22(llm, claims_of("A.", "B."), [(0, 1)], tag="doc-v22", world_knowledge=False)
    assert llm.usage["transport_retries"] == 0


def test_run_concurrently_keeps_item_order_and_raises_the_first_error():
    assert run_concurrently(lambda x: x * x, range(30), 5) == [x * x for x in range(30)]
    assert run_concurrently(lambda x: x, [], 5) == [] and run_concurrently(lambda x: -x, [3], 5) == [-3]

    def slow_then_fail(x):
        time.sleep(0.01 * (5 - x % 5))
        if x == 7:
            raise ValueError("seven")
        return x

    with pytest.raises(ValueError, match="seven"):
        run_concurrently(slow_then_fail, range(20), 4)


def test_calls_in_flight_reserve_budget_so_a_concurrent_pass_cannot_overspend(tmp_path):
    lock, state = threading.Lock(), {"now": 0, "most": 0}

    class Slow:
        def __init__(self):
            self.messages = self

        def create(self, **body):
            with lock:
                state["now"] += 1
                state["most"] = max(state["most"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            a, b = single_pair(body["messages"][0]["content"])
            return response({"a": a, "b": b, "rationale": "Fine.", "relation": "unrelated", "confidence": 0.9})

    llm = fake_llm(tmp_path, Slow())
    claims = claims_of(*[f"Claim number {i}." for i in range(6)])
    pairs = [(i, j) for i in range(6) for j in range(i + 1, 6)]
    one = max(llm.reserve_of(body) for body, *_ in planned_requests_v22(llm, claims, pairs, tag="doc-v22",
                                                                        world_knowledge=False)[:-1])
    llm.budget_tokens = int(2.5 * one)
    with pytest.raises(BudgetExceeded, match="reserved by calls in flight"):
        score_pairs_v22(llm, claims, pairs, tag="doc-v22", world_knowledge=False, concurrency=8)
    assert 1 <= state["most"] <= 2 and llm._reserved == 0
    assert llm.spent_tokens == 140 * llm.usage["api_calls"] <= llm.budget_tokens


def test_the_batch_plan_is_exactly_what_the_pipeline_sends(tmp_path):
    fake = ScriptedClient(ANA_CLAIMS, entities_v22=ANA_ENTITIES_V22)
    llm = fake_llm(tmp_path, fake)
    a = analyze_text(llm, ANA_TEXT, engine_version="2.2")
    # the relations call's schema and message are built from the inventory's answer, so it cannot be planned
    assert fake.calls[-1] == "entities-relations"
    sent = [b for b, kind in zip(fake.bodies, fake.calls) if kind not in ("extract", "entities-relations")]
    planned = planned_requests_v22(llm, a.claims, a.pairs, tag=v22_tag(a.tag), world_knowledge=False)
    assert sorted(request_key(body) for body, *_ in planned) == sorted(request_hash(b) for b in sent)
    assert [t for _, _, t, _ in planned] == [f"{a.tag}-v22-relate-{p}" for p in ("000-001", "000-002", "001-002")] + [
        f"{a.tag}-v22-entities-inventory"]
    assert [thinking for *_, thinking in planned] == [False] * 3 + ["adaptive"]
    assert planned_calls(llm, [{"text": ANA_TEXT}]) == planned


# ------------------------------------------------------------------------------------------ prompt caching and batches (§4.2)
def test_cost_counts_cache_writes_and_reads_and_halves_for_a_batch():
    model = DEFAULT.llm_model
    plain = {"input_tokens": 1000, "output_tokens": 100}
    assert cost_usd(model, plain) == pytest.approx((1000 * 2 + 100 * 10) / 1e6)
    cached = {"input_tokens": 1000, "output_tokens": 100, "cache_write_tokens": 200, "cache_read_tokens": 500}
    assert cost_usd(model, cached) == pytest.approx((300 * 2 + 200 * 2 * 1.25 + 500 * 2 * 0.1 + 100 * 10) / 1e6)
    assert cost_usd(model, plain, batch=True) == pytest.approx(cost_usd(model, plain) / 2)
    with_cache = SimpleNamespace(usage=SimpleNamespace(input_tokens=300, output_tokens=100, output_tokens_details=None,
                                                       cache_creation_input_tokens=200, cache_read_input_tokens=500))
    assert _usage_of(with_cache) == {"input_tokens": 1000, "output_tokens": 100, "thinking_tokens": 0,
                                     "cache_write_tokens": 200, "cache_read_tokens": 500}
    without = SimpleNamespace(usage=SimpleNamespace(input_tokens=300, output_tokens=100, output_tokens_details=None,
                                                    cache_creation_input_tokens=0, cache_read_input_tokens=None))
    assert _usage_of(without) == {"input_tokens": 300, "output_tokens": 100, "thinking_tokens": 0}


def test_the_cache_breakpoint_is_part_of_the_request_key(tmp_path):
    llm = fake_llm(tmp_path, ScriptedClient([]))
    kw = dict(system="S", user="U", max_tokens=10, thinking=False, schema=RelationV22)
    marked, plain = llm.request(**kw, cache_system=True), llm.request(**kw)
    assert marked["system"] == [{"type": "text", "text": "S", "cache_control": {"type": "ephemeral"}}]
    assert plain["system"] == "S" and request_hash(marked) != request_hash(plain)
    assert len({request_key(marked, k) for k in (1, 2, 3)}) == 3


class FakeBatches:
    """messages.batches: create, then retrieve (in progress once, then ended; ``lost`` retrieves fail first), then
    results answered by a scripted client, except the ``fail`` keys, which are errored."""

    def __init__(self, answer, fail=(), lost=0):
        self.answer, self.fail, self.lost = answer, set(fail), lost
        self.created, self.polls = [], 0

    def create(self, requests):
        self.created.append(list(requests))
        return SimpleNamespace(id=f"msgbatch_{len(self.created)}", processing_status="in_progress")

    def retrieve(self, batch_id):
        if self.lost:
            self.lost -= 1
            raise ConnectionError("lost while waiting")
        self.polls += 1
        return SimpleNamespace(id=batch_id, processing_status="ended" if self.polls % 2 == 0 else "in_progress",
                               request_counts=SimpleNamespace(succeeded=0, processing=len(self.created[-1])))

    def results(self, batch_id):
        for r in self.created[int(batch_id.split("_")[1]) - 1]:
            if r["custom_id"] in self.fail:
                yield SimpleNamespace(custom_id=r["custom_id"], result=SimpleNamespace(type="errored"))
            else:
                yield SimpleNamespace(custom_id=r["custom_id"],
                                      result=SimpleNamespace(type="succeeded", message=self.answer.create(**r["params"])))


def batch_client(scripted, batches):
    return SimpleNamespace(messages=SimpleNamespace(create=scripted.create, batches=batches))


def test_a_batch_caches_each_result_under_its_synchronous_key(tmp_path):
    scripted = ScriptedClient(ANA_CLAIMS, entities_v22=ANA_ENTITIES_V22, relations_v22={(0, 1): ("tension", 0.8)})
    batches = FakeBatches(scripted)
    llm = fake_llm(tmp_path, batch_client(scripted, batches))
    record = {"doc_id": "ana", "text": ANA_TEXT}
    calls = planned_calls(llm, [record])
    notes = []
    res = BatchRunner(llm, tmp_path / "batch.json", poll_s=0, log=notes.append, sleep=lambda s: None).run(calls)
    assert res == {"batch_id": "msgbatch_1", "requests": 4, "succeeded": 4, "errored": 0, "expired": 0,
                   "canceled": 0, "rejected": 0, "unknown": 0}
    assert [r["custom_id"] for r in batches.created[0]] == [request_key(body) for body, *_ in calls]
    assert batches.polls == 2 and llm.usage["batch_calls"] == 4 and llm._reserved == 0
    one = {"input_tokens": 100, "output_tokens": 40}
    assert llm.usage["estimated_cost_usd"] == pytest.approx(cost_usd(llm.model, one)
                                                            + 4 * cost_usd(llm.model, one, batch=True))
    state = json.loads((tmp_path / "batch.json").read_text("utf-8"))
    assert state["ingested"] and set(state["keys"]) == {request_key(body) for body, *_ in calls}
    assert not any(t in json.dumps(state) for t, _ in ANA_CLAIMS)     # keys and tags only, no prompt text
    # the pass now answers every call from the cache but the relations call, which needs the inventory's answer,
    # and prices the batched ones at the batch rate
    n = len(scripted.calls)
    doc = run_document_dev(llm, record)
    assert scripted.calls[n:] == ["entities-relations"] and doc.analysis.report.tension_pairs[0]["a"] == 0
    assert [devpass.call_kind(c["tag"]) for c in doc.calls][0] == "extract"
    assert [c["batch"] for c in doc.calls] == [False, True, True, True, True, False]
    assert BatchRunner(llm, tmp_path / "batch.json", poll_s=0, log=notes.append).run(calls) == {
        "batch_id": None, "requests": 0}


def test_failed_batch_results_are_left_to_synchronous_calls_and_a_wait_resumes(tmp_path):
    scripted = ScriptedClient(ANA_CLAIMS, entities_v22=ANA_ENTITIES_V22)
    llm = fake_llm(tmp_path, scripted)
    calls = planned_calls(llm, [{"text": ANA_TEXT}])
    errored = request_key(calls[0][0])
    batches = FakeBatches(scripted, fail={errored}, lost=1)
    llm._client = batch_client(scripted, batches)
    runner = BatchRunner(llm, tmp_path / "batch.json", poll_s=0, log=lambda s: None, sleep=lambda s: None)
    with pytest.raises(ConnectionError):
        runner.run(calls)
    assert llm._reserved == 0 and not json.loads((tmp_path / "batch.json").read_text("utf-8"))["ingested"]
    res = runner.run(calls)                          # the same batch: nothing is sent again
    assert len(batches.created) == 1 and (res["succeeded"], res["errored"]) == (3, 1)
    n = len(scripted.calls)
    analyze_text(llm, ANA_TEXT, engine_version="2.2")
    assert scripted.calls[n:] == ["relate-v22", "entities-relations"] and scripted.bodies[n] == calls[0][0]
    # a batch whose worst case does not fit the budget is not sent
    llm2 = fake_llm(tmp_path / "b", batch_client(scripted, FakeBatches(scripted)), budget_tokens=0)
    with pytest.raises(BudgetExceeded):
        BatchRunner(llm2, tmp_path / "b" / "batch.json", log=lambda s: None).run(calls)
    assert llm2._client.messages.batches.created == [] and llm2._reserved == 0
    with pytest.raises(Exception, match="needs the API"):
        BatchRunner(LLM(cache_dir=tmp_path / "c"), tmp_path / "c" / "batch.json").run(calls)


# ------------------------------------------------------------------------------------------ fix E1: lexicon and derivation (§5)
SPEC_TABLE = {   # §5.3, as the spec writes it
    "sequence": {"subject": "after, later than, behind, followed",
                 "object": "before, earlier than, ahead of, preceded, prior to",
                 "max": "last, final", "min": "first, earliest"},
    "magnitude": {"subject": "older, taller, heavier, larger, bigger, longer, more, higher",
                  "object": "younger, shorter, lighter, smaller, less, fewer, lower",
                  "max": "oldest, tallest, heaviest, largest, biggest, longest, most, highest",
                  "min": "youngest, shortest, lightest, smallest, least, fewest, lowest"}}


def test_every_lexicon_entry_maps_as_the_spec_table_says():
    assert set(LEXICON) == set(SPEC_TABLE)
    for kind, sides in SPEC_TABLE.items():
        assert set(LEXICON[kind]) == set(sides)
        for side, words in sides.items():
            entries = tuple(w.strip() for w in words.split(","))
            assert LEXICON[kind][side] == entries
            for w in entries:
                assert lexicon_sense(kind, w) == side
                assert lexicon_sense(kind, f"  The {w.upper()}. ") == side
    assert normalize_comparative("older than") == "older" and normalize_comparative("the oldest") == "oldest"
    for kind, word in (("magnitude", "outranked"), ("sequence", "followed by"), ("sequence", "no later than"),
                       ("sequence", "older"), ("magnitude", "after"), ("other", "after"), (None, "older"),
                       ("sequence", "ranked higher"), ("magnitude", "not older")):
        assert lexicon_sense(kind, word) is None, (kind, word)


def test_uncovered_comparatives_and_other_attributes_keep_the_models_sense_and_overrides_are_logged():
    spec = statements(attributes=[("finish", "sequence"), ("standing", "other"), ("age", "magnitude")],
                      orders=[(0, "finish", "otto", "after", "kira"), (1, "standing", "kira", "ahead of", "lena"),
                              (2, "age", "ana", "outranked", "ben"), (3, "finish", "lena", "followed by", "kira")],
                      senses=[("finish", "after", "object"), ("standing", "ahead of", "subject"),
                              ("age", "outranked", "object"), ("finish", "followed by", "object")])
    eg = build_entity_graph_v22(spec, 4)
    assert [(r.attribute, r.a, r.b) for r in eg.relations] == [("finish", "otto", "kira"), ("standing", "kira", "lena"),
                                                               ("age", "ben", "ana"), ("finish", "kira", "lena")]
    assert eg.derivation["sense_overrides"] == [{"claim_id": 0, "attribute": "finish", "comparative": "after",
                                                 "model": "object", "lexicon": "subject"}]
    # a missing sense or one of the wrong kind gives no relation and is listed
    spec = statements(attributes=[("finish", "sequence")], orders=[(0, "finish", "otto", "outpaced", "kira")],
                      extremes=[(1, "finish", "kira", "top")], senses=[("finish", "top", "subject")])
    eg = build_entity_graph_v22(spec, 2)
    assert eg.relations == [] and [(u["claim_id"], u["sense"]) for u in eg.derivation["unresolved"]] == [(0, None),
                                                                                                        (1, "subject")]


def test_kira_first_and_otto_after_kira_is_no_cycle_even_with_a_wrong_model_sense():
    spec = statements(attributes=[("signing", "sequence")], extremes=[(0, "signing", "kira", "first")],
                      orders=[(1, "signing", "otto", "after", "kira")],
                      senses=[("signing", "first", "min"), ("signing", "after", "object")])
    eg = build_entity_graph_v22(spec, 2)
    assert find_contradictions(eg) == []
    assert sorted((r.a, r.b, r.derived_from_extreme) for r in eg.relations) == [("otto", "kira", False),
                                                                               ("otto", "kira", True)]
    assert [o["comparative"] for o in eg.derivation["sense_overrides"]] == ["after"]
    claims = claims_of("Kira signed up first.", "Otto signed up after Kira.")
    assert not analyze(build_signed_graph(claims, rel22()), eg, engine_version="2.2").verdict_inconsistent


def test_two_entities_both_first_are_a_superlative_collision():
    spec = statements(attributes=[("signing", "sequence")],
                      extremes=[(0, "signing", "kira", "first"), (1, "signing", "otto", "first")],
                      senses=[("signing", "first", "min")])
    eg = build_entity_graph_v22(spec, 2)
    [c] = find_contradictions(eg)
    assert (c.type, c.attribute, c.claim_ids) == ("superlative_collision", "signing", [0, 1])
    claims = claims_of("Kira signed up first.", "Otto signed up first.")
    report = analyze(build_signed_graph(claims, rel22()), eg, engine_version="2.2")
    assert report.verdict_clauses == ["entity"]
    assert [x.type for x in report.verdict_entity_contradictions] == ["superlative_collision"]
    mini = analyze_minimal(claims, rel22(), spec, engine_version="2.2")
    assert mini.verdict_clauses == ["entity"] and mini.entity_contradictions == report.verdict_entity_contradictions
    # first and last on the same entity, or a third party in between, is an ordinary order cycle, not a collision
    both = statements(attributes=[("signing", "sequence")], extremes=[(0, "signing", "kira", "first"),
                                                                      (1, "signing", "kira", "last")],
                      orders=[(2, "signing", "otto", "after", "lena")], senses=[("signing", "first", "min"),
                                                                                ("signing", "last", "max")])
    assert [c.type for c in find_contradictions(build_entity_graph_v22(both, 3))] == ["order_cycle"]


def test_mixed_comparatives_are_derived_by_the_lexicon():
    """The spec's §9 fixture lists "Ana is older than Ben." + "Ben is younger than Cy." + "Cy is older than Ana." as an
    order cycle, but it orders Cy > Ana > Ben and is consistent (flagged to Ian, CHANGELOG). The derivation gives
    that; the cycle the fixture means is checked on a set that has one. No sense is given: the lexicon decides."""
    first = [(0, "age", "ana", "older than", "ben"), (1, "age", "ben", "younger than", "cy")]
    for third in [(2, "age", "cy", "younger than", "ana"), (2, "age", "cy", "older than", "ana")]:
        eg = build_entity_graph_v22(statements(attributes=[("age", "magnitude")], orders=first + [third]), 3)
        assert find_contradictions(eg) == [] and eg.derivation["unresolved"] == []
    cycle = [(0, "age", "ana", "older than", "ben"), (1, "age", "cy", "younger than", "ben"),
             (2, "age", "cy", "older than", "ana")]
    eg = build_entity_graph_v22(statements(attributes=[("age", "magnitude")], orders=cycle), 3)
    [c] = find_contradictions(eg)
    assert (c.type, c.claim_ids, sorted(c.entities)) == ("order_cycle", [0, 1, 2], ["ana", "ben", "cy"])
    assert sorted((r.a, r.b) for r in eg.relations) == [("ana", "ben"), ("ben", "cy"), ("cy", "ana")]


def test_an_extreme_makes_no_edge_to_its_own_equality_class():
    spec = statements(attributes=[("finish", "sequence")], same_different=[(0, "finish", "same", "kira", "otto")],
                      extremes=[(1, "finish", "kira", "first")], orders=[(2, "finish", "lena", "after", "otto")])
    eg = build_entity_graph_v22(spec, 3)
    assert sorted((r.a, r.b) for r in eg.relations if r.kind == "greater") == [("lena", "kira"), ("lena", "otto")]
    assert eg.derivation["superlatives"] == [{"claim_id": 1, "attribute": "finish", "entity": "kira",
                                              "extreme": "min", "edges": 1}]
    assert eg.derivation["extreme_edges"] == 1 and find_contradictions(eg) == []
    alone = statements(attributes=[("finish", "sequence")], extremes=[(1, "finish", "kira", "first")],
                       orders=[(2, "finish", "lena", "after", "otto")])
    assert build_entity_graph_v22(alone, 3).derivation["superlatives"][0]["edges"] == 2


def test_a_negated_comparative_gives_no_order_edge_and_is_listed(tmp_path):
    spec = statements(attributes=[("signing", "sequence")], unsupported=[0, 7], entities=("kira", "otto"))
    eg = build_entity_graph_v22(spec, 1)
    assert eg.relations == [] and eg.derivation["unsupported_order_claims"] == [0]
    text = "Otto did not sign up before Kira."
    spec = statements(attributes=[("signing", "sequence")], unsupported=[0], entities=("kira", "otto"))
    fake = ScriptedClient([(text, "asserted")], entities_v22=spec.model_dump())
    a = analyze_text(fake_llm(tmp_path, fake), text, engine_version="2.2")
    derivation = a.diagnostics["entity_derivation"]
    assert derivation["unsupported_order_claims"] == [0] and not a.report.verdict_inconsistent
    # "before" puts the claim on the coverage net, and being listed as unsupported covers it
    assert derivation["coverage"]["lexicon_matched"] == [0] and derivation["coverage"]["uncovered"] == []
    assert "entities-coverage" not in fake.calls


def test_a_restricted_superlative_is_listed_and_not_expanded():
    """§9: "Kira signed first of the judges." + "Otto signed first." is no contradiction."""
    first = [(0, "signing", "kira", "first", 0.9, "of the judges"), (1, "signing", "otto", "first")]
    spec = statements(attributes=[("signing", "sequence")], extremes=first, senses=[("signing", "first", "min")])
    eg = build_entity_graph_v22(spec, 2)
    assert find_contradictions(eg) == [] and eg.relations == []
    assert eg.derivation["restricted_extremes"] == [{"claim_id": 0, "attribute": "signing", "entity": "kira",
                                                     "comparative": "first", "restriction": "of the judges"}]
    assert [(s["claim_id"], s["edges"]) for s in eg.derivation["superlatives"]] == [(1, 0)]
    claims = claims_of("Kira signed first of the judges.", "Otto signed first.")
    assert not analyze(build_signed_graph(claims, rel22()), eg, engine_version="2.2").verdict_inconsistent
    assert analyze_minimal(claims, rel22(), spec, engine_version="2.2").verdict_clauses == []
    # nor is the restricted entity another entity's partner: Otto's "first" reaches Lena only
    spec = statements(attributes=[("signing", "sequence")], extremes=first,
                      orders=[(2, "signing", "lena", "after", "otto")], senses=[("signing", "first", "min")])
    assert [(r.a, r.b, r.derived_from_extreme) for r in build_entity_graph_v22(spec, 3).relations] == [
        ("lena", "otto", False), ("lena", "otto", True)]
    # a blank restriction restricts nothing
    blank = [(0, "signing", "kira", "first", 0.9, "  "), (1, "signing", "otto", "first")]
    spec = statements(attributes=[("signing", "sequence")], extremes=blank, senses=[("signing", "first", "min")])
    assert [c.type for c in find_contradictions(build_entity_graph_v22(spec, 2))] == ["superlative_collision"]


def test_iteration_0s_statements_are_derived_as_the_entity_steps_are():
    """Step 0 and iteration 0's saved analyses are read by the same derivation."""
    rng = random.Random(7)
    for _ in range(200):
        n = rng.randint(2, 7)
        kw = _random_statements(rng, n, restrictions=False)
        a, b = build_entity_graph_v22(statements(**kw), n), build_entity_graph_v22(statements(**kw, iteration=0), n)
        assert (a.relations, a.arity, a.arity_span, a.mentions, a.dropped) == (b.relations, b.arity, b.arity_span,
                                                                               b.mentions, b.dropped)
        assert {k: v for k, v in a.derivation.items() if k in b.derivation} == b.derivation
        assert set(a.derivation) - set(b.derivation) == {"coverage", "schema_fallback", "invalid_ids", "skipped"}


def test_the_entity_prompts_ask_for_one_inventory_verbatim_statements_and_the_net():
    inventory = prompts.ENTITY_INVENTORY_SYSTEM_V2_2
    for phrase in ("Merge mentions that refer to the same entity", "each listed once under one canonical lower-case "
                   "key", '"sequence"', '"magnitude"', '"other"', "other_greater_means", "arity",
                   "do not add any from world knowledge"):
        assert phrase in inventory, phrase
    for s in (prompts.ENTITY_RELATIONS_SYSTEM_V2_2, prompts.ENTITY_COVERAGE_SYSTEM_V2_2):
        for phrase in ("copied verbatim", "never swapped", "exactly one sense", "restriction copies verbatim",
                       '"of the judges"', "unsupported_order_claims", '"not before"',
                       "using only the listed entity ids and attribute keys",
                       "do not infer relations or superlatives that follow from other claims"):
            assert phrase in s, phrase
    coverage = prompts.ENTITY_COVERAGE_SYSTEM_V2_2
    for phrase in ("list it under none", "one-sentence reason", '"for the first time"', '"more people came"'):
        assert phrase in coverage, phrase
    assert not hasattr(prompts, "ENTITY_SYSTEM_V2_2")        # iteration 0's single call is gone
    claims = claims_of("Kira signed first.", "Otto came.", "Lena left after Otto.")
    entities, attributes = {"kira": ["Kira"], "otto": ["Otto"], "lena": []}, {
        "signing": SimpleNamespace(order_kind="sequence", other_greater_means=None),
        "standing": SimpleNamespace(order_kind="other", other_greater_means="a better rank"),
        "team": SimpleNamespace(order_kind=None, other_greater_means=None)}
    user = prompts.entity_relations_user(claims, entities, attributes)
    assert user == ("Claims:\n0. Kira signed first.\n1. Otto came.\n2. Lena left after Otto.\n\n"
                    "Entities (id: mentions):\n- kira: Kira\n- otto: Otto\n- lena\n\n"
                    "Attributes (key, order):\n- signing (sequence, greater = later)\n"
                    "- standing (other, greater = a better rank)\n- team (no order)")
    listed = prompts.entity_coverage_user(claims, [2], entities, attributes)
    assert listed.startswith("Claims:\n2. Lena left after Otto.\n\nEntities") and "Kira signed" not in listed


# ------------------------------------------------------------------------------------------ fix E1: the entity steps (§5.2–§5.7)
NET_CLAIMS = [("Kira signed up first.", "asserted"), ("Otto signed up after Kira.", "asserted"),
              ("Lena came for the first time.", "asserted"), ("Rui said more people came.", "quoted"),
              ("The hall was cold.", "asserted")]
NET_TEXT = " ".join(t for t, _ in NET_CLAIMS)


def net_steps(**kw):
    """The relations call states claims 0 and 1; claims 2 and 3 hold a lexicon word and no statement."""
    return statements(attributes=[("signing", "sequence")], extremes=[(0, "signing", "kira", "first")],
                      orders=[(1, "signing", "otto", "after", "kira")],
                      senses=[("signing", "first", "min"), ("signing", "after", "subject")], entities=("lena",), **kw)


def entity_tags(path, text=NET_TEXT):
    stem = v22_tag(text_tag(text))
    return [(r["tag"].removeprefix(stem), r.get("error")) for r in log_rows(path) if "-entities-" in r["tag"]]


def test_the_entity_steps_think_adaptively_and_extraction_and_scoring_do_not(tmp_path):
    fake = ScriptedClient(NET_CLAIMS, entities_v22=net_steps().model_dump())
    llm = fake_llm(tmp_path, fake)
    analyze_text(llm, NET_TEXT, engine_version="2.2")
    assert [k for k in fake.calls if k.startswith("entities-")] == ["entities-inventory", "entities-relations",
                                                                     "entities-coverage"]
    for kind, body in zip(fake.calls, fake.bodies):
        if kind.startswith("entities-"):
            assert body["thinking"] == {"type": "adaptive"}, kind          # the default effort: no effort field
            assert body["max_tokens"] == DEFAULT.llm_max_tokens_entity_steps and "effort" not in body["output_config"]
        else:
            assert body["thinking"] == {"type": "disabled"}, kind
    assert {r["thinking"] for r in log_rows(tmp_path) if "-entities-" in r["tag"]} == {"adaptive"}
    # max_tokens covers thinking and output, and stays below the SDK's ten-minute limit for a non-streaming call
    assert 8000 <= DEFAULT.llm_max_tokens_entity_steps <= 21_333
    # the setting is part of the request, so of its cache key
    kw = dict(system="S", user="U", max_tokens=16000, schema=InventoryV22)
    assert len({request_hash(llm.request(**kw, thinking=t)) for t in ("adaptive", False, True)}) == 3
    # a model that does not take adaptive thinking keeps its default (no thinking field)
    llm.model = "claude-haiku-4-5-20251001"
    assert "thinking" not in llm.request(**kw, thinking="adaptive") and llm.thinking_mode("adaptive") == "off"


def test_the_per_document_schema_admits_only_the_inventorys_ids_and_the_documents_claims():
    entities, attributes = {"kira": ["Kira"], "otto": ["Otto"]}, {"signing": None}
    schema = document_schema(EntityRelationsV22, entities, attributes, [0, 1])
    order = {"claim_id": 1, "attribute": "Signing", "subject": "OTTO", "comparative": "after", "object": "kira",
             "confidence": 0.9}
    ok = {**NO_STATEMENTS, "orders": [order], "unsupported_order_claims": [0]}
    parsed = schema.model_validate(ok)
    assert isinstance(parsed, EntityRelationsV22) and isinstance(parsed.orders[0], OrderStatement)
    assert (parsed.orders[0].attribute, parsed.orders[0].subject) == ("signing", "otto")     # case-insensitive
    same = {"claim_id": 0, "attribute": "signing", "kind": "same", "a": "kira", "b": "otto", "confidence": 0.9}
    extreme = {"claim_id": 0, "attribute": "signing", "entity": "kira", "comparative": "first", "restriction": None,
               "confidence": 0.9}
    sense = {"attribute": "signing", "comparative": "after", "greater_side": "subject"}
    schema.model_validate({**ok, "same_different": [same], "extremes": [extreme], "senses": [sense]})
    for key, item, field, value in [("orders", order, "subject", "lena"), ("orders", order, "attribute", "arrival"),
                                    ("orders", order, "claim_id", 2), ("same_different", same, "b", "lena"),
                                    ("extremes", extreme, "entity", "lena"), ("senses", sense, "attribute", "rank")]:
        with pytest.raises(ValidationError):
            schema.model_validate({**ok, key: [{**item, field: value}]})
    with pytest.raises(ValidationError):
        schema.model_validate({**ok, "unsupported_order_claims": [2]})
    sent = output_schema(schema)
    assert "description" not in json.dumps(sent)                    # no class docstring goes out with the schema
    subject = sent["$defs"]["OrderStatement"]["properties"]["subject"]
    assert subject["enum"] == ["kira", "otto"] and sent["$defs"]["OrderStatement"]["properties"]["attribute"][
        "const"] == "signing"
    # the coverage call's schema: the same ids, the listed claims only, and a none entry for each
    coverage = document_schema(EntityCoverageV22, entities, attributes, [1])
    coverage.model_validate({**ok, "unsupported_order_claims": [], "none": [{"claim_id": 1, "reason": "No order."}]})
    for bad in ({"unsupported_order_claims": [0]}, {"none": [{"claim_id": 0, "reason": "No order."}]}):
        with pytest.raises(ValidationError):
            coverage.model_validate({**ok, "unsupported_order_claims": [], "none": [], **bad})
    # the fallback: the same fields, plain ids
    plain = document_schema(EntityRelationsV22)
    assert plain.model_validate({**ok, "orders": [{**order, "subject": "lena", "claim_id": 9}]}).orders[0].subject == (
        "lena")
    assert "enum" not in json.dumps(output_schema(plain)["$defs"]["OrderStatement"])


def test_a_rejected_schema_falls_back_to_plain_ids_and_replays_from_cache_and_fixtures(tmp_path, monkeypatch):
    answer = net_steps().model_dump()
    answer["relations"]["orders"].append({"claim_id": 1, "attribute": "signing", "subject": "zed",
                                          "comparative": "after", "object": "kira", "confidence": 0.9})
    fake = ScriptedClient(NET_CLAIMS, entities_v22=answer, reject_v22={"relations", "coverage"})
    monkeypatch.setenv(RECORD_ENV, "1")
    llm = fake_llm(tmp_path, fake)
    a = analyze_text(llm, NET_TEXT, engine_version="2.2")
    derivation = a.entities.derivation
    assert derivation["schema_fallback"] == ["relations", "coverage"] and derivation["invalid_ids"] == 1
    assert {(r.claim_id, r.a, r.b) for r in a.entities.relations if not r.derived_from_extreme} == {(1, "otto", "kira")}
    assert entity_tags(tmp_path) == [("-entities-inventory", None), ("-entities-relations", "LLMSchemaRejected"),
                                     ("-entities-relations-fallback", None), ("-entities-coverage", "LLMSchemaRejected"),
                                     ("-entities-coverage-fallback", None)]
    stem = v22_tag(text_tag(NET_TEXT))
    rejected = json.loads((tmp_path / "fixtures" / f"{stem}-entities-relations.json").read_text("utf-8"))
    assert rejected["rejected"] == SCHEMA_TOO_COMPLEX and "output" not in rejected
    # from the cache: the same fallbacks, and the API is not asked
    no_api = SimpleNamespace(messages=SimpleNamespace(create=lambda **body: pytest.fail("the API was called")))
    again = analyze_text(fake_llm(tmp_path, no_api), NET_TEXT, engine_version="2.2")
    assert again.entities.derivation == derivation and again.entities.relations == a.entities.relations
    # from the fixtures, in dry-run mode
    monkeypatch.delenv(RECORD_ENV)
    dry = LLM(cache_dir=tmp_path / "dry", fixture_dir=tmp_path / "fixtures")
    replayed = analyze_text(dry, NET_TEXT, engine_version="2.2")
    assert dry.dry_run and dry.usage["fixture_hits"] == len(fake.calls) and dry.usage["api_calls"] == 0
    assert replayed.entities.derivation == derivation


def test_the_coverage_net_makes_one_follow_up_for_the_uncovered_claims_only(tmp_path):
    assert lexicon_words_in("For the FIRST time,  more people came\nbefore noon, earlier than Rui.") == [
        "first", "more", "before", "earlier than"]
    assert lexicon_words_in("Firstly, the moreover.") == []
    fake = ScriptedClient(NET_CLAIMS, entities_v22=net_steps().model_dump())
    a = analyze_text(fake_llm(tmp_path / "a", fake), NET_TEXT, engine_version="2.2")
    steps = a.entity_spec
    assert (steps.lexicon_matched, steps.uncovered) == ([0, 1, 2, 3], [2, 3])       # the quoted claim included
    [i] = [k for k, kind in enumerate(fake.calls) if kind == "entities-coverage"]
    user = fake.bodies[i]["messages"][0]["content"]
    assert user.startswith("Claims:\n2. Lena came for the first time.\n3. Rui said more people came.\n\nEntities")
    assert not any(t in user for t in (NET_CLAIMS[0][0], NET_CLAIMS[1][0], NET_CLAIMS[4][0]))
    assert a.entities.derivation["coverage"] == {"lexicon_matched": [0, 1, 2, 3], "uncovered": [2, 3],
                                                 "follow_up": True, "statements_added": 0, "none": [2, 3],
                                                 "still_uncovered": []}
    assert [(n.claim_id, n.reason) for n in steps.coverage.none] == [(2, "Scripted."), (3, "Scripted.")]
    # covered claims trigger none
    fake = ScriptedClient(NET_CLAIMS[:2], entities_v22=net_steps().model_dump())
    analyze_text(fake_llm(tmp_path / "b", fake), " ".join(t for t, _ in NET_CLAIMS[:2]), engine_version="2.2")
    assert "entities-coverage" not in fake.calls
    # a statement is added, a claim the follow-up leaves out stays uncovered, and there is no second follow-up
    spec = net_steps(coverage=dict(orders=[(2, "signing", "lena", "after", "otto")]), uncovered=[2, 3])
    fake = ScriptedClient(NET_CLAIMS, entities_v22=spec.model_dump())
    b = analyze_text(fake_llm(tmp_path / "c", fake), NET_TEXT, engine_version="2.2")
    assert fake.calls.count("entities-coverage") == 1
    cov = b.entities.derivation["coverage"]
    assert (cov["statements_added"], cov["none"], cov["still_uncovered"]) == (1, [], [3])
    assert {(r.claim_id, r.a, r.b) for r in b.entities.relations if not r.derived_from_extreme} == {
        (1, "otto", "kira"), (2, "lena", "otto")}
    # the net never removes or edits: under the fallback schema, statements for claims it did not list are not taken
    answer = spec.model_dump()
    answer["coverage"]["orders"].append({"claim_id": 1, "attribute": "signing", "subject": "kira",
                                         "comparative": "after", "object": "otto", "confidence": 0.9})
    answer["coverage"]["unsupported_order_claims"] = [0]
    fake = ScriptedClient(NET_CLAIMS, entities_v22=answer, reject_v22={"coverage"})
    c = analyze_text(fake_llm(tmp_path / "d", fake), NET_TEXT, engine_version="2.2")
    assert c.entities.derivation["invalid_ids"] == 2 and c.entities.derivation["schema_fallback"] == ["coverage"]
    assert c.entities.relations == b.entities.relations and c.entities.derivation["unsupported_order_claims"] == []
    # a sense the follow-up repeats does not replace the relations call's
    spec = statements(attributes=[("standing", "other")], orders=[(0, "standing", "kira", "outranked", "otto")],
                      senses=[("standing", "outranked", "subject")], uncovered=[1],
                      coverage=dict(orders=[(1, "standing", "lena", "outranked", "kira")],
                                    senses=[("standing", "outranked", "object")]))
    eg = build_entity_graph_v22(spec, 2)
    assert [(r.a, r.b) for r in eg.relations] == [("kira", "otto"), ("lena", "kira")]
    assert eg.derivation["duplicate_senses"] == 1


def test_with_no_entity_or_attribute_the_later_entity_steps_are_skipped(tmp_path):
    fake = ScriptedClient(NET_CLAIMS)                               # the inventory lists nothing
    a = analyze_text(fake_llm(tmp_path, fake), NET_TEXT, engine_version="2.2")
    assert [k for k in fake.calls if k.startswith("entities-")] == ["entities-inventory"]
    assert a.entity_spec.skipped == "the inventory lists no entity or no attribute" and a.entities.relations == []
    assert a.entities.derivation["coverage"]["still_uncovered"] == [0, 1, 2, 3]
    llm = fake_llm(tmp_path / "none", ScriptedClient([]))
    steps = extract_entity_steps_v22(llm, ClaimList(claims=[]), tag="empty")
    assert steps.skipped == "no claims" and llm.usage["calls"] == 0


def test_the_entity_calls_are_broken_out_by_step_with_their_thinking_tokens():
    def call(tag, thinking=0, output=0):
        return {"tag": tag, "usage": {"input_tokens": 100 if output else 0, "output_tokens": output,
                                      "thinking_tokens": thinking}, "batch": False}

    calls = [call("d-v22-extract", 0, 50), call("d-v22-entities-inventory", 250, 300),
             call("d-v22-entities-relations"), call("d-v22-entities-relations-fallback", 900, 1000),
             call("d-v22-entities-coverage", 40, 60)]
    assert [devpass.entity_step(c["tag"]) for c in calls] == [None, "inventory", "relations", "relations", "coverage"]
    assert devpass.entity_step("d-entities") is None and devpass.call_kind("d-v22-entities-coverage") == "entities"
    cost = devpass.cost_of(calls, DEFAULT.llm_model)
    steps = cost["entity_steps"]
    assert cost["by_call"]["entities"]["calls"] == 4 and cost["by_call"]["entities"]["thinking_tokens"] == 1190
    assert [(steps[s]["calls"], steps[s]["thinking_tokens"]) for s in devpass.ENTITY_STEPS] == [(1, 250), (2, 900),
                                                                                                  (1, 40)]
    assert sum(s["usd"] for s in steps.values()) == pytest.approx(cost["by_call"]["entities"]["usd"])


# ------------------------------------------------------------------------------------------ §6 threshold rule
def synthetic_row(doc_id, variant, flagged_at, cycle_type="order_cycle"):
    """A development row whose three methods flag the document at exactly the thresholds in ``flagged_at``."""
    at = {}
    for t in TAUS:
        f = t in flagged_at
        at[tau_key(t)] = {"engine": f, "engine_clauses": ["direct"] if f else [], "minimal": f,
                          "minimal_clauses": ["direct"] if f else [], "minimal_localized": False, "pairwise": f,
                          "pairwise_pairs": [], "evidence": {"direct": [], "cycle": None, "entity": []}}
    return {"doc_id": doc_id, "base": 0, "variant": variant, "cycle_type": cycle_type, "premise_contradicted": False,
            "n_claims": 3, "sampled": False, "by_tau": at, "localized_engine": False,
            "carried": {c: {"verdict": False, "localized": False} for c in CARRIED}, "planted_found": [],
            "relations_found": [], "arity": "missing", "harmony": None, "harmony_reason": None, "conflict": 0.0,
            "unanchored": False, "premise_top3": None, "planted_pair_relations": []}


def test_the_threshold_rule_takes_the_best_mean_f1_and_the_lowest_threshold_on_a_tie():
    assert TAUS == (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9)
    rows = [synthetic_row("c1", "consistent", set(TAUS[:3])), synthetic_row("d1", "direct", set(TAUS)),
            synthetic_row("y1", "cycle", set(TAUS))]
    curve = threshold_curve(rows, "engine")
    assert [round(p["mean"], 6) for p in curve] == [0.666667] * 3 + [1.0] * 6
    assert select_threshold(curve) == 0.65
    assert threshold_rule(rows)["selected"] == {"engine": 0.65, "minimal": 0.65, "pairwise": 0.65}
    assert select_threshold([{"tau": t, "mean": 0.5} for t in TAUS]) == 0.5
    assert select_threshold([{"tau": t, "mean": 0.9 if t in (0.7, 0.85) else 0.5} for t in reversed(TAUS)]) == 0.7
    assert select_threshold([{"tau": 0.5, "mean": 0.7}, {"tau": 0.55, "mean": 0.7 + 1e-15}]) == 0.5
    # a detection lost above 0.75 lowers recall there: the rule stops at the last threshold before it
    rows[1] = synthetic_row("d1", "direct", set(TAUS[:6]))
    assert threshold_rule(rows)["selected"]["engine"] == 0.65


# ------------------------------------------------------------------------------------------ minimal engine under rev. 2.2
def test_the_minimal_engine_follows_the_version_and_the_threshold():
    claims = claims_of("A.", "B.")
    rels = rel22((0, 1, "contradicts", 0.6))
    assert analyze_minimal(claims, rels, None, engine_version="2.2", threshold=0.5).verdict_clauses == ["direct"]
    assert not analyze_minimal(claims, rels, None, engine_version="2.2", threshold=0.65).verdict_inconsistent
    assert not analyze_minimal(claims, rel22((0, 1, "tension", 0.99)), None, engine_version="2.2").verdict_inconsistent
    with pytest.raises(ValueError, match="engine version"):
        analyze_minimal(claims, rels, None, engine_version="3")


CONFIDENCES = (0.0, 0.3, 0.49, 0.5, 0.51, 0.55, 0.62, 0.7, 0.78, 0.9, 0.95, 1.0, 1.7, -0.2, math.nan, math.inf)


def _random_v22(rng: random.Random):
    n = rng.randint(2, 7)
    rels = []
    for _ in range(rng.randint(0, 3 * n)):
        a, b = rng.sample(range(n), 2)
        rels.append((a, b, rng.choice(("supports", "contradicts", "contradicts", "tension", "unrelated")),
                     rng.choice(CONFIDENCES)))
    kinds = [rng.choice(("asserted", "asserted", "premise", "quoted")) for _ in range(n)]
    claims = claims_of(*[f"Claim {i}." for i in range(n)], kinds=kinds)
    return claims, rel22(*rels), statements(**_random_statements(rng, n))


def _random_statements(rng: random.Random, n: int, restrictions: bool = True) -> dict:
    """statements()'s arguments for n claims: ids, senses and confidences drawn to hit every derivation path."""
    names, conf = ["ana", "ben", "cy", "dee"], CONFIDENCES[:13]
    comparatives = ("after", "before", "ahead of", "older than", "younger", "outranked", "followed by", "behind")
    superlatives = ("first", "last", "oldest", "youngest", "top")
    attributes = [("finish", rng.choice(("sequence", "magnitude", "other", None))),
                  ("age", rng.choice(("magnitude", "sequence", None))),
                  ("team", None, rng.choice(("binary", "multi", "unknown")))]
    same_different = [(rng.randrange(n), rng.choice(("team", "finish", "age")), rng.choice(("same", "different")),
                       *rng.sample(names, 2), rng.choice(conf)) for _ in range(rng.randint(0, 4))]
    orders = []
    for _ in range(rng.randint(0, 5)):
        s, o = rng.sample(names, 2)
        orders.append((rng.randrange(n), rng.choice(("finish", "age")), s, rng.choice(comparatives), o,
                       rng.choice(conf)))
    extremes = [(rng.randrange(n), rng.choice(("finish", "age")), rng.choice(names), rng.choice(superlatives),
                 rng.choice(conf), rng.choice((None, None, None, "of the judges")) if restrictions else None)
                for _ in range(rng.randint(0, 3))]
    used = {(o[1], o[3]) for o in orders} | {(e[1], e[3]) for e in extremes}
    senses = [(att, comp, rng.choice(("subject", "object", "max", "min"))) for att, comp in sorted(used)
              if rng.random() < 0.8]
    return dict(attributes=attributes, same_different=same_different, orders=orders, extremes=extremes,
                senses=senses)


def test_the_two_engines_agree_on_random_rev_2_2_documents():
    rng = random.Random(20260925)
    fired = Counter()
    for _ in range(600):
        claims, relations, spec = _random_v22(rng)
        tau = rng.choice(TAUS)
        eg = build_entity_graph_v22(spec, len(claims.claims))
        full = analyze(build_signed_graph(claims, relations), eg, threshold=tau, engine_version="2.2")
        mini = analyze_minimal(claims, relations, spec, engine_version="2.2", threshold=tau)
        assert mini.direct_contradictions == full.direct_contradictions
        assert mini.entity_contradictions == full.verdict_entity_contradictions
        assert mini.verdict_clauses == [c for c in full.verdict_clauses if c != "claim_balance"]
        fired.update(full.verdict_clauses)
        fired.update(c.type for c in full.verdict_entity_contradictions)
        fired["restricted"] += len(eg.derivation["restricted_extremes"])
    assert fired["direct"] >= 20 and fired["entity"] >= 20 and fired["claim_balance"] > 0
    assert fired["superlative_collision"] > 0 and fired["order_cycle"] > 0 and fired["restricted"] > 0


ISOLATION_V22 = """
import json
import sys
from dataclasses import dataclass

sys.path.insert(0, sys.argv[1])
before = set(sys.modules)
from xon.llm.minimal import analyze_minimal


@dataclass(frozen=True)
class Claim:
    id: int
    kind: str


@dataclass(frozen=True)
class Relation:
    a: int
    b: int
    relation: str
    confidence: float


@dataclass(frozen=True)
class Attribute:
    key: str
    arity: str
    arity_span: object
    order_kind: object
    other_greater_means: object


@dataclass(frozen=True)
class Entity:
    id: str
    mentions: list


@dataclass(frozen=True)
class Extreme:
    claim_id: int
    attribute: str
    entity: str
    comparative: str
    restriction: object
    confidence: float


@dataclass(frozen=True)
class Sense:
    attribute: str
    comparative: str
    greater_side: str


@dataclass(frozen=True)
class Inventory:
    entities: list
    attributes: list


@dataclass(frozen=True)
class Statements:
    same_different: list
    orders: list
    extremes: list
    senses: list
    unsupported_order_claims: list


@dataclass(frozen=True)
class Steps:
    inventory: Inventory
    relations: Statements
    coverage: object
    lexicon_matched: list
    uncovered: list
    schema_fallback: list
    skipped: object


inventory = Inventory([Entity("kira", ["Kira"]), Entity("otto", ["Otto"])],
                      [Attribute("signing", "unknown", None, "sequence", None)])
relations = Statements([], [], [Extreme(0, "signing", "Kira", "first", None, 0.9),
                                Extreme(1, "signing", "Otto", "First", None, 0.9)],
                       [Sense("signing", "first", "min")], [])
spec = Steps(inventory, relations, None, [0, 1], [], [], None)
report = analyze_minimal([Claim(0, "asserted"), Claim(1, "asserted")], [Relation(0, 1, "tension", 0.95)], spec,
                         engine_version="2.2", threshold=0.7)
print(json.dumps({"clauses": report.verdict_clauses, "types": [c.type for c in report.entity_contradictions],
                  "loaded": sorted(set(sys.modules) - before)}))
"""


def test_the_minimal_engine_under_rev_2_2_runs_on_the_standard_library_alone(tmp_path):
    """As the rev. 2.1 isolation test (test_minimal_engine.py, unchanged), under rev. 2.2: the lexicon module is the
    one addition."""
    script = tmp_path / "isolation_v22.py"
    script.write_text(textwrap.dedent(ISOLATION_V22), "utf-8")
    out = subprocess.run([sys.executable, str(script), str(ROOT)], capture_output=True, text=True, check=True)
    res = json.loads(out.stdout)
    assert res["clauses"] == ["entity"] and res["types"] == ["superlative_collision"]
    loaded = res["loaded"]
    assert {m for m in loaded if m.split(".")[0] == "xon"} == {"xon", "xon.llm", "xon.llm.minimal",
                                                                "xon.llm.entity_consistency", "xon.llm.comparatives"}
    assert [m for m in loaded if m.split(".")[0] not in sys.stdlib_module_names | {"xon"}] == []
    assert not {"numpy", "scipy", "networkx", "pydantic", "anthropic", "xon.llm.client"} & set(loaded)


# ------------------------------------------------------------------------------------------ the development pass (§7, §8)
COMPARATIVE = {"is older than": ("older than", "magnitude"), "arrived before": ("before", "sequence"),
               "is taller than": ("taller than", "magnitude"), "finished ahead of": ("ahead of", "sequence")}
PAIR_TEXTS = re.compile(r"^A \(claim \d+\): (.*)\nB \(claim \d+\): (.*)$", re.S)


class Oracle22(Oracle):
    """The corpus oracle under rev. 2.2: one pair per relation call (a premise and the claim of the same plan are
    labeled tension, to carry the label through the pass), and the plans' relational sentences as statements, each
    order with its claim's own subject, comparative and object and the lexicon's sense; the coverage call answers
    none for every claim it lists."""

    def create(self, **body):
        kind = call_kind(body["system"])
        user = body["messages"][0]["content"]
        if kind == "relate-v22":
            self.calls.append(kind)
            a, b = single_pair(user)
            texts = dict(zip((a, b), PAIR_TEXTS.match(user).groups()))
            out = self._relation(texts, a, b)
            if out["relation"] == "unrelated" and any({texts[a], texts[b]} == {p.premise, p.claim} for p in self.plans):
                out = dict(out, relation="tension", confidence=0.8)
            return response(out)
        if kind.startswith("entities-"):
            self.calls.append(kind)
            claims = _numbered(user)
            found = self._statements(claims)
            if kind == "entities-inventory":
                return response({"entities": found["entities"], "attributes": found["attributes"]})
            if kind == "entities-relations":
                return response({k: found[k] for k in NO_STATEMENTS})
            return response({**NO_STATEMENTS, "none": [{"claim_id": c, "reason": "It compares no listed entities."}
                                                       for c in sorted(claims)]})
        return super().create(**body)

    def _statements(self, claims):
        ids = {t: i for i, t in claims.items()}
        atts, names, same_different, orders, senses = {}, set(), [], [], {}
        for p in self.plans:
            for r in dict.fromkeys(p.control_relations + p.cycle_relations):
                if r.sentence not in ids:
                    continue
                c, order_kind = ids[r.sentence], None
                names |= {r.a, r.b}
                if r.kind == "greater":
                    phrase = next(ph for ph in COMPARATIVE if f" {ph} " in r.sentence)
                    subject, obj = r.sentence.rstrip(".").split(f" {phrase} ")
                    comparative, order_kind = COMPARATIVE[phrase]
                    orders.append({"claim_id": c, "attribute": p.attribute, "subject": subject.lower(),
                                   "comparative": comparative, "object": obj.lower(), "confidence": 0.95})
                    senses[(p.attribute, comparative)] = lexicon_sense(order_kind, comparative)
                else:
                    same_different.append({"claim_id": c, "attribute": p.attribute, "kind": r.kind,
                                           "a": r.a.lower(), "b": r.b.lower(), "confidence": 0.95})
                arity = "binary" if p.arity_cycle in ids else "multi" if p.arity_control in ids else "unknown"
                atts[p.attribute] = {"key": p.attribute, "arity": arity, "arity_span": None,
                                     "order_kind": order_kind, "other_greater_means": None}
        return {"entities": [{"id": n.lower(), "mentions": [n]} for n in sorted(names)],
                "attributes": list(atts.values()), "same_different": same_different, "orders": orders,
                "extremes": [], "senses": [{"attribute": a, "comparative": c, "greater_side": s}
                                           for (a, c), s in senses.items()], "unsupported_order_claims": []}


class Garbled22(Oracle22):
    """Every pair that starts at claim 0 gets a malformed rationale, also when it is scored again."""

    def _relation(self, claims, a, b):
        out = super()._relation(claims, a, b)
        return {**out, "rationale": GARBLED} if a == 0 else out


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    """The sample corpus's run of record under rev. 2.1, by the rev. 2.1 oracle: its cache, its rows and a corpus
    file, as the development pass finds them."""
    root = tmp_path_factory.mktemp("rev22")
    plans, records = sample()
    llm = LLM(cache_dir=root / "cache", client=Oracle(plans), fixture_dir=root / "fixtures")
    runs = run_corpus(llm, records, log=lambda s: None)
    eval_script = _script("run_consistency_eval.py")
    (root / "record").mkdir()
    (root / "record" / "documents.jsonl").write_text(eval_script._jsonl([document_row(r) for r in runs]), "utf-8")
    (root / "corpus.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), "utf-8")
    return SimpleNamespace(root=root, plans=plans, records=records)


def _pass_llms(monkeypatch, script, recorded, client_type, cache):
    made = []

    def factory(budget_tokens=None, cfg=DEFAULT):
        llm = LLM(cache_dir=cache, client=client_type(recorded.plans), fixture_dir=recorded.root / "fixtures",
                  budget_tokens=budget_tokens, cfg=cfg)
        made.append(llm)
        return llm

    monkeypatch.setattr(script, "LLM", factory)
    return made


def _copy_cache(recorded, to):
    to.mkdir()
    for p in (recorded.root / "cache").glob("*.json"):
        (to / p.name).write_bytes(p.read_bytes())
    return to


def test_the_development_pass_runs_offline_and_writes_labeled_diagnostics(recorded, tmp_path, monkeypatch):
    script = _script("run_rev22_dev.py")
    made = _pass_llms(monkeypatch, script, recorded, Oracle22, _copy_cache(recorded, tmp_path / "cache"))
    out = tmp_path / "out"
    argv = ["--corpus", str(recorded.root / "corpus.jsonl"), "--record-run", str(recorded.root / "record"),
            "--budget", "100000000", "--out", str(out)]
    assert script.main(argv + ["--subset", "--final"]) == 2
    assert script.main(argv + ["--iteration", "0"]) == 2          # iteration 0 is in the git history
    assert script.main(argv + ["--final", "--iteration", "1"]) == 0
    live, replay = made[-2:]
    calls = Counter(live._client.calls)
    assert set(calls) - {"entities-coverage"} == {"relate-v22", "entities-inventory", "entities-relations"}
    assert calls["entities-inventory"] == calls["entities-relations"] == 12 and replay.usage["api_calls"] == 0
    run = json.loads((out / "run.json").read_text("utf-8"))
    assert (run["engine_version"], run["label"], run["pass"], run["iteration"], run["final"]) == (
        "2.2", LABEL, "full", 1, True)
    res = json.loads((out / "diagnostics.json").read_text("utf-8"))
    assert res["label"] == LABEL and res["diagnostics"]["label"] == LABEL
    assert res["threshold_rule"]["selected"] == {"engine": 0.5, "minimal": 0.5, "pairwise": 0.5}
    d = res["diagnostics"]
    for key in ("rev_2_1", "rev_2_2_at_0.5", "rev_2_2_at_selected"):
        engine = d["methods"][key]["engine"]
        assert (engine["direct"]["f1"], engine["cycle"]["f1"], engine["false_positive_rate"]) == (1.0, 1.0, 0.0)
        assert d["methods"][key]["direct_thinking"]["carried"]
    assert d["unscored"]["unscored"] == 0 and d["tension"]["per_variant"]["consistent"]["tension_pairs"] > 0
    assert d["minimal"]["rev_2_2_at_0.5"]["clause_mismatches"] == []
    entity = d["entity"]["rev_2_2"]
    assert entity["planted_relations_extracted"] == entity["planted_relations_extracted_corrected"] == 1.0
    assert all(n == 0 for by_class in entity["relation_misses_by_type"].values() for n in by_class.values())
    net = entity["coverage_net"]
    # variants of one base can send the same follow-up, answered from the cache the second time
    assert 0 < calls["entities-coverage"] <= net["follow_up_calls"] == d["cost"]["rev_2_2"]["entity_steps"][
        "coverage"]["calls"]
    assert net["statements_added"] == 0
    assert net["none_answers"] == net["uncovered_claims"] and net["still_uncovered"] == []
    assert (entity["schema_fallbacks"], entity["invalid_ids"], entity["entity_steps_skipped"]) == ([], 0, [])
    assert entity["thinking_tokens"]["inventory"]["calls"] == 12
    assert d["cost"]["rev_2_2"]["by_call"]["relate"]["calls"] > 0 and d["cost"]["rev_2_2"]["by_call"]["extract"][
        "calls"] == 12
    assert d["cost"]["rev_2_2"]["entity_steps"]["relations"]["calls"] == 12
    rows = [json.loads(line) for line in (out / "documents_v22.jsonl").read_text("utf-8").splitlines()]
    assert len(rows) == 12 and {r["engine_version"] for r in rows} == {"2.2"}
    assert all(set(r["by_tau"]) == {tau_key(t) for t in TAUS} for r in rows)
    assert {r["iteration"] for r in rows} == {1}
    text = (out / "results.md").read_text("utf-8")
    assert text.count(LABEL) >= 5 and "Threshold rule (§6)" in text and "Rev. 2.1 threshold curves" in text
    assert "- Entity steps rev_2_2: lexicon claims" in text and "Entity steps rev_2_1" not in text
    assert len(list((out / "analyses").glob("*.json"))) == 12


def test_the_development_pass_stops_before_scoring_when_too_many_pairs_are_unscored(recorded, tmp_path,
                                                                                      monkeypatch):
    script = _script("run_rev22_dev.py")
    _pass_llms(monkeypatch, script, recorded, Garbled22, _copy_cache(recorded, tmp_path / "cache"))
    out = tmp_path / "out"
    argv = ["--corpus", str(recorded.root / "corpus.jsonl"), "--record-run", str(recorded.root / "record"),
            "--budget", "100000000", "--subset", "--out", str(out)]
    assert script.main(argv) == 3
    gate = json.loads((out / "unscored_gate.json").read_text("utf-8"))
    assert gate["stop"] and gate["unscored"] == gate["unscored_malformed"] > 0 and not gate["accepted"]
    assert not (out / "diagnostics.json").exists()
    assert script.main(argv[:-1] + [str(tmp_path / "accepted"), "--accept-unscored"]) == 0
    run = json.loads((tmp_path / "accepted" / "run.json").read_text("utf-8"))
    assert run["unscored_gate"]["accepted"] and run["usage"]["api_calls"] == 0     # the second run is all cache


def test_rows_and_markdown_from_the_pass_functions(recorded, tmp_path):
    carried = {r["doc_id"]: r for r in map(json.loads, (recorded.root / "record" / "documents.jsonl").read_text(
        "utf-8").splitlines())}
    llm21 = LLM(cache_dir=_copy_cache(recorded, tmp_path / "cache"), client=Oracle(recorded.plans), budget_tokens=0)
    docs21 = run_corpus_dev(llm21, recorded.records, engine_version="2.1", with_direct=True, log=lambda s: None)
    rows21 = [dev_row(d, carried[d.record["doc_id"]]) for d in docs21]
    llm = LLM(cache_dir=tmp_path / "cache", client=Oracle22(recorded.plans))
    rows = [dev_row(d, carried[d.record["doc_id"]]) for d in run_corpus_dev(llm, recorded.records, log=lambda s: None)]
    assert all(r["carried"]["direct_thinking"]["verdict"] == carried[r["doc_id"]]["verdict"]["direct_thinking"]
               for r in rows)
    assert [r["doc_id"] for r in rows] == [r["doc_id"] for r in rows21]
    assert {devpass.call_kind(c["tag"]) for d in docs21 for c in d.calls} == {"extract", "relate", "entities",
                                                                               "direct"}
    selected = threshold_rule(rows)["selected"]
    d = diagnostics(rows, rows21, selected)
    assert set(d["comparisons"]) == {"0.5", "selected"} and "rev_2_2_both_at_engine_tau" in d["minimal"]
    json.dumps(d)
    text = dev_markdown({"pass": "test", "diagnostics": d, "threshold_rule": threshold_rule(rows),
                         "rev21_curves": threshold_rule(rows21)["curves"]})
    assert text.startswith("# A1 rev. 2.2 development pass (test)") and LABEL in text


@pytest.mark.parametrize("reject", [(), ("relations",)])
def test_l1var_v22_rows_replay_from_the_saved_responses_rescores_included(tmp_path, reject):
    fake = ScriptedClient(ANA_CLAIMS, entities_v22=ANA_ENTITIES_V22, reject_v22=reject)
    llm = fake_llm(tmp_path, fake)
    doc = run_document_dev(llm, {"doc_id": "ana", "text": ANA_TEXT})
    fake.answers = {(0, 1): [("contradicts", 0.8, MALFORMED_RATIONALE), ("contradicts", 0.7, "Fine."),
                             ("supports", 0.6, "Fine."), ("supports", 0.6, MALFORMED_RATIONALE),
                             ("tension", 0.9, "Fine.")]}
    rows = run_l1var_v22(llm, [doc], raw_dir=tmp_path / "raw", log=lambda s: None)
    assert [r["relations"]["0-1"] for r in rows] == ["contradicts", "supports", "tension"]
    assert all(r["verdict_by_tau"]["0.50"]["engine"] for r in rows)
    # per repetition: three pairs, the inventory and the relations call (and its fallback), plus two re-scores
    saved = list((tmp_path / "raw").glob("*.json"))
    assert len(saved) == 3 * (5 + len(reject)) + 2
    assert sum("rejected" in json.loads(p.read_text("utf-8")) for p in saved) == 3 * len(reject)
    again = replay_l1var_v22([doc], tmp_path / "raw", cache_dir=tmp_path / "replay", log=lambda s: None)
    assert again == rows
    s = score_l1var_v22(rows)
    assert (s["label"], s["repeats"], s["pairs"]) == (LABEL, 3, 3)
    assert s["relation_agreement"] == pytest.approx(2 / 3) and s["entity_agreement"] == 1.0
    assert s["direction_disagreements"] == 0 and s["verdict_change_rate"]["0.5"]["engine"] == 0.0
    with pytest.raises(Exception, match="dry-run"):
        run_l1var_v22(LLM(cache_dir=tmp_path / "dry"), [doc], raw_dir=tmp_path / "raw2")


# ------------------------------------------------------------------------------------------ Step 0 (§7.1)
AGE_CYCLE = (("Isla is older than Kai.", "Isla", "Kai"), ("Kai is older than Cy.", "Kai", "Cy"),
             ("Cy is older than Isla.", "Cy", "Isla"))
FORWARD = [(0, "age", "isla", "kai"), (1, "age", "kai", "cy"), (2, "age", "cy", "isla")]
MIRRORED = [(0, "age", "kai", "isla"), (1, "age", "cy", "kai"), (2, "age", "isla", "cy")]
STEP0_SCRIPT = ROOT / "results" / "a1-l1-order-misses.py"
STEP0_READS = [ROOT / "xon", RECORD_RUN, ROOT / "results" / "a1-rev22-full-20260925-124414", CORPUS, STEP0_SCRIPT,
               *ROOT.glob("*.egg-info")]    # package metadata, read by importlib.metadata on import
NETWORK_EVENTS = ("socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.gethostbyname",
                  "socket.gethostbyaddr", "socket.sendto", "socket.sendmsg", "http.client.connect", "urllib.Request")
STEP0_DRIVER = """
import json, runpy, sys
events = {"open": [], "network": []}
def hook(event, args):
    if event == "open" and isinstance(args[0], str):
        events["open"].append([args[0], args[1], args[2]])
    elif event in NETWORK_EVENTS:
        events["network"].append(event)
        raise RuntimeError("network access in Step 0: " + event)
sys.addaudithook(hook)
script, out = sys.argv[1:3]
sys.argv = [script, "--out", out]
try:
    runpy.run_path(script, run_name="__main__")
    code = 0
except SystemExit as exc:
    code = exc.code
print("EVENTS " + json.dumps({**events, "code": code}))
"""


def age_cycle(*stated):
    """A planted three-claim order cycle, and the rev. 2.1 entity graph of the stated relations, each (claim,
    attribute, a, b) or (claim, attribute, a, b, kind); an entity's mention is its id in title case."""
    claims = claims_of(*(s for s, _, _ in AGE_CYCLE))
    record = {"cycle_type": "order_cycle", "relations": [{"sentence": s, "kind": "greater", "a": a, "b": b,
                                                          "direction": "fixed"} for s, a, b in AGE_CYCLE]}
    ids = dict.fromkeys(["isla", "kai", "cy", "uma", *(x for r in stated for x in r[2:4])])
    spec = EntityGraphSpec(entities=[Entity(id=e, mentions=[e.replace("_", " ").title()]) for e in ids],
                           attributes=[Attribute(key=k, arity="unknown", arity_span=None)
                                       for k in dict.fromkeys(r[1] for r in stated)],
                           relations=[EntityRelation(claim_id=r[0], attribute=r[1], kind=r[4] if len(r) > 4 else
                                                     "greater", a=r[2], b=r[3], confidence=0.9) for r in stated])
    return record, claims, build_entity_graph(spec, n_claims=3)


@pytest.mark.parametrize("stated, found, closes, classes", [
    (FORWARD, [True] * 3, True, []),
    (MIRRORED, [False] * 3, True, ["scoring artifact"] * 3),
    ([MIRRORED[0], *FORWARD[1:]], [False, True, True], False, ["direction flip"]),
    (FORWARD[:2], [True, True, False], False, ["not extracted"]),
    ([*FORWARD[:2], (2, "age", "cy_b", "isla")], [True, True, False], False, ["id mismatch"]),
    ([*FORWARD[:2], (2, "age", "uma", "isla")], [True, True, False], False, ["wrong relation"]),
    ([*FORWARD[:2], (2, "age", "cy", "isla", "same")], [True, True, False], False, ["wrong relation"]),
    ([*FORWARD[:2], (2, "age_rank", "cy", "isla")], [True] * 3, False, []),
    ([*MIRRORED[:2], (2, "seniority", "isla", "cy")], [False] * 3, False, ["direction flip"] * 3),
])
def test_step0_classes_a_miss_by_the_first_class_that_fits(stated, found, closes, classes):
    record, claims, eg = age_cycle(*stated)
    assert relations_extracted(record["relations"], claims, eg) == found
    assert order_cycle_closes(record["relations"], claims, eg) is closes
    assert [m["class"] for m in misses(record, claims, eg, [])] == classes
    corrected = relations_extracted_corrected(record, claims, eg, [])
    assert corrected == ([True] * 3 if closes else found)


def test_step0_a_reported_cycle_holds_a_claim_of_every_planted_sentence():
    record, claims, _ = age_cycle(*FORWARD)
    assert planted_cycle_reported(record, claims, [{"type": "order_cycle", "claim_ids": [2, 0, 1]}])
    assert not planted_cycle_reported(record, claims, [{"type": "order_cycle", "claim_ids": [0, 1]}])
    assert not planted_cycle_reported(record, claims, [{"type": "binary_parity", "claim_ids": [0, 1, 2]}])


def test_step0_script_reads_only_the_runs_files_and_makes_no_api_calls(tmp_path):
    out = tmp_path / "order-misses.md"
    env = {k: v for k, v in os.environ.items() if k not in (API_KEY_ENV, RECORD_ENV)}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    driver = f"NETWORK_EVENTS = {NETWORK_EVENTS!r}\n" + STEP0_DRIVER
    run = subprocess.run([sys.executable, "-c", driver, str(STEP0_SCRIPT), str(out)], capture_output=True,
                         text=True, encoding="utf-8", env=env, cwd=tmp_path, timeout=600)
    assert run.returncode == 0, run.stderr
    events = json.loads(run.stdout.strip().splitlines()[-1].removeprefix("EVENTS "))
    assert events["code"] == 0 and events["network"] == []
    writes = [p for p, mode, flags in events["open"]
              if (mode and set(mode) & set("wax+")) or (mode is None and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))]
    assert [Path(p).resolve() for p in writes] == [out.resolve()]
    inside = [Path(p).resolve() for p, _, _ in events["open"] if Path(p).resolve().is_relative_to(ROOT)]
    assert inside and all(any(p.is_relative_to(allowed) for allowed in STEP0_READS) for p in inside), inside
    assert out.read_text("utf-8") == (ROOT / "results" / "a1-l1-order-misses.md").read_text("utf-8")
