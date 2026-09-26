import numpy as np
import pytest

from xon.config import XonConfig
from xon.dynamics import (DYNAMICS, CompleteCoupling, OscillatorDynamics, State, StuartLandauDynamics,
                          WaveDynamics, WaveDynamicsV1, damping_profile, effective_dt, get_dynamics,
                          natural_frequencies)
from xon.graph import graph_from_edges
from xon.growth import build_graph, get_rule
from xon.metrics import modal_decomposition, phase_order_state
from xon.problems import MaxCutProblem, max_cut_brute_force, oscillator_solve
from xon.spectrum import get_spectrum

CFG = XonConfig()
# each wave with its damping switched off
UNDAMPED = {WaveDynamics: dict(alpha=0.0, beta=0.0), WaveDynamicsV1: dict(gamma0=0.0, gamma1=0.0)}
WAVES = pytest.mark.parametrize("wave", [WaveDynamics, WaveDynamicsV1], ids=["wave", "wave_v1"])


@WAVES
def test_energy_conserved_without_damping_or_drive(wave):
    g = build_graph(CFG, 4, "gasket")
    cfg = CFG.replace(drive="none", integrator="modal", **UNDAMPED[wave])
    dyn = wave()
    rng = np.random.default_rng(0)
    s = dyn.init_state(g, cfg, rng)
    e0 = dyn.energy(g, s)
    for _ in range(1000):
        s = dyn.step(g, s, cfg, rng)
    assert abs(dyn.energy(g, s) - e0) / e0 < 1e-6
    assert s.step == 1000 and np.isclose(s.t, 1000 * dyn.dt(g, cfg))


def test_rayleigh_modal_energies_decay_at_two_alpha_plus_beta_lambda():
    g = build_graph(CFG, 4, "gasket")
    spec = get_spectrum(g, CFG)
    cfg = CFG.replace(drive="none")
    dyn = WaveDynamics()
    s = dyn.init_state(g, cfg, np.random.default_rng(0))
    e0 = np.abs(spec.phi.T @ s.a) ** 2
    for _ in range(500):
        s = dyn.step(g, s, cfg, None, spec)
    predicted = e0 * np.exp(-2 * (cfg.alpha + cfg.beta * spec.lam) * s.t)
    assert np.max(np.abs(np.abs(spec.phi.T @ s.a) ** 2 - predicted) / predicted) < 1e-8
    assert s.t == pytest.approx(500 * dyn.dt(g, cfg))


def test_wave_v1_damping_profile_older_is_damped_more():
    g = build_graph(CFG, 4, "gasket")
    gam = damping_profile(g, CFG)
    by_depth = [gam[g.depth == d][0] for d in range(5)]
    assert np.all(np.diff(by_depth) < 0)
    assert np.isclose(by_depth[-1], CFG.gamma0) and np.isclose(by_depth[0], CFG.gamma0 + CFG.gamma1)
    lattice = build_graph(CFG, 0, "lattice")
    assert np.allclose(damping_profile(lattice, CFG), CFG.gamma0)
    assert np.isclose(WaveDynamicsV1().dt(g, CFG), effective_dt(g, CFG))


@WAVES
def test_noise_drive_only_touches_frontier(wave):
    g = build_graph(CFG, 3, "gasket")
    dyn = wave()
    s0 = State(np.zeros(g.n(), dtype=complex))
    s1 = dyn.step(g, s0, CFG.replace(drive="noise"), np.random.default_rng(0))
    front = g.frontier_mask(0)
    assert np.all(s1.a[~front] == 0) and np.all(s1.a[front] != 0)


@WAVES
def test_rk4_matches_modal(wave):
    g = build_graph(CFG, 4, "gasket")
    dyn = wave()
    s0 = dyn.init_state(g, CFG, np.random.default_rng(1))
    a, b = s0, s0
    for _ in range(100):
        a = dyn.step(g, a, CFG.replace(drive="none", integrator="rk4"), None)
        b = dyn.step(g, b, CFG.replace(drive="none", integrator="modal"), None)
    assert np.linalg.norm(a.a - b.a) / np.linalg.norm(b.a) < 1e-2


@WAVES
def test_tone_drive_excites_chosen_eigenspace(wave):
    """A tone drives a frequency, i.e. the whole eigenspace of lambda_k.

    The forcing is uniform on the (symmetric) frontier, so only modes overlapping the frontier
    indicator can be reached; pick the non-fundamental mode with the largest overlap.
    """
    g = build_graph(CFG, 3, "gasket")
    spec = get_spectrum(g, CFG)
    overlap = np.abs(spec.phi.T @ g.frontier_mask(0).astype(float))
    k = int(np.argmax(overlap[1:])) + 2
    a, b = next(ab for ab in spec.groups if ab[0] <= k - 1 < ab[1])
    cfg = CFG.replace(drive="tone", drive_mode=k, **UNDAMPED[wave])
    dyn = wave()
    s = State(np.zeros(g.n(), dtype=complex))
    for _ in range(2000):
        s = dyn.step(g, s, cfg, None)
    p = modal_decomposition(g, s, spec).p
    assert p[a:b].sum() > 0.5
    detuned = cfg.replace(tone_resonant=False)
    s = State(np.zeros(g.n(), dtype=complex))
    for _ in range(2000):
        s = dyn.step(g, s, detuned, None)
    assert modal_decomposition(g, s, spec).p[a:b].sum() < 0.5


@pytest.mark.parametrize("cls", [WaveDynamics, WaveDynamicsV1, StuartLandauDynamics, OscillatorDynamics])
def test_probe_injection(cls):
    g = build_graph(CFG, 2, "gasket")
    dyn = cls()
    s = dyn.probe(g, State(np.zeros(g.n(), dtype=complex)), 4, 2.0)
    assert s.a[4] == 2.0 and np.count_nonzero(s.a) == 1
    dyn.request_probe(3, 1.0)
    s0 = dyn.init_state(g, CFG, np.random.default_rng(0))
    s2 = dyn.step(g, s0, CFG.replace(drive="probe"), None)
    assert dyn.pending_probe is None
    s3 = dyn.step(g, s0, CFG.replace(drive="probe"), None)
    assert s2.a[3] != pytest.approx(s3.a[3])


def test_sink_profile_bound_and_refusal():
    g = build_graph(CFG, 4, "gasket")
    spec = get_spectrum(g, CFG)
    dyn = WaveDynamics()
    bound = WaveDynamics.sink_bound(CFG, spec)
    assert bound == pytest.approx(0.1 * CFG.beta * spec.lam[1])
    cfg = CFG.replace(sink=True, sink_gamma=bound, sink_depth=2, drive="none")
    prof = WaveDynamics.sink_profile(g, cfg)
    old = g.depth <= g.max_depth() - 2
    assert np.all(prof[old] == bound) and np.all(prof[~old] == 0)
    assert not dyn.uses_modal(g, cfg) and dyn.check(g, cfg, spec) is None
    s = dyn.step(g, dyn.init_state(g, cfg, np.random.default_rng(0)), cfg, None, spec)
    assert np.all(np.isfinite(s.a))
    too_strong = cfg.replace(sink_gamma=CFG.sink_gamma)       # the 0.01 default exceeds the bound here
    with pytest.raises(ValueError, match=r"0\.1 \* beta \* lambda_2"):
        dyn.step(g, s, too_strong, None, spec)
    assert f"{bound:.4g}" in dyn.check(g, too_strong, spec)


def test_propagate_matches_repeated_steps():
    g = build_graph(CFG, 3, "gasket")
    spec = get_spectrum(g, CFG)
    dyn = WaveDynamics()
    rng = np.random.default_rng(2)
    cols = np.column_stack([dyn.init_state(g, CFG, rng).a for _ in range(3)])
    for integrator in ("modal", "rk4"):
        cfg = CFG.replace(drive="none", integrator=integrator)
        out = dyn.propagate(g, cols, cfg, spec, 50)
        for j in range(3):
            s = State(cols[:, j])
            for _ in range(50):
                s = dyn.step(g, s, cfg, None, spec)
            assert np.allclose(out[:, j], s.a, rtol=1e-10, atol=1e-12)


def test_stuart_landau_single_node_reaches_limit_cycle():
    g = graph_from_edges(1, np.zeros((0, 2), int))
    dyn = StuartLandauDynamics()
    cfg = CFG.replace(drive="none", sl_mu=1.0)
    s = State(np.array([0.1 + 0j]))
    for _ in range(400):
        s = dyn.step(g, s, cfg, None)
    assert abs(abs(s.a[0]) - np.sqrt(cfg.sl_mu)) < 1e-3


def test_stuart_landau_two_identical_nodes_synchronize():
    """With c^2 >> beta the anti-phase state is stable too, so start inside the in-phase basin."""
    g = graph_from_edges(2, [[0, 1]])
    dyn = StuartLandauDynamics()
    cfg = CFG.replace(drive="none", omega_mode="identical")
    s = State(np.array([1.0 + 0j, np.exp(1.0j)]))
    for _ in range(2000):
        s = dyn.step(g, s, cfg, None)
    assert abs(np.angle(s.a[0] / s.a[1])) < 1e-6
    assert np.allclose(np.abs(s.a), np.sqrt(cfg.sl_mu), atol=1e-6)


def test_stuart_landau_dt_caps():
    g = build_graph(CFG, 3, "gasket")
    dyn = StuartLandauDynamics()
    lam_bound = 2 * g.degrees().max()
    for cfg in (CFG, CFG.replace(c=3.0), CFG.replace(sl_mu=4.0)):
        dt = dyn.dt(g, cfg)
        assert cfg.c ** 2 * lam_bound * dt < 0.5 and cfg.sl_mu * dt < 0.1


def test_complete_coupling_matches_dense_matrices():
    n, w = 7, 0.3
    x = np.random.default_rng(0).standard_normal((n, 2)) + 1j
    A = w * (np.ones((n, n)) - np.eye(n))
    L = np.diag(A.sum(axis=1)) - A
    assert np.allclose(CompleteCoupling(n, w, "laplacian") @ x, L @ x)
    assert np.allclose(CompleteCoupling(n, w, "adjacency") @ x, A @ x)
    assert CompleteCoupling(n, w, "laplacian").row_bound() == pytest.approx(np.abs(L).sum(axis=1).max())


def test_natural_frequencies():
    g = build_graph(CFG, 3, "gasket")
    assert np.allclose(natural_frequencies(g, CFG.replace(omega_mode="identical")), CFG.omega0)
    by_depth = natural_frequencies(g, CFG)
    assert np.allclose(by_depth, CFG.omega0 + CFG.delta_omega * g.depth / 3)
    rnd = CFG.replace(omega_mode="random")
    g4, _ = get_rule("gasket").grow(g, None, CFG)
    w3, w4 = natural_frequencies(g, rnd), natural_frequencies(g4, rnd)
    assert np.allclose(w3, w4[:g.n()])          # a vertex keeps its frequency as the graph grows
    assert abs(w4.std() - CFG.omega_sigma) < 0.05


def test_kuramoto_complete_graph_synchronizes():
    n = 20
    g = graph_from_edges(n, [(i, j) for i in range(n) for j in range(i + 1, n)])
    dyn = OscillatorDynamics()
    cfg = CFG.replace(osc_K=2.0, omega_mode="identical", drive="none")
    for seed in range(3):
        rng = np.random.default_rng(seed)
        s = dyn.init_state(g, cfg, rng)
        for _ in range(200):
            s = dyn.step(g, s, cfg, rng)
        assert phase_order_state(s) > 0.99
        assert np.allclose(np.abs(s.a), 1.0)


def test_oscillator_maxcut_six_cycle_reaches_optimum():
    cycle = MaxCutProblem(6, np.array([[i, (i + 1) % 6] for i in range(6)]))
    best = max_cut_brute_force(6, cycle.edges)
    hits = sum(cycle.score(oscillator_solve(cycle, CFG, np.random.default_rng(seed))[0])["cut"] == best
               for seed in range(10))
    assert hits >= 8


def test_oscillator_energy_and_noise_placement():
    g = build_graph(CFG, 2, "gasket")
    dyn = get_dynamics("oscillator")
    s = dyn.init_state(g, CFG, np.random.default_rng(0))
    assert np.allclose(np.abs(s.a), 1.0)
    aligned = State(np.ones(g.n(), dtype=complex))
    assert np.isclose(dyn.energy(g, aligned), -2.0 * g.n_edges())
    theta = np.angle(s.a)
    A = g.adjacency().toarray()
    assert np.isclose(dyn.energy(g, s), -np.sum(A * np.cos(theta[:, None] - theta[None, :])))
    quiet = CFG.replace(osc_K=0.0, omega_mode="identical", omega0=0.0, osc_sigma=0.1)
    moved = lambda c: ~np.isclose(dyn.step(g, s, c, np.random.default_rng(1)).a, s.a)
    assert np.array_equal(moved(quiet.replace(drive="noise")), g.frontier_mask(0))
    assert moved(quiet.replace(drive="none")).all()


def test_registry_lists_four_available_dynamics():
    assert list(DYNAMICS) == ["wave", "wave_v1", "stuart_landau", "oscillator"]
    for name in DYNAMICS:
        dyn = get_dynamics(name)
        assert dyn.name == name and dyn.available
    with pytest.raises(ValueError, match="unknown dynamics"):
        get_dynamics("nope")
