"""Per-geometry statistics behind E9 (XON_SIM_GEOMETRY_V1_2.md §5) and the Geometry Compare view.

Each ``*_row`` function builds one geometry at one level and returns plain numbers (plus the curves
for its figures under "curves"). The pre-registered predictions and thresholds are in
xon/experiments.py (REGISTRY_V1_2); ``e9_report`` joins the E9 results into one table.
"""
from __future__ import annotations

import time

import numpy as np
import plotly.graph_objects as go
from plotly.colors import qualitative
from scipy import stats
from scipy.spatial import cKDTree

from .config import XonConfig
from .graph import XonGraph
from .growth import build_graph, get_rule
from .metrics import (automorphism_orbits, cluster_purity, degenerate_fraction, einstein_residual, exact_diameter,
                      graph_diameter, kmeans, mass_dimension, plateau_containment, plateau_persistence,
                      plateau_values, region_labels, seam_fraction, spectral_dimension_est, walk_dimension)
from .plots import graph_figure, loglog_figure, staircase_figure
from .spectrum import get_spectrum

GEOMETRIES = ("gasket", "vicsek", "sierpinski_p", "carpet", "lattice", "tree")
E9D_STATUS = "E9d (harmonicity transfer across geometries) is not implemented: skipped at the user's request."


def geometry_config(name: str, cfg: XonConfig) -> XonConfig:
    """cfg with the rule parameters E9 fixes: p of S(p, n) and the tree's branching."""
    if name == "sierpinski_p":
        return cfg.replace(sierpinski_p=int(cfg.e9_sierpinski_p))
    if name == "tree":
        return cfg.replace(branch=int(cfg.e9_tree_branch))
    return cfg


def geometry_label(name: str, cfg: XonConfig) -> str:
    return f"S({int(cfg.e9_sierpinski_p)}, n)" if name == "sierpinski_p" else name


def lattice_side(level: int) -> int:
    """The lattice's E9 "levels": side 3^level + 1, the vertex grid of a carpet cell at that level."""
    return 3 ** int(level) + 1


def build_geometry(name: str, cfg: XonConfig, level: int) -> XonGraph:
    gcfg = geometry_config(name, cfg)
    if name == "lattice":
        return build_graph(gcfg.replace(lattice_side=lattice_side(level)), 0, "lattice")
    return build_graph(gcfg, int(level), name)


def level_sizes(name: str, cfg: XonConfig, n_max: int) -> list[int]:
    """N at levels 0, 1, ... up to and including the first level above n_max (that one is predicted, not built)."""
    if name == "lattice":
        sizes = [lattice_side(0) ** 2]
        while sizes[-1] <= n_max:
            sizes.append(lattice_side(len(sizes)) ** 2)
        return sizes
    gcfg = geometry_config(name, cfg)
    rule = get_rule(name)
    g = rule.seed(gcfg)
    sizes = [g.n()]
    while sizes[-1] <= n_max:
        grow = rule.predict_new_vertices(g, gcfg)
        if grow <= 0:
            break
        sizes.append(g.n() + grow)
        if sizes[-1] <= n_max:
            g, _ = rule.grow(g, None, gcfg)
    return sizes


def band_level(name: str, cfg: XonConfig, lo: int, hi: int) -> tuple[int, bool]:
    """The largest level with lo <= N <= hi, or (if none) the level whose N is nearest the band in log scale."""
    sizes = level_sizes(name, cfg, hi)
    inside = [L for L, n in enumerate(sizes) if lo <= n <= hi]
    if inside:
        return inside[-1], True
    gap = [abs(np.log(n / lo)) if n < lo else abs(np.log(n / hi)) for n in sizes]
    return int(np.argmin(gap)), False


def max_level(name: str, cfg: XonConfig, n_max: int) -> int:
    return max(L for L, n in enumerate(level_sizes(name, cfg, n_max)) if n <= n_max)


def matched_level(name: str, cfg: XonConfig, target_n: int) -> int:
    """The level whose N is nearest target_n in log scale (Geometry Compare's matched N)."""
    sizes = level_sizes(name, cfg, 4 * target_n)
    return int(np.argmin([abs(np.log(n / target_n)) for n in sizes]))


def geometry_rng(rng_seed: int, name: str) -> np.random.Generator:
    """A stream per geometry, so a geometry's numbers do not depend on which others run."""
    return np.random.default_rng([int(rng_seed), *name.encode()])


# ---------------------------------------------------------------------------- E9a: spectral self-similarity
def spectral_row(name: str, cfg: XonConfig, level: int) -> dict:
    """degenerate_fraction at level L, plateau_persistence between L-1 and L, Pearson r over L-2, L-1, L."""
    m, tol = int(cfg.plateau_multiplicity), float(cfg.degeneracy_tol)
    levels = [L for L in (level - 2, level - 1, level) if L >= 0]
    grid = (np.arange(cfg.e1_resample) + 0.5) / cfg.e1_resample
    specs, sizes, curves, resampled = {}, {}, [], {}
    for L in levels:
        g = build_geometry(name, cfg, L)
        spec = get_spectrum(g, cfg.replace(dense_max=max(cfg.dense_max, g.n())))
        specs[L], sizes[L] = spec, g.n()
        resampled[L] = np.interp(grid, np.arange(g.n()) / g.n(), spec.lam)
        curves.append((f"level {L} (N={g.n():,})", spec.lam))
    pearson = {f"{a}-{b}": float(stats.pearsonr(resampled[a], resampled[b])[0]) for a, b in zip(levels, levels[1:])}
    top = specs[level]
    return {
        "level": int(level), "n": sizes[level], "levels": levels, "n_by_level": [sizes[L] for L in levels],
        "degenerate_fraction": degenerate_fraction(top, m, tol),
        "degenerate_fraction_by_level": {str(L): degenerate_fraction(specs[L], m, tol) for L in levels},
        "plateau_persistence": (plateau_persistence(specs[level - 1], top, m, tol) if level - 1 in specs
                                else float("nan")),
        "plateau_containment": (plateau_containment(specs[level - 1], top, m, tol) if level - 1 in specs
                                else float("nan")),
        "plateaus_by_level": {str(L): int(len(plateau_values(specs[L], m, tol))) for L in levels},
        "pearson_r": pearson,
        "curves": {"staircase": curves},
    }


def staircase(name: str, cfg: XonConfig, row: dict) -> go.Figure:
    return staircase_figure(row["curves"]["staircase"],
                            f"{geometry_label(name, cfg)}: sorted eigenvalues vs index/N",
                            plateaus=(3, 5, 6) if name == "gasket" else ())


# ---------------------------------------------------------------------------- E9b: spectral individuation
def clustering_row(name: str, cfg: XonConfig, level: int, rng: np.random.Generator) -> dict:
    """k-way spectral clustering (k = top-level sub-regions) on the lowest k eigenvectors, constant included."""
    g = build_geometry(name, cfg, level)
    labels = region_labels(g)
    if labels is None:
        raise ValueError(f"{name} has no top-level sub-regions")
    k = int(labels.max()) + 1
    spec = get_spectrum(g, cfg)
    x = spec.lowest_modes(k)
    clusters = kmeans(x, k, int(cfg.cluster_restarts), rng)
    lam = spec.lam
    split = k < len(lam) and bool(abs(lam[k] - lam[k - 1]) <= cfg.degeneracy_tol)
    return {
        "level": int(level), "n": g.n(), "k": k,
        "purity": cluster_purity(clusters, labels),
        "seam_fraction": seam_fraction(g, labels),
        "cluster_sizes": sorted(np.bincount(clusters, minlength=k).tolist(), reverse=True),
        "region_sizes": sorted(np.bincount(labels[labels >= 0], minlength=k).tolist(), reverse=True),
        "gap_ratio": float(lam[k] / lam[k - 1]) if k < len(lam) and lam[k - 1] > 0 else float("nan"),
        "splits_eigenspace": split,
        "curves": {"graph": g, "clusters": clusters, "labels": labels},
    }


def cluster_overlay(name: str, cfg: XonConfig, row: dict) -> go.Figure:
    c = row["curves"]
    return graph_figure(c["graph"], c["clusters"], mode="clusters", groups=c["labels"], colorbar_title="cluster",
                        title=f"{geometry_label(name, cfg)}: {row['k']} spectral clusters (dots) over the "
                              f"sub-regions (halos), purity {row['purity']:.3f}", height=520)


# ---------------------------------------------------------------------------- E9c: dimensions
def dimension_row(name: str, cfg: XonConfig, level: int, rng: np.random.Generator,
                  centers_rng: np.random.Generator) -> dict:
    """d_f three ways, d_w (walk MSD), d_s (return probability) and the Einstein residual with each d_f.

    d_f: mass-radius with centers drawn uniformly (centers_rng; judged by E9c_v2). d_f_box: box-counting
    across levels, ln(N_L / N_{L-1}) / ln(diam_L / diam_{L-1}) with double-sweep diameters (E9c_v2; E9c
    replaces it with exact diameters, ``attach_structure``). d_f_deep: mass-radius with the first
    registration's centers (at least R_max from the boundary; judged by E9c_v1). rng drives d_f_deep, d_w
    and d_s in the first registration's order.
    """
    gcfg = geometry_config(name, cfg)
    g = build_geometry(name, cfg, level)
    deep = mass_dimension(g, cfg=cfg, rng=rng, centers="deep")
    walk = walk_dimension(g, cfg=cfg, rng=rng)
    rp = spectral_dimension_est(g, cfg=cfg, rng=rng, window=tuple(cfg.e9_rp_window))
    mass = mass_dimension(g, cfg=cfg, rng=centers_rng, centers="uniform")
    n_next = (lattice_side(level + 1) ** 2 if name == "lattice"
              else g.n() + get_rule(name).predict_new_vertices(g, gcfg))
    d_f_box = float("nan")
    if level >= 1:
        prev = build_geometry(name, cfg, level - 1)
        d_f_box = float(np.log(g.n() / prev.n()) / np.log(mass["diameter"] / graph_diameter(prev)))
    residual = lambda d_f: einstein_residual(rp["d_s"], d_f, walk["d_w"])
    details = ("diameter", "r_max", "fit_from", "eligible", "centers", "centers_at_r_max", "r2")
    return {
        "level": int(level), "n": g.n(), "n_next_level": int(n_next),
        "d_f": mass["d_f"], "d_f_box": d_f_box, "d_f_deep": deep["d_f"], "d_w": walk["d_w"], "d_s": rp["d_s"],
        "einstein_residual": residual(mass["d_f"]), "einstein_residual_box": residual(d_f_box),
        "einstein_residual_deep": residual(deep["d_f"]),
        "mass": {k: mass[k] for k in details},
        "mass_deep": {k: deep[k] for k in details},
        "walk": {k: walk[k] for k in ("t_end", "reached_target", "saturation_msd", "saturation_over_diameter_sq",
                                      "walkers", "starts", "moves", "r2")},
        "return_probability": {"window": list(cfg.e9_rp_window), "r2": rp["r2"]},
        "curves": {"mass": (mass["r"], mass["M"], (mass["fit_from"], mass["r_max"]), mass["d_f"]),
                   "mass_deep": (deep["r"], deep["M"], (deep["fit_from"], deep["r_max"]), deep["d_f"]),
                   "walk": (walk["t"], walk["msd"], (cfg.walk_t_min, walk["t_end"]), walk["slope"]),
                   "rp": (rp["t"], rp["rp"], tuple(cfg.e9_rp_window), rp["slope"])},
    }


def dimension_figures(rows: dict[str, dict], cfg: XonConfig, eid: str = "E9c",
                      deep: bool = False) -> dict[str, go.Figure]:
    """Mass-radius, MSD and return-probability curves of every geometry (log-log, fit ranges solid).

    deep=True draws M(r) from the first registration's centers (E9c_v1).
    """
    label = {name: f"{geometry_label(name, cfg)} L{row['level']}" for name, row in rows.items()}
    series = lambda key: [(label[n], *row["curves"][key]) for n, row in rows.items()]
    centers = "deep centers" if deep else "uniform centers"
    return {
        "mass_radius": loglog_figure(series("mass_deep" if deep else "mass"),
                                     f"{eid}: mass-radius M(r), {centers} (slope = d_f)", "r (hops)", "M(r)"),
        "msd": loglog_figure(series("walk"), f"{eid}: lazy-walk MSD (slope = 2 / d_w)", "t (lazy steps)",
                             "MSD (hops^2)"),
        "return_probability": loglog_figure(series("rp"), f"{eid}: return probability (slope = -d_s / 2)",
                                            "t (lazy steps)", "P(return)"),
    }


def strip_curves(row: dict) -> dict:
    return {k: v for k, v in row.items() if k != "curves"}


# ---------------------------------------------------------------------------- E9c: exact construction check
CLOSED_FORM_GEOMETRIES = ("gasket", "vicsek", "sierpinski_p", "carpet")


def closed_form(name: str, level: int, p: int = 4) -> dict[str, int] | None:
    """Cells, vertices, edges and diameter at a level, from docs/geometry_closed_forms.md; None without a form.

    Level L of sierpinski_p is S(p, L + 1).
    """
    L = int(level)
    if name == "gasket":
        return {"cells": 3 ** L, "vertices": (3 ** (L + 1) + 3) // 2, "edges": 3 ** (L + 1), "diameter": 2 ** L}
    if name == "sierpinski_p":
        n = L + 1
        return {"cells": p ** L, "vertices": p ** n, "edges": p * (p ** n - 1) // 2, "diameter": 2 ** n - 1}
    if name == "vicsek":
        return {"cells": 5 ** L, "vertices": 2 * 5 ** L + 2, "edges": 3 * 5 ** L + 1, "diameter": 3 ** L + 1}
    if name == "carpet":
        return {"cells": 8 ** L, "vertices": (44 * 8 ** L + 56 * 3 ** L + 40) // 35,
                "edges": (12 * 8 ** L + 8 * 3 ** L) // 5, "diameter": 2 * 3 ** L}
    return None


def _layout_permutation(g: XonGraph, image: np.ndarray) -> np.ndarray | None:
    """The permutation sending every vertex v to the vertex placed at image[v]; None if a position has none."""
    scale = float(np.ptp(g.coords, axis=0).max()) or 1.0
    dist, idx = cKDTree(g.coords).query(image, distance_upper_bound=1e-6 * scale)
    return idx.astype(np.int64) if np.isfinite(dist).all() else None


def candidate_symmetries(g: XonGraph) -> list[np.ndarray]:
    """Generators of the symmetries g should have, as vertex permutations for ``automorphism_orbits`` to verify.

    S(p, n): a transposition and a p-cycle of the letters, which generate all p! letter permutations. Gasket: a
    rotation and a reflection of the seed triangle; carpet, vicsek and lattice: of the square. Others: none.
    """
    if "word" in g.labels:
        p, m = g.simplices.shape[1], g.level + 1
        codes = np.asarray(g.labels["word"], dtype=np.int64)
        place = p ** np.arange(m - 1, -1, -1)
        digits = (codes[:, None] // place) % p
        id_of = np.full(p ** m, -1, dtype=np.int64)
        id_of[codes] = np.arange(len(codes))
        return [id_of[(sigma[digits] * place).sum(axis=1)] for sigma in (np.r_[1, 0, 2:p], np.r_[1:p, 0])]
    x = np.asarray(g.coords, dtype=float)
    if g.rule == "gasket":
        corners = x[g.depth == 0]
        lam = np.linalg.solve((corners[1:] - corners[0]).T, (x - corners[0]).T).T
        bary = np.c_[1.0 - lam.sum(axis=1), lam]
        images = (bary @ corners[[1, 2, 0]], bary @ corners[[0, 2, 1]])
    elif g.rule in ("carpet", "vicsek", "lattice"):
        lo, span = x.min(axis=0), np.ptp(x, axis=0)
        u = (x - lo) / span
        images = (np.c_[1.0 - u[:, 1], u[:, 0]] * span + lo, np.c_[1.0 - u[:, 0], u[:, 1]] * span + lo)
    else:
        return []
    return [perm for perm in (_layout_permutation(g, im) for im in images) if perm is not None]


def structure_row(name: str, cfg: XonConfig, level: int) -> dict:
    """Cells, vertices, edges (vertex pairs joined by an edge) and exact diameter of one level, and its closed forms."""
    t0 = time.perf_counter()
    g = build_geometry(name, cfg, level)
    orbits, generators = automorphism_orbits(g, candidate_symmetries(g))
    diam = exact_diameter(g, orbits)
    adj = g.adjacency()
    measured = {"cells": len(g.simplices), "vertices": g.n(),
                "edges": int((adj.nnz - np.count_nonzero(adj.diagonal())) // 2), "diameter": diam["diameter"]}
    form = closed_form(name, level, int(cfg.e9_sierpinski_p))
    return {"level": int(level), **measured, "closed_form": form,
            "matches": {k: measured[k] == form[k] for k in ("vertices", "edges", "diameter")} if form else {},
            "symmetry_generators": generators, "orbits": diam["orbits"], "bfs": diam["bfs"],
            "eccentricity_bfs": diam["eccentricity_bfs"], "ratio_vertices": float("nan"),
            "ratio_cells": float("nan"), "seconds": time.perf_counter() - t0}


def structure_rows(name: str, cfg: XonConfig, levels) -> list[dict]:
    """``structure_row`` at each level, with ln(X_L / X_{L-1}) / ln(D_L / D_{L-1}) for X = vertices and cells."""
    rows = [structure_row(name, cfg, L) for L in levels]
    for prev, row in zip(rows, rows[1:]):
        step = np.log(row["diameter"] / prev["diameter"]) if row["level"] == prev["level"] + 1 else 0.0
        if step > 0:
            row["ratio_vertices"] = float(np.log(row["vertices"] / prev["vertices"]) / step)
            row["ratio_cells"] = float(np.log(row["cells"] / prev["cells"]) / step)
    return rows


def attach_structure(row: dict, structure: list[dict]) -> dict:
    """Put the exact structure rows on a dimension row; its d_f_box becomes the exact vertex ratio at its level."""
    at = {s["level"]: s for s in structure}.get(row["level"])
    row["structure"] = structure
    row["d_f_box"] = at["ratio_vertices"] if at else float("nan")
    row["einstein_residual_box"] = einstein_residual(row["d_s"], row["d_f_box"], row["d_w"])
    return row


def mass_trend(name: str, cfg: XonConfig, levels, rng_seed: int, centers: int) -> list[dict]:
    """Mass-radius d_f at each level with ``centers`` deep and ``centers`` uniform centers (a stream for each)."""
    tcfg = cfg.replace(mass_centers=int(centers), mass_uniform_centers=int(centers))
    rows = []
    for L in levels:
        g = build_geometry(name, cfg, L)
        est = {kind: mass_dimension(g, cfg=tcfg, rng=geometry_rng(rng_seed, f"{name}:trend:{L}:{kind}"),
                                    centers=kind) for kind in ("deep", "uniform")}
        rows.append({"level": int(L), "n": g.n(), "d_f_deep": est["deep"]["d_f"],
                     "d_f_uniform": est["uniform"]["d_f"], "r_max": est["deep"]["r_max"],
                     "fit_from": est["deep"]["fit_from"], "deep_centers": est["deep"]["centers"],
                     "uniform_centers_at_r_max": est["uniform"]["centers_at_r_max"]})
    return rows


def ratio_figure(structures: dict[str, list[dict]], d_f: dict[str, float], cfg: XonConfig) -> go.Figure:
    """The ratio sequences by level (solid: vertices, dashed: cells) against the theoretical d_f (dotted)."""
    fig = go.Figure()
    for i, (name, rows) in enumerate(structures.items()):
        color, label = qualitative.Plotly[i % len(qualitative.Plotly)], geometry_label(name, cfg)
        rows = [r for r in rows if np.isfinite(r["ratio_vertices"])]
        if not rows:
            continue
        x = [r["level"] for r in rows]
        for key, dash in (("vertices", "solid"), ("cells", "dash")):
            fig.add_trace(go.Scatter(x=x, y=[r[f"ratio_{key}"] for r in rows], mode="lines+markers",
                                     name=f"{label}: {key}", line=dict(color=color, dash=dash)))
        fig.add_trace(go.Scatter(x=[x[0], x[-1]], y=[d_f[name]] * 2, mode="lines", name=f"{label}: {d_f[name]:.3f}",
                                 line=dict(color=color, dash="dot")))
    fig.update_layout(title="E9c: ln(X_L / X_{L-1}) / ln(D_L / D_{L-1}) by level (dotted: theoretical d_f)",
                      xaxis_title="level L", yaxis_title="ratio", height=440)
    return fig


def trend_figure(rows: list[dict], name: str, d_f: float, cfg: XonConfig) -> go.Figure:
    x = [r["level"] for r in rows]
    fig = go.Figure()
    for key, label in (("d_f_deep", "deep centers"), ("d_f_uniform", "uniform centers")):
        fig.add_trace(go.Scatter(x=x, y=[r[key] for r in rows], mode="lines+markers", name=label))
    fig.add_trace(go.Scatter(x=[x[0], x[-1]], y=[d_f] * 2, mode="lines", line=dict(dash="dot"),
                             name=f"theoretical {d_f:.3f}"))
    fig.update_layout(title=f"E9c: {geometry_label(name, cfg)} mass-radius d_f by level (reported only)",
                      xaxis_title="level L", yaxis_title="d_f (mass-radius)", height=380)
    return fig


def seam_purity_figure(rows: dict[str, dict], cfg: XonConfig) -> go.Figure:
    # Several geometries sit within 0.003 of each other, so open markers and a legend instead of text labels.
    symbols = ("circle-open", "square-open", "diamond-open", "triangle-up-open", "cross-open", "x-open")
    fig = go.Figure()
    for i, (name, row) in enumerate(rows.items()):
        fig.add_trace(go.Scatter(
            x=[row["seam_fraction"]], y=[row["purity"]], mode="markers",
            name=f"{geometry_label(name, cfg)} (seam {row['seam_fraction']:.3f}, purity {row['purity']:.3f})",
            marker=dict(size=14, symbol=symbols[i % len(symbols)], line=dict(width=2))))
    fig.update_layout(title="E9b: seam fraction vs clustering purity", xaxis_title="seam_fraction",
                      yaxis_title="purity", height=380, showlegend=True, margin=dict(l=10, r=10, t=40, b=10))
    return fig


# ---------------------------------------------------------------------------- report (V1.2 §5.3)
def _fmt(x, digits: int = 3) -> str:
    return "-" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{digits}f}"


def _verdict(match) -> str:
    return {True: "match", False: "MISMATCH", None: "exploratory"}.get(match, "-")


# (row key, column): E9c's judged d_w, d_s and residual with the theoretical d_f, then the reported d_f estimates
E9C_COLUMNS = (("d_w", "d_w"), ("d_s", "d_s"), ("einstein_residual_theory", "Residual (theory d_f)"),
               ("d_f_box", "d_f (box)"), ("d_f", "d_f (mass, uniform)"), ("d_f_deep", "d_f (mass, deep)"))


def _count(x) -> str:
    return f"{x:,}" if isinstance(x, (int, np.integer)) else str(x)


def exact_summary(row: dict) -> str:
    """E9c's exact counts in words: the levels checked, and every count that differs from its closed form."""
    s = row.get("structure") or []
    if not s:
        return "-"
    if not s[0]["closed_form"]:
        return "no closed form"
    span = f"levels {s[0]['level']}-{s[-1]['level']}" if len(s) > 1 else f"level {s[0]['level']}"
    bad = [f"{k} at level {r['level']} ({_count(r[k])}, form {_count(r['closed_form'][k])})"
           for r in s for k, ok in r["matches"].items() if not ok]
    return f"all equal, {span}" if not bad else "differ: " + "; ".join(bad)


def e9_report(results, cfg: XonConfig) -> tuple[str, list[dict]]:
    """One row per geometry across the E9 experiments that ran, and the header (dynamics module, E9d status).

    Columns of experiments that did not run are left out; "-" marks a geometry an experiment does not cover.
    """
    by_id = {r.id: r for r in results if r.id in ("E9a", "E9b", "E9c") and r.metrics.get("rows")}
    names = [n for n in GEOMETRIES if any(n in r.metrics["rows"] for r in by_id.values())]
    rows = []
    for name in names:
        row = {"Geometry": geometry_label(name, cfg)}
        a, b, c = (by_id[e].metrics["rows"].get(name) if e in by_id else None for e in ("E9a", "E9b", "E9c"))
        if "E9a" in by_id or "E9b" in by_id:
            band = a or b
            row["E9a/b level (N)"] = (f"{band['level']} ({band['n']:,})"
                                      + ("" if band.get("in_band", True) else ", outside the band")) if band else "-"
        if "E9a" in by_id:
            row["Degenerate fraction"] = _fmt(a["degenerate_fraction"]) if a else "-"
            row["Plateau persistence"] = _fmt(a["plateau_persistence"]) if a else "-"
            row["Plateau containment"] = _fmt(a["plateau_containment"]) if a else "-"
            row["Pearson r"] = ", ".join(f"{v:.4f}" for v in a["pearson_r"].values()) if a else "-"
        if "E9b" in by_id:
            row["k"] = str(b["k"]) if b else "-"
            row["Purity"] = _fmt(b["purity"]) if b else "-"
            row["Seam fraction"] = _fmt(b["seam_fraction"]) if b else "-"
        if "E9c" in by_id:
            row["E9c level (N)"] = f"{c['level']} ({c['n']:,})" if c else "-"
            row["N, E, D vs closed forms"] = exact_summary(c) if c else "-"
            for key, col in E9C_COLUMNS:
                row[col] = _fmt(c.get(key)) if c else "-"
        verdicts = [f"{eid} {_verdict(src['matches'])}" for eid, src in (("E9a", a), ("E9b", b), ("E9c", c)) if src]
        if c and c.get("retried"):
            verdicts[-1] += f" (at level {c['level']} after level {c['retried']['level']})"
        if c and c["matches"] is False and (a or b):
            verdicts.append("E9c failed, so E9a / E9b are not interpretable for this geometry yet (spec 5.2)")
        row["Predicted vs observed"] = "; ".join(verdicts)
        rows.append(row)
    header = (f"E9 report, geometries as rows. Dynamics module: none (E9a-E9c are structural; the configured "
              f"dynamics is {cfg.dynamics}). {E9D_STATUS}")
    return header, rows
