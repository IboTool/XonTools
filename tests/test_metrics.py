import numpy as np

from xon.config import XonConfig
from xon.dynamics import State
from xon.graph import graph_from_edges
from xon.growth import build_graph
from xon.metrics import (METRICS, ClusterTracker, cluster_frequency_spread, cluster_order, cluster_purity,
                         degeneracy, depth_energy, depth_energy_array, fit_exponential, fit_powerlaw,
                         frac_localized, fundamental_fraction, harmonicity_osc_value, harmonicity_value, kmeans,
                         low_eigenspace, low_subspace_fraction, modal_decomposition, partition_purity,
                         phase_order, plomp_levelt, purity_of_partition, roughness_md, spectral_clusters,
                         spectral_dimension_est, spectral_gap_ratio, spectral_k_gap, trace_metrics)
from xon.spectrum import get_spectrum

CFG = XonConfig()


def _gasket(level=4):
    g = build_graph(CFG, level, "gasket")
    return g, get_spectrum(g, CFG)


def test_constant_mode():
    g, spec = _gasket()
    s = State(np.ones(g.n(), dtype=complex))
    m = trace_metrics(g, s, spec, CFG)
    assert np.isclose(m["fundamental_fraction"], 1.0)
    assert np.isclose(m["n_eff"], 1.0)
    assert np.isclose(m["consonance"], 1.0)
    assert np.isclose(m["phase_order"], 1.0)
    assert np.isclose(m["spectral_concentration"], 1.0)
    assert np.isclose(fundamental_fraction(g, s, spec), 1.0)


def test_two_equal_modes():
    g, spec = _gasket()
    a = (spec.mode(1) + spec.mode(40)).astype(complex)
    md = modal_decomposition(g, State(a), spec)
    m = trace_metrics(g, State(a), spec, CFG)
    assert np.isclose(m["n_eff"], 2.0) and np.isclose(m["fundamental_fraction"], 0.5)
    assert np.isclose(m["spectral_concentration"], 1 - np.log(2) / np.log(spec.k_used))
    f1, f2 = spec.omega[0] * CFG.freq_scale, spec.omega[39] * CFG.freq_scale
    assert np.isclose(roughness_md(md, CFG), 0.5 * plomp_levelt(np.array(f1), np.array(f2)))
    assert np.isclose(m["harmonicity"], m["consonance"] * np.log(3) / np.log(1 + spec.k_used))


def test_roughness_curve():
    assert plomp_levelt(np.array(440.0), np.array(440.0)) == 0
    near = plomp_levelt(np.array(440.0), np.array(460.0))
    far = plomp_levelt(np.array(440.0), np.array(880.0))
    assert near > far >= 0


def test_harmonicity_factor_switch_uses_stored_components():
    g, spec = _gasket()
    s = State(np.random.default_rng(0).standard_normal(g.n()) + 0j)
    m = trace_metrics(g, s, spec, CFG)
    for f in ("consonance", "spectral_concentration", "phase_order"):
        assert np.isclose(m[f"harmonicity_{f}"], harmonicity_value(m[f], m["n_eff"], m["K"]))
    m2 = trace_metrics(g, s, spec, CFG.replace(harmonicity_coherence="phase_order"))
    assert np.isclose(m2["harmonicity"], m["harmonicity_phase_order"])


def test_phase_order():
    g, spec = _gasket(2)
    rng = np.random.default_rng(1)
    aligned = State(np.exp(1j * 0.3) * rng.uniform(0.5, 2, g.n()))
    assert np.isclose(phase_order(g, aligned), 1.0)
    opposite = State(np.array([1, -1] * (g.n() // 2) + [1] * (g.n() % 2), dtype=complex))
    assert phase_order(g, opposite) < 0.1


def test_depth_energy_and_fits():
    g, _ = _gasket(4)
    s = State(np.random.default_rng(0).standard_normal(g.n()) + 0j)
    E = depth_energy_array(g, s)
    assert len(E) == 5 and np.isclose(E.sum(), np.sum(np.abs(s.a) ** 2))
    d = np.arange(1, 12, dtype=float)
    power = np.r_[0.0, 5.0 * d ** -1.7]
    expo = np.r_[1.0, 5.0 * np.exp(-0.6 * d)]
    assert fit_powerlaw(power)["r2"] > fit_exponential(power)["r2"]
    assert fit_exponential(expo)["r2"] > fit_powerlaw(expo)["r2"]
    assert np.isclose(fit_powerlaw(power)["slope"], -1.7)
    assert set(depth_energy(g, s)) == {"E", "powerlaw", "exponential"}


def test_structural_metrics_gasket5():
    g, spec = _gasket(5)
    deg = degeneracy(g, None, spec, CFG)
    assert deg["n_distinct"] == 70 and deg["max_multiplicity"] == 120
    assert np.isclose(deg["max_multiplicity_lambda"], 6.0)
    assert frac_localized(g, None, spec, CFG) > 0.25
    assert np.isclose(spectral_gap_ratio(g, None, spec, CFG), 1.0)  # lambda_2 is doubly degenerate
    assert 0.5 <= partition_purity(g, None, spec, CFG) <= 1.0


def test_ipr_bounds():
    g, spec = _gasket(3)
    ipr = METRICS["ipr"](g, None, spec)
    assert np.isclose(ipr[0], 1.0 / g.n())
    assert np.all(ipr <= 1.0 + 1e-12) and np.all(ipr >= 1.0 / g.n() - 1e-12)


def test_purity_of_partition():
    labels = np.array([0, 0, 1, 1, 2, 2])
    assert purity_of_partition(np.array([1, 1, 0, 0, 0, 0], bool), labels) == 1.0
    assert purity_of_partition(np.array([0, 0, 1, 1, 1, 1], bool), labels) == 1.0
    assert np.isclose(purity_of_partition(np.array([1, 0, 0, 0, 0, 0], bool), labels), 5 / 6)


def test_spectral_dimension_of_lattices():
    from xon.graph import XonGraph, canonical_edges
    n = 1500
    chain = XonGraph(coords=np.c_[np.arange(n), np.zeros(n)].astype(float), simplices=np.zeros((0, 2), int),
                     edges=canonical_edges(np.c_[np.arange(n - 1), np.arange(1, n)]),
                     depth=np.zeros(n, int), parent=np.full(n, -1))
    assert abs(spectral_dimension_est(chain, cfg=CFG)["d_s"] - 1.0) < 0.1
    sq = build_graph(CFG.replace(lattice_side=70), 0, "lattice")  # N = 4900 > dense_max: Hutchinson path
    est = spectral_dimension_est(sq, cfg=CFG, rng=np.random.default_rng(0))
    assert abs(est["d_s"] - 2.0) < 0.15


def _three_cliques(size=10):
    """Three K_size joined in a Z3-symmetric ring, so lambda_2 is doubly degenerate like the gasket's."""
    edges = [(b + i, b + j) for b in (0, size, 2 * size) for i in range(size) for j in range(i + 1, size)]
    edges += [(0, size), (size, 2 * size), (2 * size, 0)]
    g = graph_from_edges(3 * size, edges)
    return g, get_spectrum(g, CFG), np.repeat(np.arange(3), size)


def test_spectral_clusters_recover_planted_communities():
    g, spec, planted = _three_cliques()
    assert low_eigenspace(spec).shape == (g.n(), 3)
    clusters = spectral_clusters(spec, 3, 20, seed=0)
    assert cluster_purity(clusters, planted) == 1.0
    assert sorted(np.unique(clusters)) == [0, 1, 2] and clusters[0] == 0
    assert spectral_clusters(spec, 3, 20, seed=0) is clusters          # cached on the spectrum


def test_kmeans_and_cluster_purity():
    rng = np.random.default_rng(0)
    centers = np.array([[0, 0], [5, 0], [0, 5]])
    x = np.repeat(centers, 30, axis=0) + 0.3 * rng.standard_normal((90, 2))
    truth = np.repeat(np.arange(3), 30)
    assert cluster_purity(kmeans(x, 3, 5, rng), truth) == 1.0
    assert cluster_purity(np.array([0, 0, 1, 1, 2, 2]), np.array([2, 2, 0, 0, 1, 1])) == 1.0
    assert np.isclose(cluster_purity(np.array([0, 0, 1, 1, 2, 1]), np.array([2, 2, 0, 0, 1, 1])), 5 / 6)
    assert cluster_purity(np.array([0, 1, 1]), np.array([-1, 1, 1])) == 1.0     # unlabelled vertices ignored


def test_cluster_order_per_cluster_phase_locking():
    g, spec, planted = _three_cliques()
    locked = State(np.exp(1j * np.array([0.3, 2.0, -1.5])[planted]))
    assert np.isclose(cluster_order(g, locked, planted), 1.0)
    assert phase_order(g, locked) < 0.5                    # locked within clusters, not globally
    rnd = State(np.exp(2j * np.pi * np.random.default_rng(1).random(g.n())))
    assert cluster_order(g, rnd, planted) < 0.6
    assert np.isclose(cluster_order(g, locked, planted, mask=planted == 1), 1.0)


def test_cluster_frequency_spread_merges_within_delta():
    t = np.linspace(0.0, 10.0, 201)
    spread = lambda w: cluster_frequency_spread(np.outer(t, w), t, drift_max=1.0)
    out = spread([1.0, 1.0, 2.0])
    assert np.isclose(out["delta"], 0.1) and np.allclose(out["frequencies"], [1.0, 1.0, 2.0])
    assert out["n_clusters_eff"] == 2
    assert spread([1.0, 1.05, 2.0])["n_clusters_eff"] == 2
    assert spread([1.0, 1.5, 2.0])["n_clusters_eff"] == 3
    assert spread([0.7, 0.7, 0.7])["n_clusters_eff"] == 1


def test_harmonicity_osc_and_tracker():
    assert np.isclose(harmonicity_osc_value(1.0, 3, 3), 1.0)
    assert np.isclose(harmonicity_osc_value(1.0, 1, 3), np.log(2) / np.log(4))
    assert harmonicity_osc_value(0.0, 3, 3) == 0.0
    g, spec, planted = _three_cliques()
    for w, n_eff in (([1.0, 2.0, 3.0], 3), ([1.5, 1.5, 1.5], 1)):
        tracker = ClusterTracker(planted, window=200, drift_max=1.0)
        for step in range(201):
            t = 0.01 * step
            out = tracker.update(State(np.exp(1j * np.asarray(w)[planted] * t), t, step))
        assert np.isclose(out["cluster_order"], 1.0) and out["n_clusters_eff"] == n_eff
        assert np.isclose(out["harmonicity_osc"], np.log1p(n_eff) / np.log(4))


def test_k_gap_and_low_subspace_fraction():
    for level in (3, 4, 5):
        assert spectral_k_gap(_gasket(level)[1]) == 3
    g, spec = _gasket(4)
    low = State(spec.phi[:, 1].astype(complex))
    high = State(spec.phi[:, 3].astype(complex))
    assert np.isclose(low_subspace_fraction(g, low, spec, CFG), 1.0)
    assert np.isclose(low_subspace_fraction(g, high, spec, CFG), 0.0)
    assert np.isclose(low_subspace_fraction(g, high, spec, k_gap=4), 1.0)
    assert np.isclose(trace_metrics(g, low, spec, CFG)["low_subspace_fraction"], 1.0)
