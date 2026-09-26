"""Dynamics interface and the registered dynamics (§3.3, §6.2; V1.1 §2).

Design rule: every dynamics operates on ``State.a`` (complex, one entry per vertex). Oscillators
are the special case |a| = 1. Adding a dynamics = one class + one entry in ``DYNAMICS``.

* ``wave``           da/dt = -i c^2 L a - (alpha I + beta L) a - Gamma_sink a + F      (V1.1 §2.1)
* ``wave_v1``        da/dt = -i c^2 L a - Gamma(depth) a + F                           (V1 §3.3)
* ``stuart_landau``  limit-cycle oscillators, amplitude and phase, coupled through L    (V1.1 §2.2)
* ``oscillator``     Kuramoto / oscillator Ising machine on the phases, a = exp(i theta) (V1.1 §2.3)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import scipy.sparse as sp

from .graph import XonGraph
from .spectrum import Spectrum, get_spectrum

SINK_BOUND_FACTOR = 0.1     # V1.1 §2.1: gamma_s <= 0.1 beta lambda_2 keeps the non-commuting sink a perturbation


@dataclass
class State:
    a: np.ndarray   # (N,) complex amplitude + phase per vertex
    t: float = 0.0
    step: int = 0

    def copy(self) -> "State":
        return State(self.a.copy(), self.t, self.step)


class Dynamics(Protocol):
    name: str
    available: bool     # False: listed in the UI but not selectable (e.g. a stub)

    def init_state(self, g: XonGraph, cfg, rng: np.random.Generator) -> State: ...

    # spec: the cached spectrum of g, passed by callers that already hold it; may be ignored
    def step(self, g: XonGraph, s: State, cfg, rng: np.random.Generator,
             spec: Spectrum | None = None) -> State: ...

    def energy(self, g: XonGraph, s: State) -> float: ...

    def dt(self, g: XonGraph, cfg) -> float: ...


# ---------------------------------------------------------------------------- helpers
def complex_normal(rng: np.random.Generator, n: int) -> np.ndarray:
    """Circular complex Gaussian with E|z|^2 = 1."""
    return (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2.0)


def real_matmul(m, z: np.ndarray) -> np.ndarray:
    """m @ z for real m and complex z (a vector or the columns of a matrix) without promoting m to complex."""
    if z.ndim == 1:
        zz = np.column_stack([z.real, z.imag])
        out = np.asarray(m @ zz)
        return out[:, 0] + 1j * out[:, 1]
    k = z.shape[1]
    out = np.asarray(m @ np.hstack([z.real, z.imag]))
    return out[:, :k] + 1j * out[:, k:]


def damping_profile(g: XonGraph, cfg) -> np.ndarray:
    """wave_v1: gamma(d) = gamma0 + gamma1 * ((d_max - d) / d_max)^p ; older vertices are damped more."""
    d = g.depth.astype(float)
    d_max = float(g.max_depth())
    if d_max == 0:
        return np.full(g.n(), float(cfg.gamma0))
    return cfg.gamma0 + cfg.gamma1 * ((d_max - d) / d_max) ** cfg.damping_p


def lambda_max_bound(g: XonGraph) -> float:
    """Gershgorin bound on the largest Laplacian eigenvalue."""
    return 2.0 * float(g.degrees().max()) if g.n_edges() else 0.0


def operator_bound(op) -> float:
    """Largest absolute row sum of a coupling operator (the Gershgorin bound for a Laplacian)."""
    if hasattr(op, "row_bound"):
        return float(op.row_bound())
    if op.shape[0] == 0:
        return 0.0
    return float(np.asarray(abs(op).sum(axis=1)).max())


def capped_dt(cfg, rate: float, dt: float | None = None) -> float:
    """cfg.dt, capped (if cfg.dt_auto) so that rate * dt <= cfg.dt_safety."""
    dt = float(cfg.dt if dt is None else dt)
    if cfg.dt_auto and rate * dt > cfg.dt_safety:
        dt = cfg.dt_safety / rate
    return dt


def effective_dt(g: XonGraph, cfg) -> float:
    """wave_v1: cfg.dt, capped (if cfg.dt_auto) so that c^2 * lambda_max * dt <= cfg.dt_safety."""
    return capped_dt(cfg, cfg.c ** 2 * lambda_max_bound(g))


def natural_frequencies(g: XonGraph, cfg) -> np.ndarray:
    """omega_i for stuart_landau and oscillator: identical, by depth, or random (fixed per vertex).

    Random draws come from a stream seeded by cfg.seed alone, so a vertex keeps its frequency as
    the graph grows (new vertices are appended and take the next draws).
    """
    n = g.n()
    if cfg.omega_mode == "identical":
        return np.full(n, float(cfg.omega0))
    if cfg.omega_mode == "by_depth":
        d_max = g.max_depth()
        if d_max == 0:
            return np.full(n, float(cfg.omega0))
        return cfg.omega0 + cfg.delta_omega * g.depth.astype(float) / d_max
    if cfg.omega_mode == "random":
        z = np.random.default_rng([int(cfg.seed), 0x0E6A]).standard_normal(n)
        return cfg.omega0 + cfg.omega_sigma * z
    raise ValueError(f"unknown omega_mode {cfg.omega_mode!r}")


class CompleteCoupling:
    """Complete graph on n vertices with uniform edge weight w, as a matrix-free operator.

    kind="laplacian": x -> (D - A) x = w (n x - sum x);  kind="adjacency": x -> A x = w (sum x - x).
    """

    def __init__(self, n: int, weight: float, kind: str = "laplacian"):
        if kind not in ("laplacian", "adjacency"):
            raise ValueError(kind)
        self.n, self.w, self.kind = int(n), float(weight), kind
        self.shape = (self.n, self.n)

    def __matmul__(self, x: np.ndarray) -> np.ndarray:
        total = x.sum(axis=0)
        if self.kind == "laplacian":
            return self.w * (self.n * x - total)
        return self.w * (total - x)

    def row_bound(self) -> float:
        return (2.0 if self.kind == "laplacian" else 1.0) * self.w * max(self.n - 1, 0)


def tone_force(g: XonGraph, t: float, cfg, spec: Spectrum) -> np.ndarray:
    """Tone forcing F(t) on the frontier for drive mode k (1-based), for the wave dynamics.

    omega_k = sqrt(lambda_k) is the metric frequency; under this first-order equation mode k
    rotates as exp(-i c^2 lambda_k t), so with cfg.tone_resonant the drive follows that phase
    (a literal exp(+i sqrt(lambda_k) t) is off-resonance and drives no particular mode).
    """
    k = int(np.clip(cfg.drive_mode, 1, spec.k_used))
    lam_k = float(spec.lam[k - 1])
    if cfg.tone_resonant:
        phase = np.exp(-1j * cfg.c ** 2 * lam_k * t)
    else:
        phase = np.exp(1j * np.sqrt(max(lam_k, 0.0)) * t)
    f = np.zeros(g.n(), dtype=complex)
    f[g.frontier_vertices()] = cfg.drive_amp * phase
    return f


def _rk4(f, y: np.ndarray, t: float, dt: float) -> np.ndarray:
    k1 = f(y, t)
    k2 = f(y + 0.5 * dt * k1, t + 0.5 * dt)
    k3 = f(y + 0.5 * dt * k2, t + 0.5 * dt)
    k4 = f(y + dt * k3, t + dt)
    return y + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)


class _Probe:
    """Probe injections shared by the complex-amplitude dynamics."""

    pending_probe: tuple[int, complex] | None = None

    def probe(self, g: XonGraph, s: State, vertex: int, amp: complex) -> State:
        """One-off injection at a single vertex (UI probe tool)."""
        a = s.a.copy()
        a[int(vertex)] += amp
        return State(a, s.t, s.step)

    def request_probe(self, vertex: int, amp: complex) -> None:
        """Queue a probe injection for the next step (drive="probe")."""
        self.pending_probe = (int(vertex), complex(amp))

    def _apply_probe(self, g: XonGraph, a: np.ndarray, cfg) -> np.ndarray:
        if cfg.drive == "probe" and self.pending_probe is not None:
            v, amp = self.pending_probe
            self.pending_probe = None
            if 0 <= v < g.n():
                a = a.copy()
                a[v] += amp
        return a

    def _frontier_noise(self, g: XonGraph, a: np.ndarray, sigma: float, dt: float,
                        rng: np.random.Generator) -> np.ndarray:
        # white-noise force: Euler-Maruyama increment, so the statistics do not depend on dt
        front = g.frontier_vertices()
        a = a.copy()
        a[front] += sigma * np.sqrt(dt) * complex_normal(rng, len(front))
        return a


# ---------------------------------------------------------------------------- wave (V1.1 §2.1)
class WaveDynamics(_Probe):
    """da/dt = -i c^2 L a - (alpha I + beta L) a - Gamma_sink a + F(t); F acts on the frontier only.

    Rayleigh damping commutes with L, so mode k keeps its shape and decays at alpha + beta lambda_k.
    The optional sink Gamma_sink = gamma_s on vertices with depth <= d_max - D_sink does not commute
    with L; it is refused unless gamma_s <= 0.1 beta lambda_2. Modal integrator (exact) when the
    sink is off and the spectrum is dense, RK4 otherwise.
    """
    name = "wave"
    available = True

    def __init__(self) -> None:
        self.pending_probe = None

    def init_state(self, g: XonGraph, cfg, rng: np.random.Generator) -> State:
        return State(cfg.init_amp * complex_normal(rng, g.n()), 0.0, 0)

    def energy(self, g: XonGraph, s: State) -> float:
        return float(np.sum(np.abs(s.a) ** 2))

    @staticmethod
    def sink_profile(g: XonGraph, cfg) -> np.ndarray | None:
        if not cfg.sink:
            return None
        return np.where(g.depth <= g.max_depth() - int(cfg.sink_depth), float(cfg.sink_gamma), 0.0)

    @staticmethod
    def sink_bound(cfg, spec: Spectrum) -> float:
        """Largest allowed gamma_s on this graph: 0.1 * beta * lambda_2."""
        lam2 = float(spec.lam[1]) if spec.k_used > 1 else 0.0
        return SINK_BOUND_FACTOR * float(cfg.beta) * max(lam2, 0.0)

    def check(self, g: XonGraph, cfg, spec: Spectrum | None = None) -> str | None:
        """Why this configuration may not run on g, or None."""
        if not cfg.sink or cfg.sink_gamma <= 0:
            return None
        spec = spec if spec is not None and spec.key == g.content_key() else get_spectrum(g, cfg)
        bound = self.sink_bound(cfg, spec)
        if cfg.sink_gamma > bound * (1.0 + 1e-9):
            return (f"sink gamma_s = {cfg.sink_gamma:.4g} exceeds the bound 0.1 * beta * lambda_2 = "
                    f"0.1 * {cfg.beta:g} * {spec.lam[1]:.6g} = {bound:.4g} on this graph; lower gamma_s "
                    f"or turn the sink off")
        return None

    def uses_modal(self, g: XonGraph, cfg) -> bool:
        if cfg.sink:
            return False
        return cfg.integrator == "modal" or (cfg.integrator == "auto" and g.n() <= cfg.dense_max)

    def dt(self, g: XonGraph, cfg) -> float:
        rate = (cfg.c ** 2 + cfg.beta) * lambda_max_bound(g) + cfg.alpha + (cfg.sink_gamma if cfg.sink else 0.0)
        return capped_dt(cfg, rate)

    def tone(self, g: XonGraph, t: float, cfg, spec: Spectrum) -> np.ndarray:
        return tone_force(g, t, cfg, spec)

    def _modal_factor(self, spec: Spectrum, cfg, tau: float) -> np.ndarray:
        lam = spec.lam
        return np.exp(-(1j * cfg.c ** 2 * lam + cfg.alpha + cfg.beta * lam) * tau)

    def _rhs(self, g: XonGraph, cfg, spec: Spectrum | None):
        lap = g.laplacian()
        c2, al, be = cfg.c ** 2, cfg.alpha, cfg.beta
        sink = self.sink_profile(g, cfg)
        tone = (lambda t: self.tone(g, t, cfg, spec)) if cfg.drive == "tone" else None

        def rhs(a: np.ndarray, t: float) -> np.ndarray:
            la = real_matmul(lap, a)
            out = -1j * c2 * la - al * a - be * la
            if sink is not None:
                out = out - (sink if a.ndim == 1 else sink[:, None]) * a
            return out + tone(t) if tone is not None else out
        return rhs

    def _spec_for(self, g: XonGraph, cfg, spec: Spectrum | None, need: bool) -> Spectrum | None:
        if not need:
            return spec
        return spec if spec is not None and spec.key == g.content_key() else get_spectrum(g, cfg)

    def step(self, g: XonGraph, s: State, cfg, rng: np.random.Generator,
             spec: Spectrum | None = None) -> State:
        dt = self.dt(g, cfg)
        use_modal = self.uses_modal(g, cfg)
        spec = self._spec_for(g, cfg, spec, use_modal or cfg.drive == "tone" or cfg.sink)
        why = self.check(g, cfg, spec)
        if why:
            raise ValueError(why)
        if use_modal and spec.method != "dense":
            use_modal = False
        if use_modal:
            phi = spec.phi_dyn
            a = real_matmul(phi, self._modal_factor(spec, cfg, dt) * real_matmul(phi.T, s.a))
            if cfg.drive == "tone":
                a = a + dt * self.tone(g, s.t + 0.5 * dt, cfg, spec)
        else:
            a = _rk4(self._rhs(g, cfg, spec), s.a, s.t, dt)
        if cfg.drive == "noise" and cfg.drive_amp > 0:
            a = self._frontier_noise(g, a, cfg.drive_amp, dt, rng)
        a = self._apply_probe(g, a, cfg)
        return State(a, s.t + dt, s.step + 1)

    def propagate(self, g: XonGraph, A: np.ndarray, cfg, spec: Spectrum | None, n_steps: int) -> np.ndarray:
        """Undriven evolution of the columns of A (N, m) over n_steps steps of dt.

        Modal: exact, one propagator for the whole interval (identical to n_steps modal steps).
        Otherwise n_steps RK4 steps.
        """
        dt = self.dt(g, cfg)
        undriven = cfg.replace(drive="none")
        use_modal = self.uses_modal(g, cfg)
        spec = self._spec_for(g, cfg, spec, use_modal or cfg.sink)
        why = self.check(g, cfg, spec)
        if why:
            raise ValueError(why)
        if use_modal and spec.method == "dense":
            phi = spec.phi_dyn
            fac = self._modal_factor(spec, cfg, n_steps * dt)
            coef = real_matmul(phi.T, A)
            return real_matmul(phi, (fac[:, None] if A.ndim == 2 else fac) * coef)
        rhs = self._rhs(g, undriven, spec)
        for i in range(int(n_steps)):
            A = _rk4(rhs, A, i * dt, dt)
        return A


# ---------------------------------------------------------------------------- wave_v1 (V1 §3.3, kept for the _v1 experiments)
class WaveDynamicsV1:
    """da/dt = -i c^2 L a - Gamma a + F(t); drive F acts on the frontier vertices only (V1)."""
    name = "wave_v1"
    available = True

    def __init__(self) -> None:
        self.pending_probe: tuple[int, complex] | None = None

    def init_state(self, g: XonGraph, cfg, rng: np.random.Generator) -> State:
        return State(cfg.init_amp * complex_normal(rng, g.n()), 0.0, 0)

    def energy(self, g: XonGraph, s: State) -> float:
        return float(np.sum(np.abs(s.a) ** 2))

    def probe(self, g: XonGraph, s: State, vertex: int, amp: complex) -> State:
        """One-off injection at a single vertex (UI probe tool)."""
        a = s.a.copy()
        a[int(vertex)] += amp
        return State(a, s.t, s.step)

    def request_probe(self, vertex: int, amp: complex) -> None:
        """Queue a probe injection for the next step (drive="probe")."""
        self.pending_probe = (int(vertex), complex(amp))

    def uses_modal(self, g: XonGraph, cfg) -> bool:
        return cfg.integrator == "modal" or (cfg.integrator == "auto" and g.n() <= cfg.dense_max)

    def dt(self, g: XonGraph, cfg) -> float:
        return effective_dt(g, cfg)

    def tone(self, g: XonGraph, t: float, cfg, spec: Spectrum) -> np.ndarray:
        return tone_force(g, t, cfg, spec)

    def step(self, g: XonGraph, s: State, cfg, rng: np.random.Generator,
             spec: Spectrum | None = None) -> State:
        dt = effective_dt(g, cfg)
        gam = damping_profile(g, cfg)
        use_modal = self.uses_modal(g, cfg)
        if use_modal or cfg.drive == "tone":
            spec = spec if spec is not None and spec.key == g.content_key() else get_spectrum(g, cfg)
        if use_modal and spec.method != "dense":
            use_modal = False
        if use_modal:
            half = np.exp(-0.5 * gam * dt)
            phi = spec.phi_dyn
            rot = np.exp(-1j * cfg.c ** 2 * spec.lam * dt)
            a = half * s.a
            a = real_matmul(phi, rot * real_matmul(phi.T, a))
            a = half * a
            if cfg.drive == "tone":
                a = a + dt * self.tone(g, s.t + 0.5 * dt, cfg, spec)
        else:
            lap = g.laplacian()
            c2 = cfg.c ** 2
            tone = (lambda t: self.tone(g, t, cfg, spec)) if cfg.drive == "tone" else None

            def rhs(a: np.ndarray, t: float) -> np.ndarray:
                out = -1j * c2 * real_matmul(lap, a) - gam * a
                return out + tone(t) if tone is not None else out

            a = _rk4(rhs, s.a, s.t, dt)
        if cfg.drive == "noise" and cfg.drive_amp > 0:
            # white-noise force: Euler-Maruyama increment, so the statistics do not depend on dt
            front = g.frontier_vertices()
            a = a.copy()
            a[front] += cfg.drive_amp * np.sqrt(dt) * complex_normal(rng, len(front))
        if cfg.drive == "probe" and self.pending_probe is not None:
            v, amp = self.pending_probe
            self.pending_probe = None
            if 0 <= v < g.n():
                a = a.copy()
                a[v] += amp
        return State(a, s.t + dt, s.step + 1)


# ---------------------------------------------------------------------------- stuart_landau (V1.1 §2.2)
class StuartLandauDynamics(_Probe):
    """da_i/dt = (mu - |a_i|^2) a_i - i omega_i a_i - i c^2 (L a)_i - alpha a_i - beta (L a)_i + F_i(t).

    An isolated node relaxes to |a| = sqrt(mu) and rotates at omega_i; the network couples through L
    (reactive c^2, dissipative beta). ``coupling`` replaces L (the E4 complete-graph control) and
    ``omega`` fixes the natural frequencies (default: ``natural_frequencies``). RK4 with dt capped so
    that c^2 lambda_max dt < 0.5 and mu dt < 0.1; noise drive sl_sigma at the frontier.
    """
    name = "stuart_landau"
    available = True

    def __init__(self, coupling=None, omega: np.ndarray | None = None):
        self.coupling = coupling
        self.omega = omega
        self.pending_probe = None

    def laplacian(self, g: XonGraph):
        return self.coupling if self.coupling is not None else g.laplacian()

    def frequencies(self, g: XonGraph, cfg) -> np.ndarray:
        return self.omega if self.omega is not None else natural_frequencies(g, cfg)

    def init_state(self, g: XonGraph, cfg, rng: np.random.Generator) -> State:
        return State(cfg.init_amp * complex_normal(rng, g.n()), 0.0, 0)

    def energy(self, g: XonGraph, s: State) -> float:
        return float(np.sum(np.abs(s.a) ** 2))

    def uses_modal(self, g: XonGraph, cfg) -> bool:
        return False

    def dt(self, g: XonGraph, cfg) -> float:
        dt = capped_dt(cfg, cfg.c ** 2 * operator_bound(self.laplacian(g)))
        if cfg.dt_auto and cfg.sl_mu > 0 and cfg.sl_mu * dt > cfg.mu_dt_max:
            dt = cfg.mu_dt_max / cfg.sl_mu
        return dt

    def step(self, g: XonGraph, s: State, cfg, rng: np.random.Generator,
             spec: Spectrum | None = None) -> State:
        dt = self.dt(g, cfg)
        lap = self.laplacian(g)
        lin = 1j * self.frequencies(g, cfg) + cfg.sl_alpha
        mu, coup = float(cfg.sl_mu), 1j * cfg.c ** 2 + cfg.sl_beta

        def rhs(a: np.ndarray, t: float) -> np.ndarray:
            return (mu - (a.real ** 2 + a.imag ** 2)) * a - lin * a - coup * (lap @ a)

        a = _rk4(rhs, s.a, s.t, dt)
        if cfg.drive == "noise" and cfg.sl_sigma > 0:
            a = self._frontier_noise(g, a, cfg.sl_sigma, dt, rng)
        a = self._apply_probe(g, a, cfg)
        return State(a, s.t + dt, s.step + 1)


# ---------------------------------------------------------------------------- oscillator (V1.1 §2.3)
class OscillatorDynamics(_Probe):
    """Kuramoto oscillators / oscillator Ising machine (§6.2, V1.1 §2.3). State a = exp(i theta).

    d theta_i/dt = omega_i - K sum_j J_ij sin(theta_i - theta_j) - K_s sin(2 theta_i) + sigma xi_i
    energy       = -sum_{ij} J_ij cos(theta_i - theta_j)          (a dissonance energy)

    J is the graph adjacency unless given (a ConstraintProblem's Ising couplings, or the E4
    complete-graph control). The noise acts on the frontier when drive = "noise", else on every vertex.
    """
    name = "oscillator"
    available = True

    def __init__(self, J: sp.spmatrix | np.ndarray | CompleteCoupling | None = None,
                 omega: np.ndarray | None = None):
        self.J = J
        self.omega = omega
        self.pending_probe = None

    def coupling(self, g: XonGraph):
        return self.J if self.J is not None else g.adjacency()

    def frequencies(self, g: XonGraph, cfg) -> np.ndarray:
        return self.omega if self.omega is not None else natural_frequencies(g, cfg)

    def init_state(self, g: XonGraph, cfg, rng: np.random.Generator) -> State:
        return State(np.exp(1j * rng.uniform(0.0, 2 * np.pi, g.n())), 0.0, 0)

    def uses_modal(self, g: XonGraph, cfg) -> bool:
        return False

    def dt(self, g: XonGraph, cfg) -> float:
        rate = 2.0 * abs(cfg.osc_K) * operator_bound(self.coupling(g)) + 2.0 * abs(cfg.osc_Ks)
        return capped_dt(cfg, rate) if rate > 0 else float(cfg.dt)

    def step(self, g: XonGraph, s: State, cfg, rng: np.random.Generator,
             spec: Spectrum | None = None) -> State:
        dt = self.dt(g, cfg)
        J = self.coupling(g)
        om = self.frequencies(g, cfg)
        K, Ks = float(cfg.osc_K), float(cfg.osc_Ks)

        def rhs(th: np.ndarray, t: float) -> np.ndarray:
            z = np.exp(1j * th)
            # sum_j J_ij sin(theta_i - theta_j) = Im(z_i conj((J z)_i)) for real J
            return om - K * np.imag(z * np.conj(J @ z)) - Ks * np.sin(2.0 * th)

        th = _rk4(rhs, np.angle(s.a), s.t, dt)
        if cfg.osc_sigma > 0:
            nodes = g.frontier_vertices() if cfg.drive == "noise" else np.arange(g.n())
            th[nodes] += cfg.osc_sigma * np.sqrt(dt) * rng.standard_normal(len(nodes))
        a = self._apply_probe(g, np.exp(1j * th), cfg)
        return State(a, s.t + dt, s.step + 1)

    def energy(self, g: XonGraph, s: State) -> float:
        a = s.a / np.where(np.abs(s.a) > 0, np.abs(s.a), 1.0)
        return float(-np.real(np.vdot(a, self.coupling(g) @ a)))


DYNAMICS: dict[str, type] = {
    "wave": WaveDynamics,
    "wave_v1": WaveDynamicsV1,
    "stuart_landau": StuartLandauDynamics,
    "oscillator": OscillatorDynamics,
}


def get_dynamics(name: str):
    try:
        return DYNAMICS[name]()
    except KeyError as exc:
        raise ValueError(f"unknown dynamics {name!r}; choose from {sorted(DYNAMICS)}") from exc
