"""Consistency analysis of the signed claim graph (XON_A1_CONSISTENCY.md §4), with the A1 re-specifications made
before any results (CHANGELOG_EXPERIMENTS.md).

Facts relied on:
- A signed graph is balanced (every cycle has an even number of negative edges) iff the energy
  E(x) = sum w_ij (x_i - s_ij x_j)^2 reaches 0 with x != 0 (Harary 1953).
- The smallest eigenvalue of the signed Laplacian L_s = D - S is 0 iff the graph is balanced, and otherwise positive:
  it measures algebraic conflict (Kunegis et al. 2010). This holds for a connected graph. L_s of a disconnected graph
  is block diagonal, so conflict here is the sum over connected components of each component's smallest eigenvalue.
- With values clamped on some vertices and a term mu (x_i - 1)^2 on each asserted claim, the energy is a
  positive-definite quadratic in the free vertices of every component that holds a clamp or an asserted claim. Its
  minimizer is the unique solution of (L_ff + mu A_f) x_f = mu a_f - L_fc x_c (a_i = 1 on asserted claims,
  A = diag(a)). Each free x_i is then a weighted average of s_ij x_j and, on asserted claims, of +1, so |x_i| <= 1
  when the clamps are +-1 (harmonic extension, maximum principle).
- Balance asks whether some truth assignment works: a single contradicts edge is balanced (make one claim false).
  A document asserts its claims, which is why the verdict has a direct clause and harmony the assertion term.

Rev. 2.2 (XON_A1_REV2_2_PRECISION.md §3.3, §6): "tension" relations make no edge, so they touch nothing here and are
only listed (``tension_pairs``); the verdict's confidence threshold is a parameter, one value for every clause.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field

import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components

from .claims import SignedClaimGraph
from .entity_consistency import (ASSERTING_KINDS, CONFIDENCE_MIN, EntityContradiction, EntityGraph,
                                 eligible_relations, find_contradictions)

CULPRIT_K = 3                   # §4.3 step 4: culprits for the top-k claims by residual; L1 localizes with the top 3
DEGENERACY_RTOL = 1e-8          # a component's lambda_min is repeated when other eigenvalues lie within this of it,
                                # relative to the component's largest eigenvalue
RESIDUAL_RTOL = 1e-12           # claim residuals at most this times the total weight (edge weights plus mu per
                                # asserted claim with a relation) count as zero: not ranked (a consistent component
                                # leaves residuals of floating-point size)
SIGN_TIE_TOL = 1e-12            # x* is unit-norm; magnitudes closer than this are ties
ASSERTION_MU = 1.0              # mu of the assertion term mu (x_i - 1)^2 on every asserted claim; fixed
NO_ANCHORS = "no premises, evidence or asserted claims"
NO_RELATIONS = "no relations reach the premises, evidence or asserted claims"
CLAUSES = ("direct", "claim_balance", "entity")


# ------------------------------------------------------------------------------------------ structure
def signed_laplacian(n: int, edges: np.ndarray, sign: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """Dense L_s = D - S with S_ij = s_ij w_ij: the Laplacian of the claim graph's sheaf."""
    lap = np.zeros((n, n))
    for (u, v), s, w in zip(np.asarray(edges).reshape(-1, 2).tolist(), sign, weight):
        lap[u, u] += w
        lap[v, v] += w
        lap[u, v] -= s * w
        lap[v, u] -= s * w
    return lap


def components(n: int, edges: np.ndarray) -> list[list[int]]:
    """Connected components, each sorted, ordered by their smallest vertex."""
    if n == 0:
        return []
    e = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
    adj = sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    k, labels = connected_components(adj, directed=False)
    return sorted((np.flatnonzero(labels == c).tolist() for c in range(k)), key=lambda c: c[0])


def _signed_neighbors(n: int, edges: np.ndarray, sign: np.ndarray) -> list[list[tuple[int, int]]]:
    """Per vertex, sorted (neighbour, parity) with parity 1 for a negative edge."""
    adj = [[] for _ in range(n)]
    for (u, v), s in zip(np.asarray(edges).reshape(-1, 2).tolist(), sign):
        p = 0 if s > 0 else 1
        adj[u].append((v, p))
        adj[v].append((u, p))
    return [sorted(a) for a in adj]


def balanced_components(n: int, edges: np.ndarray, sign: np.ndarray) -> np.ndarray:
    """Per vertex, whether its component is balanced (BFS 2-colouring on the sign structure)."""
    adj = _signed_neighbors(n, edges, sign)
    side = np.full(n, -1)
    ok = np.ones(n, dtype=bool)
    for s0 in range(n):
        if side[s0] >= 0:
            continue
        side[s0] = 0
        members, queue, good = [s0], deque([s0]), True
        while queue:
            u = queue.popleft()
            for v, p in adj[u]:
                want = side[u] ^ p
                if side[v] < 0:
                    side[v] = want
                    members.append(v)
                    queue.append(v)
                elif side[v] != want:
                    good = False
        ok[members] = good
    return ok


def is_balanced(n: int, edges: np.ndarray, sign: np.ndarray) -> bool:
    return bool(balanced_components(n, edges, sign).all())


def shortest_frustrated_cycle(n: int, edges: np.ndarray, sign: np.ndarray) -> list[int] | None:
    """Shortest cycle with an odd number of negative edges (claim ids, from the smallest), or None if balanced.

    A closed walk through v with an odd number of negative edges is a path from (v, 0) to (v, 1) in the signed double
    cover, found by BFS with parity distances. The shortest such walk over all v is a simple cycle: a repeated vertex
    would split it into two shorter closed walks, one of them odd."""
    adj = _signed_neighbors(n, edges, sign)
    best = None
    for start in range(n):
        if not adj[start]:
            continue
        prev = {(start, 0): None}
        depth = {(start, 0): 0}
        queue = deque([(start, 0)])
        goal = (start, 1)
        while queue and goal not in prev:
            node = queue.popleft()
            if best is not None and depth[node] + 1 >= len(best):
                break
            v, parity = node
            for w, p in adj[v]:
                nxt = (w, parity ^ p)
                if nxt not in prev:
                    prev[nxt] = node
                    depth[nxt] = depth[node] + 1
                    queue.append(nxt)
        if goal in prev:
            walk, node = [], goal
            while node is not None:
                walk.append(node[0])
                node = prev[node]
            cycle = walk[:-1]
            if best is None or len(cycle) < len(best):
                best = cycle
    if best is None:
        return None
    k = best.index(min(best))
    best = best[k:] + best[:k]
    if len(best) > 2 and best[1] > best[-1]:
        best = [best[0]] + best[1:][::-1]
    return [int(v) for v in best]


# ------------------------------------------------------------------------------------------ one analysis
@dataclass
class _Component:
    vertices: list[int]
    lam: float                  # lambda_min of the component's signed Laplacian (0 on a single claim)
    basis: np.ndarray           # (|C|, m) orthonormal basis of the lambda_min eigenspace
    x: np.ndarray               # the first basis vector, with the sign rule: x* when the component is unanchored
    degenerate: bool            # multiplicity m > 1
    anchored: bool              # holds a clamped or an asserted claim


@dataclass
class _Solution:
    comps: list[_Component]
    conflict: float
    x: np.ndarray
    edge_res: np.ndarray
    claim_res: np.ndarray
    harmony: float | None
    harmony_reason: str | None


def eigenspace_residuals(basis: np.ndarray, edges: np.ndarray, sign: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """Edge residuals w (1/m) sum_k (u_k,i - s u_k,j)^2 over an orthonormal basis u_1..u_m of a component's
    lambda_min eigenspace (``edges`` indexes the basis rows). The value depends only on the eigenspace, equals
    w (x_i - s x_j)^2 for the unit eigenvector x when m = 1, and sums to lambda_min over the component."""
    edges = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
    d = basis[edges[:, 0]] - np.asarray(sign)[:, None] * basis[edges[:, 1]]
    return np.asarray(weight) * np.sum(d * d, axis=1) / basis.shape[1]


def _oriented(x: np.ndarray) -> np.ndarray:
    """Sign of x* on an unanchored component, which holds no asserted or premise claim (so the rule's first part,
    a sum >= 0 over those claims, always ties): the largest-magnitude entry, the first one on a tie, is positive."""
    mag = np.abs(x)
    i = int(np.flatnonzero(mag >= mag.max() - SIGN_TIE_TOL)[0])
    return -x if x[i] < 0 else x


def _component(lap: np.ndarray, vertices: list[int], balanced: bool, anchored: bool) -> _Component:
    if len(vertices) == 1:
        return _Component(vertices, 0.0, np.ones((1, 1)), np.ones(1), False, anchored)
    w, u = np.linalg.eigh(lap[np.ix_(vertices, vertices)])
    m = int(np.count_nonzero(w - w[0] <= DEGENERACY_RTOL * max(float(w[-1]), np.finfo(float).tiny)))
    lam = 0.0 if balanced else max(float(w[0]), 0.0)   # exact zero on a balanced component (Harary; Kunegis)
    return _Component(vertices, lam, u[:, :m], _oriented(u[:, 0]), m > 1, anchored)


def related_assertions(kinds: list[str], edges: np.ndarray) -> int:
    """n_asserted of the harmony bound: asserted claims with at least one relation edge. An asserted claim without
    one settles at +1 at no cost, so counting it would raise H for free."""
    related = set(np.asarray(edges).ravel().tolist())
    return sum(1 for i, k in enumerate(kinds) if k == "asserted" and i in related)


def _solve(n: int, edges: np.ndarray, sign: np.ndarray, weight: np.ndarray, kinds: list[str],
           clamps: set[int], mu: float) -> _Solution:
    edges = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
    lap = signed_laplacian(n, edges, sign, weight)
    bal = balanced_components(n, edges, sign)
    asserted = np.array([k == "asserted" for k in kinds], dtype=bool)
    x = np.zeros(n)
    edge_res = np.zeros(len(edges))
    claim_res = np.zeros(n)
    comps, energy, wsum = [], 0.0, 0.0
    comp_of = np.zeros(n, dtype=np.int64)
    parts = components(n, edges)
    for ci, verts in enumerate(parts):
        comp_of[verts] = ci
    edge_comp = comp_of[edges[:, 0]] if len(edges) else np.zeros(0, dtype=np.int64)
    for ci, verts in enumerate(parts):
        anchored = bool(clamps.intersection(verts)) or bool(asserted[verts].any())
        c = _component(lap, verts, bool(bal[verts[0]]), anchored)
        comps.append(c)
        local = {v: k for k, v in enumerate(verts)}
        mine = np.flatnonzero(edge_comp == ci)
        if anchored:
            # premises and evidence clamped to +1, asserted claims pulled toward +1 by mu (x_i - 1)^2, the free
            # claims solved exactly (§4.3 step 2b with the assertion term)
            xc = np.ones(len(verts))
            free = [k for k, v in enumerate(verts) if v not in clamps]
            fixed = [k for k, v in enumerate(verts) if v in clamps]
            if free:
                sub = lap[np.ix_(verts, verts)]
                pull = mu * asserted[[verts[k] for k in free]]
                xc[free] = np.linalg.solve(sub[np.ix_(free, free)] + np.diag(pull),
                                           pull - sub[np.ix_(free, fixed)] @ np.ones(len(fixed)))
            x[verts] = xc
            for e in mine:
                a, b = local[edges[e, 0]], local[edges[e, 1]]
                edge_res[e] = weight[e] * (xc[a] - sign[e] * xc[b]) ** 2
                wsum += weight[e]
            claim_res[verts] = mu * asserted[verts] * (xc - 1.0) ** 2
            energy += float(edge_res[mine].sum() + claim_res[verts].sum())
        else:
            x[verts] = c.x
            ends = np.array([[local[a], local[b]] for a, b in edges[mine].tolist()], dtype=np.int64).reshape(-1, 2)
            edge_res[mine] = eigenspace_residuals(c.basis, ends, sign[mine], weight[mine])
    if len(edges):
        np.add.at(claim_res, edges[:, 0], edge_res)
        np.add.at(claim_res, edges[:, 1], edge_res)
    if not any(c.anchored for c in comps):
        harmony, reason = None, NO_ANCHORS
    elif wsum <= 0.0:
        harmony, reason = None, NO_RELATIONS
    else:
        harmony, reason = 1.0 - energy / (4.0 * wsum + 4.0 * mu * related_assertions(kinds, edges)), None
    return _Solution(comps, float(sum(c.lam for c in comps)), x, edge_res, claim_res, harmony, reason)


def _without(n: int, edges: np.ndarray, sign: np.ndarray, weight: np.ndarray, kinds: list[str], clamps: set[int],
             mu: float, drop: int) -> _Solution:
    """The same analysis with one claim removed (its relations and any clamp on it go too)."""
    keep = [v for v in range(n) if v != drop]
    new = {v: i for i, v in enumerate(keep)}
    mask = (edges[:, 0] != drop) & (edges[:, 1] != drop)
    sub = np.array([[new[int(u)], new[int(v)]] for u, v in edges[mask]], dtype=np.int64).reshape(-1, 2)
    return _solve(n - 1, sub, sign[mask], weight[mask], [kinds[v] for v in keep],
                  {new[c] for c in clamps if c != drop}, mu)


# ------------------------------------------------------------------------------------------ report
@dataclass
class ConsistencyReport:
    n_claims: int
    n_edges: int
    verdict_inconsistent: bool
    verdict_clauses: list[str]                      # subset of CLAUSES, in that order
    balanced: bool                                  # the full claim graph
    conflict: float                                 # sum of each component's lambda_min, evidence-free
    clamp_set: list[int]                            # premises + user-marked evidence (I1)
    harmony: float | None                           # H over the anchored components, if relations reach them
    harmony_reason: str | None                      # why harmony is None
    unanchored_components: list[list[int]]          # components with no clamped and no asserted claim
    component_conflict: dict[int, float]            # component index (into components) -> lambda_min
    frustrated_cycle: list[int] | None              # the full claim graph's shortest, claim ids
    entity_contradictions: list[EntityContradiction]  # on all entity relations
    truth_assignment: np.ndarray                    # the exact minimizer on anchored components, else the
                                                    # component's lowest eigenvector
    claim_residuals: np.ndarray
    edge_residuals: dict[tuple[int, int], float]
    residual_ranking: list[int]                     # claims with a nonzero residual, largest first (ties by id)
    culprits: list[tuple[int, float, float | None]]   # counterfactual: (claim, conflict drop, harmony change)
    llm_usage: dict
    components: list[list[int]] = field(default_factory=list)
    component_degenerate: dict[int, bool] = field(default_factory=dict)
    degenerate: bool = False                        # some component's lambda_min is repeated
    direct_contradictions: list[tuple[int, int]] = field(default_factory=list)   # clause (a)
    confident_frustrated_cycle: list[int] | None = None                         # clause (b)
    verdict_entity_contradictions: list[EntityContradiction] = field(default_factory=list)   # clause (c)
    engine_version: str = "2.1"
    threshold: float = CONFIDENCE_MIN               # the verdict's confidence threshold, every clause
    tension_pairs: list[dict] = field(default_factory=list)   # rev. 2.2: a, b, rationale, confidence; no edge


def analyze(sg: SignedClaimGraph, entities: EntityGraph | None = None, evidence=(),
            llm_usage: dict | None = None, *, threshold: float = CONFIDENCE_MIN,
            engine_version: str = "2.1") -> ConsistencyReport:
    """The consistency report of a signed claim graph (and its entity-relation graph), with premises and the
    user-marked ``evidence`` clamped to +1 and asserted claims carrying the assertion term. Every headline number is
    computed on the full graphs as scored (I2). ``threshold`` is the confidence a relation needs to enter the
    verdict, in each of its clauses."""
    n, kinds, mu = sg.n, sg.kinds, ASSERTION_MU
    evidence = sorted({int(v) for v in evidence})
    if any(not 0 <= v < n for v in evidence):
        raise ValueError(f"evidence {evidence} names claims outside 0..{n - 1}")
    clamp_set = sorted(set(sg.premises) | set(evidence))
    clamps = set(clamp_set)
    edges, sign, weight = np.asarray(sg.edges).reshape(-1, 2), sg.sign, sg.weight
    sol = _solve(n, edges, sign, weight, kinds, clamps, mu)
    balanced = is_balanced(n, edges, sign)

    # residual ranking: residuals equal to 9 significant digits tie and go by claim id; culprits are the top-k claims,
    # each removed in turn (a counterfactual; never a headline number)
    scale = max(float(sol.claim_res.max()) if n else 0.0, np.finfo(float).tiny)
    zero = RESIDUAL_RTOL * (float(weight.sum()) + mu * related_assertions(kinds, edges))
    ranking = sorted((v for v in range(n) if sol.claim_res[v] > zero),
                     key=lambda v: (-round(float(sol.claim_res[v]) / scale, 9), v))
    culprits = []
    for v in ranking[:CULPRIT_K]:
        after = _without(n, edges, sign, weight, kinds, clamps, mu, v)
        gain = None if sol.harmony is None or after.harmony is None else after.harmony - sol.harmony
        culprits.append((int(v), sol.conflict - after.conflict, gain))

    # verdict (§4.6)
    threshold = float(threshold)
    strong = weight >= threshold
    direct = [(int(a), int(b)) for (a, b), s, ok in zip(edges.tolist(), sign, strong)
              if ok and s < 0 and kinds[a] in ASSERTING_KINDS and kinds[b] in ASSERTING_KINDS]
    confident_cycle = (None if is_balanced(n, edges[strong], sign[strong])
                       else shortest_frustrated_cycle(n, edges[strong], sign[strong]))
    ent_all = find_contradictions(entities) if entities is not None else []
    ent_verdict = (find_contradictions(entities, eligible_relations(entities, kinds, threshold, ASSERTING_KINDS))
                   if entities is not None else [])
    fired = dict(zip(CLAUSES, (bool(direct), confident_cycle is not None, bool(ent_verdict))))
    clauses = [c for c in CLAUSES if fired[c]]

    return ConsistencyReport(
        n_claims=n, n_edges=len(edges), verdict_inconsistent=bool(clauses), verdict_clauses=clauses,
        balanced=balanced, conflict=sol.conflict, clamp_set=clamp_set, harmony=sol.harmony,
        harmony_reason=sol.harmony_reason,
        unanchored_components=[c.vertices for c in sol.comps if not c.anchored],
        component_conflict={i: c.lam for i, c in enumerate(sol.comps)},
        frustrated_cycle=None if balanced else shortest_frustrated_cycle(n, edges, sign),
        entity_contradictions=ent_all, truth_assignment=sol.x, claim_residuals=sol.claim_res,
        edge_residuals={(int(a), int(b)): float(r) for (a, b), r in zip(edges.tolist(), sol.edge_res)},
        residual_ranking=[int(v) for v in ranking], culprits=culprits, llm_usage=dict(llm_usage or {}),
        components=[c.vertices for c in sol.comps],
        component_degenerate={i: c.degenerate for i, c in enumerate(sol.comps)},
        degenerate=any(c.degenerate for c in sol.comps), direct_contradictions=direct,
        confident_frustrated_cycle=confident_cycle, verdict_entity_contradictions=ent_verdict,
        engine_version=engine_version, threshold=threshold,
        tension_pairs=[{"a": int(r.a), "b": int(r.b), "rationale": r.rationale, "confidence": float(r.confidence)}
                       for r in getattr(sg, "tension", [])])


def report_to_dict(report: ConsistencyReport) -> dict:
    """JSON-ready form of a report."""
    d = asdict(report)
    d["truth_assignment"] = [float(v) for v in report.truth_assignment]
    d["claim_residuals"] = [float(v) for v in report.claim_residuals]
    d["edge_residuals"] = [{"a": a, "b": b, "residual": r} for (a, b), r in report.edge_residuals.items()]
    d["component_conflict"] = {str(k): v for k, v in report.component_conflict.items()}
    d["component_degenerate"] = {str(k): v for k, v in report.component_degenerate.items()}
    d["culprits"] = [{"claim": c, "conflict_drop": dc, "harmony_change": dh} for c, dc, dh in report.culprits]
    d["direct_contradictions"] = [list(p) for p in report.direct_contradictions]
    return d
