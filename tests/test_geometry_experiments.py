"""V1.2 experiments: E1_lattice, E9a-E9c on small configurations, the E9 report and the suite order."""
import numpy as np
import pytest

from xon.config import XonConfig
from xon.experiments import (REGISTRY, REGISTRY_V1_2, V1_2_PAIRS, all_experiment_ids, default_ids, experiment_rng,
                             geometry_ids, preserved_v1_2_ids, run_experiment, suite_ids, v1_ids)
from xon.geometry import E9D_STATUS, band_level, e9_report, matched_level

SMALL = XonConfig().replace(e9_band=(50, 400))
LN = np.log
FIRST_E9C_CHECKS = {"d_f", "d_w", "d_s", "einstein_residual"}
E9C_CHECKS = {"vertices", "edges", "diameter", "d_w", "d_s", "einstein_residual"}
E9C_GASKET = XonConfig().replace(e9_geometries=("gasket",), e9c_max_n=1200, e9c_retry_max_n=5000)


def test_v1_2_registry_is_separate_and_e9d_is_not_registered():
    assert not set(REGISTRY_V1_2) & set(REGISTRY)
    assert set(REGISTRY_V1_2) == {"E1_lattice", "E9a", "E9b", "E9c", "E9c_v1", "E9c_v2"}
    assert not any(e.startswith("E9d") for e in all_experiment_ids())


def test_e9c_is_re_registered_and_its_earlier_registrations_are_preserved():
    new, second, first = REGISTRY_V1_2["E9c"], REGISTRY_V1_2["E9c_v2"], REGISTRY_V1_2["E9c_v1"]
    assert new.reregistered and new.role == "gate" and "exact" in new.name
    assert second.role == first.role == "v1" and second.reregistered and not first.reregistered
    assert V1_2_PAIRS == {"E9c": ("E9c_v2", "E9c_v1")} and preserved_v1_2_ids() == ["E9c_v1", "E9c_v2"]
    assert geometry_ids() == ["E9a", "E9b", "E9c"] and not {"E9c_v1", "E9c_v2"} & set(v1_ids())
    assert new.thresholds["exact"]["closed_forms"] == "docs/geometry_closed_forms.md"
    for name, tol in first.thresholds["tolerance"].items():
        assert set(tol) <= FIRST_E9C_CHECKS
        assert set(second.thresholds["tolerance"][name]) == set(tol) | {"d_f_box", "einstein_residual_box"}
        # E9c keeps the first registration's d_w, d_s and residual tolerances and references; d_f is exact now
        assert new.thresholds["tolerance"][name] == {k: t for k, t in tol.items() if k != "d_f"}
        assert new.thresholds["reference"].get(name, {}) == {k: v for k, v in first.thresholds["reference"][name].items()
                                                             if k != "d_f"}
        assert new.thresholds["d_f"][name] == first.thresholds["reference"][name]["d_f"]
    assert first.thresholds["reference"] == second.thresholds["reference"]


def test_e9c_earlier_registrations_share_its_stream():
    draw = lambda eid: experiment_rng(eid, 0).random()
    assert draw("E9c") == draw("E9c_v1") == draw("E9c_v2") != draw("E9b")


def test_suite_order():
    assert suite_ids() == default_ids() + ["E9a", "E9b", "E9c"]
    ids = suite_ids(include_controls=True)
    assert ids[ids.index("E1") + 1] == "E1_lattice" and ids.count("E1_lattice") == 1
    assert suite_ids(include_v1=True) == suite_ids() + v1_ids() + ["E9c_v1", "E9c_v2"]


def test_band_and_matched_levels():
    cfg = XonConfig()
    expected = {"gasket": 6, "vicsek": 4, "sierpinski_p": 4, "carpet": 3, "lattice": 3, "tree": 6}
    for name, level in expected.items():
        assert band_level(name, cfg, *cfg.e9_band) == (level, True), name
    assert matched_level("gasket", cfg, 1000) == 6 and matched_level("carpet", cfg, 1000) == 3


def test_e1_lattice_control():
    res = run_experiment("E1_lattice")
    assert res.status == "negative_control" and res.group == "E1"
    assert res.metrics["sides"] == [6, 11, 19]
    assert res.metrics["pearson_r_criterion_passes"] and not res.metrics["plateau_criterion_passes"]


def test_e9a_rows():
    res = run_experiment("E9a", SMALL.replace(e9_geometries=("gasket", "carpet", "lattice")))
    rows = res.metrics["rows"]
    assert list(rows) == ["gasket", "carpet", "lattice"] and all(r["in_band"] for r in rows.values())
    assert rows["gasket"]["plateau_containment"] == 1.0 and rows["gasket"]["degenerate_fraction"] > 0.5
    assert rows["carpet"]["matches"] and rows["lattice"]["matches"]
    assert res.passed == all(r["matches"] for r in rows.values()) and E9D_STATUS in res.notes


def test_e9b_rows_and_seam_relation():
    res = run_experiment("E9b", SMALL.replace(e9_geometries=("gasket", "vicsek", "carpet", "tree")))
    rows = res.metrics["rows"]
    assert {n: r["k"] for n, r in rows.items()} == {"gasket": 3, "vicsek": 5, "carpet": 8, "tree": 3}
    assert rows["carpet"]["matches"] is None
    assert all(rows[n]["matches"] for n in ("gasket", "vicsek", "tree")) and res.status == "passed"
    assert "seam_vs_purity" in res.figures and np.isfinite(res.metrics["seam_purity_spearman"])


def test_e9c_exact_counts_and_dimensions_on_the_gasket():
    res = run_experiment("E9c", E9C_GASKET)
    row = res.metrics["rows"]["gasket"]
    first = row.get("retried") or row
    assert first["level"] == 6 and set(row["checks"]) == E9C_CHECKS
    assert [s["level"] for s in row["structure"]] == list(range(8))  # N(7) = 3,282 <= 5,000 < N(8)
    assert all(row["checks"][k] for k in ("vertices", "edges", "diameter"))
    assert row["structure"][7]["diameter"] == 128 and row["structure"][7]["edges"] == 3 ** 8
    assert row["d_f_theory"] == LN(3) / LN(2)
    assert row["einstein_residual_theory"] == pytest.approx(abs(row["d_s"] - 2 * LN(3) / LN(2) / row["d_w"]))
    assert row["d_f_box"] == row["structure"][row["level"]]["ratio_vertices"]
    assert row["predicted"].startswith("N, E, D = closed forms at levels 0-7; d_w = 2.322 +- 0.1")
    assert set(res.figures) == {"ratio_sequence", "mass_radius", "msd", "return_probability"}
    assert "trend" not in res.metrics and "all equal, levels 0-7" in res.notes
    assert res.summary.startswith("gasket exact ok L0-7, dw")


def test_e9c_and_its_earlier_registrations_share_the_estimates():
    new, second, first = (run_experiment(e, E9C_GASKET) for e in ("E9c", "E9c_v2", "E9c_v1"))
    a, b, c = ((r.metrics["rows"]["gasket"].get("retried") or r.metrics["rows"]["gasket"])
               for r in (new, second, first))
    assert second.role == first.role == "v1"
    assert set(b["checks"]) == FIRST_E9C_CHECKS | {"d_f_box", "einstein_residual_box"}
    assert set(c["checks"]) == FIRST_E9C_CHECKS
    assert c["predicted"] == "d_f = 1.585 +- 0.1; d_w = 2.322 +- 0.1; d_s = 1.365 +- 0.1; residual <= 0.1"
    assert a["level"] == b["level"] == c["level"] == 6
    for key in ("d_f", "d_f_deep", "d_w", "d_s", "einstein_residual_deep"):
        assert a[key] == b[key] == c[key], key
    assert "judged by E9c_v1" in second.notes
    assert second.figures["mass_radius"].layout.title.text.startswith("E9c_v2: mass-radius M(r), uniform centers")
    assert first.figures["mass_radius"].layout.title.text.startswith("E9c_v1: mass-radius M(r), deep centers")
    assert first.summary.startswith(f"gasket df {c['d_f_deep']:.2f} dw")


def test_e9c_retries_a_miss_on_the_estimates_one_level_up():
    res = run_experiment("E9c", XonConfig().replace(e9_geometries=("gasket",), e9c_max_n=20, e9c_retry_max_n=100))
    row = res.metrics["rows"]["gasket"]
    assert row["retried"]["level"] == 2 and row["level"] == 3 and res.status == "failed"
    assert "structure" not in row["retried"] and [s["level"] for s in row["structure"]] == [0, 1, 2, 3]
    assert all(row["checks"][k] for k in ("vertices", "edges", "diameter"))
    assert "misses on" in res.notes and "at level 2 and again at level 3" in res.notes


def test_e9c_vicsek_trend():
    cfg = XonConfig().replace(e9_geometries=("vicsek",), e9c_max_n=300, e9c_retry_max_n=1300,
                              e9c_trend_from_level=3, e9c_trend_centers=20)
    res = run_experiment("E9c", cfg)
    row, trend = res.metrics["rows"]["vicsek"], res.metrics["trend"]
    assert [s["level"] for s in row["structure"]] == [0, 1, 2, 3, 4] and row["checks"]["diameter"]
    assert trend["geometry"] == "vicsek" and [t["level"] for t in trend["levels"]] == [3, 4]
    assert all(np.isfinite(t["d_f_deep"]) and np.isfinite(t["d_f_uniform"]) for t in trend["levels"])
    assert "trend" in res.figures and "mass-radius d_f by level" in res.notes


def test_e9_report_table():
    cfg = SMALL.replace(e9_geometries=("gasket", "lattice", "tree"))
    results = [run_experiment(e, cfg) for e in ("E9a", "E9b")]
    header, rows = e9_report(results, cfg)
    assert "E9d" in header and "not implemented" in header and "Dynamics module" in header
    assert [r["Geometry"] for r in rows] == ["gasket", "lattice", "tree"]
    assert "d_f (mass)" not in rows[0]  # E9c did not run
    by = {r["Geometry"]: r for r in rows}
    assert by["lattice"]["Purity"] == "-" and by["tree"]["Degenerate fraction"] == "-"
    assert by["tree"]["Predicted vs observed"] == "E9b match"
