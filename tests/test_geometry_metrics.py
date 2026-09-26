"""V1.2 geometry metrics (XON_SIM_GEOMETRY_V1_2.md §4)."""
import numpy as np
import pytest

from scipy.sparse import csgraph

from xon.config import XonConfig
from xon.geometry import CLOSED_FORM_GEOMETRIES, build_geometry, candidate_symmetries, closed_form
from xon.graph import graph_from_edges
from xon.growth import build_graph
from xon.metrics import (METRICS, automorphism_orbits, degenerate_fraction, einstein_residual, exact_diameter,
                         graph_diameter, mass_dimension, outer_boundary, plateau_persistence, plateau_values,
                         region_labels, seam_fraction, walk_dimension)
from xon.spectrum import Spectrum, get_spectrum

CFG = XonConfig()


def cycle(n: int):
    return graph_from_edges(n, np.c_[np.arange(n), (np.arange(n) + 1) % n])


def test_degenerate_fraction_counts_levels_of_multiplicity_m():
    lam = np.array([0.0, 1.0, 1.0, 1.0 + 5e-7, 2.0, 2.0, 3.0, 3.0, 3.0, 3.0])
    assert degenerate_fraction(lam, m=3, tol=1e-6) == pytest.approx(7 / 10)
    assert degenerate_fraction(lam, m=2, tol=1e-6) == pytest.approx(9 / 10)
    assert degenerate_fraction(lam, m=3, tol=1e-8) == pytest.approx(4 / 10)
    assert plateau_values(lam, 3, 1e-6) == pytest.approx([1.0 + 5e-7 / 3, 3.0])


def test_plateau_persistence_is_the_jaccard_overlap():
    a = np.r_[0.0, [1.0] * 3, [2.0] * 4, [5.0] * 3]
    b = np.r_[0.0, [1.0 + 4e-7] * 3, [5.0] * 5, [7.0] * 3, [8.0] * 3]
    assert plateau_persistence(a, b, 3, 1e-6) == pytest.approx(2 / 5)
    assert plateau_persistence(a, a, 3, 1e-6) == 1.0
    assert np.isnan(plateau_persistence(np.arange(5.0), np.arange(6.0), 3, 1e-6))


def test_gasket_plateaus_persist_between_levels():
    s4, s5 = get_spectrum(build_graph(CFG, 4, "gasket"), CFG), get_spectrum(build_graph(CFG, 5, "gasket"), CFG)
    assert degenerate_fraction(s5) > 0.5
    assert 3.0 in np.round(plateau_values(s5), 6) and 5.0 in np.round(plateau_values(s5), 6)
    assert 0 < plateau_persistence(s4, s5) <= 1


def test_einstein_residual():
    assert einstein_residual(2 * np.log(3) / np.log(5), np.log(3) / np.log(2), np.log(5) / np.log(2)) < 1e-12
    assert einstein_residual(1.5, 2.0, 2.0) == pytest.approx(0.5)


def test_region_labels_and_seam_fraction():
    g = build_graph(CFG, 3, "gasket")
    assert region_labels(g) is g.labels["subgasket"]
    # the sub-gaskets touch at 3 junction vertices, each labeled with one of its two sub-gaskets: the
    # junction's 2 edges into the other one are the only seam edges among the 3^(L+1)
    assert seam_fraction(g) == pytest.approx(6 / 3 ** 4)
    tree = build_graph(CFG.replace(branch=3), 4, "tree")
    lab = region_labels(tree)
    assert lab[0] == -1 and np.bincount(lab[1:]).tolist() == [40, 40, 40]
    assert seam_fraction(tree) == 0.0
    carpet = build_graph(CFG, 2, "carpet")
    lab = region_labels(carpet)
    cut = lab[carpet.edges[:, 0]] != lab[carpet.edges[:, 1]]
    assert seam_fraction(carpet) == pytest.approx(cut.mean()) and 0 < cut.mean() < 0.2
    assert np.isnan(seam_fraction(build_graph(CFG.replace(lattice_side=5), 0, "lattice")))


def test_outer_boundary_per_geometry():
    assert outer_boundary(build_graph(CFG, 3, "gasket")).tolist() == [0, 1, 2]
    assert len(outer_boundary(build_graph(CFG.replace(lattice_side=6), 0, "lattice"))) == 20
    assert len(outer_boundary(build_graph(CFG, 3, "vicsek"))) == 8
    assert len(outer_boundary(build_graph(CFG.replace(sierpinski_p=4), 2, "sierpinski_p"))) == 4
    assert len(outer_boundary(cycle(10))) == 0


def test_graph_diameter():
    assert graph_diameter(cycle(101)) == 50
    assert graph_diameter(build_graph(CFG, 5, "gasket")) == 32
    assert graph_diameter(build_graph(CFG, 3, "carpet")) == 54


def _brute_diameter(g, chunk: int = 256) -> float:
    """BFS distances from every vertex (unit-weight shortest paths), a chunk of sources at a time."""
    adj = g.adjacency()
    return max(float(csgraph.dijkstra(adj, directed=False, unweighted=True,
                                      indices=np.arange(s, min(s + chunk, g.n()))).max())
               for s in range(0, g.n(), chunk))


def test_exact_diameter_equals_all_pairs_bfs():
    rng = np.random.default_rng(1)
    for _ in range(150):
        n = int(rng.integers(2, 50))
        tree = [(i, int(rng.integers(i))) for i in range(1, n)]
        extra = [tuple(rng.choice(n, 2, replace=False)) for _ in range(int(rng.integers(n)))]
        g = graph_from_edges(n, np.array(tree + extra))
        assert exact_diameter(g)["diameter"] == _brute_diameter(g)
    path = graph_from_edges(30, np.c_[np.arange(29), np.arange(1, 30)])
    assert exact_diameter(path)["diameter"] == 29 and exact_diameter(cycle(31))["diameter"] == 15
    assert exact_diameter(graph_from_edges(1, np.zeros((0, 2), dtype=int)))["diameter"] == 0
    assert exact_diameter(graph_from_edges(5, np.array([[0, 1], [2, 3]])))["diameter"] == float("inf")


@pytest.mark.parametrize("name,level,orbits", [("gasket", 1, 2), ("carpet", 1, 3), ("vicsek", 1, 2),
                                               ("sierpinski_p", 1, 2), ("gasket", 4, 23), ("carpet", 2, 14)])
def test_symmetry_orbits_are_verified_and_keep_the_diameter(name, level, orbits):
    g = build_geometry(name, CFG, level)
    labels, kept = automorphism_orbits(g, candidate_symmetries(g))
    assert kept == 2 and len(np.unique(labels)) == orbits
    assert exact_diameter(g, labels)["diameter"] == exact_diameter(g)["diameter"] == _brute_diameter(g)


def _levels_up_to(n_max: int) -> list[tuple[str, int]]:
    """(geometry, level) for every level of E9c's geometries with at most n_max vertices."""
    p = int(CFG.e9_sierpinski_p)
    return [(name, L) for name in CLOSED_FORM_GEOMETRIES
            for L in range(20) if closed_form(name, L, p)["vertices"] <= n_max]


def _assert_symmetry_diameter_is_brute_force(name: str, level: int):
    g = build_geometry(name, CFG, level)
    labels, kept = automorphism_orbits(g, candidate_symmetries(g))
    assert kept == 2
    assert exact_diameter(g, labels)["diameter"] == _brute_diameter(g)


@pytest.mark.parametrize("name,level", _levels_up_to(2000))
def test_symmetry_diameter_equals_brute_force(name, level):
    _assert_symmetry_diameter_is_brute_force(name, level)


@pytest.mark.slow
@pytest.mark.parametrize("name,level", _levels_up_to(7000))
def test_symmetry_diameter_equals_brute_force_slow(name, level):
    _assert_symmetry_diameter_is_brute_force(name, level)


def test_automorphism_orbits_reject_what_is_not_an_automorphism():
    g = build_geometry("gasket", CFG, 3)
    swap = np.arange(g.n())
    swap[[0, 5]] = swap[[5, 0]]
    not_bijective = np.zeros(g.n(), dtype=np.int64)
    labels, kept = automorphism_orbits(g, [np.random.default_rng(0).permutation(g.n()), swap, not_bijective])
    assert kept == 0 and np.array_equal(labels, np.arange(g.n()))
    assert candidate_symmetries(build_graph(CFG.replace(branch=3), 3, "tree")) == []


def test_mass_dimension_on_known_graphs():
    ring = mass_dimension(cycle(800), cfg=CFG)
    assert ring["d_f"] == pytest.approx(1.0, abs=0.05) and ring["r_max"] == 100
    assert ring["centers"] == ring["centers_at_r_max"] == CFG.mass_uniform_centers  # no boundary: every ball fits
    grid = mass_dimension(build_graph(CFG.replace(lattice_side=121), 0, "lattice"), cfg=CFG)
    assert grid["d_f"] == pytest.approx(2.0, abs=0.08) and grid["estimator"] == "uniform"
    assert grid["centers"] == CFG.mass_uniform_centers > grid["centers_at_r_max"] > 0
    assert grid["fit_from"] == int(np.ceil(0.25 * grid["r_max"]))


def test_mass_dimension_uniform_and_deep_centers():
    g = build_graph(CFG.replace(lattice_side=121), 0, "lattice")
    uniform, deep = (mass_dimension(g, cfg=CFG, rng=np.random.default_rng(0), centers=c) for c in ("uniform", "deep"))
    # on a lattice every ball that stays inside is the same diamond, so the choice of centers cannot matter
    assert uniform["d_f"] == pytest.approx(deep["d_f"], abs=1e-12)
    assert np.allclose(uniform["M"], deep["M"]) and np.allclose(deep["M"], 2 * deep["r"] ** 2 + 2 * deep["r"] + 1)
    assert deep["centers"] == deep["centers_at_r_max"] == CFG.mass_centers
    with pytest.raises(ValueError):
        mass_dimension(g, cfg=CFG, centers="central")


def test_walk_dimension_on_known_graphs():
    cfg = CFG.replace(walk_walkers=400, walk_starts=20)
    ring = walk_dimension(cycle(600), cfg=cfg, rng=np.random.default_rng(1))
    assert ring["reached_target"] and ring["d_w"] == pytest.approx(2.0, abs=0.12)
    grid = walk_dimension(build_graph(CFG.replace(lattice_side=101), 0, "lattice"), cfg=CFG,
                          rng=np.random.default_rng(2))
    assert grid["d_w"] == pytest.approx(2.0, abs=0.1)
    assert grid["t"][0] == CFG.walk_t_min and grid["t"][-1] == grid["t_end"]
    assert grid["target_msd"] == pytest.approx(CFG.walk_saturation * grid["saturation_msd"])


def test_walk_window_stops_at_the_step_cap():
    cfg = CFG.replace(walk_walkers=100, walk_starts=10, walk_max_steps=400)
    out = walk_dimension(cycle(5000), cfg=cfg, rng=np.random.default_rng(0))
    assert not out["reached_target"] and out["t_end"] == 400 and np.isfinite(out["d_w"])


@pytest.mark.parametrize("rule,k", [("gasket", 6), ("carpet", 8), ("vicsek", 5)])
def test_lowest_modes_match_the_canonical_basis(rule, k):
    spec = Spectrum(build_graph(CFG, 3 if rule == "gasket" else 2, rule), cfg=CFG)
    low = spec.lowest_modes(k)
    assert spec._phi is None and low.shape == (spec.n, k)
    assert np.allclose(low, spec.phi[:, :k])


def test_new_metrics_are_registered():
    g = build_graph(CFG, 3, "carpet")
    spec = get_spectrum(g, CFG)
    assert METRICS["degenerate_fraction"](g, None, spec, CFG) == degenerate_fraction(spec)
    assert METRICS["seam_fraction"](g, None, spec, CFG) == seam_fraction(g)
    assert {"mass_dimension", "walk_dimension"} <= set(METRICS)
