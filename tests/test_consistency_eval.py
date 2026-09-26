"""A1 experiment runners and their scoring rules (XON_A1_CONSISTENCY.md §6, rev. 2.1). Never calls the API."""
import importlib.util
import json
import re
import shutil
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from llm_fakes import PAIR, call_kind
from xon.llm.client import API_KEY_ENV, LLM, RECORD_ENV, LLMError
from xon.llm.corpus import SAMPLE_BASES, build_variants, occurrences, plan, record_to_dict
from xon.llm.engine import analysis_to_dict
from xon.llm.entity_consistency import build_entity_graph
from xon.llm.evaluation import (RECORD_MODEL, arity_read, auc, clause_attribution, contamination, direct_localizes,
                                document_row, engine_localizes, minimal_localizes, minimal_markdown, of_record, prf,
                                relations_extracted, run_corpus, run_l1var, score_l1, score_l1b, score_l1var,
                                score_minimal, span_matches, unscored_report)
from xon.llm.schemas import Claim, ClaimList, Contradiction, EntityGraphSpec

ROOT = Path(__file__).resolve().parents[1]
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.delenv(RECORD_ENV, raising=False)


def draft(p):
    """Claude's draft of variant (i): the required sentences with filler, over a few paragraphs."""
    parts = ["The group met early on a Saturday."]
    for k, s in enumerate(p.required):
        parts += [s, f"Nobody mentioned item {k} again."]
    return "\n\n".join(" ".join(parts[i:i + 4]) for i in range(0, len(parts), 4))


def sample():
    plans = [plan(b) for b in SAMPLE_BASES]
    return plans, [record_to_dict(r) for p in plans for r in build_variants(p, draft(p))]


def _numbered(block: str) -> dict[int, str]:
    return {int(m.group(1)): m.group(2) for m in re.finditer(r"^(\d+)\. (.*)$", block, re.M)}


GARBLED = "oracle', 'confidence': 0.3}"


class Oracle:
    """An SDK client that reads the corpus documents the way a perfect pipeline would: one claim per sentence (span =
    the sentence; "Assume" sentences are premises), a planted negation contradicts what it negates, the plans'
    relational sentences become entity relations (arity from the arity sentence), and LLM-direct cites the planted
    sentences."""

    def __init__(self, plans):
        self.plans, self.calls = list(plans), []
        self.messages = self

    def create(self, **body):
        kind = call_kind(body["system"])
        self.calls.append(kind)
        user = body["messages"][0]["content"]
        text = user.removeprefix("<text>\n").removesuffix("\n</text>")
        if kind == "extract":
            out = {"claims": [{"id": i, "text": s, "span": s, "kind": "premise" if s.startswith("Assume") else "asserted"}
                              for i, s in enumerate(SENTENCE.split(text.strip()))]}
        elif kind == "relate":
            claims = _numbered(user.split("\n\nPairs (A, B):")[0])
            out = {"relations": [self._relation(claims, int(a), int(b))
                                 for a, b in PAIR.findall(user.split("Pairs (A, B):")[1])]}
        elif kind == "entities":
            out = self._entities(_numbered(user))
        else:
            out = {"contradictions": [{"sentences": s, "explanation": "oracle"} for s in self._direct(text)]}
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(out))], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=100, output_tokens=40, output_tokens_details=None))

    def _relation(self, claims, a, b):
        contra = any({claims[a], claims[b]} == {p.premise if p.premise_contradicted else p.claim, p.negation}
                     for p in self.plans)
        return {"a": a, "b": b, "relation": "contradicts" if contra else "unrelated",
                "confidence": 0.95 if contra else 0.9, "rationale": "oracle"}

    def _entities(self, claims):
        ids = {t: i for i, t in claims.items()}
        rels, atts, names = [], {}, set()
        for p in self.plans:
            for r in dict.fromkeys(p.control_relations + p.cycle_relations):
                if r.sentence in ids:
                    rels.append({"claim_id": ids[r.sentence], "attribute": p.attribute, "kind": r.kind,
                                 "a": r.a.lower(), "b": r.b.lower(), "confidence": 0.95})
                    names |= {r.a, r.b}
                    arity = ("binary" if p.arity_cycle in ids else "multi" if p.arity_control in ids else "unknown")
                    atts[p.attribute] = {"key": p.attribute, "arity": arity, "arity_span": None}
        return {"entities": [{"id": n.lower(), "mentions": [n]} for n in sorted(names)],
                "attributes": list(atts.values()), "relations": rels}

    def _direct(self, text):
        for p in self.plans:
            if not occurrences(text, p.premise):
                continue
            if occurrences(text, p.negation):
                return [[p.premise if p.premise_contradicted else p.claim, p.negation]]
            if (p.arity_cycle and occurrences(text, p.arity_cycle)) or any(
                    occurrences(text, s) for s in p.cycle if s not in p.control):
                return [list(p.cycle) + ([p.arity_cycle] if p.arity_cycle else [])]
        return []


class GarbledOracle(Oracle):
    """The oracle, with a malformed rationale for every pair that starts at claim 0, also when it is scored again."""

    def _relation(self, claims, a, b):
        out = super()._relation(claims, a, b)
        return {**out, "rationale": GARBLED} if a == 0 else out


def claims_of(*spans):
    return ClaimList(claims=[Claim(id=i, text=s, span=s, kind="asserted") for i, s in enumerate(spans)])


def entity_graph(relations, entities=("ana", "ben", "cy"), attributes=(("rank", "unknown"),), mentions=None):
    spec = {"entities": [{"id": e, "mentions": (mentions or {}).get(e, [e.title()])} for e in entities],
            "attributes": [{"key": k, "arity": a, "arity_span": None} for k, a in attributes],
            "relations": [{"claim_id": c, "attribute": att, "kind": kind, "a": a, "b": b, "confidence": 0.9}
                          for c, att, kind, a, b in relations]}
    return build_entity_graph(EntityGraphSpec.model_validate(spec))


def planted(sentence, kind, a, b, direction="none"):
    return {"sentence": sentence, "kind": kind, "a": a, "b": b, "direction": direction}


# ------------------------------------------------------------------------------------------ matching rules
def test_a_claim_matches_a_planted_sentence_it_lies_inside_or_contains():
    s = "Ana is older than Ben."
    assert span_matches("Ana is older than Ben", s) and span_matches(f"It rained.  {s}\nThen", s)
    assert span_matches("Ana  is older\nthan Ben.", s)
    assert not span_matches("Ben is older than Ana.", s) and not span_matches("", s)


def test_a_planted_relation_counts_only_when_its_own_claim_states_it():
    rels = [planted("Ana is older than Ben.", "greater", "Ana", "Ben", "fixed")]
    claims = claims_of("Ana is older than Ben.", "Something else about Ana and Ben.")
    assert relations_extracted(rels, claims, entity_graph([(0, "age", "greater", "ana", "ben")])) == [True]
    assert relations_extracted(rels, claims, entity_graph([(1, "age", "greater", "ana", "ben")])) == [False]
    assert relations_extracted(rels, claims, entity_graph([(0, "age", "greater", "ben", "ana")])) == [False]
    assert relations_extracted(rels, claims, entity_graph([(0, "age", "same", "ana", "ben")])) == [False]
    # the attribute key is not compared; comparative keys are normalized by the engine first
    assert relations_extracted(rels, claims, entity_graph([(0, "seniority", "greater", "ana", "ben")])) == [True]
    assert relations_extracted(rels, claims, entity_graph([(0, "younger", "greater", "ben", "ana")])) == [True]


def test_entities_match_by_id_or_mention_and_same_and_different_are_unordered():
    rels = [planted("Ana is on the same team as Ben.", "same", "Ana", "Ben")]
    claims = claims_of("Ana is on the same team as Ben.")
    eg = entity_graph([(0, "team", "same", "ana_p", "ben")], entities=("ana_p", "ben"),
                      mentions={"ana_p": ["Ana", "she"]})
    assert relations_extracted(rels, claims, eg) == [True]
    assert relations_extracted(rels, claims, entity_graph([(0, "team", "same", "ben", "ana")])) == [True]


def test_rank_relations_count_in_either_direction_only_when_they_agree():
    s = ["Ana finished ahead of Ben.", "Ben finished ahead of Cy.", "Cy finished ahead of Ana."]
    rels = [planted(x, "greater", x.split()[0], x.split()[-1].rstrip("."), "either") for x in s]
    claims = claims_of(*s)
    reverse = [(0, "rank", "greater", "ben", "ana"), (1, "rank", "greater", "cy", "ben"),
               (2, "rank", "greater", "ana", "cy")]
    assert relations_extracted(rels, claims, entity_graph(reverse)) == [True, True, True]
    mixed = reverse[:2] + [(2, "rank", "greater", "cy", "ana")]
    assert relations_extracted(rels, claims, entity_graph(mixed)) == [False, False, True]
    assert relations_extracted(rels, claims, entity_graph(reverse[:2])) == [True, True, False]


def test_arity_is_read_from_the_attribute_of_the_matched_relations():
    s = ["Ana and Ben were on different teams.", "Ben and Cy were on different teams."]
    rels = [planted(x, "different", x.split()[0], x.split()[2]) for x in s]
    claims = claims_of(*s)
    eg = entity_graph([(0, "team", "different", "ana", "ben"), (1, "team", "different", "ben", "cy")],
                      attributes=(("team", "binary"), ("colour", "multi")))
    assert arity_read(rels, claims, eg) == "binary"
    assert arity_read(rels, claims, entity_graph([], attributes=(("team", "binary"),))) == "missing"


def test_localization_needs_two_planted_claims_in_one_reported_contradiction():
    cmap = {0: {0}, 1: {1}, 2: {2}, 3: set(), 4: set()}
    cycle = SimpleNamespace(claim_ids=[0, 1, 2])
    report = SimpleNamespace(entity_contradictions=[], frustrated_cycle=None, culprits=[])
    assert not engine_localizes(report, cmap)
    assert engine_localizes(SimpleNamespace(**{**vars(report), "entity_contradictions": [cycle]}), cmap)
    assert engine_localizes(SimpleNamespace(**{**vars(report), "frustrated_cycle": [3, 1, 2]}), cmap)
    assert not engine_localizes(SimpleNamespace(**{**vars(report), "frustrated_cycle": [3, 4, 0]}), cmap)
    culprits = [(4, 0.1, None), (0, 0.1, None), (2, 0.1, None), (1, 0.1, None)]
    assert engine_localizes(SimpleNamespace(**{**vars(report), "culprits": culprits}), cmap)
    assert not engine_localizes(SimpleNamespace(**{**vars(report), "culprits": culprits[:2] + [(3, 0.1, None)]}), cmap)
    planted_ = ["Ana is older than Ben.", "Ben is older than Cy.", "Cy is older than Ana."]
    hit = SimpleNamespace(contradictions=[Contradiction(sentences=["Ana is older than Ben", "Cy is older than Ana."],
                                                        explanation="x")])
    miss = SimpleNamespace(contradictions=[Contradiction(sentences=["Ana is older than Ben.", "Dara won."],
                                                         explanation="x")])
    assert direct_localizes(hit, planted_) and not direct_localizes(miss, planted_)
    minimal = SimpleNamespace(direct_contradictions=[(3, 4)], entity_contradictions=[])
    assert not minimal_localizes(minimal, cmap)
    assert minimal_localizes(SimpleNamespace(direct_contradictions=[(0, 3), (1, 2)], entity_contradictions=[]), cmap)
    assert minimal_localizes(SimpleNamespace(**{**vars(minimal), "entity_contradictions": [cycle]}), cmap)


def test_precision_recall_f1_and_auc():
    assert prf([True, True, False, False], [True, False, True, False]) == {
        "n": 4, "tp": 1, "fp": 1, "fn": 1, "precision": 0.5, "recall": 0.5, "f1": 0.5}
    assert prf([False, False], [True, False])["f1"] == 0.0
    assert auc([0.9, 0.5], [0.1, 0.5]) == pytest.approx((1 + 1 + 1 + 0.5) / 4)
    assert auc([0.3], []) is None


def row(variant, **kw):
    base = {"doc_id": variant, "base": 0, "variant": variant, "cycle_type": "order_cycle",
            "premise_contradicted": False, "harmony": 1.0, "conflict": 0.0, "unanchored": False, "premise_top3": None}
    return {**base, **kw}


def test_l1b_leaves_out_documents_without_harmony_and_counts_them():
    rows = [row("consistent", harmony=1.0), row("consistent", harmony=None, unanchored=True),
            row("consistent", harmony=0.9, conflict=0.2), row("direct", harmony=0.8, conflict=0.1,
                                                               premise_contradicted=True, premise_top3=True),
            row("direct", harmony=0.7, conflict=0.3), row("direct", harmony=None), row("cycle", harmony=0.1)]
    res = score_l1b(rows)
    assert res["documents"] == 6 and res["kept"] == {"consistent": 2, "direct": 2}
    assert res["left_out_harmony_none"] == {"consistent": 1, "direct": 1}
    assert res["auc_harmony"] == 1.0 and res["auc_conflict"] == pytest.approx(0.75)
    assert res["premise_top3"] == 1.0 and res["premise_documents"] == 1 and res["unanchored_fraction"] == 1 / 6
    assert res["checks"] == {"auc": True, "auc_at_least_conflict": True, "premise_top3": True} and res["passed"]
    assert score_l1b(rows, judged=False)["passed"] is None


def test_l1var_agreement():
    reps = [{"doc_id": "d", "repeat": k, "relations": rel, "entity_relations": ents,
             "verdict": {"engine": v, "pairwise": False, "direct_thinking": True, "direct_no_thinking": True}}
            for k, (rel, ents, v) in enumerate([({"0-1": "supports", "0-2": "unrelated"}, ["0:greater:a:b"], True),
                                                ({"0-1": "supports", "0-2": "contradicts"}, ["0:greater:a:b"], True),
                                                ({"0-1": "supports"}, ["0:greater:a:b", "1:same:a:c"], False)])]
    res = score_l1var(reps)
    assert res["documents"] == 1 and res["repeats"] == 3 and res["pairs"] == 2 and res["relation_agreement"] == 0.5
    assert res["entity_relations"] == 2 and res["entity_agreement"] == 0.5
    assert res["verdict_change_rate"] == {"engine": 1.0, "pairwise": 0.0, "direct_thinking": 0.0,
                                          "direct_no_thinking": 0.0}


def test_contamination_and_clause_attribution_on_cycle_variants():
    rows = [row("cycle", planted_pair_relations=[[1, 5, "unrelated", 0.6], [1, 7, "contradicts", 0.85],
                                                 [5, 7, None, None]],
                verdict={"engine": [True] * 3}, engine_clauses=["direct", "claim_balance", "entity"]),
            row("cycle", cycle_type="binary_parity", planted_pair_relations=[[0, 1, "supports", 0.7],
                                                                             [0, 2, "unrelated", 0.9]],
                verdict={"engine": [True] * 3}, engine_clauses=["entity"]),
            row("cycle", cycle_type="equality_break", planted_pair_relations=[[2, 3, "contradicts", 0.4]],
                verdict={"engine": [True] * 3}, engine_clauses=["claim_balance"]),
            row("cycle", cycle_type="equality_break", planted_pair_relations=[], verdict={"engine": [False] * 3},
                engine_clauses=[]),
            row("consistent", planted_pair_relations=[[0, 1, "contradicts", 0.9]], verdict={"engine": [True] * 3},
                engine_clauses=["entity"])]
    c = contamination(rows)
    assert (c["pairs"], c["scored"], c["unscored"], c["contradicts"], c["rate"]) == (6, 5, 1, 2, 0.4)
    assert [c["by_type"][t]["rate"] for t in ("order_cycle", "binary_parity", "equality_break")] == [0.5, 0.0, 1.0]
    at = clause_attribution(rows)
    assert (at["detections"], at["entity_alone"], at["entity_with_direct_or_balance"],
            at["direct_or_balance_without_entity"]) == (3, 1, 1, 1)
    assert at["combinations"] == {"direct+claim_balance+entity": 1, "entity": 1, "claim_balance": 1}
    assert at["by_type"]["equality_break"]["detections"] == 1


def test_the_minimal_engine_is_scored_next_to_the_full_engine_with_every_disagreement_listed():
    def doc(doc_id, full, minimal, variant="cycle"):
        return row(variant, doc_id=doc_id, engine_clauses=full, verdict={"engine": [bool(full)] * 3},
                   localized={"engine": [bool(full)] * 3},
                   minimal={"verdict": [bool(minimal)] * 3, "clauses": minimal, "localized": [bool(minimal)] * 3})
    rows = [doc("balance-only", ["claim_balance"], []), doc("both", ["direct", "claim_balance"], ["direct"]),
            doc("clean", [], [], variant="consistent")]
    res = score_minimal(rows)
    assert res["report_only"] and res["agreement"] == pytest.approx(2 / 3) and res["clause_mismatches"] == []
    assert [(d["doc_id"], d["full_clauses"], d["minimal_clauses"], d["predicted"]) for d in res["disagreements"]] == [
        ("balance-only", ["claim_balance"], [], True)]
    assert res["prediction"] == {"agreement_at_least": 0.98, "agreement_met": False,
                                 "all_disagreements_predicted": True, "held": False} and not res["investigate"]
    assert res["methods"]["full"]["cycle"]["recall"] == 1.0 and res["methods"]["minimal"]["cycle"]["recall"] == 0.5
    text = minimal_markdown(res)
    assert "report-only, no pass or fail" in text and "balance-only (full claim_balance, minimal none)" in text
    assert "investigate" not in text
    bug = score_minimal(rows + [doc("entity-missed", ["entity"], [])])
    assert [d["doc_id"] for d in bug["clause_mismatches"]] == ["entity-missed"] and bug["investigate"]
    assert not bug["prediction"]["all_disagreements_predicted"]
    assert "not the predicted kind" in minimal_markdown(bug) and "investigate it" in minimal_markdown(bug)


def test_unscored_pairs_are_reported_per_document_and_stop_the_run_above_one_percent():
    def unscored(doc, n, malformed=0, planted_=False, sampled=False):
        return row("cycle", doc_id=doc, sampled=sampled, unscored_pairs=[n, n + 1, 0] if sampled else [n] * 3,
                   unscored_malformed=[malformed] * 3, unscored_planted=planted_,
                   diagnostics={"pairs_requested": 100, "relations_rescored": malformed + 1})
    rows = [unscored("a", 0, sampled=True), unscored("b", 1, malformed=1, planted_=True), unscored("c", 0)]
    u = unscored_report(rows)
    assert (u["pairs_requested"], u["unscored"], u["unscored_malformed"], u["left_out_by_model"]) == (300, 1, 1, 0)
    assert u["relations_rescored"] == 4 and u["sampled_by_seed"] == {"0": 0, "1": 1, "2": 0}
    assert u["documents"] == [{"doc_id": "b", "unscored": 1, "unscored_malformed": 1, "planted_involved": True}]
    assert u["documents_with_planted_unscored"] == 1 and not u["stop"]
    assert unscored_report(rows + [unscored("d", 4)])["stop"]                 # 5 of 400
    assert not unscored_report([unscored("e", 1)])["stop"]                    # 1 of 100 is not above 1%


def test_only_the_full_corpus_with_the_model_of_record_is_judged():
    rows = [{"variant": v} for v in ("consistent", "direct", "cycle") for _ in range(60)]
    assert of_record(rows, RECORD_MODEL, subset=False) == (True, None)
    assert of_record(rows, RECORD_MODEL, subset=True)[0] is False
    assert of_record(rows, "claude-haiku-4-5-20251001", subset=False)[0] is False
    assert of_record(rows[:-1], RECORD_MODEL, subset=False)[0] is False


# ------------------------------------------------------------------------------------------ the runners
def test_l1_and_l1b_on_the_sample_with_an_oracle_pipeline(tmp_path):
    plans, records = sample()
    llm = LLM(cache_dir=tmp_path / "cache", client=Oracle(plans), fixture_dir=tmp_path / "fixtures")
    rows = [document_row(r) for r in run_corpus(llm, records, log=lambda s: None)]
    judged, why_not = of_record(rows, llm.model, subset=True)
    assert not judged and why_not == "the 12-document subset"
    l1 = score_l1(rows, judged)
    m = l1["methods"]
    assert l1["documents"] == {"consistent": 4, "direct": 4, "cycle": 4} and l1["passed"] is None
    assert m["engine"]["direct"]["f1"] == m["engine"]["cycle"]["f1"] == 1.0
    assert all(m["engine"]["cycle_by_type"][t]["f1"] == 1.0 for t in m["engine"]["cycle_by_type"])
    assert m["pairwise"]["direct"]["f1"] == 1.0 and m["pairwise"]["cycle"]["f1"] == 0.0
    assert m["direct_thinking"]["cycle"]["f1"] == m["direct_no_thinking"]["direct"]["f1"] == 1.0
    assert all(m[k]["false_positive_rate"] == 0.0 for k in m)
    assert l1["localization"] == {"engine": 1.0, "direct_thinking": 1.0, "direct_no_thinking": 1.0}
    dg = l1["diagnostics"]
    assert dg["planted_sentences_extracted"] == dg["planted_relations_extracted"] == dg["arity_accuracy"] == 1.0
    assert dg["arity_read"] == {"cycle": {"binary": 1}, "consistent": {"multi": 1}}
    assert dg["documents_sampled"] == 0 and l1["checks"] == {"direct_f1": True, "cycle_f1": True, "localization": True}
    assert (dg["contamination"]["scored"], dg["contamination"]["rate"]) == (15, 0.0)
    assert dg["clause_attribution"]["entity_alone"] == dg["clause_attribution"]["detections"] == 4
    assert dg["unscored"]["unscored"] == dg["unscored"]["relations_rescored"] == 0 and not dg["unscored"]["stop"]
    assert l1["expected"]["pairwise_cycle_f1_below"]
    mn = l1["minimal"]
    full = mn["methods"]["full"]
    assert (full["direct"], full["cycle"], full["cycle_by_type"], full["false_positive_rate"]) == (
        m["engine"]["direct"], m["engine"]["cycle"], m["engine"]["cycle_by_type"], m["engine"]["false_positive_rate"])
    assert full["localization"] == l1["localization"]["engine"]
    assert full["binary_control_false_positive_rate"] == dg["binary_control_false_positive_rate"]["engine"]
    assert mn["methods"]["minimal"]["direct"]["f1"] == mn["methods"]["minimal"]["cycle"]["f1"] == 1.0
    assert mn["methods"]["minimal"]["localization"] == 1.0 and mn["methods"]["minimal"]["false_positive_rate"] == 0.0
    assert mn["agreement"] == 1.0 and mn["disagreements"] == mn["clause_mismatches"] == [] and mn["prediction"]["held"]
    assert [r["minimal"]["clauses"] for r in rows if r["variant"] == "cycle"] == [["entity"]] * 4
    l1b = score_l1b(rows, judged)
    # the oracle relates only a negation to what it negates: consistent documents have no relation, so no harmony
    assert l1b["left_out_harmony_none"] == {"consistent": 4, "direct": 0} and l1b["auc_harmony"] is None
    assert l1b["premise_top3"] == 1.0 and l1b["premise_documents"] == 2


def test_l1var_bypasses_the_cache_and_refuses_dry_run(tmp_path):
    plans, records = sample()
    client = Oracle(plans)
    llm = LLM(cache_dir=tmp_path / "cache", client=client, fixture_dir=tmp_path / "fixtures")
    runs = run_corpus(llm, records, log=lambda s: None)
    before = client.calls.count("entities")
    res = score_l1var(run_l1var(llm, runs, log=lambda s: None))
    assert client.calls.count("entities") - before == 3 * len(records)
    assert client.calls.count("direct") == 2 * 4 * len(records)
    assert res["documents"] == 12 and res["relation_agreement"] == res["entity_agreement"] == 1.0
    assert set(res["verdict_change_rate"].values()) == {0.0}
    with pytest.raises(LLMError, match="dry-run"):
        run_l1var(LLM(cache_dir=tmp_path / "c2", fixture_dir=tmp_path / "f2"), runs)


def test_recording_fixtures_changes_nothing_but_the_fixture_files(tmp_path, monkeypatch):
    plans, records = sample()

    class Kept(GarbledOracle):
        def __init__(self, plans):
            super().__init__(plans)
            self.bodies = []

        def create(self, **body):
            self.bodies.append(json.dumps(body, sort_keys=True))
            return super().create(**body)

    def session(name, record, cache_from=None):
        if record:
            monkeypatch.setenv(RECORD_ENV, "1")
        else:
            monkeypatch.delenv(RECORD_ENV, raising=False)
        cache, fixtures = tmp_path / name / "cache", tmp_path / name / "fixtures"
        if cache_from:
            shutil.copytree(cache_from, cache)
        client = Kept(plans)
        llm = LLM(cache_dir=cache, client=client, fixture_dir=fixtures)
        runs = run_corpus(llm, records, log=lambda s: None)
        log = [{k: v for k, v in json.loads(line).items() if k not in ("timestamp", "duration_s")}
               for line in (cache / "log.jsonl").read_text("utf-8").splitlines()]
        return SimpleNamespace(bodies=client.bodies, log=log, usage=llm.usage, rows=[document_row(r) for r in runs],
                               analyses=[analysis_to_dict(a) for r in runs for a in r.analyses.values()],
                               cache={p.name: p.read_bytes() for p in cache.glob("*.json")},
                               fixtures={p.name: p.read_bytes() for p in fixtures.glob("*.json")})

    off, on = session("off", False), session("on", True)
    assert on.bodies == off.bodies and on.cache == off.cache and on.log == off.log and on.usage == off.usage
    assert on.analyses == off.analyses and on.rows == off.rows
    assert off.fixtures == {} and any("rescore" in name for name in on.fixtures)
    cached = {json.loads(v)["request"]: json.loads(v) for v in on.cache.values()}
    recorded = [json.loads(v) for v in on.fixtures.values()]
    assert all(f == cached[f["request"]] for f in recorded) and {f["request"] for f in recorded} == set(cached)
    # a resumed run answers from the cache and records the same fixtures
    resumed = session("resumed", True, cache_from=tmp_path / "on" / "cache")
    assert resumed.bodies == [] and resumed.fixtures == on.fixtures and resumed.rows == on.rows


def _script(name="run_consistency_eval.py"):
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), ROOT / "scripts" / name)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


class Wavering(Oracle):
    """The oracle, whose relations and LLM-direct answers change from call to call."""

    def __init__(self, plans):
        super().__init__(plans)
        self.n = 0

    def create(self, **body):
        self.n += 1
        resp = super().create(**body)
        out = json.loads(resp.content[0].text)
        if out.get("relations") and self.n % 3 == 0:
            out["relations"][0] = {**out["relations"][0], "relation": "supports", "confidence": 0.8}
        if "contradictions" in out and self.n % 2 == 0:
            out["contradictions"] = []
        resp.content[0].text = json.dumps(out)
        return resp


def test_l1var_saves_every_response_and_is_recomputed_from_them_alone(tmp_path, monkeypatch, capsys):
    plans, records = sample()
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("".join(json.dumps(r) + "\n" for r in records), "utf-8")
    client = Wavering(plans)
    script = _script()
    monkeypatch.setattr(script, "LLM", lambda budget_tokens=None: LLM(
        cache_dir=tmp_path / "cache", client=client, fixture_dir=tmp_path / "fixtures", budget_tokens=budget_tokens))
    out = tmp_path / "results" / "var"
    assert script.main(["--corpus", str(corpus), "--l1var", "--out", str(out)]) == 0
    live = json.loads((out / "l1var.json").read_text("utf-8"))
    assert live["relation_agreement"] < 1.0
    saved = [json.loads(p.read_text("utf-8")) for p in (out / "l1var").glob("*.json")]
    assert len(saved) == json.loads((out / "run.json").read_text("utf-8"))["usage"]["api_calls"] - \
        sum(1 for r in (tmp_path / "cache").glob("*.json"))
    assert {r["repetition"] for r in saved} == {1, 2, 3} and {r["doc_id"] for r in saved} == {r["doc_id"] for r in records}
    assert all({"request", "tag", "repetition", "model", "kind", "schema", "output", "usage", "stop_reason"} <= set(r)
               for r in saved)
    assert sorted(r["call"] for r in saved) == list(range(1, len(saved) + 1))
    assert not (tmp_path / "fixtures").exists()
    capsys.readouterr()

    log_before = (tmp_path / "cache" / "log.jsonl").read_bytes()
    recompute = _script("recompute_l1var.py")
    again = tmp_path / "again"
    assert recompute.main([str(out / "l1var"), "--corpus", str(corpus), "--cache", str(tmp_path / "cache"),
                           "--out", str(again)]) == 0
    assert json.loads((again / "l1var.json").read_text("utf-8")) == live
    assert (again / "l1var_repeats.jsonl").read_text("utf-8") == (out / "l1var_repeats.jsonl").read_text("utf-8")
    assert (tmp_path / "cache" / "log.jsonl").read_bytes() == log_before and client.n == len(saved) + sum(
        1 for _ in (tmp_path / "cache").glob("*.json"))
    next((out / "l1var").glob("*direct-thinking.json")).unlink()
    assert recompute.main([str(out / "l1var"), "--corpus", str(corpus), "--cache", str(tmp_path / "cache"),
                           "--out", str(tmp_path / "missing")]) == 1
    assert "No saved L1-var response left" in capsys.readouterr().err


def test_the_eval_cli_writes_rows_scores_and_tables(tmp_path, monkeypatch, capsys):
    plans, records = sample()
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("".join(json.dumps(r) + "\n" for r in records), "utf-8")
    script = _script()
    assert script.main(["--corpus", str(tmp_path / "none.jsonl")]) == 2
    monkeypatch.setattr(script, "LLM", lambda budget_tokens=None: LLM(
        cache_dir=tmp_path / "dry", fixture_dir=tmp_path / "no-fixtures", budget_tokens=budget_tokens))
    assert script.main(["--corpus", str(corpus), "--subset", "--out", str(tmp_path / "dry-out")]) == 1
    err = capsys.readouterr().err
    assert "DryRunMissingFixture" in err and "b00-consistent (1 of 12)" in err
    client = Oracle(plans)
    monkeypatch.setattr(script, "LLM", lambda budget_tokens=None: LLM(
        cache_dir=tmp_path / "cache", client=client, fixture_dir=tmp_path / "fixtures", budget_tokens=budget_tokens))
    out = tmp_path / "out"
    assert script.main(["--corpus", str(corpus), "--subset", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "### L1" in printed and "### L1b" in printed and "not judged (the 12-document subset)" in printed
    assert "#### Minimal engine (XON_A1_MINIMAL_ENGINE.md, Section 4): report-only, no pass or fail" in printed
    assert {p.name for p in out.iterdir()} == {"documents.jsonl", "analyses", "l1.json", "l1b.json", "run.json",
                                               "results.md"}
    assert len(list((out / "analyses").glob("*.json"))) == 12
    run = json.loads((out / "run.json").read_text("utf-8"))
    assert run["of_record"] is False and run["subset"] and run["documents"] == 12
    rows = [json.loads(x) for x in (out / "documents.jsonl").read_text("utf-8").splitlines()]
    assert score_l1(rows, False) == json.loads((out / "l1.json").read_text("utf-8"))
    assert script.main(["--corpus", str(corpus), "--l1var", "--out", str(tmp_path / "var")]) == 0
    assert "### L1-var" in capsys.readouterr().out and (tmp_path / "var" / "l1var.json").exists()


def test_the_eval_cli_writes_scores_computed_from_numpy_values(tmp_path, monkeypatch, capsys):
    """The run of record's harmony and conflict values are NumPy floats, so its L1b checks are NumPy booleans."""
    plans, records = sample()
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("".join(json.dumps(r) + "\n" for r in records), "utf-8")
    script = _script()
    monkeypatch.setattr(script, "LLM", lambda budget_tokens=None: LLM(
        cache_dir=tmp_path / "cache", client=Oracle(plans), fixture_dir=tmp_path / "fixtures", budget_tokens=budget_tokens))
    real, scored = script.score_l1b, []

    def score_numpy(rows, judged):
        consistent = [r["variant"] == "consistent" for r in rows]
        rows = [{**r, "harmony": np.float64(0.9 if c else 0.4), "conflict": np.float64(0.0 if c else 0.3)}
                for r, c in zip(rows, consistent)]
        scored.append(real(rows, judged))
        return scored[-1]

    monkeypatch.setattr(script, "score_l1b", score_numpy)
    out = tmp_path / "out"
    assert script.main(["--corpus", str(corpus), "--subset", "--out", str(out)]) == 0
    capsys.readouterr()
    res = scored[0]
    assert isinstance(res["checks"]["auc"], np.bool_) and isinstance(res["auc_harmony"], np.floating)
    written = json.loads((out / "l1b.json").read_text("utf-8"))
    assert written["checks"] == {k: bool(v) for k, v in res["checks"].items()}
    assert all(type(v) is bool for v in written["checks"].values()) and written["auc_harmony"] == res["auc_harmony"]
    assert {"run.json", "results.md"} <= {p.name for p in out.iterdir()}


def test_the_eval_cli_stops_before_l1_when_too_many_pairs_are_unscored(tmp_path, monkeypatch, capsys):
    plans, records = sample()
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("".join(json.dumps(r) + "\n" for r in records), "utf-8")
    script = _script()
    client = GarbledOracle(plans)
    monkeypatch.setattr(script, "LLM", lambda budget_tokens=None: LLM(
        cache_dir=tmp_path / "cache", client=client, fixture_dir=tmp_path / "fixtures", budget_tokens=budget_tokens))
    out = tmp_path / "out"
    assert script.main(["--corpus", str(corpus), "--subset", "--out", str(out)]) == 3
    printed = capsys.readouterr()
    assert "### Unscored pairs" in printed.out and "### L1" not in printed.out and "Stopped before L1" in printed.err
    assert {p.name for p in out.iterdir()} == {"unscored_gate.json", "run.json"}
    gate = json.loads((out / "unscored_gate.json").read_text("utf-8"))
    assert gate["stop"] and not gate["accepted"] and gate["left_out_by_model"] == 0
    assert gate["unscored"] == gate["unscored_malformed"] == gate["relations_rescored"] > 0
    assert json.loads((out / "run.json").read_text("utf-8"))["stopped"] == "unscored pairs"
    calls = len(client.calls)
    assert script.main(["--corpus", str(corpus), "--subset", "--out", str(tmp_path / "on"), "--accept-unscored"]) == 0
    assert len(client.calls) == calls and "### L1" in capsys.readouterr().out     # replayed from the cache
    run = json.loads((tmp_path / "on" / "run.json").read_text("utf-8"))
    assert run["unscored_gate"]["stop"] and run["unscored_gate"]["accepted"] and "stopped" not in run


def test_records_carry_what_the_scoring_reads():
    _, records = sample()
    rec = records[0]
    assert {"doc_id", "base", "variant", "cycle_type", "premise_contradicted", "text", "planted", "premises",
            "relations"} <= set(rec)
    assert asdict(plan(0).control_relations[0]) == rec["relations"][0]
