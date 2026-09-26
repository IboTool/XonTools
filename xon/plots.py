"""Plotly figure builders shared by the Streamlit app and the experiments."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from .graph import XonGraph
from .metrics import fit_exponential, fit_powerlaw

PARTITION_COLORS = [[0.0, "#1f77b4"], [0.5, "#1f77b4"], [0.5, "#d62728"], [1.0, "#d62728"]]
CLUSTER_COLORS = ("#1f77b4", "#2ca02c", "#d62728", "#9467bd", "#ff7f0e", "#8c564b", "#e377c2", "#17becf",
                  "#bcbd22", "#7f7f7f")


def _discrete_scale(n: int) -> list:
    cols = [CLUSTER_COLORS[i % len(CLUSTER_COLORS)] for i in range(max(n, 1))]
    return [[f, c] for i, c in enumerate(cols) for f in (i / len(cols), (i + 1) / len(cols))]


def _display_subset(g: XonGraph, keep, max_vertices: int, seed: int) -> np.ndarray:
    n = g.n()
    if n <= max_vertices:
        return np.arange(n)
    rng = np.random.default_rng(seed)
    must = np.unique(np.asarray([v for v in (keep or []) if 0 <= v < n], dtype=np.int64))
    front = np.setdiff1d(g.frontier_vertices(), must)
    budget = max_vertices - len(must)
    if len(front) >= budget:
        chosen = rng.choice(front, size=budget, replace=False)
    else:
        rest = np.setdiff1d(np.arange(n), np.concatenate([must, front]))
        chosen = np.concatenate([front, rng.choice(rest, size=budget - len(front), replace=False)])
    return np.sort(np.concatenate([must, chosen]))


def graph_figure(g: XonGraph, values: np.ndarray, mode: str = "phase", sizes: np.ndarray | None = None,
                 title: str = "", keep=None, max_vertices: int = 5000, max_edges: int = 20000,
                 hover=None, colorbar_title: str = "", seed: int = 0,
                 height: int = 560, highlight: int | None = None,
                 groups: np.ndarray | None = None) -> go.Figure:
    """Vertices colored by ``values`` (mode: phase | diverging | partition | clusters | sequential).

    ``hover`` is a list of per-vertex strings or a callable mapping displayed indices to strings.
    ``highlight`` draws a ring around one vertex (the sandbox's probe target).
    ``groups`` (labels 0..k-1, -1 = none) draws one hue per group at 30% opacity behind the vertices.
    Arrays are sent as float32: the figure is redrawn every frame while the sandbox runs.
    """
    xy = g.layout2d().astype(np.float32)
    idx = _display_subset(g, keep, max_vertices, seed)
    notes = []
    if len(idx) < g.n():
        notes.append(f"showing {len(idx):,} of {g.n():,} vertices")
    shown = np.zeros(g.n(), dtype=bool)
    shown[idx] = True
    edges = g.edges[shown[g.edges[:, 0]] & shown[g.edges[:, 1]]] if g.n_edges() else g.edges
    if len(edges) > max_edges:
        sel = np.random.default_rng(seed + 1).choice(len(edges), size=max_edges, replace=False)
        notes.append(f"{max_edges:,} of {len(edges):,} edges")
        edges = edges[np.sort(sel)]
    # WebGL only pays off for large graphs; without GPU acceleration it is far slower than SVG
    scatter = go.Scattergl if len(idx) > 2000 else go.Scatter
    fig = go.Figure()
    if len(edges):
        ex = np.full(3 * len(edges), np.nan, dtype=np.float32)
        ey = np.full(3 * len(edges), np.nan, dtype=np.float32)
        ex[0::3], ex[1::3] = xy[edges[:, 0], 0], xy[edges[:, 1], 0]
        ey[0::3], ey[1::3] = xy[edges[:, 0], 1], xy[edges[:, 1], 1]
        fig.add_trace(scatter(x=ex, y=ey, mode="lines", hoverinfo="skip", showlegend=False,
                              line=dict(color="rgba(120,120,120,0.35)", width=1)))
    v = np.asarray(values, dtype=np.float32)[idx]
    marker = dict(color=v, showscale=True, colorbar=dict(title=colorbar_title, thickness=12))
    if mode == "phase":
        marker.update(colorscale="Twilight", cmin=-np.pi, cmax=np.pi)
    elif mode == "diverging":
        lim = float(np.nanmax(np.abs(v))) if len(v) else 1.0
        marker.update(colorscale="RdBu", cmin=-lim, cmax=lim)
    elif mode == "partition":
        marker.update(colorscale=PARTITION_COLORS, cmin=0, cmax=1, colorbar=dict(
            title=colorbar_title, tickvals=[0.25, 0.75], ticktext=["-", "+"], thickness=12))
    elif mode == "clusters":
        k = int(np.nanmax(v)) + 1 if len(v) else 1
        marker.update(colorscale=_discrete_scale(k), cmin=-0.5, cmax=k - 0.5, colorbar=dict(
            title=colorbar_title, tickvals=list(range(k)), thickness=12))
    else:
        marker.update(colorscale="Viridis")
    if sizes is None:
        marker["size"] = 7 if len(idx) < 2000 else 4
    else:
        s = np.asarray(sizes, dtype=np.float32)[idx]
        top = float(s.max()) if len(s) and s.max() > 0 else 1.0
        marker["size"] = (3 + 11 * s / top).astype(np.float32)
    if groups is not None:
        lab = np.asarray(groups)[idx]
        halo = float(np.max(marker["size"])) + 8.0
        for j in range(int(lab.max()) + 1 if len(lab) else 0):
            sel = idx[lab == j]
            fig.add_trace(scatter(x=xy[sel, 0], y=xy[sel, 1], mode="markers", hoverinfo="skip",
                                  showlegend=False, marker=dict(size=halo, opacity=0.3, line=dict(width=0),
                                                                color=CLUSTER_COLORS[j % len(CLUSTER_COLORS)])))
    if callable(hover):
        text = list(hover(idx))
    else:
        text = [hover[i] for i in idx] if hover is not None else None
    if highlight is not None and 0 <= highlight < g.n() and shown[highlight]:
        fig.add_trace(scatter(x=xy[[highlight], 0], y=xy[[highlight], 1], mode="markers", hoverinfo="skip",
                              showlegend=False, marker=dict(size=18, color="rgba(0,0,0,0)",
                                                            line=dict(color="black", width=2))))
    fig.add_trace(scatter(
        x=xy[idx, 0], y=xy[idx, 1], mode="markers", marker=marker, customdata=idx.astype(np.int32),
        text=text,
        hovertemplate="%{text}<extra></extra>" if hover is not None else "vertex %{customdata}<extra></extra>",
        showlegend=False))
    full_title = title + (f"  ({'; '.join(notes)})" if notes else "")
    # Fixed ranges and a uirevision keep the view still when the figure is redrawn every frame: autorange
    # would re-pad for the changing marker sizes, and zoom / pan survive updates until the rule changes.
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    span = float((hi - lo).max())
    pad = 0.04 * span if span > 0 else 1.0
    fig.update_layout(title=full_title, height=height, margin=dict(l=10, r=10, t=40, b=10),
                      plot_bgcolor="white", dragmode="pan", uirevision=g.rule)
    fig.update_xaxes(visible=False, range=[float(lo[0]) - pad, float(hi[0]) + pad])
    fig.update_yaxes(visible=False, range=[float(lo[1]) - pad, float(hi[1]) + pad], scaleanchor="x",
                     scaleratio=1)
    return fig


def staircase_figure(curves: list[tuple], title: str = "Sorted eigenvalues", plateaus=(3, 5, 6)) -> go.Figure:
    """Each curve: (label, sorted eigenvalues[, N]) plotted against index / N.

    N defaults to the number of eigenvalues; pass it for sparse spectra (lowest k modes only).
    ``plateaus`` are drawn as dotted lines (default: the gasket's lambda = 3, 5, 6).
    """
    fig = go.Figure()
    for i, curve in enumerate(curves):
        label, lam = curve[0], curve[1]
        n = curve[2] if len(curve) > 2 else len(lam)
        x = np.arange(len(lam)) / max(n, 1)
        last = i == len(curves) - 1
        fig.add_trace(go.Scatter(x=x, y=lam, mode="lines", name=label,
                                 line=dict(width=2.5 if last else 1.2), opacity=1.0 if last else 0.55))
    for v in plateaus:
        fig.add_hline(y=v, line=dict(color="gray", dash="dot", width=1))
    fig.update_layout(title=title, xaxis_title="index / N", yaxis_title="lambda", height=420,
                      margin=dict(l=10, r=10, t=40, b=10))
    return fig


def loglog_figure(series: list[tuple], title: str, x_title: str, y_title: str) -> go.Figure:
    """Each series: (label, x, y, (fit_lo, fit_hi), slope); the fitted range is drawn solid, the rest faint."""
    fig = go.Figure()
    for i, (label, x, y, (lo, hi), slope) in enumerate(series):
        x, y = np.asarray(x, float), np.asarray(y, float)
        color = CLUSTER_COLORS[i % len(CLUSTER_COLORS)]
        fit = (x >= lo) & (x <= hi)
        fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line=dict(color=color, width=1), opacity=0.4,
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=x[fit], y=y[fit], mode="lines", line=dict(color=color, width=2.5),
                                 name=f"{label} (slope {slope:.3f})"))
    fig.update_layout(title=title, height=420, margin=dict(l=10, r=10, t=40, b=10))
    fig.update_xaxes(type="log", title=x_title)
    fig.update_yaxes(type="log", title=y_title)
    return fig


def stacked_figure(x, panels: list[tuple], vlines=(), panel_height: int = 165, gap: float = 0.045,
                   x_title: str = "step") -> go.Figure:
    """Vertically stacked panels sharing one x axis.

    ``panels``: list of (title, [(name, y, color, width), ...], log_y). Axes are laid out directly
    because make_subplots is ~20x slower, which matters when the figure is redrawn every frame.
    """
    n = len(panels)
    h = (1.0 - gap * (n - 1)) / n
    layout: dict = {"annotations": [], "shapes": [], "height": panel_height * n + 90,
                    "margin": dict(l=10, r=10, t=40, b=10), "legend": dict(orientation="h", y=-0.06)}
    data = []
    for i, (title, series, log_y) in enumerate(panels):
        ax = "" if i == 0 else str(i + 1)
        top = min(1.0, 1.0 - i * (h + gap))
        layout[f"yaxis{ax}"] = {"domain": [max(0.0, top - h), top], "anchor": f"x{ax}",
                                "type": "log" if log_y else "linear"}
        layout[f"xaxis{ax}"] = {"anchor": f"y{ax}", "showticklabels": i == n - 1}
        if i:
            layout[f"xaxis{ax}"]["matches"] = "x"
        if i == n - 1:
            layout[f"xaxis{ax}"]["title"] = {"text": x_title}
        layout["annotations"].append({"text": title, "x": 0.5, "y": top, "xref": "paper", "yref": "paper",
                                      "xanchor": "center", "yanchor": "bottom", "showarrow": False})
        for xv in vlines:
            layout["shapes"].append({"type": "line", "x0": xv, "x1": xv, "xref": f"x{ax}", "y0": 0, "y1": 1,
                                     "yref": f"y{ax} domain",
                                     "line": {"color": "rgba(0,0,0,0.4)", "dash": "dot", "width": 1}})
        for name, y, color, width in series:
            data.append(go.Scatter(x=x, y=y, mode="lines", name=name, line=dict(color=color, width=width),
                                   xaxis=f"x{ax}", yaxis=f"y{ax}"))
    return go.Figure(data=data, layout=layout)


def depth_energy_figure(E: np.ndarray, title: str = "") -> go.Figure:
    """E[d] on log-log and log-linear axes with both fits (fits use d >= 1)."""
    from plotly.subplots import make_subplots
    E = np.asarray(E, dtype=float)
    d = np.arange(len(E))
    pw, ex = fit_powerlaw(E), fit_exponential(E)
    fig = make_subplots(rows=1, cols=2, subplot_titles=(
        f"log-log: power law R2 = {pw['r2']:.3f}", f"log-linear: exponential R2 = {ex['r2']:.3f}"))
    sel = (d >= 1) & (E > 0)
    fig.add_trace(go.Scatter(x=d[sel], y=E[sel], mode="markers+lines", name="E[d]"), row=1, col=1)
    fig.add_trace(go.Scatter(x=d[E > 0], y=E[E > 0], mode="markers+lines", name="E[d]", showlegend=False),
                  row=1, col=2)
    if np.isfinite(pw["r2"]):
        xs = d[sel].astype(float)
        fig.add_trace(go.Scatter(x=xs, y=np.exp(pw["intercept"]) * xs ** pw["slope"], mode="lines",
                                 name="power-law fit", line=dict(dash="dash")), row=1, col=1)
    if np.isfinite(ex["r2"]):
        xs = d[sel].astype(float)
        fig.add_trace(go.Scatter(x=xs, y=np.exp(ex["intercept"] + ex["slope"] * xs), mode="lines",
                                 name="exponential fit", line=dict(dash="dash")), row=1, col=2)
    fig.update_xaxes(type="log", title="depth d", row=1, col=1)
    fig.update_yaxes(type="log", title="E[d]", row=1, col=1)
    fig.update_xaxes(title="depth d", row=1, col=2)
    fig.update_yaxes(type="log", row=1, col=2)
    fig.update_layout(title=title, height=380, margin=dict(l=10, r=10, t=60, b=10))
    return fig
