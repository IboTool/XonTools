"""The interactive Sandbox session behind the Streamlit UI.

Kept free of Streamlit so it can be unit-tested; the app stores one ``Sandbox`` in
``st.session_state`` and injects its ``st.cache_resource`` spectrum provider.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .config import XonConfig
from .dynamics import State, effective_dt, get_dynamics
from .export import export_run
from .growth import get_rule
from .metrics import ClusterTracker, depth_energy_array, modal_decomposition, spectral_clusters, trace_metrics
from .sheaf import CellularSheaf, sample_sections, state_to_stalks
from .spectrum import Spectrum, get_spectrum

# Settings that define the graph, the dynamics or the initial state: changing one requires a reset.
STRUCTURAL = ("seed", "growth_rule", "simplex_dim", "branch", "lattice_side", "sierpinski_p", "merge_tol", "init_amp",
              "dynamics")
# Settings behind the cluster traces: changing one restarts the cluster phase history.
CLUSTER_SETTINGS = ("n_clusters", "cluster_restarts", "cluster_window", "cluster_drift_max", "metrics_scope",
                    "frontier_window")
SHEAF_INITS = ("identity", "random", "learned")


def default_spectrum(g, cfg: XonConfig) -> Spectrum:
    return get_spectrum(g, cfg, cfg.k_modes)


class TraceLog:
    """Column-oriented per-step metric log, bounded to ``max_rows`` (oldest rows dropped first)."""

    def __init__(self, max_rows: int = 20_000):
        self.max_rows = int(max_rows)
        self.cols: dict[str, list] = {}
        self.n = 0
        self.dropped = 0

    def append(self, row: dict[str, Any]) -> None:
        for key in row.keys() - self.cols.keys():
            self.cols[key] = [np.nan] * self.n
        for key, col in self.cols.items():
            col.append(row.get(key, np.nan))
        self.n += 1
        if self.n > self.max_rows + max(1, self.max_rows // 10):  # trim in chunks: O(1) amortized
            cut = self.n - self.max_rows
            for col in self.cols.values():
                del col[:cut]
            self.n -= cut
            self.dropped += cut

    def __len__(self) -> int:
        return self.n

    def last(self) -> dict[str, Any]:
        return {k: v[-1] for k, v in self.cols.items()} if self.n else {}

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.cols)

    def rows(self) -> list[dict[str, Any]]:
        keys = list(self.cols)
        return [dict(zip(keys, vals)) for vals in zip(*self.cols.values())]


class Sandbox:
    """One graph + one state + growth, trace, spectrum and sheaf history."""

    def __init__(self, cfg: XonConfig | None = None,
                 spectrum_fn: Callable[[Any, XonConfig], Spectrum] | None = None,
                 max_trace: int = 20_000, max_history: int = 8):
        self.spectrum_fn = spectrum_fn or default_spectrum
        self.max_trace = int(max_trace)
        self.max_history = int(max_history)
        self.reset(cfg or XonConfig())

    # ------------------------------------------------------------------ lifecycle
    def reset(self, cfg: XonConfig) -> None:
        self.cfg = cfg
        self.rule = get_rule(cfg.growth_rule)
        self.g = self.rule.seed(cfg)
        self.rng = np.random.default_rng(cfg.seed)              # dynamics + growth
        self.aux_rng = np.random.default_rng([cfg.seed, 7])     # sheaf draws; never perturbs the dynamics stream
        self.dyn = get_dynamics(cfg.dynamics)
        if not getattr(self.dyn, "available", True):
            raise ValueError(f"dynamics {cfg.dynamics!r} is registered but not available yet")
        self.s = self.dyn.init_state(self.g, cfg, self.rng)
        self.traces = TraceLog(self.max_trace)
        self.growth_steps: list[int] = []
        self.spec_history: list[tuple[str, np.ndarray, int]] = []
        self.sheaf: CellularSheaf | None = None
        self.sheaf_frames: np.ndarray | None = None   # hidden flat ground truth a learned sheaf came from
        self.sheaf_log: dict[str, Any] = {}
        self._clear_average()
        self._new_tracker()
        self.record()

    def configure(self, cfg: XonConfig) -> bool:
        """Adopt new settings; returns True if a structural change forced a reset."""
        if any(getattr(cfg, f) != getattr(self.cfg, f) for f in STRUCTURAL):
            self.reset(cfg)
            return True
        restart_clusters = any(getattr(cfg, f) != getattr(self.cfg, f) for f in CLUSTER_SETTINGS)
        self.cfg = cfg
        if restart_clusters:
            self._new_tracker()
        return False

    def _new_tracker(self) -> None:
        cfg = self.cfg
        self.tracker = ClusterTracker(self.clusters(), cfg.cluster_window, cfg.cluster_drift_max, cfg.n_clusters)

    def _clear_average(self) -> None:
        self._acc = np.zeros(self.g.n())
        self.avg_steps = 0

    # ------------------------------------------------------------------ derived quantities
    @property
    def spec(self) -> Spectrum:
        return self.spectrum_fn(self.g, self.cfg)

    def dt(self) -> float:
        dt = getattr(self.dyn, "dt", None)
        return dt(self.g, self.cfg) if dt is not None else effective_dt(self.g, self.cfg)

    def clusters(self) -> np.ndarray:
        """3-way spectral clusters of the current graph (cached with its spectrum)."""
        cfg = self.cfg
        return spectral_clusters(self.spec, cfg.n_clusters, cfg.cluster_restarts, cfg.seed)

    def dynamics_blocker(self) -> str | None:
        """Why the dynamics refuses to run on this graph with these settings (e.g. the sink bound), or None."""
        check = getattr(self.dyn, "check", None)
        return check(self.g, self.cfg, self.spec) if check is not None else None

    def integrator(self) -> str:
        uses_modal = getattr(self.dyn, "uses_modal", None)
        if uses_modal is None:
            return self.dyn.name
        modal = uses_modal(self.g, self.cfg) and self.spec.method == "dense"
        return "modal (exact)" if modal else "RK4"

    def metrics_mask(self) -> np.ndarray | None:
        if self.cfg.metrics_scope == "frontier":
            return self.g.frontier_mask(self.cfg.frontier_window)
        return None

    def depth_energy(self, averaged: bool = False) -> np.ndarray:
        """E[d]; ``averaged`` uses the mean of |a|^2 over the steps since the last growth or reset."""
        if averaged and self.avg_steps:
            return np.bincount(self.g.depth, weights=self._acc / self.avg_steps,
                               minlength=self.g.max_depth() + 1)
        return depth_energy_array(self.g, self.s)

    # ------------------------------------------------------------------ actions
    def record(self) -> dict[str, Any]:
        row = {"step": self.s.step, "t": self.s.t, "level": self.g.level, "N": self.g.n()}
        mask = self.metrics_mask()
        row.update(trace_metrics(self.g, self.s, self.spec, self.cfg, mask))
        row.update(self.tracker.update(self.s, mask))
        if self.sheaf is not None:
            row["consistency"] = self.sheaf.consistency(self.g, state_to_stalks(self.s.a, self.sheaf.k))
        self.traces.append(row)
        return row

    def step(self, n: int = 1) -> None:
        """Advance n steps; raises ValueError (before stepping) if the dynamics refuses to run."""
        for _ in range(int(n)):
            why = self.dynamics_blocker()
            if why is not None:
                raise ValueError(why)
            self.s = self.dyn.step(self.g, self.s, self.cfg, self.rng, self.spec)
            self._acc += np.abs(self.s.a) ** 2
            self.avg_steps += 1
            self.record()
            every = int(self.cfg.auto_grow_every)
            if every > 0 and self.s.step % every == 0 and self.growth_blocker() is None:
                self.grow()

    def growth_blocker(self) -> str | None:
        cfg, g = self.cfg, self.g
        n_new = self.rule.predict_new_vertices(g, cfg)
        if n_new == 0:
            return f"the {cfg.growth_rule} rule does not grow"
        if g.level >= cfg.target_level:
            return f"target level {cfg.target_level} reached"
        if g.n() + n_new > cfg.max_vertices:
            return f"growing would exceed max vertices ({cfg.max_vertices:,})"
        return None

    def grow(self) -> tuple[bool, str]:
        why = self.growth_blocker()
        if why is not None:
            return False, f"Not grown: {why}."
        spec = self.spec
        self.spec_history.append((f"level {self.g.level} (N={self.g.n():,})", spec.lam.copy(), self.g.n()))
        del self.spec_history[:-self.max_history]
        self.g, self.s = self.rule.grow(self.g, self.s, self.cfg, self.rng)
        self.growth_steps.append(self.s.step)
        if self.sheaf is not None:
            # vertex ids only carry over if some vertex survived the step (vicsek replaces them all)
            survived = bool((self.g.depth < self.g.max_depth()).any())
            self.sheaf = self.sheaf.adapt(self.g) if survived else CellularSheaf.identity(self.g, self.sheaf.k)
        self._clear_average()
        self._new_tracker()
        self.record()
        return True, f"Grew to level {self.g.level}: N = {self.g.n():,}, E = {self.g.n_edges():,}."

    def grow_to_target(self) -> tuple[int, str]:
        grown, msg = 0, ""
        while self.growth_blocker() is None:
            _, msg = self.grow()
            grown += 1
        return grown, msg if grown else f"Not grown: {self.growth_blocker()}."

    def probe(self, vertex: int, amp: complex | None = None) -> None:
        v = int(vertex)
        if not 0 <= v < self.g.n():
            raise ValueError(f"vertex {v} outside 0..{self.g.n() - 1}")
        a = self.s.a.copy()
        a[v] += self.cfg.probe_amp if amp is None else amp
        self.s = State(a, self.s.t, self.s.step)
        self.record()

    # ------------------------------------------------------------------ sheaf (§6.1)
    def init_sheaf(self, k: int, kind: str) -> None:
        g, rng, cfg = self.g, self.aux_rng, self.cfg
        self.sheaf_frames = None
        self.sheaf_log = {"kind": kind, "k": int(k)}
        if kind == "identity":
            sheaf = CellularSheaf.identity(g, k)
        elif kind == "random":
            sheaf = CellularSheaf.random(g, k, rng)
        elif kind == "learned":
            _, frames = CellularSheaf.random_flat(g, k, rng)
            sheaf = CellularSheaf.identity(g, k)
            self.sheaf_log["learn"] = sheaf.learn(g, sample_sections(frames, rng, cfg.e5_examples),
                                                  cfg.e5_learn_eta, cfg.e5_learn_steps)
            self.sheaf_frames = frames
        else:
            raise ValueError(f"unknown sheaf initialization {kind!r}; choose from {SHEAF_INITS}")
        self.sheaf = sheaf
        self.record()

    def clear_sheaf(self) -> None:
        self.sheaf, self.sheaf_frames, self.sheaf_log = None, None, {}

    def stable_eta(self, eta: float, sheaf: CellularSheaf | None = None) -> float:
        lam = (sheaf or self.sheaf).lambda_max(self.g)
        return float(min(eta, 1.9 / lam)) if lam > 0 else float(eta)

    def sheaf_diffusion(self, eta: float, steps: int, start: str = "state") -> dict[str, Any]:
        if self.sheaf is None:
            raise RuntimeError("no active sheaf")
        g, k = self.g, self.sheaf.k
        x0 = state_to_stalks(self.s.a, k) if start == "state" else self.aux_rng.standard_normal(g.n() * k)
        eta_used = self.stable_eta(eta)
        _, trace = self.sheaf.diffuse(g, x0, eta_used, steps, record_every=max(1, int(steps) // 200))
        out = {"trace": trace, "eta": eta_used, "start": start}
        self.sheaf_log["diffusion"] = out
        return out

    def sheaf_inference(self, clamp_frac: float, eta: float, steps: int) -> dict[str, Any]:
        """Clamp a fraction of vertices to a ground-truth section, diffuse, report MSE on the rest."""
        if self.sheaf is None:
            raise RuntimeError("no active sheaf")
        g, k, rng = self.g, self.sheaf.k, self.aux_rng
        frames = self.sheaf_frames
        fresh = frames is None or frames.shape[:2] != (g.n(), k)
        if fresh:
            _, frames = CellularSheaf.random_flat(g, k, rng)
        x_true = sample_sections(frames, rng, 1)[0]
        n_clamp = int(np.clip(round(clamp_frac * g.n()), 1, max(g.n() - 1, 1)))
        clamp = np.zeros(g.n(), dtype=bool)
        clamp[rng.choice(g.n(), size=n_clamp, replace=False)] = True
        free = np.repeat(~clamp, k)
        identity = CellularSheaf.identity(g, k)

        def mse(sheaf: CellularSheaf) -> float:
            x = sheaf.diffuse(g, np.zeros(g.n() * k), self.stable_eta(eta, sheaf), steps, clamp, x_true)
            return float(np.mean((x[free] - x_true[free]) ** 2))

        m, m_id = mse(self.sheaf), mse(identity)
        out = {"mse": m, "mse_identity": m_id, "ratio": m / m_id if m_id > 0 else float("nan"),
               "clamped": n_clamp, "fresh_truth": fresh, "steps": int(steps)}
        self.sheaf_log["inference"] = out
        return out

    # ------------------------------------------------------------------ export
    def export(self, out: str | Path = "results", figures: dict | None = None,
               experiments: list | None = None) -> tuple[Path, dict]:
        spec = self.spec
        md = modal_decomposition(self.g, self.s, spec)
        extra = {
            "source": "sandbox",
            "graph": {"rule": self.g.rule, "level": self.g.level, "N": self.g.n(), "E": self.g.n_edges(),
                      "version": self.g.version},
            "state": {"dynamics": self.dyn.name, "step": self.s.step, "t": self.s.t,
                      "integrator": self.integrator(), "dt": self.dt()},
            "spectrum": {"method": spec.method, "k_used": spec.k_used, "captured": md.captured},
            "growth_steps": list(self.growth_steps),
            "trace_rows_dropped": self.traces.dropped,
            "sheaf": {k: v for k, v in self.sheaf_log.items() if k in ("kind", "k", "inference")},
        }
        return export_run(out, self.cfg, spec=spec, p=md.p, traces=self.traces.rows(),
                          growth_steps=self.growth_steps, depth_energy=self.depth_energy(),
                          experiments=experiments, figures=figures, extra=extra)
