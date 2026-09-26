import json

import numpy as np
import pytest

from xon.config import XonConfig
from xon.dynamics import DYNAMICS, State
from xon.metrics import METRICS, Metric
from xon.sandbox import Sandbox, TraceLog

CFG = XonConfig()


def test_tracelog_is_bounded_and_columnar():
    tl = TraceLog(max_rows=100)
    for i in range(1000):
        row = {"step": i, "x": float(i)}
        if i >= 500:
            row["late"] = 1.0
        tl.append(row)
    assert 100 <= len(tl) <= 110 and tl.dropped == 1000 - len(tl)
    assert list(tl.frame()["step"]) == list(range(1000 - len(tl), 1000))
    assert tl.rows()[-1] == {"step": 999, "x": 999.0, "late": 1.0}
    assert tl.last()["step"] == 999


def test_grow_step_probe_and_spectrum_history():
    sb = Sandbox(CFG.replace(target_level=3))
    assert sb.g.n() == 3 and len(sb.traces) == 1
    n, _ = sb.grow_to_target()
    assert n == 3 and sb.g.level == 3 and sb.g.n() == (3 ** 4 + 3) // 2
    assert len(sb.spec_history) == 3 and len(sb.growth_steps) == 3
    ok, msg = sb.grow()
    assert not ok and "target level" in msg
    sb.step(20)
    assert sb.s.step == 20 and sb.traces.last()["step"] == 20
    before = sb.s.a[5]
    sb.probe(5, amp=2.0)
    assert sb.s.a[5] == pytest.approx(before + 2.0)
    with pytest.raises(ValueError):
        sb.probe(sb.g.n())


def test_growth_limits():
    sb = Sandbox(CFG.replace(target_level=9, max_vertices=50))
    sb.grow_to_target()
    assert sb.g.n() <= 50 and "max vertices" in sb.growth_blocker()
    lat = Sandbox(CFG.replace(growth_rule="lattice", lattice_side=5))
    assert not lat.grow()[0] and lat.g.n() == 25


def test_auto_grow_while_stepping():
    sb = Sandbox(CFG.replace(target_level=2, auto_grow_every=10))
    sb.step(35)
    assert sb.g.level == 2 and sb.growth_steps == [10, 20]


def test_registered_dynamics_and_trace_metric_reach_the_sandbox(monkeypatch):
    class Frozen:
        """Minimal Dynamics: the state never changes."""
        name, available = "frozen", True

        def init_state(self, g, cfg, rng):
            return State(np.ones(g.n(), complex))

        def step(self, g, s, cfg, rng, spec=None):
            return State(s.a, s.t + cfg.dt, s.step + 1)

        def energy(self, g, s):
            return float(np.sum(np.abs(s.a) ** 2))

    monkeypatch.setitem(DYNAMICS, "frozen", Frozen)
    monkeypatch.setitem(METRICS, "max_amplitude", Metric(
        "max_amplitude", lambda g, s, spec, cfg=None, mask=None: float(np.abs(s.a).max()),
        "state", "largest |a_i|", trace=True))
    sb = Sandbox(CFG.replace(dynamics="frozen"))
    sb.step(3)
    assert sb.integrator() == "frozen" and sb.s.step == 3
    assert sb.traces.frame()["max_amplitude"].tolist() == [1.0] * 4

    class Unfinished(Frozen):
        name, available = "unfinished", False

    monkeypatch.setitem(DYNAMICS, "unfinished", Unfinished)
    with pytest.raises(ValueError, match="not available"):
        Sandbox(CFG.replace(dynamics="unfinished"))


@pytest.mark.parametrize("name", list(DYNAMICS))
def test_every_dynamics_runs_in_the_sandbox_with_cluster_traces(name):
    sb = Sandbox(CFG.replace(dynamics=name, target_level=3))
    sb.grow_to_target()
    sb.step(25)
    assert sb.dyn.name == name and sb.s.step == 25 and np.all(np.isfinite(sb.s.a))
    last = sb.traces.last()
    for key in ("cluster_order", "n_clusters_eff", "harmonicity_osc", "low_subspace_fraction"):
        assert np.isfinite(last[key])
    assert 1 <= last["n_clusters_eff"] <= sb.cfg.n_clusters
    assert sorted(np.unique(sb.clusters())) == list(range(sb.cfg.n_clusters))


def test_sink_above_the_bound_blocks_stepping():
    sb = Sandbox(CFG.replace(target_level=4, sink=True, sink_gamma=0.01))
    sb.grow_to_target()
    assert "0.1 * beta * lambda_2" in sb.dynamics_blocker()
    with pytest.raises(ValueError, match="lambda_2"):
        sb.step(1)
    assert sb.s.step == 0
    bound = 0.1 * sb.cfg.beta * sb.spec.lam[1]
    assert not sb.configure(sb.cfg.replace(sink_gamma=bound))
    assert sb.dynamics_blocker() is None
    sb.step(5)
    assert sb.s.step == 5 and sb.integrator() == "RK4"


def test_configure_resets_only_on_structural_change():
    sb = Sandbox(CFG.replace(target_level=2))
    sb.grow_to_target()
    sb.step(5)
    assert not sb.configure(sb.cfg.replace(gamma1=0.0, harmonicity_coherence="phase_order"))
    assert sb.g.level == 2 and sb.s.step == 5 and sb.cfg.gamma1 == 0.0
    assert sb.configure(sb.cfg.replace(growth_rule="tree"))
    assert sb.g.rule == "tree" and sb.s.step == 0


def test_same_seed_same_trajectory():
    runs = []
    for _ in range(2):
        sb = Sandbox(CFG.replace(target_level=2))
        sb.grow_to_target()
        sb.step(30)
        runs.append(sb.s.a)
    np.testing.assert_array_equal(*runs)


def test_frontier_scope_and_time_averaged_depth_energy():
    sb = Sandbox(CFG.replace(target_level=3, metrics_scope="frontier"))
    sb.grow_to_target()
    sb.step(10)
    assert sb.avg_steps == 10
    assert sb.depth_energy(True).shape == sb.depth_energy(False).shape == (4,)
    full = Sandbox(CFG.replace(target_level=3))
    full.grow_to_target()
    full.step(10)
    assert sb.traces.last()["energy"] == pytest.approx(full.traces.last()["energy"])
    assert sb.traces.last()["n_eff"] != pytest.approx(full.traces.last()["n_eff"])


def test_sheaf_lifecycle():
    sb = Sandbox(CFG.replace(target_level=3))
    sb.grow_to_target()
    sb.init_sheaf(2, "learned")
    assert "consistency" in sb.traces.last()
    r = sb.sheaf_inference(0.3, 0.2, 2000)
    assert not r["fresh_truth"] and r["ratio"] < 0.25
    cons = [c for _, c in sb.sheaf_diffusion(0.2, 200, start="state")["trace"]]
    assert cons[-1] <= cons[0]
    sb.cfg = sb.cfg.replace(target_level=4)
    assert sb.grow()[0]
    assert sb.sheaf.F_head.shape[0] == sb.g.n_edges()
    assert sb.sheaf_inference(0.3, 0.2, 200)["fresh_truth"]
    sb.clear_sheaf()
    sb.step(1)
    assert np.isnan(sb.traces.last()["consistency"])


def test_sheaf_eta_is_clipped_for_stability():
    sb = Sandbox(CFG.replace(growth_rule="simplex", simplex_dim=4, target_level=1))
    sb.grow_to_target()
    sb.init_sheaf(1, "identity")
    lam = sb.sheaf.lambda_max(sb.g)
    assert sb.stable_eta(10.0) == pytest.approx(1.9 / lam)
    trace = sb.sheaf_diffusion(10.0, 300, start="random")["trace"]
    assert np.isfinite(trace[-1][1]) and trace[-1][1] < trace[0][1]


def test_export_writes_run_folder(tmp_path):
    sb = Sandbox(CFG.replace(target_level=2, seed=3))
    sb.grow_to_target()
    sb.step(10)
    run_dir, _ = sb.export(tmp_path)
    names = {p.name for p in run_dir.iterdir()}
    assert {"params.json", "traces.csv", "spectrum.csv", "depth_energy.csv"} <= names
    assert run_dir.name.endswith("_3")
    params = json.loads((run_dir / "params.json").read_text())
    assert params["seed"] == 3 and params["config"]["seed"] == 3
    assert params["code_version"]["xon_version"] and params["graph"]["level"] == 2
    assert params["growth_steps"] == sb.growth_steps
