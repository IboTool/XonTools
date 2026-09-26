"""V1.2 geometry rules (XON_SIM_GEOMETRY_V1_2.md §3): carpet, vicsek and sierpinski_p."""
import itertools

import numpy as np
import pytest
from scipy.sparse import csgraph

from xon.config import XonConfig
from xon.dynamics import State
from xon.graph import canonical_edges, graph_from_edges
from xon.growth import (CARPET_KEEP, RULE_GROUPS, RULES, VICSEK_KEEP, build_graph, get_rule,
                        interpolate_amplitudes, interpolate_weighted)
from xon.sandbox import Sandbox

CFG = XonConfig()
KEEP = {"carpet": CARPET_KEEP, "vicsek": VICSEK_KEEP}


def kept_cells(level: int, keep) -> list[tuple[int, int]]:
    """Cells (x, y) of the 3^level grid whose base-3 digit pair is a kept sub-square at every scale."""
    n = 3 ** level
    return [(x, y) for x in range(n) for y in range(n)
            if all(((x // 3 ** k) % 3, (y // 3 ** k) % 3) in keep for k in range(level))]


def brute_force(level: int, keep) -> tuple[set, set]:
    verts, edges = set(), set()
    for x, y in kept_cells(level, keep):
        c = [(x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)]
        verts.update(c)
        edges.update(frozenset(e) for e in zip(c, c[1:] + c[:1]))
    return verts, edges


def grid_coords(g) -> np.ndarray:
    return np.round(g.coords * 3 ** g.level).astype(np.int64)


@pytest.mark.parametrize("rule", ["carpet", "vicsek"])
@pytest.mark.parametrize("level", [1, 2, 3])
def test_square_rules_match_brute_force(rule, level):
    g = build_graph(CFG, level, rule)
    verts, edges = brute_force(level, KEEP[rule])
    xy = [tuple(p) for p in grid_coords(g).tolist()]
    assert g.n() == len(verts) and g.n_edges() == len(edges)
    assert set(xy) == verts
    assert {frozenset((xy[u], xy[v])) for u, v in g.edges} == edges


@pytest.mark.parametrize("rule", ["carpet", "vicsek"])
@pytest.mark.parametrize("level", [1, 2, 3])
def test_no_vertex_strictly_inside_a_removed_cell(rule, level):
    keep = KEEP[rule]
    xy = grid_coords(build_graph(CFG, level, rule))
    for scale in range(1, level + 1):
        size = 3 ** (level - scale)
        removed = np.array([(3 * x + i, 3 * y + j) for x, y in kept_cells(scale - 1, keep)
                            for i, j in itertools.product(range(3), repeat=2) if (i, j) not in keep])
        lo = removed[:, None, :] * size
        inside = ((xy[None] > lo) & (xy[None] < lo + size)).all(axis=2)
        assert not inside.any(), (scale, removed[inside.any(axis=1)][:3])


@pytest.mark.parametrize("level", range(6))
def test_closed_form_counts(level):
    carpet, vicsek = build_graph(CFG, level, "carpet"), build_graph(CFG, level, "vicsek")
    assert vicsek.n() == 2 * 5 ** level + 2 and vicsek.n_edges() == 3 * 5 ** level + 1
    n = 4
    for k in range(level):
        n = 8 * n - 8 * (3 ** k + 1)
    assert carpet.n() == n


@pytest.mark.parametrize("rule", ["carpet", "vicsek"])
def test_predict_new_vertices_is_net_growth(rule):
    r = get_rule(rule)
    g = r.seed(CFG)
    for _ in range(4):
        expected = g.n() + r.predict_new_vertices(g, CFG)
        g, _ = r.grow(g, None, CFG)
        assert g.n() == expected


@pytest.mark.parametrize("rule", ["carpet", "vicsek"])
@pytest.mark.parametrize("level", [1, 2, 3])
def test_subregion_is_lowest_index_top_level_square(rule, level):
    keep = KEEP[rule]
    g = build_graph(CFG, level, rule)
    index = {xy: i for i, xy in enumerate(keep)}
    best: dict = {}
    for x, y in kept_cells(level, keep):
        top = index[(x // 3 ** (level - 1), y // 3 ** (level - 1))]
        for c in [(x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)]:
            best[c] = min(best.get(c, top), top)
    xy = [tuple(p) for p in grid_coords(g).tolist()]
    assert g.labels["subregion"].tolist() == [best[c] for c in xy]
    assert sorted(set(best.values())) == list(range(len(keep)))


def test_carpet_only_adds_vertices_and_vicsek_replaces_them():
    for rule in ("carpet", "vicsek"):
        r = get_rule(rule)
        g = r.seed(CFG)
        for level in range(1, 4):
            old, (g, _) = g, r.grow(g, None, CFG)
            if rule == "carpet":
                n0 = old.n()
                assert np.allclose(g.coords[:n0], old.coords)
                assert np.array_equal(g.depth[:n0], old.depth) and (g.depth[n0:] == level).all()
                assert np.array_equal(g.labels["subregion"][:n0][old.labels["subregion"] >= 0],
                                      old.labels["subregion"][old.labels["subregion"] >= 0])
            else:
                assert (g.depth == level).all() and g.max_depth() == level
            assert g.version == old.version + 1 and g.uid == old.uid


def test_boundary_labels_mark_the_outer_square():
    carpet, vicsek = build_graph(CFG, 3, "carpet"), build_graph(CFG, 3, "vicsek")
    assert int(carpet.labels["boundary"].sum()) == 4 * 27
    tips = vicsek.coords[vicsek.labels["boundary"] == 1]
    assert len(tips) == 8 and ((np.isclose(tips, 0) | np.isclose(tips, 1)).any(axis=1)).all()


def test_interpolate_weighted_generalizes_the_gasket_midpoint():
    rng = np.random.default_rng(0)
    a1, a2 = rng.normal(size=20) + 1j * rng.normal(size=20), rng.normal(size=20) + 1j * rng.normal(size=20)
    assert np.allclose(interpolate_weighted(np.c_[a1, a2], [0.5, 0.5]), interpolate_amplitudes(a1, a2))
    same_phase = np.exp(0.7j) * np.array([[1.0, 2.0, 3.0, 4.0]])
    w = np.array([0.4, 0.2, 0.3, 0.1])
    assert np.allclose(interpolate_weighted(same_phase, w), np.exp(0.7j) * (w @ [1.0, 2.0, 3.0, 4.0]))


@pytest.mark.parametrize("rule", ["carpet", "vicsek"])
def test_state_is_extended_by_bilinear_interpolation(rule):
    r = get_rule(rule)
    g = r.seed(CFG)
    amps = np.array([1.0, 2.0, 3.0, 4.0])            # corners (0,0), (1,0), (1,1), (0,1), all phase 0.3
    state = State(amps * np.exp(0.3j))
    g1, s1 = r.grow(g, state, CFG)
    assert len(s1.a) == g1.n()
    x, y = g1.coords[:, 0], g1.coords[:, 1]
    bilinear = (1 - x) * (1 - y) * amps[0] + x * (1 - y) * amps[1] + x * y * amps[2] + (1 - x) * y * amps[3]
    assert np.allclose(s1.a, bilinear * np.exp(0.3j))
    if rule == "carpet":
        assert np.array_equal(s1.a[:4], state.a)


# ---------------------------------------------------------------------------- S(p, n)
def sierpinski_words(p: int, n: int):
    return list(itertools.product(range(p), repeat=n))


def definition_adjacent(u, v) -> bool:
    """Spec §3.1: u ~ v iff there is h with u_i = v_i (i < h), u_h != v_h, u_j = v_h and v_j = u_h (j > h)."""
    for h in range(len(u)):
        if u[h] != v[h]:
            return all(u[j] == v[h] and v[j] == u[h] for j in range(h + 1, len(u)))
    return False


def sp_graph(p: int, n: int):
    return build_graph(CFG.replace(sierpinski_p=p), n - 1, "sierpinski_p")


@pytest.mark.parametrize("p", [3, 4, 5])
@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_sierpinski_counts(p, n):
    g = sp_graph(p, n)
    assert g.n() == p ** n and g.n_edges() == p * (p ** n - 1) // 2
    deg = np.bincount(g.edges.ravel(), minlength=g.n())
    assert int((deg == p - 1).sum()) == p and ((deg == p) | (deg == p - 1)).all()
    assert set(np.flatnonzero(deg == p - 1)) == set(np.flatnonzero(g.labels["boundary"]))


@pytest.mark.parametrize("p,n", [(3, 3), (4, 3), (5, 2), (3, 4)])
def test_sierpinski_edges_follow_the_word_definition(p, n):
    g = sp_graph(p, n)
    words = [tuple(int(d) for d in np.base_repr(int(c), p).zfill(n)) for c in g.labels["word"]]
    expected = {frozenset((i, j)) for i, j in itertools.combinations(range(g.n()), 2)
                if definition_adjacent(words[i], words[j])}
    assert {frozenset(map(int, e)) for e in g.edges} == expected
    assert g.labels["subregion"].tolist() == [w[0] for w in words]


@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_s3_contracted_bridges_is_the_gasket(n):
    g = sp_graph(3, n)
    clique = g.labels["word"] // 3
    bridge = clique[g.edges[:, 0]] != clique[g.edges[:, 1]]
    merged = csgraph.connected_components(graph_from_edges(g.n(), g.edges[bridge]).adjacency(), directed=False)[1]
    contracted = canonical_edges(merged[g.edges[~bridge]])
    quotient = graph_from_edges(int(merged.max()) + 1, contracted)
    gasket = build_graph(CFG, n - 1, "gasket")
    assert quotient.n() == gasket.n() and quotient.n_edges() == gasket.n_edges()
    lam_q = np.linalg.eigvalsh(quotient.laplacian().toarray())
    lam_g = np.linalg.eigvalsh(gasket.laplacian().toarray())
    assert np.allclose(lam_q, lam_g, atol=1e-8)


def test_sierpinski_growth_keeps_ids_and_interpolates():
    cfg = CFG.replace(sierpinski_p=4)
    r = get_rule("sierpinski_p")
    g = r.seed(cfg)
    state = State(np.exp(1j * np.arange(4.0)))
    for level in range(1, 4):
        old, old_state = g, state
        g, state = r.grow(g, state, cfg)
        n0 = old.n()
        assert np.array_equal(g.labels["word"][:n0], old.labels["word"] * 4 + old.labels["word"] % 4)
        assert np.array_equal(state.a[:n0], old_state.a) and len(state.a) == g.n()
        assert np.array_equal(g.depth[:n0], old.depth) and (g.depth[n0:] == level).all()
        born = np.arange(n0, g.n())
        owner = g.parent[born]
        toward_code = old.labels["word"][owner] - old.labels["word"][owner] % 4 + g.labels["word"][born] % 4
        id_of = {int(c): i for i, c in enumerate(old.labels["word"])}
        toward = np.array([id_of[int(c)] for c in toward_code])
        assert np.allclose(state.a[born], interpolate_amplitudes(old_state.a[owner], old_state.a[toward]))


# ---------------------------------------------------------------------------- registry and sandbox
def test_rules_are_grouped_for_the_sidebar():
    assert list(RULES)[:3] == ["gasket", "carpet", "sierpinski_p"]
    assert set(RULE_GROUPS) == set(RULES)
    groups = [RULE_GROUPS[r] for r in RULES]
    assert groups == sorted(groups, key=["Candidates", "Bridge", "Controls"].index)
    assert RULE_GROUPS["vicsek"] == "Bridge" and RULE_GROUPS["tree"] == RULE_GROUPS["lattice"] == "Controls"


@pytest.mark.parametrize("rule", ["carpet", "vicsek", "sierpinski_p"])
def test_sandbox_runs_the_new_rules(rule):
    sb = Sandbox(CFG.replace(growth_rule=rule, target_level=2))
    sb.init_sheaf(2, "learned")
    assert sb.grow_to_target()[0] == 2
    sb.probe(0)
    sb.step(20)
    assert len(sb.s.a) == sb.g.n() and np.isfinite(sb.s.a).all()
    assert sb.sheaf.F_head.shape[0] == sb.g.n_edges()
    assert sb.spec.lam.shape == (sb.g.n(),) and sb.clusters().shape == (sb.g.n(),)
    assert len(sb.sheaf_diffusion(0.1, 10)["trace"]) > 0
    assert np.isfinite(sb.sheaf_inference(0.3, 0.1, 20)["mse"])
