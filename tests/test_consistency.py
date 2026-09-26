"""A1 consistency engine on hand-built signed claim graphs (XON_A1_CONSISTENCY.md §4, rev. 2.1 and the A1
re-specifications in CHANGELOG_EXPERIMENTS.md). Offline."""
import json
import math

import networkx as nx
import numpy as np
import pytest
from pydantic import ValidationError

from xon.llm import consistency
from xon.llm.baselines import pairwise_only
from xon.llm.claims import build_signed_graph
from xon.llm.consistency import (ASSERTION_MU, CULPRIT_K, NO_ANCHORS, NO_RELATIONS, analyze, eigenspace_residuals,
                                 is_balanced, report_to_dict, shortest_frustrated_cycle, signed_laplacian)
from xon.llm.schemas import Claim, Relation

REL = {"+": "supports", "-": "contradicts", "0": "unrelated"}


def claims(kinds):
    return [Claim(id=i, text=f"claim {i}", span=f"claim {i}", kind=k) for i, k in enumerate(kinds)]


def rel(a, b, s, c=1.0):
    return Relation(a=a, b=b, relation=REL[s], confidence=c, rationale="test")


def graph(kinds, rels):
    kinds = ["asserted"] * kinds if isinstance(kinds, int) else kinds
    return build_signed_graph(claims(kinds), [rel(*r) for r in rels])


def random_graph(rng, n, p=0.5, kinds=None, positive=0.6):
    rels = [(i, j, "+" if rng.random() < positive else "-", float(rng.uniform(0.05, 1.0)))
            for i in range(n) for j in range(i + 1, n) if rng.random() < p]
    return graph(kinds or n, rels)


def energy(sg, x):
    e = sg.edges
    return float(np.sum(sg.weight * (x[e[:, 0]] - sg.sign * x[e[:, 1]]) ** 2)) if len(e) else 0.0


def full_energy(sg, x):
    """The edge energy plus the assertion term mu (x_i - 1)^2 on every asserted claim."""
    asserted = np.array([k == "asserted" for k in sg.kinds])
    return energy(sg, x) + ASSERTION_MU * float(np.sum((x[asserted] - 1.0) ** 2))


QUOTED = ["quoted"] * 8                                                      # claims that anchor nothing
TRIANGLE = [(0, 1, "+"), (1, 2, "+"), (0, 2, "-")]                          # frustrated, lambda_min = 1 twice
TWO_TRIANGLES = TRIANGLE + [(3, 4, "+"), (4, 5, "+"), (3, 5, "-"), (2, 3, "+", 0.3)]   # lambda_min = 1, m = 3


# ------------------------------------------------------------------------------------------ structure
def test_the_claim_sheaf_is_the_signed_laplacian():
    rng = np.random.default_rng(0)
    for _ in range(20):
        sg = random_graph(rng, int(rng.integers(2, 9)))
        lap = signed_laplacian(sg.n, sg.edges, sg.sign, sg.weight)
        assert np.allclose(sg.sheaf.laplacian(sg.graph).toarray(), lap)
        x = rng.normal(size=sg.n)
        assert x @ lap @ x == pytest.approx(energy(sg, x)) == pytest.approx(sg.sheaf.dirichlet_energy(sg.graph, x))


def test_balanced_graph_has_zero_conflict_and_no_cycle():
    rels = [(0, 1, "+"), (1, 2, "-"), (2, 3, "+"), (0, 3, "-")]              # two negatives on the square
    for kinds in (4, QUOTED[:4]):
        sg = graph(kinds, rels)
        rep = analyze(sg)
        assert rep.balanced and rep.conflict == 0.0 and rep.frustrated_cycle is None
        assert rep.component_conflict == {0: 0.0}
    assert energy(sg, rep.truth_assignment) == pytest.approx(0.0, abs=1e-12)   # the unanchored eigenvector


def test_frustrated_triangle():
    rep = analyze(graph(3, TRIANGLE))
    assert not rep.balanced and rep.conflict == pytest.approx(1.0)
    assert rep.frustrated_cycle == [0, 1, 2]
    assert rep.verdict_inconsistent and rep.verdict_clauses == ["direct", "claim_balance"]
    assert rep.confident_frustrated_cycle == [0, 1, 2] and rep.direct_contradictions == [(0, 2)]


def test_shortest_frustrated_cycle_matches_brute_force():
    rng = np.random.default_rng(1)
    checked = 0
    for _ in range(250):
        sg = random_graph(rng, int(rng.integers(3, 9)), p=float(rng.uniform(0.25, 0.7)))
        g = nx.Graph()
        g.add_nodes_from(range(sg.n))
        for (a, b), s in zip(sg.edges.tolist(), sg.sign):
            g.add_edge(a, b, s=s)
        odd = [len(c) for c in nx.simple_cycles(g)
               if np.prod([g.edges[c[k], c[(k + 1) % len(c)]]["s"] for k in range(len(c))]) < 0]
        cyc = shortest_frustrated_cycle(sg.n, sg.edges, sg.sign)
        assert is_balanced(sg.n, sg.edges, sg.sign) == (not odd)
        if not odd:
            assert cyc is None
            continue
        checked += 1
        assert len(cyc) == min(odd) and len(set(cyc)) == len(cyc) and cyc[0] == min(cyc)
        assert len(cyc) < 3 or cyc[1] < cyc[-1]
        assert np.prod([g.edges[cyc[k], cyc[(k + 1) % len(cyc)]]["s"] for k in range(len(cyc))]) < 0
    assert checked > 100


def test_shortest_cycle_prefers_the_shorter_of_two():
    rels = [(0, 1, "+"), (1, 2, "+"), (2, 3, "+"), (3, 4, "+"), (0, 4, "-"), (4, 5, "+"),
            (5, 6, "+"), (6, 7, "+"), (5, 7, "-")]
    assert analyze(graph(8, rels)).frustrated_cycle == [5, 6, 7]


# ------------------------------------------------------------------------------------------ verdict (§4.6)
def test_a_single_contradiction_is_balanced_but_fires_the_direct_clause():
    rep = analyze(graph(2, [(0, 1, "-", 0.9)]))
    assert rep.balanced and rep.conflict == 0.0
    assert rep.verdict_inconsistent and rep.verdict_clauses == ["direct"]


def test_quoted_claims_are_excluded_from_the_direct_clause():
    sg = graph(["asserted", "quoted"], [(0, 1, "-", 0.9)])
    rep = analyze(sg)
    assert not rep.verdict_inconsistent and rep.direct_contradictions == []
    assert pairwise_only(sg) == (True, [(0, 1)])                 # the baseline counts any two claims
    assert analyze(graph(["premise", "asserted"], [(0, 1, "-", 0.9)])).verdict_clauses == ["direct"]


def test_the_balance_clause_uses_confident_edges_only():
    rep = analyze(graph(3, [(0, 1, "+", 0.9), (1, 2, "+", 0.9), (0, 2, "-", 0.3)]))
    assert not rep.balanced and rep.conflict > 0 and rep.frustrated_cycle == [0, 1, 2]
    assert not rep.verdict_inconsistent and rep.confident_frustrated_cycle is None
    rep = analyze(graph(["quoted", "quoted", "quoted"], TRIANGLE))
    assert rep.verdict_clauses == ["claim_balance"]              # balance does not look at claim kinds


def test_zero_confidence_and_unrelated_relations_make_no_edge():
    sg = graph(3, [(0, 1, "-", 0.0), (1, 2, "0", 0.9), (0, 2, "+", 0.7)])
    assert sg.edges.tolist() == [[0, 2]] and sg.zero_weight == 1 and len(sg.relations) == 3


# ------------------------------------------------------------------------------------------ components
def test_conflict_is_the_sum_over_components():
    sg = graph(QUOTED[:6], [(0, 1, "+"), (1, 2, "-"), (3, 4, "+", 0.9), (4, 5, "+", 0.6), (3, 5, "-", 0.8)])
    rep = analyze(sg)
    lap = signed_laplacian(sg.n, sg.edges, sg.sign, sg.weight)
    lam = np.linalg.eigvalsh(lap[np.ix_([3, 4, 5], [3, 4, 5])])[0]
    assert rep.components == [[0, 1, 2], [3, 4, 5]]
    assert rep.component_conflict == {0: 0.0, 1: pytest.approx(lam)}
    assert rep.conflict == pytest.approx(lam) and lam > 0.1
    assert np.linalg.eigvalsh(lap)[0] == pytest.approx(0.0, abs=1e-12)   # the global minimum would hide it
    assert sum(r for (a, b), r in rep.edge_residuals.items() if a >= 3) == pytest.approx(lam)


def test_residuals_sum_to_lambda_min_with_multiplicity_one():
    sg = graph(QUOTED[:3], [(0, 1, "+"), (1, 2, "+"), (0, 2, "-", 0.5)])
    rep = analyze(sg)
    lam, u = np.linalg.eigh(signed_laplacian(sg.n, sg.edges, sg.sign, sg.weight))
    assert not rep.degenerate and lam[1] - lam[0] > 0.1
    x = u[:, 0]
    by_edge = sg.weight * (x[sg.edges[:, 0]] - sg.sign * x[sg.edges[:, 1]]) ** 2
    assert np.allclose(list(rep.edge_residuals.values()), by_edge)
    assert sum(rep.edge_residuals.values()) == pytest.approx(lam[0]) == pytest.approx(rep.conflict)
    assert rep.claim_residuals.sum() == pytest.approx(2 * lam[0])


def test_repeated_lambda_min_residuals_do_not_depend_on_the_eigenbasis():
    sg = graph(QUOTED[:6], TWO_TRIANGLES)
    rep = analyze(sg)
    lam, u = np.linalg.eigh(signed_laplacian(sg.n, sg.edges, sg.sign, sg.weight))
    m = int(np.sum(np.isclose(lam, lam[0])))
    assert m == 3 and rep.degenerate and rep.component_degenerate == {0: True}
    basis = u[:, :m]
    q, _ = np.linalg.qr(np.random.default_rng(2).normal(size=(m, m)))
    r1 = eigenspace_residuals(basis, sg.edges, sg.sign, sg.weight)
    r2 = eigenspace_residuals(basis @ q, sg.edges, sg.sign, sg.weight)
    assert np.allclose(r1, r2) and np.allclose(list(rep.edge_residuals.values()), r1)
    assert r1.sum() == pytest.approx(lam[0]) == pytest.approx(rep.conflict)
    assert np.ptp(r1) > 0.05                                    # not uniform, so the check has teeth

    def first_vector(b):
        return sg.weight * (b[sg.edges[:, 0], 0] - sg.sign * b[sg.edges[:, 1], 0]) ** 2
    assert not np.allclose(first_vector(basis), first_vector(basis @ q))   # one eigenvector alone would differ

    # relabelling the claims relabels the residuals
    perm = [4, 2, 5, 0, 3, 1]
    moved = analyze(graph(QUOTED[:6], [(perm[a], perm[b], *rest) for a, b, *rest in TWO_TRIANGLES]))
    for (a, b), r in rep.edge_residuals.items():
        assert moved.edge_residuals[tuple(sorted((perm[a], perm[b])))] == pytest.approx(r)
    assert np.allclose(moved.claim_residuals[perm], rep.claim_residuals)


def test_sign_rule():
    s = 1 / math.sqrt(2)
    assert analyze(graph(QUOTED[:2], [(0, 1, "-")])).truth_assignment == pytest.approx([s, -s])   # tie: first entry
    x = analyze(graph(QUOTED[:3], [(0, 1, "+"), (1, 2, "-")])).truth_assignment
    assert x == pytest.approx(np.array([1.0, 1.0, -1.0]) / math.sqrt(3))  # equal magnitudes: the first is positive


def test_a_single_claim_is_its_own_component():
    for kinds in (3, QUOTED[:3]):
        rep = analyze(graph(kinds, [(0, 1, "+")]))
        assert rep.components == [[0, 1], [2]] and rep.component_conflict[1] == 0.0
        assert rep.truth_assignment[2] == 1.0 and rep.claim_residuals[2] == 0.0
    assert rep.unanchored_components == [[0, 1], [2]]           # quoted claims anchor nothing


# ------------------------------------------------------------------------------------------ harmony
def test_a_premise_contradicting_an_asserted_claim():
    rep = analyze(graph(["premise", "asserted"], [(0, 1, "-")]))
    assert rep.truth_assignment == pytest.approx([1.0, 0.0], abs=1e-12)
    assert rep.harmony == pytest.approx(0.75)                   # E = 1 + 1 against the bound 4 w + 4 mu
    assert rep.claim_residuals == pytest.approx([1.0, 2.0])     # the edge; the edge plus the assertion term
    assert rep.residual_ranking == [1, 0]


def test_two_asserted_claims_contradicting_each_other_without_premises():
    rep = analyze(graph(2, [(0, 1, "-")]))
    assert rep.clamp_set == [] and rep.unanchored_components == []
    assert rep.truth_assignment == pytest.approx([1 / 3, 1 / 3])
    assert rep.harmony == pytest.approx(1 - (4 / 3) / 12) and rep.harmony < 1


def test_a_quoted_claim_contradicted_by_a_premise_flips_at_no_cost():
    for kinds in (["premise", "quoted"], ["asserted", "quoted"]):
        rep = analyze(graph(kinds, [(0, 1, "-")]))
        assert rep.truth_assignment == pytest.approx([1.0, -1.0])
        assert rep.harmony == pytest.approx(1.0) and rep.residual_ranking == [] and rep.culprits == []


def test_unanchored_components_keep_their_own_eigenvector():
    rels = [(0, 1, "+", 0.8), (2, 3, "+"), (3, 4, "+"), (2, 4, "-")]
    rep = analyze(graph(["premise", "asserted", "quoted", "quoted", "quoted"], rels))
    free = analyze(graph(QUOTED[:5], rels))
    assert rep.clamp_set == [0] and rep.unanchored_components == [[2, 3, 4]]
    assert rep.truth_assignment[:2] == pytest.approx([1.0, 1.0])
    assert rep.truth_assignment[2:] == pytest.approx(free.truth_assignment[2:])
    assert rep.harmony == pytest.approx(1.0)                    # from the anchored component only
    assert rep.conflict == pytest.approx(free.conflict) == pytest.approx(1.0)


def test_harmony_is_not_measured_when_no_relation_reaches_an_anchor():
    rep = analyze(graph(["premise", "premise", "asserted"], []))
    assert rep.harmony is None and rep.harmony_reason == NO_RELATIONS
    rep = analyze(graph(["premise", "quoted", "quoted"], [(1, 2, "+", 0.9)]))
    assert rep.harmony is None and rep.harmony_reason == NO_RELATIONS and rep.unanchored_components == [[1, 2]]
    rep = analyze(graph(QUOTED[:3], [(0, 1, "-")]))
    assert rep.harmony is None and rep.harmony_reason == NO_ANCHORS
    rep = analyze(graph(QUOTED[:3], [(0, 1, "-")]), evidence=[2])
    assert rep.harmony is None and rep.harmony_reason == NO_RELATIONS and rep.clamp_set == [2]
    # asserted claims anchor their component, so a related pair is measured without premises
    rep = analyze(graph(["premise", "asserted", "asserted"], [(1, 2, "+", 0.9)]))
    assert rep.harmony == pytest.approx(1.0) and rep.unanchored_components == []


def test_isolated_claims():
    rels = [(0, 1, "-", 0.9), (1, 2, "+", 0.7), (2, 3, "+", 0.6), (0, 3, "+", 0.5)]
    a = analyze(graph(["premise", "asserted", "asserted", "asserted"], rels))
    b = analyze(graph(["premise", "asserted", "asserted", "asserted", "premise"], rels))
    assert 0 < a.harmony < 1 and b.harmony == pytest.approx(a.harmony)   # an isolated premise contributes nothing
    assert b.clamp_set == [0, 4] and b.truth_assignment[4] == 1.0
    c = analyze(graph(["premise", "asserted", "asserted", "asserted", "asserted"], rels))
    assert c.truth_assignment[4] == 1.0 and c.harmony == pytest.approx(a.harmony)   # nor does an isolated assertion


@pytest.mark.parametrize("unrelated", [0, 1, 5, 20])
def test_unrelated_assertions_do_not_pad_harmony(unrelated):
    rep = analyze(graph(["premise", "asserted"] + ["asserted"] * unrelated, [(0, 1, "-", 1.0)]))
    assert rep.harmony == pytest.approx(0.75) and rep.truth_assignment[1] == pytest.approx(0.0)
    rep = analyze(graph(["asserted", "asserted"] + ["asserted"] * unrelated, [(0, 1, "-", 1.0)]))
    assert rep.harmony == pytest.approx(1 - (4 / 3) / 12)


def test_premise_contradicting_two_asserted_claims():
    """Acceptance (§9), with only the premise clamped: harmony < 1, the premise among the top-3 residual claims and
    still clamped. Claims 1 and 2 contradict premise 0, claims 3 and 4 support them, and claim 5 supports claim 4."""
    kinds = ["premise", "asserted", "asserted", "asserted", "asserted", "asserted"]
    rels = [(0, 1, "-", 0.9), (0, 2, "-", 0.9), (1, 3, "+", 0.9), (2, 4, "+", 0.9), (4, 5, "+", 0.6)]
    sg = graph(kinds, rels)
    rep = analyze(sg)
    assert rep.clamp_set == [0] and rep.truth_assignment[0] == 1.0
    assert rep.balanced and rep.conflict == 0.0                 # no frustrated cycle: the assertions conflict
    assert rep.harmony < 1 and 0 in rep.residual_ranking[:3]
    assert rep.harmony == pytest.approx(1 - full_energy(sg, rep.truth_assignment) / (4 * 4.2 + 4 * ASSERTION_MU * 5))


# ------------------------------------------------------------------------------------------ invariants (§4.5)
def test_I1_evidence_is_never_dropped():
    sg = graph(["premise", "asserted", "premise", "asserted", "quoted"], [(0, 1, "-"), (1, 3, "+"), (3, 4, "-")])
    rep = analyze(sg, evidence=[3, 0, 3])
    assert rep.clamp_set == [0, 2, 3]
    assert all(rep.truth_assignment[v] == 1.0 for v in rep.clamp_set)
    assert analyze(sg).clamp_set == [0, 2]
    with pytest.raises(ValueError, match="outside"):
        analyze(sg, evidence=[5])


def test_I2_scores_are_computed_on_the_full_graph():
    rng = np.random.default_rng(3)
    sg = random_graph(rng, 7, p=0.6, kinds=["premise"] + ["asserted"] * 6, positive=0.5)
    before = (sg.edges.copy(), sg.sign.copy(), sg.weight.copy(), list(sg.relations))
    rep = analyze(sg)
    assert np.array_equal(sg.edges, before[0]) and np.array_equal(sg.sign, before[1])
    assert np.array_equal(sg.weight, before[2]) and sg.relations == before[3]
    lap = signed_laplacian(sg.n, sg.edges, sg.sign, sg.weight)
    lam = sum(np.linalg.eigvalsh(lap[np.ix_(c, c)])[0] if len(c) > 1 else 0.0 for c in rep.components)
    assert rep.conflict == pytest.approx(max(lam, 0.0), abs=1e-9)
    assert rep.n_edges == len(sg.edges) and len(rep.edge_residuals) == len(sg.edges)


def test_I3_premises_are_immutable():
    sg = graph(["premise", "asserted"], [(0, 1, "-")])
    with pytest.raises(ValidationError):
        sg.claims[0].text = "rewritten"
    with pytest.raises(ValidationError):
        sg.claims[0].kind = "asserted"
    rep = analyze(sg)
    assert sg.claims[0].text == "claim 0" and sg.claims[0].kind == "premise" and rep.truth_assignment[0] == 1.0


def test_I4_scale_invariance(monkeypatch):
    """Edge weights and mu scaled together."""
    rng = np.random.default_rng(4)
    ranked = 0
    for _ in range(20):
        n = int(rng.integers(4, 9))
        kinds = ["premise"] + [str(k) for k in rng.choice(["asserted", "asserted", "quoted"], size=n - 1)]
        rels = [(i, j, "+" if rng.random() < 0.5 else "-", float(rng.uniform(0.2, 1.0)))
                for i in range(n) for j in range(i + 1, n) if rng.random() < 0.6]
        a = analyze(graph(kinds, rels))
        with monkeypatch.context() as m:
            m.setattr(consistency, "ASSERTION_MU", 0.1 * ASSERTION_MU)
            b = analyze(graph(kinds, [(i, j, s, c * 0.1) for i, j, s, c in rels]))
        if a.harmony is None:
            assert b.harmony is None
            continue
        assert b.harmony == pytest.approx(a.harmony)
        assert b.conflict == pytest.approx(0.1 * a.conflict, abs=1e-12)
        assert b.residual_ranking == a.residual_ranking
        assert [c for c, _, _ in b.culprits] == [c for c, _, _ in a.culprits]
        ranked += bool(a.residual_ranking)
    assert ranked >= 5


def test_a_consistent_document_ranks_no_claims():
    """Every relation holds when the premises and asserted claims are true; quoted claims may be false."""
    rng = np.random.default_rng(6)
    for _ in range(20):
        n = int(rng.integers(3, 9))
        kinds = ["premise"] + [str(k) for k in rng.choice(["asserted", "quoted"], size=n - 1)]
        truth = [1.0 if k != "quoted" else float(rng.choice([-1.0, 1.0])) for k in kinds]
        rels = [(i, j, "+" if truth[i] == truth[j] else "-", float(rng.uniform(0.05, 1.0)))
                for i in range(n) for j in range(i + 1, n) if rng.random() < 0.6]
        rep = analyze(graph(kinds, rels))
        assert rep.balanced and rep.residual_ranking == [] and rep.culprits == []
        assert rep.harmony is None or rep.harmony == pytest.approx(1.0)


def test_I5_no_free_lunch_from_agnosticism():
    """E, with the assertion term, over the anchored components (those with a clamped or an asserted claim)."""
    rng = np.random.default_rng(5)
    for _ in range(20):
        n = int(rng.integers(3, 9))
        kinds = [str(rng.choice(["premise", "asserted", "asserted", "quoted"])) for _ in range(n)]
        kinds[0] = "premise"
        sg = random_graph(rng, n, p=0.6, kinds=kinds, positive=0.5)
        rep = analyze(sg)
        anchored = [v for c in rep.components if c not in rep.unanchored_components for v in c]
        asserted = np.array([k == "asserted" for k in kinds])
        x = rep.truth_assignment
        clamped = np.array(rep.clamp_set)

        def anchored_energy(y):
            keep = np.isin(sg.edges[:, 0], anchored)
            e = sg.edges[keep]
            return (float(np.sum(sg.weight[keep] * (y[e[:, 0]] - sg.sign[keep] * y[e[:, 1]]) ** 2))
                    + ASSERTION_MU * float(np.sum((y[asserted] - 1.0) ** 2)))
        best = anchored_energy(x)
        for y in [np.ones(n), np.zeros(n)] + [rng.uniform(-1, 1, n) for _ in range(50)]:
            y = y.copy()
            y[clamped] = 1.0
            assert best <= anchored_energy(y) + 1e-9
        assert np.all(np.abs(x) <= 1 + 1e-9)                    # maximum principle


# ------------------------------------------------------------------------------------------ culprits and export
def test_culprits_are_counterfactual_and_recompute_components():
    rels = [(0, 1, "+"), (1, 2, "+"), (0, 2, "-"), (0, 3, "+"), (3, 4, "+"), (0, 4, "-")]   # bowtie through 0
    rep = analyze(graph(QUOTED[:5], rels))
    assert rep.conflict == pytest.approx(1.0) and len(rep.culprits) == CULPRIT_K
    claim, drop, gain = rep.culprits[0]
    assert claim == 0 and drop == pytest.approx(1.0) and gain is None   # removing 0 leaves two balanced paths
    assert rep.conflict == pytest.approx(1.0)                   # the headline number is untouched
    asserted = analyze(graph(5, rels))                          # harmony is measured, so its change is reported
    claim, drop, gain = asserted.culprits[0]
    assert claim == 0 and drop == pytest.approx(1.0) and gain == pytest.approx(1 - asserted.harmony) and gain > 0
    # joined by a bridge, one component with lambda_min 1: removing claim 2 or 3 leaves the other triangle (drop 0);
    # apart, two components of lambda_min 1 each: removing a claim of one triangle drops the conflict by 1
    joined = analyze(graph(QUOTED[:6], TWO_TRIANGLES))
    by_claim = {c: d for c, d, _ in joined.culprits}
    assert joined.conflict == pytest.approx(1.0) and {2, 3} <= set(by_claim)
    assert by_claim[2] == pytest.approx(0.0, abs=1e-9) and by_claim[3] == pytest.approx(0.0, abs=1e-9)
    apart = analyze(graph(QUOTED[:6], TWO_TRIANGLES[:-1]))
    assert apart.conflict == pytest.approx(2.0) and [c for c, _, _ in apart.culprits] == [0, 1, 2]
    assert all(d == pytest.approx(1.0) for _, d, _ in apart.culprits)


def test_report_exports_to_json():
    rep = analyze(graph(["premise", "asserted", "asserted"], TRIANGLE))
    d = json.loads(json.dumps(report_to_dict(rep)))
    assert d["verdict_inconsistent"] and d["clamp_set"] == [0] and len(d["truth_assignment"]) == 3
    assert {"harmony", "harmony_reason", "unanchored_components", "frustrated_cycle", "entity_contradictions",
            "claim_residuals", "edge_residuals", "culprits", "verdict_clauses", "llm_usage"} <= set(d)
    assert d["culprits"][0].keys() == {"claim", "conflict_drop", "harmony_change"}
