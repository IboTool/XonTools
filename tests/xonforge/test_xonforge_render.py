"""XonForge's renderer (XONFORGE_SPEC.md §6; §14, step 3; the user's item 2 of 2026-09-25): the prompts, the twin
rendered first and its variants derived from it, retries with the failed checks quoted back, provenance, rotation and
the document store. Offline: every call goes to a fake client."""
import json
import re

import pytest
from pydantic import ValidationError

from xon_common.providers.base import DryRunMissing
from xonforge import locations, prompts
from xonforge.render import prompt
from xonforge.render.phrasing import statement
from xonforge.render.renderer import derivation_problems, derive, doc_id, render, splice
from xonforge.render.rotation import Rotation
from xonforge.render.schema import Document, Rendering, RenderRules, ReviewProblem, Revisions
from xonforge.render.store import DocumentStore
from xonforge.skeleton.generators import Knobs, generate

from xonforge_fakes import FakeClient, anthropic_response, caller, entry

RULES = RenderRules(words=300, explicitness="stated", lexical_variety="medium", min_spacing=2)


def base(plant_type="order_cycle", seed=1, **kw):
    return generate(plant_type, seed=seed, genre="office memo", knobs=Knobs(entities=5, distractors=1), **kw)


def twin(plant_type="order_cycle", seed=1, **kw):
    return base(plant_type, seed, **kw).consistent


def reply(skeleton, text=None, spans=None):
    """A rendering whose text is one sentence per fact."""
    sentences = {f.id: statement(f, skeleton) + "." for f in skeleton.facts}
    body = {"text": text if text is not None else " ".join(sentences.values()),
            "spans": [{"fact": k, "span": v} for k, v in (spans if spans is not None else sentences).items()]}
    return anthropic_response(text=json.dumps(body))


def revisions(new: dict):
    return anthropic_response(text=json.dumps({"sentences": [{"fact": f, "sentence": s} for f, s in new.items()]}))


def checks(*problem_lists):
    """A check that returns the given problem lists in turn, then passes."""
    seen = []

    def check(skeleton, rendering, rules):
        seen.append(rendering)
        return list(problem_lists[len(seen) - 1]) if len(seen) <= len(problem_lists) else []

    return check, seen


def rendered(tmp_path, skeleton, name="twin"):
    return render(skeleton, RULES, caller(tmp_path / name, entry("anthropic"), FakeClient(reply(skeleton))),
                  check=checks()[0], max_tokens=8000, mode="record")


def own(skeleton, fid):
    return statement(next(f for f in skeleton.facts if f.id == fid), skeleton) + "."


# ------------------------------------------------------------------------------------------ the prompts
def test_the_twin_s_prompt_lists_people_and_facts_and_the_rules_of_the_document():
    sk = twin()
    system, user = prompt.build(sk, RULES)
    for f in sk.facts:
        assert f"{f.id}. {statement(f, sk)}." in user
    for e in sk.entities:
        assert f"{e.name} ({e.pronoun})" in user
    assert "Genre: office memo" in user and "about 300 words" in user
    assert prompt.LEXICAL["medium"] in user and prompt.EXPLICIT["stated"] in user
    ids = sk.twin_facts
    assert f"put at least 2 other sentences between any two of the sentences for facts {', '.join(ids[:-1])} and " \
           f"{ids[-1]}, and {prompt.SPREAD['any']}." in user
    names = {e.id: e.name for e in sk.entities}
    planted_entities = base().planted[0].plant.params["entities"]
    assert all(names[e] in user.split("Restriction:")[1] for e in planted_entities)
    assert "no quotation marks" in system and "each in a sentence of its own" in system
    assert "name the people a fact is about" in system and "keep each fact's sense" in system
    assert "no sentence may mention any of " in user
    assert "contradiction" not in user and "even where facts do not fit together" not in system
    assert system == prompts.load("render.txt").text and prompt.PROMPT_VERSION.startswith("render-v0-draft-3+")


def test_the_spacing_and_the_level_s_spread_are_asked_for():
    sk = twin()
    one = RULES.model_copy(update={"min_spacing": 1})
    assert "put at least 1 other sentence between any two" in prompt.build(sk, one)[1]
    for spread in ("half", "quarters"):
        _, user = prompt.build(sk, RULES.model_copy(update={"spread": spread}))
        assert prompt.SPREAD[spread] in user
    assert prompt.SPREAD == {
        "any": "spread them through the document so that where they appear does not stand out",
        "half": "spread them so that, from the first of them to the last, they take up at least half of the document",
        "quarters": "put the first of them within the first quarter of the document and the last within the last "
                    "quarter"}


def test_an_assumption_and_a_stated_number_of_values_are_written_as_a1_wrote_them():
    negation = base("direct_negation", premise=True)
    claim = negation.planted[0].plant.params["negated_claim"]
    _, user = prompt.build(negation.consistent, RULES)
    assert f"{claim}. (an assumption) Assume that " in user
    parity = twin("binary_parity")
    _, user = prompt.build(parity, RULES)
    assert f"{parity.arity_fact}. There are exactly two " in user and "Assume" not in user
    restriction = user.split("Restriction:")[1]
    assert f"facts {', '.join(parity.twin_facts)} and {parity.arity_fact}, no sentence" in restriction
    assert not re.search(rf"\b{parity.arity_fact}\b", user.split("Spacing:")[1].split("Restriction:")[0])


def test_only_a_consistent_twin_is_rendered_from_its_skeleton():
    b = base("binary_parity", traps=("arity_control",))
    for variant in (b.planted[0], b.trap_only[0]):
        with pytest.raises(ValueError, match="derived from another variant's text"):
            prompt.build(variant, RULES)
    with pytest.raises(ValueError, match="records its twin_facts"):
        prompt.build(b.consistent.model_copy(update={"twin_facts": ()}), RULES)
    with pytest.raises(ValidationError):
        RenderRules(words=300, explicitness="inferred", lexical_variety="low")


@pytest.mark.parametrize("fields, message", [({"words": 149}, "150 to 3,000"), ({"words": 3001}, "150 to 3,000"),
                                             ({"min_spacing": 0}, "at least 1 sentence"),
                                             ({"level": 4}, "levels are 1, 2 and 3"), ({"spread": "wide"}, "spread"),
                                             ({"retry_cap": 0}, "at least one")])
def test_render_rules_stay_within_the_spec_s_ranges(fields, message):
    with pytest.raises(ValidationError, match=message):
        RenderRules(**{"words": 300, "explicitness": "stated", "lexical_variety": "low", **fields})
    assert RenderRules(words=300, explicitness="stated", lexical_variety="low").min_spacing == 1


def test_failed_checks_and_a_reviewer_s_problems_are_quoted_back():
    sk = twin()
    _, user = prompt.build(sk, RULES, problems=["the span for f2 is not in the text", "a quotation mark"])
    assert "An earlier draft had these problems, which this one must not have: the span for f2 is not in the text; " \
           "a quotation mark." in user
    _, user = prompt.build(sk, RULES, review_problems=[ReviewProblem(problem="Ana is ranked twice", fact="f3"),
                                                       ReviewProblem(problem="stray claim", sentence="Ben won.")],
                           previous_text="EARLIER-TEXT-MARKER")
    assert "- Ana is ranked twice (fact f3)" in user and "- stray claim (the sentence: Ben won.)" in user
    assert user.endswith("EARLIER-TEXT-MARKER") and "Change only what is needed" in user


def test_the_derive_prompt_shows_only_the_sentences_to_restate():
    b = base()
    planted, (fid,) = b.planted[0], b.planted[0].plant.params["differs_from_twin"]
    system, user = prompt.build_derive(planted, {fid: "OLD-SENTENCE-MARKER."}, RULES)
    assert system == prompts.load("derive.txt").text and "contradiction" not in system + user
    assert f"{fid}.\n- The sentence now: OLD-SENTENCE-MARKER.\n- The fact to state instead: {own(planted, fid)}" in user
    others = [f for f in planted.facts if f.id != fid]
    assert not any(f"{f.id}. " in user or statement(f, planted) in user for f in others)
    _, user = prompt.build_derive(planted, {fid: "x."}, RULES, problems=["PROBLEM-MARKER"])
    assert user.endswith("An earlier attempt had these problems, which this one must not have: PROBLEM-MARKER.")


# ------------------------------------------------------------------------------------------ retries
def test_a_rendering_that_passes_is_kept_with_its_provenance(tmp_path):
    sk = twin()
    fake = FakeClient(reply(sk))
    check, seen = checks()
    doc = render(sk, RULES, caller(tmp_path, entry("anthropic"), fake), check=check, max_tokens=8000, mode="record",
                 params={"temperature": 0.7})
    assert (doc.status, doc.flags, len(doc.attempts), doc.attempts[0].source) == ("rendered", (), 1, "api")
    assert doc.doc_id == doc_id(sk) == f"{sk.base_id}-consistent" and doc.skeleton_digest == sk.digest()
    assert doc.spans == {f.id: statement(f, sk) + "." for f in sk.facts} and len(seen) == 1
    r = doc.renderer
    assert (r.entry, r.provider, r.model, r.params, r.prompt_version, r.prompt_sha256) == (
        "anthropic", "anthropic", "model-x", {"temperature": 0.7}, prompt.PROMPT_VERSION, prompt.RENDER.sha256)
    assert len(fake.bodies) == 1 and doc.mode == "record" and doc.derived_from is None and doc.changed == ()


def test_a_document_is_labelled_with_the_mode_of_the_run_that_made_it(tmp_path):
    sk = twin()
    doc = render(sk, RULES, caller(tmp_path, entry("anthropic"), FakeClient(reply(sk))), check=checks()[0],
                 max_tokens=8000, mode="pipeline_test")
    assert doc.mode == "pipeline_test"
    fake = FakeClient(reply(sk))
    for mode in (None, "", "test"):
        with pytest.raises(ValueError, match="names its mode"):
            render(sk, RULES, caller(tmp_path, entry("anthropic"), fake), check=checks()[0], max_tokens=8000,
                   mode=mode)
    assert fake.bodies == []
    with pytest.raises(ValidationError, match="mode"):
        Document.model_validate({k: v for k, v in doc.model_dump().items() if k != "mode"})


def test_failed_checks_are_quoted_back_until_a_rendering_passes(tmp_path):
    sk = twin()
    fake = FakeClient(reply(sk))
    check, _ = checks(["PROBLEM-ONE"], ["PROBLEM-TWO"])
    doc = render(sk, RULES, caller(tmp_path, entry("anthropic"), fake), check=check, max_tokens=8000, mode="record")
    assert doc.status == "rendered" and [a.failed for a in doc.attempts] == [("PROBLEM-ONE",), ("PROBLEM-TWO",), ()]
    users = [json.dumps(b["messages"]) for b in fake.bodies]
    assert "PROBLEM-ONE" not in users[0] and "PROBLEM-ONE" in users[1] and "PROBLEM-TWO" in users[2]
    assert doc.flags == ()


def test_a_document_that_needs_every_attempt_is_flagged_and_one_that_never_passes_is_kept_as_failed(tmp_path):
    sk = twin()
    check, _ = checks(*[["STILL-WRONG"]] * 4)
    doc = render(sk, RULES, caller(tmp_path / "a", entry("anthropic"), FakeClient(reply(sk))), check=check,
                 max_tokens=8000, mode="record")
    assert doc.status == "rendered" and doc.flags == ("needed all 5 rendering attempts",)
    check, _ = checks(*[["STILL-WRONG"]] * 5)
    doc = render(sk, RULES, caller(tmp_path / "b", entry("anthropic"), FakeClient(reply(sk))), check=check,
                 max_tokens=8000, mode="record")
    assert doc.status == "failed" and len(doc.attempts) == 5 and doc.text is not None
    assert doc.flags == ("needed all 5 rendering attempts", "still failed after 5 attempts: STILL-WRONG")
    three = RULES.model_copy(update={"retry_cap": 3})
    doc = render(sk, three, caller(tmp_path / "c", entry("anthropic"), FakeClient(reply(sk))),
                 check=checks(*[["X"]] * 3)[0], max_tokens=8000, mode="record")
    assert len(doc.attempts) == 3 and doc.flags[0] == "needed all 3 rendering attempts"


def test_an_unreadable_cut_off_or_declined_reply_counts_as_a_failed_attempt(tmp_path):
    sk = twin()
    fake = FakeClient(anthropic_response(text="not json"), anthropic_response(text='{"text": "x', stop="max_tokens"),
                      anthropic_response(text="", stop="refusal"), reply(sk))
    doc = render(sk, RULES, caller(tmp_path, entry("anthropic"), fake), check=checks()[0], max_tokens=8000,
                 mode="record")
    assert [a.error for a in doc.attempts] == ["OutputInvalid", "Truncated", "Refusal", None]
    assert doc.status == "rendered" and "was not a JSON object" in json.dumps(fake.bodies[1]["messages"])
    assert "was cut off" in json.dumps(fake.bodies[2]["messages"])


def test_a_resumed_run_replays_every_attempt_from_the_cache_and_a_dry_run_sends_nothing(tmp_path):
    sk = twin()
    first = render(sk, RULES, caller(tmp_path, entry("anthropic"), FakeClient(reply(sk))),
                   check=checks(["AGAIN"])[0], max_tokens=8000, mode="record")
    fake = FakeClient(RuntimeError("no call may be sent"))
    again = render(sk, RULES, caller(tmp_path, entry("anthropic"), fake, dry_run=True), check=checks(["AGAIN"])[0],
                   max_tokens=8000, mode="record")
    assert fake.bodies == [] and [a.source for a in again.attempts] == ["cache", "cache"]
    same = ("text", "spans", "status", "flags", "doc_id", "renderer")
    assert all(getattr(first, k) == getattr(again, k) for k in same)
    with pytest.raises(DryRunMissing):
        render(twin(seed=2), RULES, caller(tmp_path, entry("anthropic"), fake, dry_run=True), check=checks()[0],
               max_tokens=8000, mode="record")


def test_the_renderer_never_renders_a_planted_or_trap_variant_from_its_skeleton(tmp_path):
    b = base("binary_parity", seed=4, traps=("arity_control",))
    fake = FakeClient(reply(b.planted[0]))
    for variant in (b.planted[0], b.trap_only[0]):
        with pytest.raises(ValueError, match="derived"):
            render(variant, RULES, caller(tmp_path, entry("anthropic"), fake), check=checks()[0], max_tokens=10,
                   mode="record")
    assert fake.bodies == []


# ------------------------------------------------------------------------------------------ derived variants
def test_a_planted_variant_is_derived_from_its_twin_by_re_rendering_only_the_changed_sentence(tmp_path):
    b = base()
    planted, (fid,) = b.planted[0], b.planted[0].plant.params["differs_from_twin"]
    source = rendered(tmp_path, b.consistent)
    fake = FakeClient(revisions({fid: " " + own(planted, fid) + " "}))
    doc = derive(planted, b.consistent, source, caller(tmp_path / "derive", entry("anthropic"), fake),
                 check=checks()[0], max_tokens=4000, mode="record")
    old, new = source.spans[fid], own(planted, fid)
    assert old != new and doc.text == source.text.replace(old, new) and doc.spans == {**source.spans, fid: new}
    assert (doc.doc_id, doc.variant, doc.status, doc.derived_from, doc.changed) == (
        f"{b.base_id}-planted", "planted", "rendered", source.doc_id, (fid,))
    assert doc.skeleton_digest == planted.digest() and doc.rules == source.rules
    assert (doc.renderer.prompt_version, doc.renderer.prompt_sha256) == (prompt.DERIVE_VERSION, prompt.DERIVE.sha256)
    sent = json.dumps(fake.bodies[0])
    assert json.dumps(old)[1:-1] in sent and json.dumps(new)[1:-1] in sent
    assert not any(json.dumps(s)[1:-1] in sent for f, s in source.spans.items() if f != fid)
    assert derivation_problems(planted, doc, source) == []


def test_a_trap_variant_is_derived_from_its_planted_variant_by_re_rendering_the_arity_sentence(tmp_path):
    b = base("binary_parity", traps=("arity_control",))
    planted, trap = b.planted[0], b.trap_only[0]
    (fid,) = planted.plant.params["differs_from_twin"]
    source = rendered(tmp_path, b.consistent)
    middle = derive(planted, b.consistent, source,
                    caller(tmp_path / "planted", entry("anthropic"), FakeClient(revisions({fid: own(planted, fid)}))),
                    check=checks()[0], max_tokens=4000, mode="record")
    arity = trap.arity_fact
    doc = derive(trap, planted, middle,
                 caller(tmp_path / "trap", entry("anthropic"), FakeClient(revisions({arity: own(trap, arity)}))),
                 check=checks()[0], max_tokens=4000, mode="record")
    assert doc.changed == (arity,) and doc.derived_from == middle.doc_id and "three" in doc.spans[arity]
    assert doc.text == middle.text.replace(middle.spans[arity], doc.spans[arity])
    assert derivation_problems(trap, doc, middle) == [] and derivation_problems(planted, middle, source) == []


def test_a_reply_that_keeps_the_old_sentence_or_restates_other_facts_is_quoted_back(tmp_path):
    b = base()
    planted, (fid,) = b.planted[0], b.planted[0].plant.params["differs_from_twin"]
    source = rendered(tmp_path, b.consistent)
    other = next(f.id for f in planted.facts if f.id != fid)
    fake = FakeClient(revisions({fid: source.spans[fid]}), revisions({fid: own(planted, fid), other: "Extra."}),
                      revisions({}), anthropic_response(text="not json"), revisions({fid: own(planted, fid)}))
    doc = derive(planted, b.consistent, source, caller(tmp_path / "derive", entry("anthropic"), fake),
                 check=checks()[0], max_tokens=4000, mode="record")
    assert [a.failed for a in doc.attempts] == [
        (f"the new sentence for fact {fid} is the sentence it replaces; state the fact given",),
        (f"new sentences were given for {other}, which is not a fact to restate",),
        (f"no new sentence was given for fact {fid}",),
        ("the reply was not a JSON object with one new sentence per listed fact",), ()]
    assert doc.status == "rendered" and doc.flags == ("needed all 5 rendering attempts",)
    assert "is the sentence it replaces" in json.dumps(fake.bodies[1]["messages"])


def test_a_derived_variant_whose_checks_keep_failing_is_kept_as_failed(tmp_path):
    b = base()
    planted, (fid,) = b.planted[0], b.planted[0].plant.params["differs_from_twin"]
    source = rendered(tmp_path, b.consistent)
    fake = FakeClient(revisions({fid: own(planted, fid)}))
    check, seen = checks(*[["CHECK-MARKER"]] * 5)
    doc = derive(planted, b.consistent, source, caller(tmp_path / "derive", entry("anthropic"), fake), check=check,
                 max_tokens=4000, mode="record")
    assert doc.status == "failed" and len(seen) == 5 and doc.text is not None
    assert doc.flags[-1] == "still failed after 5 attempts: CHECK-MARKER"


def test_derive_refuses_what_a_variant_cannot_be_derived_from(tmp_path):
    b = base()
    planted = b.planted[0]
    source = rendered(tmp_path, b.consistent)
    fake = FakeClient(revisions({}))
    call = dict(check=checks()[0], max_tokens=4000)
    cases = [((b.consistent, planted, source, "record"), "not derived from"),
             ((planted, b.consistent, source.model_copy(update={"skeleton_digest": "x"}), "record"), "does not render"),
             ((planted, b.consistent, source.model_copy(update={"status": "failed"}), "record"), "passed its checks"),
             ((planted, b.consistent, source, "pipeline_test"), "derives from its own documents"),
             ((planted, b.consistent, source, "test"), "names its mode")]
    for (sk, src, document, mode), message in cases:
        with pytest.raises(ValueError, match=message):
            derive(sk, src, document, caller(tmp_path / "d", entry("anthropic"), fake), mode=mode, **call)
    assert fake.bodies == []


def test_the_derivation_check_catches_any_byte_changed_outside_the_re_rendered_sentences(tmp_path):
    b = base()
    planted, (fid,) = b.planted[0], b.planted[0].plant.params["differs_from_twin"]
    source = rendered(tmp_path, b.consistent)
    doc = derive(planted, b.consistent, source,
                 caller(tmp_path / "derive", entry("anthropic"), FakeClient(revisions({fid: own(planted, fid)}))),
                 check=checks()[0], max_tokens=4000, mode="record")
    other = next(f for f in doc.spans if f != fid)
    edited = doc.model_copy(update={"text": doc.text.replace(doc.spans[other], doc.spans[other][:-1] + "!")})
    assert derivation_problems(planted, edited, source) == [
        "its text differs from the document it was derived from outside the re-rendered sentences"]
    respanned = doc.model_copy(update={"spans": {**doc.spans, other: "x"}})
    assert derivation_problems(planted, respanned, source) == [
        f"its spans for facts {other} differ from the document it was derived from"]
    assert derivation_problems(planted, doc, None) == [
        f"the document it was derived from, {source.doc_id}, is needed to check it"]
    assert derivation_problems(planted, doc.model_copy(update={"derived_from": None}), source) == [
        "a planted variant is derived from its consistent variant's text, and this document was not"]
    assert derivation_problems(planted, doc.model_copy(update={"changed": (other,)}), source)[0] == (
        f"it re-rendered the sentences for facts {other}, and the facts that differ are {fid}")
    assert derivation_problems(b.consistent, source.model_copy(update={"derived_from": "x"}), None) == [
        "a consistent twin is rendered from its skeleton, not derived"]
    assert derivation_problems(b.consistent, source, None) == []


def test_splicing_keeps_every_other_byte():
    text = "One.  Two!\n\nThree? Four."
    assert splice(text, {"a": ("Two!", "2!"), "b": ("Four.", "4.")}) == "One.  2!\n\nThree? 4."
    with pytest.raises(ValueError, match="exactly once"):
        splice("One. One.", {"a": ("One.", "1.")})


# ------------------------------------------------------------------------------------------ rotation and storage
def test_renderers_are_rotated_balanced_and_a_resumed_run_keeps_the_balance():
    r = Rotation(["a", "b", "c"])
    assert [r.next() for _ in range(7)] == ["a", "b", "c", "a", "b", "c", "a"]
    assert [Rotation(["a", "b", "c"], done={"a": 2, "b": 1}).next() for _ in range(1)] == ["c"]
    for args, message in [(([],), "no renderer is configured"), ((["a", "a"],), "listed once"),
                          ((["a"], {"z": 1}), "not configured: z")]:
        with pytest.raises(ValueError, match=message):
            Rotation(*args)


def test_documents_are_stored_outside_the_repository_and_read_back(tmp_path):
    doc = rendered(tmp_path, twin())
    store = DocumentStore(tmp_path / "documents")
    path = store.save("run-1", doc)
    assert path == tmp_path / "documents" / "run-1" / f"{doc.doc_id}.json"
    assert store.load("run-1", doc.doc_id) == doc and store.documents("run-1") == [doc]
    assert store.load("run-1", "missing") is None and store.documents("other") == []
    with pytest.raises(locations.LocationRefused):
        DocumentStore(locations.ROOT / "documents")
    for bad in ("../x", "a/b", ""):
        with pytest.raises(ValueError, match="plain file name"):
            store.path(bad, "d")
    assert isinstance(Document.model_validate_json(path.read_text(encoding="utf-8")), Document)


def test_the_reply_schemas_are_strict_enough_for_every_provider():
    from xon_common.schema import ANTHROPIC_UNSUPPORTED, strict_schema
    schema = strict_schema(Rendering, unsupported=ANTHROPIC_UNSUPPORTED, max_min_items=1, all_required=True)
    assert schema["additionalProperties"] is False and set(schema["required"]) == {"text", "spans"}
    schema = strict_schema(Revisions, unsupported=ANTHROPIC_UNSUPPORTED, max_min_items=1, all_required=True)
    assert schema["additionalProperties"] is False and schema["required"] == ["sentences"]
