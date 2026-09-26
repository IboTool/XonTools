"""V1.2 in the Streamlit UI: the new geometries in every tab, Geometry Compare and E9 in the Test Suite."""
from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

from xon.experiments import default_ids  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _button(at, label):
    for b in list(at.sidebar.button) + list(at.main.button):
        if b.label == label:
            return b
    raise KeyError(label)


def _ok(at):
    assert not at.exception, [e.message for e in at.exception]


@pytest.fixture()
def at(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(APP, default_timeout=180)
    app.run()
    _ok(app)
    return app


@pytest.mark.parametrize("rule", ["carpet", "vicsek", "sierpinski_p"])
def test_new_geometries_work_in_every_tab(at, rule):
    at.sidebar.selectbox(key="cfg_growth_rule").select(rule).run()
    at.sidebar.number_input(key="cfg_target_level").set_value(2).run()
    _ok(at)
    _button(at, "Grow to target").click().run()
    _ok(at)
    sb = at.session_state["sb"]
    assert sb.g.rule == rule and sb.g.level == 2
    _button(at, "Step ×50").click().run()
    _ok(at)
    for overlay in ("Eigenmode", "Fiedler partition", "Depth", "State"):
        at.radio(key="ui_overlay").set_value(overlay).run()
        _ok(at)
    at.radio(key="sh_init").set_value("learned")
    _button(at, "Initialize sheaf").click().run()
    _ok(at)
    at.sidebar.number_input(key="cfg_target_level").set_value(3).run()
    _button(at, "Grow ×1").click().run()
    _ok(at)
    assert sb.g.level == 3 and sb.sheaf is not None and sb.sheaf.F_head.shape[0] == sb.g.n_edges()


def test_geometry_compare_mode(at):
    at.sidebar.radio(key="ui_mode").set_value("Geometry Compare").run()
    _ok(at)
    assert any("E9d" in c.value and "not implemented" in c.value for c in at.caption)
    at.multiselect(key="gc_geometries").set_value(["gasket", "sierpinski_p", "lattice"])
    at.number_input(key="gc_target_n").set_value(100)
    _button(at, "Compare").click().run()
    _ok(at)
    res, _ = at.session_state["gc_results"]
    assert set(res["rows"]) == {"E9a", "E9b", "E9c"} and res["names"] == ["gasket", "sierpinski_p", "lattice"]
    assert res["rows"]["E9b"]["lattice"] is None and res["rows"]["E9b"]["gasket"]["purity"] >= 0.85
    gasket = res["rows"]["E9c"]["gasket"]
    level = res["levels"]["gasket"]
    assert gasket["predicted"].startswith(f"N, E, D = closed forms at levels {level - 1}-{level}; d_w = 2.322")
    assert set(gasket["checks"]) == {"vertices", "edges", "diameter", "d_w", "d_s", "einstein_residual"}
    assert res["rows"]["E9c"]["lattice"]["matches"] is None and "structure" not in res["rows"]["E9c"]["lattice"]
    assert len(at.dataframe) == 3
    table = at.dataframe[2].value
    assert {"N, E, D vs closed forms", "Residual (theory d_f)", "d_f (box)", "d_f (mass, uniform)",
            "d_f (mass, deep)"} <= set(table.columns)
    assert table["N, E, D vs closed forms"].tolist()[:2] == [f"all equal, levels {res['levels'][n] - 1}-"
                                                             f"{res['levels'][n]}" for n in ("gasket", "sierpinski_p")]


def test_test_suite_runs_e9_and_shows_the_report(at):
    at.sidebar.radio(key="ui_mode").set_value("Test Suite").run()
    _ok(at)
    assert not any(at.checkbox(key=f"ts_{e}").value for e in ("E9a", "E1_lattice", "E9c_v1", "E9c_v2"))
    for eid in default_ids():
        at.checkbox(key=f"ts_{eid}").uncheck()
    at.checkbox(key="ts_E9b").check()
    at.multiselect(key="ts_geometries").set_value(["gasket", "tree"])
    _button(at, "Run selected").click().run()
    _ok(at)
    res = at.session_state["exp_results"]
    assert set(res) == {"E9b"} and res["E9b"].status == "passed"
    assert set(res["E9b"].metrics["rows"]) == {"gasket", "tree"}
    assert any("E9 report" in m.value for m in at.markdown)
