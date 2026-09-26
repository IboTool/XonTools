"""Figures of the Consistency view (XON_A1_CONSISTENCY.md §7): the claim graph drawn with V1's graph_figure, and one
entity-graph panel per attribute."""
from __future__ import annotations

import textwrap

import numpy as np
import plotly.graph_objects as go

from ..graph import graph_from_edges
from ..plots import graph_figure
from .engine import Analysis

SUPPORT_COLOR, CONTRADICT_COLOR, CYCLE_COLOR = "#1f77b4", "#d62728", "#ff7f0e"
UNANCHORED_NOTE = "no premise, evidence or asserted claim anchors these claims"


def _wrap(text: str, width: int = 60) -> str:
    return "<br>".join(textwrap.wrap(text, width)) or text


def claim_graph_figure(a: Analysis, height: int = 540) -> go.Figure:
    """Vertices = claims coloured by x*; edge colour by sign, width by weight; clamped claims ringed; unanchored
    components shaded when other components are anchored; the frustrated cycle highlighted."""
    sg, rep = a.graph, a.report
    n = sg.n
    if n == 0:
        return go.Figure(layout=dict(title="No claims were extracted", height=200))
    xy = sg.graph.layout2d()
    clamped = set(rep.clamp_set)
    hover = [f"<b>claim {i}</b> ({c.kind}{', clamped' if i in clamped else ''})<br>{_wrap(c.text)}<br>"
             f"x* = {rep.truth_assignment[i]:+.3f}, residual = {rep.claim_residuals[i]:.4f}"
             for i, c in enumerate(sg.claims)]
    base = graph_figure(graph_from_edges(n, np.zeros((0, 2)), coords=xy, rule="claims"), rep.truth_assignment,
                        mode="diverging", hover=hover, colorbar_title="x*", height=height,
                        title="Claim graph: blue supports, red contradicts, width = confidence")
    for trace in base.data:
        if getattr(trace.marker, "colorscale", None) is not None:
            trace.marker.update(cmin=-1.0, cmax=1.0, size=16, line=dict(color="white", width=1))
    under, over = [], []
    unanchored = ([v for comp in rep.unanchored_components for v in comp]
                  if len(rep.unanchored_components) < len(rep.components) else [])
    if unanchored:
        under.append(go.Scatter(x=xy[unanchored, 0], y=xy[unanchored, 1], mode="markers", hoverinfo="skip",
                                name=UNANCHORED_NOTE, marker=dict(size=34, color="rgba(150,150,150,0.28)")))
    mid_x, mid_y, mid_text = [], [], []
    for (i, j), s, w, r in zip(sg.edges.tolist(), sg.sign, sg.weight, sg.edge_relation):
        under.append(go.Scatter(x=xy[[i, j], 0], y=xy[[i, j], 1], mode="lines", hoverinfo="skip", showlegend=False,
                                line=dict(color=SUPPORT_COLOR if s > 0 else CONTRADICT_COLOR, width=1 + 5 * w)))
        mid_x.append(xy[[i, j], 0].mean())
        mid_y.append(xy[[i, j], 1].mean())
        mid_text.append(f"<b>{i} {r.relation} {j}</b> (confidence {r.confidence:.2f}, residual "
                        f"{rep.edge_residuals[(i, j)]:.4f})<br>{_wrap(r.rationale)}")
    if mid_x:
        under.append(go.Scatter(x=mid_x, y=mid_y, mode="markers", text=mid_text, showlegend=False,
                                hovertemplate="%{text}<extra></extra>", marker=dict(size=10, opacity=0)))
    if rep.frustrated_cycle:
        loop = rep.frustrated_cycle + rep.frustrated_cycle[:1]
        under.append(go.Scatter(x=xy[loop, 0], y=xy[loop, 1], mode="lines", hoverinfo="skip",
                                name="shortest frustrated cycle",
                                line=dict(color=CYCLE_COLOR, width=10), opacity=0.45))
    if clamped:
        cl = sorted(clamped)
        over.append(go.Scatter(x=xy[cl, 0], y=xy[cl, 1], mode="markers", hoverinfo="skip", name="clamped (+1)",
                               marker=dict(size=24, color="rgba(0,0,0,0)", line=dict(color="black", width=2.5))))
    labels = go.Scatter(x=xy[:, 0], y=xy[:, 1], mode="text", text=[str(i) for i in range(n)], hoverinfo="skip",
                        showlegend=False, textfont=dict(size=10, color="black"))
    fig = go.Figure(data=[*under, *base.data, labels, *over], layout=base.layout)
    fig.update_layout(showlegend=bool(unanchored or clamped or rep.frustrated_cycle),
                      legend=dict(orientation="h", y=-0.02), dragmode="pan")
    return fig


def entity_figures(a: Analysis, height: int = 360) -> list[tuple[str, go.Figure, list[str]]]:
    """Per attribute: (attribute, figure, caption lines). Same relations solid, different dashed, greater as arrows
    from the greater entity; relations of a reported contradiction highlighted."""
    eg, rep = a.entities, a.report
    out = []
    flagged = {}
    for con in rep.entity_contradictions:
        flagged.setdefault(con.attribute, set()).update(con.relations)
    for attribute in eg.attributes():
        ids = [i for i, r in enumerate(eg.relations) if r.attribute == attribute]
        ents = sorted({e for i in ids for e in (eg.relations[i].a, eg.relations[i].b)})
        ang = 2 * np.pi * np.arange(len(ents)) / max(len(ents), 1) + np.pi / 2
        pos = {e: (float(np.cos(t)), float(np.sin(t))) for e, t in zip(ents, ang)}
        fig = go.Figure()
        hot = flagged.get(attribute, set())
        for i in ids:
            r = eg.relations[i]
            (x0, y0), (x1, y1) = pos[r.a], pos[r.b]
            color = CYCLE_COLOR if i in hot else ("#444" if r.kind != "different" else CONTRADICT_COLOR)
            width = 4 if i in hot else 2
            if r.kind == "greater":
                fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
                                   showarrow=True, arrowhead=3, arrowsize=1.2, arrowwidth=width, arrowcolor=color,
                                   standoff=14, startstandoff=14)
            else:
                fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines", hoverinfo="skip", showlegend=False,
                                         line=dict(color=color, width=width,
                                                   dash="dash" if r.kind == "different" else "solid")))
            fig.add_trace(go.Scatter(x=[(x0 + x1) / 2], y=[(y0 + y1) / 2], mode="markers", showlegend=False,
                                     marker=dict(size=10, opacity=0),
                                     hovertemplate=f"claim {r.claim_id}: {r.a} {r.kind} {r.b} "
                                                   f"(confidence {r.confidence:.2f})<extra></extra>"))
        fig.add_trace(go.Scatter(x=[pos[e][0] for e in ents], y=[pos[e][1] for e in ents], mode="markers+text",
                                 text=ents, textposition="top center", hoverinfo="text", showlegend=False,
                                 marker=dict(size=16, color="#9ecae1", line=dict(color="#08519c", width=1))))
        fig.update_layout(height=height, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="white",
                          title=f"{attribute} ({eg.arity_of(attribute)})")
        fig.update_xaxes(visible=False, range=[-1.5, 1.5])
        fig.update_yaxes(visible=False, range=[-1.4, 1.5], scaleanchor="x", scaleratio=1)
        caption = [f"Arity {eg.arity_of(attribute)}"
                   + (f', from: "{eg.arity_span[attribute]}"' if eg.arity_span.get(attribute) else
                      " (not established by the text; treated as more than two values)")]
        for con in rep.entity_contradictions:
            if con.attribute == attribute:
                caption.append(f"Contradiction ({con.type.replace('_', ' ')}): {' → '.join(con.entities)} → "
                               f"{con.entities[0]}; claims {', '.join(map(str, con.claim_ids))}; "
                               f"lowest confidence {con.min_confidence:.2f}")
        out.append((attribute, fig, caption))
    return out
