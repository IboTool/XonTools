import numpy as np
import pytest

from xon.config import XonConfig
from xon.dynamics import State
from xon.growth import RULES, TreeRule, build_graph, get_rule, interpolate_amplitudes, regular_simplex
from xon.sandbox import Sandbox

CFG = XonConfig()


def test_registered_rule_is_used_by_build_graph_and_sandbox(monkeypatch):
    class BinaryTree(TreeRule):
        """Tree rule with the branching factor fixed at 2."""
        name = "binary"

        def grow(self, g, state, cfg, rng=None):
            return super().grow(g, state, cfg.replace(branch=2), rng)

        def predict_new_vertices(self, g, cfg):
            return super().predict_new_vertices(g, cfg.replace(branch=2))

    monkeypatch.setitem(RULES, "binary", BinaryTree)
    assert build_graph(CFG, 3, "binary").n() == 1 + 2 + 4 + 8
    sb = Sandbox(CFG.replace(growth_rule="binary", target_level=3))
    assert sb.grow_to_target()[0] == 3 and sb.g.n() == 15


@pytest.mark.parametrize("level", range(7))
def test_gasket_vertex_count(level):
    g = build_graph(CFG, level, "gasket")
    assert g.n() == (3 ** (level + 1) + 3) // 2


@pytest.mark.parametrize("level", range(6))
def test_gasket_edges_deduplicated(level):
    g = build_graph(CFG, level, "gasket")
    e = g.edges
    assert np.all(e[:, 0] < e[:, 1])
    assert len(np.unique(e, axis=0)) == len(e)
    assert len(e) == 3 ** (level + 1)
    deg = g.degrees()
    if level >= 1:
        assert sorted(np.unique(deg).tolist()) == [2, 4]
        assert int((deg == 2).sum()) == 3


def test_vertices_are_merged():
    g = build_graph(CFG, 5, "gasket")
    keys = np.round(g.coords / CFG.merge_tol).astype(np.int64)
    assert len(np.unique(keys, axis=0)) == g.n()


def test_depth_labels():
    rule = get_rule("gasket")
    g = rule.seed(CFG)
    for level in range(1, 6):
        n0, d0 = g.n(), g.depth.copy()
        g, _ = rule.grow(g, None, CFG)
        assert np.array_equal(g.depth[:n0], d0)
        assert np.all(g.depth[n0:] == d0.max() + 1)
        assert int((g.depth == level).sum()) == 3 ** level
        assert g.version == level
    assert np.array_equal(g.frontier_vertices(), np.flatnonzero(g.depth == g.depth.max()))


def _barycentric(points, corners):
    m = np.vstack([corners.T, np.ones(len(corners))])
    rhs = np.vstack([points.T, np.ones(len(points))])
    return np.linalg.solve(m, rhs).T


def test_subgasket_labels():
    g = build_graph(CFG, 5, "gasket")
    lab = g.labels["subgasket"]
    assert np.bincount(lab).tolist() == [122, 122, 122]
    bary = _barycentric(g.coords, regular_simplex(2))
    for s in range(3):
        assert np.all(bary[lab == s, s] >= 0.5 - 1e-9), "vertex outside its top-level sub-gasket"
    g3 = build_graph(CFG, 3, "gasket")
    assert np.array_equal(lab[:g3.n()], g3.labels["subgasket"]), "labels must be inherited"


@pytest.mark.parametrize("n,level", [(3, 0), (3, 1), (3, 3), (4, 2)])
def test_simplex_counts(n, level):
    g = build_graph(CFG.replace(simplex_dim=n), level, "simplex")
    assert g.n() == (n + 1) + (n + 1) * ((n + 1) ** level - 1) // 2
    assert g.n_edges() == (n + 1) ** level * n * (n + 1) // 2
    assert g.coords.shape[1] == n
    assert g.layout2d().shape == (g.n(), 2)


def test_simplex_dim2_equals_gasket():
    a = build_graph(CFG.replace(simplex_dim=2), 4, "simplex")
    b = build_graph(CFG, 4, "gasket")
    assert np.array_equal(a.edges, b.edges)


def test_tree():
    g = build_graph(CFG.replace(branch=3), 4, "tree")
    assert g.n() == (3 ** 5 - 1) // 2
    assert g.n_edges() == g.n() - 1
    assert np.bincount(g.depth).tolist() == [1, 3, 9, 27, 81]
    assert np.all(g.depth[g.parent[1:]] == g.depth[1:] - 1)


def test_lattice_is_static():
    rule = get_rule("lattice")
    g = rule.seed(CFG.replace(lattice_side=7))
    assert g.n() == 49 and g.n_edges() == 2 * 7 * 6
    g2, _ = rule.grow(g, None, CFG)
    assert g2 is g and np.all(g.depth == 0)


def test_adaptive_refines_energetic_cells():
    cfg = CFG.replace(refine_floor=0.0, refine_threshold=1.5)
    rule = get_rule("adaptive")
    g = rule.seed(cfg)
    s = State(np.ones(g.n(), dtype=complex))
    for _ in range(3):
        g, s = rule.grow(g, s, cfg)
    assert len(s.a) == g.n()
    # concentrate energy on the vertices of one leaf cell: that cell must be refined
    a = np.full(g.n(), 0.01, dtype=complex)
    a[g.simplices[0]] = 10.0
    n0 = g.n()
    g2, s2 = rule.grow(g, State(a), cfg)
    assert g2.n() > n0
    assert not any(set(row) == set(g.simplices[0]) for row in g2.simplices.tolist())
    assert np.all(g2.edges[:, 0] < g2.edges[:, 1])
    assert len(np.unique(g2.edges, axis=0)) == g2.n_edges()


def test_adaptive_never_stalls():
    cfg = CFG.replace(refine_floor=0.0, refine_threshold=1e9)
    rule = get_rule("adaptive")
    g = rule.seed(cfg)
    for _ in range(4):
        n0 = g.n()
        g, _ = rule.grow(g, None, cfg, np.random.default_rng(0))
        assert g.n() > n0


def test_state_extension_by_interpolation():
    rule = get_rule("gasket")
    g = rule.seed(CFG)
    a = np.array([1.0, 2.0 * np.exp(1j * np.pi / 2), 3.0 * np.exp(-1j * np.pi / 2)])
    g1, s1 = rule.grow(g, State(a.copy(), t=1.5, step=7), CFG)
    assert len(s1.a) == g1.n() == 6 and s1.t == 1.5 and s1.step == 7
    assert np.allclose(s1.a[:3], a)
    new = s1.a[3:]
    expected = interpolate_amplitudes(a[[0, 0, 1]], a[[1, 2, 2]])
    assert np.allclose(np.sort_complex(new), np.sort_complex(expected))
    # mean amplitude and circular-mean phase
    z = interpolate_amplitudes(np.array([1.0 + 0j]), np.array([3.0j]))
    assert np.isclose(abs(z[0]), 2.0) and np.isclose(np.angle(z[0]), np.pi / 4)
