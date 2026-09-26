"""V1.2 CLI flags: --include-controls and --geometries, and the exported E9 report."""
import csv
import json

import pytest

from xon import run_tests
from xon.config import XonConfig
from xon.run_tests import main


def test_include_controls_puts_the_lattice_next_to_e1(tmp_path, capsys):
    code = main(["--out", str(tmp_path), "--experiments", "E1", "--include-controls", "--no-figures"])
    data = json.loads(next(tmp_path.glob("*/experiments.json")).read_text())
    assert [d["id"] for d in data] == ["E1", "E1_lattice"] and data[1]["role"] == "negative_control"
    assert code == 0  # a negative control never gates
    assert not list(tmp_path.glob("*/e9_report.csv"))


def test_geometries_flag_and_e9_report(tmp_path, capsys):
    main(["--out", str(tmp_path), "--experiments", "E9b", "--geometries", "gasket,tree", "--no-figures"])
    out = capsys.readouterr().out
    run_dir = next(tmp_path.glob("*"))
    rows = list(csv.DictReader((run_dir / "e9_report.csv").open(encoding="utf-8")))
    assert [r["Geometry"] for r in rows] == ["gasket", "tree"]
    assert all(r["Predicted vs observed"] == "E9b match" for r in rows)
    params = json.loads((run_dir / "params.json").read_text())
    assert params["config"]["e9_geometries"] == ["gasket", "tree"] and "E9d" in params["e9_report_header"]
    assert "E9 report" in out and "not implemented" in out


def test_unknown_geometry_is_rejected(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["--out", str(tmp_path), "--experiments", "E9b", "--geometries", "gasket,sponge"])
    assert "unknown geometries" in capsys.readouterr().err


def test_e9c_earlier_registrations_need_include_v1_and_are_reported_next_to_e9c(tmp_path, capsys, monkeypatch):
    for old in ("E9c_v1", "E9c_v2"):
        with pytest.raises(SystemExit):
            main(["--out", str(tmp_path), "--experiments", old])
        assert "--include-v1" in capsys.readouterr().err
    monkeypatch.setattr(run_tests, "XonConfig",
                        lambda seed=0: XonConfig(seed=seed).replace(e9c_max_n=1200, e9c_retry_max_n=5000))
    main(["--out", str(tmp_path), "--experiments", "e9c", "--include-v1", "--geometries", "gasket", "--no-figures"])
    out = capsys.readouterr().out
    data = json.loads(next(tmp_path.glob("*/experiments.json")).read_text())
    assert [d["id"] for d in data] == ["E9c", "E9c_v2", "E9c_v1"] and data[1]["role"] == data[2]["role"] == "v1"
    assert "V1.2 re-registrations vs their earlier registrations" in out and "E9c_v2:" in out and "E9c_v1:" in out
    row = next(csv.DictReader(next(tmp_path.glob("*/e9_report.csv")).open(encoding="utf-8")))
    assert row["N, E, D vs closed forms"] == "all equal, levels 0-7"
    assert {"d_w", "d_s", "Residual (theory d_f)", "d_f (box)", "d_f (mass, uniform)", "d_f (mass, deep)"} <= set(row)
