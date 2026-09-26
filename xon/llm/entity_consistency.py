"""Contradictions in the entity-relation graph (XON_A1_CONSISTENCY.md §4.7).

Relations are grouped by attribute and each attribute is checked on its own:
1. Equality classes: union-find over "same" relations.
2. A "different" relation inside one class is a contradiction for every arity: the path of "same" relations between
   its two entities plus the "different" relation is a cycle with exactly one "different".
3. Binary attributes only: an odd cycle of "different" relations over the classes is a contradiction (Harary 1953:
   with exactly two values, "different" means "opposite", so the class graph must be 2-colourable). Not applied to
   "multi" or "unknown" attributes, where a != b, b != c, a != c is consistent; "unknown" counts as "multi".
4. A "greater" relation inside one class (a > b while a = b), or a directed cycle of "greater" relations over the
   classes (a > b > c > a), is a contradiction: a strict order has no cycles.
For each attribute and check, the shortest contradiction (fewest relations) is reported, with the claims whose
relations form it and the smallest confidence along it (localization).

Rev. 2.2 (XON_A1_REV2_2_PRECISION.md §5.8) builds the same graph from the model's statements instead of its
normalized relations (``build_entity_graph_v22``); the checks are unchanged, a superlative with a restriction is not
expanded, and an order cycle made by two superlatives of the same kind on one attribute is reported as a superlative
collision.

Standard library only, so that A1's full engine and the minimal engine (``minimal.py``) share this module. It reads
A1's schema objects by attribute; the schemas are imported for type checking only.
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schemas import EntityGraphSpec, EntityGraphSpecV22, EntityRelation, EntityStepsV22

CONFIDENCE_MIN = 0.5            # §4.6 / §4.7: the verdict uses relations with confidence >= this
ASSERTING_KINDS = ("asserted", "premise")
CONTRADICTION_TYPES = ("different_within_class", "binary_parity", "order_cycle")
CONTRADICTION_TYPES_V2_2 = CONTRADICTION_TYPES + ("superlative_collision",)

# A safety net behind the prompt's direction rule (§3.2): an attribute key that is itself a comparative is renamed
# to the attribute it compares, and a "greater" relation under a comparative toward less has its entities swapped.
COMPARATIVES = {"older": ("age", False), "younger": ("age", True), "taller": ("height", False),
                "shorter": ("height", True), "heavier": ("weight", False), "lighter": ("weight", True),
                "later": ("time", False), "earlier": ("time", True), "faster": ("speed", False),
                "slower": ("speed", True)}


def canonical_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")


def normalize_relation(r: EntityRelation) -> EntityRelation:
    attribute, a, b = canonical_key(r.attribute), canonical_key(r.a), canonical_key(r.b)
    if attribute in COMPARATIVES:
        attribute, toward_less = COMPARATIVES[attribute]
        if toward_less and r.kind == "greater":
            a, b = b, a
    update = {"attribute": attribute, "a": a, "b": b}
    # A1's relations are frozen pydantic models; a standalone caller of the minimal engine may pass dataclasses
    return r.model_copy(update=update) if hasattr(r, "model_copy") else replace(r, **update)


@dataclass
class EntityGraph:
    relations: list[EntityRelation]         # normalized; a relation's index is its id
    arity: dict[str, str]                   # attribute -> "binary" | "multi" | "unknown"
    arity_span: dict[str, str | None]       # attribute -> the sentence establishing its arity
    mentions: dict[str, list[str]]          # entity -> surface forms
    dropped: int = 0                        # relations whose claim_id is not a claim
    derivation: dict = field(default_factory=dict)   # rev. 2.2: how the relations were derived (§5.8)

    def attributes(self) -> list[str]:
        return sorted({r.attribute for r in self.relations})

    def arity_of(self, attribute: str) -> str:
        return self.arity.get(attribute, "unknown")


def _attribute_key(key: str) -> str:
    key = canonical_key(key)
    return COMPARATIVES.get(key, (key, False))[0]


def _arities(attributes) -> tuple[dict[str, str], dict[str, str | None]]:
    seen: dict[str, list] = defaultdict(list)
    for att in attributes:
        seen[_attribute_key(att.key)].append(att)
    arity, span = {}, {}
    for key, atts in seen.items():
        kinds = {a.arity for a in atts}
        # binary only if every entry says so: fewer false alarms when the model is inconsistent
        arity[key] = "binary" if kinds == {"binary"} else ("multi" if "multi" in kinds else "unknown")
        span[key] = next((a.arity_span for a in atts if a.arity == arity[key] and a.arity_span), None)
    return arity, span


def build_entity_graph(spec: EntityGraphSpec, n_claims: int | None = None) -> EntityGraph:
    relations, dropped = [], 0
    for r in spec.relations:
        if n_claims is not None and not 0 <= r.claim_id < n_claims:
            dropped += 1
            continue
        relations.append(normalize_relation(r))
    arity, span = _arities(spec.attributes)
    mentions = {canonical_key(e.id): list(e.mentions) for e in spec.entities}
    return EntityGraph(relations, arity, span, mentions, dropped)


# ------------------------------------------------------------------------------------------ rev. 2.2 derivation
@dataclass(frozen=True)
class DerivedRelation:
    """An entity relation the rev. 2.2 engine derives from the model's statements; read like EntityRelation."""
    claim_id: int
    attribute: str
    kind: str                               # "same" | "different" | "greater" (a > b)
    a: str
    b: str
    confidence: float
    derived_from_extreme: bool = False
    extreme: str | None = None              # "max" | "min" for a relation derived from an extreme statement


def build_entity_graph_v22(spec: EntityGraphSpecV22 | EntityStepsV22, n_claims: int | None = None) -> EntityGraph:
    """The entity graph of rev. 2.2's statements (XON_A1_REV2_2_PRECISION.md §5.8): what the entity steps returned
    (an inventory, the relations call's statements and the coverage call's, from development iteration 1), or the
    statements of iteration 0's single entity call, read by attribute.

    Same and different relations are kept as stated. An order statement becomes greater(subject, object) or
    greater(object, subject) by its comparative's sense: the lexicon's on a sequence or magnitude attribute when the
    lexicon covers the comparative (a model sense that disagrees is listed in sense_overrides), otherwise the
    model's. An unrestricted extreme statement on E becomes greater(E, X) for "max" and greater(X, E) for "min", for
    every other entity X of an order or unrestricted extreme statement on the attribute outside E's equality class
    (the classes of all its same relations), each keeping the statement's claim and confidence and marked
    derived_from_extreme. An extreme statement with a restriction is not expanded and is listed in
    restricted_extremes. Attribute keys are merged as in rev. 2.1, but a comparative key never swaps a derived
    direction. Statements whose claim_id is not a claim are dropped; statements whose sense is missing or of the
    wrong kind give no relation and are listed in unresolved. Under the entity steps, the coverage call's statements
    are added to the relations call's (_steps_graph)."""
    if hasattr(spec, "inventory"):
        return _steps_graph(spec, n_claims)
    return _derived_graph(spec.entities, spec.attributes, spec.same_different, spec.orders, spec.extremes,
                          spec.senses, spec.unsupported_order_claims, n_claims)


def _steps_graph(spec: EntityStepsV22, n_claims: int | None) -> EntityGraph:
    """The coverage call's statements for the claims it was asked about are added to the relations call's, and its
    senses after the relations call's; nothing of the relations call's is removed or changed (§5.6). A statement
    with an entity id or attribute key the inventory does not list, or from the coverage call for a claim it was not
    asked about, is not extracted: counted in invalid_ids (the per-document schema admits none; its fallback may)."""
    entity_ids = {canonical_key(e.id) for e in spec.inventory.entities} - {""}
    attribute_keys = {canonical_key(a.key) for a in spec.inventory.attributes} - {""}
    listed = set(spec.uncovered)
    kept: dict[str, list] = {"same_different": [], "orders": [], "extremes": []}
    entities_of = {"same_different": lambda s: (s.a, s.b), "orders": lambda s: (s.subject, s.object),
                   "extremes": lambda s: (s.entity,)}
    senses, unsupported, answered = [], [], set()
    invalid = added = 0
    for answer, asked in ((spec.relations, None), (spec.coverage, listed)):
        if answer is None:
            continue
        for name, statements in kept.items():
            for s in getattr(answer, name):
                if ((asked is None or s.claim_id in asked) and canonical_key(s.attribute) in attribute_keys
                        and all(canonical_key(e) in entity_ids for e in entities_of[name](s))):
                    statements.append(s)
                    if asked is not None:
                        added += 1
                        answered.add(s.claim_id)
                else:
                    invalid += 1
        claims = [int(c) for c in answer.unsupported_order_claims]
        invalid += sum(asked is not None and c not in asked for c in claims)
        claims = [c for c in claims if asked is None or c in asked]
        unsupported += claims
        if asked is not None:
            answered.update(claims)
        senses += answer.senses
    eg = _derived_graph(spec.inventory.entities, spec.inventory.attributes, kept["same_different"], kept["orders"],
                        kept["extremes"], senses, unsupported, n_claims)
    none = sorted({int(n.claim_id) for n in spec.coverage.none if n.claim_id in listed}) if spec.coverage else []
    eg.derivation.update(
        coverage={"lexicon_matched": list(spec.lexicon_matched), "uncovered": sorted(listed),
                  "follow_up": spec.coverage is not None, "statements_added": added, "none": none,
                  "still_uncovered": sorted(listed - answered - set(none))},
        schema_fallback=list(spec.schema_fallback), invalid_ids=invalid, skipped=spec.skipped)
    return eg


def _derived_graph(entities, attributes, same_different_statements, order_statements, extreme_statements,
                   sense_statements, unsupported_order_claims, n_claims: int | None) -> EntityGraph:
    # imported here: the minimal engine under rev. 2.1 loads exactly the modules its isolation test lists
    from .comparatives import lexicon_sense, normalize_comparative

    def valid(claim_id: int) -> bool:
        return n_claims is None or 0 <= claim_id < n_claims

    dropped = 0
    order_kind: dict[str, str | None] = {}
    for att in attributes:
        key = _attribute_key(att.key)
        if order_kind.get(key) is None:
            order_kind[key] = att.order_kind
    senses: dict[tuple[str, str], str] = {}
    duplicate_senses = 0
    for s in sense_statements:
        k = (_attribute_key(s.attribute), normalize_comparative(s.comparative))
        if k in senses:
            duplicate_senses += 1
        else:
            senses[k] = s.greater_side

    overrides, unresolved = [], []

    def sense_of(attribute: str, comparative: str, claim_id: int) -> str | None:
        norm = normalize_comparative(comparative)
        lexical, model = lexicon_sense(order_kind.get(attribute), norm), senses.get((attribute, norm))
        if lexical is not None and model is not None and model != lexical:
            overrides.append({"claim_id": claim_id, "attribute": attribute, "comparative": comparative,
                              "model": model, "lexicon": lexical})
        return lexical if lexical is not None else model

    same_different, orders, extremes = [], [], []
    participants: dict[str, set[str]] = defaultdict(set)
    for r in same_different_statements:
        if not valid(r.claim_id):
            dropped += 1
            continue
        same_different.append(DerivedRelation(r.claim_id, _attribute_key(r.attribute), r.kind, canonical_key(r.a),
                                              canonical_key(r.b), r.confidence))
    for s in order_statements:
        if not valid(s.claim_id):
            dropped += 1
            continue
        attribute, subj, obj = _attribute_key(s.attribute), canonical_key(s.subject), canonical_key(s.object)
        participants[attribute] |= {subj, obj}
        side = sense_of(attribute, s.comparative, s.claim_id)
        if side not in ("subject", "object"):
            unresolved.append({"claim_id": s.claim_id, "attribute": attribute, "comparative": s.comparative,
                               "statement": "order", "sense": side})
            continue
        a, b = (subj, obj) if side == "subject" else (obj, subj)
        orders.append(DerivedRelation(s.claim_id, attribute, "greater", a, b, s.confidence))
    resolved_extremes, restricted = [], []
    for s in extreme_statements:
        if not valid(s.claim_id):
            dropped += 1
            continue
        attribute, entity = _attribute_key(s.attribute), canonical_key(s.entity)
        restriction = getattr(s, "restriction", None)       # iteration 0's statements have none
        if restriction is not None and str(restriction).strip():
            restricted.append({"claim_id": s.claim_id, "attribute": attribute, "entity": entity,
                               "comparative": s.comparative, "restriction": restriction})
            continue
        participants[attribute].add(entity)
        side = sense_of(attribute, s.comparative, s.claim_id)
        if side not in ("max", "min"):
            unresolved.append({"claim_id": s.claim_id, "attribute": attribute, "comparative": s.comparative,
                               "statement": "extreme", "sense": side})
            continue
        resolved_extremes.append((s, attribute, entity, side))

    classes = _equality_classes(same_different)
    expansions = []
    for s, attribute, entity, side in resolved_extremes:
        own = classes.get(attribute, {}).get(entity, {entity})
        others = sorted(participants[attribute] - own)
        for x in others:
            a, b = (entity, x) if side == "max" else (x, entity)
            extremes.append(DerivedRelation(s.claim_id, attribute, "greater", a, b, s.confidence, True, side))
        expansions.append({"claim_id": s.claim_id, "attribute": attribute, "entity": entity, "extreme": side,
                           "edges": len(others)})
    arity, span = _arities(attributes)
    mentions = {canonical_key(e.id): list(e.mentions) for e in entities}
    unsupported = sorted({int(c) for c in unsupported_order_claims if valid(int(c))})
    derivation = {"order_kind": order_kind, "sense_overrides": overrides, "unresolved": unresolved,
                  "duplicate_senses": duplicate_senses, "superlatives": expansions,
                  "extreme_edges": len(extremes), "restricted_extremes": restricted,
                  "unsupported_order_claims": unsupported}
    return EntityGraph(same_different + orders + extremes, arity, span, mentions, dropped, derivation)


def _equality_classes(relations) -> dict[str, dict[str, set[str]]]:
    """Per attribute, each entity's equality class under the attribute's same relations."""
    root: dict[tuple[str, str], tuple[str, str]] = {}

    def find(v):
        root.setdefault(v, v)
        while root[v] != v:
            root[v] = root[root[v]]
            v = root[v]
        return v

    for r in relations:
        if r.kind == "same":
            ra, rb = find((r.attribute, r.a)), find((r.attribute, r.b))
            if ra != rb:
                root[max(ra, rb)] = min(ra, rb)
    members: dict[tuple[str, str], set[str]] = defaultdict(set)
    for v in list(root):
        members[find(v)].add(v[1])
    out: dict[str, dict[str, set[str]]] = defaultdict(dict)
    for v in root:
        out[v[0]][v[1]] = members[find(v)]
    return out


@dataclass
class EntityContradiction:
    type: str                   # one of CONTRADICTION_TYPES
    attribute: str
    entities: list[str]         # the cycle in order; it closes back to the first entity
    relations: list[int]        # indices into EntityGraph.relations, in cycle order
    claim_ids: list[int]        # the claims stating those relations
    min_confidence: float


def eligible_relations(eg: EntityGraph, kinds: list[str], confidence_min: float,
                       asserting_kinds=ASSERTING_KINDS) -> set[int]:
    """Relations that may enter the verdict: confidence >= confidence_min, stated by an asserted or premise claim."""
    return {i for i, r in enumerate(eg.relations) if r.confidence >= confidence_min and kinds[r.claim_id]
            in asserting_kinds}


def find_contradictions(eg: EntityGraph, use: set[int] | None = None) -> list[EntityContradiction]:
    """The shortest contradiction of each type on each attribute, among the relations in ``use`` (default: all)."""
    by_attribute: dict[str, list[int]] = defaultdict(list)
    for i in (range(len(eg.relations)) if use is None else sorted(use)):
        by_attribute[eg.relations[i].attribute].append(i)
    out = []
    for attribute in sorted(by_attribute):
        out += _check_attribute(eg, attribute, by_attribute[attribute])
    return out


def _path(start: str, goal: str, moves) -> list[tuple[str, int]] | None:
    """Fewest-relation path as [(entity, relation), ...] ending at goal; [] if start == goal; None if unreachable."""
    if start == goal:
        return []
    prev = {start: None}
    queue = deque([start])
    while queue:
        u = queue.popleft()
        for v, rel in moves(u):
            if v in prev:
                continue
            prev[v] = (u, rel)
            if v == goal:
                steps, node = [], goal
                while prev[node] is not None:
                    parent, r = prev[node]
                    steps.append((node, r))
                    node = parent
                return steps[::-1]
            queue.append(v)
    return None


def _contradiction(eg: EntityGraph, type_: str, attribute: str, entities: list[str],
                   relations: list[int]) -> EntityContradiction:
    rels = [eg.relations[i] for i in relations]
    return EntityContradiction(type_, attribute, entities, relations, sorted({r.claim_id for r in rels}),
                               min(min(max(r.confidence, 0.0), 1.0) for r in rels))


def _check_attribute(eg: EntityGraph, attribute: str, ids: list[int]) -> list[EntityContradiction]:
    rel = eg.relations
    same = [i for i in ids if rel[i].kind == "same"]
    different = [i for i in ids if rel[i].kind == "different"]
    greater = [i for i in ids if rel[i].kind == "greater"]
    same_adj: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for i in same:
        a, b = rel[i].a, rel[i].b
        if a != b:
            same_adj[a].append((b, i))
            same_adj[b].append((a, i))
    for moves in same_adj.values():
        moves.sort()

    def by_same(u):
        return same_adj.get(u, ())

    found = []
    # 2. "different" inside an equality class: the same-path from a to b, then the different relation back to a
    best = None
    for i in different:
        a, b = rel[i].a, rel[i].b
        steps = _path(a, b, by_same)
        if steps is not None and (best is None or len(steps) + 1 < len(best[1])):
            best = ([a] + [e for e, _ in steps], [r for _, r in steps] + [i])
    if best is not None:
        found.append(_contradiction(eg, "different_within_class", attribute, *best))

    # 3. binary parity: an odd cycle of "different" relations over the equality classes
    if eg.arity_of(attribute) == "binary":
        cycle = _odd_class_cycle(rel, same_adj, different, by_same)
        if cycle is not None:
            found.append(_contradiction(eg, "binary_parity", attribute, *cycle))

    # 4. order: a greater relation a > b closed by a path from b back to a along greater relations (forward) and
    #    same relations (either way); inside one class the path uses same relations only
    down: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for i in greater:
        down[rel[i].a].append((rel[i].b, i))
    for u, moves in same_adj.items():
        down[u].extend(moves)
    for moves in down.values():
        moves.sort()
    best = None
    for i in greater:
        a, b = rel[i].a, rel[i].b
        steps = _path(b, a, lambda u: down.get(u, ()))
        if steps is not None and (best is None or len(steps) + 1 < len(best[1])):
            best = ([a] + ([b] + [e for e, _ in steps])[:-1], [i] + [r for _, r in steps])
    if best is not None:
        found.append(_contradiction(eg, _order_type([rel[i] for i in best[1]]), attribute, *best))
    return found


def _order_type(cycle) -> str:
    """Rev. 2.2: a 2-cycle made by two superlatives of the same kind (two entities both first) is a superlative
    collision; every other order cycle, and every rev. 2.1 one, is an order cycle."""
    sides = {getattr(r, "extreme", None) for r in cycle}
    if len(cycle) == 2 and all(getattr(r, "derived_from_extreme", False) for r in cycle) and len(sides) == 1:
        return "superlative_collision"
    return "order_cycle"


def _odd_class_cycle(rel, same_adj, different, by_same):
    """Shortest odd cycle of "different" relations between distinct equality classes, expanded to entities.

    Over classes, a closed walk through class c with an odd number of relations is a path from (c, 0) to (c, 1) in
    the parity double cover; the shortest such walk over all c is a simple cycle."""
    root: dict[str, str] = {}

    def find(v):
        root.setdefault(v, v)
        while root[v] != v:
            root[v] = root[root[v]]
            v = root[v]
        return v

    for u, moves in same_adj.items():
        for v, _ in moves:
            ru, rv = find(u), find(v)
            if ru != rv:
                root[max(ru, rv)] = min(ru, rv)
    adj: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for i in different:
        ca, cb = find(rel[i].a), find(rel[i].b)
        if ca != cb:
            adj[ca].append((cb, i))
            adj[cb].append((ca, i))
    for moves in adj.values():
        moves.sort()
    best = None                                   # (start class, relations of the walk)
    for start in sorted(adj):
        prev = {(start, 0): None}
        depth = {(start, 0): 0}
        queue = deque([(start, 0)])
        goal = (start, 1)
        while queue and goal not in prev:
            node = queue.popleft()
            if best is not None and depth[node] + 1 >= len(best[1]):
                break
            c, parity = node
            for d, i in adj[c]:
                nxt = (d, parity ^ 1)
                if nxt not in prev:
                    prev[nxt] = (node, i)
                    depth[nxt] = depth[node] + 1
                    queue.append(nxt)
        if goal in prev:
            walk, node = [], goal
            while prev[node] is not None:
                node, i = prev[node]
                walk.append(i)
            if best is None or len(walk) < len(best[1]):
                best = (start, walk[::-1])
    if best is None:
        return None
    # orient each relation along the walk: it leaves class cls at entity a and enters the next class at entity b
    start, walk = best
    oriented, cls = [], start
    for i in walk:
        a, b = rel[i].a, rel[i].b
        if find(a) != cls:
            a, b = b, a
        oriented.append((a, b, i))
        cls = find(b)
    # join each entry entity b to the next exit entity inside its class by a path of same relations
    entities, relations = [], []
    for k, (a, b, i) in enumerate(oriented):
        nxt = oriented[(k + 1) % len(oriented)][0]
        steps = _path(b, nxt, by_same)
        entities += [a, b] + [e for e, _ in steps][:-1]
        relations += [i] + [r for _, r in steps]
    merged = [e for k, e in enumerate(entities) if k == 0 or e != entities[k - 1]]
    if len(merged) > 1 and merged[-1] == merged[0]:
        merged.pop()
    return merged, relations
