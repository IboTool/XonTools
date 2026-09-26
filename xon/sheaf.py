"""CellularSheaf: stalks, restriction maps, sheaf Laplacian, diffusion, learning (§6.1).

Edge e = (tail, head) = (edges[e, 0], edges[e, 1]); the coboundary is
(delta x)_e = F_head[e] x_head - F_tail[e] x_tail, and L_F = delta^T delta.
Vectors x have shape (N*k,), vertex-major (x[v*k:(v+1)*k] is the stalk vector at v).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from .graph import XonGraph


def random_orthogonal(rng: np.random.Generator, n: int, k: int) -> np.ndarray:
    """n Haar-random k x k orthogonal matrices, shape (n, k, k)."""
    z = rng.standard_normal((n, k, k))
    q, r = np.linalg.qr(z)
    d = np.sign(np.diagonal(r, axis1=1, axis2=2))
    d[d == 0] = 1.0
    return q * d[:, None, :]


def state_to_stalks(a: np.ndarray, k: int) -> np.ndarray:
    """Embed a complex per-vertex state in k-dim stalks as (Re a, Im a, 0, ...)."""
    x = np.zeros((len(a), k))
    x[:, 0] = a.real
    if k > 1:
        x[:, 1] = a.imag
    return x.ravel()


@dataclass
class CellularSheaf:
    k: int
    F_head: np.ndarray           # (E, k, k) restriction map edge -> head vertex stalk
    F_tail: np.ndarray           # (E, k, k)
    edges: np.ndarray | None = None  # the edge list these maps are aligned with

    # ------------------------------------------------------------------ constructors
    @classmethod
    def identity(cls, g: XonGraph, k: int) -> "CellularSheaf":
        eye = np.broadcast_to(np.eye(k), (g.n_edges(), k, k))
        return cls(k, eye.copy(), eye.copy(), g.edges.copy())

    @classmethod
    def random(cls, g: XonGraph, k: int, rng: np.random.Generator) -> "CellularSheaf":
        e = g.n_edges()
        return cls(k, random_orthogonal(rng, e, k), random_orthogonal(rng, e, k), g.edges.copy())

    @classmethod
    def random_flat(cls, g: XonGraph, k: int, rng: np.random.Generator
                    ) -> tuple["CellularSheaf", np.ndarray]:
        """Random orthogonal maps with trivial holonomy (the E5 ground truth).

        With vertex frames Q_v and edge frames R_e, F_head = R_e Q_head^T and F_tail = R_e Q_tail^T,
        so x_v = Q_v y is a global section for every y in R^k (parallel transport of y).
        Returns (sheaf, frames) with frames of shape (N, k, k).
        """
        frames = random_orthogonal(rng, g.n(), k)
        r = random_orthogonal(rng, g.n_edges(), k)
        tail, head = g.edges[:, 0], g.edges[:, 1]
        f_head = r @ np.transpose(frames[head], (0, 2, 1))
        f_tail = r @ np.transpose(frames[tail], (0, 2, 1))
        return cls(k, f_head, f_tail, g.edges.copy()), frames

    # ------------------------------------------------------------------ operators
    def _check(self, g: XonGraph) -> None:
        if self.edges is not None and (self.edges.shape != g.edges.shape or not np.array_equal(self.edges, g.edges)):
            raise ValueError("sheaf maps are not aligned with this graph's edges; call adapt(g) first")

    def coboundary(self, g: XonGraph) -> sp.csr_matrix:
        self._check(g)
        e, k = g.n_edges(), self.k
        tail, head = g.edges[:, 0], g.edges[:, 1]
        ar = np.arange(k)
        rows = np.broadcast_to(np.arange(e)[:, None, None] * k + ar[None, :, None], (e, k, k))
        cols_h = np.broadcast_to(head[:, None, None] * k + ar[None, None, :], (e, k, k))
        cols_t = np.broadcast_to(tail[:, None, None] * k + ar[None, None, :], (e, k, k))
        data = np.concatenate([self.F_head.ravel(), -self.F_tail.ravel()])
        r = np.concatenate([rows.ravel(), rows.ravel()])
        c = np.concatenate([cols_h.ravel(), cols_t.ravel()])
        return sp.coo_matrix((data, (r, c)), shape=(e * k, g.n() * k)).tocsr()

    def laplacian(self, g: XonGraph) -> sp.csr_matrix:
        d = self.coboundary(g)
        return (d.T @ d).tocsr()

    def dirichlet_energy(self, g: XonGraph, x: np.ndarray) -> float:
        r = self.coboundary(g) @ np.asarray(x, dtype=float)
        return float(r @ r)

    def consistency(self, g: XonGraph, x: np.ndarray, eps: float = 1e-12) -> float:
        x = np.asarray(x, dtype=float)
        return self.dirichlet_energy(g, x) / (float(x @ x) + eps)

    def lambda_max(self, g: XonGraph) -> float:
        """Largest eigenvalue of L_F; diffusion x <- x - eta L_F x is stable only for eta < 2 / lambda_max."""
        lap = self.laplacian(g)
        m = lap.shape[0]
        if m <= 600:
            return float(np.linalg.eigvalsh(lap.toarray())[-1]) if m else 0.0
        v0 = np.random.default_rng(0).standard_normal(m)
        return float(spla.eigsh(lap, k=1, which="LA", return_eigenvectors=False, v0=v0)[0])

    def global_sections(self, g: XonGraph, tol: float = 1e-8) -> np.ndarray:
        """Orthonormal basis of ker L_F (dense; for small graphs)."""
        w, v = np.linalg.eigh(self.laplacian(g).toarray())
        return v[:, w < tol * max(1.0, float(w.max()))]

    # ------------------------------------------------------------------ inference / learning
    def _expand_mask(self, g: XonGraph, mask: np.ndarray | None) -> np.ndarray | None:
        if mask is None:
            return None
        mask = np.asarray(mask, dtype=bool)
        if mask.shape == (g.n(),):
            return np.repeat(mask, self.k)
        if mask.shape == (g.n() * self.k,):
            return mask
        raise ValueError("clamp_mask must have shape (N,) or (N*k,)")

    def diffuse(self, g: XonGraph, x: np.ndarray, eta: float, steps: int,
                clamp_mask: np.ndarray | None = None, clamp_values: np.ndarray | None = None,
                record_every: int = 0):
        """x <- x - eta L_F x with clamped entries reset each step.

        ``clamp_values`` is a full-length (N*k,) vector; only its clamped entries are used.
        Returns x, or (x, [(step, consistency), ...]) when record_every > 0.
        """
        lap = self.laplacian(g)
        x = np.array(x, dtype=float).ravel()
        cm = self._expand_mask(g, clamp_mask)
        cv = None
        if cm is not None:
            cv = np.asarray(clamp_values, dtype=float).ravel()[cm]
            x[cm] = cv
        trace = []
        for t in range(int(steps)):
            if record_every and t % record_every == 0:
                trace.append((t, self.consistency(g, x)))
            x = x - eta * (lap @ x)
            if cm is not None:
                x[cm] = cv
        if record_every:
            trace.append((int(steps), self.consistency(g, x)))
            return x, trace
        return x

    def learn(self, g: XonGraph, examples: list[np.ndarray], eta: float, steps: int,
              l2: float = 1e-3) -> list[float]:
        """Gradient descent on the mean Dirichlet energy of the examples w.r.t. both maps, with an
        L2 pull toward the maps held when learning started; each map is renormalized to unit
        Frobenius norm after every step (rules out the trivial zero solution).
        Returns the mean example energy after each step."""
        self._check(g)
        n, k = g.n(), self.k
        X = np.stack([np.asarray(ex, dtype=float).reshape(n, k) for ex in examples])
        tail, head = g.edges[:, 0], g.edges[:, 1]
        # per-edge example matrices, shape (E, S, k)
        xt = np.ascontiguousarray(np.transpose(X[:, tail, :], (1, 0, 2)))
        xh = np.ascontiguousarray(np.transpose(X[:, head, :], (1, 0, 2)))
        s = len(X)
        fh, ft = self.F_head.astype(float).copy(), self.F_tail.astype(float).copy()
        fh0, ft0 = fh.copy(), ft.copy()

        def residual(fh, ft):  # (E, S, k): F_head x_head - F_tail x_tail per example
            return xh @ np.transpose(fh, (0, 2, 1)) - xt @ np.transpose(ft, (0, 2, 1))

        history = []
        for _ in range(int(steps)):
            rt = np.transpose(residual(fh, ft), (0, 2, 1))
            gh = 2.0 * (rt @ xh) / s + 2.0 * l2 * (fh - fh0)
            gt = -2.0 * (rt @ xt) / s + 2.0 * l2 * (ft - ft0)
            fh -= eta * gh
            ft -= eta * gt
            fh /= np.maximum(np.linalg.norm(fh, axis=(1, 2)), 1e-15)[:, None, None]
            ft /= np.maximum(np.linalg.norm(ft, axis=(1, 2)), 1e-15)[:, None, None]
            history.append(float(np.sum(residual(fh, ft) ** 2) / s))
        self.F_head, self.F_tail = fh, ft
        return history

    def adapt(self, g: XonGraph) -> "CellularSheaf":
        """Align with a grown graph: surviving edges keep their maps, new edges get identity maps."""
        k = self.k
        f_head = np.broadcast_to(np.eye(k), (g.n_edges(), k, k)).copy()
        f_tail = f_head.copy()
        if self.edges is not None and len(self.edges):
            old = {(int(u), int(v)): i for i, (u, v) in enumerate(self.edges)}
            for j, (u, v) in enumerate(g.edges):
                i = old.get((int(u), int(v)))
                if i is not None:
                    f_head[j], f_tail[j] = self.F_head[i], self.F_tail[i]
        return CellularSheaf(k, f_head, f_tail, g.edges.copy())


def sample_sections(frames: np.ndarray, rng: np.random.Generator, count: int) -> list[np.ndarray]:
    """Random global sections x_v = Q_v y (y ~ N(0, I_k)) of a flat sheaf with vertex frames Q."""
    k = frames.shape[1]
    return [(frames @ rng.standard_normal(k)).ravel() for _ in range(count)]
