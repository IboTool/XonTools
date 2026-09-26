import json
from types import SimpleNamespace

import pytest

import xon.experiments as experiments
from xon.config import XonConfig
from xon.experiments import (CRITERIA, EXPERIMENTS, NAMES, REGISTRY, THRESHOLDS, V1_PAIRS, ExperimentResult,
                             Registration, default_ids, experiment, experiment_rng, gate_verdicts, run_experiment,
                             v1_ids)
from xon.run_tests import exit_code, main

GATES = ["E1", "E2", "E3", "E4b", "E4c", "E5", "E6", "E7", "E8", "E8b"]


def test_registry_complete():
    ids = ["E1", "E2", "E3", "E4a", "E4b", "E4c", "E5", "E6", "E7", "E8", "E8b",
           "E2_v1", "E3_v1", "E4_v1", "E8_v1"]
    assert list(EXPERIMENTS) == list(REGISTRY) == ids
    assert set(NAMES) == set(CRITERIA) == set(THRESHOLDS) == set(ids)
    assert default_ids() == ids[:11] and v1_ids() == ids[11:]
    assert [e for e in ids if REGISTRY[e].role == "gate"] == GATES
    assert REGISTRY["E4a"].role == "negative_control"
    assert {REGISTRY[e].group for e in ("E4a", "E4b", "E4c")} == {"E4"}
    assert set(V1_PAIRS.values()) == set(v1_ids())
    for new in V1_PAIRS:
        regs = [r for e, r in REGISTRY.items() if (e == new or r.group == new) and r.role != "v1"]
        assert regs and all(r.reregistered for r in regs)
    for unchanged in ("E1", "E5", "E6", "E7"):
        assert not REGISTRY[unchanged].reregistered


def test_v1_variants_share_the_v1_stream_and_variants_get_their_own():
    draw = lambda eid: experiment_rng(eid, 0).random()
    assert draw("E2_v1") == draw("E2") and draw("E4_v1") == draw("E4") and draw("E8_v1") == draw("E8")
    assert len({draw("E4a"), draw("E4b"), draw("E4c"), draw("E4")}) == 4
    assert draw("E8b") != draw("E8")


def test_adding_an_experiment_is_one_registration_and_one_function(monkeypatch):
    with pytest.raises(KeyError, match="not pre-registered"):
        @experiment
        def E99(cfg, rng):
            raise AssertionError("never registered, never run")

    monkeypatch.setattr(experiments, "EXPERIMENTS", dict(EXPERIMENTS))
    monkeypatch.setitem(REGISTRY, "E9", Registration("Demo", "value >= 1", {"value_min": 1.0}))

    @experiment
    def E9(cfg, rng):
        value = 1.0
        return ExperimentResult("Demo", value >= REGISTRY["E9"].thresholds["value_min"], {"value": value}, "")

    res = run_experiment("E9")
    assert res.status == "passed" and res.criterion == "value >= 1" and res.thresholds == {"value_min": 1.0}
    assert res.role == "gate" and res.group == "E9"
    assert "E9" not in EXPERIMENTS


def test_e1_passes_and_e6_now_runs():
    e1 = run_experiment("E1", XonConfig())
    assert e1.status == "passed" and e1.id == "E1" and "staircase" in e1.figures
    e6 = run_experiment("E6", XonConfig())
    assert e6.metrics["optima"] == [54, 54, 54, 55, 52, 54, 53, 55, 56, 54]
    assert e6.status == "passed" and e6.metrics["seeds_ok"] >= 8 and "energy" in e6.figures


def test_experiment_errors_are_captured(monkeypatch):
    def boom(cfg, rng):
        raise RuntimeError("boom")
    monkeypatch.setitem(EXPERIMENTS, "E1", boom)
    res = run_experiment("E1", XonConfig())
    assert res.status == "error" and "boom" in res.notes


def test_negative_control_status_never_gates(monkeypatch):
    monkeypatch.setitem(EXPERIMENTS, "E4a", lambda cfg, rng: ExperimentResult("control", False, {}, ""))
    res = run_experiment("E4a", XonConfig())
    assert res.status == "negative_control" and res.passed is False and res.group == "E4"
    assert exit_code([res]) == 0


def test_exit_codes():
    r = lambda s, role="gate", group="": SimpleNamespace(status=s, role=role, group=group, id=group)
    assert exit_code([r("passed", group="E1"), r("not_implemented", group="E6")]) == 0
    assert exit_code([r("passed", group="E1"), r("failed", group="E2")]) == 1
    assert exit_code([r("failed", group="E1"), r("error", group="E2")]) == 2
    # E4 passes if E4b or E4c passes; E4a (negative control) and the V1 variants never gate
    e4 = [r("negative_control", "negative_control", "E4"), r("failed", group="E4"), r("passed", group="E4")]
    assert gate_verdicts(e4) == {"E4": "passed"} and exit_code(e4) == 0
    assert exit_code([r("failed", group="E4"), r("failed", group="E4")]) == 1
    assert exit_code([r("passed", group="E2"), r("failed", "v1", "E2")]) == 0
    assert exit_code([r("negative_control", "negative_control", "E4")]) == 0


def test_cli_writes_experiments_json(tmp_path):
    code = main(["--out", str(tmp_path), "--experiments", "E1,E6", "--no-figures"])
    assert code == 0
    files = list(tmp_path.glob("*/experiments.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert [d["id"] for d in data] == ["E1", "E6"]
    assert [d["status"] for d in data] == ["passed", "passed"] and data[1]["role"] == "gate"
    params = json.loads((files[0].parent / "params.json").read_text())
    assert params["seed"] == 0 and params["code_version"]["xon_version"]
    assert params["experiments_run"] == ["E1", "E6"] and params["gate_verdicts"] == {"E1": "passed", "E6": "passed"}


def test_cli_v1_variants_need_include_v1(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["--out", str(tmp_path), "--experiments", "E2_v1", "--no-figures"])
    assert "--include-v1" in capsys.readouterr().err
    main(["--out", str(tmp_path), "--experiments", "e2", "--include-v1", "--no-figures"])
    out = capsys.readouterr().out
    data = json.loads(next(tmp_path.glob("*/experiments.json")).read_text())
    assert [d["id"] for d in data] == ["E2", "E2_v1"] and data[1]["role"] == "v1"
    assert "V1.1" in out and "E2_v1:" in out
