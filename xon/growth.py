"""GrowthRule interface and the rules: gasket, simplex, adaptive, tree, lattice (§3.2) and the V1.2
geometry family carpet, vicsek and sierpinski_p (XON_SIM_GEOMETRY_V1_2.md §3).

Adding a rule = one class with ``name``, ``seed(cfg)``, ``grow(g, state, cfg, rng=None)`` and
``predict_new_vertices(g, cfg)`` (net number of vertices one growth step adds; 0 = the rule does not
grow) plus one entry in ``RULES``.
"""
from __future__ import annotations

from dataclasses import replace as dc_replace
from typing import Any, Protocol

import numpy as np

from .graph import XonGraph, canonical_edges, coord_keys, principal_axes, simplex_edges


class GrowthRule(Protocol):
    name: str

    def seed(self, cfg) -> XonGraph: ...

    def grow(self, g: XonGraph, state: Any, cfg, rng: np.random.Generator | None = None
             ) -> tuple[XonGraph, Any]: ...

    def predict_new_vertices(self, g: XonGraph, cfg) -> int: ...


# ---------------------------------------------------------------------------- helpers
def regular_simplex(n: int) -> np.ndarray:
    """Vertices (n+1, n) of a regular n-simplex with unit edge length."""
    if n == 1:
        return np.array([[0.0], [1.0]])
    if n == 2:
        return np.array([[0.0, 0.0], [1.0, 0.0], [0.5, np.sqrt(3.0) / 2.0]])
    m = n + 1
    helmert = np.zeros((m, n))
    for j in range(n):
        helmert[: j + 1, j] = 1.0
        helmert[j + 1, j] = -(j + 1.0)
        helmert[:, j] /= np.sqrt((j + 1.0) * (j + 2.0))
    return helmert / np.sqrt(2.0)


def interpolate_amplitudes(a1: np.ndarray, a2: np.ndarray) -> np.ndarray:
    """Mean of endpoint amplitudes |a| combined with the circular mean of their phases."""
    amp = 0.5 * (np.abs(a1) + np.abs(a2))
    with np.errstate(invalid="ignore", divide="ignore"):
        u1 = np.where(np.abs(a1) > 0, a1 / np.abs(a1), 0)
        u2 = np.where(np.abs(a2) > 0, a2 / np.abs(a2), 0)
    u = u1 + u2
    phase = np.where(np.abs(u) > 1e-12, np.angle(u), np.angle(a1))
    return amp * np.exp(1j * phase)


def interpolate_weighted(a: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Row i: weighted mean of the amplitudes |a[i]| with the weighted circular mean of their phases.

    a is (n, k) parent amplitudes, w (n, k) or (k,) weights summing to 1; two equal weights give
    ``interpolate_amplitudes``.
    """
    a = np.asarray(a, dtype=complex)
    w = np.broadcast_to(np.asarray(w, dtype=float), a.shape)
    amp = np.abs(a)
    with np.errstate(invalid="ignore", divide="ignore"):
        unit = np.where(amp > 0, a / amp, 0)
    u = (w * unit).sum(axis=1)
    fallback = np.angle(a[np.arange(len(a)), np.argmax(w, axis=1)])
    phase = np.where(np.abs(u) > 1e-12, np.angle(u), fallback)
    return (w * amp).sum(axis=1) * np.exp(1j * phase)


def _extend_state(state: Any, new_a: np.ndarray) -> Any:
    if state is None:
        return None
    return dc_replace(state, a=np.concatenate([state.a, new_a.astype(complex)]))


def _extend_labels(labels: dict[str, np.ndarray], n_new: int, skip: tuple[str, ...] = ()) -> dict:
    out = {}
    for k, v in labels.items():
        if k in skip:
            continue
        fill = np.nan if np.issubdtype(v.dtype, np.floating) else -1
        out[k] = np.concatenate([v, np.full(n_new, fill, dtype=v.dtype)])
    return out


def _junction_label(i: int, j: int, n1: int) -> int:
    """Sub-gasket label of the first-subdivision midpoint between seed corners i < j.

    Such a vertex belongs to two top-level sub-gaskets; we pick one cyclically so that for the
    gasket each sub-gasket receives exactly one junction vertex.
    """
    return i if (j - i) <= n1 // 2 else j


# ---------------------------------------------------------------------------- simplex seed / subdivision
def simplex_seed(n: int, cfg, rule_name: str) -> XonGraph:
    coords = regular_simplex(n)
    nv = n + 1
    simplices = np.arange(nv, dtype=np.int64)[None, :]
    return XonGraph(
        coords=coords,
        simplices=simplices,
        edges=simplex_edges(simplices),
        depth=np.zeros(nv, dtype=np.int64),
        parent=np.full(nv, -1, dtype=np.int64),
        version=0,
        labels={"subgasket": np.full(nv, -1, dtype=np.int64)},
        rule=rule_name,
        level=0,
        cell_labels={"subgasket": np.array([-1], dtype=np.int64), "cell_id": np.array([0], dtype=np.int64)},
        proj_axes=principal_axes(coords) if n > 2 else None,
        coord_index=dict(zip(coord_keys(coords, cfg.merge_tol), range(nv))),
    )


def subdivide(g: XonGraph, which: np.ndarray, state: Any, cfg) -> tuple[XonGraph, Any]:
    """Replace the selected leaf n-simplices by their n+1 corner sub-simplices."""
    which = np.asarray(which, dtype=bool)
    if not which.any():
        return g, state
    cells = g.simplices[which]
    keep = g.simplices[~which]
    m, n1 = cells.shape
    ii, jj = np.triu_indices(n1, k=1)
    n_pairs = len(ii)
    pair_index = {(int(a), int(b)): p for p, (a, b) in enumerate(zip(ii, jj))}

    ends_a = cells[:, ii]
    ends_b = cells[:, jj]
    mids = 0.5 * (g.coords[ends_a] + g.coords[ends_b])
    flat_mids = mids.reshape(m * n_pairs, -1)

    coord_index = dict(g.coord_index)
    n0 = g.n()
    mid_ids = np.empty(m * n_pairs, dtype=np.int64)
    new_rows: list[int] = []
    next_id = n0
    for idx, key in enumerate(coord_keys(flat_mids, cfg.merge_tol)):
        vid = coord_index.get(key)
        if vid is None:
            vid = next_id
            next_id += 1
            coord_index[key] = vid
            new_rows.append(idx)
        mid_ids[idx] = vid
    new_rows_arr = np.asarray(new_rows, dtype=np.int64)
    n_new = len(new_rows_arr)
    mid_ids = mid_ids.reshape(m, n_pairs)

    # per-new-vertex bookkeeping
    cell_ids = g.cell_labels["cell_id"][which]
    cell_sub = g.cell_labels["subgasket"][which]
    flat_cell = np.repeat(cell_ids, n_pairs)[new_rows_arr]
    flat_a = ends_a.ravel()[new_rows_arr]
    flat_b = ends_b.ravel()[new_rows_arr]

    labels_sub = g.labels.get("subgasket", np.full(n0, -1, dtype=np.int64)).copy()
    sub_per_mid = np.repeat(cell_sub, n_pairs).copy()
    seed_cells = np.flatnonzero(cell_sub < 0)
    if len(seed_cells):
        # first subdivision: corners take their corner index, midpoints the junction rule
        junction = np.array([_junction_label(int(a), int(b), n1) for a, b in zip(ii, jj)])
        for c in seed_cells:
            labels_sub[cells[c]] = np.arange(n1)
            sub_per_mid[c * n_pairs:(c + 1) * n_pairs] = junction
    new_sub = sub_per_mid[new_rows_arr]

    # children: child c keeps corner c and the midpoints of the edges (c, k)
    children = np.empty((m, n1, n1), dtype=np.int64)
    for c in range(n1):
        for k in range(n1):
            children[:, c, k] = cells[:, c] if k == c else mid_ids[:, pair_index[(min(c, k), max(c, k))]]
    children = children.reshape(m * n1, n1)
    child_sub = np.where(np.repeat(cell_sub, n1) >= 0, np.repeat(cell_sub, n1), np.tile(np.arange(n1), m))
    next_cell = int(g.cell_labels["cell_id"].max()) + 1
    child_ids = np.arange(next_cell, next_cell + m * n1, dtype=np.int64)

    simplices = np.vstack([keep, children])
    cell_labels = {
        "subgasket": np.concatenate([g.cell_labels["subgasket"][~which], child_sub]).astype(np.int64),
        "cell_id": np.concatenate([g.cell_labels["cell_id"][~which], child_ids]),
    }
    labels = _extend_labels(g.labels, n_new, skip=("subgasket",))
    labels["subgasket"] = np.concatenate([labels_sub, new_sub]).astype(np.int64)

    new_graph = XonGraph(
        coords=np.vstack([g.coords, flat_mids[new_rows_arr]]),
        simplices=simplices,
        edges=simplex_edges(simplices),
        depth=np.concatenate([g.depth, np.full(n_new, g.max_depth() + 1, dtype=np.int64)]),
        parent=np.concatenate([g.parent, flat_cell]),
        version=g.version + 1,
        labels=labels,
        rule=g.rule,
        level=g.level + 1,
        cell_labels=cell_labels,
        proj_axes=g.proj_axes,
        uid=g.uid,
        coord_index=coord_index,
    )
    new_state = None
    if state is not None:
        new_state = _extend_state(state, interpolate_amplitudes(state.a[flat_a], state.a[flat_b]))
    return new_graph, new_state


# ---------------------------------------------------------------------------- rules
class GasketRule:
    name = "gasket"

    def seed(self, cfg) -> XonGraph:
        return simplex_seed(2, cfg, self.name)

    def grow(self, g, state, cfg, rng=None):
        return subdivide(g, np.ones(len(g.simplices), dtype=bool), state, cfg)

    def predict_new_vertices(self, g, cfg) -> int:
        n1 = g.simplices.shape[1]
        return len(g.simplices) * n1 * (n1 - 1) // 2


class SimplexRule(GasketRule):
    name = "simplex"

    def seed(self, cfg) -> XonGraph:
        return simplex_seed(int(cfg.simplex_dim), cfg, self.name)


class AdaptiveRule(SimplexRule):
    """Refine only energetic leaf cells, plus a random floor fraction so growth never stalls."""
    name = "adaptive"

    def grow(self, g, state, cfg, rng=None):
        rng = rng if rng is not None else np.random.default_rng([int(cfg.seed), int(g.version), 7])
        m = len(g.simplices)
        which = np.zeros(m, dtype=bool)
        if state is not None:
            energy = np.abs(state.a) ** 2
            cell_energy = energy[g.simplices].mean(axis=1)
            which |= cell_energy > cfg.refine_threshold * energy.mean()
        n_floor = min(m, int(round(cfg.refine_floor * m)))
        if n_floor:
            which[rng.choice(m, size=n_floor, replace=False)] = True
        if not which.any():
            which[rng.integers(m)] = True
        return subdivide(g, which, state, cfg)


class TreeRule:
    name = "tree"

    def seed(self, cfg) -> XonGraph:
        return XonGraph(
            coords=np.zeros((1, 2)),
            simplices=np.zeros((0, 2), dtype=np.int64),
            edges=np.zeros((0, 2), dtype=np.int64),
            depth=np.zeros(1, dtype=np.int64),
            parent=np.full(1, -1, dtype=np.int64),
            rule=self.name,
        )

    def grow(self, g, state, cfg, rng=None):
        front = g.frontier_vertices()
        b = int(cfg.branch)
        n0, n_new = g.n(), len(front) * b
        new_ids = np.arange(n0, n0 + n_new, dtype=np.int64)
        par = np.repeat(front, b)
        new_edges = np.stack([par, new_ids], axis=1)
        d = g.max_depth() + 1
        ang = 2 * np.pi * (np.arange(n_new) + 0.5) / n_new
        coords = np.c_[d * np.cos(ang), d * np.sin(ang)]
        new_graph = XonGraph(
            coords=np.vstack([g.coords, coords]),
            simplices=new_edges,
            edges=canonical_edges(np.vstack([g.edges, new_edges])),
            depth=np.concatenate([g.depth, np.full(n_new, d, dtype=np.int64)]),
            parent=np.concatenate([g.parent, par]),
            version=g.version + 1,
            labels=_extend_labels(g.labels, n_new),
            rule=self.name,
            level=g.level + 1,
            uid=g.uid,
        )
        new_state = _extend_state(state, state.a[par]) if state is not None else None
        return new_graph, new_state

    def predict_new_vertices(self, g, cfg) -> int:
        return len(g.frontier_vertices()) * int(cfg.branch)


class LatticeRule:
    """side x side grid, all depth 0; the control does not grow."""
    name = "lattice"

    def seed(self, cfg) -> XonGraph:
        side = int(cfg.lattice_side)
        idx = np.arange(side * side).reshape(side, side)
        horiz = np.stack([idx[:, :-1].ravel(), idx[:, 1:].ravel()], axis=1)
        vert = np.stack([idx[:-1, :].ravel(), idx[1:, :].ravel()], axis=1)
        edges = canonical_edges(np.vstack([horiz, vert]))
        yy, xx = np.divmod(np.arange(side * side), side)
        return XonGraph(
            coords=np.c_[xx, yy].astype(float),
            simplices=edges.copy(),
            edges=edges,
            depth=np.zeros(side * side, dtype=np.int64),
            parent=np.full(side * side, -1, dtype=np.int64),
            rule=self.name,
        )

    def grow(self, g, state, cfg, rng=None):
        return g, state

    def predict_new_vertices(self, g, cfg) -> int:
        return 0


# ---------------------------------------------------------------------------- square subdivision (V1.2 §3)
# Kept sub-squares of a cell's 3 x 3 grid as (column, row) from the bottom-left. The position in the
# tuple is the sub-region label; a vertex shared by several sub-squares takes the lowest index.
CARPET_KEEP = tuple((i, j) for j in range(3) for i in range(3) if (i, j) != (1, 1))
VICSEK_KEEP = tuple((i, j) for j in range(3) for i in range(3) if i == 1 or j == 1)


def square_edges(cells: np.ndarray) -> np.ndarray:
    """Sides of square cells given as (M, 4) corner ids in cyclic order."""
    c = np.asarray(cells, dtype=np.int64)
    return canonical_edges(np.vstack([c[:, [0, 1]], c[:, [1, 2]], c[:, [2, 3]], c[:, [3, 0]]]))


def _unit_square_boundary(coords: np.ndarray, tol: float) -> np.ndarray:
    return ((np.abs(coords) <= tol) | (np.abs(coords - 1.0) <= tol)).any(axis=1).astype(np.int64)


def square_seed(rule_name: str) -> XonGraph:
    """The unit square: 4 corners, 4 sides, one cell stored as (bottom-left, bottom-right, top-right, top-left)."""
    cells = np.arange(4, dtype=np.int64)[None, :]
    return XonGraph(
        coords=np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]),
        simplices=cells,
        edges=square_edges(cells),
        depth=np.zeros(4, dtype=np.int64),
        parent=np.full(4, -1, dtype=np.int64),
        labels={"subregion": np.full(4, -1, dtype=np.int64), "boundary": np.ones(4, dtype=np.int64)},
        rule=rule_name,
        level=0,
        cell_labels={"subregion": np.array([-1], dtype=np.int64), "cell_id": np.array([0], dtype=np.int64)},
    )


def subdivide_squares(g: XonGraph, keep: tuple[tuple[int, int], ...], state: Any, cfg) -> tuple[XonGraph, Any]:
    """Split every cell into its 3 x 3 grid and keep the sub-squares in ``keep`` (boundary skeleton).

    The new vertex set is the corners of the kept sub-squares, merged by rounded coordinates. Old
    vertices that are still corners keep their data (and their order, ahead of the new ones); the rest
    are dropped. A new vertex gets the bilinear interpolation of its parent cell's corner amplitudes.
    """
    cells = g.simplices
    m, n_keep = len(cells), len(keep)
    corner = g.coords[cells[:, 0]]
    side = g.coords[cells[:, 1], 0] - corner[:, 0]
    local = np.array(sorted({(i + di, j + dj) for i, j in keep for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1))}))
    n_loc = len(local)
    pos = (corner[:, None, :] + local[None, :, :] * (side[:, None, None] / 3.0)).reshape(-1, 2)
    uv = local / 3.0
    weights = np.c_[(1 - uv[:, 0]) * (1 - uv[:, 1]), uv[:, 0] * (1 - uv[:, 1]),
                    uv[:, 0] * uv[:, 1], (1 - uv[:, 0]) * uv[:, 1]]

    n0 = g.n()
    q = np.round(np.vstack([g.coords, pos]) / cfg.merge_tol).astype(np.int64)
    _, first, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    used = np.zeros(len(first), dtype=bool)
    used[inv[n0:]] = True
    survivors = np.sort(first[used & (first < n0)])
    fresh = np.flatnonzero(used & (first >= n0))
    fresh = fresh[np.argsort(first[fresh], kind="stable")]
    n_surv, n_fresh = len(survivors), len(fresh)
    new_id = np.full(len(first), -1, dtype=np.int64)
    new_id[inv[survivors]] = np.arange(n_surv)
    new_id[fresh] = n_surv + np.arange(n_fresh)
    cand = new_id[inv[n0:]].reshape(m, n_loc)
    src_cell, src_loc = np.divmod(first[fresh] - n0, n_loc)

    slot = {p: t for t, p in enumerate(map(tuple, local.tolist()))}
    child_corners = np.array([[slot[(i, j)], slot[(i + 1, j)], slot[(i + 1, j + 1)], slot[(i, j + 1)]]
                              for i, j in keep])
    children = cand[:, child_corners].reshape(m * n_keep, 4)
    parent_sub = np.repeat(g.cell_labels["subregion"], n_keep)
    child_sub = np.where(parent_sub >= 0, parent_sub, np.tile(np.arange(n_keep), m)).astype(np.int64)
    next_cell = int(g.cell_labels["cell_id"].max()) + 1
    child_ids = np.arange(next_cell, next_cell + m * n_keep, dtype=np.int64)

    n_new = n_surv + n_fresh
    coords = np.vstack([g.coords[survivors], pos[first[fresh] - n0]])
    sub = np.full(n_new, np.iinfo(np.int64).max, dtype=np.int64)
    np.minimum.at(sub, children.ravel(), np.repeat(child_sub, 4))
    labels = _extend_labels({k: v[survivors] for k, v in g.labels.items()}, n_fresh, skip=("subregion", "boundary"))
    labels["subregion"] = sub
    labels["boundary"] = _unit_square_boundary(coords, 1e3 * cfg.merge_tol)

    new_graph = XonGraph(
        coords=coords,
        simplices=children,
        edges=square_edges(children),
        depth=np.concatenate([g.depth[survivors], np.full(n_fresh, g.max_depth() + 1, dtype=np.int64)]),
        parent=np.concatenate([g.parent[survivors], g.cell_labels["cell_id"][src_cell]]),
        version=g.version + 1,
        labels=labels,
        rule=g.rule,
        level=g.level + 1,
        cell_labels={"subregion": child_sub, "cell_id": child_ids},
        uid=g.uid,
    )
    new_state = None
    if state is not None:
        born = interpolate_weighted(state.a[cells[src_cell]], weights[src_loc])
        new_state = dc_replace(state, a=np.concatenate([state.a[survivors], born]).astype(complex))
    return new_graph, new_state


class CarpetRule:
    """Sierpinski carpet: keep 8 of 9 sub-squares (drop the center). Vertices are only ever added."""
    name = "carpet"
    keep = CARPET_KEEP

    def seed(self, cfg) -> XonGraph:
        return square_seed(self.name)

    def grow(self, g, state, cfg, rng=None):
        return subdivide_squares(g, self.keep, state, cfg)

    def predict_new_vertices(self, g, cfg) -> int:
        # N(L+1) = 8 N(L) - 8 (3^L + 1): the copies share whole sides of 3^L + 1 vertices
        return 7 * g.n() - 8 * (3 ** g.level + 1)


class VicsekRule(CarpetRule):
    """Vicsek (plus) fractal: keep the center and the four edge-midpoint sub-squares.

    Every subdivision drops the parent cell corners, so each level replaces all vertices (the new
    ones interpolate the state); the copies share one side (2 vertices) at each junction.
    """
    name = "vicsek"
    keep = VICSEK_KEEP

    def predict_new_vertices(self, g, cfg) -> int:
        return 4 * g.n() - 8          # N(L+1) = 5 N(L) - 8


# ---------------------------------------------------------------------------- Sierpinski graphs S(p, n) (V1.2 §3.1)
def _word_digits(codes: np.ndarray, p: int, m: int) -> np.ndarray:
    """(n, m) letters of each word code, first letter first."""
    return (np.asarray(codes)[:, None] // p ** np.arange(m - 1, -1, -1)) % p


def sierpinski_graph(p: int, codes: np.ndarray, *, depth: np.ndarray, parent: np.ndarray, level: int,
                     version: int = 0, uid: str | None = None) -> XonGraph:
    """S(p, m) on the words ``codes`` (vertex i has word code codes[i]; m = level + 1 letters).

    A word is its base-p code, first letter most significant. u ~ v iff u = P a b^k and v = P b a^k for
    a prefix P and letters a != b: k = 0 gives the edges inside the smallest p-cliques, k >= 1 the
    bridges between copies.
    """
    m = level + 1
    codes = np.asarray(codes, dtype=np.int64)
    id_of = np.empty(p ** m, dtype=np.int64)
    id_of[codes] = np.arange(len(codes))
    a, b = np.triu_indices(p, 1)
    rows = []
    for k in range(m):
        prefix = np.arange(p ** (m - 1 - k))[:, None] * p ** (k + 1)
        rep = (p ** k - 1) // (p - 1)
        u = prefix + a[None, :] * p ** k + b[None, :] * rep
        v = prefix + b[None, :] * p ** k + a[None, :] * rep
        rows.append(np.stack([u.ravel(), v.ravel()], axis=1))
    digits = _word_digits(codes, p, m)
    ang = np.pi / 2 + 2 * np.pi * np.arange(p) / p
    ratio = np.sin(np.pi / p) / (1 + np.sin(np.pi / p))   # copies of the layout never overlap
    coords = (np.c_[np.cos(ang), np.sin(ang)][digits] * (ratio ** np.arange(m))[None, :, None]).sum(axis=1)
    cliques = id_of[np.arange(p ** (m - 1))[:, None] * p + np.arange(p)[None, :]]
    extreme = codes % ((p ** m - 1) // (p - 1)) == 0
    return XonGraph(
        coords=coords,
        simplices=cliques,
        edges=canonical_edges(id_of[np.vstack(rows)]),
        depth=np.asarray(depth, dtype=np.int64),
        parent=np.asarray(parent, dtype=np.int64),
        version=version,
        labels={"word": codes, "subregion": digits[:, 0].astype(np.int64), "boundary": extreme.astype(np.int64)},
        rule="sierpinski_p",
        level=level,
        **({} if uid is None else {"uid": uid}),
    )


class SierpinskiPRule:
    """Generalized Sierpinski graphs S(p, n): level L is S(p, L + 1), so the seed is the clique K_p.

    Growth replaces every vertex w by the p-clique {w x}; w keeps its id as w w_n (its last letter
    repeated) and the p - 1 others are new, born on the clique edge from w toward the letter x (their
    amplitude interpolates that edge's endpoints, as in the gasket).
    """
    name = "sierpinski_p"

    def seed(self, cfg) -> XonGraph:
        p = int(cfg.sierpinski_p)
        if p < 2:
            raise ValueError(f"sierpinski_p needs p >= 2, got {p}")
        return sierpinski_graph(p, np.arange(p), depth=np.zeros(p), parent=np.full(p, -1), level=0)

    def grow(self, g, state, cfg, rng=None):
        p, n0 = g.simplices.shape[1], g.n()
        codes = g.labels["word"]
        last = codes % p
        letters = np.tile(np.arange(p), n0)
        owner = np.repeat(np.arange(n0), p)
        born = letters != last[owner]
        owner, letters = owner[born], letters[born]
        new_codes = np.concatenate([codes * p + last, codes[owner] * p + letters])
        new_graph = sierpinski_graph(
            p, new_codes,
            depth=np.concatenate([g.depth, np.full(len(owner), g.max_depth() + 1)]),
            parent=np.concatenate([g.parent, owner]),
            level=g.level + 1, version=g.version + 1, uid=g.uid)
        new_state = None
        if state is not None:
            id_of = np.empty(p ** (g.level + 1), dtype=np.int64)
            id_of[codes] = np.arange(n0)
            toward = id_of[codes[owner] - last[owner] + letters]
            new_state = _extend_state(state, interpolate_amplitudes(state.a[owner], state.a[toward]))
        return new_graph, new_state

    def predict_new_vertices(self, g, cfg) -> int:
        return g.n() * (g.simplices.shape[1] - 1)


# Ordered by the sidebar's groups (RULE_GROUPS): candidates, bridge, controls.
RULES: dict[str, type] = {
    "gasket": GasketRule,
    "carpet": CarpetRule,
    "sierpinski_p": SierpinskiPRule,
    "simplex": SimplexRule,
    "adaptive": AdaptiveRule,
    "vicsek": VicsekRule,
    "tree": TreeRule,
    "lattice": LatticeRule,
}
RULE_GROUPS: dict[str, str] = {
    "gasket": "Candidates", "carpet": "Candidates", "sierpinski_p": "Candidates", "simplex": "Candidates",
    "adaptive": "Candidates", "vicsek": "Bridge", "tree": "Controls", "lattice": "Controls",
}


def get_rule(name: str) -> GrowthRule:
    try:
        return RULES[name]()
    except KeyError as exc:
        raise ValueError(f"unknown growth rule {name!r}; choose from {sorted(RULES)}") from exc


def build_graph(cfg, level: int, rule: str | None = None, state: Any = None,
                rng: np.random.Generator | None = None) -> XonGraph:
    """Seed with ``rule`` (default cfg.growth_rule) and grow ``level`` times (no dynamics)."""
    r = get_rule(rule or cfg.growth_rule)
    g = r.seed(cfg)
    for _ in range(level):
        g, state = r.grow(g, state, cfg, rng)
    return g
