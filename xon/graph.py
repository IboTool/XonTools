"""XonGraph: vertices, leaf simplices, edges, depth labels, layout (§3.1)."""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp


def canonical_edges(pairs: np.ndarray) -> np.ndarray:
    """Unique undirected edges as sorted (i < j) int64 rows; self-loops dropped."""
    pairs = np.asarray(pairs, dtype=np.int64).reshape(-1, 2)
    pairs = np.sort(pairs, axis=1)
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    if len(pairs) == 0:
        return np.zeros((0, 2), dtype=np.int64)
    return np.unique(pairs, axis=0)


def simplex_edges(simplices: np.ndarray) -> np.ndarray:
    """All edges of a set of simplices, deduplicated."""
    simplices = np.asarray(simplices, dtype=np.int64)
    if simplices.size == 0 or simplices.shape[1] < 2:
        return np.zeros((0, 2), dtype=np.int64)
    m = simplices.shape[1]
    ii, jj = np.triu_indices(m, k=1)
    pairs = np.stack([simplices[:, ii].ravel(), simplices[:, jj].ravel()], axis=1)
    return canonical_edges(pairs)


def coord_keys(coords: np.ndarray, tol: float) -> list[tuple[int, ...]]:
    """Rounded-coordinate keys used to merge vertices created at the same position."""
    q = np.round(np.asarray(coords, dtype=float) / tol).astype(np.int64)
    return [tuple(row) for row in q.tolist()]


@dataclass
class XonGraph:
    coords: np.ndarray        # (N, d_embed) layout coordinates (full dimension for simplex_dim > 2)
    simplices: np.ndarray     # (M, n+1) current leaf cells (frontier cells)
    edges: np.ndarray         # (E, 2) unique undirected edges of the current leaf cells
    depth: np.ndarray         # (N,) growth step at which each vertex was born
    parent: np.ndarray        # (N,) id of the cell (or parent vertex for trees) a vertex was born on; -1 for seed
    version: int = 0          # increments on every structural change
    labels: dict[str, np.ndarray] = field(default_factory=dict)
    # implementation extras
    rule: str = ""
    level: int = 0                                                  # number of growth steps applied
    cell_labels: dict[str, np.ndarray] = field(default_factory=dict)  # per leaf cell, aligned with simplices
    proj_axes: np.ndarray | None = None                             # (d_embed, 2) display projection
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)
    coord_index: dict = field(default_factory=dict, repr=False)
    _cache: dict = field(default_factory=dict, repr=False, compare=False)

    # ------------------------------------------------------------------ basic queries
    def n(self) -> int:
        return int(self.coords.shape[0])

    def n_edges(self) -> int:
        return int(self.edges.shape[0])

    def max_depth(self) -> int:
        return int(self.depth.max()) if self.n() else 0

    def frontier_vertices(self) -> np.ndarray:
        return np.flatnonzero(self.depth == self.depth.max())

    def frontier_mask(self, window: int = 0) -> np.ndarray:
        """Vertices with depth >= d_max - window."""
        return self.depth >= self.max_depth() - window

    # ------------------------------------------------------------------ operators
    def _cached(self, name: str, fn):
        key = (name, self.version)
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def adjacency(self) -> sp.csr_matrix:
        def build():
            n = self.n()
            if self.n_edges() == 0:
                return sp.csr_matrix((n, n))
            u, v = self.edges[:, 0], self.edges[:, 1]
            data = np.ones(2 * len(u))
            a = sp.coo_matrix((data, (np.r_[u, v], np.r_[v, u])), shape=(n, n))
            return a.tocsr()
        return self._cached("adjacency", build)

    def degrees(self) -> np.ndarray:
        return self._cached("degrees", lambda: np.asarray(self.adjacency().sum(axis=1)).ravel())

    def laplacian(self) -> sp.csr_matrix:
        return self._cached("laplacian", lambda: (sp.diags(self.degrees()) - self.adjacency()).tocsr())

    def content_key(self) -> str:
        """Hash of the structure (N, edges); identical graphs share cached spectra."""
        def build():
            h = hashlib.sha1()
            h.update(np.int64(self.n()).tobytes())
            h.update(np.ascontiguousarray(self.edges, dtype=np.int64).tobytes())
            return h.hexdigest()
        return self._cached("content_key", build)

    # ------------------------------------------------------------------ layout
    def layout2d(self) -> np.ndarray:
        """2D display coordinates (projection onto principal axes when d_embed > 2)."""
        def build():
            x = np.asarray(self.coords, dtype=float)
            if x.shape[1] == 2:
                return x
            if x.shape[1] == 1:
                return np.c_[x, np.zeros(len(x))]
            axes = self.proj_axes if self.proj_axes is not None else principal_axes(x)
            return (x - x.mean(axis=0)) @ axes
        return self._cached("layout2d", build)


def graph_from_edges(n: int, edges, coords: np.ndarray | None = None, depth: np.ndarray | None = None,
                     rule: str = "custom") -> XonGraph:
    """A plain graph whose only simplices are its edges; coords default to a circle, depth to 0."""
    edges = canonical_edges(np.asarray(edges, dtype=np.int64).reshape(-1, 2))
    if coords is None:
        ang = 2 * np.pi * np.arange(n) / max(n, 1)
        coords = np.c_[np.cos(ang), np.sin(ang)]
    return XonGraph(coords=np.asarray(coords, dtype=float), simplices=edges.copy(), edges=edges,
                    depth=np.zeros(n, dtype=np.int64) if depth is None else np.asarray(depth, dtype=np.int64),
                    parent=np.full(n, -1, dtype=np.int64), rule=rule)


def principal_axes(x: np.ndarray) -> np.ndarray:
    """First two principal axes (d, 2) with a deterministic sign convention."""
    xc = x - x.mean(axis=0)
    _, _, vt = np.linalg.svd(xc, full_matrices=False)
    axes = vt[:2].T.copy()
    for j in range(axes.shape[1]):
        i = np.argmax(np.abs(axes[:, j]))
        if axes[i, j] < 0:
            axes[:, j] *= -1
    return axes
