"""The minimal consistency engine (XON_A1_MINIMAL_ENGINE.md §5). Never calls the API.

Equivalence with the full engine is checked three ways: on every full-engine analysis the A1 tests make (the
cross-check in conftest.py), on random documents, and on the recorded fixtures of the 12-document subset once they
exist."""
import json
import math
import random
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path

import pytest

from xon.llm import client, minimal
from xon.llm.claims import build_signed_graph
from xon.llm.client import LLM, DryRunMissingFixture
from xon.llm.consistency import analyze
from xon.llm.corpus import SAMPLE_BASES
from xon.llm.entity_consistency import build_entity_graph
from xon.llm.evaluation import document_row, run_corpus, score_minimal
from xon.llm.minimal import analyze_minimal, minimal_report_to_dict
from xon.llm.schemas import Claim, ClaimList, EntityGraphSpec, Relation, RelationList

ROOT = Path(__file__).resolve().parents[1]
ORDER_CYCLE = [(0, "age", "greater", "ana", "ben"), (1, "age", "greater", "ben", "cy"),
               (2, "age", "greater", "cy", "ana")]
DIFFERENT_TRIANGLE = [(0, "team", "different", "ana", "ben"), (1, "team", "different", "ben", "cy"),
                      (2, "team", "different", "ana", "cy")]


def claims_of(*kinds):
    return ClaimList(claims=[Claim(id=i, text=f"Claim {i}.", span=f"Claim {i}.", kind=k) for i, k in enumerate(kinds)])


def relations_of(*rels):
    return RelationList(relations=[Relation(a=a, b=b, rationale="Hand-built.", relation=label, confidence=conf)
                                   for a, b, label, conf in rels])


def spec(relations, arity=None):
    """Entity relations as (claim_id, attribute, kind, a, b[, confidence]); confidence 0.9 unless given."""
    arity = arity or {}
    return EntityGraphSpec.model_validate({
        "entities": [{"id": e, "mentions": [e.title()]} for e in sorted({x for r in relations for x in r[3:5]})],
        "attributes": [{"key": k, "arity": arity.get(k, "unknown"), "arity_span": None}
                       for k in sorted({r[1] for r in relations} | set(arity))],
        "relations": [{"claim_id": r[0], "attribute": r[1], "kind": r[2], "a": r[3], "b": r[4],
                       "confidence": r[5] if len(r) > 5 else 0.9} for r in relations]})


# ------------------------------------------------------------------------------------------ hand-built cases
def test_an_order_three_cycle_is_flagged_by_the_entity_clause():
    rep = analyze_minimal(claims_of("asserted", "asserted", "asserted"), relations_of(), spec(ORDER_CYCLE))
    assert rep.verdict_inconsistent and rep.verdict_clauses == ["entity"] and rep.direct_contradictions == []
    [c] = rep.entity_contradictions
    assert (c.type, c.attribute, c.claim_ids, c.min_confidence) == ("order_cycle", "age", [0, 1, 2], 0.9)
    assert sorted(c.entities) == ["ana", "ben", "cy"]


@pytest.mark.parametrize("kinds, flagged", [(("asserted", "asserted"), True), (("premise", "asserted"), True),
                                            (("asserted", "quoted"), False), (("quoted", "premise"), False)])
def test_a_confident_contradiction_is_flagged_by_the_direct_clause_unless_a_claim_is_quoted(kinds, flagged):
    rep = analyze_minimal(claims_of(*kinds), relations_of((0, 1, "contradicts", 0.9)), None)
    assert rep.verdict_inconsistent is flagged and rep.verdict_clauses == (["direct"] if flagged else [])
    assert rep.direct_contradictions == ([(0, 1)] if flagged else []) and rep.entity_contradictions == []


@pytest.mark.parametrize("arity, flagged", [("binary", True), ("multi", False), ("unknown", False)])
def test_three_different_relations_are_flagged_for_a_binary_attribute_only(arity, flagged):
    rep = analyze_minimal(claims_of(*["asserted"] * 3), relations_of(), spec(DIFFERENT_TRIANGLE, {"team": arity}))
    assert rep.verdict_inconsistent is flagged
    assert [c.type for c in rep.entity_contradictions] == (["binary_parity"] if flagged else [])


def test_relations_are_read_as_a1_builds_its_claim_graph():
    claims = claims_of("asserted", "asserted", "premise", "asserted")
    direct = minimal.direct_contradictions
    assert direct(claims, relations_of((1, 0, "contradicts", 0.5))) == [(0, 1)]           # unordered; >= 0.5
    assert direct(claims, relations_of((0, 1, "contradicts", 0.49))) == []
    assert direct(claims, relations_of((0, 1, "contradicts", 7.0))) == [(0, 1)]           # clipped to 1
    assert direct(claims, relations_of((0, 1, "contradicts", math.nan))) == []            # NaN reads as 0
    assert direct(claims, relations_of((0, 1, "unrelated", 0.9), (1, 0, "contradicts", 0.9))) == []   # first kept
    assert direct(claims, relations_of((2, 3, "contradicts", 0.8), (0, 1, "supports", 0.9),
                                       (0, 2, "contradicts", 0.6))) == [(0, 2), (2, 3)]
    with pytest.raises(ValueError, match="two distinct claims"):
        direct(claims, relations_of((1, 1, "contradicts", 0.9)))
    with pytest.raises(ValueError, match="0..n-1"):
        direct(ClaimList(claims=[Claim(id=1, text="x", span="x", kind="asserted")]), relations_of())


def test_entity_relations_enter_the_verdict_only_when_confident_and_asserted():
    three = claims_of(*["asserted"] * 3)
    weak = spec(ORDER_CYCLE[:2] + [(2, "age", "greater", "cy", "ana", 0.4)])
    assert not analyze_minimal(three, relations_of(), weak).verdict_inconsistent
    assert not analyze_minimal(claims_of("asserted", "asserted", "quoted"), relations_of(),
                               spec(ORDER_CYCLE)).verdict_inconsistent
    assert analyze_minimal(claims_of("asserted", "asserted", "premise"), relations_of(),
                           spec(ORDER_CYCLE)).verdict_clauses == ["entity"]


def test_both_clauses_and_the_unscored_pairs_are_reported():
    rep = analyze_minimal(claims_of(*["asserted"] * 3), relations_of((0, 2, "contradicts", 0.8)), spec(ORDER_CYCLE),
                          unscored_pairs=2)
    assert rep.verdict_clauses == ["direct", "entity"] and rep.unscored_pairs == 2
    d = minimal_report_to_dict(rep)
    assert json.loads(json.dumps(d)) == d and d["direct_contradictions"] == [[0, 2]]


# ------------------------------------------------------------------------------------------ equivalence
def test_the_a1_tests_cross_check_every_full_engine_analysis(monkeypatch):
    """conftest.py wraps the full engine's analyze while the A1 tests run (this module included): a test fails when
    the minimal engine's clause (a) or clause (c) output differs from the full engine's."""
    pair = build_signed_graph(claims_of("asserted", "asserted"), relations_of((0, 1, "contradicts", 0.9)))
    trio = build_signed_graph(claims_of(*["asserted"] * 3), relations_of())
    eg = build_entity_graph(spec(ORDER_CYCLE), 3)
    assert analyze(pair).verdict_clauses == ["direct"] and analyze(trio, eg).verdict_clauses == ["entity"]
    monkeypatch.setattr(minimal, "direct_contradictions", lambda claims, relations, *threshold: [])
    with pytest.raises(AssertionError, match=r"clause \(a\)"):
        analyze(pair)
    monkeypatch.setattr(minimal, "entity_contradictions", lambda entities, kinds, *threshold: [])
    with pytest.raises(AssertionError, match=r"clause \(c\)"):
        analyze(trio, eg)


def _random_document(rng: random.Random):
    n = rng.randint(2, 7)
    confidences = (0.0, 0.3, 0.49, 0.5, 0.51, 0.7, 0.9, 0.95, 1.0, 1.7, -0.2, math.nan, math.inf)
    rels = []
    for _ in range(rng.randint(0, 3 * n)):
        a, b = rng.sample(range(n), 2)
        rels.append((a, b, rng.choice(("supports", "supports", "contradicts", "unrelated")), rng.choice(confidences)))
    ents = []
    for _ in range(rng.randint(0, 9)):
        a, b = rng.sample(["ana", "ben", "cy", "dee"], 2)
        ents.append((rng.randrange(n), rng.choice(("age", "team", "younger")),
                     rng.choice(("same", "different", "greater")), a, b, rng.choice(confidences[:10])))
    arity = {k: rng.choice(("binary", "multi", "unknown")) for k in ("age", "team")}
    kinds = [rng.choice(("asserted", "premise", "quoted")) for _ in range(n)]
    return claims_of(*kinds), relations_of(*rels), spec(ents, arity)


def test_the_two_engines_agree_on_random_documents():
    rng = random.Random(20260924)
    fired = Counter()
    for _ in range(300):
        claims, relations, entity_spec = _random_document(rng)
        full = analyze(build_signed_graph(claims, relations), build_entity_graph(entity_spec, len(claims.claims)))
        mini = analyze_minimal(claims, relations, entity_spec)
        assert mini.direct_contradictions == full.direct_contradictions
        assert mini.entity_contradictions == full.verdict_entity_contradictions
        assert mini.verdict_clauses == [c for c in full.verdict_clauses if c != "claim_balance"]
        fired["+".join(full.verdict_clauses) or "none"] += 1
    # every clause fires, and some documents are flagged by clause (b) alone: the disagreement the spec predicts
    assert all(sum(k for c, k in fired.items() if clause in c) >= 20 for clause in ("direct", "claim_balance", "entity"))
    assert fired["claim_balance"] > 0 and fired["none"] > 0


def test_the_two_engines_agree_on_the_recorded_subset(tmp_path, monkeypatch):
    """The 12-document dry-run subset, replayed from tests/fixtures/llm; skipped until its fixtures are recorded."""
    monkeypatch.delenv(client.API_KEY_ENV, raising=False)
    monkeypatch.delenv(client.RECORD_ENV, raising=False)
    corpus = ROOT / "data" / "consistency" / "corpus.jsonl"
    records = [r for r in map(json.loads, corpus.read_text("utf-8").splitlines()) if r["base"] in SAMPLE_BASES]
    assert len(records) == 12
    try:
        runs = run_corpus(LLM(cache_dir=tmp_path / "cache"), records, log=lambda s: None)
    except DryRunMissingFixture as exc:
        pytest.skip(f"the 12-document subset has no recorded fixtures yet: {exc}")
    res = score_minimal([document_row(r) for r in runs])
    assert res["clause_mismatches"] == [] and all(d["predicted"] for d in res["disagreements"])


# ------------------------------------------------------------------------------------------ isolation, no API calls
ISOLATION = """
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
class EntityRelation:
    claim_id: int
    attribute: str
    kind: str
    a: str
    b: str
    confidence: float


@dataclass(frozen=True)
class EntityGraphSpec:
    entities: list
    attributes: list
    relations: list


cycle = [EntityRelation(i, "younger", "greater", a, b, 0.9)
         for i, (a, b) in enumerate((("Ana", "Ben"), ("Ben", "Cy"), ("Cy", "Ana")))]
report = analyze_minimal([Claim(i, "asserted") for i in range(3)], [Relation(0, 2, "contradicts", 0.8)],
                         EntityGraphSpec([], [], cycle))
print(json.dumps({"clauses": report.verdict_clauses, "direct": report.direct_contradictions,
                  "loaded": sorted(set(sys.modules) - before)}))
"""


def test_the_minimal_engine_runs_on_the_standard_library_alone(tmp_path):
    """A fresh interpreter imports xon.llm.minimal and runs it on plain dataclasses: nothing outside the standard
    library and the two modules is loaded (no NumPy, SciPy, pydantic, V1 or xon.llm.client)."""
    script = tmp_path / "isolation.py"
    script.write_text(textwrap.dedent(ISOLATION), "utf-8")
    out = subprocess.run([sys.executable, str(script), str(ROOT)], capture_output=True, text=True, check=True)
    res = json.loads(out.stdout)
    assert res["clauses"] == ["direct", "entity"] and res["direct"] == [[0, 2]]
    loaded = res["loaded"]
    assert {m for m in loaded if m.split(".")[0] == "xon"} == {"xon", "xon.llm", "xon.llm.minimal",
                                                                "xon.llm.entity_consistency"}
    assert [m for m in loaded if m.split(".")[0] not in sys.stdlib_module_names | {"xon"}] == []
    assert not {"numpy", "scipy", "networkx", "pydantic", "anthropic", "xon.llm.client"} & set(loaded)


def test_the_minimal_engine_runs_with_the_llm_client_mocked_to_raise(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the minimal engine reached the LLM client")

    for name in ("__init__", "parse", "text", "_call", "_create"):
        monkeypatch.setattr(client.LLM, name, refuse)
    monkeypatch.setattr(client, "_sdk", refuse)
    rep = analyze_minimal(claims_of(*["asserted"] * 3), relations_of((0, 2, "contradicts", 0.8)), spec(ORDER_CYCLE))
    assert rep.verdict_clauses == ["direct", "entity"]
