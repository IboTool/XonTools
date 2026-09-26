"""Pre-registered experiments (§5, re-registered where noted in V1.1 §4).

Each experiment is ``E#(cfg, rng) -> ExperimentResult``. Its name, pass criterion and thresholds are
fixed in REGISTRY below, before the first run. If a threshold turns out to be unreasonable, change it
there with a comment explaining why; never tune silently. An experiment whose protocol changes is
re-registered under its id with the reason (``reregistered``; details in CHANGELOG_EXPERIMENTS.md),
and the old protocol stays runnable as ``E#_v1``. Protocol parameters (levels, T, G, seeds) come from
the config so they are exported with every run. Adding an experiment = one REGISTRY entry + one
function named after its id and decorated with ``@experiment``.

Roles: "gate" experiments decide the exit code, and gates sharing a ``group`` pass when any member
passes (E4 = E4b or E4c); "negative_control" and "v1" experiments are reported only.
"""
from __future__ import annotations

import re
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy import stats

from .config import COHERENCE_FACTORS, XonConfig
from .dynamics import (CompleteCoupling, OscillatorDynamics, StuartLandauDynamics, WaveDynamics,
                       WaveDynamicsV1, damping_profile)
from .geometry import (E9D_STATUS, attach_structure, band_level, cluster_overlay, clustering_row, dimension_figures,
                       dimension_row, exact_summary, geometry_label, geometry_rng, mass_trend, max_level,
                       ratio_figure, seam_purity_figure, spectral_row, staircase, strip_curves, structure_rows,
                       trend_figure)
from .growth import build_graph, get_rule
from .metrics import (ClusterTracker, cluster_purity, depth_energy_array, einstein_residual, fit_exponential,
                      fit_powerlaw, frac_localized, fundamental_fraction, low_eigenspace, modal_decomposition,
                      multiplicity_at, partition_purity, purity_of_partition, spectral_clusters,
                      spectral_dimension_est, spectral_gap_ratio, spectral_k_gap, trace_metrics)
from .plots import depth_energy_figure, graph_figure, staircase_figure
from .problems import MaxCutProblem, oscillator_solve
from .sheaf import CellularSheaf, sample_sections
from .spectrum import get_spectrum


# ---------------------------------------------------------------------------- pre-registration
@dataclass(frozen=True)
class Registration:
    name: str
    criterion: str
    thresholds: dict[str, Any]
    role: str = "gate"          # gate | negative_control | v1
    group: str = ""             # gates in one group pass together when any member passes
    reregistered: str = ""      # V1.1: why the protocol changed


_E4_V1_CRITERION = ("Frontier harmonicity end-mean > start-mean, one-sided paired t-test p < 0.05 across seeds, "
                    "AND increase >= 2x the increase of the uniform-damping control (gamma1 = 0).")

REGISTRY: dict[str, Registration] = {
    "E1": Registration(
        "Spectral self-similarity",
        "Pearson r between consecutive levels >= 0.95; plateaus at lambda in {3, 5, 6} with "
        "multiplicity > 5% of N at every level (gasket levels 3, 4, 5).",
        {"pearson_r_min": 0.95, "plateaus": (3.0, 5.0, 6.0), "plateau_frac_min": 0.05}),
    "E2": Registration(
        "Individuation from structure (3-way spectral clustering)",
        "Gasket level 5: k-means (k = 3, 20 seeded restarts) on the rows of the low eigenspace (the constant and "
        "every eigenvector with lambda <= lambda_2 (1 + 1e-6)); purity of the best one-to-one matching of the "
        "clusters to the three sub-gaskets >= 0.9; frac_localized >= 0.25; lattice control frac_localized < 0.05.",
        {"purity3_min": 0.9, "frac_localized_min": 0.25, "lattice_frac_localized_max": 0.05},
        reregistered="degenerate lambda_2: the single Fiedler vector is not unique on the gasket"),
    "E3": Registration(
        "Power-law memory (retention of energy injected at a layer's birth)",
        "Wave (alpha = 0.005, beta = 0.05, no sink, no drive); gasket grown from level 3 to level 7 with G = 200 "
        "steps between growths; unit energy injected on each newly born layer; R(k) = energy remaining on that "
        "layer's vertices k growth steps later, averaged over layers, with the known factor exp(-2 alpha k G dt) "
        "divided out. Over k = 1..4: gasket R2_powerlaw > R2_exponential AND tree (branch 3) R2_exponential >= "
        "R2_powerlaw. Lattice control (no growth, elapsed time in units of G) is reported.",
        {"gasket": "R2_powerlaw > R2_exponential over k = 1..4",
         "tree": "R2_exponential >= R2_powerlaw over k = 1..4", "k_max": 4},
        reregistered="the V1 depth profile mostly reflected the imposed gamma(depth); the claim is about time of birth"),
    "E4a": Registration(
        "Harmonicity under drive-and-sink: linear wave (negative control)",
        "V1 E4 criteria on the V1.1 wave: frontier harmonicity end-mean > start-mean (one-sided paired t-test "
        "p < 0.05) AND increase >= 2x that of the no-sink control; sink = Gamma_sink at the maximum allowed "
        "gamma_s. Expected to fail; never affects the exit code.",
        {"p_max": 0.05, "control_ratio_min": 2.0},
        role="negative_control", group="E4",
        reregistered="linear dynamics cannot select coherence; kept so the negative result stays on the record"),
    "E4b": Registration(
        "Harmonicity rises: Stuart-Landau (headline)",
        "Gasket grown from level 2 to level 5 (G = 500 steps per level); stuart_landau with omega by depth and "
        "noise sigma = 0.05 at the frontier; 5 seeds; harmonicity_osc at the frontier with the 3-way spectral "
        "clusters recomputed after each growth. Pass: end - start > 0 with one-sided paired t-test p < 0.05; "
        "AND gasket end > complete-graph (same N) end with p < 0.05; AND the mu = 0 control shows no significant "
        "rise. A pass on E4b or E4c passes E4.",
        {"p_max": 0.05},
        group="E4", reregistered="linear dynamics cannot select coherence; nonlinearity required"),
    "E4c": Registration(
        "Harmonicity rises: Kuramoto",
        "Same protocol and criteria as E4b with the oscillator dynamics (K = 1, omega by depth); the null "
        "control is K = 0 (uncoupled phases) in place of mu = 0. A pass on E4b or E4c passes E4.",
        {"p_max": 0.05},
        group="E4", reregistered="linear dynamics cannot select coherence; nonlinearity required"),
    "E5": Registration(
        "Sheaf inference",
        "Recovery MSE on unclamped vertices < 25% of the identity-map baseline MSE.",
        {"mse_ratio_max": 0.25}),
    "E6": Registration(
        "Constraint solving by dissonance minimization",
        "Cut value >= 90% of optimum in >= 8/10 seeds (OscillatorDynamics, implemented in V1.1).",
        {"ratio_min": 0.9, "seeds_ok_min": 8}),
    "E7": Registration(
        "Spectral dimension vs simplex dimension",
        "|d_s estimate - 2 ln(n+1)/ln(n+3)| <= 0.08 for n = 2, 3, 4.",
        {"tol": 0.08}),
    "E8": Registration(
        "The peace trap (individuation before global rest)",
        "Wave (V1.1), no sink, gasket level 5. Phase 1 without drive for the predicted global-collapse time "
        "1/(2 beta lambda_2); phase 2 with noise drive at the frontier. Pass: low_subspace_fraction (modes "
        "k <= k_gap, the first spectral gap; 3 on the gasket) >= 0.9 at the end of phase 1 AND <= 0.5 throughout "
        "the second half of phase 2.",
        {"low_subspace_min": 0.9, "driven_low_subspace_max": 0.5},
        reregistered="non-commuting damping; individuation means peace per node precedes global peace"),
    "E8b": Registration(
        "The peace trap with the weak depth sink",
        "E8 with Gamma_sink on at the maximum allowed gamma_s = 0.1 beta lambda_2; identical criteria.",
        {"low_subspace_min": 0.9, "driven_low_subspace_max": 0.5},
        reregistered="verifies the weak sink does not break the collapse"),
    # ---- V1 protocols, kept runnable for comparison (run_tests --include-v1) ----
    "E2_v1": Registration(
        "Individuation from structure (V1)",
        "Gasket level 5: partition_purity >= 0.9 and frac_localized >= 0.25; lattice control "
        "frac_localized < 0.05.",
        {"purity_min": 0.9, "frac_localized_min": 0.25, "lattice_frac_localized_max": 0.05}, role="v1"),
    "E3_v1": Registration(
        "Power-law memory (V1)",
        "Gasket level 6 under noise drive: R2_powerlaw > R2_exponential for E[d]. Tree control is "
        "expected to show R2_exponential >= R2_powerlaw (reported, not a failure).",
        {"gasket": "R2_powerlaw > R2_exponential",
         "tree (expectation, not a failure)": "R2_exponential >= R2_powerlaw"}, role="v1"),
    "E4_v1": Registration(
        "Harmonicity rises under drive-and-sink (V1)", _E4_V1_CRITERION,
        {"p_max": 0.05, "control_ratio_min": 2.0}, role="v1"),
    "E8_v1": Registration(
        "The peace trap (V1)",
        "No drive: fundamental_fraction >= 0.9 at the end. With noise drive: stays <= 0.5.",
        {"no_drive_fundamental_min": 0.9, "driven_fundamental_max": 0.5}, role="v1"),
}

NAMES = {eid: r.name for eid, r in REGISTRY.items()}
CRITERIA = {eid: r.criterion for eid, r in REGISTRY.items()}
THRESHOLDS = {eid: r.thresholds for eid, r in REGISTRY.items()}
V1_PAIRS = {"E2": "E2_v1", "E3": "E3_v1", "E4": "E4_v1", "E8": "E8_v1"}     # new id or group -> preserved V1 id

EXPERIMENTS: dict[str, Callable[[XonConfig, np.random.Generator], ExperimentResult]] = {}


def experiment(fn):
    """Register ``fn`` under its function name, which must already have a REGISTRY entry."""
    eid = fn.__name__
    if eid not in REGISTRY:
        raise KeyError(f"{eid} is not pre-registered: add its name, criterion and thresholds to REGISTRY")
    EXPERIMENTS[eid] = fn
    return fn


def default_ids() -> list[str]:
    """Experiments run by default: everything registered except the V1 variants."""
    return [eid for eid in EXPERIMENTS if REGISTRY.get(eid) is None or REGISTRY[eid].role != "v1"]


def v1_ids() -> list[str]:
    return [eid for eid in EXPERIMENTS if REGISTRY.get(eid) is not None and REGISTRY[eid].role == "v1"]


@dataclass
class ExperimentResult:
    name: str
    passed: bool | None
    metrics: dict
    notes: str
    figures: dict[str, go.Figure] = field(default_factory=dict)
    id: str = ""
    status: str = ""          # passed | failed | not_implemented | error | negative_control
    summary: str = ""         # key numbers for tables
    criterion: str = ""
    thresholds: dict = field(default_factory=dict)
    runtime_s: float = 0.0
    role: str = "gate"
    group: str = ""

    def __post_init__(self) -> None:
        if not self.status:
            self.status = "passed" if self.passed else ("failed" if self.passed is False else "not_implemented")

    def to_json(self) -> dict:
        return {
            "id": self.id, "name": self.name, "status": self.status, "passed": self.passed,
            "role": self.role, "group": self.group,
            "summary": self.summary, "criterion": self.criterion, "thresholds": self.thresholds,
            "metrics": self.metrics, "notes": self.notes, "runtime_s": round(self.runtime_s, 3),
            "figures": sorted(self.figures),
        }


def gate_verdicts(results) -> dict[str, str]:
    """Verdict per gate group: "passed" if any member passed, "failed" if members ran and none passed.

    Negative controls, V1 variants, errors and not_implemented results do not count.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for r in results:
        if getattr(r, "role", "gate") != "gate" or r.status not in ("passed", "failed"):
            continue
        key = getattr(r, "group", "") or getattr(r, "id", "") or str(id(r))
        groups[key].append(r.status)
    return {k: ("passed" if "passed" in v else "failed") for k, v in groups.items()}


def _gasket(cfg: XonConfig, level: int):
    return build_graph(cfg, level, "gasket")


def _paired_greater(a, b) -> float:
    """One-sided paired t-test p-value for mean(a - b) > 0; nan when undefined (e.g. no variance)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 2 or not np.any(a - b):
        return float("nan")
    with np.errstate(all="ignore"):
        return float(stats.ttest_rel(a, b, alternative="greater").pvalue)


def _fit(x: np.ndarray, y: np.ndarray, log_x: bool) -> dict:
    """R^2 of log y against log x (power law) or x (exponential)."""
    ok = y > 0
    if ok.sum() < 3:
        return {"r2": float("nan"), "slope": float("nan"), "intercept": float("nan")}
    xx = np.log(x[ok]) if log_x else x[ok]
    res = stats.linregress(xx, np.log(y[ok]))
    return {"r2": float(res.rvalue ** 2), "slope": float(res.slope), "intercept": float(res.intercept)}


def _downsample_idx(n: int, points: int = 600, log: bool = False) -> np.ndarray:
    if n <= points:
        return np.arange(n)
    if log:
        return np.unique(np.geomspace(1, n, points).astype(int) - 1)
    return np.unique(np.linspace(0, n - 1, points).astype(int))


# ---------------------------------------------------------------------------- E1
@experiment
def E1(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    th = THRESHOLDS["E1"]
    levels = list(cfg.e1_levels)
    grid = (np.arange(cfg.e1_resample) + 0.5) / cfg.e1_resample
    resampled, curves, plateau, sizes = {}, [], {}, {}
    for level in levels:
        g = _gasket(cfg, level)
        spec = get_spectrum(g, cfg)
        n = g.n()
        resampled[level] = np.interp(grid, np.arange(n) / n, spec.lam)
        curves.append((f"level {level} (N={n})", spec.lam))
        plateau[level] = {str(v): multiplicity_at(spec, v) / n for v in th["plateaus"]}
        sizes[level] = n
    rs = {f"{a}-{b}": float(stats.pearsonr(resampled[a], resampled[b])[0]) for a, b in zip(levels, levels[1:])}
    ok_r = all(r >= th["pearson_r_min"] for r in rs.values())
    ok_p = all(f > th["plateau_frac_min"] for lv in plateau.values() for f in lv.values())
    passed = ok_r and ok_p
    min_frac = min(f for lv in plateau.values() for f in lv.values())
    return ExperimentResult(
        NAMES["E1"], passed,
        {"pearson_r": rs, "plateau_fraction": plateau, "n": sizes},
        f"Pearson r {'ok' if ok_r else 'BELOW threshold'}; plateaus {'present' if ok_p else 'MISSING'} "
        f"(smallest plateau fraction {min_frac:.3f}).",
        {"staircase": staircase_figure(curves, "E1: sorted eigenvalues vs index/N")},
        summary=f"r = {', '.join(f'{r:.4f}' for r in rs.values())}; min plateau frac {min_frac:.3f}",
    )


# ---------------------------------------------------------------------------- E2
def fiedler_eigenspace_purity(g, spec, n_dirs: int = 720) -> dict:
    """Purity over every direction of the lambda_2 eigenspace (it is degenerate on symmetric graphs)."""
    grp = next((ab for ab in spec.groups if ab[0] == 1), (1, 2))
    block = spec.phi[:, grp[0]:grp[1]]
    m = block.shape[1]
    if m == 1:
        dirs = np.ones((1, 1))
    elif m == 2:
        th = np.linspace(0, np.pi, n_dirs, endpoint=False)
        dirs = np.stack([np.cos(th), np.sin(th)])
    else:
        dirs = np.random.default_rng(0).standard_normal((m, n_dirs))
    labels = g.labels["subgasket"]
    pur = np.array([purity_of_partition(block @ dirs[:, i] >= 0, labels) for i in range(dirs.shape[1])])
    return {"multiplicity": m, "min": float(pur.min()), "mean": float(pur.mean()), "max": float(pur.max())}


def _ipr_figure(cfg, g, spec, gl, spec_l, title: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=spec.lam, y=spec.ipr, mode="markers", name=f"gasket L{cfg.e2_level}"))
    fig.add_trace(go.Scatter(x=spec_l.lam, y=spec_l.ipr, mode="markers", name="lattice"))
    fig.add_hline(y=cfg.ipr_factor / g.n(), line=dict(dash="dash"), annotation_text="5/N gasket")
    fig.add_hline(y=cfg.ipr_factor / gl.n(), line=dict(dash="dot"), annotation_text="5/N lattice")
    fig.update_layout(title=title, xaxis_title="lambda", yaxis_title="IPR", yaxis_type="log", height=420)
    return fig


@experiment
def E2(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    th = THRESHOLDS["E2"]
    g = _gasket(cfg, cfg.e2_level)
    spec = get_spectrum(g, cfg)
    clusters = spectral_clusters(spec, cfg.n_clusters, cfg.cluster_restarts, cfg.seed)
    purity3 = cluster_purity(clusters, g.labels["subgasket"])
    m_low = low_eigenspace(spec).shape[1]
    fl = frac_localized(g, None, spec, cfg)
    gl = build_graph(cfg, 0, "lattice")
    spec_l = get_spectrum(gl, cfg)
    fl_l = frac_localized(gl, None, spec_l, cfg)
    purity_v1 = partition_purity(g, None, spec, cfg)
    eig = fiedler_eigenspace_purity(g, spec)
    checks = {"purity3": purity3 >= th["purity3_min"], "frac_localized": fl >= th["frac_localized_min"],
              "lattice_frac_localized": fl_l < th["lattice_frac_localized_max"]}
    passed = all(checks.values())
    sizes = np.bincount(clusters).tolist()
    notes = (f"Low eigenspace = {m_low} vectors (constant + lambda_2 with multiplicity {eig['multiplicity']}); "
             f"k-means with k = {cfg.n_clusters}, {cfg.cluster_restarts} k-means++ restarts seeded with {cfg.seed}; "
             f"cluster sizes {sizes}. Purity = best one-to-one matching of clusters to sub-gasket labels over the "
             f"labelled vertices. V1 numbers: single-vector Fiedler purity {purity_v1:.3f}; purity over all "
             f"directions of the lambda_2 eigenspace {eig['min']:.3f}-{eig['max']:.3f} (mean {eig['mean']:.3f}). "
             f"Failed checks: {[k for k, v in checks.items() if not v] or 'none'}.")
    fig_g = graph_figure(g, clusters, mode="clusters", title="E2: 3-way spectral clusters (gasket)",
                         colorbar_title="cluster")
    return ExperimentResult(
        NAMES["E2"], passed,
        {"purity3": purity3, "cluster_sizes": sizes, "low_eigenspace_dim": m_low, "frac_localized": fl,
         "lattice_frac_localized": fl_l, "checks": checks, "n": g.n(), "lattice_n": gl.n(),
         "v1": {"partition_purity": purity_v1, "fiedler_eigenspace_purity": eig,
                "spectral_gap_ratio": spectral_gap_ratio(g, None, spec, cfg)}},
        notes, {"clusters": fig_g, "ipr": _ipr_figure(cfg, g, spec, gl, spec_l, "E2: IPR per mode")},
        summary=f"3-way purity {purity3:.3f} (V1 single vector {purity_v1:.3f}, eigenspace range "
                f"{eig['min']:.3f}-{eig['max']:.3f}); frac_loc {fl:.3f}; lattice {fl_l:.4f}",
    )


@experiment
def E2_v1(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    th = THRESHOLDS["E2_v1"]
    g = _gasket(cfg, cfg.e2_level)
    spec = get_spectrum(g, cfg)
    purity = partition_purity(g, None, spec, cfg)
    fl = frac_localized(g, None, spec, cfg)
    gap = spectral_gap_ratio(g, None, spec, cfg)
    eig = fiedler_eigenspace_purity(g, spec)
    gl = build_graph(cfg, 0, "lattice")
    spec_l = get_spectrum(gl, cfg)
    fl_l = frac_localized(gl, None, spec_l, cfg)
    checks = {"purity": purity >= th["purity_min"], "frac_localized": fl >= th["frac_localized_min"],
              "lattice_frac_localized": fl_l < th["lattice_frac_localized_max"]}
    passed = all(checks.values())
    notes = (f"lambda_2 has multiplicity {eig['multiplicity']} (spectral_gap_ratio = {gap:.3f}). phi_2 is the member "
             f"of the lambda_2 eigenspace with the sparsest sign cut (canonical basis, see spectrum.py); over all "
             f"directions of that eigenspace the purity ranges {eig['min']:.3f}-{eig['max']:.3f} "
             f"(mean {eig['mean']:.3f}). IPR is evaluated in the maximally localized basis of each degenerate "
             f"eigenspace. Failed checks: {[k for k, v in checks.items() if not v] or 'none'}.")
    fig_g = graph_figure(g, spec.mode(2) >= 0, mode="partition", title="E2_v1: Fiedler sign partition (gasket)",
                         colorbar_title="sign phi_2")
    return ExperimentResult(
        NAMES["E2_v1"], passed,
        {"partition_purity": purity, "frac_localized": fl, "lattice_frac_localized": fl_l,
         "spectral_gap_ratio": gap, "fiedler_eigenspace_purity": eig, "checks": checks,
         "n": g.n(), "lattice_n": gl.n()},
        notes, {"fiedler_partition": fig_g, "ipr": _ipr_figure(cfg, g, spec, gl, spec_l, "E2_v1: IPR per mode")},
        summary=f"purity {purity:.3f}; frac_loc {fl:.3f}; lattice {fl_l:.4f}",
    )


# ---------------------------------------------------------------------------- E3
def _layer_injection(n: int, idx: np.ndarray, rng: np.random.Generator, coherent: bool) -> np.ndarray:
    """Unit energy spread evenly over idx: |a_i|^2 = 1/len(idx), random phases unless coherent."""
    a = np.zeros(n, dtype=complex)
    ph = np.zeros(len(idx)) if coherent else rng.uniform(0.0, 2 * np.pi, len(idx))
    a[idx] = np.exp(1j * ph) / np.sqrt(len(idx))
    return a


def _retention(cfg: XonConfig, rule_name: str, rng: np.random.Generator, coherent: bool) -> dict:
    """R_s(k) for every birth layer s, tracked on tagged copies of the linear dynamics.

    By linearity each injection evolves independently, so it is propagated as its own column; new
    vertices start at zero in every tagged column (growth adds no tagged energy). Lattice: one layer
    (all vertices) injected at t = 0, measured every G steps.
    """
    c = cfg.replace(dynamics="wave", alpha=cfg.e3_alpha, beta=cfg.e3_beta, sink=False, drive="none")
    if rule_name == "tree":
        c = c.replace(branch=cfg.e3_tree_branch)
    epochs = cfg.e3_end_level - cfg.e3_start_level + 1
    grows = rule_name != "lattice"
    rule = get_rule(rule_name)
    g = build_graph(c, cfg.e3_start_level if grows else 0, rule_name)
    dyn = WaveDynamics()
    draws = 1 if coherent else max(int(cfg.e3_phase_draws), 1)
    A = np.zeros((g.n(), 0), dtype=complex)
    layers: list[dict] = []

    def inject() -> None:
        nonlocal A
        idx = np.flatnonzero(g.depth == g.max_depth())
        cols = [_layer_injection(g.n(), idx, rng, coherent) for _ in range(draws)]
        layers.append({"depth": int(g.max_depth()), "idx": idx, "cols": list(range(A.shape[1], A.shape[1] + draws)),
                       "R": [], "elapsed": [], "t0": elapsed})
        A = np.column_stack([A] + cols)

    elapsed = 0.0
    inject()
    for e in range(epochs):
        spec = get_spectrum(g, c) if dyn.uses_modal(g, c) else None
        A = dyn.propagate(g, A, c, spec, cfg.e3_grow_every)
        elapsed += cfg.e3_grow_every * dyn.dt(g, c)
        for lay in layers:
            block = A[lay["idx"]][:, lay["cols"]]
            lay["R"].append(float(np.mean(np.sum(np.abs(block) ** 2, axis=0))))
            lay["elapsed"].append(elapsed - lay["t0"])
        if e == epochs - 1 or not grows:
            continue
        g, _ = rule.grow(g, None, c, rng)
        A = np.vstack([A, np.zeros((g.n() - A.shape[0], A.shape[1]), dtype=complex)])
        inject()
    kmax = max(len(lay["R"]) for lay in layers)
    R = np.array([np.mean([lay["R"][k] for lay in layers if len(lay["R"]) > k]) for k in range(kmax)])
    # alpha I commutes with everything: layer s loses exactly exp(-2 alpha tau) of its energy to it
    Rc = np.array([np.mean([lay["R"][k] * np.exp(2 * c.alpha * lay["elapsed"][k])
                            for lay in layers if len(lay["R"]) > k]) for k in range(kmax)])
    k = np.arange(1, kmax + 1, dtype=float)
    kk = min(int(cfg.e3_fit_k), kmax)
    pw, ex = _fit(k[:kk], Rc[:kk], True), _fit(k[:kk], Rc[:kk], False)
    return {"n": g.n(), "layers": [lay["depth"] for lay in layers], "k": k.tolist(), "R": R.tolist(),
            "R_corrected": Rc.tolist(), "per_layer": {str(lay["depth"]): lay["R"] for lay in layers},
            "r2_powerlaw": pw["r2"], "r2_exponential": ex["r2"], "powerlaw_slope": pw["slope"],
            "exponential_slope": ex["slope"], "fits": {"powerlaw": pw, "exponential": ex}, "fit_k": kk,
            "dt": dyn.dt(g, c)}


def _retention_figure(out: dict, fit_k: int, title: str) -> go.Figure:
    fig = make_subplots(rows=1, cols=2, subplot_titles=("log-log (power law is a line)",
                                                        "log-linear (exponential is a line)"))
    colors = {"gasket": "#d62728", "tree": "#1f77b4", "lattice": "#7f7f7f"}
    for name, r in out.items():
        k, rc = np.array(r["k"]), np.array(r["R_corrected"])
        for col, key in ((1, "powerlaw"), (2, "exponential")):
            fig.add_trace(go.Scatter(x=k, y=rc, mode="markers+lines", name=name, legendgroup=name,
                                     showlegend=col == 1, line=dict(color=colors.get(name))), row=1, col=col)
            f = r["fits"][key]
            if np.isfinite(f["slope"]):
                kf = np.linspace(1, fit_k, 30)
                yf = np.exp(f["intercept"] + f["slope"] * (np.log(kf) if key == "powerlaw" else kf))
                fig.add_trace(go.Scatter(x=kf, y=yf, mode="lines", legendgroup=name, showlegend=False,
                                         line=dict(color=colors.get(name), dash="dot")), row=1, col=col)
    fig.update_xaxes(type="log", title_text="k (growth steps; lattice: units of G steps)", row=1, col=1)
    fig.update_xaxes(title_text="k", row=1, col=2)
    fig.update_yaxes(type="log", title_text="R(k) x exp(2 alpha k G dt)", row=1, col=1)
    fig.update_yaxes(type="log", row=1, col=2)
    fig.update_layout(title=title, height=440)
    return fig


@experiment
def E3(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    kk = int(cfg.e3_fit_k)
    out = {name: _retention(cfg, name, rng, coherent=False) for name in ("gasket", "tree", "lattice")}
    coherent = {name: _retention(cfg, name, rng, coherent=True) for name in ("gasket", "tree", "lattice")}
    gk, tr = out["gasket"], out["tree"]
    gasket_ok = bool(gk["r2_powerlaw"] > gk["r2_exponential"])
    tree_ok = bool(tr["r2_exponential"] >= tr["r2_powerlaw"])
    passed = gasket_ok and tree_ok
    dt = gk["dt"]
    notes = (f"Protocol: levels {cfg.e3_start_level}->{cfg.e3_end_level}, G = {cfg.e3_grow_every} steps (dt = {dt:g}) "
             f"between growths and after the last one, alpha = {cfg.e3_alpha}, beta = {cfg.e3_beta}, no drive, no "
             f"sink. Each newly born layer (the level-{cfg.e3_start_level} vertices at t = 0, then every new layer) "
             f"receives unit energy |a_i|^2 = 1/n_s with independent uniform random phases, averaged over "
             f"{cfg.e3_phase_draws} draws; R_s(k) is measured on that layer's vertices after k epochs of G steps. "
             f"Correction: every R_s(k) is multiplied by exp(2 alpha tau), tau = k G dt, which removes the known "
             f"uniform decay exp(-2 alpha G k) exactly (alpha I commutes with L); fits use the corrected R over "
             f"k = 1..{kk}. The coherent (equal-phase) injection is reported but not judged: its constant-mode part "
             f"never decays under beta L and dilutes as the graph grows. "
             f"Gasket R2 pow {gk['r2_powerlaw']:.3f} vs exp {gk['r2_exponential']:.3f} "
             f"({'ok' if gasket_ok else 'FAIL'}); tree exp {tr['r2_exponential']:.3f} vs pow {tr['r2_powerlaw']:.3f} "
             f"({'ok' if tree_ok else 'FAIL'}).")
    figs = {"retention": _retention_figure(out, kk, "E3: retention R(k), random-phase injection (judged)"),
            "retention_coherent": _retention_figure(coherent, kk, "E3: retention R(k), coherent injection "
                                                                  "(reported only)")}
    return ExperimentResult(
        NAMES["E3"], passed,
        {**out, "coherent_injection": coherent, "checks": {"gasket": gasket_ok, "tree": tree_ok},
         "alpha_correction": "R(k) multiplied by exp(2 alpha k G dt) before fitting"},
        notes, figs,
        summary=f"gasket R2 pow {gk['r2_powerlaw']:.3f} vs exp {gk['r2_exponential']:.3f}; tree pow "
                f"{tr['r2_powerlaw']:.3f} vs exp {tr['r2_exponential']:.3f} (k = 1..{kk}, alpha divided out)",
    )


def _driven_depth_energy(g, cfg: XonConfig, steps: int, rng) -> np.ndarray:
    dyn = WaveDynamicsV1()
    s = dyn.init_state(g, cfg, rng)
    spec = get_spectrum(g, cfg) if dyn.uses_modal(g, cfg) else None
    acc = np.zeros(g.max_depth() + 1)
    count = 0
    for t in range(steps):
        s = dyn.step(g, s, cfg, rng, spec)
        if t >= steps // 2:
            acc += depth_energy_array(g, s)
            count += 1
    return acc / max(count, 1)


@experiment
def E3_v1(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    c = cfg.replace(drive="noise")
    cases = {
        "gasket": build_graph(c, cfg.e3_level, "gasket"),
        "tree": build_graph(c.replace(branch=cfg.e3_tree_branch), cfg.e3_tree_depth, "tree"),
        "lattice": build_graph(c, 0, "lattice"),
    }
    out, figs = {}, {}
    for name, g in cases.items():
        E = _driven_depth_energy(g, c, cfg.e3_steps, rng)
        pw, ex = fit_powerlaw(E), fit_exponential(E)
        out[name] = {"n": g.n(), "E": E.tolist(), "r2_powerlaw": pw["r2"], "r2_exponential": ex["r2"],
                     "powerlaw_slope": pw["slope"], "exponential_slope": ex["slope"]}
        if len(E) > 1:
            figs[f"depth_{name}"] = depth_energy_figure(E, f"E3_v1: E[d] ({name}, N={g.n()})")
    gk, tr = out["gasket"], out["tree"]
    passed = bool(gk["r2_powerlaw"] > gk["r2_exponential"])
    tree_ok = bool(tr["r2_exponential"] >= tr["r2_powerlaw"])
    notes = (f"E[d] is the total energy at depth d under wave_v1, time-averaged over the second half of "
             f"T={cfg.e3_steps} noise-driven steps; both fits use depths d >= 1 (log d is undefined at 0). Tree "
             f"expectation R2_exp >= R2_pow {'met' if tree_ok else 'VIOLATED (reported, does not fail E3_v1)'}. The "
             f"lattice has a single depth, so no fit applies.")
    return ExperimentResult(
        NAMES["E3_v1"], passed, {**out, "tree_expectation_met": tree_ok}, notes, figs,
        summary=f"gasket R2 pow {gk['r2_powerlaw']:.3f} vs exp {gk['r2_exponential']:.3f}; "
                f"tree pow {tr['r2_powerlaw']:.3f} vs exp {tr['r2_exponential']:.3f}",
    )


# ---------------------------------------------------------------------------- E4: linear (E4a, E4_v1)
def _e4_linear_run(cfg: XonConfig, seed: int, dyn_cls, sink_max: bool = False) -> tuple[np.ndarray, list[int]]:
    """One grow-while-driving run; returns frontier harmonicity (steps, factors) and growth steps.

    sink_max: turn Gamma_sink on at the largest allowed gamma_s of each level (V1.1 wave).
    """
    rng = np.random.default_rng(seed)
    rule = get_rule("gasket")
    g = build_graph(cfg, cfg.e4_start_level, "gasket")
    dyn = dyn_cls()
    s = dyn.init_state(g, cfg, rng)
    rows, growth = [], []
    level = cfg.e4_start_level
    while True:
        spec = get_spectrum(g, cfg)
        run = cfg.replace(sink=True, sink_gamma=WaveDynamics.sink_bound(cfg, spec)) if sink_max else cfg
        mask = g.frontier_mask(cfg.frontier_window)
        for _ in range(cfg.e4_grow_every):
            s = dyn.step(g, s, run, rng, spec)
            m = trace_metrics(g, s, spec, run, mask)
            rows.append([m[f"harmonicity_{f}"] for f in COHERENCE_FACTORS])
        if level >= cfg.e4_end_level:
            break
        g, s = rule.grow(g, s, cfg, rng)
        level += 1
        growth.append(len(rows))
    return np.array(rows), growth


def _e4_linear(cfg: XonConfig, rng: np.random.Generator, eid: str, conditions: dict, dyn_cls,
               control_label: str) -> ExperimentResult:
    """V1 E4 analysis: conditions = {"sink": (cfg, sink_max), "control": (cfg, sink_max)}."""
    th = THRESHOLDS[eid]
    seeds = [int(x) for x in rng.integers(0, 2 ** 31 - 1, size=cfg.e4_seeds)]
    G = cfg.e4_grow_every
    traces: dict[str, list[np.ndarray]] = {c: [] for c in conditions}
    growth: list[int] = []
    for sd in seeds:
        for cname, (ccfg, sink_max) in conditions.items():
            h, growth = _e4_linear_run(ccfg, sd, dyn_cls, sink_max)
            traces[cname].append(h)
    per_factor = {}
    for fi, f in enumerate(COHERENCE_FACTORS):
        res = {}
        for cname in conditions:
            H = np.stack([t[:, fi] for t in traces[cname]])       # (seeds, steps)
            start, end = H[:, :G].mean(axis=1), H[:, -G:].mean(axis=1)
            res[cname] = {"start": start.tolist(), "end": end.tolist(),
                          "increase_mean": float(np.mean(end - start))}
        start, end = np.array(res["sink"]["start"]), np.array(res["sink"]["end"])
        p = float(stats.ttest_rel(end, start, alternative="greater").pvalue)
        inc_s, inc_c = res["sink"]["increase_mean"], res["control"]["increase_mean"]
        rises = bool(np.isfinite(p) and p < th["p_max"] and inc_s > 0)
        attributable = bool(inc_s >= th["control_ratio_min"] * inc_c)
        per_factor[f] = {**res, "p_value": p, "rises": rises, "attributable_to_sink": attributable,
                         "passed": rises and attributable}
    primary = cfg.harmonicity_coherence
    pf = per_factor[primary]
    passed = pf["passed"]
    n_hold = sum(per_factor[f]["passed"] for f in COHERENCE_FACTORS)
    verdict = []
    for f in COHERENCE_FACTORS:
        r = per_factor[f]
        v = "PASS" if r["passed"] else ("rises, but gradient not attributable to sink" if r["rises"] else "does not rise")
        verdict.append(f"{f}: {v} (sink {r['sink']['increase_mean']:+.4f}, control "
                       f"{r['control']['increase_mean']:+.4f}, p={r['p_value']:.3g})")
    notes = (f"Primary coherence factor: {primary}. Control: {control_label}. Start/end means are over the first "
             f"and last growth epochs (G={G} steps each; levels {cfg.e4_start_level} and {cfg.e4_end_level}). "
             f"Frontier = depth >= d_max - {cfg.frontier_window}. Result holds under {n_hold}/3 coherence factors "
             f"(a conclusion that holds under only one is not a conclusion). " + " | ".join(verdict))
    fig = go.Figure()
    x = np.arange(len(traces["sink"][0]))
    fi = COHERENCE_FACTORS.index(primary)
    for cname, color in (("sink", "#d62728"), ("control", "#1f77b4")):
        H = np.stack([t[:, fi] for t in traces[cname]])
        fig.add_trace(go.Scatter(x=x, y=H.mean(axis=0), mode="lines", name=f"{cname} (mean of {len(seeds)})",
                                 line=dict(color=color)))
    for gs in growth:
        fig.add_vline(x=gs, line=dict(color="gray", dash="dot"))
    fig.update_layout(title=f"{eid}: frontier harmonicity ({primary})", xaxis_title="step",
                      yaxis_title="harmonicity", height=420)
    fig_bar = go.Figure()
    for cname in conditions:
        fig_bar.add_trace(go.Bar(x=list(COHERENCE_FACTORS), name=cname,
                                 y=[per_factor[f][cname]["increase_mean"] for f in COHERENCE_FACTORS]))
    fig_bar.update_layout(title=f"{eid}: end - start increase by coherence factor", barmode="group", height=380)
    return ExperimentResult(
        NAMES[eid], passed,
        {"primary_factor": primary, "per_factor": per_factor, "seeds": seeds, "factors_holding": n_hold},
        notes, {"harmonicity_trace": fig, "increase_by_factor": fig_bar},
        summary=f"{primary}: sink {pf['sink']['increase_mean']:+.4f} vs control "
                f"{pf['control']['increase_mean']:+.4f}, p={pf['p_value']:.3g}; holds {n_hold}/3 factors",
    )


@experiment
def E4a(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    base = cfg.replace(dynamics="wave", drive="noise", sink=False)
    return _e4_linear(cfg, rng, "E4a", {"sink": (base, True), "control": (base, False)}, WaveDynamics,
                      "Gamma_sink off; sink condition uses gamma_s = 0.1 beta lambda_2 of each level")


@experiment
def E4_v1(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    conditions = {"sink": (cfg.replace(drive="noise"), False),
                  "control": (cfg.replace(drive="noise", gamma1=0.0), False)}
    return _e4_linear(cfg, rng, "E4_v1", conditions, WaveDynamicsV1, "uniform damping (gamma1 = 0), wave_v1")


# ---------------------------------------------------------------------------- E4: nonlinear (E4b, E4c)
E4_VARIANTS = ("harmonicity_osc",) + tuple(f"harmonicity_{f}" for f in COHERENCE_FACTORS)
_E4_EXTRA = ("cluster_order", "n_clusters_eff")


def _use_complete_graph(dyn, g) -> None:
    """Couple dyn through the complete graph on g's vertices with weight mean degree / (N - 1)."""
    n = g.n()
    w = 2.0 * g.n_edges() / n / max(n - 1, 1)
    if isinstance(dyn, OscillatorDynamics):
        dyn.J = CompleteCoupling(n, w, "adjacency")
    else:
        dyn.coupling = CompleteCoupling(n, w, "laplacian")


def _e4_nonlinear_run(cfg: XonConfig, seed: int, dyn_cls, complete: bool) -> tuple[np.ndarray, list[int]]:
    """One grow-while-driving run; per-step frontier values of E4_VARIANTS then _E4_EXTRA."""
    rng = np.random.default_rng(seed)
    rule = get_rule("gasket")
    g = build_graph(cfg, cfg.e4_start_level, "gasket")
    dyn = dyn_cls()
    s = dyn.init_state(g, cfg, rng)
    rows, growth = [], []
    level = cfg.e4_start_level
    while True:
        spec = get_spectrum(g, cfg)
        if complete:
            _use_complete_graph(dyn, g)
        mask = g.frontier_mask(cfg.frontier_window)
        tracker = ClusterTracker(spectral_clusters(spec, cfg.n_clusters, cfg.cluster_restarts, cfg.seed),
                                 cfg.cluster_window, cfg.cluster_drift_max, cfg.n_clusters)
        for _ in range(cfg.e4_grow_every):
            s = dyn.step(g, s, cfg, rng, spec)
            m = trace_metrics(g, s, spec, cfg, mask)
            c = tracker.update(s, mask)
            rows.append([c["harmonicity_osc"]] + [m[f"harmonicity_{f}"] for f in COHERENCE_FACTORS]
                        + [c[k] for k in _E4_EXTRA])
        if level >= cfg.e4_end_level:
            break
        g, s = rule.grow(g, s, cfg, rng)
        level += 1
        growth.append(len(rows))
    return np.array(rows), growth


def _e4_nonlinear(cfg: XonConfig, rng: np.random.Generator, eid: str, dyn_cls, base: XonConfig,
                  null_name: str, null_cfg: XonConfig, setup: str) -> ExperimentResult:
    th = THRESHOLDS[eid]
    seeds = [int(x) for x in rng.integers(0, 2 ** 31 - 1, size=cfg.e4_seeds)]
    conditions = {"gasket": (base, False), "complete": (base, True), null_name: (null_cfg, False)}
    G = cfg.e4_grow_every
    traces: dict[str, list[np.ndarray]] = {c: [] for c in conditions}
    growth: list[int] = []
    for sd in seeds:
        for cname, (ccfg, complete) in conditions.items():
            rows, growth = _e4_nonlinear_run(ccfg, sd, dyn_cls, complete)
            traces[cname].append(rows)
    columns = E4_VARIANTS + _E4_EXTRA
    se = {}
    for ci, col in enumerate(columns):
        se[col] = {}
        for cname in conditions:
            H = np.stack([t[:, ci] for t in traces[cname]])
            se[col][cname] = (H[:, :G].mean(axis=1), H[:, -G:].mean(axis=1))
    per_variant = {}
    for var in E4_VARIANTS:
        (gs, ge), (_, ce), (ns, ne) = se[var]["gasket"], se[var]["complete"], se[var][null_name]
        p_rise, p_struct, p_null = _paired_greater(ge, gs), _paired_greater(ge, ce), _paired_greater(ne, ns)
        rises = bool(np.isfinite(p_rise) and p_rise < th["p_max"] and np.mean(ge - gs) > 0)
        beats = bool(np.isfinite(p_struct) and p_struct < th["p_max"] and np.mean(ge - ce) > 0)
        null_rises = bool(np.isfinite(p_null) and p_null < th["p_max"] and np.mean(ne - ns) > 0)
        per_variant[var] = {
            **{cname: {"start": se[var][cname][0].tolist(), "end": se[var][cname][1].tolist(),
                       "start_mean": float(se[var][cname][0].mean()), "end_mean": float(se[var][cname][1].mean())}
               for cname in conditions},
            "p_rise": p_rise, "p_gasket_vs_complete": p_struct, f"p_rise_{null_name}": p_null,
            "rises": rises, "beats_complete": beats, f"{null_name}_rises": null_rises,
            "criterion_met": rises and beats and not null_rises}
    diagnostics = {col: {cname: {"start_mean": float(se[col][cname][0].mean()),
                                 "end_mean": float(se[col][cname][1].mean())} for cname in conditions}
                   for col in _E4_EXTRA}
    head = per_variant["harmonicity_osc"]
    passed = head["criterion_met"]
    lines = []
    for var in E4_VARIANTS:
        r = per_variant[var]
        lines.append(f"{var}: gasket {r['gasket']['start_mean']:.4f} -> {r['gasket']['end_mean']:.4f} "
                     f"(p={r['p_rise']:.3g}); complete end {r['complete']['end_mean']:.4f} "
                     f"(p={r['p_gasket_vs_complete']:.3g}); {null_name} {r[null_name]['start_mean']:.4f} -> "
                     f"{r[null_name]['end_mean']:.4f} (p={r[f'p_rise_{null_name}']:.3g})"
                     f"{' [criterion met]' if r['criterion_met'] else ''}")
    notes = (f"{setup} Start/end = means over the first and last growth epochs (G = {G} steps; levels "
             f"{cfg.e4_start_level} and {cfg.e4_end_level}); frontier = depth >= d_max - {cfg.frontier_window}. "
             f"Clusters = 3-way spectral clusters of the gasket, recomputed after each growth; n_clusters_eff merges "
             f"cluster frequencies whose phases drift apart by less than {cfg.cluster_drift_max:g} rad over the last "
             f"{cfg.cluster_window} steps. Complete-graph control: same vertices, depths, frequencies, noise and "
             f"clusters, coupled through K_N with uniform weight (gasket mean degree)/(N - 1); the V1 harmonicity "
             f"variants use the gasket's modes in every condition. One-sided paired t-tests across {len(seeds)} "
             f"seeds; the pass is on harmonicity_osc, the other variants are reported. " + " | ".join(lines))
    x = np.arange(len(traces["gasket"][0]))
    colors = {"gasket": "#d62728", "complete": "#1f77b4", null_name: "#7f7f7f"}
    fig = go.Figure()
    for cname in conditions:
        H = np.stack([t[:, 0] for t in traces[cname]])
        fig.add_trace(go.Scatter(x=x, y=H.mean(axis=0), mode="lines", name=f"{cname} (mean of {len(seeds)})",
                                 line=dict(color=colors[cname])))
    for gsx in growth:
        fig.add_vline(x=gsx, line=dict(color="gray", dash="dot"))
    fig.update_layout(title=f"{eid}: frontier harmonicity_osc", xaxis_title="step", yaxis_title="harmonicity_osc",
                      height=420)
    fig_cl = make_subplots(rows=1, cols=2, subplot_titles=("cluster_order", "n_clusters_eff"))
    for ci, col in enumerate(_E4_EXTRA):
        idx = len(E4_VARIANTS) + ci
        for cname in conditions:
            H = np.stack([t[:, idx] for t in traces[cname]])
            fig_cl.add_trace(go.Scatter(x=x, y=H.mean(axis=0), mode="lines", name=cname, legendgroup=cname,
                                        showlegend=ci == 0, line=dict(color=colors[cname])), row=1, col=ci + 1)
    fig_cl.update_layout(title=f"{eid}: cluster diagnostics (frontier, mean over seeds)", height=380)
    fig_bar = go.Figure()
    for cname in conditions:
        fig_bar.add_trace(go.Bar(x=list(E4_VARIANTS), name=cname,
                                 y=[per_variant[v][cname]["end_mean"] - per_variant[v][cname]["start_mean"]
                                    for v in E4_VARIANTS]))
    fig_bar.update_layout(title=f"{eid}: end - start by harmonicity variant", barmode="group", height=380)
    return ExperimentResult(
        NAMES[eid], passed,
        {"per_variant": per_variant, "diagnostics": diagnostics, "seeds": seeds, "null_control": null_name,
         "variants_meeting_criterion": [v for v in E4_VARIANTS if per_variant[v]["criterion_met"]]},
        notes, {"harmonicity_osc_trace": fig, "clusters": fig_cl, "increase_by_variant": fig_bar},
        summary=f"harmonicity_osc gasket {head['gasket']['start_mean']:.3f}->{head['gasket']['end_mean']:.3f} "
                f"(p={head['p_rise']:.3g}); vs complete {head['complete']['end_mean']:.3f} "
                f"(p={head['p_gasket_vs_complete']:.3g}); {null_name} p={head[f'p_rise_{null_name}']:.3g}",
    )


@experiment
def E4b(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    base = cfg.replace(dynamics="stuart_landau", drive="noise", sl_sigma=cfg.e4_sigma, omega_mode="by_depth")
    setup = (f"stuart_landau: mu = {base.sl_mu:g}, omega_i = {base.omega0:g} + {base.delta_omega:g} depth/d_max, "
             f"c = {base.c:g}, alpha = {base.sl_alpha:g}, beta = {base.sl_beta:g}, noise sigma = {base.sl_sigma:g} "
             f"at the newest layer; null control mu = 0.")
    return _e4_nonlinear(cfg, rng, "E4b", StuartLandauDynamics, base, "mu0", base.replace(sl_mu=0.0), setup)


@experiment
def E4c(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    base = cfg.replace(dynamics="oscillator", drive="noise", osc_sigma=cfg.e4_sigma, osc_Ks=0.0,
                       omega_mode="by_depth")
    setup = (f"oscillator (Kuramoto): K = {base.osc_K:g}, K_s = 0, omega_i = {base.omega0:g} + "
             f"{base.delta_omega:g} depth/d_max, phase noise sigma = {base.osc_sigma:g} at the newest layer; null "
             f"control K = 0.")
    return _e4_nonlinear(cfg, rng, "E4c", OscillatorDynamics, base, "K0", base.replace(osc_K=0.0), setup)


# ---------------------------------------------------------------------------- E5
@experiment
def E5(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    th = THRESHOLDS["E5"]
    g = _gasket(cfg, cfg.e5_level)
    k = cfg.e5_stalk_dim
    truth, frames = CellularSheaf.random_flat(g, k, rng)
    kernel_dim = int(truth.global_sections(g).shape[1])
    examples = sample_sections(frames, rng, cfg.e5_examples)
    learned = CellularSheaf.identity(g, k)
    history = learned.learn(g, examples, cfg.e5_learn_eta, cfg.e5_learn_steps)
    x_true = sample_sections(frames, rng, 1)[0]
    clamp = np.zeros(g.n(), dtype=bool)
    clamp[rng.choice(g.n(), size=int(round(cfg.e5_clamp_frac * g.n())), replace=False)] = True
    free = np.repeat(~clamp, k)

    def recover(sheaf: CellularSheaf) -> float:
        x = sheaf.diffuse(g, np.zeros(g.n() * k), cfg.e5_diffuse_eta, cfg.e5_diffuse_steps, clamp, x_true)
        return float(np.mean((x[free] - x_true[free]) ** 2))

    mse_learned = recover(learned)
    mse_identity = recover(CellularSheaf.identity(g, k))
    mse_truth = recover(truth)
    ratio = mse_learned / mse_identity if mse_identity > 0 else float("inf")
    passed = bool(ratio < th["mse_ratio_max"])
    fig = go.Figure(go.Scatter(y=history, mode="lines"))
    fig.update_layout(title="E5: mean Dirichlet energy of training examples during learning",
                      xaxis_title="step", yaxis_title="energy", yaxis_type="log", height=380)
    return ExperimentResult(
        NAMES["E5"], passed,
        {"mse_learned": mse_learned, "mse_identity": mse_identity, "mse_ground_truth": mse_truth,
         "mse_ratio": ratio, "ground_truth_kernel_dim": kernel_dim,
         "learned_kernel_dim": int(learned.global_sections(g, tol=1e-6).shape[1]),
         "final_training_energy": history[-1] if history else None, "n": g.n(), "stalk_dim": k},
        f"Ground truth: random orthogonal maps with trivial holonomy (vertex/edge frames), kernel dim "
        f"{kernel_dim}. Maps learned from identity on {cfg.e5_examples} consistent states; "
        f"{int(clamp.sum())} of {g.n()} vertices clamped.",
        {"learning_curve": fig},
        summary=f"MSE ratio {ratio:.3g} (learned {mse_learned:.3g} / identity {mse_identity:.3g})",
    )


# ---------------------------------------------------------------------------- E6
@experiment
def E6(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    th = THRESHOLDS["E6"]
    problems = [MaxCutProblem.random_regular(cfg.e6_n, 3, seed) for seed in range(cfg.e6_seeds)]
    optima = [p.optimum() for p in problems]
    ratios, cuts, energy = [], [], []
    for p in problems:
        s, en = oscillator_solve(p, cfg, rng)
        sc = p.score(s)
        ratios.append(sc["ratio"])
        cuts.append(sc["cut"])
        energy.append(en)
    ok = sum(r >= th["ratio_min"] for r in ratios)
    fig = go.Figure()
    for i, en in enumerate(energy):
        idx = _downsample_idx(len(en))
        fig.add_trace(go.Scatter(x=idx, y=en[idx], mode="lines", name=f"seed {i}: {cuts[i]}/{optima[i]}"))
    fig.update_layout(title="E6: oscillator energy -sum J cos(theta_i - theta_j) during annealing",
                      xaxis_title="step", yaxis_title="energy", height=420)
    return ExperimentResult(
        NAMES["E6"], bool(ok >= th["seeds_ok_min"]),
        {"optima": optima, "cuts": cuts, "ratios": ratios, "seeds_ok": ok},
        f"Oscillator Ising machine on J = -A: K = {cfg.osc_K:g}, K_s ramped 0 -> {cfg.osc_Ks_max:g} over "
        f"{cfg.osc_anneal_steps} of {cfg.e6_steps} steps, phase noise {cfg.osc_noise:g} at every vertex, omega = 0 "
        f"(frame of the sub-harmonic injection); spins = sign(Re a). {ok}/{len(ratios)} seeds reached "
        f"{th['ratio_min']:.0%} of the optimum.",
        {"energy": fig},
        summary=f"{ok}/{len(ratios)} seeds >= {th['ratio_min']:.0%} (cuts {cuts} vs optima {optima})",
    )


# ---------------------------------------------------------------------------- E7
def simplex_vertex_count(n: int, level: int) -> int:
    return (n + 1) + (n + 1) * ((n + 1) ** level - 1) // 2


@experiment
def E7(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    th = THRESHOLDS["E7"]
    rows, fig = {}, go.Figure()
    for n in cfg.e7_dims:
        level = min(range(1, 16), key=lambda L: abs(np.log(simplex_vertex_count(n, L) / cfg.e7_target_n)))
        g = build_graph(cfg.replace(simplex_dim=n), level, "simplex")
        est = spectral_dimension_est(g, cfg=cfg, rng=rng)
        theory = 2 * np.log(n + 1) / np.log(n + 3)
        err = abs(est["d_s"] - theory)
        rows[f"n={n}"] = {"level": level, "N": g.n(), "d_s": est["d_s"], "theory": float(theory),
                          "abs_error": float(err), "fit_r2": est["r2"], "ok": bool(err <= th["tol"])}
        fig.add_trace(go.Scatter(x=est["t"], y=est["rp"], mode="markers+lines",
                                 name=f"n={n} (N={g.n()}): d_s={est['d_s']:.3f} vs {theory:.3f}"))
    fig.update_layout(title="E7: return probability of the lazy walk", xaxis_type="log", yaxis_type="log",
                      xaxis_title="t", yaxis_title="RP(t)", height=420)
    passed = all(r["ok"] for r in rows.values())
    return ExperimentResult(
        NAMES["E7"], passed, rows,
        f"Window t in [{cfg.rp_t_min}, {cfg.rp_t_max}]; levels chosen so N is closest to {cfg.e7_target_n}; "
        f"RP exact from the spectrum when N <= {cfg.dense_max}, else Hutchinson ({cfg.rp_probes} probes).",
        {"return_probability": fig},
        summary="; ".join(f"{k}: {r['d_s']:.3f} (th {r['theory']:.3f})" for k, r in rows.items()),
    )


# ---------------------------------------------------------------------------- E8
def _e8(cfg: XonConfig, rng: np.random.Generator, eid: str, sink: bool) -> ExperimentResult:
    th = THRESHOLDS[eid]
    g = _gasket(cfg, cfg.e8_level)
    spec = get_spectrum(g, cfg)
    c = cfg.replace(dynamics="wave", sink=False)
    if sink:
        c = c.replace(sink=True, sink_gamma=WaveDynamics.sink_bound(c, spec))
    dyn = WaveDynamics()
    s = dyn.init_state(g, c, rng)
    dt = dyn.dt(g, c)
    lam = spec.lam
    k_gap = spectral_k_gap(spec, cfg.k_gap_max)
    t_global = 1.0 / (2.0 * c.beta * lam[1])
    t_individual = 1.0 / (2.0 * c.beta * (lam[k_gap] - lam[1])) if spec.k_used > k_gap else float("nan")
    T1 = int(np.ceil(cfg.e8_collapse_times * t_global / dt))
    T2 = int(cfg.e8_steps)
    quiet, driven = c.replace(drive="none"), c.replace(drive="noise")
    low, fund = np.empty(T1 + T2), np.empty(T1 + T2)
    for i in range(T1 + T2):
        s = dyn.step(g, s, quiet if i < T1 else driven, rng, spec)
        p = modal_decomposition(g, s, spec).p
        low[i], fund[i] = p[:k_gap].sum(), p[0]
    end_low, end_fund = float(low[T1 - 1]), float(fund[T1 - 1])
    driven_max = float(low[T1 + T2 // 2:].max())
    ok_quiet = end_low >= th["low_subspace_min"]
    ok_driven = driven_max <= th["driven_low_subspace_max"]
    passed = bool(ok_quiet and ok_driven)
    v1_len = min(int(cfg.e8_steps), T1)
    t = dt * np.arange(1, T1 + T2 + 1)
    fig = make_subplots(rows=1, cols=2, subplot_titles=("phase 1: no drive", "phase 2: noise drive"),
                        horizontal_spacing=0.12)
    i1 = _downsample_idx(T1, 700, log=True)
    i2 = T1 + _downsample_idx(T2, 500)
    for name, y, color in (("low_subspace_fraction", low, "#d62728"), ("fundamental_fraction", fund, "#1f77b4")):
        fig.add_trace(go.Scatter(x=t[i1], y=y[i1], mode="lines", name=name, legendgroup=name,
                                 line=dict(color=color)), row=1, col=1)
        fig.add_trace(go.Scatter(x=t[i2] - t[T1 - 1], y=y[i2], mode="lines", name=name, legendgroup=name,
                                 showlegend=False, line=dict(color=color)), row=1, col=2)
    for x_mark, dash, label in ((t_global, "dash", "1/(2 beta lambda_2)"),
                                (t_individual, "dot", f"1/(2 beta (lambda_{k_gap + 1} - lambda_2))")):
        if np.isfinite(x_mark):
            fig.add_trace(go.Scatter(x=[x_mark, x_mark], y=[0, 1], mode="lines", name=label,
                                     line=dict(color="gray", dash=dash)), row=1, col=1)
    fig.add_hline(y=th["low_subspace_min"], line=dict(dash="dash"), row=1, col=1)
    fig.add_hline(y=th["driven_low_subspace_max"], line=dict(dash="dot"), row=1, col=2)
    fig.update_xaxes(type="log", title_text="time (log)", row=1, col=1)
    fig.update_xaxes(title_text="time since drive on", row=1, col=2)
    fig.update_layout(title=f"{eid}: energy fractions (predicted global collapse 1/(2 beta lambda_2) = "
                            f"{t_global:.0f})", height=480,
                      legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="left", x=0))
    sink_txt = (f"Gamma_sink on at gamma_s = {c.sink_gamma:.4g} (= 0.1 beta lambda_2) on depths <= d_max - "
                f"{c.sink_depth}; RK4 integrator. " if sink else "Gamma_sink off; exact modal integrator. ")
    notes = (f"{sink_txt}Gasket level {cfg.e8_level}, alpha = {c.alpha:g}, beta = {c.beta:g}, dt = {dt:g}. k_gap = "
             f"{k_gap} (lambda_{k_gap + 1}/lambda_{k_gap} = {lam[k_gap] / lam[k_gap - 1]:.2f}). Phase 1 = predicted "
             f"global-collapse time 1/(2 beta lambda_2) = {t_global:.1f} ({T1} steps) without drive from a random "
             f"state; modes above the gap fall behind the low subspace on the time scale 1/(2 beta (lambda_"
             f"{k_gap + 1} - lambda_2)) = {t_individual:.1f}. End of phase 1: low_subspace_fraction {end_low:.4f}, "
             f"fundamental_fraction {end_fund:.4f}. At step {v1_len} (the V1 phase length) the fractions were "
             f"{low[v1_len - 1]:.4f} and {fund[v1_len - 1]:.4f}. Phase 2: {T2} steps of noise drive at the "
             f"frontier, judged on its second half (max {driven_max:.4f}).")
    return ExperimentResult(
        NAMES[eid], passed,
        {"low_subspace_end_phase1": end_low, "fundamental_end_phase1": end_fund,
         "low_subspace_max_driven_second_half": driven_max,
         "checks": {"no_drive": bool(ok_quiet), "driven": bool(ok_driven)}, "k_gap": k_gap,
         "lambda": [float(x) for x in lam[:k_gap + 2]], "predicted_global_collapse_time": t_global,
         "predicted_individuation_time": t_individual, "phase1_steps": T1, "phase2_steps": T2, "dt": dt,
         "at_v1_phase_length": {"step": v1_len, "low_subspace_fraction": float(low[v1_len - 1]),
                                "fundamental_fraction": float(fund[v1_len - 1])},
         "sink_gamma": float(c.sink_gamma) if sink else 0.0},
        notes, {"energy_fractions": fig},
        summary=f"phase 1 end: low subspace {end_low:.4f}, fundamental {end_fund:.4f} (t = {t_global:.0f}); "
                f"driven max {driven_max:.4f}",
    )


@experiment
def E8(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    return _e8(cfg, rng, "E8", sink=False)


@experiment
def E8b(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    return _e8(cfg, rng, "E8b", sink=True)


@experiment
def E8_v1(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    th = THRESHOLDS["E8_v1"]
    g = _gasket(cfg, cfg.e8_level)
    spec = get_spectrum(g, cfg)
    dyn = WaveDynamicsV1()
    s = dyn.init_state(g, cfg, rng)
    T = cfg.e8_steps
    quiet, driven = cfg.replace(drive="none"), cfg.replace(drive="noise")
    ff_quiet, ff_driven = [], []
    for _ in range(T):
        s = dyn.step(g, s, quiet, rng, spec)
        ff_quiet.append(fundamental_fraction(g, s, spec))
    md = modal_decomposition(g, s, spec)
    for _ in range(T):
        s = dyn.step(g, s, driven, rng, spec)
        ff_driven.append(fundamental_fraction(g, s, spec))
    end_quiet = ff_quiet[-1]
    driven_max = float(np.max(ff_driven[T // 2:]))
    ok_quiet = end_quiet >= th["no_drive_fundamental_min"]
    ok_driven = driven_max <= th["driven_fundamental_max"]
    passed = bool(ok_quiet and ok_driven)
    # where the undriven energy went: secular decay rate of each mode = <phi_k, Gamma phi_k>
    gam = damping_profile(g, cfg)
    rates = (spec.phi ** 2 * gam[:, None]).sum(axis=0)
    top = np.argsort(md.p)[::-1][:5]
    front = g.frontier_mask(0)
    dominant = [{"k": int(i + 1), "lambda": float(spec.lam[i]), "p": float(md.p[i]), "decay_rate": float(rates[i]),
                 "frontier_weight": float((spec.phi[front, i] ** 2).sum())} for i in top]
    fig = go.Figure()
    fig.add_trace(go.Scatter(y=ff_quiet, mode="lines", name="no drive"))
    fig.add_trace(go.Scatter(x=np.arange(T, 2 * T), y=ff_driven, mode="lines", name="noise drive"))
    fig.add_hline(y=th["no_drive_fundamental_min"], line=dict(dash="dash"))
    fig.add_hline(y=th["driven_fundamental_max"], line=dict(dash="dot"))
    fig.update_layout(title="E8_v1: fundamental fraction", xaxis_title="step", yaxis_title="p_1", height=400)
    notes = (f"wave_v1 (depth damping). Phase 1: T={T} steps without drive from a random initial state; phase 2 "
             f"continues with noise drive for T steps and is judged on its second half (first half = burn-in from "
             f"the end of phase 1). Secular decay rate of the fundamental = mean(gamma) = {rates[0]:.4f}; slowest "
             f"mode rate = {rates.min():.4f} (k={int(np.argmin(rates)) + 1}, "
             f"lambda={spec.lam[int(np.argmin(rates))]:.4f}). Energy left after the undriven phase sits in the modes "
             f"listed under dominant_modes_no_drive.")
    return ExperimentResult(
        NAMES["E8_v1"], passed,
        {"fundamental_end_no_drive": end_quiet, "fundamental_max_driven_second_half": driven_max,
         "checks": {"no_drive": bool(ok_quiet), "driven": bool(ok_driven)},
         "fundamental_decay_rate": float(rates[0]), "min_decay_rate": float(rates.min()),
         "dominant_modes_no_drive": dominant},
        notes, {"fundamental_fraction": fig},
        summary=f"no drive end {end_quiet:.4f}; driven max {driven_max:.4f}",
    )


# ---------------------------------------------------------------------------- V1.2 (XON_SIM_GEOMETRY_V1_2.md)
# E9 and the E1 lattice control have their own table so that REGISTRY above stays exactly as it was
# pre-registered for V1 / V1.1. Implementation choices are logged in CHANGELOG_EXPERIMENTS.md.
_LN = np.log
_E9_BAND = "the level with 500 <= N <= 3000 (the largest if two qualify)"

REGISTRY_V1_2: dict[str, Registration] = {
    "E1_lattice": Registration(
        "E1 on the square lattice (control)",
        "E1's statistics on square lattices whose N matches E1's gasket levels (side = round(sqrt(N))). "
        "Reported next to E1 with --include-controls; E1's own criteria are unchanged. Expected: Pearson r "
        "passes (so r alone does not separate the gasket from a lattice) and the plateaus at 3, 5, 6 are absent.",
        {"compares_to": "E1"}, role="negative_control", group="E1"),
    "E9a": Registration(
        "Spectral self-similarity across geometries (V1.2)",
        f"At {_E9_BAND}: gasket, vicsek and S(4, n) (finitely ramified) have degenerate_fraction >= 0.5 AND "
        "plateau_persistence(L-1, L) >= 0.8; carpet (infinitely ramified) and lattice (control) have "
        "degenerate_fraction <= 0.3. Levels of multiplicity >= 3, eigenvalues within 1e-6. Pearson r between "
        "the index-normalized spectra of levels L-2, L-1, L is reported only.",
        {"band": [500, 3000], "multiplicity_min": 3, "tol": 1e-6,
         "finitely_ramified": {"geometries": ["gasket", "vicsek", "sierpinski_p"],
                               "degenerate_fraction_min": 0.5, "plateau_persistence_min": 0.8},
         "not_finitely_ramified": {"geometries": ["carpet", "lattice"], "degenerate_fraction_max": 0.3}}),
    "E9b": Registration(
        "Spectral individuation across geometries (V1.2)",
        f"At {_E9_BAND}: k-way spectral clustering (k = top-level sub-regions: 3 gasket, 5 vicsek, 8 carpet, "
        "p for S(p, n), 3 for the branch-3 tree) on the lowest k Laplacian eigenvectors including the constant; "
        "k-means with 20 restarts; purity = best one-to-one matching of clusters to sub-regions. gasket, vicsek, "
        "S(4, n) and tree (control): purity >= 0.85. carpet: exploratory, no prediction. seam_fraction and the "
        "seam-vs-purity relation across geometries are reported.",
        {"band": [500, 3000], "purity_min": 0.85, "restarts": 20,
         "predicted": ["gasket", "vicsek", "sierpinski_p", "tree"], "exploratory": ["carpet"]}),
    "E9c": Registration(
        "Known dimensions: exact construction check (V1.2)",
        "Exact counts: at every level built up to N <= 400,000 (gasket 0-11, vicsek 0-7, S(4, n) 0-8, carpet 0-6), "
        "the vertex count, the edge count (distinct vertex pairs joined by an edge) and the exact graph diameter "
        "equal the closed forms in docs/geometry_closed_forms.md, written before this check first ran: integer "
        "equality, no tolerance. At the largest level with N <= 50,000: d_w (lazy-walk MSD) and d_s (return "
        "probability) within 0.10 of the reference for gasket and vicsek and 0.15 for carpet (S(4, n) has no "
        "reference), and the Einstein residual |d_s - 2 d_f / d_w| with the theoretical d_f (ln 3 / ln 2, "
        "ln 5 / ln 3, ln 4 / ln 2, ln 8 / ln 3) <= 0.10 for gasket and vicsek and 0.15 for carpet and S(4, n); a "
        "geometry that misses on these is rerun once at the next level (N <= 400,000) and judged there. A geometry "
        "matches when both parts hold. Reported, not judged: ln(N_{L+1} / N_L) / ln(D_{L+1} / D_L) at every level, "
        "counting vertices and counting cells; box-counting d_f (that vertex ratio at the judged level); "
        "mass-radius d_f with uniform (E9c_v2) and deep (E9c_v1) centers; vicsek's mass-radius d_f at levels 4-7 "
        "with 200 deep and 200 uniform centers per level. The earlier registrations stay runnable as E9c_v2 and "
        "E9c_v1.",
        {"exact": {"max_n": 400_000, "closed_forms": "docs/geometry_closed_forms.md",
                   "counts": ["vertices", "edges", "diameter"],
                   "levels": {"gasket": "0-11", "vicsek": "0-7", "sierpinski_p": "0-8", "carpet": "0-6"}},
         "max_n": 50_000, "retry_max_n": 400_000,
         "d_f": {"gasket": _LN(3) / _LN(2), "vicsek": _LN(5) / _LN(3), "sierpinski_p": "ln p / ln 2",
                 "carpet": _LN(8) / _LN(3)},
         "reference": {"gasket": {"d_w": _LN(5) / _LN(2), "d_s": 2 * _LN(3) / _LN(5)},
                       "vicsek": {"d_w": _LN(15) / _LN(3), "d_s": 2 * _LN(5) / _LN(15)},
                       "carpet": {"d_w": 2.10, "d_s": 1.80}},
         "tolerance": {"gasket": {"d_w": 0.10, "d_s": 0.10, "einstein_residual": 0.10},
                       "vicsek": {"d_w": 0.10, "d_s": 0.10, "einstein_residual": 0.10},
                       "carpet": {"d_w": 0.15, "d_s": 0.15, "einstein_residual": 0.15},
                       "sierpinski_p": {"einstein_residual": 0.15}},
         "reported": {"trend": {"geometry": "vicsek", "levels_from": 4, "centers": 200}}},
        reregistered="2026-09-23, twice more by the user's decision (CHANGELOG_EXPERIMENTS.md): estimators had been "
                     "chosen after seeing results, so no estimator is the pass criterion; the ratio criterion "
                     "registered next (never run) ignored known additive offsets in diameter, so the check is exact"),
    # ---- earlier registrations of re-registered V1.2 experiments, kept runnable (run_tests --include-v1) ----
    "E9c_v1": Registration(
        "Known dimensions (as first registered)",
        "At the largest level with N <= 50,000: d_f (mass-radius), d_w (lazy-walk MSD) and d_s (return "
        "probability). gasket and vicsek: each within 0.10 of the reference, einstein_residual |d_s - 2 d_f / d_w| "
        "<= 0.10. carpet: d_f within 0.10, d_w and d_s within 0.15, residual <= 0.15. S(4, n): d_f within 0.10 of "
        "ln 4 / ln 2 = 2, residual <= 0.15. A geometry that fails is rerun once at the next level (N <= 400,000) "
        "and judged there; failing again flags its construction.",
        {"max_n": 50_000, "retry_max_n": 400_000,
         "reference": {"gasket": {"d_f": _LN(3) / _LN(2), "d_w": _LN(5) / _LN(2), "d_s": 2 * _LN(3) / _LN(5)},
                       "vicsek": {"d_f": _LN(5) / _LN(3), "d_w": _LN(15) / _LN(3), "d_s": 2 * _LN(5) / _LN(15)},
                       "carpet": {"d_f": _LN(8) / _LN(3), "d_w": 2.10, "d_s": 1.80},
                       "sierpinski_p": {"d_f": "ln p / ln 2"}},
         "tolerance": {"gasket": {"d_f": 0.10, "d_w": 0.10, "d_s": 0.10, "einstein_residual": 0.10},
                       "vicsek": {"d_f": 0.10, "d_w": 0.10, "d_s": 0.10, "einstein_residual": 0.10},
                       "carpet": {"d_f": 0.10, "d_w": 0.15, "d_s": 0.15, "einstein_residual": 0.15},
                       "sierpinski_p": {"d_f": 0.10, "einstein_residual": 0.15}}},
        role="v1"),
    "E9c_v2": Registration(
        "Known dimensions (re-registration 1)",
        "At the largest level with N <= 50,000: d_f two ways, (1) mass-radius with 200 centers drawn uniformly "
        "from all vertices, M(r) averaging the centers at least r hops from the outer boundary (R_max and the fit "
        "range [R_max / 4, R_max] as first registered), and (2) box-counting across levels, "
        "ln(N_L / N_{L-1}) / ln(diam_L / diam_{L-1}); d_w (lazy-walk MSD) and d_s (return probability). Both d_f "
        "estimates are judged, and the Einstein residual |d_s - 2 d_f / d_w| must hold with each. gasket and "
        "vicsek: d_f, d_w, d_s within 0.10 of the reference, residuals <= 0.10. carpet: d_f within 0.10, d_w and "
        "d_s within 0.15, residuals <= 0.15. S(4, n): d_f within 0.10 of ln 4 / ln 2 = 2, residuals <= 0.15. A "
        "geometry that fails is rerun once at the next level (N <= 400,000) and judged there; failing again flags "
        "its construction. The first registration's d_f (centers at least R_max from the boundary) is reported, "
        "not judged; that protocol stays runnable as E9c_v1.",
        {"max_n": 50_000, "retry_max_n": 400_000,
         "reference": {"gasket": {"d_f": _LN(3) / _LN(2), "d_w": _LN(5) / _LN(2), "d_s": 2 * _LN(3) / _LN(5)},
                       "vicsek": {"d_f": _LN(5) / _LN(3), "d_w": _LN(15) / _LN(3), "d_s": 2 * _LN(5) / _LN(15)},
                       "carpet": {"d_f": _LN(8) / _LN(3), "d_w": 2.10, "d_s": 1.80},
                       "sierpinski_p": {"d_f": "ln p / ln 2"}},
         "tolerance": {"gasket": {"d_f": 0.10, "d_f_box": 0.10, "d_w": 0.10, "d_s": 0.10,
                                  "einstein_residual": 0.10, "einstein_residual_box": 0.10},
                       "vicsek": {"d_f": 0.10, "d_f_box": 0.10, "d_w": 0.10, "d_s": 0.10,
                                  "einstein_residual": 0.10, "einstein_residual_box": 0.10},
                       "carpet": {"d_f": 0.10, "d_f_box": 0.10, "d_w": 0.15, "d_s": 0.15,
                                  "einstein_residual": 0.15, "einstein_residual_box": 0.15},
                       "sierpinski_p": {"d_f": 0.10, "d_f_box": 0.10,
                                        "einstein_residual": 0.15, "einstein_residual_box": 0.15}}},
        role="v1",
        reregistered="2026-09-23, after the first V1.2 run, by the user's decision: the first registration's "
                     "mass-radius centers all sat around vicsek's central cross, where box-counting on the same "
                     "graphs gave 1.466 against 1.465"),
}
V1_2_PAIRS = {"E9c": ("E9c_v2", "E9c_v1")}   # re-registered V1.2 id -> its preserved registrations, newest first
EXPERIMENTS_V1_2: dict[str, Callable[[XonConfig, np.random.Generator], ExperimentResult]] = {}


def experiment_v1_2(fn):
    """``experiment`` for REGISTRY_V1_2."""
    eid = fn.__name__
    if eid not in REGISTRY_V1_2:
        raise KeyError(f"{eid} is not pre-registered: add its name, criterion and thresholds to REGISTRY_V1_2")
    EXPERIMENTS_V1_2[eid] = fn
    return fn


def registration(eid: str) -> Registration | None:
    return REGISTRY.get(eid) or REGISTRY_V1_2.get(eid)


def geometry_ids() -> list[str]:
    return [eid for eid, r in REGISTRY_V1_2.items() if eid.startswith("E9") and r.role != "v1"]


def control_ids() -> list[str]:
    return [eid for eid, r in REGISTRY_V1_2.items() if r.role == "negative_control"]


def preserved_v1_2_ids() -> list[str]:
    """Earlier registrations of re-registered V1.2 experiments (E9c_v1, E9c_v2); they run with the V1 protocols."""
    return [eid for eid, r in REGISTRY_V1_2.items() if r.role == "v1"]


def all_experiment_ids() -> list[str]:
    return list(EXPERIMENTS) + list(EXPERIMENTS_V1_2)


def suite_ids(include_v1: bool = False, include_controls: bool = False) -> list[str]:
    """The CLI's default run: the V1.1 experiments (controls right after the experiment they check), E9, then the
    preserved protocols (V1, and the earlier registrations of V1.2 experiments) with include_v1."""
    ids = []
    for eid in default_ids():
        ids.append(eid)
        ids += [c for c in control_ids() if include_controls and REGISTRY_V1_2[c].group == eid]
    return ids + geometry_ids() + (v1_ids() + preserved_v1_2_ids() if include_v1 else [])


_E9C_V1_KEYS = {"d_f": "d_f_deep", "einstein_residual": "einstein_residual_deep"}   # E9c_v1 threshold -> row key
E9C_EXACT = ("vertices", "edges", "diameter")
E9C_DIMENSIONS = ("d_w", "d_s", "einstein_residual")     # E9c's judged estimates; a miss on these is retried


def _e9c_prediction(name: str, row: dict, cfg: XonConfig) -> tuple[bool | None, str]:
    """E9c: the exact counts at every level of row["structure"], then d_w, d_s and the residual with the
    theoretical d_f at the row's level."""
    th = REGISTRY_V1_2["E9c"].thresholds
    ref, tol = th["reference"].get(name, {}), th["tolerance"].get(name)
    if tol is None:
        return None, "no prediction"
    d_f = float(_LN(cfg.e9_sierpinski_p) / _LN(2)) if name == "sierpinski_p" else th["d_f"][name]
    row["d_f_theory"] = d_f
    row["einstein_residual_theory"] = einstein_residual(row["d_s"], d_f, row["d_w"])
    levels = [s["level"] for s in row["structure"]]
    checks = {k: all(s["matches"][k] for s in row["structure"]) for k in E9C_EXACT}
    checks.update({k: abs(row[k] - ref[k]) <= tol[k] for k in ("d_w", "d_s") if k in tol})
    checks["einstein_residual"] = row["einstein_residual_theory"] <= tol["einstein_residual"]
    row["reference"], row["checks"] = dict(ref), {k: bool(v) for k, v in checks.items()}
    span = f"levels {levels[0]}-{levels[-1]}" if len(levels) > 1 else f"level {levels[0]}"
    return bool(all(checks.values())), "; ".join(
        [f"N, E, D = closed forms at {span}"] + [f"{k} = {ref[k]:.3f} +- {tol[k]}" for k in ("d_w", "d_s") if k in tol]
        + [f"residual (d_f = {d_f:.3f}) <= {tol['einstein_residual']}"])


def e9_prediction(eid: str, name: str, row: dict, cfg: XonConfig) -> tuple[bool | None, str]:
    """(matches, predicted) for one geometry row of E9a / E9b / E9c and its earlier registrations; matches is None
    when exploratory."""
    if eid == "E9c":
        return _e9c_prediction(name, row, cfg)
    th = REGISTRY_V1_2[eid].thresholds
    if eid == "E9a":
        fin, other = th["finitely_ramified"], th["not_finitely_ramified"]
        if name in fin["geometries"]:
            ok = (row["degenerate_fraction"] >= fin["degenerate_fraction_min"]
                  and row["plateau_persistence"] >= fin["plateau_persistence_min"])
            return bool(ok), (f"degenerate_fraction >= {fin['degenerate_fraction_min']}, "
                              f"plateau_persistence >= {fin['plateau_persistence_min']}")
        if name in other["geometries"]:
            return bool(row["degenerate_fraction"] <= other["degenerate_fraction_max"]), \
                f"degenerate_fraction <= {other['degenerate_fraction_max']}"
        return None, "no prediction"
    if eid == "E9b":
        if name in th["predicted"]:
            return bool(row["purity"] >= th["purity_min"]), f"purity >= {th['purity_min']}"
        return None, "exploratory"
    ref, tol = dict(th["reference"].get(name, {})), th["tolerance"].get(name)
    if tol is None:
        return None, "no reference"
    if name == "sierpinski_p":
        ref["d_f"] = float(_LN(cfg.e9_sierpinski_p) / _LN(2))
    value = (lambda k: row[_E9C_V1_KEYS.get(k, k)]) if eid == "E9c_v1" else (lambda k: row[k])
    target = lambda k: ref["d_f" if k == "d_f_box" else k]
    residuals = [k for k in tol if k.startswith("einstein_residual")]
    checks = {k: abs(value(k) - target(k)) <= t for k, t in tol.items() if k not in residuals}
    checks.update({k: value(k) <= tol[k] for k in residuals})
    row["reference"], row["checks"] = ref, {k: bool(v) for k, v in checks.items()}
    return bool(all(checks.values())), "; ".join(
        [f"{k} = {target(k):.3f} +- {t}" for k, t in tol.items() if k not in residuals]
        + [f"{k.replace('einstein_residual', 'residual')} <= {tol[k]}" for k in residuals])


def _e9_geometries(cfg: XonConfig, eligible) -> list[str]:
    return [n for n in cfg.e9_geometries if n in eligible]


def _e9_result(eid: str, cfg: XonConfig, rows: dict, figures: dict, extra: dict | None = None) -> ExperimentResult:
    judged = {n: r["matches"] for n, r in rows.items() if r["matches"] is not None}
    passed = all(judged.values()) if judged else None
    misses = [geometry_label(n, cfg) for n, ok in judged.items() if not ok]
    notes = (f"{len(judged) - len(misses)} of {len(judged)} predicted geometries match"
             + (f"; mismatches: {', '.join(misses)}" if misses else "") + f". {E9D_STATUS}")
    return ExperimentResult(REGISTRY_V1_2[eid].name, passed, {"rows": rows, **(extra or {})}, notes, figures)


@experiment_v1_2
def E1_lattice(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    th = THRESHOLDS["E1"]
    grid = (np.arange(cfg.e1_resample) + 0.5) / cfg.e1_resample
    sides = [int(round(np.sqrt((3 ** (level + 1) + 3) // 2))) for level in cfg.e1_levels]
    resampled, curves, plateau = {}, [], {}
    for side in sides:
        g = build_graph(cfg.replace(lattice_side=side), 0, "lattice")
        spec = get_spectrum(g, cfg)
        resampled[side] = np.interp(grid, np.arange(g.n()) / g.n(), spec.lam)
        curves.append((f"side {side} (N={g.n()})", spec.lam))
        plateau[side] = {str(v): multiplicity_at(spec, v) / g.n() for v in th["plateaus"]}
    rs = {f"{a}-{b}": float(stats.pearsonr(resampled[a], resampled[b])[0]) for a, b in zip(sides, sides[1:])}
    ok_r = all(r >= th["pearson_r_min"] for r in rs.values())
    ok_p = all(f > th["plateau_frac_min"] for lv in plateau.values() for f in lv.values())
    min_frac = min(f for lv in plateau.values() for f in lv.values())
    by_side = "; ".join(f"side {s} " + ", ".join(f"{f:.3f}" for f in lv.values()) for s, lv in plateau.items())
    return ExperimentResult(
        REGISTRY_V1_2["E1_lattice"].name, ok_r and ok_p,
        {"sides": sides, "pearson_r": rs, "plateau_fraction": {str(s): p for s, p in plateau.items()},
         "pearson_r_criterion_passes": ok_r, "plateau_criterion_passes": ok_p},
        f"On the lattice E1's Pearson-r criterion {'also passes' if ok_r else 'fails'} "
        f"(r = {', '.join(f'{r:.4f}' for r in rs.values())})"
        + (", so r alone does not separate the gasket from a lattice" if ok_r else "")
        + f"; the plateau criterion {'passes' if ok_p else 'fails'} (smallest plateau fraction {min_frac:.3f}; "
        f"fractions at lambda = {', '.join(f'{v:g}' for v in th['plateaus'])}: {by_side}).",
        {"staircase": staircase_figure(curves, "E1 control: lattice spectra vs index/N")},
        summary=f"r = {', '.join(f'{r:.4f}' for r in rs.values())}; min plateau frac {min_frac:.3f}",
    )


@experiment_v1_2
def E9a(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    th = REGISTRY_V1_2["E9a"].thresholds
    rows, figures = {}, {}
    for name in _e9_geometries(cfg, th["finitely_ramified"]["geometries"] + th["not_finitely_ramified"]["geometries"]):
        level, in_band = band_level(name, cfg, *cfg.e9_band)
        row = spectral_row(name, cfg, level)
        figures[f"staircase_{name}"] = staircase(name, cfg, row)
        row = strip_curves(row)
        row["in_band"] = in_band
        row["matches"], row["predicted"] = e9_prediction("E9a", name, row, cfg)
        rows[name] = row
    res = _e9_result("E9a", cfg, rows, figures)
    res.summary = "; ".join(f"{geometry_label(n, cfg)} df {r['degenerate_fraction']:.2f} pp "
                            f"{r['plateau_persistence']:.2f}{'' if r['matches'] else ' (miss)'}"
                            for n, r in rows.items())
    return res


@experiment_v1_2
def E9b(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    th = REGISTRY_V1_2["E9b"].thresholds
    base = int(rng.integers(2 ** 32))
    run_cfg = cfg.replace(cluster_restarts=int(th["restarts"]))
    rows, figures = {}, {}
    for name in _e9_geometries(cfg, th["predicted"] + th["exploratory"]):
        level, in_band = band_level(name, cfg, *cfg.e9_band)
        row = clustering_row(name, run_cfg, level, geometry_rng(base, name))
        figures[f"clusters_{name}"] = cluster_overlay(name, cfg, row)
        row = strip_curves(row)
        row["in_band"] = in_band
        row["matches"], row["predicted"] = e9_prediction("E9b", name, row, cfg)
        rows[name] = row
    extra = {}
    if len(rows) >= 3:
        rho = stats.spearmanr([r["seam_fraction"] for r in rows.values()], [r["purity"] for r in rows.values()])
        extra["seam_purity_spearman"] = float(rho.statistic) if np.isfinite(rho.statistic) else float("nan")
    if len(rows) >= 2:
        figures["seam_vs_purity"] = seam_purity_figure(rows, cfg)
    res = _e9_result("E9b", cfg, rows, figures, extra)
    res.summary = "; ".join(f"{geometry_label(n, cfg)} purity {r['purity']:.2f} seam {r['seam_fraction']:.3f}"
                            f"{'' if r['matches'] is not False else ' (miss)'}" for n, r in rows.items())
    return res


def _e9c(eid: str, cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    """E9c_v1 and E9c_v2, E9c's earlier registrations: the same rows and retry rule, judged on different d_f.

    Each geometry's stream drives the first registration's estimators in their original order, so E9c_v1
    reproduces the first V1.2 run; the uniform mass-radius centers come from a stream of their own.
    """
    th = REGISTRY_V1_2[eid].thresholds
    base = int(rng.integers(2 ** 32))
    rows, curves = {}, {}
    for name in _e9_geometries(cfg, list(th["tolerance"])):
        grng, crng = geometry_rng(base, name), geometry_rng(base, f"{name}:uniform centers")
        row = dimension_row(name, cfg, max_level(name, cfg, cfg.e9c_max_n), grng, crng)
        row["matches"], row["predicted"] = e9_prediction(eid, name, row, cfg)
        if not row["matches"] and row["n_next_level"] <= cfg.e9c_retry_max_n:
            first = strip_curves(row)
            row = dimension_row(name, cfg, first["level"] + 1, grng, crng)
            row["matches"], row["predicted"] = e9_prediction(eid, name, row, cfg)
            row["retried"] = first
        curves[name] = row
        rows[name] = strip_curves(row)
    v1 = eid == "E9c_v1"
    res = _e9_result(eid, cfg, rows, dimension_figures(curves, cfg, eid, deep=v1) if curves else {})
    for n, r in rows.items():
        if r["matches"] is False:
            where = (f"at level {r['retried']['level']} and again at level {r['level']}" if r.get("retried")
                     else f"at level {r['level']}")
            res.notes += (f" {geometry_label(n, cfg)} fails on {', '.join(k for k, ok in r['checks'].items() if not ok)}"
                          f" {where}; its box-counting d_f is {r['d_f_box']:.3f} (mass-radius "
                          f"{r['d_f_deep' if v1 else 'd_f']:.3f}).")
    if v1:
        res.summary = "; ".join(f"{geometry_label(n, cfg)} df {r['d_f_deep']:.2f} dw {r['d_w']:.2f} ds {r['d_s']:.2f}"
                                f"{'' if r['matches'] else ' (miss)'}" for n, r in rows.items())
    else:
        if rows:
            res.notes += (" First registration's mass-radius d_f (centers at least R_max from the boundary; reported, "
                          "judged by E9c_v1): " + ", ".join(f"{geometry_label(n, cfg)} {r['d_f_deep']:.3f}"
                                                           for n, r in rows.items()) + ".")
        res.summary = "; ".join(f"{geometry_label(n, cfg)} df {r['d_f']:.2f} (box {r['d_f_box']:.2f}) dw {r['d_w']:.2f} "
                                f"ds {r['d_s']:.2f}{'' if r['matches'] else ' (miss)'}" for n, r in rows.items())
    return res


def _e9c_row(name: str, cfg: XonConfig, level: int, grng, crng, structure: list[dict]) -> dict:
    row = attach_structure(dimension_row(name, cfg, level, grng, crng), structure)
    row["matches"], row["predicted"] = e9_prediction("E9c", name, row, cfg)
    return row


@experiment_v1_2
def E9c(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    """Exact counts at every level up to e9c_retry_max_n, and d_w, d_s and the residual with the theoretical d_f.

    The streams are E9c_v2's, so the estimates at the same level reproduce its numbers; the exact counts use no
    randomness, and vicsek's mass-radius trend has a stream per level and estimator.
    """
    th = REGISTRY_V1_2["E9c"].thresholds
    base = int(rng.integers(2 ** 32))
    rows, curves, structures = {}, {}, {}
    for name in _e9_geometries(cfg, list(th["tolerance"])):
        structure = structures[name] = structure_rows(name, cfg, range(max_level(name, cfg, cfg.e9c_retry_max_n) + 1))
        grng, crng = geometry_rng(base, name), geometry_rng(base, f"{name}:uniform centers")
        row = _e9c_row(name, cfg, max_level(name, cfg, cfg.e9c_max_n), grng, crng, structure)
        missed = not all(row["checks"][k] for k in E9C_DIMENSIONS if k in row["checks"])
        if missed and row["n_next_level"] <= cfg.e9c_retry_max_n:
            first = {k: v for k, v in strip_curves(row).items() if k != "structure"}
            row = _e9c_row(name, cfg, first["level"] + 1, grng, crng, structure)
            row["retried"] = first
        curves[name] = row
        rows[name] = strip_curves(row)
    figures = {}
    if rows:
        figures["ratio_sequence"] = ratio_figure(structures, {n: r["d_f_theory"] for n, r in rows.items()}, cfg)
    trend_name = th["reported"]["trend"]["geometry"]
    trend = []
    if trend_name in rows:
        top = max_level(trend_name, cfg, cfg.e9c_retry_max_n)
        trend = mass_trend(trend_name, cfg, range(min(int(cfg.e9c_trend_from_level), top), top + 1), base,
                           int(cfg.e9c_trend_centers))
        figures["trend"] = trend_figure(trend, trend_name, rows[trend_name]["d_f_theory"], cfg)
    if curves:
        figures.update(dimension_figures(curves, cfg, "E9c"))
    res = _e9_result("E9c", cfg, rows, figures, {"trend": {"geometry": trend_name, "levels": trend}} if trend else None)
    for n, r in rows.items():
        label = geometry_label(n, cfg)
        res.notes += f" {label}: N, E, D vs closed forms: {exact_summary(r)}."
        missed = [k for k in E9C_DIMENSIONS if k in r["checks"] and not r["checks"][k]]
        if missed:
            where = (f"at level {r['retried']['level']} and again at level {r['level']}" if r.get("retried")
                     else f"at level {r['level']}")
            res.notes += f" {label} misses on {', '.join(missed)} {where}."
    if rows:
        res.notes += (" Reported only: the vertex ratio at the top level, "
                      + ", ".join(f"{geometry_label(n, cfg)} {structures[n][-1]['ratio_vertices']:.3f} "
                                  f"(level {structures[n][-1]['level']}, theory {r['d_f_theory']:.3f})"
                                  for n, r in rows.items())
                      + "; mass-radius d_f at the judged level, uniform (E9c_v2) / deep (E9c_v1) centers: "
                      + ", ".join(f"{geometry_label(n, cfg)} {r['d_f']:.3f} / {r['d_f_deep']:.3f}"
                                  for n, r in rows.items()) + ".")
    if trend:
        res.notes += (f" {geometry_label(trend_name, cfg)} mass-radius d_f by level, deep / uniform centers: "
                      + ", ".join(f"level {t['level']} {t['d_f_deep']:.3f} / {t['d_f_uniform']:.3f}" for t in trend)
                      + ".")
    res.summary = "; ".join(
        f"{geometry_label(n, cfg)} exact {'ok' if all(r['checks'][k] for k in E9C_EXACT) else 'MISS'} "
        f"L0-{r['structure'][-1]['level']}, dw {r['d_w']:.2f} ds {r['d_s']:.2f} res {r['einstein_residual_theory']:.3f}"
        f"{'' if r['matches'] else ' (miss)'}" for n, r in rows.items())
    return res


@experiment_v1_2
def E9c_v1(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    return _e9c("E9c_v1", cfg, rng)


@experiment_v1_2
def E9c_v2(cfg: XonConfig, rng: np.random.Generator) -> ExperimentResult:
    return _e9c("E9c_v2", cfg, rng)


# ---------------------------------------------------------------------------- runner
_order = {eid: i for i, eid in enumerate(REGISTRY)}
_items = sorted(EXPERIMENTS.items(), key=lambda kv: _order[kv[0]])
EXPERIMENTS.clear()
EXPERIMENTS.update(_items)


def experiment_rng(eid: str, seed: int) -> np.random.Generator:
    """Per-experiment stream, independent of which other experiments run.

    E#_v1 (and E9c_v2) share the stream of the experiment they preserve, so they reproduce its numbers;
    lettered variants (E4a, E8b) get streams of their own.
    """
    m = re.fullmatch(r"E(\d+)([a-z]?)(?:_v\d+)?", eid)
    if m is None:
        entropy = [int(seed), *eid.encode()]
    else:
        entropy = [int(seed), int(m[1])] + ([ord(m[2])] if m[2] else [])
    return np.random.default_rng(np.random.SeedSequence(entropy))


def run_experiment(eid: str, cfg: XonConfig | None = None, seed: int | None = None) -> ExperimentResult:
    cfg = cfg or XonConfig()
    seed = cfg.seed if seed is None else seed
    reg = REGISTRY.get(eid) or REGISTRY_V1_2.get(eid)
    t0 = time.time()
    try:
        fn = EXPERIMENTS[eid] if eid in EXPERIMENTS else EXPERIMENTS_V1_2[eid]
        res = fn(cfg, experiment_rng(eid, seed))
    except Exception:
        res = ExperimentResult(reg.name if reg else eid, None, {}, traceback.format_exc(), status="error",
                               summary="raised an exception")
    res.id = eid
    res.runtime_s = time.time() - t0
    res.criterion = reg.criterion if reg else ""
    res.thresholds = reg.thresholds if reg else {}
    res.role = reg.role if reg else "gate"
    res.group = (reg.group or eid) if reg else eid
    if res.role == "negative_control" and res.status in ("passed", "failed"):
        res.status = "negative_control"
    return res
