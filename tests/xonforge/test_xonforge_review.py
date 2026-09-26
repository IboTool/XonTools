"""XonForge's blind review and human review queue (XONFORGE_SPEC.md §7.3, §7.4; §13; §14, step 5; the user's items 5
and 7 to 10 of 2026-09-25): reviewer selection, blind requests with opaque ids and the user's prompts, the replies and
how their conflicts are matched, canaries and certification, the queue with its random share, and the hash-chained
decision log. Offline: every call goes to a fake client."""
import dataclasses
import json
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from xonforge import locations, prompts
from xonforge.render.schema import Attempt, Document, Renderer, RenderRules, ScanRecord
from xonforge.review import blind, calibration, matching, outcome, reviewers
from xonforge.review.decisions import GENESIS, ChainBroken, DecisionLog
from xonforge.review.queue import QueueItem, QueueStore, flagged, queue, random_share
from xonforge.review.replies import Conflict, ContradictionReply, InventoryReply
from xonforge.skeleton.catalog import CATEGORICAL, ORDINAL

from xonforge_fakes import FakeClient, anthropic_response, caller, entry

ROOT = Path(__file__).resolve().parents[2]
XONFORGE = ROOT / "xonforge"
L1_COMMIT = "1b1749b4afcea1106c439306bcc8600b44095263"


# ------------------------------------------------------------------------------------------ reviewers (§13)
def registered(provider, roles=("review",), **kw):
    return dataclasses.replace(entry(provider, **kw), roles=roles)


def candidates():
    return [registered("anthropic", roles=("render", "review")), registered("openai"), registered("google"),
            registered("xai")]


def test_no_reviewer_shares_the_renderer_s_provider():
    pool = candidates()
    for renderer in pool:
        chosen = reviewers.select(renderer, pool, mode="record")
        assert len(chosen) == reviewers.K == 2
        assert all(reviewers.provider_of(r) != reviewers.provider_of(renderer) for r in chosen)
    assert [r.provider for r in reviewers.select(pool[1], pool, k=3, mode="record")] == ["anthropic", "google", "xai"]
    with pytest.raises(ValueError, match="4 reviewers are needed from providers other than the renderer's"):
        reviewers.select(pool[0], pool, k=4, mode="record")


def test_an_openai_compatible_entry_is_one_provider_per_address():
    here = registered("openai_compatible", name="here", base_url="http://localhost:11434/v1")
    same = registered("openai_compatible", roles=("render",), name="same", base_url="http://localhost:11434/v1")
    there = registered("openai_compatible", name="there", base_url="http://example.org:8000/v1")
    assert [r.name for r in reviewers.select(same, [here, there], k=1, mode="record")] == ["there"]


def test_reviewers_are_listed_once_and_registered_for_the_review_role():
    pool = candidates()
    for mode in ("record", "pipeline_test"):
        with pytest.raises(ValueError, match="listed once"):
            reviewers.select(pool[0], pool + [pool[1]], mode=mode)
        with pytest.raises(ValueError, match="not registered for the review role: gpt"):
            reviewers.select(pool[0], [registered("openai", roles=("render",), name="gpt"), pool[2]], mode=mode)


def test_the_mode_is_always_named():
    pool = candidates()
    with pytest.raises(TypeError):
        reviewers.select(pool[0], pool)
    for mode in (None, "", "test", "Record"):
        with pytest.raises(ValueError, match="names its mode, record or pipeline_test"):
            reviewers.select(pool[0], pool, mode=mode)


def test_in_the_pipeline_test_mode_reviewers_may_share_the_renderer_s_provider_but_not_its_model():
    sonnet = registered("anthropic", roles=("render",), name="claude-sonnet", model="claude-sonnet-5")
    opus = registered("anthropic", name="claude-opus", model="claude-opus-5-5")
    fable = registered("anthropic", name="claude-fable", model="claude-fable-5-1")
    assert [r.name for r in reviewers.select(sonnet, [opus, fable], mode="pipeline_test")] == ["claude-opus",
                                                                                                "claude-fable"]
    with pytest.raises(ValueError, match="2 reviewers are needed from providers other than the renderer's"):
        reviewers.select(sonnet, [opus, fable], mode="record")
    also_sonnet = registered("anthropic", name="sonnet-again", model="claude-sonnet-5")
    with pytest.raises(ValueError, match=r"2 reviewers of different models are needed, none of them the renderer's "
                                         r"\(claude-sonnet-5\), and 1 of the listed ones are"):
        reviewers.select(sonnet, [also_sonnet, opus], mode="pipeline_test")
    opus_twice = registered("anthropic", name="opus-again", model="claude-opus-5-5")
    with pytest.raises(ValueError, match="and 1 of the listed ones are"):
        reviewers.select(sonnet, [opus, opus_twice], mode="pipeline_test")
    assert [r.name for r in reviewers.select(sonnet, [opus, opus_twice, fable], mode="pipeline_test")] == [
        "claude-opus", "claude-fable"]


# ------------------------------------------------------------------------------------------ blind requests (§13)
DOCS = {"b0001-planted": "Ada is older than Ben. Ben is older than Cleo. Cleo is older than Ada.",
        "b0001-consistent": "Ada is older than Ben. Ben is older than Cleo. Ada is older than Cleo.",
        "b0002-planted": "Assume that Dev is on the red team. Dev is not on the red team."}
CANARIES = {"canary-superlative": "Eli arrived first. Femi arrived before anyone else."}


def reply(*conflicts):
    return anthropic_response(text=json.dumps(
        {"conflicts": [{"statements": list(c), "explanation": "They cannot all be true."} for c in conflicts]}))


def test_review_ids_are_opaque_and_the_order_is_shuffled_by_the_seed():
    batch = blind.assemble("run-1", "batch-1", list(DOCS), list(CANARIES), seed=7, salt="s" * 32)
    assert {i.ref for i in batch.items} == set(DOCS) | set(CANARIES)
    for item in batch.items:
        assert item.review_id.startswith("r") and len(item.review_id) == 13
        assert not any(part in item.review_id for part in ("b0001", "b0002", "planted", "consistent", "canary"))
    again = blind.assemble("run-1", "batch-1", list(DOCS), list(CANARIES), seed=7, salt="s" * 32)
    assert again == batch
    salted = blind.assemble("run-1", "batch-1", list(DOCS), list(CANARIES), seed=7, salt="t" * 32)
    assert not {i.review_id for i in salted.items} & {i.review_id for i in batch.items}
    orders = {tuple(i.ref for i in blind.assemble("r", "b", list(DOCS), list(CANARIES), seed=s, salt="x").items)
              for s in range(20)}
    assert len(orders) > 1
    assert len(blind.assemble("r", "b", list(DOCS), [], seed=1).salt) == 32
    with pytest.raises(ValueError, match="appears once"):
        blind.assemble("r", "b", ["d1", "d1"], [], seed=1)
    for n in (0, 21):
        with pytest.raises(ValueError, match=f"a batch holds 1 to 20 generated documents, not {n}"):
            blind.assemble("r", "b", [f"d{i}" for i in range(n)], [], seed=1)
    assert len(blind.assemble("r", "b", [f"d{i}" for i in range(20)], ["c1"], seed=1).items) == 21


@pytest.mark.parametrize("prompt, file, schema", [
    ("contradiction_only", "review_contradiction.txt", ContradictionReply),
    ("relational_inventory", "review_inventory.txt", InventoryReply)])
def test_a_review_request_holds_only_the_review_id_the_text_and_the_user_s_prompt(tmp_path, prompt, file, schema):
    batch = blind.assemble("run-1", "batch-1", list(DOCS), list(CANARIES), seed=3, reviewer="anthropic",
                           prompt=prompt)
    assert batch.prompt_version == prompts.load(file).version
    texts = {**DOCS, **CANARIES}
    empty = {"conflicts": []} if prompt == "contradiction_only" else {"inventory": [], "conflicts": []}
    fake = FakeClient(anthropic_response(text=json.dumps(empty)))
    reviewer = entry("anthropic", structured_output="json_schema")
    results = blind.review(batch, texts, prompt, caller(tmp_path, reviewer, fake), max_tokens=2048)
    assert set(results) == {i.review_id for i in batch.items}
    assert all(r.parsed == schema.model_validate(empty) for r in results.values())
    for item, body in zip(batch.items, fake.bodies):
        assert body["system"] == prompts.load(file).text
        assert body["messages"] == [{"role": "user", "content": f"Document {item.review_id}:\n\n{texts[item.ref]}"}]
        sent = json.dumps(body)
        for secret in ["run-1", "batch-1", batch.salt, *DOCS, *CANARIES, "planted", "consistent", "canary"]:
            assert secret not in sent
    logged = (tmp_path / "log.jsonl").read_text(encoding="utf-8")
    for secret in [*DOCS, *CANARIES, batch.salt]:
        assert secret not in logged
    other = "relational_inventory" if prompt == "contradiction_only" else "contradiction_only"
    with pytest.raises(ValueError, match=f"is reviewed with the {prompt} prompt, not {other}"):
        blind.review(batch, texts, other, caller(tmp_path, reviewer, fake), max_tokens=2048)


def test_the_review_prompts_and_replies_are_the_user_s():
    assert {n: blind.load_prompt(n).version for n in blind.PROMPTS} == {
        "contradiction_only": "contradiction-only-v1", "relational_inventory": "relational-inventory-v1"}
    with pytest.raises(ValueError, match="the review prompts are"):
        blind.load_prompt("other")
    assert list(ContradictionReply.model_fields) == ["conflicts"]
    assert list(InventoryReply.model_fields) == ["inventory", "conflicts"]
    fields = Conflict.model_json_schema()["properties"]
    assert (fields["statements"]["description"], fields["explanation"]["description"]) == (
        "Each statement quoted verbatim.", "One sentence.")
    with pytest.raises(ValidationError):
        ContradictionReply.model_validate({"conflicts": [], "inventory": []})


def test_a_refused_truncated_or_malformed_reply_leaves_its_item_unreviewed_and_the_batch_goes_on(tmp_path):
    batch = blind.assemble("run-1", "batch-1", list(DOCS), [], seed=3, reviewer="anthropic",
                           prompt="contradiction_only")
    fake = FakeClient(anthropic_response(text="", stop="refusal"), anthropic_response(text="{}"), reply())
    reviewer = entry("anthropic", structured_output="json_schema")
    results = blind.review(batch, DOCS, "contradiction_only", caller(tmp_path, reviewer, fake), max_tokens=2048)
    kinds = [type(results[i.review_id]).__name__ for i in batch.items]
    assert kinds == ["Refusal", "OutputInvalid", "Result"]
    out = outcome.outcome(batch, results, plants={}, canaries={})
    first, second, third = (i.ref for i in batch.items)
    assert out.flags[first] == ("anthropic, with the contradiction_only prompt, returned no usable reply (Refusal)",
                                "anthropic's batch held no defect canary, so it cannot certify this document clean")
    assert "returned no usable reply (OutputInvalid)" in out.flags[second][0]
    assert not out.certifiable and len(out.flags[third]) == 1


# ------------------------------------------------------------------------------------------ matching (item 7)
def test_a_statement_matches_a_sentence_after_normalization_if_either_contains_the_other():
    s = "Quinn, always punctual, had arrived a full ten minutes before anyone else."
    assert matching.matches("quinn, always punctual, had arrived", s)
    assert matching.matches("\u201cQuinn, always  punctual,\nhad arrived a full ten minutes before anyone "
                            "else.\u201d", s)
    assert matching.matches("QUINN, ALWAYS PUNCTUAL, HAD ARRIVED A FULL TEN MINUTES BEFORE ANYONE ELSE. Milo left.", s)
    assert matching.matches("Milo\u2019s notes", "Milo's notes were long.")
    assert matching.matches("Milo arrived \ufb01rst", "Milo arrived first, carrying notes.")
    assert not matching.matches("Quinn arrived last.", s)
    assert not matching.matches("\u201c \u201d", s) and not matching.matches(s, "  ")


def test_a_conflict_matches_a_defect_with_two_of_its_sentences_or_its_only_one():
    defect = ["Ada is older than Ben.", "Ben is older than Cleo.", "Cleo is older than Ada."]
    assert matching.found(["Ada is older than Ben.", "Cleo is older than Ada."], defect)
    assert matching.found(["Ada is older than Ben. Ben is older than Cleo."], defect)
    assert not matching.found(["Ada is older than Ben.", "Dev is older than Ada."], defect)
    assert not matching.found([], defect)
    assert matching.found(["Rosa never worked in finance"], ["Rosa never worked in finance."])
    with pytest.raises(ValueError, match="at least one sentence"):
        matching.found(["x"], [])


def test_batch_records_stay_outside_the_repository(tmp_path):
    store = blind.BatchStore(tmp_path / "batches")
    batch = blind.assemble("run-1", "batch-1", list(DOCS), [], seed=1)
    store.save(batch)
    assert store.load("run-1", "batch-1") == batch and store.load("run-1", "batch-2") is None
    with pytest.raises(FileExistsError):
        store.save(batch)
    with pytest.raises(locations.LocationRefused):
        blind.BatchStore(locations.ROOT / "batches")


# ------------------------------------------------------------------------------------------ canary scores
def canary(cid, kind):
    if kind == "clean":
        return calibration.ReviewCanary(id=cid, kind="clean", text="Some text.")
    return calibration.ReviewCanary(id=cid, kind="defect", text="Ada won. Ada lost.", defect="a clash",
                                    defect_kind="negation", attributes=("team",), defect_sentences=("Ada won.",
                                                                                                    "Ada lost."))


def test_recall_and_false_alarms_on_a_batch_s_canaries_are_kept_as_exact_fractions():
    batch = [canary("d1", "defect"), canary("d2", "defect"), canary("d3", "defect"), canary("c1", "clean"),
             canary("c2", "clean")]
    s = calibration.score("gpt", "batch-1", batch, {"d1": True, "d2": False, "d3": True, "c1": True, "c2": False})
    assert (s.recall, s.false_alarm_rate, s.missed, s.alarms) == (Fraction(2, 3), Fraction(1, 2), ("d2",), ("c1",))
    only_clean = calibration.score("gpt", "batch-1", batch[3:], {"c1": False, "c2": False})
    assert only_clean.recall is None and only_clean.false_alarm_rate == 0
    with pytest.raises(ValueError, match="no judgement for the canaries d3"):
        calibration.score("gpt", "batch-1", batch, {"d1": True, "d2": True, "c1": False, "c2": False})


def test_a_review_canary_says_what_its_defect_is_where_and_its_sentences_verbatim(tmp_path):
    with pytest.raises(ValidationError, match="says what its defect is, its kind, the attributes it is on"):
        calibration.ReviewCanary(id="x", kind="defect", text="t", defect="d")
    with pytest.raises(ValidationError, match="a clean one has no defect"):
        calibration.ReviewCanary(id="x", kind="clean", text="t", defect="d")
    with pytest.raises(ValidationError, match=r"each defect sentence occurs once in the text, verbatim; these do not: "
                                              r"Ada won\. / Ada lost\."):
        calibration.ReviewCanary(id="x", kind="defect", text="Ada won. Ada won.", defect="d", defect_kind="negation",
                                 attributes=("team",), defect_sentences=("Ada won.", "Ada lost."))
    for name in ("a", "b"):
        (tmp_path / f"{name}.json").write_text(json.dumps({"id": "same", "kind": "clean", "text": "t"}),
                                               encoding="utf-8")
    with pytest.raises(ValueError, match="an id of its own"):
        calibration.load(tmp_path)


def test_the_review_canaries_are_synthetic_defects_base_32_s_clash_and_l1_s_60_consistent_documents():
    pool = calibration.load()
    assert calibration.FOLDER == XONFORGE / "canaries" / "review"
    defects = [c for c in pool if c.kind == "defect"]
    clean = [c for c in pool if c.kind == "clean"]
    assert (len(defects), len(clean)) == (15, 60)
    assert sorted({a for c in defects for a in c.attributes}) == sorted(set(ORDINAL) | set(CATEGORICAL))
    assert {c.defect_kind for c in defects} == set(calibration.DEFECT_KINDS)
    assert [c.id for c in defects if c.source != "synthetic"] == ["l1-base32-superlative"]
    rows = [json.loads(line) for line in (ROOT / "data" / "consistency" / "corpus.jsonl").read_text(
        encoding="utf-8").splitlines()]
    consistent = {r["doc_id"]: r["text"] for r in rows if r["variant"] == "consistent"}
    assert sorted(c.source.split(", ")[1] for c in clean) == sorted(consistent)
    assert all(c.text == consistent[c.source.split(", ")[1]] and L1_COMMIT in c.source for c in clean)
    pack = json.loads((ROOT / "data" / "consistency" / "corpus_review_pack.json").read_text(encoding="utf-8"))
    base32 = next(c for c in defects if c.id == "l1-base32-superlative")
    assert base32.text == pack["attempt_flagged"]["32"]["text"] and L1_COMMIT in base32.source
    assert [s.split(",")[0] for s in base32.defect_sentences] == ["Milo arrived first", "Quinn"]


def test_a_batch_draws_5_defect_canaries_on_its_attributes_first_a_kind_at_a_time_and_2_clean_ones():
    pool = calibration.load()
    drawn = calibration.draw(pool, {"team", "age"}, seed=11)
    kinds = [c.kind for c in drawn]
    assert kinds.count("defect") == 5 and kinds.count("clean") == 2
    assert {"syn-superlative-age", "syn-order-age", "syn-same-team"} <= {c.id for c in drawn}
    assert calibration.draw(pool, {"team", "age"}, seed=11) == drawn
    assert len({tuple(c.id for c in calibration.draw(pool, {"team"}, seed=s)) for s in range(10)}) > 1
    ordinal = calibration.draw(pool, {"arrival", "score", "speed", "age", "height"}, seed=3)
    kinds = Counter(c.defect_kind for c in ordinal if c.kind == "defect")
    assert set(kinds) == {"order_cycle", "superlative"} and sorted(kinds.values()) == [2, 3]
    assert all(set(c.attributes) & {"arrival", "score", "speed", "age", "height"} for c in ordinal
               if c.kind == "defect")
    with pytest.raises(ValueError, match="a batch holds 5 defect canaries and 2 clean ones, and the registry has 4 "
                                         "and 60"):
        calibration.draw([c for c in pool if c.kind == "clean"] + [c for c in pool if c.kind == "defect"][:4],
                         {"team"}, seed=1)
    batch = blind.batch_for("run-1", "batch-1", ["b1-planted"], pool, {"team", "age"}, 11, reviewer="opus",
                            prompt="contradiction_only")
    assert sorted(i.ref for i in batch.items if i.kind == "canary") == sorted(c.id for c in drawn)
    assert (batch.seed, batch.reviewer, batch.prompt) == (11, "opus", "contradiction_only")


def test_a_batch_is_certifiable_at_a_recall_of_4_of_5_and_not_below():
    five = [canary(f"d{i}", "defect") for i in range(5)] + [canary("c1", "clean"), canary("c2", "clean")]
    judged = {c.id: c.kind == "defect" for c in five}
    assert calibration.certifiable(calibration.score("opus", "b", five, judged))
    one_miss = calibration.score("opus", "b", five, {**judged, "d0": False})
    assert one_miss.recall == Fraction(4, 5) and calibration.certifiable(one_miss)
    two_misses = calibration.score("opus", "b", five, {**judged, "d0": False, "d1": False})
    assert two_misses.recall == Fraction(3, 5) and not calibration.certifiable(two_misses)
    three = calibration.score("opus", "b", five[2:], {c.id: c.kind == "defect" for c in five[2:]})
    assert three.recall == 1 and not calibration.certifiable(three)
    assert calibration.caught(five[0], [["Ada won.", "Ada lost."]])
    assert not calibration.caught(five[0], [["Ada won.", "Ben lost."]]) and not calibration.caught(five[0], [])
    assert calibration.caught(five[5], [["anything"]]) and not calibration.caught(five[5], [])


def test_a_batch_s_outcome_flags_conflicts_outside_the_plant_and_scores_its_canaries(tmp_path):
    pool = {c.id: c for c in calibration.load()}
    defects = sorted(c for c in pool if pool[c].kind == "defect")[:5]
    clean = sorted(c for c in pool if pool[c].kind == "clean")[:2]
    plant = ("Ada is older than Ben.", "Ben is older than Cleo.", "Cleo is older than Ada.")
    docs = {"b0001-planted": " ".join(("The club met.",) + plant), "b0001-consistent": "The club met. Ada is older."}
    batch = blind.assemble("run-1", "batch-1", list(docs), defects + clean, seed=5, reviewer="opus",
                           prompt="contradiction_only")
    stray = ("Dev arrived first.", "Eli arrived first.")

    def answer(ref):
        if ref == "b0001-planted":
            return reply(plant[:2], stray)
        if ref == "b0001-consistent":
            return reply(stray)
        if ref in defects[:4]:
            return reply(pool[ref].defect_sentences)
        return reply(stray) if ref == clean[0] else reply()
    fake = FakeClient(*[answer(i.ref) for i in batch.items])
    texts = {**docs, **{c: pool[c].text for c in defects + clean}}
    results = blind.review(batch, texts, "contradiction_only",
                           caller(tmp_path, entry("anthropic", structured_output="json_schema"), fake), max_tokens=2048)
    plants = {"b0001-planted": plant, "b0001-consistent": ()}
    out = outcome.outcome(batch, results, plants=plants, canaries={c: pool[c] for c in defects + clean})
    assert (out.score.recall, out.score.missed, out.score.false_alarm_rate, out.score.alarms) == (
        Fraction(4, 5), (defects[4],), Fraction(1, 2), (clean[0],))
    assert out.certifiable and out.plants_found == ("b0001-planted",)
    flag = ('opus, with the contradiction_only prompt, reported a conflict that is not the plant\'s: '
            '"Dev arrived first." / "Eli arrived first." (They cannot all be true.)')
    assert out.flags == {"b0001-planted": (flag,), "b0001-consistent": (flag,)}
    lacking = outcome.missing(list(docs), [out], ["opus", "fable"], ["contradiction_only"])
    assert lacking == {d: ("no review by fable with the contradiction_only prompt",) for d in docs}
    assert outcome.reviewer_flags(list(docs), [out], ["opus"], ["contradiction_only"]) == out.flags
    with pytest.raises(ValueError, match="has no result for 1 of its items"):
        outcome.outcome(batch, dict(list(results.items())[1:]), plants=plants, canaries={c: pool[c] for c in pool})


# ------------------------------------------------------------------------------------------ the queue
def document(doc_id, flags=(), scans=()):
    return Document(doc_id=doc_id, base_id=doc_id.split("-")[0], variant="planted", skeleton_digest="0" * 64,
                    mode="record", renderer=Renderer(entry="e", provider="anthropic", model="m", prompt_version="v"),
                    rules=RenderRules(words=300, explicitness="stated", lexical_variety="low", min_spacing=2),
                    status="failed" if any(f.startswith("still failed") for f in flags) else "rendered",
                    text="Some text.", attempts=(Attempt(number=1),), flags=tuple(flags), scans=tuple(scans))


def test_every_flagged_document_is_queued_with_its_reasons_and_no_other():
    docs = [document("b1-planted"), document("b2-planted", flags=["needed all 5 rendering attempts"]),
            document("b3-planted", flags=["needed all 5 rendering attempts", "still failed after 5 attempts: x"],
                     scans=[ScanRecord(scan="order_cycles", result="hits", trusted=False)]),
            document("b4-planted")]
    items = flagged("run-1", docs, {"b4-planted": ["a conflict outside the plant"]})
    assert [(i.doc_id, i.reasons) for i in items] == [
        ("b2-planted", ("needed all 5 rendering attempts",)),
        ("b3-planted", ("needed all 5 rendering attempts", "still failed after 5 attempts: x",
                        "the order_cycles scan found hits")),
        ("b4-planted", ("a reviewer flagged: a conflict outside the plant",))]
    with pytest.raises(ValueError, match="reviewer flags for documents not given: b9-planted"):
        flagged("run-1", docs, {"b9-planted": ["x"]})


@pytest.mark.parametrize("n, drawn, in_sample", [(0, 0, 0), (1, 1, 1), (5, 1, 2), (10, 1, 2), (11, 2, 2), (20, 2, 2),
                                                 (21, 3, 3), (300, 30, 30)])
def test_the_random_share_is_a_tenth_of_the_unflagged_rounded_up_at_least_1_or_2_in_the_sample(n, drawn, in_sample):
    ids = [f"b{i:04d}-planted" for i in range(n)]
    assert len(random_share(ids, 7)) == drawn and len(random_share(ids, 7, sample=True)) == in_sample
    chosen = random_share(list(reversed(ids)), 7)
    assert chosen == sorted(chosen) == random_share(ids, 7) and set(chosen) <= set(ids)
    if n >= 20:
        assert len({tuple(random_share(ids, s)) for s in range(10)}) > 1


def test_the_queue_holds_the_flagged_documents_and_the_random_share_drawn_with_the_logged_seed(tmp_path):
    docs = [document(f"b{i}-planted") for i in range(1, 13)]
    log = DecisionLog(tmp_path / "decisions.jsonl", clock=clock)
    with pytest.raises(ValueError, match="run-1 has no sample seed in the decision log"):
        queue("run-1", docs, {}, log)
    log.log_seed("run-1", 20260925)
    items = queue("run-1", docs, {"b3-planted": ["a conflict"]}, log, sample=True)
    assert items[0] == QueueItem(run="run-1", doc_id="b3-planted", reasons=("a reviewer flagged: a conflict",))
    spot = items[1:]
    assert [i.doc_id for i in spot] == random_share([d.doc_id for d in docs if d.doc_id != "b3-planted"], 20260925,
                                                    sample=True)
    assert len(spot) == 2 and all(i.reasons == ("drawn for a spot check: the random share of unflagged documents, "
                                                "with the run's seed 20260925",) for i in spot)


def test_the_queue_is_kept_outside_the_repository(tmp_path):
    store = QueueStore(tmp_path / "queue")
    items = [QueueItem(run="run-1", doc_id="b2-planted", reasons=("needed all 5 rendering attempts",))]
    store.save("run-1", items)
    assert store.load("run-1") == items and store.load("run-2") == []
    with pytest.raises(ValueError, match="belongs to run run-2"):
        store.save("run-2", items)
    with pytest.raises(locations.LocationRefused):
        QueueStore(locations.ROOT / "queue")


# ------------------------------------------------------------------------------------------ the decision log
def clock():
    return datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def filled(tmp_path):
    log = DecisionLog(tmp_path / "reviews" / "decisions.jsonl", clock=clock)
    log.log_seed("run-1", 20260925)
    log.decide("run-1", "b1-planted", "accept", "reads well", reviewer="MF")
    log.decide("run-1", "b2-planted", "regenerate", "a second superlative on arrival")
    log.decide("run-1", "b3-planted", "discard", "the negation was lost")
    return log


def test_decisions_are_appended_to_a_chain_that_verifies(tmp_path):
    log = filled(tmp_path)
    count, head = log.verify()
    entries = log.entries()
    assert count == 4 and head == entries[-1].hash != GENESIS
    assert [e.seq for e in entries] == [0, 1, 2, 3] and entries[0].prev == GENESIS
    assert all(b.prev == a.hash for a, b in zip(entries, entries[1:]))
    assert [e.decision for e in entries[1:]] == ["accept", "regenerate", "discard"]
    assert log.seed("run-1") == 20260925 and log.seed("run-2") is None
    assert DecisionLog(tmp_path / "none.jsonl").verify() == (0, GENESIS)


@pytest.mark.parametrize("tamper", ["alter", "remove", "swap", "insert"])
def test_altering_removing_reordering_or_inserting_an_entry_breaks_the_chain(tmp_path, tamper):
    log = filled(tmp_path)
    lines = log.path.read_text(encoding="utf-8").splitlines()
    if tamper == "alter":
        lines[2] = lines[2].replace("a second superlative", "a third superlative")
    elif tamper == "remove":
        del lines[1]
    elif tamper == "swap":
        lines[1], lines[2] = lines[2], lines[1]
    else:
        lines.insert(2, lines[1])
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ChainBroken, match="line [23]"):
        log.verify()
    with pytest.raises(ChainBroken):
        log.decide("run-1", "b4-planted", "accept", "fine")


def test_removing_the_last_entries_shows_only_against_a_head_kept_elsewhere(tmp_path):
    log = filled(tmp_path)
    _, head = log.verify()
    lines = log.path.read_text(encoding="utf-8").splitlines()
    log.path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    count, shorter = log.verify()
    assert count == 3 and shorter != head


def test_a_decision_needs_a_reason_and_a_run_s_seed_comes_once_before_its_decisions(tmp_path):
    log = filled(tmp_path)
    with pytest.raises(ValidationError, match="a reason"):
        log.decide("run-1", "b4-planted", "accept", "  ")
    with pytest.raises(ValidationError):
        log.decide("run-1", "b4-planted", "approve", "fine")
    with pytest.raises(ValueError, match="already has its sample seed"):
        log.log_seed("run-1", 1)
    log.decide("run-2", "b1-planted", "accept", "fine")
    with pytest.raises(ValueError, match="comes before any flag exists"):
        log.log_seed("run-2", 1)
    assert log.verify()[0] == 5


def test_the_quota_and_split_seeds_are_logged_once_each_beside_the_sample_seed(tmp_path):
    log = DecisionLog(tmp_path / "decisions.jsonl")
    log.log_seed("corpus-v0.1", 11, kind="split_seed")
    log.log_seed("corpus-v0.1", 12, kind="quota_seed")
    log.log_seed("corpus-v0.1", 13)
    assert [log.seed("corpus-v0.1", k) for k in ("split_seed", "quota_seed", "sample_seed")] == [11, 12, 13]
    with pytest.raises(ValueError, match="already has its split seed"):
        log.log_seed("corpus-v0.1", 14, kind="split_seed")
    with pytest.raises(ValueError, match="the seeds are sample_seed, quota_seed, split_seed, not 'seed'"):
        log.log_seed("corpus-v0.1", 14, kind="seed")
    log.decide("corpus-v0.2", "b1-planted", "accept", "fine")
    with pytest.raises(ValueError, match="already has decisions; its quota seed comes before"):
        log.log_seed("corpus-v0.2", 1, kind="quota_seed")
    assert log.verify()[0] == 4


def test_the_decision_log_is_kept_outside_the_repository():
    with pytest.raises(locations.LocationRefused):
        DecisionLog(locations.ROOT / "reviews" / "decisions.jsonl")
