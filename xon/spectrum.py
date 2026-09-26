"""Cached Laplacian eigendecomposition, dense or sparse (§3.5).

Canonical basis
---------------
Eigenvectors inside a degenerate eigenspace are not unique (the gasket's lambda=6 level alone has
multiplicity 120 at level 5), so every quantity that reads individual eigenvectors -- modal
fractions p_k, IPR, the Fiedler vector -- would otherwise depend on LAPACK internals. We fix a
canonical, platform-independent basis:

* the lambda_2 eigenspace is rotated so that phi_2 is the vector whose sign cut has the smallest
  ratio cut (the Fiedler vector is by definition the relaxation of the sparsest cut);
* every other degenerate eigenspace is rotated to its maximally localized basis, i.e. the rotation
  maximizing sum_k sum_i phi_k(i)^4 = sum_k IPR_k (quartimax, initialized by pivoted QR / SCDM);
* each eigenvector's largest-magnitude entry is made positive.

``cfg.canonical_basis = "raw"`` keeps the solver's basis for non-Fiedler eigenspaces. Rotations
inside an eigenspace do not change the dynamics' propagator.
"""
from __future__ import annotations

from collections import OrderedDict

import numpy as np
import scipy.linalg
import scipy.sparse.linalg as spla

from .config import DEFAULT, XonConfig
from .graph import XonGraph

ROUGHNESS_MATRIX_MAX_K = 1500
EIG_MERGE_ATOL = 1e-10


def degenerate_groups(lam: np.ndarray, tol: float, rtol: float = 0.0) -> list[tuple[int, int]]:
    """Index ranges [start, stop) of eigenvalue levels (consecutive gaps <= tol + rtol * |lambda|)."""
    if len(lam) == 0:
        return []
    breaks = np.flatnonzero(np.diff(lam) > tol + rtol * np.abs(lam[1:])) + 1
    starts = np.r_[0, breaks]
    stops = np.r_[breaks, len(lam)]
    return [(int(a), int(b)) for a, b in zip(starts, stops)]


def ratio_cuts(vectors: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """RatioCut = cut(S, S^c) (1/|S| + 1/|S^c|) of the sign cut S = {v >= 0} of each column."""
    n = vectors.shape[0]
    side = vectors >= 0
    size = side.sum(axis=0)
    cut = (side[edges[:, 0]] != side[edges[:, 1]]).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        rc = cut * (1.0 / size + 1.0 / (n - size))
    rc = np.where((size == 0) | (size == n), np.inf, rc)
    return rc


def _fiedler_rotate(block: np.ndarray, edges: np.ndarray) -> np.ndarray:
    m = block.shape[1]
    if m == 2:
        th = np.linspace(0.0, np.pi, 360, endpoint=False)
        cand = np.stack([np.cos(th), np.sin(th)])
    else:
        rng = np.random.default_rng(0)
        cand = np.hstack([np.eye(m), rng.standard_normal((m, 512))])
        cand /= np.linalg.norm(cand, axis=0)
    best = cand[:, int(np.argmin(ratio_cuts(block @ cand, edges)))]
    q, _ = np.linalg.qr(np.column_stack([best, np.eye(m)]))
    return block @ q[:, :m]


def _localize(block: np.ndarray, max_iter: int, tol: float = 1e-9) -> np.ndarray:
    """Quartimax rotation of an orthonormal block (maximizes the summed IPR), SCDM start."""
    m = block.shape[1]
    _, _, piv = scipy.linalg.qr(block.T, pivoting=True, mode="economic")
    u, _, vt = np.linalg.svd(block.T[:, piv[:m]])
    rot = u @ vt
    obj_old = -np.inf
    for _ in range(max_iter):
        cur = block @ rot
        obj = float(np.sum(cur ** 4))
        if obj - obj_old <= tol * abs(obj):
            break
        obj_old = obj
        u, _, vt = np.linalg.svd(block.T @ cur ** 3)
        rot = u @ vt
    return block @ rot


def _fix_signs(phi: np.ndarray) -> np.ndarray:
    idx = np.argmax(np.abs(phi), axis=0)
    signs = np.sign(phi[idx, np.arange(phi.shape[1])])
    signs[signs == 0] = 1.0
    return phi * signs


class Spectrum:
    """Eigenpairs of L = D - A: all of them (dense) or the lowest k (sparse, shift-invert)."""

    def __init__(self, g: XonGraph, k: int | None = None, cfg: XonConfig | None = None):
        cfg = cfg or DEFAULT
        self.version = g.version
        self.key = g.content_key()
        self.n = g.n()
        self.tol = float(cfg.degeneracy_tol)
        self.canonical_basis = cfg.canonical_basis
        self.localize_max_iter = int(cfg.localize_max_iter)
        self._edges = g.edges.copy()
        lap = g.laplacian()
        rtol = float(cfg.eig_merge_rtol)
        if self.n <= cfg.dense_max:
            lam, phi = np.linalg.eigh(lap.toarray())
            self.method = "dense"
            groups = degenerate_groups(lam, EIG_MERGE_ATOL, rtol)
        else:
            k = int(k or cfg.k_modes)
            k_req = min(self.n - 1, k + max(8, k // 4))
            v0 = np.random.default_rng(0).standard_normal(self.n)
            lam, phi = spla.eigsh(lap.tocsc(), k=k_req, sigma=-1e-4, which="LM", v0=v0)
            order = np.argsort(lam)
            lam, phi = lam[order], phi[:, order]
            groups = degenerate_groups(lam, EIG_MERGE_ATOL, rtol)
            if len(groups) > 1:
                groups = groups[:-1]  # the last level may be cut off by k_req
            stops = [b for _, b in groups]
            keep = next((b for b in stops if b >= k), stops[-1])
            groups = [(a, b) for a, b in groups if b <= keep]
            lam, phi = lam[:keep], phi[:, :keep]
            self.method = "sparse"
        lam = lam.copy()
        for a, b in groups:
            lam[a:b] = lam[a:b].mean()
        self.lam = lam
        self.groups = groups
        self.k_used = int(phi.shape[1])
        self.captured_fraction_hint = self.k_used / self.n
        self._phi_raw: np.ndarray | None = phi
        self._phi: np.ndarray | None = None
        self._ipr: np.ndarray | None = None
        self._rough: dict[float, np.ndarray] = {}

    # ------------------------------------------------------------------ bases
    @property
    def phi(self) -> np.ndarray:
        """Canonical eigenvector basis (N, k_used), computed on first access."""
        if self._phi is None:
            phi = self._phi_raw.copy()
            for a, b in self.groups:
                if b - a < 2:
                    continue
                if a == 1:
                    phi[:, a:b] = _fiedler_rotate(phi[:, a:b], self._edges)
                elif self.canonical_basis == "localized":
                    phi[:, a:b] = _localize(phi[:, a:b], self.localize_max_iter)
            self._phi = _fix_signs(phi)
            self._phi_raw = None
        return self._phi

    @property
    def phi_dyn(self) -> np.ndarray:
        """Any orthonormal eigenbasis (for the propagator); avoids forcing canonicalization."""
        return self._phi if self._phi is not None else self._phi_raw

    def lowest_modes(self, k: int) -> np.ndarray:
        """The first k columns of ``phi``, canonicalizing only the eigenspaces they reach."""
        if self._phi is not None:
            return self._phi[:, :k]
        blocks = []
        for a, b in self.groups:
            if a >= k:
                break
            block = self._phi_raw[:, a:b]
            if b - a >= 2:
                if a == 1:
                    block = _fiedler_rotate(block, self._edges)
                elif self.canonical_basis == "localized":
                    block = _localize(block, self.localize_max_iter)
            blocks.append(block)
        return _fix_signs(np.hstack(blocks))[:, :k]

    @property
    def omega(self) -> np.ndarray:
        return np.sqrt(np.clip(self.lam, 0.0, None))

    @property
    def ipr(self) -> np.ndarray:
        if self._ipr is None:
            p2 = self.phi ** 2
            self._ipr = (p2 ** 2).sum(axis=0) / p2.sum(axis=0) ** 2
        return self._ipr

    def mode(self, k: int) -> np.ndarray:
        """Eigenvector k, 1-based (k = 1 is the fundamental, k = 2 the Fiedler vector)."""
        if not 1 <= k <= self.k_used:
            raise IndexError(f"mode {k} outside 1..{self.k_used}")
        return self.phi[:, k - 1]

    def project(self, a: np.ndarray) -> np.ndarray:
        """Modal coefficients c = Phi^T a in the canonical basis."""
        return self.phi.T @ a

    def lambda_max(self) -> float:
        return float(self.lam[-1])

    def roughness_matrix(self, freq_scale: float) -> np.ndarray | None:
        """Pairwise Plomp-Levelt roughness r(omega_j, omega_k) in Hz units (cached; None if K is large)."""
        if self.k_used > ROUGHNESS_MATRIX_MAX_K:
            return None
        key = float(freq_scale)
        if key not in self._rough:
            from .metrics import plomp_levelt
            f = self.omega * key
            self._rough[key] = plomp_levelt(f[:, None], f[None, :])
        return self._rough[key]

    def nbytes(self) -> int:
        total = sum(m.nbytes for m in self._rough.values())
        for arr in (self._phi_raw, self._phi):
            if arr is not None:
                total += arr.nbytes
        return total


# ---------------------------------------------------------------------------- cache
_CACHE: "OrderedDict[tuple, Spectrum]" = OrderedDict()
_CACHE_MAX_ENTRIES = 8
_CACHE_MAX_BYTES = 800 * 2 ** 20


def get_spectrum(g: XonGraph, cfg: XonConfig | None = None, k: int | None = None) -> Spectrum:
    """Spectrum of ``g`` from the cache (keyed on the graph structure of this version)."""
    cfg = cfg or DEFAULT
    kk = None if g.n() <= cfg.dense_max else int(k or cfg.k_modes)
    key = (g.content_key(), kk, int(cfg.dense_max), float(cfg.degeneracy_tol), float(cfg.eig_merge_rtol),
           cfg.canonical_basis)
    spec = _CACHE.get(key)
    if spec is not None:
        _CACHE.move_to_end(key)
        return spec
    spec = Spectrum(g, k=kk, cfg=cfg)
    _CACHE[key] = spec
    while len(_CACHE) > _CACHE_MAX_ENTRIES or (
        len(_CACHE) > 1 and sum(s.nbytes() for s in _CACHE.values()) > _CACHE_MAX_BYTES
    ):
        _CACHE.popitem(last=False)
    return spec


def clear_cache() -> None:
    _CACHE.clear()


def cache_size() -> int:
    return len(_CACHE)
