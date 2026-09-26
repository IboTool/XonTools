"""XON SIM - Streamlit UI (spec section 4).

    streamlit run app.py          (or: python -m streamlit run app.py)

All state lives in st.session_state: one xon.sandbox.Sandbox plus UI selections. The spectrum is
cached with st.cache_resource keyed by the graph version, so it is recomputed only after growth;
switching a metric setting such as the harmonicity coherence factor only re-reads stored trace
components.
"""
from __future__ import annotations

import json
import mimetypes
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import plotly
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
import streamlit.components.v1 as components
from streamlit.errors import StreamlitInvalidLayoutContextError

from xon import __version__
from xon.config import (COHERENCE_FACTORS, DRIVES, ENGINE_VERSIONS, LLM_CAPABILITIES, LLM_MODELS, METRIC_SCOPES,
                        OMEGA_MODES, OSC_DRIVES, XonConfig)
from xon.dynamics import DYNAMICS, WaveDynamics
from xon.experiments import (E4_VARIANTS, REGISTRY_V1_2, V1_2_PAIRS, V1_PAIRS, control_ids, default_ids,
                             e9_prediction, gate_verdicts, geometry_ids, preserved_v1_2_ids, registration,
                             run_experiment, suite_ids, v1_ids)
from xon.export import export_run, to_jsonable
from xon.geometry import (CLOSED_FORM_GEOMETRIES, E9C_COLUMNS, E9D_STATUS, GEOMETRIES, attach_structure,
                          cluster_overlay, clustering_row, dimension_figures, dimension_row, e9_report, exact_summary,
                          geometry_label, geometry_rng, matched_level, spectral_row, staircase, strip_curves,
                          structure_rows)
from xon.growth import RULE_GROUPS, RULES
from xon.llm.client import API_KEY_ENV, LLM, api_key_is_set
from xon.llm.engine import analysis_to_dict, analyze_text, rescored, with_evidence
from xon.llm.plots import UNANCHORED_NOTE, claim_graph_figure, entity_figures
from xon.metrics import (METRICS, degeneracy, fit_exponential, fit_powerlaw, frac_localized,
                         modal_decomposition, partition_purity, spectral_gap_ratio)
from xon.plots import depth_energy_figure, graph_figure, stacked_figure, staircase_figure
from xon.problems import MaxCutProblem, max_cut_brute_force, oscillator_solve
from xon.sandbox import SHEAF_INITS, Sandbox
from xon.spectrum import degenerate_groups, get_spectrum

st.set_page_config(page_title="XON SIM", layout="wide")
ss = st.session_state
D = XonConfig()
TABS = ("Graph", "Spectrum", "Traces", "Depth", "Modes", "Sheaf", "Constraints", "Test Suite")
MODES = ("Sandbox", "Test Suite", "Geometry Compare", "Consistency")
DRY_RUN_NOTE = (f"LLM dry-run: {API_KEY_ENV} is not set in the environment, so the Consistency mode makes no API "
                "calls and answers only from recorded fixtures.")
OVERLAYS = ("State", "Eigenmode", "Fiedler partition", "Depth")
TRACE_PLOT_POINTS = 2000
STATUS_LABEL = {"passed": "PASS", "failed": "FAIL", "not_implemented": "NOT IMPLEMENTED", "error": "ERROR",
                "negative_control": "NEGATIVE CONTROL"}
ROLE_LABEL = {"gate": "gate", "negative_control": "negative control", "v1": "preserved protocol"}
FACTOR_COLORS = dict(zip(COHERENCE_FACTORS, ("#1f77b4", "#2ca02c", "#9467bd")))
WAVES = ("wave", "wave_v1")


# ------------------------------------------------------------------------------------------ spectrum
@st.cache_resource(max_entries=8, show_spinner="Computing the Laplacian spectrum ...")
def _cached_spectrum(content_key: str, version: int, k: int | None, _g, _cfg):
    return get_spectrum(_g, _cfg, k)


def spectrum_fn(g, cfg: XonConfig):
    k = None if g.n() <= cfg.dense_max else int(cfg.k_modes)
    return _cached_spectrum(g.content_key(), g.version, k, g, cfg)


@st.cache_resource(max_entries=16)
def _maxcut(n: int, seed: int) -> MaxCutProblem:
    return MaxCutProblem.random_regular(n, 3, seed)


# ------------------------------------------------------------------------------------------ helpers
def flash(kind: str, text: str) -> None:
    ss.setdefault("flash", []).append((kind, text))


def show_flash() -> None:
    for kind, text in ss.pop("flash", []):
        if kind in ("info", "success"):
            st.toast(text)
        else:
            getattr(st, kind)(text)


def _default(key: str, value) -> None:
    if key not in ss:
        ss[key] = value


def num(container, label: str, field: str, lo, hi, step, fmt: str | None = None, help: str | None = None):
    key = f"cfg_{field}"
    _default(key, getattr(D, field))
    return container.number_input(label, min_value=lo, max_value=hi, step=step, format=fmt, key=key, help=help)


def select(container, label: str, field: str, options, help: str | None = None, **kw):
    key = f"cfg_{field}"
    _default(key, getattr(D, field))
    return container.selectbox(label, options, key=key, help=help, **kw)


def _selection(key: str, kind: str) -> list:
    try:
        return list(ss[key]["selection"][kind])
    except (KeyError, TypeError, AttributeError):
        return []


def _fmt_thresholds(th: dict) -> str:
    return "; ".join(f"{k} = {v}" for k, v in th.items())


def _toggle_run() -> None:
    ss.running = not ss.get("running", False)


def consume_selections(sb: Sandbox) -> bool:
    """Apply chart / table clicks before any widget is drawn; returns True if a selection was applied."""
    changed = False
    click = ss.get("graph_live")
    if isinstance(click, dict) and click != ss.get("_graph_click"):
        ss["_graph_click"] = click
        cd = click.get("customdata")
        v = int(cd[0] if isinstance(cd, (list, tuple)) else cd) if cd is not None else -1
        if 0 <= v < sb.g.n():
            ss["ui_probe_vertex"] = v
            flash("info", f"Probe target set to vertex {v}.")
            changed = True
    rows = tuple(_selection("modes_table", "rows"))
    if rows and rows != ss.get("_modes_sel"):
        ss["ui_paint_k"] = int(rows[0]) + 1
        ss["ui_overlay"] = "Eigenmode"
        flash("info", f"Painting mode k = {rows[0] + 1} on the Graph tab.")
        changed = True
    ss["_modes_sel"] = rows
    return changed


# ------------------------------------------------------------------------------------------ live charts
LIVE_TEMPLATE = pio.templates["plotly_white"].to_plotly_json()
# elements inside containers keyed live_* are redrawn every frame; Streamlit's stale fade would dim them
# whenever a frame takes longer than 0.5 s
LIVE_CSS = ('<style>[class*="st-key-live_"] [data-stale="true"] '
            '{opacity: 1 !important; transition: none !important;}</style>')


@st.cache_resource(show_spinner=False)
def _live_chart_component():
    # the frontend loads plotly.min.js from its own folder; some Windows registries map .js to text/plain,
    # which browsers refuse to execute
    mimetypes.add_type("text/javascript", ".js")
    root = Path(tempfile.gettempdir()) / f"xon_live_chart-plotly-{plotly.__version__}"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("live_chart") / "index.html", root / "index.html")
    js_src, js = Path(plotly.__file__).parent / "package_data" / "plotly.min.js", root / "plotly.min.js"
    if not js.exists() or js.stat().st_size != js_src.stat().st_size:
        shutil.copyfile(js_src, js)
    return components.declare_component("live_chart", path=str(root))


def live_chart(fig: go.Figure, key: str, **config):
    """Draw ``fig`` in a chart that stays mounted and is updated in place with Plotly.react.

    st.plotly_chart derives its element id from the figure, so every new figure remounts the chart, which
    flashes when the figure changes every frame. Returns the last clicked point, {"customdata", "t"}, or None.
    """
    spec = fig.to_dict()
    spec["layout"]["template"] = LIVE_TEMPLATE
    return _live_chart_component()(spec=pio.to_json(spec, validate=False),
                                   height=int(spec["layout"].get("height") or 450),
                                   config=config, key=key, default=None)


# ------------------------------------------------------------------------------------------ sidebar
def omega_panel(bar, v: dict) -> None:
    v["omega_mode"] = select(bar, "Natural frequencies ω_i", "omega_mode", OMEGA_MODES)
    c1, c2 = bar.columns(2)
    v["omega0"] = num(c1, "ω₀", "omega0", -100.0, 100.0, 0.1)
    if v["omega_mode"] == "by_depth":
        v["delta_omega"] = num(c2, "Δω", "delta_omega", -100.0, 100.0, 0.1, help="ω_i = ω₀ + Δω · depth_i / d_max")
    elif v["omega_mode"] == "random":
        v["omega_sigma"] = num(c2, "σ_ω", "omega_sigma", 0.0, 100.0, 0.05,
                               help="ω_i = ω₀ + σ_ω · N(0, 1), fixed per vertex")


def sidebar(sb: Sandbox):
    bar = st.sidebar
    bar.title("XON SIM")
    bar.caption(f"v{__version__}. Tests whether the model's claims co-occur (internal coherence), "
                "not whether the model is true of the world.")
    mode = bar.radio("Mode", MODES, horizontal=True, key="ui_mode")
    if not api_key_is_set():
        bar.info(DRY_RUN_NOTE)
    if mode == "Consistency":
        llm_sidebar(bar)
    v: dict = {}

    bar.subheader("Graph")
    v["growth_rule"] = select(bar, "Growth rule", "growth_rule", tuple(RULES))
    groups: dict[str, list[str]] = {}
    for name in RULES:
        groups.setdefault(RULE_GROUPS.get(name, "Other"), []).append(name)
    bar.caption(" · ".join(f"{group}: {', '.join(names)}" for group, names in groups.items()))
    c1, c2 = bar.columns(2)
    v["simplex_dim"] = num(c1, "simplex_dim", "simplex_dim", 2, 8, 1, help="simplex / adaptive rules (2 = gasket)")
    v["seed"] = num(c2, "Seed", "seed", 0, 2 ** 31 - 1, 1)
    c1, c2 = bar.columns(2)
    v["target_level"] = num(c1, "Target level", "target_level", 0, 20, 1, help="growth stops at this level")
    v["max_vertices"] = num(c2, "Max vertices", "max_vertices", 3, 5_000_000, 1000)
    c1, c2 = bar.columns(2)
    v["refine_threshold"] = num(c1, "refine_threshold", "refine_threshold", 0.0, 100.0, 0.1, help="adaptive rule")
    v["refine_floor"] = num(c2, "refine_floor", "refine_floor", 0.0, 1.0, 0.01, help="adaptive rule")
    c1, c2, c3 = bar.columns(3)
    v["branch"] = num(c1, "Tree branch", "branch", 1, 10, 1, help="tree rule")
    v["lattice_side"] = num(c2, "Lattice side", "lattice_side", 2, 1000, 1, help="lattice control")
    v["sierpinski_p"] = num(c3, "p of S(p, n)", "sierpinski_p", 3, 12, 1, help="sierpinski_p rule")

    bar.subheader("Dynamics")

    def available(name: str) -> bool:
        return getattr(DYNAMICS[name], "available", True)

    dyn = select(bar, "Dynamics", "dynamics", tuple(DYNAMICS),
                 format_func=lambda d: d if available(d) else f"{d} (unavailable)")
    if not available(dyn):
        bar.warning(f"{DYNAMICS[dyn].__name__} is registered but not available. "
                    f"The current dynamics ({sb.cfg.dynamics}) stays active.")
        dyn = sb.cfg.dynamics
    v["dynamics"] = dyn
    c1, c2 = bar.columns(2)
    v["c"] = num(c1, "c", "c", 0.0, 10.0, 0.1)
    v["dt"] = num(c2, "dt", "dt", 0.0001, 1.0, 0.005, fmt="%.4f", help="capped automatically for stability")
    if dyn == "wave":
        c1, c2 = bar.columns(2)
        v["alpha"] = num(c1, "α (uniform)", "alpha", 0.0, 10.0, 0.005, fmt="%.4f")
        v["beta"] = num(c2, "β (spectral)", "beta", 0.0, 10.0, 0.005, fmt="%.4f", help="mode k decays at α + βλ_k")
        _default("cfg_sink", D.sink)
        v["sink"] = bar.toggle("Depth sink Γ_sink", key="cfg_sink",
                               help="γ_s on vertices with depth ≤ d_max − D_sink; refused unless γ_s ≤ 0.1·β·λ₂")
        if v["sink"]:
            c1, c2 = bar.columns(2)
            v["sink_gamma"] = num(c1, "γ_s", "sink_gamma", 0.0, 10.0, 1e-5, fmt="%.3e")
            v["sink_depth"] = num(c2, "D_sink", "sink_depth", 0, 50, 1)
            bound = WaveDynamics.sink_bound(D.replace(beta=v["beta"]), sb.spec)
            show = bar.caption if v["sink_gamma"] <= bound * (1 + 1e-9) else bar.error
            show(f"Allowed on this graph: γ_s ≤ 0.1·β·λ₂ = {bound:.4g}")
    elif dyn == "wave_v1":
        c1, c2, c3 = bar.columns(3)
        v["gamma0"] = num(c1, "γ0", "gamma0", 0.0, 10.0, 0.01)
        v["gamma1"] = num(c2, "γ1", "gamma1", 0.0, 10.0, 0.1)
        v["damping_p"] = num(c3, "p", "damping_p", 0.05, 10.0, 0.1)
    elif dyn == "stuart_landau":
        c1, c2 = bar.columns(2)
        v["sl_mu"] = num(c1, "μ", "sl_mu", -10.0, 10.0, 0.1, help="limit-cycle amplitude √μ (μ ≤ 0: no limit cycle)")
        v["sl_sigma"] = num(c2, "σ (noise)", "sl_sigma", 0.0, 10.0, 0.01, help="noise drive at the frontier")
        c1, c2 = bar.columns(2)
        v["sl_alpha"] = num(c1, "α", "sl_alpha", 0.0, 10.0, 0.005, fmt="%.4f")
        v["sl_beta"] = num(c2, "β", "sl_beta", 0.0, 10.0, 0.005, fmt="%.4f", help="dissipative coupling through L")
        omega_panel(bar, v)
    elif dyn == "oscillator":
        c1, c2, c3 = bar.columns(3)
        v["osc_K"] = num(c1, "K", "osc_K", -10.0, 10.0, 0.1)
        v["osc_Ks"] = num(c2, "K_s", "osc_Ks", 0.0, 10.0, 0.1, help="sub-harmonic locking −K_s sin 2θ")
        v["osc_sigma"] = num(c3, "σ", "osc_sigma", 0.0, 10.0, 0.01,
                             help="phase noise: frontier when drive = noise, else every vertex")
        omega_panel(bar, v)
    drives = DRIVES if dyn in WAVES else OSC_DRIVES
    if ss.get("cfg_drive") not in drives:
        ss["cfg_drive"] = drives[0]
    v["drive"] = select(bar, "Drive type", "drive", drives,
                        help="noise and tone act on frontier vertices; probe = injections from the Probe button only")
    if dyn in WAVES:
        c1, c2 = bar.columns(2)
        v["drive_amp"] = num(c1, "drive_amp", "drive_amp", 0.0, 100.0, 0.1)
        v["drive_mode"] = num(c2, "Drive mode k", "drive_mode", 1, 100_000, 1, help="1-based mode index (tone drive)")

    bar.subheader("Metrics")
    v["harmonicity_coherence"] = select(bar, "Harmonicity coherence factor", "harmonicity_coherence",
                                        COHERENCE_FACTORS)
    c1, c2 = bar.columns(2)
    v["k_modes"] = num(c1, "K modes (sparse)", "k_modes", 4, 2000, 4, help=f"used when N > {D.dense_max:,}")
    v["metrics_scope"] = select(c2, "Traces over", "metrics_scope", METRIC_SCOPES,
                                help=f"frontier = depth >= d_max - {D.frontier_window}")
    c1, c2 = bar.columns(2)
    v["cluster_window"] = num(c1, "Cluster window W", "cluster_window", 2, 100_000, 10,
                              help="steps of cluster phase history behind n_clusters_eff")
    v["cluster_drift_max"] = num(c2, "Merge drift (rad)", "cluster_drift_max", 0.01, 100.0, 0.1,
                                 help="clusters drifting apart by less than this over the window share a frequency")

    bar.subheader("Controls")
    c1, c2 = bar.columns(2)
    v["fps"] = num(c1, "FPS", "fps", 0.5, 30.0, 0.5)
    v["steps_per_frame"] = num(c2, "Steps / frame", "steps_per_frame", 1, 2000, 1)
    c1, c2 = bar.columns(2)
    v["step_n"] = num(c1, "N (Step ×N)", "step_n", 1, 1_000_000, 10)
    v["auto_grow_every"] = num(c2, "Auto-grow every", "auto_grow_every", 0, 1_000_000, 100,
                               help="grow one level every this many steps, up to the target level (0 = off)")
    cfg = D.replace(**v)

    act: dict = {}
    c1, c2 = bar.columns(2)
    act["grow"] = c1.button("Grow ×1", width="stretch")
    act["grow_target"] = c2.button("Grow to target", width="stretch")
    c1, c2 = bar.columns(2)
    act["step"] = c1.button(f"Step ×{cfg.step_n}", width="stretch")
    running = ss.get("running", False)
    c2.button("Pause" if running else "Run", on_click=_toggle_run, width="stretch", type="primary",
              icon=":material/pause:" if running else ":material/play_arrow:")
    c1, c2 = bar.columns(2)
    n_max = max(sb.g.n() - 1, 0)
    ss["ui_probe_vertex"] = int(np.clip(ss.get("ui_probe_vertex", 0), 0, n_max))
    act["probe_vertex"] = c1.number_input("Probe vertex", 0, n_max, step=1, key="ui_probe_vertex",
                                          help="click a vertex on the Graph tab to set it")
    act["probe"] = c2.button("Probe", width="stretch", help=f"one-off injection of amplitude {cfg.probe_amp}")
    c1, c2 = bar.columns(2)
    act["reset"] = c1.button("Reset", width="stretch")
    act["export"] = c2.button("Export", width="stretch", help="writes results/<timestamp>_<seed>/")
    act["export_slot"] = bar.empty()
    return mode, cfg, act


def safe_step(sb: Sandbox, n: int) -> bool:
    """Step; if the dynamics refuses (e.g. the sink bound), pause and report instead of raising."""
    try:
        sb.step(n)
        return True
    except ValueError as exc:
        ss.running = False
        flash("error", f"Dynamics refused to run: {exc}")
        return False


def handle_actions(sb: Sandbox, act: dict) -> None:
    if act["reset"]:
        sb.reset(sb.cfg)
        ss.running = False
        flash("info", "Simulation reset.")
    if act["grow"]:
        with st.spinner("Growing ..."):
            ok, msg = sb.grow()
        flash("success" if ok else "warning", msg)
    if act["grow_target"]:
        with st.spinner("Growing to the target level ..."):
            n, msg = sb.grow_to_target()
        flash("success" if n else "warning", msg)
    if act["step"]:
        with st.spinner(f"Stepping ×{sb.cfg.step_n} ..."):
            safe_step(sb, sb.cfg.step_n)
    if act["probe"]:
        v = int(act["probe_vertex"])
        if 0 <= v < sb.g.n():
            sb.probe(v)
            flash("success", f"Probe injected at vertex {v} (amplitude {sb.cfg.probe_amp}).")
        else:
            flash("warning", f"Vertex {v} does not exist (N = {sb.g.n():,}).")


# ------------------------------------------------------------------------------------------ header
def render_header(slot, sb: Sandbox) -> None:
    g, s, cfg, spec = sb.g, sb.s, sb.cfg, sb.spec
    last = sb.traces.last()
    coh = cfg.harmonicity_coherence
    harm = last.get(f"harmonicity_{coh}", float("nan"))
    with slot.container():
        cols = st.columns(9)
        cols[0].metric("Rule / level", f"{g.rule} / {g.level}")
        cols[1].metric("Vertices", f"{g.n():,}")
        cols[2].metric("Edges", f"{g.n_edges():,}")
        cols[3].metric("Step", f"{s.step:,}", help=f"t = {s.t:.3f}")
        cols[4].metric("Energy Σ|a|²", f"{last.get('energy', float('nan')):.4g}")
        cols[5].metric("Harmonicity", f"{harm:.4f}", help=f"coherence factor: {coh}")
        cols[6].metric("harmonicity_osc", f"{last.get('harmonicity_osc', float('nan')):.4f}",
                       help=f"cluster_order {last.get('cluster_order', float('nan')):.3f} × log(1 + n_clusters_eff) / "
                            f"log(1 + {cfg.n_clusters}); n_clusters_eff = {last.get('n_clusters_eff', float('nan')):.0f}")
        cols[7].metric("Fundamental fraction", f"{last.get('fundamental_fraction', float('nan')):.4f}")
        cols[8].metric("n_eff", f"{last.get('n_eff', float('nan')):.2f}")
        why = sb.dynamics_blocker()
        if why:
            st.error(f"Dynamics refuses to run: {why}")
        state = "running" if ss.get("running") else "paused"
        st.caption(f"{state} · {sb.dyn.name} · integrator: {sb.integrator()} · dt = {sb.dt():.4g} · spectrum: "
                   f"{spec.method}, "
                   f"K = {spec.k_used:,} · drive: {cfg.drive} · traces over: {cfg.metrics_scope}"
                   + (f" (captured energy fraction {last.get('captured', float('nan')):.3f})"
                      if spec.method == "sparse" else ""))


# ------------------------------------------------------------------------------------------ Graph tab
def graph_fig(sb: Sandbox, overlay: str, k: int, height: int = 620) -> go.Figure:
    g, s, cfg, spec = sb.g, sb.s, sb.cfg, sb.spec
    amp, ph = np.abs(s.a), np.angle(s.a)
    sizes, extra = None, None
    if overlay == "Eigenmode":
        k = int(np.clip(k, 1, spec.k_used))
        vals, mode = spec.mode(k), "diverging"
        title, cbar = f"Eigenmode φ_{k} (λ = {spec.lam[k - 1]:.6g})", f"φ_{k}"
        extra = (f"φ_{k}", vals)
    elif overlay == "Fiedler partition" and spec.k_used >= 2:
        vals, mode = (spec.mode(2) >= 0).astype(float), "partition"
        title, cbar = "Fiedler partition: sign of φ_2", "sign φ_2"
        purity = partition_purity(g, s, spec)
        if np.isfinite(purity):
            title += f" (purity vs sub-gaskets = {purity:.3f})"
    elif overlay == "Depth":
        vals, mode, title, cbar = g.depth.astype(float), "sequential", "Depth (growth step at birth)", "depth"
    else:
        vals, mode, sizes = ph, "phase", amp
        title, cbar = "State: color = phase, size ∝ |a|", "phase"

    def hover(idx):
        text = [f"id {i}<br>depth {g.depth[i]}<br>|a| {amp[i]:.3g}<br>phase {ph[i]:+.3f}" for i in idx]
        if extra is not None:
            text = [f"{t}<br>{extra[0]} {extra[1][i]:+.4g}" for t, i in zip(text, idx)]
        return text

    groups = None
    if ss.get("ui_clusters"):
        groups = sb.clusters()
        title += f" · {int(groups.max()) + 1} spectral clusters behind the vertices"
    probe = int(ss.get("ui_probe_vertex", 0))
    return graph_figure(g, vals, mode=mode, sizes=sizes, title=title, keep=[probe],
                        max_vertices=cfg.max_display_vertices, max_edges=cfg.max_display_edges, hover=hover,
                        colorbar_title=cbar, seed=cfg.seed, height=height, highlight=probe, groups=groups)


def graph_tab(sb: Sandbox):
    spec = sb.spec
    c1, c2, c3, c4 = st.columns([3, 1, 1, 2])
    _default("ui_overlay", "State")
    overlay = c1.radio("Overlay", OVERLAYS, key="ui_overlay", horizontal=True)
    k_max = max(spec.k_used, 1)
    ss["ui_paint_k"] = int(np.clip(ss.get("ui_paint_k", 2), 1, k_max))
    c2.number_input("Mode k", 1, k_max, step=1, key="ui_paint_k", disabled=overlay != "Eigenmode")
    if ss.get("_clusters_dynamics") != sb.cfg.dynamics:
        ss["_clusters_dynamics"] = sb.cfg.dynamics
        ss["ui_clusters"] = sb.cfg.dynamics in ("stuart_landau", "oscillator")
    c3.toggle("Cluster overlay", key="ui_clusters",
              help="3-way spectral clusters (k-means on the low eigenspace) as three hues at 30% opacity")
    c4.caption("Click a vertex to set the probe target (ringed). Scroll to zoom, drag to pan. "
               "Rows of the Modes tab paint that mode here.")
    return st.container(key="live_graph")


def draw_graph(slot, sb: Sandbox, figs: dict) -> None:
    fig = graph_fig(sb, ss.get("ui_overlay", "State"), ss.get("ui_paint_k", 2))
    figs["graph"] = fig
    with slot:
        live_chart(fig, key="graph_live", scrollZoom=True)


# ------------------------------------------------------------------------------------------ Spectrum tab
def spectrum_tab(sb: Sandbox, figs: dict) -> None:
    g, spec = sb.g, sb.spec
    curves = list(sb.spec_history) + [(f"level {g.level} (N={g.n():,}), current", spec.lam, g.n())]
    title = "Sorted eigenvalues vs index / N"
    if spec.method == "sparse":
        title += f" (lowest {spec.k_used:,} of {g.n():,} modes)"
    fig = staircase_figure(curves, title)
    hist = go.Figure(go.Histogram(x=spec.lam, nbinsx=150, marker_color="#4c78a8"))
    hist.update_layout(title="Eigenvalue histogram", xaxis_title="λ", yaxis_title="count", height=420,
                       margin=dict(l=10, r=10, t=40, b=10))
    figs["spectrum_staircase"], figs["spectrum_histogram"] = fig, hist
    c1, c2 = st.columns([3, 2])
    c1.plotly_chart(fig, key="staircase_chart")
    c2.plotly_chart(hist, key="histogram_chart")

    deg = degeneracy(g, sb.s, spec, sb.cfg)
    m = st.columns(6)
    m[0].metric("Distinct eigenvalues", f"{deg['n_distinct']:,}")
    m[1].metric("Max multiplicity", f"{deg['max_multiplicity']:,}", help=f"at λ = {deg['max_multiplicity_lambda']:.6g}")
    m[2].metric("Fraction in degenerate levels", f"{deg['frac_degenerate']:.3f}")
    m[3].metric("Spectral gap ratio λ3/λ2", f"{spectral_gap_ratio(g, sb.s, spec):.4g}")
    m[4].metric("frac_localized", f"{frac_localized(g, sb.s, spec, sb.cfg):.3f}")
    m[5].metric("Method", f"{spec.method}, K = {spec.k_used:,}")
    groups = degenerate_groups(spec.lam, sb.cfg.degeneracy_tol)
    levels = sorted(((b - a, float(spec.lam[a])) for a, b in groups if b - a > 1), reverse=True)[:20]
    if levels:
        st.caption("Largest degenerate levels" + (" (among the computed modes)" if spec.method == "sparse" else ""))
        st.dataframe(pd.DataFrame({"λ": [l for _, l in levels], "multiplicity": [mm for mm, _ in levels],
                                   "fraction of N": [mm / g.n() for mm, _ in levels]}),
                     hide_index=True, height=260,
                     column_config={"λ": st.column_config.NumberColumn(format="%.6f"),
                                    "fraction of N": st.column_config.NumberColumn(format="%.4f")})


# ------------------------------------------------------------------------------------------ Traces tab
def traces_fig(sb: Sandbox) -> go.Figure | None:
    if len(sb.traces) == 0:
        return None
    df = sb.traces.frame()
    if len(df) > TRACE_PLOT_POINTS:
        df = df.iloc[np.unique(np.linspace(0, len(df) - 1, TRACE_PLOT_POINTS).astype(int))]
    coh = sb.cfg.harmonicity_coherence

    def col(name):
        return df[name].to_numpy(np.float32)

    harm = (df[coh] * np.log1p(df["n_eff"]) / np.log1p(df["K"])).to_numpy(np.float32)
    panels = [
        (f"harmonicity (coherence factor: {coh})", [(f"harmonicity [{coh}]", harm, "#d62728", 1.6)], False),
        ("coherence factors", [(f, col(f), FACTOR_COLORS[f], 2.6 if f == coh else 1.1) for f in COHERENCE_FACTORS],
         False),
        ("n_eff", [("n_eff", col("n_eff"), "#ff7f0e", 1.6)], False),
        ("fundamental_fraction", [("fundamental_fraction", col("fundamental_fraction"), "#8c564b", 1.6)], False),
        ("total energy Σ|a|²", [("energy", col("energy"), "#7f7f7f", 1.6)], True),
    ]
    if "harmonicity_osc" in df:
        panels += [
            (f"harmonicity_osc = cluster_order × log(1 + n_clusters_eff) / log(1 + {sb.cfg.n_clusters})",
             [("harmonicity_osc", col("harmonicity_osc"), "#d62728", 1.6),
              ("cluster_order", col("cluster_order"), "#1f77b4", 1.1)], False),
            ("n_clusters_eff (distinct cluster frequencies)",
             [("n_clusters_eff", col("n_clusters_eff"), "#ff7f0e", 1.6)], False),
        ]
    if "low_subspace_fraction" in df:
        panels.append(("low_subspace_fraction (modes k ≤ k_gap)",
                       [("low_subspace_fraction", col("low_subspace_fraction"), "#2ca02c", 1.6)], False))
    plotted = {"harmonicity", "n_eff", "fundamental_fraction", "energy", *COHERENCE_FACTORS,
               "harmonicity_osc", "cluster_order", "n_clusters_eff", "low_subspace_fraction"}
    panels += [(m.name, [(m.name, col(m.name), "#17becf", 1.6)], False)
               for m in METRICS.values() if m.trace and m.name not in plotted and m.name in df]
    if "consistency" in df and bool(df["consistency"].notna().any()):
        panels.append(("sheaf consistency energy", [("consistency", col("consistency"), "#e377c2", 1.6)], False))
    return stacked_figure(df["step"].to_numpy(np.int32), panels, vlines=sb.growth_steps)


def traces_tab(sb: Sandbox):
    st.caption("Harmonicity is recomputed from the stored coherence factors, n_eff and K whenever the "
               "coherence factor changes; the spectrum is not recomputed. Dotted lines mark growth events. "
               "While running, this plot refreshes about once per second."
               + (f" Oldest {sb.traces.dropped:,} rows dropped." if sb.traces.dropped else ""))
    return st.container(key="live_traces")


def draw_traces(slot, sb: Sandbox, figs: dict) -> None:
    fig = traces_fig(sb)
    if fig is not None:
        figs["traces"] = fig
        with slot:
            live_chart(fig, key="traces_live")


# ------------------------------------------------------------------------------------------ Depth tab
def depth_tab(sb: Sandbox, figs: dict) -> None:
    _default("ui_depth_avg", True)
    averaged = st.toggle("Time-average |a|² since the last growth event or reset", key="ui_depth_avg")
    E = sb.depth_energy(averaged)
    label = f"mean over {sb.avg_steps:,} steps" if averaged and sb.avg_steps else "instantaneous"
    fig = depth_energy_figure(E, title=f"E[d] = Σ_(depth = d) |a|² ({label}); fits use d ≥ 1")
    figs["depth_energy"] = fig
    st.plotly_chart(fig, key="depth_chart")
    pw, ex = fit_powerlaw(E), fit_exponential(E)
    c = st.columns(4)
    c[0].metric("R² power law (log-log)", f"{pw['r2']:.4f}")
    c[1].metric("Power-law slope", f"{pw['slope']:.4g}")
    c[2].metric("R² exponential (log-linear)", f"{ex['r2']:.4f}")
    c[3].metric("Exponential slope", f"{ex['slope']:.4g}")
    counts = np.bincount(sb.g.depth, minlength=len(E))
    st.dataframe(pd.DataFrame({"depth": np.arange(len(E)), "vertices": counts, "E[d]": E}), hide_index=True,
                 column_config={"E[d]": st.column_config.NumberColumn(format="%.6g")})


# ------------------------------------------------------------------------------------------ Modes tab
def modes_tab(sb: Sandbox) -> None:
    spec = sb.spec
    md = modal_decomposition(sb.g, sb.s, spec)
    # + 0.0 turns the -0.0 of a numerically zero eigenvalue into 0.0, so it is not shown as -0.000000
    df = pd.DataFrame({"k": np.arange(1, spec.k_used + 1), "λ_k": spec.lam.round(12) + 0.0,
                       "ω_k": spec.omega, "p_k": md.p, "ipr_k": spec.ipr})
    st.caption("Click a row to paint that mode on the Graph tab. p_k = modal energy fraction of the current "
               "full state" + (f"; the {spec.k_used:,} computed modes carry {md.captured:.3f} of its energy."
                               if spec.method == "sparse" else "."))
    st.dataframe(df, key="modes_table", on_select="rerun", selection_mode="single-row", hide_index=True,
                 height=560, column_config={
                     "λ_k": st.column_config.NumberColumn(format="%.6f"),
                     "ω_k": st.column_config.NumberColumn(format="%.6f"),
                     "p_k": st.column_config.NumberColumn(format="%.3e"),
                     "ipr_k": st.column_config.NumberColumn(format="%.4f")})


# ------------------------------------------------------------------------------------------ Sheaf tab
def sheaf_tab(sb: Sandbox, figs: dict) -> None:
    cfg = sb.cfg
    st.markdown("A cellular sheaf on the current graph (spec 6.1): a k-dim stalk per vertex and restriction "
                "maps per edge. Consistency = xᵀL_F x / ‖x‖²; globally consistent states form ker L_F. "
                "When the graph grows, new edges get identity maps.")
    c1, c2, c3 = st.columns([1, 2, 1])
    _default("sh_k", cfg.e5_stalk_dim)
    k = c1.number_input("Stalk dim k", 1, 4, step=1, key="sh_k")
    _default("sh_init", "identity")
    kind = c2.radio("Initialize maps", SHEAF_INITS, key="sh_init", horizontal=True,
                    help=f"learned = trained from identity maps on {cfg.e5_examples} consistent states of a "
                         "hidden flat ground-truth sheaf")
    if c3.button("Initialize sheaf", type="primary"):
        with st.spinner("Initializing sheaf ..."):
            sb.init_sheaf(int(k), kind)
    if sb.sheaf is None:
        st.info("No sheaf is active. Initialize one to run diffusion, the inference test, and to add the "
                "consistency energy to the Traces tab.")
        return
    log = sb.sheaf_log
    live = sb.traces.last().get("consistency", float("nan"))
    c = st.columns(4)
    c[0].metric("Active sheaf", f"{log.get('kind', '?')}, k = {sb.sheaf.k}")
    c[1].metric("Consistency of the live state", f"{live:.4g}")
    c[2].metric("Edges with maps", f"{len(sb.sheaf.F_head):,}")
    if c[3].button("Remove sheaf"):
        sb.clear_sheaf()
        st.rerun()
    if "learn" in log:
        fig = go.Figure(go.Scatter(y=log["learn"], mode="lines"))
        fig.update_layout(title="Learning: mean Dirichlet energy of the training examples", xaxis_title="step",
                          yaxis_type="log", height=300, margin=dict(l=10, r=10, t=40, b=10))
        figs["sheaf_learning"] = fig
        st.plotly_chart(fig, key="sheaf_learn_chart")

    st.markdown("#### Diffusion")
    c1, c2, c3, c4 = st.columns(4)
    _default("sh_steps", 1000)
    _default("sh_eta", float(cfg.e5_diffuse_eta))
    steps = c1.number_input("Steps", 1, 200_000, step=100, key="sh_steps")
    eta = c2.number_input("eta", 0.001, 2.0, step=0.01, key="sh_eta", help="clipped to 1.9 / λ_max(L_F)")
    start = c3.selectbox("Start from", ("state", "random"), key="sh_start",
                         format_func=lambda s: "live state" if s == "state" else "random vector")
    if c4.button("Run diffusion"):
        with st.spinner("Diffusing ..."):
            sb.sheaf_diffusion(float(eta), int(steps), start)
    if "diffusion" in log:
        d = log["diffusion"]
        t, cons = zip(*d["trace"])
        fig = go.Figure(go.Scatter(x=t, y=cons, mode="lines"))
        fig.update_layout(title=f"Consistency energy during diffusion (eta = {d['eta']:.4g}, from {d['start']})",
                          xaxis_title="step", yaxis_type="log", height=320, margin=dict(l=10, r=10, t=40, b=10))
        figs["sheaf_diffusion"] = fig
        st.plotly_chart(fig, key="sheaf_diffusion_chart")

    st.markdown("#### Inference test")
    c1, c2, c3 = st.columns(3)
    _default("sh_clamp", int(round(cfg.e5_clamp_frac * 100)))
    _default("sh_inf_steps", int(cfg.e5_diffuse_steps))
    clamp = c1.slider("Clamp % of vertices", 1, 99, key="sh_clamp")
    inf_steps = c2.number_input("Diffusion steps", 10, 200_000, step=500, key="sh_inf_steps")
    if c3.button("Run inference test"):
        with st.spinner("Recovering unclamped vertices ..."):
            sb.sheaf_inference(clamp / 100.0, float(eta), int(inf_steps))
    if "inference" in log:
        r = log["inference"]
        c = st.columns(4)
        c[0].metric("Recovery MSE (active sheaf)", f"{r['mse']:.4g}")
        c[1].metric("MSE (identity-map baseline)", f"{r['mse_identity']:.4g}")
        c[2].metric("Ratio", f"{r['ratio']:.4g}", help="E5 passes when this is < 0.25 (on gasket level 4)")
        c[3].metric("Clamped vertices", f"{r['clamped']:,}")
        st.caption("Ground truth: " + ("a fresh random flat sheaf; the active sheaf was not learned from it, so "
                                       "a ratio near or above 1 is expected." if r["fresh_truth"] else
                                       "the hidden flat sheaf the active maps were learned from."))


# ------------------------------------------------------------------------------------------ Constraints tab
@st.cache_data(max_entries=32, show_spinner=False)
def _maxcut_optimum(n: int, seed: int) -> tuple[int, str]:
    prob = _maxcut(n, seed)
    if n <= 20:
        return max_cut_brute_force(n, prob.edges), "brute force"
    return prob.optimum(), "exact tree-decomposition DP"


def constraints_tab(sb: Sandbox, figs: dict) -> None:
    st.markdown("**MaxCut with an oscillator Ising machine** (spec 6.2, V1.1 2.3): "
                "dθ_i/dt = −K Σ_j J_ij sin(θ_i − θ_j) − K_s(t) sin(2θ_i) + σξ_i with J = −A (antiferromagnetic), "
                "in the frame of the sub-harmonic injection (ω_i = 0). K_s ramps from 0 to K_s,max over the "
                "annealing steps and pulls every phase to 0 or π; spins = sign(Re a). "
                "Energy = −Σ_ij J_ij cos(θ_i − θ_j). E6 runs this on ten 40-node instances.")
    c = st.columns(4)
    _default("cp_n", 16)
    _default("cp_seed", 0)
    _default("cp_run", 0)
    _default("cp_steps", int(D.e6_steps))
    n = int(c[0].number_input("Nodes (3-regular graph, even)", 4, 60, step=2, key="cp_n"))
    seed = int(c[1].number_input("Problem seed", 0, 100_000, step=1, key="cp_seed"))
    run_seed = int(c[2].number_input("Run seed", 0, 100_000, step=1, key="cp_run",
                                     help="initial phases and noise"))
    steps = int(c[3].number_input("Steps", 10, 200_000, step=100, key="cp_steps"))
    c = st.columns(4)
    _default("cp_K", float(D.osc_K))
    _default("cp_ksmax", float(D.osc_Ks_max))
    _default("cp_anneal", int(D.osc_anneal_steps))
    _default("cp_noise", float(D.osc_noise))
    K = float(c[0].number_input("K", 0.0, 10.0, step=0.1, key="cp_K"))
    ksmax = float(c[1].number_input("K_s max", 0.0, 10.0, step=0.1, key="cp_ksmax"))
    anneal = int(c[2].number_input("Annealing steps", 1, 200_000, step=100, key="cp_anneal"))
    noise = float(c[3].number_input("Noise σ", 0.0, 5.0, step=0.01, key="cp_noise"))
    if n % 2:
        st.warning("A 3-regular graph needs an even number of nodes.")
        return
    prob = _maxcut(n, seed)
    optimum, how = _maxcut_optimum(n, seed)
    key = (n, seed, run_seed, steps, K, ksmax, anneal, noise)
    if st.button("Solve with OscillatorDynamics", type="primary"):
        run_cfg = sb.cfg.replace(osc_K=K, osc_Ks_max=ksmax, osc_anneal_steps=anneal, osc_noise=noise)
        with st.spinner("Annealing ..."):
            s, energy = oscillator_solve(prob, run_cfg, np.random.default_rng([seed, run_seed]), steps)
        ss.cp_result = {"key": key, "a": s.a, "energy": energy}
    res = ss.get("cp_result")
    if res is None or res["key"] != key:
        st.info(f"Optimum cut of this graph: {optimum} ({how}). Press Solve to anneal.")
        fig = graph_figure(prob.graph(), np.zeros(n), mode="sequential", title=f"MaxCut instance: n = {n}, "
                           f"{len(prob.edges)} edges, optimum {optimum}", height=460)
        figs["constraints"] = fig
        st.plotly_chart(fig, key="constraints_chart")
        return
    spins = np.where(np.real(res["a"]) >= 0, 1, -1)
    cut = prob.cut_value(spins)
    energy = res["energy"]
    m = st.columns(4)
    m[0].metric("Cut found", cut)
    m[1].metric(f"Optimum ({how})", optimum)
    m[2].metric("Ratio", f"{cut / optimum:.3f}" if optimum else "n/a", help="E6 criterion: ≥ 0.9 in ≥ 8/10 seeds")
    m[3].metric("Final energy", f"{energy[-1]:.4g}", help="−Σ J cos Δθ; −2 × (#cut − #uncut) at a binary state")
    c1, c2 = st.columns([1, 1])
    fig_e = go.Figure(go.Scatter(x=np.arange(1, len(energy) + 1), y=energy, mode="lines"))
    fig_e.add_vline(x=min(anneal, len(energy)), line=dict(color="gray", dash="dot"),
                    annotation_text="K_s reaches max")
    fig_e.update_layout(title="Energy during annealing", xaxis_title="step", yaxis_title="energy", height=460,
                        margin=dict(l=10, r=10, t=40, b=10))
    fig = graph_figure(prob.graph(), (spins > 0).astype(float), mode="partition",
                       title=f"Spins = sign(Re a): cut {cut} of optimum {optimum}", colorbar_title="spin", height=460)
    figs["constraints_energy"], figs["constraints"] = fig_e, fig
    c1.plotly_chart(fig_e, key="constraints_energy_chart")
    c2.plotly_chart(fig, key="constraints_chart")


# ------------------------------------------------------------------------------------------ Test Suite
def _comparison_rows(results: dict, pairs=V1_PAIRS, labels=("V1.1", "V1")) -> list[dict]:
    """The current protocol next to each preserved predecessor that ran (a pair's value is an id or a tuple)."""
    rows = []
    for new, olds in pairs.items():
        news = [r for r in results.values() if r.id == new or (r.group == new and r.role == "gate")]
        if not news:
            continue
        verdict = gate_verdicts(news).get(new, news[0].status)
        for old in ((olds,) if isinstance(olds, str) else olds):
            if old in results:
                rows.append({"Experiment": new, labels[0]: STATUS_LABEL.get(verdict, verdict),
                             f"{labels[0]} key numbers": " | ".join(f"{r.id}: {r.summary}" for r in news),
                             labels[1]: STATUS_LABEL.get(results[old].status, results[old].status),
                             f"{labels[1]} key numbers": f"{old}: {results[old].summary}"})
    return rows


def _e4_tables(results: dict) -> None:
    for eid in ("E4b", "E4c"):
        r = results.get(eid)
        if r is None or "per_variant" not in r.metrics:
            continue
        pv, null = r.metrics["per_variant"], r.metrics["null_control"]
        st.markdown(f"**{eid}: all four harmonicity variants** (the pass is on harmonicity_osc)")
        st.dataframe(pd.DataFrame([{
            "variant": v, "gasket start": pv[v]["gasket"]["start_mean"], "gasket end": pv[v]["gasket"]["end_mean"],
            "p rise": pv[v]["p_rise"], "complete end": pv[v]["complete"]["end_mean"],
            "p gasket > complete": pv[v]["p_gasket_vs_complete"],
            f"{null} start": pv[v][null]["start_mean"], f"{null} end": pv[v][null]["end_mean"],
            f"p {null} rise": pv[v][f"p_rise_{null}"], "criterion met": pv[v]["criterion_met"]}
            for v in E4_VARIANTS]), hide_index=True)
    for eid in ("E4a", "E4_v1"):
        r = results.get(eid)
        if r is None or "per_factor" not in r.metrics:
            continue
        pf = r.metrics["per_factor"]
        st.markdown(f"**{eid} under all three coherence factors** (a conclusion that holds under only one is not a "
                    "conclusion)")
        st.dataframe(pd.DataFrame([{
            "coherence factor": f, "sink increase": pf[f]["sink"]["increase_mean"],
            "control increase": pf[f]["control"]["increase_mean"], "p (one-sided paired)": pf[f]["p_value"],
            "rises": pf[f]["rises"], "attributable to sink": pf[f]["attributable_to_sink"],
            "holds": pf[f]["passed"]} for f in COHERENCE_FACTORS]), hide_index=True)


def test_suite_panel(cfg: XonConfig) -> None:
    st.subheader("Test Suite: pre-registered experiments")
    st.caption("Protocols and pass thresholds are fixed in xon/experiments.py before any run; re-registrations (V1.1, "
               "and E9c's after the first V1.2 run) are logged in CHANGELOG_EXPERIMENTS.md. They are shown next to "
               "every result and cannot be tuned from the UI. E4 passes if E4b or E4c passes; E4a is a negative "
               "control and never counts.")
    _default("ts_include_v1", False)
    include_v1 = st.toggle("Include the preserved V1 protocols (" + ", ".join(v1_ids()) + ")", key="ts_include_v1",
                           help="same as run_tests --include-v1; results appear side by side with V1.1")
    ids = default_ids() + (v1_ids() if include_v1 else [])
    chosen = []
    per_row = 8

    def checkboxes(eids: list[str], default: bool) -> None:
        for start in range(0, len(eids), per_row):
            cols = st.columns(per_row)
            for col, eid in zip(cols, eids[start:start + per_row]):
                _default(f"ts_{eid}", default)
                role = registration(eid).role
                if col.checkbox(eid, key=f"ts_{eid}", help=f"{registration(eid).name} ({ROLE_LABEL.get(role, role)})"):
                    chosen.append(eid)

    checkboxes(ids, True)
    v12 = control_ids() + geometry_ids() + preserved_v1_2_ids()
    st.caption("V1.2 (XON_SIM_GEOMETRY_V1_2): E1_lattice runs E1's statistics on the lattice, next to E1; E9a-E9c "
               "compare the geometries chosen below; E9c_v1 and E9c_v2 are E9c's earlier registrations (reported "
               "only). " + E9D_STATUS)
    checkboxes(v12, False)
    _default("ts_geometries", list(GEOMETRIES))
    geos = st.multiselect("E9 geometries", GEOMETRIES, key="ts_geometries",
                          format_func=lambda n: geometry_label(n, D),
                          help="each E9 experiment runs the geometries it has a prediction for (E9c: its references)")
    order = {e: i for i, e in enumerate(suite_ids(include_v1=include_v1, include_controls=True))}
    chosen.sort(key=lambda e: order.get(e, len(order)))
    missing_geos = any(e in geometry_ids() for e in chosen) and not geos
    if missing_geos:
        st.warning("Choose at least one geometry for the E9 experiments.")
    c1, c2, c3 = st.columns([1, 1, 2])
    _default("ts_seeds", int(D.e4_seeds))
    _default("ts_seed", int(D.seed))
    _default("ts_sidebar", False)
    seeds = c1.number_input("Seeds count", 1, 100, step=1, key="ts_seeds",
                            help=f"seeds for E4a/b/c and E4_v1 (pre-registered: {D.e4_seeds})")
    base = c2.number_input("Base seed", 0, 2 ** 31 - 1, step=1, key="ts_seed")
    use_sidebar = c3.toggle("Use the sidebar's dynamics and metric settings", key="ts_sidebar",
                            help="Off = the protocol defaults in config.py")
    if st.button("Run selected", type="primary", disabled=not chosen or missing_geos):
        exp_cfg = (cfg if use_sidebar else D).replace(seed=int(base), e4_seeds=int(seeds), e9_geometries=tuple(geos))
        results = {}
        progress = st.progress(0.0)
        for i, eid in enumerate(chosen):
            progress.progress(i / len(chosen), text=f"Running {eid}: {registration(eid).name} ...")
            results[eid] = run_experiment(eid, exp_cfg)
        progress.progress(1.0, text="Done.")
        ss.exp_results, ss.exp_cfg = results, exp_cfg

    results = ss.get("exp_results") or {}
    if not results:
        st.markdown("#### Pre-registered criteria")
        regs = {e: registration(e) for e in ids + v12}
        st.dataframe(pd.DataFrame([{"ID": e, "Experiment": r.name, "Role": ROLE_LABEL[r.role],
                                    "Pass criterion": r.criterion, "Thresholds": _fmt_thresholds(r.thresholds),
                                    "Re-registered": r.reregistered} for e, r in regs.items()]),
                     hide_index=True)
        return
    rows = [{"ID": r.id, "Experiment": r.name, "Role": ROLE_LABEL.get(r.role, r.role),
             "Result": STATUS_LABEL.get(r.status, r.status), "Key numbers": r.summary,
             "Pre-registered criterion": r.criterion, "Thresholds": _fmt_thresholds(r.thresholds),
             "Runtime (s)": round(r.runtime_s, 1)} for r in results.values()]
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    counts = pd.Series([r.status for r in results.values()]).value_counts().to_dict()
    verdicts = gate_verdicts(results.values())
    multi = {g: v for g, v in verdicts.items() if sum(r.group == g and r.role == "gate" for r in results.values()) > 1}
    st.caption(" · ".join(f"{STATUS_LABEL.get(k, k)}: {v}" for k, v in counts.items())
               + "".join(f" · {g} (any of {', '.join(r.id for r in results.values() if r.group == g and r.role == 'gate')})"
                         f": {STATUS_LABEL.get(v, v)}" for g, v in multi.items())
               + f" · seed {ss.exp_cfg.seed}")
    comparison = _comparison_rows(results)
    if comparison:
        st.markdown("**V1.1 vs the preserved V1 protocols**")
        st.dataframe(pd.DataFrame(comparison), hide_index=True)
    comparison = _comparison_rows(results, V1_2_PAIRS, ("Current", "Earlier registration"))
    if comparison:
        st.markdown("**V1.2 re-registrations vs their earlier registrations**")
        st.dataframe(pd.DataFrame(comparison), hide_index=True)
    header, report = e9_report(results.values(), ss.exp_cfg)
    if report:
        st.markdown("**E9 report: geometries as rows**")
        st.caption(header)
        st.dataframe(pd.DataFrame(report), hide_index=True)
    _e4_tables(results)
    if st.button("Export results", key="ts_export"):
        with st.spinner("Exporting ..."):
            figs = {f"{r.id}_{name}": fig for r in results.values() for name, fig in r.figures.items()}
            run_dir, info = export_run("results", ss.exp_cfg, experiments=list(results.values()), figures=figs,
                                       extra={"source": "app test suite", **({"e9_report_header": header}
                                                                               if report else {})},
                                       tables={"e9_report": report})
        st.success(f"Exported to {run_dir}" + (f". {info['note']}" if info.get("note") else ""))
    for r in results.values():
        with st.expander(f"{r.id} · {r.name} · {STATUS_LABEL.get(r.status, r.status)}"):
            st.markdown(f"**Pre-registered criterion:** {r.criterion}")
            st.markdown(f"**Thresholds:** `{_fmt_thresholds(r.thresholds)}`")
            st.markdown(f"**Key numbers:** {r.summary}")
            if r.notes:
                st.text(r.notes)
            st.json(to_jsonable(r.metrics), expanded=False)
            for name, fig in r.figures.items():
                st.plotly_chart(fig, key=f"exp_{r.id}_{name}")


# ------------------------------------------------------------------------------------------ Geometry Compare
GC_EXPERIMENTS = {"E9a": "spectral self-similarity", "E9b": "spectral individuation", "E9c": "known dimensions"}
GC_COLUMNS = {
    "E9a": (("Degenerate fraction", "degenerate_fraction"), ("Plateau persistence", "plateau_persistence"),
            ("Plateau containment", "plateau_containment")),
    "E9b": (("k", "k"), ("Purity", "purity"), ("Seam fraction", "seam_fraction")),
    "E9c": tuple((col, key) for key, col in E9C_COLUMNS),
}


def _gc_compute(names: list[str], eids: list[str], cfg: XonConfig, target: int) -> dict:
    """E9a-E9c rows of every geometry at its matched level, with their predictions and figures."""
    restarts = int(REGISTRY_V1_2["E9b"].thresholds["restarts"])
    out = {"names": names, "target": target, "p": int(cfg.e9_sierpinski_p), "seed": int(cfg.seed),
           "levels": {n: matched_level(n, cfg, target) for n in names},
           "rows": {e: {} for e in eids}, "figures": {e: {} for e in eids}}
    jobs = [(e, n) for e in eids for n in names]
    curves = {}
    progress = st.progress(0.0)
    for i, (eid, name) in enumerate(jobs):
        level = out["levels"][name]
        progress.progress(i / len(jobs), text=f"{eid} on {geometry_label(name, cfg)} (level {level}) ...")
        rng = geometry_rng(cfg.seed, f"{eid}:{name}")
        if eid == "E9a":
            row = spectral_row(name, cfg, level)
            out["figures"][eid][name] = staircase(name, cfg, row)
        elif eid == "E9b":
            try:
                row = clustering_row(name, cfg.replace(cluster_restarts=restarts), level, rng)
            except ValueError:
                out["rows"][eid][name] = None  # no top-level sub-regions (lattice)
                continue
            out["figures"][eid][name] = cluster_overlay(name, cfg, row)
        else:
            row = curves[name] = dimension_row(name, cfg, level, rng,
                                               geometry_rng(cfg.seed, f"{eid}:{name}:uniform centers"))
            if name in CLOSED_FORM_GEOMETRIES:
                attach_structure(row, structure_rows(name, cfg, range(max(level - 1, 0), level + 1)))
        row["matches"], row["predicted"] = e9_prediction(eid, name, row, cfg)
        out["rows"][eid][name] = strip_curves(row)
    if curves:
        out["figures"]["E9c"] = dimension_figures(curves, cfg)
    progress.progress(1.0, text="Done.")
    return out


def _gc_table(eid: str, res: dict, cfg: XonConfig) -> pd.DataFrame:
    rows = []
    for name in res["names"]:
        r = res["rows"][eid].get(name)
        row = {"Geometry": geometry_label(name, cfg)}
        if r is None:
            rows.append({**row, "Level (N)": str(res["levels"][name]), "Predicted": "no sub-regions to cluster",
                         "Verdict": "-"})
            continue
        row["Level (N)"] = f"{r['level']} ({r['n']:,})"
        if eid == "E9c":
            row["N, E, D vs closed forms"] = exact_summary(r)
        for col, key in GC_COLUMNS[eid]:
            row[col] = r[key] if key == "k" else round(float(r.get(key, np.nan)), 3)
        row["Predicted"] = r["predicted"]
        row["Verdict"] = r["predicted"] if r["matches"] is None else ("match" if r["matches"] else "MISMATCH")
        rows.append(row)
    return pd.DataFrame(rows)


def geometry_compare_panel(cfg: XonConfig) -> None:
    st.subheader("Geometry Compare: E9a-E9c side by side at matched N")
    st.caption("Each geometry is built at the level whose N is nearest the target (log scale) and measured with the "
               "E9 metrics; predictions come from REGISTRY_V1_2 and cannot be tuned here. The Test Suite runs the "
               "same experiments at their registered sizes (E9a/E9b: 500 <= N <= 3,000; E9c: exact counts at every "
               "level up to N = 400,000, estimates at the largest level with N <= 50,000), so verdicts here at other "
               "sizes are indicative only; E9c checks the exact counts at the matched level and the one below. "
               + E9D_STATUS)
    _default("gc_geometries", ["gasket", "vicsek", "carpet"])
    _default("gc_target_n", 1000)
    _default("gc_p", int(D.e9_sierpinski_p))
    c1, c2, c3 = st.columns([3, 1, 1])
    names = c1.multiselect("Geometries (2 to 4)", GEOMETRIES, key="gc_geometries", max_selections=4,
                           format_func=lambda n: "S(p, n)" if n == "sierpinski_p" else n)
    target = c2.number_input("Target N", 50, 3000, step=50, key="gc_target_n",
                             help="E9a needs dense spectra of three levels, hence the cap")
    p = c3.number_input("p of S(p, n)", 3, 8, step=1, key="gc_p")
    cols = st.columns(len(GC_EXPERIMENTS) + 1)
    eids = []
    for col, (eid, title) in zip(cols, GC_EXPERIMENTS.items()):
        _default(f"gc_{eid}", True)
        if col.checkbox(f"{eid}: {title}", key=f"gc_{eid}"):
            eids.append(eid)
    ok = 2 <= len(names) <= 4 and eids
    if cols[-1].button("Compare", type="primary", disabled=not ok, width="stretch"):
        gcfg = D.replace(seed=int(cfg.seed), e9_sierpinski_p=int(p))
        ss.gc_results = (_gc_compute(list(names), eids, gcfg, int(target)), gcfg)
    if len(names) < 2:
        st.info("Choose at least two geometries.")
    if not ss.get("gc_results"):
        return
    res, gcfg = ss.gc_results
    st.caption(f"Results for target N = {res['target']:,}, p = {res['p']}, seed {res['seed']}; matched levels: "
               + ", ".join(f"{geometry_label(n, gcfg)} {res['levels'][n]}" for n in res["names"]) + ".")
    for eid in res["rows"]:
        st.markdown(f"#### {eid}: {GC_EXPERIMENTS[eid]}")
        st.caption(f"Pre-registered: {registration(eid).criterion}")
        st.dataframe(_gc_table(eid, res, gcfg), hide_index=True)
        figs = res["figures"][eid]
        if figs:
            for col, (name, fig) in zip(st.columns(len(figs)), figs.items()):
                col.plotly_chart(fig, key=f"gc_{eid}_{name}")
    st.info(E9D_STATUS)


# ------------------------------------------------------------------------------------------ Consistency (A1)
CLAUSE_LABEL = {"direct": "direct contradiction", "claim_balance": "unbalanced claim graph",
                "entity": "contradictory entity relations"}
ENGINE_DEFAULT = "2.2"          # XON_A1_REV2_2_PRECISION.md §2: the view defaults to rev. 2.2
TENSION_STYLE = "background-color: rgba(245, 166, 35, 0.25)"


def get_llm() -> LLM:
    """The session's LLM client: one budget and one running cost per browser session."""
    if "llm" not in ss:
        ss.llm = LLM(model=ss.get("llm_model", D.llm_model), budget_tokens=ss.get("llm_budget", D.llm_budget_tokens))
    return ss.llm


def llm_sidebar(bar) -> None:
    bar.subheader("LLM")
    _default("llm_model", D.llm_model)
    model = bar.selectbox("Model", LLM_MODELS, key="llm_model",
                          help=f"{D.llm_model} is the model for runs of record. Haiku 4.5 is cheap but not for runs "
                               "of record: its announced retirement would make results unreproducible.")
    if model != D.llm_model:
        bar.caption(f"Not the model for runs of record ({D.llm_model}).")
    if not LLM_CAPABILITIES[model]["thinking_can_disable"]:
        bar.caption("This model always thinks, so extraction and relation calls cost more and vary more.")
    _default("llm_engine_version", ENGINE_DEFAULT)
    bar.radio("Engine version", ENGINE_VERSIONS, key="llm_engine_version", horizontal=True,
              help="2.1: the L1 run of record's engine, relations scored in batches of 20. 2.2: one pair per call, a "
                   "'tension' label that makes no edge, entity directions derived from the text's own words. Both "
                   "reuse the same claims.")
    _default("llm_world_knowledge", D.llm_world_knowledge)
    bar.toggle("Relations may use world knowledge", key="llm_world_knowledge",
               help="Off: relations are judged from the claims' content only, so the engine checks the text's own "
                    "consistency.")
    _default("llm_budget", D.llm_budget_tokens)
    budget = bar.number_input("Session budget (tokens)", min_value=1_000, max_value=100_000_000, step=50_000,
                              key="llm_budget", help="A call that could take this session past the budget is refused.")
    llm = get_llm()
    llm.model, llm.budget_tokens = model, int(budget)
    u = llm.usage
    bar.caption(f"Spent {u['spent_tokens']:,} of {int(budget):,} tokens, about ${u['estimated_cost_usd']:.3f} "
                f"(price table needs verification). Calls: {u['api_calls']} to the API, {u['cache_hits']} from the "
                f"cache, {u['fixture_hits']} from fixtures.")
    if bar.button("Clear LLM cache", width="stretch", help="Deletes cached responses; the call log stays"):
        flash("info", f"Deleted {llm.clear_cache()} cached LLM responses.")


def _cs_run(fn, history: list) -> bool:
    try:
        with st.spinner("Extracting claims, scoring relations and extracting entity relations ..."):
            a = fn()
    except Exception as exc:  # dry-run fixture missing, budget, refusal, truncation, API errors
        st.error(f"{type(exc).__name__}: {exc}")
        return False
    history.append(a)
    ss["_cs_show"] = len(history) - 1  # applied before the report selector is drawn
    return True


def _cs_row(a) -> dict:
    r = a.report
    return {"Report": a.label, "Engine": a.engine_version,
            "Verdict": "inconsistent" if r.verdict_inconsistent else "no contradiction found",
            "Clauses": ", ".join(r.verdict_clauses) or "-", "Balanced": "yes" if r.balanced else "no",
            "Conflict": f"{r.conflict:.4f}", "Harmony": "not measured" if r.harmony is None else f"{r.harmony:.4f}",
            "Tension pairs": len(r.tension_pairs), "Clamped claim ids": ", ".join(map(str, r.clamp_set)) or "-",
            "World knowledge": "on" if a.world_knowledge else "off", "Model": a.model}


def _cs_verdict(a) -> None:
    r, claims = a.report, a.graph.claims
    if not r.verdict_inconsistent:
        st.success("No contradiction found by any clause of the verdict.")
        return
    lines = []
    for p, q in r.direct_contradictions:
        lines.append(f"- {CLAUSE_LABEL['direct']}: claims {p} and {q} (confidence ≥ {r.threshold:g})")
    if r.confident_frustrated_cycle:
        lines.append(f"- {CLAUSE_LABEL['claim_balance']}: frustrated cycle through claims "
                     f"{' → '.join(map(str, r.confident_frustrated_cycle))} (edges with confidence ≥ {r.threshold:g})")
    for con in r.verdict_entity_contradictions:
        lines.append(f"- {CLAUSE_LABEL['entity']} ({con.type.replace('_', ' ')} on {con.attribute}): "
                     f"{' → '.join(con.entities)} → {con.entities[0]}, from claims "
                     + ", ".join(f"{c} (\"{claims[c].text}\")" for c in con.claim_ids))
    st.error("**Inconsistent.** Clauses that fired: " + ", ".join(CLAUSE_LABEL[c] for c in r.verdict_clauses)
             + "\n\n" + "\n".join(lines))


def _cs_side_by_side(a, b) -> None:
    """Two reports next to each other, and the scored pairs whose labels differ between them."""
    for col, x in zip(st.columns(2), (a, b)):
        with col:
            r = x.report
            st.markdown(f"**{x.label}**: engine {x.engine_version}, threshold {r.threshold:g}, world knowledge "
                        f"{'on' if x.world_knowledge else 'off'}")
            _cs_verdict(x)
            st.caption(f"Balanced: {'yes' if r.balanced else 'no'}; conflict {r.conflict:.4f}; harmony "
                       f"{'not measured' if r.harmony is None else f'{r.harmony:.3f}'}; {r.n_claims} claims, "
                       f"{r.n_edges} relation edges, {len(r.tension_pairs)} tension pairs.")
    if [c.text for c in a.claims.claims] != [c.text for c in b.claims.claims]:
        st.caption("The two reports have different claims, so their relations are not compared pair by pair.")
        return
    la = {tuple(sorted((int(x.a), int(x.b)))): x for x in a.relations.relations}
    lb = {tuple(sorted((int(x.a), int(x.b)))): x for x in b.relations.relations}
    diff = [{"a": p, "b": q, f"{a.label} ({a.engine_version})": f"{la[p, q].relation} {la[p, q].confidence:g}",
             f"{b.label} ({b.engine_version})": f"{lb[p, q].relation} {lb[p, q].confidence:g}",
             f"rationale in {a.label}": la[p, q].rationale, f"rationale in {b.label}": lb[p, q].rationale}
            for p, q in sorted(set(la) & set(lb)) if la[p, q].relation != lb[p, q].relation]
    st.caption(f"{len(diff)} of {len(set(la) & set(lb))} pairs scored in both reports have different labels.")
    if diff:
        st.dataframe(pd.DataFrame(diff), hide_index=True)


def consistency_panel() -> None:
    st.subheader("Consistency: can the text's claims all be true together?")
    st.caption("Claude extracts the claims, scores how pairs of claims relate, and extracts the relations claims state "
               "between entities. Balance, algebraic conflict, clamped harmony and entity-relation cycles are then "
               "computed exactly. The engine is only as good as the extraction: a contradiction that is not extracted "
               "as a claim or relation is invisible to the mathematics.")
    llm = get_llm()
    up = st.file_uploader("Upload a text file", type=["txt", "md"], key="cs_upload")
    if up is not None and ss.get("_cs_upload_id") != up.file_id:
        ss["_cs_upload_id"] = up.file_id
        ss["cs_text"] = up.getvalue().decode("utf-8", errors="replace")
    _default("cs_text", "")
    text = st.text_area("Text", key="cs_text", height=180, placeholder="Paste the text to check")
    history: list = ss.setdefault("cs_reports", [])
    version = ss.get("llm_engine_version", ENGINE_DEFAULT)
    if st.button("Analyze", type="primary", disabled=not text.strip()):
        _cs_run(lambda: analyze_text(llm, text.strip(), world_knowledge=bool(ss.get("llm_world_knowledge")),
                                     label=f"Report {len(history) + 1}", engine_version=version), history)
    if not history:
        return

    st.markdown("#### Reports")
    st.caption("Every analysis is kept: marking evidence, re-scoring with world knowledge or analyzing with the other "
               "engine version adds a report and leaves the earlier ones as they were.")
    st.dataframe(pd.DataFrame([_cs_row(a) for a in history]), hide_index=True)
    ss["cs_view"] = min(int(ss.pop("_cs_show", ss.get("cs_view", len(history) - 1))), len(history) - 1)
    view = st.selectbox("Show report", list(range(len(history))), key="cs_view",
                        format_func=lambda i: f"{history[i].label} (engine {history[i].engine_version})")
    a = history[view]
    r = a.report
    others = [i for i in range(len(history)) if i != view]
    if others:
        _default("cs_compare", None)
        if "_cs_compare_next" in ss:  # applied before the selector is drawn
            ss["cs_compare"] = ss.pop("_cs_compare_next")
        if ss["cs_compare"] not in [None] + others:
            ss["cs_compare"] = None
        pick = st.selectbox("Side by side with", [None] + others, key="cs_compare",
                            format_func=lambda i: "none" if i is None else
                            f"{history[i].label} (engine {history[i].engine_version})")
        if pick is not None:
            _cs_side_by_side(a, history[pick])
    _cs_verdict(a)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Balanced", "yes" if r.balanced else "no")
    c2.metric("Conflict (Σ λ_min)", f"{r.conflict:.4f}")
    c3.metric("Clamped harmony", "not measured" if r.harmony is None else f"{r.harmony:.3f}")
    c4.metric("Claims / relations", f"{r.n_claims} / {r.n_edges}")
    notes = []
    if r.harmony is None:
        notes.append(f"Harmony not measured: {r.harmony_reason}.")
    if r.unanchored_components and len(r.unanchored_components) < len(r.components):
        parts = [f"claims {', '.join(map(str, comp))} (λ_min {r.component_conflict[r.components.index(comp)]:.4f})"
                 for comp in r.unanchored_components if len(comp) > 1]
        isolated = [comp[0] for comp in r.unanchored_components if len(comp) == 1]
        if isolated:
            parts.append(f"isolated claim{'s' if len(isolated) > 1 else ''} {', '.join(map(str, isolated))}")
        notes.append(f"Unanchored components ({UNANCHORED_NOTE}; harmony is not assigned there): " + "; ".join(parts))
    if any(r.component_degenerate[r.components.index(comp)] for comp in r.unanchored_components):
        notes.append("λ_min is repeated on an unanchored component: x* shows one basis vector of that eigenspace, and "
                     "the residuals there are averaged over the eigenspace, so they do not depend on that choice.")
    for note in notes:
        st.caption(note)

    st.markdown("#### Claims")
    rank = {v: k + 1 for k, v in enumerate(r.residual_ranking)}
    res = np.array([r.claim_residuals[i] if i in rank else 0.0 for i in range(r.n_claims)], dtype=float)
    df = pd.DataFrame({"claim": range(r.n_claims), "kind": a.graph.kinds,
                       "clamped": [i in r.clamp_set for i in range(r.n_claims)],
                       "evidence": [i in a.evidence for i in range(r.n_claims)],
                       "text": [c.text for c in a.graph.claims], "x*": r.truth_assignment, "residual": res,
                       "rank": [rank.get(i) for i in range(r.n_claims)]})
    edited = st.data_editor(
        df, key=f"cs_claims_{view}", hide_index=True, disabled=[c for c in df.columns if c != "evidence"],
        column_config={
            "evidence": st.column_config.CheckboxColumn("mark as evidence",
                                                        help="Clamp this claim to true, like a premise. Premises are "
                                                             "always clamped."),
            "x*": st.column_config.NumberColumn("x*", format="%+.3f"),
            "residual": st.column_config.ProgressColumn("residual", min_value=0.0,
                                                        max_value=float(max(res.max(initial=0.0), 1e-12)),
                                                        format="%.4f")})
    chosen = sorted(int(i) for i, e, k in zip(edited["claim"], edited["evidence"], a.graph.kinds)
                    if e and k != "premise")
    b1, b2, b3, b4 = st.columns(4)
    if b1.button("Re-analyze with this evidence", disabled=chosen == a.evidence, width="stretch"):
        history.append(with_evidence(a, chosen, label=f"Report {len(history) + 1}"))
        ss["_cs_show"] = len(history) - 1
        st.rerun()
    other = not a.world_knowledge
    if b2.button(f"Re-score with world knowledge {'on' if other else 'off'}", width="stretch"):
        if _cs_run(lambda: rescored(llm, a, other, label=f"Report {len(history) + 1}"), history):
            st.rerun()
    swap = next(v for v in ENGINE_VERSIONS if v != a.engine_version)
    if b3.button(f"Analyze with engine {swap}", width="stretch",
                 help="The same text, claims and evidence under the other engine version, as a new report"):
        if _cs_run(lambda: analyze_text(llm, a.text, tag=a.tag, evidence=a.evidence,
                                        world_knowledge=a.world_knowledge, label=f"Report {len(history) + 1}",
                                        engine_version=swap), history):
            ss["_cs_compare_next"] = view
            st.rerun()
    b4.download_button("Export report (JSON)", data=json.dumps(analysis_to_dict(a), indent=1),
                       file_name=f"consistency_{a.tag}_{a.label.replace(' ', '_').lower()}.json",
                       mime="application/json", width="stretch")

    st.plotly_chart(claim_graph_figure(a), key=f"cs_graph_{view}")
    figs = entity_figures(a)
    st.markdown("#### Entity relations")
    if not figs:
        st.caption("No relations between entities were extracted.")
    else:
        cols = st.columns(min(len(figs), 3))
        for k, (attribute, fig, caption) in enumerate(figs):
            with cols[k % len(cols)]:
                st.plotly_chart(fig, key=f"cs_entity_{view}_{attribute}")
                for line in caption:
                    st.caption(line)

    st.markdown("#### Culprits (counterfactual: if this claim were removed)")
    if r.culprits:
        st.dataframe(pd.DataFrame([{"claim": c, "text": a.graph.claims[c].text, "conflict drop": round(dc, 4),
                                    "harmony change": "not measured" if dh is None else round(dh, 4)}
                                   for c, dc, dh in r.culprits]), hide_index=True)
    else:
        st.caption("No claim has a residual, so there is nothing to remove.")
    st.caption("Counterfactuals only: the scores above are computed on the full graph as scored and are never "
               "replaced by these.")
    with st.expander(f"Relations and rationales ({len(a.relations.relations)} scored pairs)"):
        table = pd.DataFrame([{"a": x.a, "b": x.b, "rationale": x.rationale, "relation": x.relation,
                               "confidence": x.confidence} for x in a.relations.relations])
        st.dataframe(table.style.apply(lambda row: [TENSION_STYLE if row["relation"] == "tension" else ""] * len(row),
                                       axis=1) if len(table) else table, hide_index=True)
        if r.tension_pairs:
            st.caption(f"{len(r.tension_pairs)} tension pair{'s' if len(r.tension_pairs) > 1 else ''} (amber): both "
                       "claims can be true, but they sit badly together. Tension makes no edge, so it is not in the "
                       "verdict, balance, conflict, harmony, residuals or culprits.")
        for x in a.diagnostics.get("relations_rescored", []):
            first = x["first"]
            why = ("was for another pair than the one asked about" if x.get("reason") == "other pair" else
                   "had a fragment of JSON in its rationale")
            st.caption(f"Pair ({x['a']}, {x['b']}): its first answer ({first['relation']}, {first['confidence']}) {why}, "
                       "so the pair was scored again on its own. "
                       + ("The second answer replaced it." if x["outcome"] == "replaced" else
                          "That answer was malformed too or left the pair out, so the pair is unscored (no edge)."))
    with st.expander("Extraction diagnostics"):
        st.json(a.diagnostics | {"pair selection": a.pair_info}, expanded=False)


# ------------------------------------------------------------------------------------------ export / run loop
def export_sandbox(sb: Sandbox, figs: dict, slot) -> None:
    with st.spinner("Exporting ..."):
        exps = list((ss.get("exp_results") or {}).values()) or None
        run_dir, info = sb.export("results", figures=figs, experiments=exps)
    msg = f"Exported to {run_dir}"
    if info.get("format") == "html":
        msg += f". {info['note']}"
    slot.success(msg)


def live_view(sb: Sandbox, slots: dict, figs: dict) -> None:
    """Header, graph and traces, redrawn into their slots.

    While running, st.fragment(run_every=1/FPS) advances steps_per_frame per tick. The browser
    schedules these reruns, so a slow client lowers the frame rate instead of queueing frames, and the
    page stays interactive.

    The slots are keyed containers rather than st.empty(): a full rerun resets an st.empty() to an empty
    element, and if the browser renders that before this fragment refills it, the charts are torn down
    and rebuilt. A container keeps its previous content until the new content replaces it in place.
    """
    running = bool(ss.get("running"))
    fps = max(float(sb.cfg.fps), 0.1)

    def fill_slots(*draws) -> None:
        # A tick that races an interrupted full rerun finds its slots unclaimed; a full rerun claims them.
        try:
            for draw in draws:
                draw()
        except StreamlitInvalidLayoutContextError:
            st.rerun()

    @st.fragment(run_every=1.0 / fps if running else None, key="live_state")
    def state_view():
        if consume_selections(sb):
            st.rerun()
        if ss.get("running") and not safe_step(sb, sb.cfg.steps_per_frame):
            st.rerun()
        fill_slots(lambda: render_header(slots["header"], sb), lambda: draw_graph(slots["graph"], sb, figs))

    @st.fragment(run_every=max(1.0, 1.0 / fps) if running else None, key="live_traces")
    def traces_view():
        fill_slots(lambda: draw_traces(slots["traces"], sb, figs))

    state_view()
    traces_view()


# ------------------------------------------------------------------------------------------ main
def main() -> None:
    if "sb" not in ss:
        ss.sb = Sandbox(D, spectrum_fn=spectrum_fn)
        ss.running = False
    sb: Sandbox = ss.sb
    sb.spectrum_fn = spectrum_fn
    consume_selections(sb)
    mode, cfg, act = sidebar(sb)
    if sb.configure(cfg):
        ss.running = False
        flash("info", "Graph, seed or dynamics changed: simulation reset.")
    handle_actions(sb, act)
    show_flash()
    if mode in ("Test Suite", "Geometry Compare", "Consistency"):
        if mode == "Consistency":
            consistency_panel()
        else:
            (test_suite_panel if mode == "Test Suite" else geometry_compare_panel)(cfg)
        if act["export"]:
            export_sandbox(sb, {}, act["export_slot"])
        return
    figs: dict = {}
    st.html(LIVE_CSS)
    slots = {"header": st.container(key="live_header")}
    tabs = st.tabs(TABS)
    with tabs[0]:
        slots["graph"] = graph_tab(sb)
    with tabs[1]:
        spectrum_tab(sb, figs)
    with tabs[2]:
        slots["traces"] = traces_tab(sb)
    with tabs[3]:
        depth_tab(sb, figs)
    with tabs[4]:
        modes_tab(sb)
    with tabs[5]:
        sheaf_tab(sb, figs)
    with tabs[6]:
        constraints_tab(sb, figs)
    with tabs[7]:
        test_suite_panel(cfg)
    live_view(sb, slots, figs)
    if act["export"]:
        export_sandbox(sb, figs, act["export_slot"])


main()
