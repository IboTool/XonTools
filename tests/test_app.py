"""Headless smoke test of the Streamlit UI (streamlit.testing.v1.AppTest)."""
import json
from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

import xon.spectrum as spectrum_module  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _button(at, label):
    for b in list(at.sidebar.button) + list(at.main.button):
        if b.label == label:
            return b
    raise KeyError(label)


def _metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


def _ok(at):
    assert not at.exception, [e.message for e in at.exception]


@pytest.fixture()
def at(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # exports land in tmp_path/results
    app = AppTest.from_file(APP, default_timeout=180)
    app.run()
    _ok(app)
    return app


def test_sandbox_workflow(at, tmp_path, monkeypatch):
    assert [t.label for t in at.tabs] == ["Graph", "Spectrum", "Traces", "Depth", "Modes", "Sheaf",
                                          "Constraints", "Test Suite"]
    _button(at, "Grow to target").click().run()
    _ok(at)
    sb = at.session_state["sb"]
    assert sb.g.level == 5 and sb.g.n() == 366

    _button(at, "Step ×50").click().run()
    _ok(at)
    assert sb.s.step == 50

    built = []
    original = spectrum_module.Spectrum.__init__

    def counting_init(self, *a, **kw):
        built.append(1)
        original(self, *a, **kw)

    monkeypatch.setattr(spectrum_module.Spectrum, "__init__", counting_init)
    h_consonance = _metric(at, "Harmonicity")
    at.sidebar.selectbox(key="cfg_harmonicity_coherence").select("phase_order").run()
    _ok(at)
    assert _metric(at, "Harmonicity") != h_consonance
    assert built == []  # switching the coherence factor never recomputes the spectrum

    at.radio(key="ui_overlay").set_value("Eigenmode").run()
    _ok(at)
    at.radio(key="ui_overlay").set_value("Fiedler partition").run()
    _ok(at)

    _button(at, "Run").click().run()  # AppTest has no auto-rerun timer: the live fragment ticks once
    _ok(at)
    assert at.session_state["running"] and sb.s.step == 50 + sb.cfg.steps_per_frame
    _button(at, "Pause").click().run()
    _ok(at)
    assert not at.session_state["running"] and sb.s.step == 50 + sb.cfg.steps_per_frame

    at.sidebar.number_input(key="ui_probe_vertex").set_value(10)
    _button(at, "Probe").click().run()
    _ok(at)

    at.radio(key="sh_init").set_value("learned")
    _button(at, "Initialize sheaf").click().run()
    _ok(at)
    assert sb.sheaf is not None and "consistency" in sb.traces.last()
    _button(at, "Run inference test").click().run()
    _ok(at)
    assert sb.sheaf_log["inference"]["ratio"] < 0.25

    _button(at, "Export").click().run()
    _ok(at)
    run_dirs = list((tmp_path / "results").iterdir())
    assert len(run_dirs) == 1
    names = {p.name for p in run_dirs[0].iterdir()}
    assert {"params.json", "traces.csv", "spectrum.csv", "depth_energy.csv", "figures"} <= names


def _live_charts(at):
    return {c.key: c.proto for c in at.get("component_instance")}


def test_live_charts_keep_their_identity(at):
    _button(at, "Grow to target").click().run()
    _button(at, "Step ×50").click().run()
    _ok(at)
    charts = _live_charts(at)
    assert {"graph_live", "traces_live"} <= set(charts)
    assert all(p.component_name.endswith("live_chart") for p in charts.values())
    spec = json.loads(json.loads(charts["graph_live"].json_args)["spec"])
    assert spec["layout"]["uirevision"] == "gasket" and len(spec["layout"]["xaxis"]["range"]) == 2

    # the element id must not depend on the figure, or the browser remounts the chart on every frame
    _button(at, "Step ×50").click().run()
    _ok(at)
    after = _live_charts(at)
    assert after["graph_live"].json_args != charts["graph_live"].json_args
    assert after["graph_live"].id == charts["graph_live"].id

    at.session_state["graph_live"] = {"customdata": [7], "t": 1}  # what a click on vertex 7 sends
    at.run()
    _ok(at)
    assert at.session_state["ui_probe_vertex"] == 7


def test_structural_change_resets(at):
    _button(at, "Grow ×1").click().run()
    assert at.session_state["sb"].g.level == 1
    at.sidebar.selectbox(key="cfg_growth_rule").select("tree").run()
    _ok(at)
    sb = at.session_state["sb"]
    assert sb.g.rule == "tree" and sb.g.level == 0


def test_dropdowns_list_the_registries(at):
    from xon.config import DRIVES, OSC_DRIVES
    from xon.growth import RULES
    assert at.sidebar.selectbox(key="cfg_growth_rule").options == list(RULES)
    box = at.sidebar.selectbox(key="cfg_dynamics")
    assert box.options == ["wave", "wave_v1", "stuart_landau", "oscillator"]
    panels = {"wave": "cfg_beta", "wave_v1": "cfg_gamma1", "stuart_landau": "cfg_sl_mu", "oscillator": "cfg_osc_K"}
    for name, key in panels.items():
        at.sidebar.selectbox(key="cfg_dynamics").select(name).run()
        _ok(at)
        sb = at.session_state["sb"]
        assert sb.cfg.dynamics == name and sb.dyn.name == name
        keys = {w.key for w in at.sidebar.number_input}
        assert key in keys and not (set(panels.values()) - {key}) & keys
        drives = DRIVES if name.startswith("wave") else OSC_DRIVES
        assert at.sidebar.selectbox(key="cfg_drive").options == list(drives)
        _button(at, "Step ×50").click().run()
        _ok(at)
        assert sb.s.step == 50 and 0.0 <= float(_metric(at, "harmonicity_osc")) <= 1.0


def test_sink_bound_is_enforced_in_the_ui(at):
    _button(at, "Grow to target").click().run()
    at.sidebar.toggle(key="cfg_sink").set_value(True).run()
    _ok(at)
    sb = at.session_state["sb"]
    assert any("0.1·β·λ₂" in e.value for e in at.sidebar.error)
    _button(at, "Step ×50").click().run()
    _ok(at)
    assert sb.s.step == 0 and any("lambda_2" in e.value for e in at.error)
    at.sidebar.number_input(key="cfg_sink_gamma").set_value(1e-5).run()
    _button(at, "Step ×50").click().run()
    _ok(at)
    assert sb.s.step == 50 and sb.integrator() == "RK4"


def test_test_suite_mode(at):
    at.sidebar.radio(key="ui_mode").set_value("Test Suite").run()
    _ok(at)
    for eid in ("E2", "E3", "E4a", "E4b", "E4c", "E5", "E7", "E8", "E8b"):
        at.checkbox(key=f"ts_{eid}").uncheck()
    _button(at, "Run selected").click().run()
    _ok(at)
    res = at.session_state["exp_results"]
    assert set(res) == {"E1", "E6"}
    assert res["E1"].status == "passed" and res["E6"].status == "passed"

    at.toggle(key="ts_include_v1").set_value(True).run()
    _ok(at)
    for eid in ("E1", "E6", "E3_v1", "E4_v1", "E8_v1"):
        at.checkbox(key=f"ts_{eid}").uncheck()
    at.checkbox(key="ts_E2").check()
    _button(at, "Run selected").click().run()
    _ok(at)
    res = at.session_state["exp_results"]
    assert set(res) == {"E2", "E2_v1"} and res["E2_v1"].role == "v1"
    assert any("V1.1 vs the preserved V1" in m.value for m in at.markdown)


def test_constraints_demo_solves_maxcut(at):
    at.number_input(key="cp_n").set_value(12).run()
    _ok(at)
    _button(at, "Solve with OscillatorDynamics").click().run()
    _ok(at)
    res = at.session_state["cp_result"]
    assert res["key"][0] == 12 and len(res["energy"]) == at.session_state["cp_steps"]
    cut, optimum = _metric(at, "Cut found"), _metric(at, "Optimum (brute force)")
    assert 0 < int(cut) <= int(optimum)
