"""Metrics (§3.4). Every metric takes ``(g, s, spec, cfg=None)`` and returns a float or a small dict.

Adding a metric = one function + one entry in ``METRICS``. An entry with ``trace=True`` is a per-step
float: ``trace_metrics`` records it every step (Sandbox Traces tab, traces.csv), and its function must
also accept ``mask`` (the metric scope). The built-in per-step scalars are produced together by
``trace_metrics`` so that one modal projection serves all of them.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np
import scipy.sparse as sp
from scipy import stats
from scipy.optimize import linear_sum_assignment
from scipy.sparse import csgraph

from .config import COHERENCE_FACTORS, DEFAULT
from .dynamics import State, real_matmul
from .graph import XonGraph
from .spectrum import Spectrum, degenerate_groups


# ---------------------------------------------------------------------------- modal decomposition
@dataclass
class ModalDecomposition:
    c: np.ndarray        # modal coefficients c = Phi^T a
    p: np.ndarray        # modal energy fractions (sum to 1 over the modes considered)
    lam: np.ndarray
    omega: np.ndarray
    K: int               # number of modes considered
    captured: float      # fraction of the (masked) state's energy carried by these K modes
    total: float         # energy of the (masked) state
    spec: Spectrum | None = None


def modal_decomposition(g: XonGraph, s: State, spec: Spectrum, mask: np.ndarray | None = None
                        ) -> ModalDecomposition:
    a = s.a if mask is None else np.where(mask, s.a, 0.0)
    c = real_matmul(spec.phi.T, a)
    e = np.abs(c) ** 2
    tot_c = float(e.sum())
    tot = float(np.sum(np.abs(a) ** 2))
    p = e / tot_c if tot_c > 0 else np.zeros_like(e)
    return ModalDecomposition(c, p, spec.lam, spec.omega, spec.k_used,
                              tot_c / tot if tot > 0 else float("nan"), tot, spec)


# ---------------------------------------------------------------------------- 1-6: modal / coherence metrics
def fundamental_fraction_md(md: ModalDecomposition) -> float:
    return float(md.p[0])


def spectral_entropy_md(md: ModalDecomposition) -> float:
    p = md.p[md.p > 0]
    return float(-np.sum(p * np.log(p)))


def spectral_concentration_md(md: ModalDecomposition) -> float:
    if md.K < 2:
        return 1.0
    return float(1.0 - spectral_entropy_md(md) / np.log(md.K))


def plomp_levelt(f1: np.ndarray, f2: np.ndarray) -> np.ndarray:
    """Sethares' parameterization of the Plomp-Levelt roughness of two partials (Hz)."""
    f_min = np.minimum(f1, f2)
    x = np.abs(f1 - f2)
    s = 0.24 / (0.021 * f_min + 19.0)
    return np.exp(-3.5 * s * x) - np.exp(-5.75 * s * x)


def roughness_md(md: ModalDecomposition, cfg=None) -> float:
    """R = sum_{j<k, p_j p_k > eps} sqrt(p_j p_k) r(omega_j, omega_k), omega scaled to Hz."""
    cfg = cfg or DEFAULT
    p = md.p
    p_max = float(p.max()) if len(p) else 0.0
    if p_max <= 0:
        return 0.0
    eps = cfg.roughness_eps
    idx = np.flatnonzero(p > eps / p_max)
    if len(idx) < 2:
        return 0.0
    pp = p[idx]
    sq = np.sqrt(pp)
    rmat = md.spec.roughness_matrix(cfg.freq_scale) if md.spec is not None else None
    if rmat is not None:
        sub = rmat if len(idx) == len(p) else rmat[np.ix_(idx, idx)]
        keep = np.outer(pp, pp) > eps
        # r has a zero diagonal, so half the symmetric sum is the sum over j < k
        return float(0.5 * sq @ (np.where(keep, sub, 0.0) @ sq))
    f = md.omega[idx] * cfg.freq_scale
    n = len(idx)
    kk = np.arange(n)[None, :]
    total = 0.0
    block = max(1, 2_000_000 // n)
    for start in range(0, n, block):
        stop = min(start + block, n)
        jj = np.arange(start, stop)[:, None]
        r = plomp_levelt(f[start:stop, None], f[None, :])
        w = sq[start:stop, None] * sq[None, :] * r
        keep = (kk > jj) & (pp[start:stop, None] * pp[None, :] > eps)
        total += float(np.sum(w, where=keep))
    return total


def phase_order_state(s: State, mask: np.ndarray | None = None) -> float:
    """Kuramoto order |mean_i exp(i arg a_i)| over vertices (exact zeros have no phase)."""
    a = s.a if mask is None else s.a[mask]
    a = a[np.abs(a) > 0]
    if len(a) == 0:
        return 0.0
    return float(np.abs(np.mean(np.exp(1j * np.angle(a)))))


def harmonicity_value(coherence: float, n_eff: float, K: int) -> float:
    """Valence proxy: coherence x log(1 + n_eff) / log(1 + K)  (a modeling choice)."""
    if K < 1:
        return float("nan")
    return float(coherence * np.log1p(n_eff) / np.log1p(K))


def trace_metrics(g: XonGraph, s: State, spec: Spectrum, cfg=None,
                  mask: np.ndarray | None = None) -> dict[str, float]:
    """All per-step scalars in one pass; harmonicity is reported under every coherence factor."""
    cfg = cfg or DEFAULT
    md = modal_decomposition(g, s, spec, mask)
    ent = spectral_entropy_md(md)
    n_eff = float(np.exp(ent))
    rough = roughness_md(md, cfg)
    out = {
        "fundamental_fraction": fundamental_fraction_md(md),
        "spectral_entropy": ent,
        "n_eff": n_eff,
        "spectral_concentration": spectral_concentration_md(md),
        "roughness": rough,
        "consonance": 1.0 / (1.0 + rough),
        "phase_order": phase_order_state(s, mask),
        "K": md.K,
        "captured": md.captured,
        "energy": float(np.sum(np.abs(s.a) ** 2)),
    }
    for f in COHERENCE_FACTORS:
        out[f"harmonicity_{f}"] = harmonicity_value(out[f], n_eff, md.K)
    out["harmonicity"] = out[f"harmonicity_{cfg.harmonicity_coherence}"]
    out["low_subspace_fraction"] = float(md.p[:spectral_k_gap(spec, cfg.k_gap_max)].sum())
    for m in METRICS.values():
        if m.trace and m.name not in out:
            out[m.name] = float(m(g, s, spec, cfg, mask=mask))
    return out


def fundamental_fraction(g, s, spec, cfg=None, mask=None) -> float:
    return fundamental_fraction_md(modal_decomposition(g, s, spec, mask))


def spectral_entropy(g, s, spec, cfg=None, mask=None) -> dict:
    ent = spectral_entropy_md(modal_decomposition(g, s, spec, mask))
    return {"spectral_entropy": ent, "n_eff": float(np.exp(ent))}


def spectral_concentration(g, s, spec, cfg=None, mask=None) -> float:
    return spectral_concentration_md(modal_decomposition(g, s, spec, mask))


def roughness(g, s, spec, cfg=None, mask=None) -> dict:
    r = roughness_md(modal_decomposition(g, s, spec, mask), cfg)
    return {"roughness": r, "consonance": 1.0 / (1.0 + r)}


def phase_order(g, s, spec=None, cfg=None, mask=None) -> float:
    return phase_order_state(s, mask)


def harmonicity(g, s, spec, cfg=None, mask=None) -> float:
    return trace_metrics(g, s, spec, cfg, mask)["harmonicity"]


# ---------------------------------------------------------------------------- 7: depth energy
def depth_energy_array(g: XonGraph, s: State) -> np.ndarray:
    """E[d] = sum over vertices of depth d of |a_i|^2."""
    return np.bincount(g.depth, weights=np.abs(s.a) ** 2, minlength=g.max_depth() + 1)


def _depth_fit(E: np.ndarray, log_x: bool) -> dict:
    """Linear regression of log E[d]; both fits use the same depths (d >= 1, E[d] > 0) because
    a power law in d is undefined at d = 0."""
    E = np.asarray(E, dtype=float)
    d = np.arange(len(E), dtype=float)
    sel = (d >= 1) & (E > 0)
    nan = {"r2": float("nan"), "slope": float("nan"), "intercept": float("nan"), "n_points": int(sel.sum())}
    if sel.sum() < 3:
        return nan
    x = np.log(d[sel]) if log_x else d[sel]
    y = np.log(E[sel])
    if np.ptp(y) == 0:
        return nan
    res = stats.linregress(x, y)
    return {"r2": float(res.rvalue ** 2), "slope": float(res.slope), "intercept": float(res.intercept),
            "n_points": int(sel.sum())}


def fit_powerlaw(E: np.ndarray) -> dict:
    """log E vs log d."""
    return _depth_fit(E, log_x=True)


def fit_exponential(E: np.ndarray) -> dict:
    """log E vs d."""
    return _depth_fit(E, log_x=False)


def depth_energy(g, s, spec=None, cfg=None) -> dict:
    E = depth_energy_array(g, s)
    return {"E": E, "powerlaw": fit_powerlaw(E), "exponential": fit_exponential(E)}


# ---------------------------------------------------------------------------- 8-10: structural metrics
def ipr(g, s, spec: Spectrum, cfg=None) -> np.ndarray:
    """Inverse participation ratio of every mode."""
    return spec.ipr


def frac_localized(g, s, spec: Spectrum, cfg=None) -> float:
    cfg = cfg or DEFAULT
    return float(np.mean(spec.ipr > cfg.ipr_factor / spec.n))


def degeneracy(g, s, spec: Spectrum, cfg=None) -> dict:
    tol = (cfg or DEFAULT).degeneracy_tol
    groups = degenerate_groups(spec.lam, tol)
    sizes = np.array([b - a for a, b in groups])
    top = int(np.argmax(sizes))
    return {
        "n_distinct": len(groups),
        "max_multiplicity": int(sizes.max()),
        "max_multiplicity_lambda": float(spec.lam[groups[top][0]]),
        "frac_degenerate": float(sizes[sizes > 1].sum() / len(spec.lam)),
    }


def multiplicity_at(spec: Spectrum, value: float, tol: float | None = None) -> int:
    tol = spec.tol if tol is None else tol
    return int(np.sum(np.abs(spec.lam - value) < tol))


def spectral_gap_ratio(g, s, spec: Spectrum, cfg=None) -> float:
    if spec.k_used < 3 or spec.lam[1] <= spec.tol:
        return float("nan")
    return float(spec.lam[2] / spec.lam[1])


def fiedler_partition(g, s, spec: Spectrum, cfg=None) -> np.ndarray:
    return (spec.mode(2) >= 0).astype(np.int64)


def purity_of_partition(side: np.ndarray, labels: np.ndarray) -> float:
    """Best agreement of a two-way partition with the one-vs-rest groupings of ``labels``."""
    valid = labels >= 0
    side, labels = np.asarray(side, bool)[valid], labels[valid]
    best = 0.0
    for u in np.unique(labels):
        agree = float(np.mean(side == (labels == u)))
        best = max(best, agree, 1.0 - agree)
    return best


def partition_purity(g, s, spec: Spectrum, cfg=None) -> float:
    labels = g.labels.get("subgasket")
    if labels is None or not np.any(labels >= 0):
        return float("nan")
    return purity_of_partition(fiedler_partition(g, s, spec).astype(bool), labels)


# ---------------------------------------------------------------------------- 11: return probability
def lazy_walk_symmetric(g: XonGraph) -> sp.csr_matrix:
    """S = 1/2 I + 1/2 D^-1/2 A D^-1/2, similar to the lazy walk P = 1/2 I + 1/2 D^-1 A."""
    dinv = 1.0 / np.sqrt(np.maximum(g.degrees(), 1.0))
    a = sp.diags(dinv) @ g.adjacency() @ sp.diags(dinv)
    return (0.5 * sp.identity(g.n()) + 0.5 * a).tocsr()


def return_probability(g: XonGraph, ts, cfg=None, rng: np.random.Generator | None = None) -> np.ndarray:
    """Mean diagonal of P^t: exact from the spectrum of S when N <= dense_max, else Hutchinson."""
    cfg = cfg or DEFAULT
    ts = np.asarray(ts, dtype=int)
    S = lazy_walk_symmetric(g)
    n = g.n()
    if n <= cfg.dense_max:
        mu = np.linalg.eigvalsh(S.toarray())
        return np.array([np.mean(mu ** t) for t in ts])
    rng = rng if rng is not None else np.random.default_rng(cfg.seed)
    z = rng.choice([-1.0, 1.0], size=(n, int(cfg.rp_probes)))
    y = z.copy()
    want = set(int(t) for t in ts)
    got = {0: 1.0}
    for t in range(1, int(ts.max()) + 1):
        y = S @ y
        if t in want:
            got[t] = float(np.mean(np.sum(z * y, axis=0)) / n)
    return np.array([got[int(t)] for t in ts])


def spectral_dimension_est(g, s=None, spec=None, cfg=None, rng=None, window=None) -> dict:
    """d_s = -2 x slope of log RP(t) vs log t over the window (default [rp_t_min, rp_t_max])."""
    cfg = cfg or DEFAULT
    t0, t1 = window or (cfg.rp_t_min, cfg.rp_t_max)
    ts = np.arange(int(t0), int(t1) + 1)
    rp = return_probability(g, ts, cfg, rng)
    res = stats.linregress(np.log(ts), np.log(rp))
    return {"d_s": float(-2.0 * res.slope), "slope": float(res.slope), "r2": float(res.rvalue ** 2),
            "t": ts, "rp": rp}


# ---------------------------------------------------------------------------- V1.1 §3: clusters, low subspace
def low_eigenspace(spec: Spectrum, rel_tol: float = 1e-6) -> np.ndarray:
    """Columns of phi spanning the constant and every eigenvector with lambda <= lambda_2 (1 + rel_tol)."""
    if spec.k_used < 2:
        return spec.phi[:, :spec.k_used]
    m = int(np.sum(spec.lam <= spec.lam[1] * (1.0 + rel_tol)))
    return spec.phi[:, :max(m, 2)]


def kmeans(x: np.ndarray, k: int, restarts: int, rng: np.random.Generator, max_iter: int = 300) -> np.ndarray:
    """Lloyd's k-means with k-means++ seeding; labels of the lowest-inertia restart."""
    n = len(x)
    if n <= k:
        return np.arange(n)
    best, best_inertia = None, np.inf
    for _ in range(max(1, int(restarts))):
        first = int(rng.integers(n))
        centers = [x[first]]
        d2 = np.sum((x - x[first]) ** 2, axis=1)
        for _ in range(1, k):
            total = float(d2.sum())
            idx = int(rng.choice(n, p=d2 / total)) if total > 0 else int(rng.integers(n))
            centers.append(x[idx])
            d2 = np.minimum(d2, np.sum((x - x[idx]) ** 2, axis=1))
        c = np.array(centers, dtype=float)
        labels = None
        for _ in range(max_iter):
            dist = ((x[:, None, :] - c[None, :, :]) ** 2).sum(axis=2)
            new = dist.argmin(axis=1)
            if labels is not None and np.array_equal(new, labels):
                break
            labels = new
            for j in range(k):
                members = labels == j
                if members.any():
                    c[j] = x[members].mean(axis=0)
        inertia = float(dist[np.arange(n), labels].sum())
        if inertia < best_inertia - 1e-12:
            best, best_inertia = labels.copy(), inertia
    return best


def spectral_clusters(spec: Spectrum, n_clusters: int = 3, restarts: int = 20, seed: int = 0) -> np.ndarray:
    """k-means on the rows of the low eigenspace (``low_eigenspace``), cached on the spectrum.

    Labels are 0..k-1, ordered by each cluster's smallest vertex index.
    """
    key = (int(n_clusters), int(restarts), int(seed))
    cache = spec.__dict__.setdefault("_clusters", {})
    if key not in cache:
        labels = kmeans(low_eigenspace(spec), int(n_clusters), restarts, np.random.default_rng(int(seed)))
        uniq, first = np.unique(labels, return_index=True)
        remap = np.empty(int(uniq.max()) + 1, dtype=np.int64)
        remap[uniq[np.argsort(first)]] = np.arange(len(uniq))
        cache[key] = remap[labels]
    return cache[key]


def cluster_purity(clusters: np.ndarray, labels: np.ndarray) -> float:
    """Fraction of labelled vertices whose cluster matches their label under the best one-to-one matching."""
    valid = np.asarray(labels) >= 0
    c, lab = np.asarray(clusters)[valid], np.asarray(labels)[valid]
    if len(c) == 0:
        return float("nan")
    conf = np.array([[np.sum((c == a) & (lab == b)) for b in np.unique(lab)] for a in np.unique(c)])
    rows, cols = linear_sum_assignment(-conf)
    return float(conf[rows, cols].sum() / len(c))


def cluster_phases(s: State, clusters: np.ndarray, mask: np.ndarray | None = None
                   ) -> tuple[np.ndarray, np.ndarray]:
    """Per cluster (labels 0..k-1): order |<exp(i arg a)>| and mean phase over its vertices in mask.

    Clusters with no (nonzero) vertex in the mask get nan.
    """
    k = int(clusters.max()) + 1 if len(clusters) and clusters.max() >= 0 else 0
    amp = np.abs(s.a)
    sel = (clusters >= 0) & (amp > 0)
    if mask is not None:
        sel &= mask
    z = s.a[sel] / amp[sel]
    lab = clusters[sel]
    cnt = np.bincount(lab, minlength=k).astype(float)
    mean = (np.bincount(lab, weights=z.real, minlength=k) + 1j * np.bincount(lab, weights=z.imag, minlength=k))
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(cnt > 0, mean / np.maximum(cnt, 1.0), np.nan)
    return np.abs(mean), np.angle(mean)


def cluster_order(g, s: State, clusters: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Mean over clusters of the Kuramoto order within each cluster."""
    order, _ = cluster_phases(s, clusters, mask)
    order = order[np.isfinite(order)]
    return float(order.mean()) if len(order) else 0.0


def cluster_frequency_spread(phases: np.ndarray, times: np.ndarray, drift_max: float) -> dict:
    """Cluster mean frequencies from unwrapped mean phases (T, C) and the number of distinct ones.

    Frequency = least-squares slope over the window. Sorted frequencies closer than
    Delta = drift_max / window duration merge (their relative phase drifts by less than drift_max).
    """
    phases = np.atleast_2d(np.asarray(phases, dtype=float))
    times = np.asarray(times, dtype=float)
    ok = np.all(np.isfinite(phases), axis=0) if len(phases) else np.zeros(0, bool)
    span = float(times[-1] - times[0]) if len(times) > 1 else 0.0
    if span <= 0 or not ok.any():
        return {"frequencies": np.full(phases.shape[1], np.nan), "n_clusters_eff": float(min(1, ok.sum())),
                "delta": float("inf")}
    tc = times - times.mean()
    freqs = np.full(phases.shape[1], np.nan)
    ph = phases[:, ok]
    freqs[ok] = tc @ (ph - ph.mean(axis=0)) / float(tc @ tc)
    delta = float(drift_max) / span
    f = np.sort(freqs[ok])
    return {"frequencies": freqs, "n_clusters_eff": float(1 + np.sum(np.diff(f) > delta)), "delta": delta}


def harmonicity_osc_value(order: float, n_eff: float, n_max: int) -> float:
    """harmonicity_osc = cluster_order x log(1 + n_clusters_eff) / log(1 + n_clusters_max)."""
    return float(order * np.log1p(n_eff) / np.log1p(max(int(n_max), 1)))


class ClusterTracker:
    """Per-step cluster_order, n_clusters_eff and harmonicity_osc; keeps the last W+1 cluster phases."""

    def __init__(self, clusters: np.ndarray, window: int, drift_max: float, n_max: int | None = None):
        self.clusters = np.asarray(clusters, dtype=np.int64)
        k = int(self.clusters.max()) + 1 if len(self.clusters) else 0
        self.n_max = int(n_max) if n_max else max(k, 1)
        self.drift_max = float(drift_max)
        self.times: deque[float] = deque(maxlen=int(window) + 1)
        self.phases: deque[np.ndarray] = deque(maxlen=int(window) + 1)

    def update(self, s: State, mask: np.ndarray | None = None) -> dict[str, float]:
        order, phase = cluster_phases(s, self.clusters, mask)
        if self.phases:
            last = self.phases[-1]
            phase = np.where(np.isfinite(last), last + np.angle(np.exp(1j * (phase - last))), phase)
        self.times.append(float(s.t))
        self.phases.append(phase)
        spread = cluster_frequency_spread(np.array(self.phases), np.array(self.times), self.drift_max)
        finite = order[np.isfinite(order)]
        co = float(finite.mean()) if len(finite) else 0.0
        n_eff = spread["n_clusters_eff"]
        return {"cluster_order": co, "n_clusters_eff": n_eff,
                "harmonicity_osc": harmonicity_osc_value(co, n_eff, self.n_max)}


def spectral_k_gap(spec: Spectrum, k_max: int = 10) -> int:
    """k_gap = argmax over 2 <= k <= k_max of lambda_{k+1} / lambda_k (1-based); 3 on the gasket."""
    lam = spec.lam
    ks = [k for k in range(2, min(int(k_max), spec.k_used - 1) + 1) if lam[k - 1] > 0]
    if not ks:
        return min(spec.k_used, 1)
    return ks[int(np.argmax([lam[k] / lam[k - 1] for k in ks]))]


def low_subspace_fraction(g, s, spec: Spectrum, cfg=None, mask=None, k_gap: int | None = None) -> float:
    """Energy fraction in modes k <= k_gap (the constant plus the modes below the first spectral gap)."""
    cfg = cfg or DEFAULT
    k = k_gap or spectral_k_gap(spec, cfg.k_gap_max)
    return float(modal_decomposition(g, s, spec, mask).p[:k].sum())


def _cluster_order_metric(g, s, spec: Spectrum, cfg=None, mask=None) -> float:
    cfg = cfg or DEFAULT
    return cluster_order(g, s, spectral_clusters(spec, cfg.n_clusters, cfg.cluster_restarts, cfg.seed), mask)


def _spectral_clusters_metric(g, s, spec: Spectrum, cfg=None) -> np.ndarray:
    cfg = cfg or DEFAULT
    return spectral_clusters(spec, cfg.n_clusters, cfg.cluster_restarts, cfg.seed)


# ---------------------------------------------------------------------------- V1.2 §4: geometry metrics
def _eigenvalues(spec) -> np.ndarray:
    return np.asarray(spec.lam if isinstance(spec, Spectrum) else spec, dtype=float)


def plateau_values(spec, m: int = 3, tol: float = 1e-6) -> np.ndarray:
    """Mean eigenvalue of every level (eigenvalues chained within tol) of multiplicity >= m."""
    lam = _eigenvalues(spec)
    return np.array([lam[a:b].mean() for a, b in degenerate_groups(lam, tol) if b - a >= m])


def degenerate_fraction(spec, m: int = 3, tol: float = 1e-6) -> float:
    """Fraction of all eigenvalues that lie in levels of multiplicity >= m."""
    lam = _eigenvalues(spec)
    return float(sum(b - a for a, b in degenerate_groups(lam, tol) if b - a >= m) / len(lam))


def _matched_plateaus(spec_a, spec_b, m: int, tol: float) -> tuple[int, int, int]:
    """(|A|, |B|, |A & B|) for the plateau values of two spectra, matched one-to-one within tol in sorted order."""
    a, b = plateau_values(spec_a, m, tol), plateau_values(spec_b, m, tol)
    i = j = matched = 0
    while i < len(a) and j < len(b):
        if abs(a[i] - b[j]) <= tol:
            matched, i, j = matched + 1, i + 1, j + 1
        elif a[i] < b[j]:
            i += 1
        else:
            j += 1
    return len(a), len(b), matched


def plateau_persistence(spec_a, spec_b, m: int = 3, tol: float = 1e-6) -> float:
    """Jaccard overlap |A & B| / |A | B| of the multiplicity >= m eigenvalues of two spectra.

    A value of A and one of B within tol are the same plateau; NaN when neither spectrum has a plateau.
    """
    na, nb, matched = _matched_plateaus(spec_a, spec_b, m, tol)
    union = na + nb - matched
    return float(matched / union) if union else float("nan")


def plateau_containment(spec_a, spec_b, m: int = 3, tol: float = 1e-6) -> float:
    """|A & B| / |A|: the fraction of A's plateaus (the coarser level) still present in B."""
    na, _, matched = _matched_plateaus(spec_a, spec_b, m, tol)
    return float(matched / na) if na else float("nan")


def einstein_residual(d_s: float, d_f: float, d_w: float) -> float:
    """|d_s - 2 d_f / d_w|."""
    return float(abs(d_s - 2.0 * d_f / d_w))


def region_labels(g: XonGraph) -> np.ndarray | None:
    """Top-level sub-region of every vertex (-1 = none), or None if the geometry has none.

    ``subregion`` (carpet, vicsek, S(p, n)), ``subgasket`` (simplex rules), or on a tree the subtree
    of the root's child that contains the vertex (the root itself is -1).
    """
    for key in ("subregion", "subgasket"):
        lab = g.labels.get(key)
        if lab is not None and np.any(lab >= 0):
            return lab
    if g.rule == "tree" and g.n() > 1:
        lab = np.full(g.n(), -1, dtype=np.int64)
        top = np.flatnonzero(g.depth == 1)
        lab[top] = np.arange(len(top))
        for d in range(2, g.max_depth() + 1):
            at = np.flatnonzero(g.depth == d)
            lab[at] = lab[g.parent[at]]
        return lab
    return None


def seam_fraction(g: XonGraph, labels: np.ndarray | None = None) -> float:
    """Fraction of edges joining two different top-level sub-regions (edges at unlabeled vertices skipped)."""
    lab = region_labels(g) if labels is None else np.asarray(labels)
    if lab is None:
        return float("nan")
    u, v = lab[g.edges[:, 0]], lab[g.edges[:, 1]]
    valid = (u >= 0) & (v >= 0)
    return float(np.mean(u[valid] != v[valid])) if valid.any() else float("nan")


def hop_distances(g: XonGraph, sources, limit: float = np.inf, min_only: bool = False) -> np.ndarray:
    """Hop distances (len(sources), N) from each source, or (N,) to the nearest one; inf when farther than limit."""
    return csgraph.dijkstra(g.adjacency(), directed=False, indices=np.asarray(sources, dtype=np.int64),
                            unweighted=True, limit=limit, min_only=min_only)


def graph_diameter(g: XonGraph, sweeps: int = 4) -> int:
    """Diameter (hops) by repeated BFS from the farthest vertex found: a lower bound, exact on trees."""
    v, best = 0, 0
    for _ in range(sweeps):
        d = hop_distances(g, [v])[0]
        far = int(np.argmax(np.where(np.isfinite(d), d, -1.0)))
        if d[far] <= best:
            break
        best, v = int(d[far]), far
    return best


def automorphism_orbits(g: XonGraph, candidates) -> tuple[np.ndarray, int]:
    """Orbit label of every vertex under the candidate permutations that are automorphisms, and how many were.

    A candidate (perm[v] = image of v) counts only if it is a bijection that maps the edge set onto itself.
    Orbits are the connected components of the graph joining every v to perm[v] over those candidates.
    """
    n = g.n()
    e = np.sort(np.asarray(g.edges, dtype=np.int64), axis=1)
    keys = np.unique(e[:, 0] * n + e[:, 1])
    kept = []
    for perm in candidates:
        perm = np.asarray(perm, dtype=np.int64)
        if perm.shape != (n,) or perm.min(initial=0) < 0 or perm.max(initial=0) >= n or len(np.unique(perm)) != n:
            continue
        img = np.sort(perm[e], axis=1)
        if np.array_equal(np.unique(img[:, 0] * n + img[:, 1]), keys):
            kept.append(perm)
    if not kept:
        return np.arange(n), 0
    link = sp.coo_matrix((np.ones(n * len(kept)), (np.tile(np.arange(n), len(kept)), np.concatenate(kept))),
                         shape=(n, n))
    return csgraph.connected_components(link, directed=True, connection="weak")[1], len(kept)


def _eccentricity(adj: sp.csr_matrix, v: int) -> tuple[int, int]:
    """(eccentricity of v, vertices reached): the last vertex of a breadth-first order is a farthest one."""
    order, pred = csgraph.breadth_first_order(adj, v, directed=False, return_predecessors=True)
    w, e = int(order[-1]), 0
    while w != v:
        w, e = int(pred[w]), e + 1
    return e, len(order)


def exact_diameter(g: XonGraph, orbits: np.ndarray | None = None) -> dict:
    """Exact diameter (hops) from eccentricity bounds (Takes and Kosters 2011); inf if g is disconnected.

    A BFS from v bounds every w: max(d(v, w), ecc(v) - d(v, w)) <= ecc(w) <= ecc(v) + d(v, w). The largest
    lower bound is a lower bound on the diameter, and a vertex whose upper bound does not exceed it is settled.
    Sources alternate between the unsettled vertex with the smallest lower bound (a central one, whose BFS
    tightens many upper bounds) and the one with the largest upper bound. Once every unsettled vertex is known
    to reach the current bound, each only needs its own eccentricity, from a cheaper breadth-first order. The
    search ends when no vertex is unsettled, so the result is exact. ``orbits`` (``automorphism_orbits``)
    labels vertices that share one eccentricity; bounds are pooled over each orbit.
    """
    n = g.n()
    out = {"diameter": 0, "bfs": 0, "eccentricity_bfs": 0, "orbits": n}
    if n <= 1:
        return out
    adj = g.adjacency().tocsr()
    orb = np.arange(n) if orbits is None else np.unique(np.asarray(orbits), return_inverse=True)[1].ravel()
    k = int(orb.max()) + 1
    if k == n:
        orb = np.arange(n)
    by_orbit = np.argsort(orb, kind="stable")
    starts = np.flatnonzero(np.r_[True, np.diff(orb[by_orbit]) != 0])
    rep = by_orbit[starts]                                   # smallest vertex of each orbit
    pool = (lambda x, f: x) if k == n else (lambda x, f: f.reduceat(x[by_orbit], starts))
    lo, hi = np.zeros(k, dtype=np.int64), np.full(k, np.iinfo(np.int64).max, dtype=np.int64)
    best, bfs, pick_high = 0, 0, False
    o = int(orb[int(np.argmax(np.diff(adj.indptr)))])
    while True:
        d = csgraph.dijkstra(adj, directed=False, indices=int(rep[o]), unweighted=True)
        bfs += 1
        if not np.isfinite(d).all():
            return {**out, "diameter": float("inf"), "bfs": bfs, "orbits": k}
        d = d.astype(np.int64)
        e = int(d.max())
        lo = np.maximum(lo, pool(np.maximum(d, e - d), np.maximum))
        hi = np.minimum(hi, pool(e + d, np.minimum))
        lo[o] = hi[o] = e
        best = max(best, int(lo.max()))
        live = np.flatnonzero(hi > best)
        if len(live) == 0 or lo[live].min() >= best:
            break
        o = int(live[np.argmax(hi[live])] if pick_high else live[np.argmin(lo[live])])
        pick_high = not pick_high
    ecc_bfs = 0
    for o in live[np.argsort(-hi[live], kind="stable")]:
        if hi[o] > best:
            best = max(best, _eccentricity(adj, int(rep[o]))[0])
            ecc_bfs += 1
    return {"diameter": best, "bfs": bfs, "eccentricity_bfs": ecc_bfs, "orbits": k}


def outer_boundary(g: XonGraph) -> np.ndarray:
    """Vertices where a larger copy of the geometry would attach, for ``mass_dimension``.

    The ``boundary`` label (carpet: the outer sides; vicsek: the arm tips; S(p, n): the extreme
    vertices), the seed corners of the simplex rules, the outer ring of a lattice and the frontier of
    a tree; other graphs have none.
    """
    lab = g.labels.get("boundary")
    if lab is not None:
        return np.flatnonzero(lab > 0)
    if g.rule in ("gasket", "simplex", "adaptive"):
        return np.flatnonzero(g.depth == 0)
    if g.rule == "lattice":
        x, y = g.coords[:, 0], g.coords[:, 1]
        return np.flatnonzero((x == x.min()) | (x == x.max()) | (y == y.min()) | (y == y.max()))
    if g.rule == "tree":
        return g.frontier_vertices()
    return np.zeros(0, dtype=np.int64)


def _ball_masses(g: XonGraph, centers: np.ndarray, r_max: int, chunk: int = 16) -> np.ndarray:
    """(len(centers), r_max): vertices within r hops of each center, r = 1..r_max (BFS in chunks to bound memory)."""
    out = np.empty((len(centers), r_max), dtype=np.int64)
    for i in range(0, len(centers), chunk):
        for j, row in enumerate(hop_distances(g, centers[i:i + chunk], limit=r_max), start=i):
            out[j] = np.bincount(row[np.isfinite(row)].astype(np.int64), minlength=r_max + 1).cumsum()[1:]
    return out


def mass_dimension(g, s=None, spec=None, cfg=None, rng=None, r_max: int | None = None,
                   centers: str = "uniform") -> dict:
    """d_f from the mass-radius relation M(r) ~ r^d_f in the graph metric.

    M(r) = vertices within r hops (r = 1..R_max), averaged at each r over the centers at least r hops
    from ``outer_boundary``, so every ball counted is the same as in the unbounded geometry. By default
    R_max is the boundary distance reached by cfg.mass_eligible_frac of the vertices. d_f is the slope of
    log M vs log r over r in [cfg.mass_fit_from * R_max, R_max]: the smallest shells follow the lattice
    scale (on the square lattice M = 2r^2 + 2r + 1 gives 1.88 over r = 1..64, 1.97 over 16..64).

    centers="uniform" (E9c): cfg.mass_uniform_centers centers drawn uniformly from all vertices.
    centers="deep" (E9c as first registered, E9c_v1): cfg.mass_centers centers drawn from the vertices at
    least R_max from the boundary. Deep centers cluster around one point where the boundary is a few
    tips (vicsek: the central cross), and M(r) seen from one point oscillates log-periodically in r.
    """
    if centers not in ("uniform", "deep"):
        raise ValueError(f"centers must be 'uniform' or 'deep', not {centers!r}")
    cfg = cfg or DEFAULT
    rng = rng if rng is not None else np.random.default_rng(cfg.seed)
    diam = graph_diameter(g)
    bnd = outer_boundary(g)
    to_bnd = hop_distances(g, bnd, min_only=True) if len(bnd) else np.full(g.n(), np.inf)
    finite = to_bnd[np.isfinite(to_bnd)]
    if r_max is None:
        r_max = int(np.quantile(finite, 1.0 - cfg.mass_eligible_frac)) if len(finite) else diam // 4
    r_max = max(int(r_max), 4)
    r = np.arange(1, r_max + 1)
    r_lo = max(1, int(np.ceil(cfg.mass_fit_from * r_max)))
    eligible = np.flatnonzero(to_bnd >= r_max)
    out = {"estimator": centers, "diameter": diam, "r_max": r_max, "fit_from": r_lo, "eligible": len(eligible),
           "centers": 0, "centers_at_r_max": 0, "d_f": float("nan"), "r2": float("nan"), "r": r,
           "M": np.full(r_max, np.nan)}
    if centers == "deep":
        if len(eligible) == 0:
            return out
        chosen = rng.choice(eligible, size=min(int(cfg.mass_centers), len(eligible)), replace=False)
    else:
        chosen = rng.choice(g.n(), size=min(int(cfg.mass_uniform_centers), g.n()), replace=False)
    inside = to_bnd[chosen][:, None] >= r[None, :]
    n_inside = inside.sum(axis=0)
    mass = np.full(r_max, np.nan)
    ok = n_inside > 0
    mass[ok] = (_ball_masses(g, chosen, r_max) * inside).sum(axis=0)[ok] / n_inside[ok]
    fit_r = (r >= r_lo) & ok
    out.update(centers=len(chosen), centers_at_r_max=int(n_inside[-1]), M=mass)
    if fit_r.sum() >= 2:
        fit = stats.linregress(np.log(r[fit_r]), np.log(mass[fit_r]))
        out.update(d_f=float(fit.slope), r2=float(fit.rvalue ** 2))
    return out


def _lazy_from_simple(simple_msd: np.ndarray, ts: np.ndarray) -> np.ndarray:
    """Lazy-walk MSD at times ts: the Binomial(t, 1/2) mixture of the simple-walk MSD over the move count."""
    out = np.empty(len(ts))
    k_max = len(simple_msd) - 1
    for i, t in enumerate(ts):
        half, spread = 0.5 * t, 8.0 * np.sqrt(t) + 1.0
        k = np.arange(max(0, int(half - spread)), min(int(t), k_max, int(half + spread)) + 1)
        w = stats.binom.pmf(k, int(t), 0.5)
        out[i] = float(w @ simple_msd[k] / w.sum())
    return out


def walk_dimension(g, s=None, spec=None, cfg=None, rng=None) -> dict:
    """d_w from the mean squared graph displacement of lazy random walks, MSD(t) ~ t^(2/d_w).

    cfg.walk_walkers walkers start evenly on cfg.walk_starts random vertices. The walks are simulated
    as simple walks; the lazy MSD at time t is the Binomial(t, 1/2) mixture of the simple MSD over the
    number of moves. The fit (log MSD vs log t) runs from cfg.walk_t_min until the MSD reaches
    cfg.walk_saturation of its saturation value (the mean squared distance from a walker's start to a
    degree-weighted random vertex), or until cfg.walk_max_steps lazy steps.
    """
    cfg = cfg or DEFAULT
    rng = rng if rng is not None else np.random.default_rng(cfg.seed)
    n = g.n()
    adj = g.adjacency()
    indptr, nbrs = adj.indptr.astype(np.int64), adj.indices.astype(np.int64)
    deg = np.diff(indptr)
    starts = rng.choice(n, size=min(int(cfg.walk_starts), n), replace=False)
    dist = hop_distances(g, starts)
    if not np.isfinite(dist).all():
        raise ValueError("walk_dimension needs a connected graph")
    dist = dist.astype(np.int64)
    walkers = int(cfg.walk_walkers)
    home = np.arange(walkers) % len(starts)
    pos, row, flat = starts[home].copy(), home * n, dist.ravel()
    saturation = float((((dist.astype(float) ** 2) @ (deg / deg.sum()))[home]).mean())
    target = cfg.walk_saturation * saturation

    t_cap = int(cfg.walk_max_steps)
    k_stop = k_cap = t_cap // 2 + int(5 * np.sqrt(t_cap)) + 1
    msd = np.zeros(k_cap + 1)
    k, t_hit = 0, None
    while k < k_stop:
        m = min(2048, k_stop - k)
        u = rng.random((m, walkers))
        for i in range(m):
            pos = nbrs[indptr[pos] + (u[i] * deg[pos]).astype(np.int64)]
            d = flat[row + pos]
            msd[k + i + 1] = (d @ d) / walkers
        k += m
        if t_hit is None:
            above = np.flatnonzero(msd[1:k + 1] >= target)
            if len(above):
                t_hit = 2 * int(above[0] + 1)
                k_stop = min(k_cap, t_hit // 2 + int(5 * np.sqrt(t_hit)) + 1)
    msd = msd[:k + 1]
    t_end = min(t_hit, t_cap) if t_hit is not None else t_cap
    out = {"diameter": graph_diameter(g), "saturation_msd": saturation, "target_msd": target,
           "reached_target": t_hit is not None and t_hit <= t_cap, "t_end": int(t_end),
           "walkers": walkers, "starts": len(starts), "moves": int(k),
           "d_w": float("nan"), "slope": float("nan"), "r2": float("nan"), "t": np.array([]), "msd": np.array([])}
    out["saturation_over_diameter_sq"] = saturation / max(out["diameter"], 1) ** 2
    if t_end < 4 * cfg.walk_t_min:
        return out
    ts = np.unique(np.round(np.geomspace(cfg.walk_t_min, t_end, 40)).astype(np.int64))
    lazy = _lazy_from_simple(msd, ts)
    fit = stats.linregress(np.log(ts), np.log(lazy))
    out.update(d_w=float(2.0 / fit.slope), slope=float(fit.slope), r2=float(fit.rvalue ** 2), t=ts, msd=lazy)
    return out


def _degenerate_fraction_metric(g, s, spec: Spectrum, cfg=None) -> float:
    cfg = cfg or DEFAULT
    return degenerate_fraction(spec, cfg.plateau_multiplicity, cfg.degeneracy_tol)


def _seam_fraction_metric(g, s=None, spec=None, cfg=None) -> float:
    return seam_fraction(g)


# ---------------------------------------------------------------------------- registry
@dataclass(frozen=True)
class Metric:
    name: str
    fn: Callable
    kind: str          # "state" (reads State.a) or "structure" (graph / spectrum only)
    description: str
    trace: bool = False     # per-step float recorded by trace_metrics

    def __call__(self, g, s, spec, cfg=None, **kw):
        return self.fn(g, s, spec, cfg, **kw)


METRICS: dict[str, Metric] = {m.name: m for m in [
    Metric("fundamental_fraction", fundamental_fraction, "state", "p_1, energy in the constant mode", trace=True),
    Metric("spectral_entropy", spectral_entropy, "state", "-sum p log p and n_eff = exp(entropy)"),
    Metric("spectral_concentration", spectral_concentration, "state", "1 - entropy / log K", trace=True),
    Metric("roughness", roughness, "state", "Plomp-Levelt roughness R and consonance 1/(1+R)"),
    Metric("phase_order", phase_order, "state", "Kuramoto order over vertex phases", trace=True),
    Metric("harmonicity", harmonicity, "state", "coherence x log(1+n_eff)/log(1+K)", trace=True),
    Metric("depth_energy", depth_energy, "state", "E[d] with power-law and exponential fits"),
    Metric("ipr", ipr, "structure", "inverse participation ratio per mode"),
    Metric("frac_localized", frac_localized, "structure", "fraction of modes with ipr > 5/N"),
    Metric("degeneracy", degeneracy, "structure", "distinct eigenvalues, max multiplicity, degenerate fraction"),
    Metric("spectral_gap_ratio", spectral_gap_ratio, "structure", "lambda_3 / lambda_2"),
    Metric("fiedler_partition", fiedler_partition, "structure", "sign of phi_2"),
    Metric("partition_purity", partition_purity, "structure", "Fiedler sign vs sub-gasket labels"),
    Metric("spectral_dimension_est", spectral_dimension_est, "structure", "-2 x slope of log RP vs log t"),
    Metric("low_subspace_fraction", low_subspace_fraction, "state",
           "energy fraction in modes k <= k_gap (first spectral gap; 3 on the gasket)", trace=True),
    Metric("cluster_order", _cluster_order_metric, "state", "mean Kuramoto order within the spectral clusters"),
    Metric("spectral_clusters", _spectral_clusters_metric, "structure",
           "k-means (k = 3) on the rows of the low eigenspace"),
    Metric("degenerate_fraction", _degenerate_fraction_metric, "structure",
           "fraction of eigenvalues in levels of multiplicity >= 3"),
    Metric("seam_fraction", _seam_fraction_metric, "structure", "fraction of edges between top-level sub-regions"),
    Metric("mass_dimension", mass_dimension, "structure", "d_f from the mass-radius relation (graph metric)"),
    Metric("walk_dimension", walk_dimension, "structure", "d_w from the MSD of lazy random walks"),
]}
