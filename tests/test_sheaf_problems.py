import itertools

import numpy as np

from xon.config import XonConfig
from xon.dynamics import State
from xon.growth import build_graph, get_rule
from xon.problems import MaxCutProblem, max_cut_brute_force, max_cut_exact
from xon.sheaf import CellularSheaf, sample_sections

CFG = XonConfig()


def test_flat_sheaf_has_k_dimensional_kernel():
    g = build_graph(CFG, 3, "gasket")
    rng = np.random.default_rng(0)
    truth, frames = CellularSheaf.random_flat(g, 2, rng)
    assert truth.global_sections(g).shape[1] == 2
    for x in sample_sections(frames, rng, 5):
        assert truth.consistency(g, x) < 1e-20
    assert np.allclose(truth.F_head @ np.transpose(truth.F_head, (0, 2, 1)), np.eye(2))


def test_coboundary_and_identity_laplacian():
    g = build_graph(CFG, 2, "gasket")
    sh = CellularSheaf.identity(g, 3)
    assert sh.coboundary(g).shape == (g.n_edges() * 3, g.n() * 3)
    L = sh.laplacian(g).toarray()
    expected = np.kron(g.laplacian().toarray(), np.eye(3))
    assert np.allclose(L, expected)
    x = np.random.default_rng(0).standard_normal(g.n() * 3)
    assert np.isclose(sh.dirichlet_energy(g, x), x @ L @ x)


def test_learning_and_inference():
    g = build_graph(CFG, 3, "gasket")
    rng = np.random.default_rng(1)
    truth, frames = CellularSheaf.random_flat(g, 2, rng)
    learned = CellularSheaf.identity(g, 2)
    hist = learned.learn(g, sample_sections(frames, rng, 30), eta=0.1, steps=300)
    assert hist[-1] < 1e-3 * hist[0]
    assert np.allclose(np.linalg.norm(learned.F_head, axis=(1, 2)), 1.0)
    x_true = sample_sections(frames, rng, 1)[0]
    clamp = np.zeros(g.n(), bool)
    clamp[rng.choice(g.n(), 13, replace=False)] = True
    x = learned.diffuse(g, np.zeros_like(x_true), 0.2, 3000, clamp, x_true)
    free = np.repeat(~clamp, 2)
    assert np.mean((x[free] - x_true[free]) ** 2) < 1e-4
    _, trace = learned.diffuse(g, np.ones_like(x_true), 0.2, 50, record_every=10)
    assert trace[-1][1] <= trace[0][1]


def test_sheaf_survives_growth():
    rule = get_rule("gasket")
    g = build_graph(CFG, 2, "gasket")
    sh = CellularSheaf.random(g, 2, np.random.default_rng(0))
    g2, _ = rule.grow(g, None, CFG)
    sh2 = sh.adapt(g2)
    assert sh2.F_head.shape == (g2.n_edges(), 2, 2)
    sh2.laplacian(g2)
    # Sierpinski subdivision replaces every old edge, so all maps are new identity maps
    assert np.allclose(sh2.F_head, np.eye(2))
    lat = build_graph(CFG, 0, "lattice")
    sh3 = CellularSheaf.random(lat, 2, np.random.default_rng(0)).adapt(lat)
    assert np.allclose(sh3.F_head, CellularSheaf.random(lat, 2, np.random.default_rng(0)).F_head)


def _best_assignment(n, edges):
    best, arg = -1, None
    for bits in itertools.product([0, 1], repeat=n - 1):
        s = np.array(bits + (0,))
        cut = int(np.sum(s[edges[:, 0]] != s[edges[:, 1]]))
        if cut > best:
            best, arg = cut, s
    return best, arg


def test_maxcut_score():
    p = MaxCutProblem.random_regular(10, 3, seed=3)
    opt, assignment = _best_assignment(10, p.edges)
    assert p.optimum() == opt == max_cut_brute_force(10, p.edges)
    state = State(np.exp(1j * np.pi * assignment))
    sc = p.score(state)
    assert sc == {"cut": opt, "optimum": opt, "ratio": 1.0}
    same_side = p.score(State(np.ones(10, dtype=complex)))
    assert same_side["cut"] == 0 and same_side["ratio"] == 0.0


def test_maxcut_exact_solver_and_encodings():
    for n, seed in [(12, 0), (16, 1), (20, 2)]:
        p = MaxCutProblem.random_regular(n, 3, seed)
        assert max_cut_exact(n, p.edges) == max_cut_brute_force(n, p.edges)
    p = MaxCutProblem.random_regular(40, 3, seed=0)
    assert 0 < p.optimum() <= len(p.edges)
    J = p.to_ising()
    assert (J != J.T).nnz == 0 and np.all(J.data == -1)
    spins = np.where(np.random.default_rng(0).random(40) < 0.5, 1.0, -1.0)
    uncut = len(p.edges) - p.cut_value(spins)
    assert np.isclose(p.to_sheaf().dirichlet_energy(p.graph(), spins), 4 * uncut)
    assert p.graph().n() == 40
