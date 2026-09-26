"""Headless test of the Consistency mode (XON_A1_CONSISTENCY.md §7) in dry-run, answering from fixtures recorded with
a scripted client. Never calls the API."""
from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

from llm_fakes import (ANA_CLAIMS, ANA_ENTITIES, ANA_ENTITIES_V22, ANA_TEXT, MALFORMED_RATIONALE,  # noqa: E402
                       ScriptedClient)
from xon.llm import client as client_module  # noqa: E402
from xon.llm.client import API_KEY_ENV, LLM, RECORD_ENV  # noqa: E402
from xon.llm.engine import analyze_text, rescored  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _ok(at):
    assert not at.exception, [e.message for e in at.exception]


def _button(at, label):
    return next(b for b in list(at.sidebar.button) + list(at.main.button) if b.label == label)


def _app(tmp_path, monkeypatch, client, record):
    """The app with no key set, answering from the fixtures that record(llm) makes with the scripted client."""
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.setenv(RECORD_ENV, "1")
    record(LLM(cache_dir=tmp_path / "recording", client=client, fixture_dir=tmp_path / "fixtures"))
    monkeypatch.delenv(RECORD_ENV)
    monkeypatch.setattr(client_module, "FIXTURE_DIR", tmp_path / "fixtures")
    monkeypatch.chdir(tmp_path)  # the app's cache and call log land in tmp_path/cache/llm
    app = AppTest.from_file(APP, default_timeout=120)
    app.run()
    _ok(app)
    return app


@pytest.fixture()
def at(tmp_path, monkeypatch):
    """The app, its fixtures recorded for ANA_TEXT (relations with world knowledge off and on)."""
    client = ScriptedClient(ANA_CLAIMS, entities=ANA_ENTITIES, wk_relations={(0, 2): ("contradicts", 0.7)})
    return _app(tmp_path, monkeypatch, client, lambda llm: rescored(
        llm, analyze_text(llm, ANA_TEXT, world_knowledge=False), True, label="recording"))


def test_consistency_mode_in_dry_run(at, tmp_path):
    assert any("dry-run" in i.value for i in at.sidebar.info)
    at.sidebar.radio(key="ui_mode").set_value("Consistency").run()
    _ok(at)
    assert at.sidebar.selectbox(key="llm_model").value == "claude-sonnet-5"
    assert at.sidebar.radio(key="llm_engine_version").value == "2.2"
    at.sidebar.radio(key="llm_engine_version").set_value("2.1").run()   # the fixtures are rev. 2.1's
    assert _button(at, "Analyze").disabled

    at.text_area(key="cs_text").input("A text nobody recorded.").run()
    _button(at, "Analyze").click().run()
    _ok(at)
    assert any("DryRunMissingFixture" in e.value for e in at.error) and at.session_state["cs_reports"] == []

    at.text_area(key="cs_text").input(f"\n{ANA_TEXT}\n").run()  # as an uploaded file would end
    _button(at, "Analyze").click().run()
    _ok(at)
    [first] = at.session_state["cs_reports"]
    assert first.report.verdict_clauses == ["entity"] and not first.world_knowledge
    assert any("Inconsistent" in e.value and "order cycle on age" in e.value for e in at.error)
    assert _button(at, "Re-analyze with this evidence").disabled
    assert [m.value for m in at.metric if m.label == "Clamped harmony"] == ["not measured"]

    _button(at, "Re-score with world knowledge on").click().run()
    _ok(at)
    reports = at.session_state["cs_reports"]
    assert [r.world_knowledge for r in reports] == [False, True] and reports[0] is first
    assert reports[1].report.verdict_clauses == ["direct", "entity"]
    assert at.selectbox(key="cs_view").value == 1
    assert at.session_state["llm"].usage["api_calls"] == 0

    log = (tmp_path / "cache" / "llm" / "log.jsonl").read_text("utf-8")
    assert "Ana is older" not in log and '"source": "fixture"' in log


def test_a_pair_scored_again_is_explained_under_the_relations(tmp_path, monkeypatch):
    client = ScriptedClient(ANA_CLAIMS, entities=ANA_ENTITIES,
                            answers={(0, 2): [("contradicts", 0.85, MALFORMED_RATIONALE), None]})
    at = _app(tmp_path, monkeypatch, client, lambda llm: analyze_text(llm, ANA_TEXT, world_knowledge=False))
    at.sidebar.radio(key="ui_mode").set_value("Consistency").run()
    at.sidebar.radio(key="llm_engine_version").set_value("2.1").run()
    at.text_area(key="cs_text").input(ANA_TEXT).run()
    _button(at, "Analyze").click().run()
    _ok(at)
    [report] = at.session_state["cs_reports"]
    assert report.diagnostics["pairs_unscored_malformed"] == [(0, 2)]
    assert any(c.value.startswith("Pair (0, 2): its first answer (contradicts, 0.85)")
               and "unscored (no edge)" in c.value for c in at.caption)


def test_rev22_is_the_default_and_both_versions_show_side_by_side(tmp_path, monkeypatch):
    """XON_A1_REV2_2_PRECISION.md §2 and §3.3: the view analyzes under 2.2 by default, lists tension pairs under the
    relations, and shows a 2.1 report of the same text next to it."""
    client = ScriptedClient(ANA_CLAIMS, entities=ANA_ENTITIES, entities_v22=ANA_ENTITIES_V22,
                            relations_v22={(0, 1): ("tension", 0.8)})

    def record(llm):
        for version in ("2.2", "2.1"):
            analyze_text(llm, ANA_TEXT, world_knowledge=False, engine_version=version)

    at = _app(tmp_path, monkeypatch, client, record)
    at.sidebar.radio(key="ui_mode").set_value("Consistency").run()
    at.text_area(key="cs_text").input(ANA_TEXT).run()
    _button(at, "Analyze").click().run()
    _ok(at)
    [first] = at.session_state["cs_reports"]
    assert first.engine_version == "2.2" and first.report.verdict_clauses == ["entity"]
    assert [(t["a"], t["b"]) for t in first.report.tension_pairs] == [(0, 1)] and first.report.n_edges == 0
    assert any(c.value.startswith("1 tension pair (amber)") for c in at.caption)

    _button(at, "Analyze with engine 2.1").click().run()
    _ok(at)
    reports = at.session_state["cs_reports"]
    assert [r.engine_version for r in reports] == ["2.2", "2.1"] and reports[0] is first
    assert at.selectbox(key="cs_view").value == 1 and at.selectbox(key="cs_compare").value == 0
    assert any("engine 2.2, threshold 0.5" in m.value for m in at.markdown)
    assert any("pairs scored in both reports have different labels" in c.value for c in at.caption)
    assert at.session_state["llm"].usage["api_calls"] == 0
