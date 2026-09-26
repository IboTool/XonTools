import numpy as np

from xon.config import XonConfig
from xon.growth import build_graph, get_rule
from xon.spectrum import Spectrum, degenerate_groups, get_spectrum

CFG = XonConfig()


def test_gasket_level5_regression():
    """Known values: 70 distinct eigenvalues; eigenvalue 6 has multiplicity 120."""
    g = build_graph(CFG, 5, "gasket")
    spec = Spectrum(g, cfg=CFG)
    assert spec.method == "dense" and spec.k_used == 366
    assert len(degenerate_groups(spec.lam, 1e-6)) == 70
    assert int(np.sum(np.abs(spec.lam - 6.0) < 1e-6)) == 120


def test_canonical_basis_is_an_eigenbasis():
    g = build_graph(CFG, 4, "gasket")
    spec = Spectrum(g, cfg=CFG)
    phi = spec.phi
    assert np.allclose(phi.T @ phi, np.eye(spec.k_used), atol=1e-10)
    assert np.allclose(g.laplacian() @ phi, phi * spec.lam, atol=1e-6)
    assert np.allclose(spec.mode(1), 1 / np.sqrt(g.n()))


def test_localized_basis_increases_localization():
    g = build_graph(CFG, 4, "gasket")
    loc = Spectrum(g, cfg=CFG)
    raw = Spectrum(g, cfg=CFG.replace(canonical_basis="raw"))
    assert loc.ipr.sum() >= raw.ipr.sum() - 1e-9


def test_cache_keyed_on_version():
    rule = get_rule("gasket")
    g = build_graph(CFG, 3, "gasket")
    s1 = get_spectrum(g, CFG)
    assert get_spectrum(g, CFG) is s1
    g2, _ = rule.grow(g, None, CFG)
    s2 = get_spectrum(g2, CFG)
    assert s2 is not s1 and s2.version == g2.version and s2.n == g2.n()


def test_sparse_matches_dense_lowest_modes():
    g = build_graph(CFG, 5, "gasket")
    dense = Spectrum(g, cfg=CFG)
    sparse = Spectrum(g, k=20, cfg=CFG.replace(dense_max=100))
    assert sparse.method == "sparse"
    assert sparse.k_used >= 20
    assert np.allclose(sparse.lam, dense.lam[:sparse.k_used], atol=1e-8)
    assert np.allclose(g.laplacian() @ sparse.phi, sparse.phi * sparse.lam, atol=1e-6)


def test_sparse_above_dense_max_keeps_close_levels_apart():
    """Level 7 (N = 3282) takes the eigsh path; its low levels are only ~1e-6 apart."""
    g = build_graph(CFG, 7, "gasket")
    spec = Spectrum(g, cfg=CFG)
    assert g.n() > CFG.dense_max and spec.method == "sparse" and spec.k_used >= CFG.k_modes
    dense = np.linalg.eigvalsh(g.laplacian().toarray())[:spec.k_used]
    assert np.allclose(spec.lam, dense, rtol=0, atol=1e-9)
    assert np.allclose(spec.phi.T @ spec.phi, np.eye(spec.k_used), atol=1e-8)
    assert np.abs(g.laplacian() @ spec.phi - spec.phi * spec.lam).max() < 1e-9


def test_fiedler_vector_is_sparsest_sign_cut():
    from xon.spectrum import ratio_cuts
    g = build_graph(CFG, 4, "gasket")
    spec = Spectrum(g, cfg=CFG)
    block = spec.phi[:, 1:3]
    th = np.linspace(0, np.pi, 90, endpoint=False)
    rc = ratio_cuts(block @ np.stack([np.cos(th), np.sin(th)]), g.edges)
    assert ratio_cuts(spec.mode(2)[:, None], g.edges)[0] <= rc.min() + 1e-12
