"""ConstraintProblem interface, MaxCutProblem (§6.3) and the oscillator Ising machine solver (V1.1 §2.3).

The problem graph, Ising couplings, sheaf encoding, exact optimum and scoring are all here;
``oscillator_solve`` runs ``OscillatorDynamics`` on a problem (E6 and the Constraints tab).
"""
from __future__ import annotations

from typing import Protocol

import networkx as nx
import numpy as np
import scipy.sparse as sp
from networkx.algorithms.approximation import treewidth_min_fill_in

from .dynamics import OscillatorDynamics, State
from .graph import XonGraph, canonical_edges
from .sheaf import CellularSheaf


class ConstraintProblem(Protocol):
    name: str

    def graph(self) -> XonGraph: ...

    def to_ising(self) -> sp.csr_matrix: ...

    def to_sheaf(self) -> CellularSheaf: ...

    def score(self, state: State) -> dict: ...


# ---------------------------------------------------------------------------- exact max-cut
def max_cut_brute_force(n: int, edges: np.ndarray) -> int:
    """Exhaustive search (vertex n-1 fixed to side 0 by symmetry); fine for n <= ~22."""
    edges = np.asarray(edges, dtype=np.int64)
    if n < 2 or len(edges) == 0:
        return 0
    u, v = edges[:, 0], edges[:, 1]
    total = 1 << (n - 1)
    shifts = np.arange(n - 1, dtype=np.int64)
    best = 0
    for start in range(0, total, 1 << 15):
        idx = np.arange(start, min(start + (1 << 15), total), dtype=np.int64)
        bits = np.zeros((len(idx), n), dtype=np.int8)
        bits[:, : n - 1] = (idx[:, None] >> shifts) & 1
        best = max(best, int((bits[:, u] != bits[:, v]).sum(axis=1).max()))
    return best


def _bits(m: int) -> np.ndarray:
    idx = np.arange(1 << m, dtype=np.int64)
    return (idx[:, None] >> np.arange(m, dtype=np.int64)) & 1


def _max_cut_connected(G: nx.Graph) -> int:
    if G.number_of_edges() == 0:
        return 0
    _, tree = treewidth_min_fill_in(G)
    root = next(iter(tree.nodes))
    order = list(nx.dfs_preorder_nodes(tree, root))
    parent = nx.dfs_predecessors(tree, root)
    children: dict = {b: [] for b in order}
    for b, p in parent.items():
        children[p].append(b)
    assigned: dict = {b: [] for b in order}
    for u, v in G.edges():
        for b in order:
            if u in b and v in b:
                assigned[b].append((u, v))
                break
    tables: dict = {}
    for b in reversed(order):
        verts = sorted(b)
        pos = {x: i for i, x in enumerate(verts)}
        bits = _bits(len(verts))
        val = np.zeros(len(bits))
        for u, v in assigned[b]:
            val += bits[:, pos[u]] != bits[:, pos[v]]
        for c in children[b]:
            cverts, ctable = tables.pop(c)
            cpos = {x: i for i, x in enumerate(cverts)}
            cbits = _bits(len(cverts))
            inter = sorted(set(verts) & set(cverts))
            key_c = np.zeros(len(cbits), dtype=np.int64)
            key_b = np.zeros(len(bits), dtype=np.int64)
            for j, x in enumerate(inter):
                key_c |= cbits[:, cpos[x]] << j
                key_b |= bits[:, pos[x]] << j
            best = np.full(1 << len(inter), -np.inf)
            np.maximum.at(best, key_c, ctable)
            val += best[key_b]
        tables[b] = (verts, val)
    return int(round(tables[root][1].max()))


def max_cut_exact(n: int, edges: np.ndarray) -> int:
    """Exact maximum cut by dynamic programming over a tree decomposition (min-fill-in heuristic).

    Exponential only in the treewidth, so a 40-node 3-regular graph (treewidth ~ 6-8) is instant.
    """
    G = nx.Graph()
    G.add_nodes_from(range(n))
    G.add_edges_from((int(u), int(v)) for u, v in edges)
    return sum(_max_cut_connected(G.subgraph(c).copy()) for c in nx.connected_components(G))


# ---------------------------------------------------------------------------- MaxCutProblem
class MaxCutProblem:
    """Max-cut on a graph; spins are read from phases (Re a >= 0 -> +1, else -1)."""
    name = "maxcut"

    def __init__(self, n: int, edges: np.ndarray, seed: int = 0):
        self.n = int(n)
        self.edges = canonical_edges(edges)
        self.seed = int(seed)
        self._optimum: int | None = None
        self._graph: XonGraph | None = None

    @classmethod
    def random_regular(cls, n: int = 40, degree: int = 3, seed: int = 0) -> "MaxCutProblem":
        G = nx.random_regular_graph(degree, n, seed=seed)
        return cls(n, np.array(list(G.edges()), dtype=np.int64).reshape(-1, 2), seed)

    def graph(self) -> XonGraph:
        if self._graph is None:
            G = nx.Graph()
            G.add_nodes_from(range(self.n))
            G.add_edges_from(map(tuple, self.edges))
            pos = nx.spring_layout(G, seed=self.seed)
            self._graph = XonGraph(
                coords=np.array([pos[i] for i in range(self.n)], dtype=float),
                simplices=self.edges.copy(),
                edges=self.edges.copy(),
                depth=np.zeros(self.n, dtype=np.int64),
                parent=np.full(self.n, -1, dtype=np.int64),
                rule="maxcut",
            )
        return self._graph

    def to_ising(self) -> sp.csr_matrix:
        """J = -A (antiferromagnetic): minimizing -sum_ij J_ij s_i s_j maximizes the cut."""
        return (-self.graph().adjacency()).tocsr()

    def to_sheaf(self) -> CellularSheaf:
        """k = 1 sign-flip sheaf: (delta x)_e = x_u + x_v, so for spins x in {+-1} the Dirichlet
        energy is 4 x (number of uncut edges); global sections exist iff the graph is bipartite."""
        e = len(self.edges)
        return CellularSheaf(1, np.ones((e, 1, 1)), -np.ones((e, 1, 1)), self.edges.copy())

    def spins(self, state: State) -> np.ndarray:
        return np.where(np.real(state.a) >= 0, 1, -1)

    def cut_value(self, spins: np.ndarray) -> int:
        s = np.asarray(spins)
        return int(np.sum(s[self.edges[:, 0]] != s[self.edges[:, 1]]))

    def optimum(self) -> int:
        if self._optimum is None:
            self._optimum = max_cut_exact(self.n, self.edges)
        return self._optimum

    def score(self, state: State) -> dict:
        cut = self.cut_value(self.spins(state))
        opt = self.optimum()
        return {"cut": cut, "optimum": opt, "ratio": cut / opt if opt else float("nan")}


PROBLEMS: dict[str, type] = {"maxcut": MaxCutProblem}


def oscillator_solve(problem: ConstraintProblem, cfg, rng: np.random.Generator,
                     steps: int | None = None) -> tuple[State, np.ndarray]:
    """Oscillator Ising machine: Kuramoto on J = problem.to_ising() in the frame of the sub-harmonic
    injection (omega = 0), K = cfg.osc_K, K_s ramped linearly from 0 to cfg.osc_Ks_max over
    cfg.osc_anneal_steps, phase noise cfg.osc_noise on every vertex.

    Returns the final state and the energy -sum_ij J_ij cos(theta_i - theta_j) after each step.
    """
    steps = int(cfg.e6_steps if steps is None else steps)
    g = problem.graph()
    dyn = OscillatorDynamics(J=problem.to_ising(), omega=np.zeros(g.n()))
    s = dyn.init_state(g, cfg, rng)
    run = cfg.replace(drive="none", osc_sigma=cfg.osc_noise)
    ramp = max(int(cfg.osc_anneal_steps), 1)
    energy = np.empty(steps)
    for t in range(steps):
        s = dyn.step(g, s, run.replace(osc_Ks=cfg.osc_Ks_max * min(1.0, t / ramp)), rng)
        energy[t] = dyn.energy(g, s)
    return s, energy
