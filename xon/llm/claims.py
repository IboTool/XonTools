"""Claims, relations and entity relations from text, and the graphs built from them (XON_A1_CONSISTENCY.md §3.3).

The signed claim graph is a V1 ``CellularSheaf`` with one-dimensional stalks (§4.1): an edge with sign s and weight w
has F_head = sqrt(w) and F_tail = s sqrt(w), so its Laplacian is the signed Laplacian L_s = D - S and its Dirichlet
energy is E(x) = sum w (x_i - s x_j)^2.

Rev. 2.2 (XON_A1_REV2_2_PRECISION.md §3, §4, §5) scores one pair per call, concurrently, and labels pairs that can
both be true but sit badly together "tension", which makes no edge; its entity steps (an inventory, then statements
under a schema built from the inventory, then a coverage net) report statements, from which
entity_consistency.build_entity_graph_v22 derives the relations. Every rev. 2.2 call has a "-v22" fixture tag.
"""
from __future__ import annotations

import hashlib
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import networkx as nx
import numpy as np

from ..graph import XonGraph, graph_from_edges
from ..sheaf import CellularSheaf
from . import prompts
from .client import LLM, LLMSchemaRejected
from .comparatives import lexicon_words_in
from .entity_consistency import EntityGraph, build_entity_graph, canonical_key
from .schemas import (AttributeV22, Claim, ClaimList, EntityCoverageV22, EntityGraphSpec, EntityRelationsV22,
                      EntityStepsV22, InventoryV22, PairList, Relation, RelationList, RelationListV22, RelationV22,
                      document_schema)

ALL_PAIRS_MAX = 25        # §3.2: every pair is scored up to this many claims; above it, the pairs the model proposes
BLIND_CHECK_FRAC = 0.1    # plus this fraction of the remaining pairs, drawn at random as a blind check
PAIRS_PER_CALL = 20
# A rationale holding a fragment of JSON (a brace, a quoted key and a colon, or an output field's name and a colon)
# shows a garbled answer. The pair is scored once more on its own; if that answer is malformed too or leaves the pair
# out, the pair stays unscored. Decided from the output's form alone, before any analysis (CHANGELOG, A1 re-spec 14).
JSON_FRAGMENT = re.compile(r"""[{}]|["'][A-Za-z_]\w*["']\s*:|\b(?:relation|confidence|rationale)["']?\s*:""")

NO_EDGE = ("unrelated", "tension")       # labels that make no edge of the claim graph
V22 = "v22"                             # rev. 2.2 fixture tags are <text tag>-v22-...

__all__ = ["ALL_PAIRS_MAX", "BLIND_CHECK_FRAC", "PAIRS_PER_CALL", "JSON_FRAGMENT", "SignedClaimGraph", "EntityGraph",
           "text_tag", "malformed_rationale", "extract_claims", "candidate_pairs", "score_relations",
           "extract_entity_relations", "build_signed_graph", "build_entity_graph", "score_pairs_v22",
           "extract_entity_steps_v22"]


def text_tag(text: str) -> str:
    """Fixture tag prefix of a text: the same text always maps to the same fixtures."""
    return "text-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def v22_tag(tag: str) -> str:
    return f"{tag}-{V22}"


def _seed_of(tag: str, seed: int) -> list[int]:
    return [int(seed), int(hashlib.sha256(tag.encode("utf-8")).hexdigest()[:8], 16)]


def malformed_rationale(rationale: str) -> bool:
    return JSON_FRAGMENT.search(rationale) is not None


# ------------------------------------------------------------------------------------------ LLM steps
def extract_claims(llm: LLM, text: str, *, tag: str) -> ClaimList:
    """Claims in the model's order (by its id), renumbered 0..n-1; claims with empty text are left out."""
    out = llm.parse(system=prompts.EXTRACT_SYSTEM, user=prompts.extract_user(text), schema=ClaimList,
                    max_tokens=llm.cfg.llm_max_tokens_extract, thinking=False, tag=f"{tag}-extract")
    kept = sorted((c for c in out.claims if c.text.strip()), key=lambda c: c.id)
    return ClaimList(claims=[c.model_copy(update={"id": i}) for i, c in enumerate(kept)])


def candidate_pairs(llm: LLM, claims: ClaimList, *, tag: str, seed: int = 0, world_knowledge: bool = False,
                    fixture_tag: str | None = None) -> tuple[list[tuple[int, int]], dict]:
    """The pairs to score (§3.2) and how they were chosen. ``tag`` also seeds the blind check; ``fixture_tag``, if
    given, replaces it as the selection call's fixture-tag prefix (rev. 2.2 reuses rev. 2.1's selections)."""
    n = len(claims.claims)
    every = [(i, j) for i in range(n) for j in range(i + 1, n)]
    if n <= ALL_PAIRS_MAX:
        return every, {"mode": "all", "proposed": 0, "blind": [], "invalid_proposed": 0}
    out = llm.parse(system=prompts.pairs_system(world_knowledge), user=prompts.pairs_user(claims), schema=PairList,
                    max_tokens=llm.cfg.llm_max_tokens_pairs, thinking=False,
                    tag=f"{fixture_tag or tag}-pairs{'-wk' if world_knowledge else ''}")
    proposed, invalid = set(), 0
    for p in out.pairs:
        a, b = sorted((p.a, p.b))
        if 0 <= a < b < n:
            proposed.add((a, b))
        else:
            invalid += 1
    rest = [p for p in every if p not in proposed]
    k = math.ceil(BLIND_CHECK_FRAC * len(rest))
    picks = np.random.default_rng(_seed_of(tag, seed)).choice(len(rest), size=k, replace=False) if k else []
    blind = {rest[int(i)] for i in picks}
    return sorted(proposed | blind), {"mode": "proposed + blind check", "proposed": len(proposed),
                                      "blind": sorted(blind), "invalid_proposed": invalid}


def _relate(llm: LLM, claims: ClaimList, pairs: list[tuple[int, int]], *, tag: str, world_knowledge: bool,
            bypass_cache: bool) -> RelationList:
    return llm.parse(system=prompts.relate_system(world_knowledge), user=prompts.relate_user(claims, pairs),
                     schema=RelationList, max_tokens=llm.cfg.llm_max_tokens_relate, thinking=False, tag=tag,
                     bypass_cache=bypass_cache)


def _answer(r: Relation) -> dict:
    return {"relation": r.relation, "confidence": r.confidence, "rationale": r.rationale}


def _score_batches(llm: LLM, claims: ClaimList, pairs: list[tuple[int, int]], *, tag: str,
                   world_knowledge: bool, bypass_cache: bool = False) -> tuple[RelationList, int, list[dict]]:
    """The relations, the count of relations ignored (a pair not asked for in its call, or asked for twice) and one
    record per pair scored again because its rationale was malformed, with both answers and the outcome: "replaced"
    by the second answer, or "unscored"."""
    wanted = [tuple(sorted(p)) for p in pairs]
    got: dict[tuple[int, int], Relation] = {}
    ignored = 0
    stem = f"{tag}-relate{'-wk' if world_knowledge else ''}"

    def take(out: RelationList, allowed: set) -> dict[tuple[int, int], Relation]:
        nonlocal ignored
        found = {}
        for r in out.relations:
            pair = tuple(sorted((r.a, r.b)))
            if pair in allowed and pair not in found:
                found[pair] = r.model_copy(update={"a": pair[0], "b": pair[1]})
            else:
                ignored += 1
        return found

    for k in range(0, len(wanted), PAIRS_PER_CALL):
        batch = wanted[k:k + PAIRS_PER_CALL]
        got.update(take(_relate(llm, claims, batch, tag=f"{stem}-{k // PAIRS_PER_CALL:03d}",
                                world_knowledge=world_knowledge, bypass_cache=bypass_cache), set(batch)))
    rescores = []
    for pair in [p for p in wanted if p in got and malformed_rationale(got[p].rationale)]:
        first = got.pop(pair)
        again = take(_relate(llm, claims, [pair], tag=f"{stem}-rescore-{pair[0]:03d}-{pair[1]:03d}",
                             world_knowledge=world_knowledge, bypass_cache=bypass_cache), {pair}).get(pair)
        clean = again is not None and not malformed_rationale(again.rationale)
        if clean:
            got[pair] = again
        rescores.append({"a": pair[0], "b": pair[1], "first": _answer(first),
                         "second": None if again is None else _answer(again),
                         "outcome": "replaced" if clean else "unscored"})
    return RelationList(relations=[got[p] for p in wanted if p in got]), ignored, rescores


def score_relations(llm: LLM, claims: ClaimList, pairs: list[tuple[int, int]] | None = None, *, tag: str,
                    world_knowledge: bool = False, seed: int = 0) -> RelationList:
    """One relation per scored pair, in batches of PAIRS_PER_CALL; pairs the model leaves out get no relation, and so
    do pairs whose rationale is malformed in the batch answer and again when the pair is scored on its own."""
    if pairs is None:
        pairs, _ = candidate_pairs(llm, claims, tag=tag, seed=seed, world_knowledge=world_knowledge)
    return _score_batches(llm, claims, pairs, tag=tag, world_knowledge=world_knowledge)[0]


def extract_entity_relations(llm: LLM, claims: ClaimList, *, tag: str, bypass_cache: bool = False) -> EntityGraphSpec:
    return llm.parse(system=prompts.ENTITY_SYSTEM, user=prompts.entity_user(claims), schema=EntityGraphSpec,
                     max_tokens=llm.cfg.llm_max_tokens_entities, thinking=False, tag=f"{tag}-entities",
                     bypass_cache=bypass_cache)


# ------------------------------------------------------------------------------------------ rev. 2.2 LLM steps
def run_concurrently(fn, items, limit: int) -> list:
    """fn over items, at most ``limit`` at a time, results in item order. The first error cancels the calls not yet
    started and is raised once the running ones have finished (their answers stay cached)."""
    items = list(items)
    if limit <= 1 or len(items) <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=min(int(limit), len(items))) as pool:
        futures = [pool.submit(fn, x) for x in items]
        try:
            return [f.result() for f in futures]
        except BaseException:
            for f in futures:
                f.cancel()
            raise


def _relate_pair_call(llm: LLM, claims: ClaimList, pair: tuple[int, int], *, tag: str, world_knowledge: bool,
                      bypass_cache: bool = False, attempt: int = 1) -> dict:
    """llm.parse's arguments for one pair (§4.1): the pair's two statements and ids, with a prompt-cache breakpoint on
    the shared system prompt."""
    return dict(system=prompts.relate_system_v2_2(world_knowledge), user=prompts.relate_single_user(claims, pair),
                schema=RelationV22, max_tokens=llm.cfg.llm_max_tokens_relate_single, thinking=False, tag=tag,
                bypass_cache=bypass_cache, cache_system=True, attempt=attempt)


def _entity_step(llm: LLM, *, system: str, user: str, schema, tag: str, bypass_cache: bool) -> dict:
    """llm.parse's arguments for an entity step (§5.7): adaptive thinking at the default effort, max_tokens for
    thinking plus output, and a prompt-cache breakpoint on the system prompt."""
    return dict(system=system, user=user, schema=schema, max_tokens=llm.cfg.llm_max_tokens_entity_steps,
                thinking="adaptive", tag=tag, bypass_cache=bypass_cache, cache_system=True)


def _inventory_call(llm: LLM, claims: ClaimList, *, tag: str, bypass_cache: bool = False) -> dict:
    return _entity_step(llm, system=prompts.ENTITY_INVENTORY_SYSTEM_V2_2, user=prompts.entity_user(claims),
                        schema=InventoryV22, tag=f"{tag}-entities-inventory", bypass_cache=bypass_cache)


def _relations_call(llm: LLM, claims: ClaimList, entities: dict, attributes: dict, *, tag: str,
                    bypass_cache: bool = False, fallback: bool = False) -> dict:
    schema = (document_schema(EntityRelationsV22) if fallback else
              document_schema(EntityRelationsV22, entities, attributes, [c.id for c in claims.claims]))
    return _entity_step(llm, system=prompts.ENTITY_RELATIONS_SYSTEM_V2_2,
                        user=prompts.entity_relations_user(claims, entities, attributes), schema=schema,
                        tag=f"{tag}-entities-relations{'-fallback' if fallback else ''}", bypass_cache=bypass_cache)


def _coverage_call(llm: LLM, claims: ClaimList, listed: list[int], entities: dict, attributes: dict, *, tag: str,
                   bypass_cache: bool = False, fallback: bool = False) -> dict:
    schema = (document_schema(EntityCoverageV22) if fallback else
              document_schema(EntityCoverageV22, entities, attributes, listed))
    return _entity_step(llm, system=prompts.ENTITY_COVERAGE_SYSTEM_V2_2,
                        user=prompts.entity_coverage_user(claims, listed, entities, attributes), schema=schema,
                        tag=f"{tag}-entities-coverage{'-fallback' if fallback else ''}", bypass_cache=bypass_cache)


def _relate_stem(tag: str, world_knowledge: bool) -> str:
    return f"{tag}-relate{'-wk' if world_knowledge else ''}"


def _pair_tag(stem: str, pair: tuple[int, int], rescore: bool = False) -> str:
    return f"{stem}-{'rescore-' if rescore else ''}{pair[0]:03d}-{pair[1]:03d}"


def planned_requests_v22(llm: LLM, claims: ClaimList, pairs: list[tuple[int, int]], *, tag: str,
                         world_knowledge: bool) -> list[tuple[dict, type, str, bool | str]]:
    """(body, schema, tag, thinking) of a document's first-attempt rev. 2.2 calls that can be sent before any
    answer, one per pair and the inventory call, exactly as score_pairs_v22 and extract_entity_steps_v22 send them
    (for client.BatchRunner). The relations and coverage calls depend on the inventory's answer."""
    stem = _relate_stem(tag, world_knowledge)
    calls = [_relate_pair_call(llm, claims, p, tag=_pair_tag(stem, p), world_knowledge=world_knowledge)
             for p in (tuple(sorted(p)) for p in pairs)] + [_inventory_call(llm, claims, tag=tag)]
    return [(llm.request(system=c["system"], user=c["user"], max_tokens=c["max_tokens"], thinking=c["thinking"],
                         schema=c["schema"], cache_system=c["cache_system"]), c["schema"], c["tag"], c["thinking"])
            for c in calls]


def _answer_v22(r: RelationV22 | None) -> dict | None:
    return None if r is None else {"a": r.a, "b": r.b, "relation": r.relation, "confidence": r.confidence,
                                   "rationale": r.rationale}


def score_pairs_v22(llm: LLM, claims: ClaimList, pairs: list[tuple[int, int]], *, tag: str, world_knowledge: bool,
                    bypass_cache: bool = False, concurrency: int | None = None
                    ) -> tuple[RelationListV22, int, list[dict]]:
    """Rev. 2.2 (§4.1): one call per pair, at most ``concurrency`` (default cfg.llm_concurrency) at a time. An answer
    whose rationale is malformed (JSON_FRAGMENT) or that is not for the pair asked about is scored once more, with
    the same request under its own cache key (attempt 2); if that answer is malformed or off the pair too, the pair
    is unscored. Returns the relations in pair order, the number of answers for another pair, and one record per
    re-scored pair with both answers, the reason and the outcome ("replaced" or "unscored")."""
    wanted = [tuple(sorted(p)) for p in pairs]
    stem = _relate_stem(tag, world_knowledge)
    limit = llm.cfg.llm_concurrency if concurrency is None else concurrency

    def ask(pair, attempt):
        return llm.parse(**_relate_pair_call(llm, claims, pair, tag=_pair_tag(stem, pair, attempt > 1),
                                             world_knowledge=world_knowledge, bypass_cache=bypass_cache,
                                             attempt=attempt))

    def problem(pair, r: RelationV22) -> str | None:
        if tuple(sorted((r.a, r.b))) != pair:
            return "other pair"
        return "malformed" if malformed_rationale(r.rationale) else None

    got: dict[tuple[int, int], RelationV22] = {}
    retry = []
    off_pair = 0
    for pair, r in zip(wanted, run_concurrently(lambda p: ask(p, 1), wanted, limit)):
        why = problem(pair, r)
        off_pair += why == "other pair"
        if why is None:
            got[pair] = r.model_copy(update={"a": pair[0], "b": pair[1]})
        else:
            retry.append((pair, r, why))
    rescores = []
    for (pair, first, why), again in zip(retry, run_concurrently(lambda x: ask(x[0], 2), retry, limit)):
        second_problem = problem(pair, again)
        off_pair += second_problem == "other pair"
        if second_problem is None:
            got[pair] = again.model_copy(update={"a": pair[0], "b": pair[1]})
        rescores.append({"a": pair[0], "b": pair[1], "reason": why, "first": _answer_v22(first),
                         "second": _answer_v22(again),
                         "outcome": "replaced" if second_problem is None else "unscored"})
    return RelationListV22(relations=[got[p] for p in wanted if p in got]), off_pair, rescores


def inventory_ids(inventory: InventoryV22) -> tuple[dict[str, list[str]], dict[str, AttributeV22]]:
    """The inventory's entities (id -> mentions) and attributes (key -> its first declaration), ids and keys as the
    entity graph keys them (canonical_key); one that is empty that way is left out."""
    entities: dict[str, list[str]] = {}
    attributes: dict[str, AttributeV22] = {}
    for e in inventory.entities:
        if key := canonical_key(e.id):
            mentions = entities.setdefault(key, [])
            mentions += [m for m in e.mentions if m not in mentions]
    for a in inventory.attributes:
        if key := canonical_key(a.key):
            attributes.setdefault(key, a)
    return entities, attributes


def lexicon_claims(claims: ClaimList) -> list[int]:
    """The claims, of any kind, whose text holds a word or phrase of the comparative lexicon (§5.6)."""
    return [c.id for c in claims.claims if lexicon_words_in(c.text)]


def claims_with_statements(answer: EntityRelationsV22) -> set[int]:
    """The claims an answer covers: those with an order, extreme or same/different statement, or listed in
    unsupported_order_claims (§5.6)."""
    return ({s.claim_id for s in answer.same_different} | {s.claim_id for s in answer.orders}
            | {s.claim_id for s in answer.extremes} | {int(c) for c in answer.unsupported_order_claims})


def extract_entity_steps_v22(llm: LLM, claims: ClaimList, *, tag: str, bypass_cache: bool = False) -> EntityStepsV22:
    """Rev. 2.2's entity extraction (§5.2), each call with adaptive thinking (§5.7): the inventory; the statements,
    under a schema that admits only the inventory's ids and the document's claim ids (§5.3); then the coverage net
    (§5.6): if a claim whose text holds a lexicon word has no statement, one follow-up call lists every such claim,
    and there is no second. A per-document schema the API will not compile is replaced by the same schema with plain
    ids, whose ids the derivation checks, and the call is listed in schema_fallback. With no claims, or an inventory
    with no entity or no attribute, no statement can be made: the later calls are skipped and the lexicon's claims
    stay uncovered."""
    matched = lexicon_claims(claims)
    empty = EntityRelationsV22(same_different=[], orders=[], extremes=[], senses=[], unsupported_order_claims=[])
    if not claims.claims:
        return EntityStepsV22(inventory=InventoryV22(entities=[], attributes=[]), relations=empty, coverage=None,
                              lexicon_matched=[], uncovered=[], schema_fallback=[], skipped="no claims")
    inventory = llm.parse(**_inventory_call(llm, claims, tag=tag, bypass_cache=bypass_cache))
    entities, attributes = inventory_ids(inventory)
    if not entities or not attributes:
        return EntityStepsV22(inventory=inventory, relations=empty, coverage=None, lexicon_matched=matched,
                              uncovered=matched, schema_fallback=[],
                              skipped="the inventory lists no entity or no attribute")
    fallback = []

    def ask(call, step: str):
        try:
            return llm.parse(**call(False))
        except LLMSchemaRejected:
            fallback.append(step)
            return llm.parse(**call(True))

    found = ask(lambda fb: _relations_call(llm, claims, entities, attributes, tag=tag, bypass_cache=bypass_cache,
                                           fallback=fb), "relations")
    relations = EntityRelationsV22.model_validate(found.model_dump())
    uncovered = [c for c in matched if c not in claims_with_statements(relations)]
    coverage = None
    if uncovered:
        found = ask(lambda fb: _coverage_call(llm, claims, uncovered, entities, attributes, tag=tag,
                                              bypass_cache=bypass_cache, fallback=fb), "coverage")
        coverage = EntityCoverageV22.model_validate(found.model_dump())
    return EntityStepsV22(inventory=inventory, relations=relations, coverage=coverage, lexicon_matched=matched,
                          uncovered=uncovered, schema_fallback=fallback)


# ------------------------------------------------------------------------------------------ the signed claim graph
@dataclass
class SignedClaimGraph:
    claims: list[Claim]
    relations: list[Relation]      # every scored relation, unrelated ones included
    graph: XonGraph                # vertices = claims; edges = supports / contradicts relations with weight > 0
    sign: np.ndarray               # (E,) +1 supports, -1 contradicts, aligned with graph.edges
    weight: np.ndarray             # (E,) confidence clipped to [0, 1]
    edge_relation: list[Relation]  # the relation behind each edge
    sheaf: CellularSheaf           # k = 1: F_head = sqrt(w), F_tail = s sqrt(w)
    zero_weight: int = 0           # supports / contradicts relations with confidence 0: no edge (w = 0 adds nothing)
    duplicates: int = 0            # repeated pairs; the first relation is kept
    tension: list = field(default_factory=list)   # rev. 2.2 "tension" relations: reported, no edge

    @property
    def n(self) -> int:
        return len(self.claims)

    @property
    def edges(self) -> np.ndarray:
        return self.graph.edges

    @property
    def kinds(self) -> list[str]:
        return [c.kind for c in self.claims]

    @property
    def premises(self) -> list[int]:
        return [i for i, c in enumerate(self.claims) if c.kind == "premise"]


def build_signed_graph(claims: ClaimList | list[Claim], relations: RelationList | RelationListV22 | list[Relation],
                       seed: int = 0) -> SignedClaimGraph:
    claim_list = list(claims.claims if isinstance(claims, ClaimList) else claims)
    rel_list = list(getattr(relations, "relations", relations))
    n = len(claim_list)
    if [c.id for c in claim_list] != list(range(n)):
        raise ValueError("claim ids must be 0..n-1 in order")
    chosen: dict[tuple[int, int], Relation] = {}
    seen: set[tuple[int, int]] = set()
    tension = []
    zero = duplicates = 0
    for r in rel_list:
        a, b = sorted((int(r.a), int(r.b)))
        if not 0 <= a < b < n:
            raise ValueError(f"relation ({r.a}, {r.b}) does not join two distinct claims")
        if (a, b) in seen:
            duplicates += 1
            continue
        seen.add((a, b))
        if r.relation == "tension":
            tension.append(r)
        if r.relation in NO_EDGE:
            continue
        if float(np.clip(np.nan_to_num(r.confidence), 0.0, 1.0)) <= 0.0:
            zero += 1
            continue
        chosen[(a, b)] = r
    pairs = sorted(chosen)
    edges = np.asarray(pairs, dtype=np.int64).reshape(-1, 2)
    edge_relation = [chosen[p] for p in pairs]
    sign = np.array([1.0 if r.relation == "supports" else -1.0 for r in edge_relation])
    weight = np.array([float(np.clip(np.nan_to_num(r.confidence), 0.0, 1.0)) for r in edge_relation])
    nxg = nx.Graph()
    nxg.add_nodes_from(range(n))
    nxg.add_weighted_edges_from((int(a), int(b), w) for (a, b), w in zip(pairs, weight))
    pos = nx.spring_layout(nxg, seed=seed) if n > 1 else {i: (0.0, 0.0) for i in range(n)}
    coords = np.array([pos[i] for i in range(n)], dtype=float).reshape(n, 2)
    g = graph_from_edges(n, edges, coords=coords, rule="claims")
    if not np.array_equal(g.edges, edges):
        raise AssertionError("claim-graph edges are not in canonical order")
    root = np.sqrt(weight).reshape(-1, 1, 1)
    sheaf = CellularSheaf(1, root.copy(), sign.reshape(-1, 1, 1) * root, g.edges.copy())
    return SignedClaimGraph(claim_list, rel_list, g, sign, weight, edge_relation, sheaf, zero, duplicates, tension)
