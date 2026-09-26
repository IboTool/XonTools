"""The dashboard (XONFORGE_SPEC.md §10, §14 step 9). Offline: no test sends an API call or starts a run."""
from pathlib import Path

import pytest

from xonforge import locations, registry
from xonforge.app import views
from xonforge.corpus.terms import TermsCheck
from xonforge.render.schema import Attempt, Document, Renderer, RenderRules
from xonforge.review.decisions import DecisionLog
from xonforge.review.queue import QueueItem
from xonforge.skeleton.generators import generate

ROOT = Path(__file__).resolve().parents[2]
CANARY = "sk-canary-dashboard-0123456789"


def _document(doc_id="order_cycle-1-aaaa-planted", **update):
    fields = dict(doc_id=doc_id, base_id="order_cycle-1-aaaa", variant="planted", skeleton_digest="0" * 64,
                  mode="pipeline_test",
                  renderer=Renderer(entry="claude-sonnet", provider="anthropic", model="m", prompt_version="v"),
                  rules=RenderRules(words=200, explicitness="stated", lexical_variety="low", min_spacing=1, level=1),
                  status="rendered", text="A memo.", spans={"f1": "A memo."}, attempts=(Attempt(number=1),),
                  measured={"words": 180, "min_spacing": 2})
    fields.update(update)
    return Document(**fields)


def test_a_configure_draft_round_trips_and_stays_outside_the_repository(tmp_path):
    draft = views.default_draft()
    assert draft["target"] == 300 and draft["review_k"] == 2
    assert views.validate_draft(draft) == []
    assert sum(views.proportions_of(draft).values()) == 1
    preview = views.quota_preview(draft)
    assert sum(row["units"] for row in preview) == 300
    assert all(row["plant_type"] not in views.JUDGED_PLANTS for row in preview)
    path = views.save_draft(tmp_path / "configure.yaml", draft)
    assert views.load_draft(path)["target"] == 300
    defaults = (ROOT / "xonforge" / "config" / "defaults.yaml").read_text(encoding="utf-8")
    assert "target:" not in defaults
    with pytest.raises(locations.LocationRefused):
        views.save_draft(ROOT / "xonforge" / "config" / "dashboard.yaml", draft)
    bad = {**draft, "target": 0, "development": 10}
    assert views.validate_draft(bad)


def test_judged_plants_are_left_out_of_the_proportional_preview():
    draft = views.default_draft()
    draft["plant_types"] = ["causal_inconsistency"]
    assert views.quota_preview(draft) == []


def test_provider_rows_name_a_key_as_present_or_missing_and_never_its_value(monkeypatch):
    for env in registry.KEY_ENV.values():
        monkeypatch.setenv(env, CANARY)
    rows = views.provider_rows()
    assert rows and {row["key"] for row in rows} <= {"present", "missing", "not needed"}
    shown = views.flatten(rows) + views.flatten(views.terms_rows()) + views.flatten(views.constants())
    assert CANARY not in shown


def test_only_the_sample_may_start_and_the_first_corpus_waits():
    corpus = views.run_status("first_corpus")
    assert corpus["allowed"] is False
    assert any("first corpus" in problem for problem in corpus["problems"])
    sample = views.run_status("sample")
    assert all("first corpus" not in problem for problem in sample["problems"])


def test_a_decision_is_appended_only_with_a_reason_and_the_queue_counts_it(tmp_path):
    log = DecisionLog(tmp_path / "decisions.jsonl")
    log.log_seed("sample", 1)
    with pytest.raises(ValueError, match="reason"):
        views.record_decision(log, "sample", "doc-1", "accept", "  ")
    views.record_decision(log, "sample", "doc-1", "accept", "Accepted on the spot check.")
    items = [QueueItem(run="sample", doc_id="doc-1", reasons=("drawn for a spot check",)),
             QueueItem(run="sample", doc_id="doc-2", reasons=("a check fails",))]
    stats = views.queue_statistics(items, log.entries())
    assert stats == {"queued": 2, "open": 1, "decided": 1, "spot_checks": 1}
    verification = views.decision_verification(log)
    assert verification["ok"] and verification["entries"] == 2


def test_quality_counts_flags_and_discards_and_calibration_stops_before_the_document(tmp_path):
    flagged = _document(flags=("still failed after 5 attempts: x",))
    clean = _document(doc_id="order_cycle-2-bbbb-consistent", variant="consistent")
    assert views.flag_rates([flagged, clean]) == [
        {"renderer": "claude-sonnet", "documents": 2, "flagged": 1}]
    assert views.difficulty_rows([clean])[0]["words_set"] == 200
    assert views.difficulty_rows([clean])[0]["words_measured"] == 180
    packet = f"claude-opus / contradiction_only: recall 5/5, false alarms 0/2, certifiable\n\n## doc\n\n{CANARY}\n"
    assert views.score_lines(packet) == [
        "claude-opus / contradiction_only: recall 5/5, false alarms 0/2, certifiable"]
    assert CANARY not in views.flatten(views.score_lines(packet))
    base = generate("order_cycle", seed=1, genre="memo", level=1)
    (tmp_path / "skeletons").mkdir()
    (tmp_path / "skeletons" / "one.json").write_text(base.model_dump_json(), encoding="utf-8")
    counts = views.solver_discard_counts(tmp_path / "skeletons")
    assert counts == {"present": True, "kept": 1, "discarded": 0, "problems": []}
    assert views.solver_discard_counts(tmp_path / "missing")["present"] is False


def test_export_is_refused_for_a_pipeline_test_and_for_unchecked_terms():
    doc = _document()
    refusal = views.export_refusal([doc])
    assert any("pipeline-test" in reason for reason in refusal)
    assert any("terms" in reason for reason in refusal)
    preview = views.datasheet_preview([doc])
    assert preview["sections"][0] == "Motivation" and "License" in preview["sections"]
    assert CANARY not in views.flatten(preview)
    record = _document(mode="record")
    checked = {"anthropic": TermsCheck.model_validate(
        {"checked": "2026-09-26", "allows": True, "sources": ["https://example.test/terms"], "notes": None})}
    assert views.export_refusal([record], checked) == []


def test_the_changelog_entry_and_the_call_log_are_the_logs_page(tmp_path):
    text = (ROOT / "CHANGELOG_EXPERIMENTS.md").read_text(encoding="utf-8")
    latest = views.changelog_latest(text)
    assert latest.startswith("## ") and "step 9" in latest
    from xon_common.calllog import CallLog

    log = tmp_path / "log.jsonl"
    CallLog(log).write(run="sample", provider="claude-sonnet", model="m", tag="render", source="api",
                       input_tokens=3, output_tokens=4, cost_usd=0.1, stop_reason="end")
    shown = views.flatten(views.call_rows(log))
    assert "claude-sonnet" in shown and CANARY not in shown


def test_documents_filter_by_variant_status_and_renderer():
    docs = [_document(), _document(doc_id="other-consistent", variant="consistent", status="failed",
                                   renderer=Renderer(entry="other", provider="openai", model="m",
                                                     prompt_version="v"))]
    assert [d.doc_id for d in views.filter_documents(docs, variant="planted", renderer="claude-sonnet")] == [
        "order_cycle-1-aaaa-planted"]
    assert views.provenance(docs[0], None, []).get("plant") is None
    assert views.provenance(docs[0], None, []).get("renderer") == "claude-sonnet"
