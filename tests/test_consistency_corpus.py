"""A1 corpus plans, variants and plant verification (XON_A1_CONSISTENCY.md §5, rev. 2.1). Never calls the API."""
import importlib.util
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from xon.llm import corpus
from xon.llm.client import API_KEY_ENV, LLM, RECORD_ENV
from xon.llm.corpus import (CYCLE_TYPES, N_BASE, SAMPLE_BASES, PlantedRelation, build_variants, corpus_user, generate,
                            normalize_ws, occurrences, plan, record_to_dict, scan_leaks, verify)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.delenv(RECORD_ENV, raising=False)


def draft(p, drop=None, twice=None):
    """A stand-in for Claude's draft of variant (i): the required sentences with filler, over a few paragraphs."""
    parts = ["The group met early on a Saturday."]
    for k, s in enumerate(p.required):
        parts += ([] if s == drop else [s] * (2 if s == twice else 1)) + [f"Nobody mentioned item {k} again."]
    return "\n\n".join(" ".join(parts[i:i + 4]) for i in range(0, len(parts), 4))


class Drafts:
    """An SDK client that answers generation calls with the given drafts and leak-scan calls with the given flag
    lists (by schema title, since QA calls carry no other identifying field); fails on any other call."""

    def __init__(self, texts, qa_flags=()):
        self.texts, self.qa_flags, self.bodies = list(texts), list(qa_flags), []
        self.messages = self

    def create(self, **body):
        self.bodies.append(body)
        title = body.get("output_config", {}).get("format", {}).get("schema", {}).get("title")
        if title == "LeakScan":
            payload = {"flags": self.qa_flags.pop(0) if self.qa_flags else []}
        elif self.texts:
            payload = {"text": self.texts.pop(0)}
        else:
            raise AssertionError("an LLM call that was not a generation call")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))],
                               stop_reason="end_turn", usage=SimpleNamespace(input_tokens=10, output_tokens=10))


def test_plans_are_balanced_and_fixed():
    plans = [plan(b) for b in range(N_BASE)]
    assert Counter(p.cycle_type for p in plans) == {t: 20 for t in CYCLE_TYPES}
    assert Counter((p.cycle_type, p.premise_contradicted) for p in plans) == {(t, v): 10 for t in CYCLE_TYPES
                                                                             for v in (True, False)}
    assert all(Counter(p.topic for p in plans if p.cycle_type == t) == {x: 1 for x in corpus.TOPICS}
               for t in CYCLE_TYPES)
    assert all(len(set(p.people)) == 5 for p in plans) and plan(7) == plans[7]
    assert {plans[b].cycle_type for b in SAMPLE_BASES} == set(CYCLE_TYPES)
    with pytest.raises(ValueError):
        plan(N_BASE)


def test_the_equality_control_keeps_both_relation_types():
    p = plan(1)
    b = p.people[1]
    negated = [" not " in s for s in p.control], [" not " in s for s in p.cycle]
    assert p.cycle_type == "equality_break" and negated == ([False, True, True], [False, False, True])
    assert p.control[0] == p.cycle[0] and p.control[2] == p.cycle[2] and p.control[1].startswith(f"{b} is not")


def test_planted_relations_follow_the_extraction_prompts_direction_rule():
    older, arrival, rank, equality, binary = plan(0), plan(3), plan(9), plan(1), plan(2)
    a, b = older.people[:2]
    assert older.attribute == "age"
    assert older.control_relations[0] == PlantedRelation(f"{a} is older than {b}.", "greater", a, b, "fixed")
    a, _, c = arrival.people[:3]
    assert arrival.attribute == "arrival_time"
    assert arrival.cycle_relations[2] == PlantedRelation(f"{c} arrived before {a}.", "greater", a, c, "fixed")
    assert rank.attribute == "rank" and {r.direction for r in rank.cycle_relations} == {"either"}
    assert [r.kind for r in equality.control_relations] == ["same", "different", "different"]
    assert [r.kind for r in equality.cycle_relations] == ["same", "same", "different"]
    assert {r.kind for r in binary.cycle_relations} == {"different"} and binary.control == binary.cycle
    [consistent, _, cycle] = build_variants(arrival, draft(arrival))
    assert record_to_dict(cycle)["relations"][2] == {"sentence": f"{c} arrived before {a}.", "kind": "greater",
                                                     "a": a, "b": c, "direction": "fixed"}
    assert [r.sentence for r in consistent.relations] == list(arrival.control)


@pytest.mark.parametrize("base", [0, 1, 2, 3])
def test_variants_differ_only_in_their_planted_sentences(base):
    p = plan(base)
    consistent, direct, cycle = build_variants(p, draft(p))
    assert [verify(p, r) for r in (consistent, direct, cycle)] == [[], [], []]
    assert consistent.planted == [] and consistent.premises == direct.premises == cycle.premises == [p.premise]
    assert direct.planted == [p.premise if p.premise_contradicted else p.claim, p.negation]
    assert normalize_ws(direct.text.replace(" " + p.negation, "", 1)) == normalize_ws(consistent.text)
    if p.cycle_type == "binary_parity":
        assert cycle.planted == list(p.cycle) + [p.arity_cycle] and cycle.arity_sentence == p.arity_cycle
        assert "two" in p.arity_cycle and "three" in p.arity_control and consistent.arity_sentence == p.arity_control
        assert cycle.text == consistent.text.replace(p.arity_control, p.arity_cycle)
    else:
        [(old, new)] = [(o, n) for o, n in zip(p.control, p.cycle) if o != n]
        assert cycle.planted == list(p.cycle) and cycle.text == consistent.text.replace(old, new)


def test_verification_catches_missing_repeated_and_leaked_sentences():
    p = plan(3)
    [consistent, direct, cycle] = build_variants(p, draft(p, drop=p.claim))
    assert all(f"missing: {p.claim}" in verify(p, r) for r in (consistent, direct, cycle))
    [consistent, _, _] = build_variants(p, draft(p, twice=p.control[0]))
    assert verify(p, consistent) == [f"repeated: {p.control[0]}"]
    leaked = draft(p) + " " + p.negation
    assert f"present: {p.negation}" in verify(p, build_variants(p, leaked)[0])
    assert occurrences("x\n" + p.premise.replace(" ", "\n  "), p.premise) == 1
    assert occurrences("Hana is older than Ben.", "Ana is older than Ben.") == 0


def test_superlative_collision_catches_first_vs_before_anyone_else():
    """Base 32's defect: 'arrived first' and 'before anyone else' are the same arrival pole."""
    from xon.llm.corpus import superlative_collisions
    text = ("Milo arrived first, carrying notes. "
            "Quinn, always punctual, had arrived a full ten minutes before anyone else and sat down.")
    hits = superlative_collisions(text, ("Milo", "Hana", "Quinn"))
    assert any(h["attribute"] == "arrival" and h["pole"] == "earliest"
               and set(h["people"]) >= {"Milo", "Quinn"} for h in hits)
    assert superlative_collisions("Milo arrived first.", ("Milo", "Quinn")) == []
    # Speaker is not credited: only the nearest name before the cue.
    assert superlative_collisions(
        "Esme mentioned that Leo was the tallest among the staff.", ("Esme", "Leo")) == []
    assert superlative_collisions(
        "Xavi and Mina were close in age, both a year older than Fay, who was the youngest.",
        ("Xavi", "Mina", "Fay")) == []


def test_order_cycle_scan_finds_planted_cycle_and_ignores_it_when_excluded():
    from xon.llm.corpus_qa import order_cycle_scan
    p = plan(0)
    text = " ".join(p.cycle)
    all_cycles = order_cycle_scan(text, p.people, exclude_sentences=())["cycles_all"]
    assert any(c["attribute"] == "age" for c in all_cycles)
    assert order_cycle_scan(text, p.people, exclude_sentences=p.cycle)["cycles_unplanted"] == []


def test_activity_synonym_hits_photograph_paraphrase():
    from xon.llm.corpus_qa import activity_synonym_hits
    p = plan(34)  # Kai took the photographs
    assert p.claim_keyword == "photograph"
    text = p.required[0] + " " + p.claim + " Kai moved around, capturing the best shots of the robots."
    hits = activity_synonym_hits(text, p, exclude=p.required)
    assert any(h["keyword"] in ("capturing", "shots", "shot") for h in hits)


def test_verification_catches_bunched_quoted_and_leaked_content():
    """Rev. 2.1 tighten re-specification: position must not be a tell, no stray quotation marks, and no sentence
    but the required ones may name the claim's event."""
    p = plan(1)
    bunched = ("The group met early on a Saturday. " + " ".join(p.required) + " "
              + " ".join(f"Extra detail sentence number {k}." for k in range(4)))
    assert "adjacent required sentences" in verify(p, build_variants(p, bunched)[0])

    early = " ".join(["Opener sentence one."] + [x for s in p.required for x in (s, "A short filler follows.")]
                     + [f"Extra filler sentence number {k}." for k in range(20)])
    early_problems = verify(p, build_variants(p, early)[0])
    assert "required sentences clustered in one stretch of the document" in early_problems
    assert "adjacent required sentences" not in early_problems

    quoted = draft(p) + " \u201cA stray quote appears here.\u201d"
    assert "stray quotation mark" in verify(p, build_variants(p, quoted)[0])

    leaked = draft(p) + " Someone mentioned the hall again later that day."
    assert all("refers to 'hall' outside the required sentences" in verify(p, r)
              for r in build_variants(p, leaked))


def test_the_leak_scan_pass_reports_flags_without_regenerating(tmp_path):
    p = plan(1)
    flag = {"sentence": "This meant the group finally had a proper meeting space.", "reason": "implies sentence 3"}
    client = Drafts([draft(p)], qa_flags=[[flag]])
    llm = LLM(cache_dir=tmp_path / "f", client=client)
    scanned = scan_leaks(llm, p, draft(p), tag="corpus-b01-qa")
    assert scanned == [flag]

    client = Drafts([draft(p)], qa_flags=[[flag]])
    records, stats = generate(LLM(cache_dir=tmp_path / "g", client=client), [p], log=lambda s: None, qa_scan=True)
    assert stats["leak_flags"] == {1: [flag]} and len(records) == 3   # flagged, not regenerated

    client = Drafts([draft(p)], qa_flags=[[]])
    records, stats = generate(LLM(cache_dir=tmp_path / "h", client=client), [p], log=lambda s: None, qa_scan=True)
    assert stats["leak_flags"] == {} and len(records) == 3

    client = Drafts([draft(p)])   # qa_scan=False by default: no LeakScan call at all
    records, stats = generate(LLM(cache_dir=tmp_path / "i", client=client), [p], log=lambda s: None)
    assert stats["leak_flags"] == {} and len(client.bodies) == 1


def test_a_truncated_draft_is_retried_not_fatal(tmp_path):
    """A truncated response must not abort the whole corpus; it is retried like a verification failure."""
    from xon.llm.client import LLMTruncated

    p = plan(0)

    class TruncateThenDraft(Drafts):
        def create(self, **body):
            self.bodies.append(body)
            if len(self.bodies) == 1:
                raise LLMTruncated("hit max_tokens")
            return super().create(**body)

    client = TruncateThenDraft([draft(p)])
    # Drafts.create is never reached on the first call; the second call needs the draft.
    # Override: first parse raises via a wrapper on LLM.parse path — TruncateThenDraft raises before return.
    # Actually LLM._create catches and re-raises LLMTruncated only if it comes from messages.create; our raise
    # in create works. But then Drafts has no text consumed. Second call uses draft.
    records, stats = generate(LLM(cache_dir=tmp_path / "t", client=client), [p], log=lambda s: None)
    assert stats["regenerated"] == 1 and stats["attempts"] == {0: 2} and len(records) == 3


def test_a_base_that_only_passes_on_the_final_attempt_is_flagged(tmp_path):
    p = plan(2)
    client = Drafts([draft(p, drop=p.claim)] * (corpus.MAX_ATTEMPTS - 1) + [draft(p)])
    records, stats = generate(LLM(cache_dir=tmp_path / "e", client=client), [p], log=lambda s: None)
    assert stats["flagged"] == [2] and stats["attempts"] == {2: corpus.MAX_ATTEMPTS} and len(records) == 3


def test_plant_verification_makes_no_llm_call(tmp_path):
    plans = [plan(b) for b in SAMPLE_BASES]
    client = Drafts([draft(p) for p in plans])
    llm = LLM(cache_dir=tmp_path / "cache", client=client, fixture_dir=tmp_path / "fixtures")
    records, stats = generate(llm, plans, log=lambda s: None)
    assert len(client.bodies) == len(plans) and len(records) == 12 and stats["regenerated"] == 0
    assert Counter(r.variant for r in records) == {"consistent": 4, "direct": 4, "cycle": 4}
    assert all(verify(p, r) == [] for p in plans for r in records if r.base == p.base)   # the client now raises
    assert len(client.bodies) == len(plans)


def test_a_draft_missing_a_sentence_is_regenerated_with_a_changed_request(tmp_path):
    p = plan(2)
    client = Drafts([draft(p, drop=p.arity_control), draft(p)])
    records, stats = generate(LLM(cache_dir=tmp_path / "c", client=client), [p], log=lambda s: None)
    assert stats["regenerated"] == 1 and stats["attempts"] == {2: 2} and len(records) == 3
    first, second = (b["messages"][0]["content"] for b in client.bodies)
    assert "Attempt 2" in second and "Attempt" not in first
    client = Drafts([draft(p, drop=p.claim)] * corpus.MAX_ATTEMPTS)
    records, stats = generate(LLM(cache_dir=tmp_path / "d", client=client), [p], log=lambda s: None)
    assert records == [] and list(stats["failed"]) == [2] and stats["regenerated"] == corpus.MAX_ATTEMPTS - 1


def test_review_problems_start_at_attempt_2_and_are_stated(tmp_path):
    p, q = plan(2), plan(3)
    client = Drafts([draft(p), draft(q)])
    records, stats = generate(LLM(cache_dir=tmp_path / "r", client=client), [p, q], log=lambda s: None,
                              review_problems={2: ["a sentence implies how many groups there were"]})
    assert len(records) == 6 and stats["attempts"] == {2: 2, 3: 1} and stats["regenerated"] == 0
    first, second = (b["messages"][0]["content"] for b in client.bodies)
    assert "Attempt 2" in first and "a sentence implies how many groups there were" in first
    assert "Attempt" not in second


def test_the_request_lists_the_sentences_and_restrictions():
    p = plan(2)
    user = corpus_user(p)
    assert all(s in user for s in p.required) and p.arity_control in user
    assert "Do not say how many" in user and "except in the required sentence that does" in user
    assert "how many" not in corpus_user(plan(0))


def test_leak_qa_prompt_exempts_cross_attribute_filler():
    """Rev. 2.1 re-specification 12: comparisons on a different attribute than the plant are expected filler."""
    from xon.llm.corpus import LEAK_QA_SYSTEM, leak_qa_user
    p = plan(0)
    assert "different attribute" in LEAK_QA_SYSTEM and "expected filler" in LEAK_QA_SYSTEM
    assert "ranking" in LEAK_QA_SYSTEM and "value or order" in LEAK_QA_SYSTEM
    assert p.attribute.replace("_", " ") in leak_qa_user(p, "doc")
    assert "expected filler" in leak_qa_user(p, "doc")


def test_the_full_corpus_needs_the_reviewed_sample(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("make_corpus", ROOT / "scripts" / "make_consistency_corpus.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main(["--out", str(tmp_path)]) == 2
    assert script.main(["--out", str(tmp_path), "--sample-reviewed"]) == 2
    assert "review sample" in capsys.readouterr().err
