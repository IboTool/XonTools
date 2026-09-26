"""Text in, consistency report out: the pipeline behind the Consistency view (XON_A1_CONSISTENCY.md §3, §4, §7).

Re-analysing with more evidence reuses the claims and relations as scored (no LLM call, invariant I2). Relations are
scored again only by re-scoring with world knowledge toggled, which produces a second analysis (the caller keeps
both), and, before any analysis, once for a pair whose rationale is malformed (``claims.JSON_FRAGMENT``).

Two engine versions (XON_A1_REV2_2_PRECISION.md §2): "2.1", the run of record's, unchanged; and "2.2", which reuses
2.1's claims and pair selection (the same requests, so the same cached answers) and scores one pair per call, labels
"tension", derives entity relations from the statements of its entity steps and uses rev. 2.2's threshold. The
version defaults to the config's ``llm_engine_version``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

from ..config import ENGINE_VERSIONS, REV22_ITERATION, relation_threshold
from .claims import (SignedClaimGraph, _score_batches, build_signed_graph, candidate_pairs, extract_claims,
                     extract_entity_relations, extract_entity_steps_v22, score_pairs_v22, text_tag, v22_tag)
from .client import LLM
from .consistency import ConsistencyReport, analyze, report_to_dict
from .entity_consistency import CONFIDENCE_MIN, EntityGraph, build_entity_graph, build_entity_graph_v22
from .schemas import ClaimList, EntityGraphSpec, EntityStepsV22, RelationList, RelationListV22


@dataclass
class Analysis:
    label: str
    text: str
    tag: str
    model: str
    world_knowledge: bool
    evidence: list[int]              # user-marked; the report's clamp_set adds the premises
    claims: ClaimList
    pairs: list[tuple[int, int]]
    pair_info: dict
    relations: RelationList | RelationListV22
    entity_spec: EntityGraphSpec | EntityStepsV22
    graph: SignedClaimGraph
    entities: EntityGraph
    report: ConsistencyReport
    diagnostics: dict = field(default_factory=dict)
    engine_version: str = "2.1"
    threshold: float = CONFIDENCE_MIN


def _diagnostics(claims: ClaimList, pairs, pair_info: dict, relations: RelationList, ignored: int,
                 rescores: list[dict], graph: SignedClaimGraph, entities: EntityGraph) -> dict:
    """pairs_missing: every requested pair without a relation, left out by the model or left unscored after a
    malformed re-score (those are also in pairs_unscored_malformed)."""
    scored = {(r.a, r.b) for r in relations.relations}
    missing = [p for p in pairs if tuple(p) not in scored]
    blind = [tuple(p) for p in pair_info.get("blind", [])]
    related = {(r.a, r.b) for r in relations.relations if r.relation != "unrelated"}
    return {"claims": len(claims.claims), "pairs_requested": len(pairs), "pairs_missing": missing,
            "relations_ignored": ignored, "relations_rescored": rescores,
            "pairs_unscored_malformed": [(r["a"], r["b"]) for r in rescores if r["outcome"] == "unscored"],
            "zero_weight_relations": graph.zero_weight,
            "blind_pairs": len(blind), "blind_pairs_related": sum(p in related for p in blind),
            "entity_relations": len(entities.relations), "entity_relations_dropped": entities.dropped}


def _diagnostics_v22(claims, pairs, pair_info, relations, off_pair, rescores, graph, entities) -> dict:
    """Rev. 2.1's diagnostics (relations_ignored counts answers for another pair than the one asked about), plus the
    tension relations and the entity derivation's record (§5.4)."""
    d = _diagnostics(claims, pairs, pair_info, relations, off_pair, rescores, graph, entities)
    d.update(tension_pairs=[(r.a, r.b) for r in graph.tension], entity_derivation=entities.derivation)
    return d


def _version(llm: LLM, engine_version: str | None) -> str:
    version = llm.cfg.llm_engine_version if engine_version is None else engine_version
    if version not in ENGINE_VERSIONS:
        raise ValueError(f"unknown engine version {version!r}; expected one of {ENGINE_VERSIONS}")
    return version


def _relations(llm: LLM, claims: ClaimList, pairs, *, tag: str, world_knowledge: bool, version: str):
    if version == "2.2":
        return score_pairs_v22(llm, claims, pairs, tag=v22_tag(tag), world_knowledge=world_knowledge)
    return _score_batches(llm, claims, pairs, tag=tag, world_knowledge=world_knowledge)


def analyze_text(llm: LLM, text: str, *, tag: str | None = None, evidence=(), world_knowledge: bool | None = None,
                 seed: int = 0, label: str = "Analysis", engine_version: str | None = None,
                 threshold: float | None = None) -> Analysis:
    """The analysis of a text under an engine version (default: the config's), with that version's verdict
    threshold unless ``threshold`` is given. Rev. 2.2's calls are tagged <tag>-v22-...; its pair sampling is seeded
    as rev. 2.1's, so both versions score the same pairs."""
    tag = tag or text_tag(text)
    version = _version(llm, engine_version)
    wk = llm.cfg.llm_world_knowledge if world_knowledge is None else bool(world_knowledge)
    fixtures = v22_tag(tag) if version == "2.2" else tag
    claims = extract_claims(llm, text, tag=fixtures)
    pairs, pair_info = candidate_pairs(llm, claims, tag=tag, seed=seed, world_knowledge=wk, fixture_tag=fixtures)
    relations, ignored, rescores = _relations(llm, claims, pairs, tag=tag, world_knowledge=wk, version=version)
    graph = build_signed_graph(claims, relations)
    evidence = sorted({int(v) for v in evidence})
    tau = relation_threshold("engine", version) if threshold is None else float(threshold)
    if version == "2.2":
        spec = extract_entity_steps_v22(llm, claims, tag=fixtures)
        entities = build_entity_graph_v22(spec, n_claims=len(claims.claims))
        diagnostics = _diagnostics_v22(claims, pairs, pair_info, relations, ignored, rescores, graph, entities)
    else:
        spec = extract_entity_relations(llm, claims, tag=tag)
        entities = build_entity_graph(spec, n_claims=len(claims.claims))
        diagnostics = _diagnostics(claims, pairs, pair_info, relations, ignored, rescores, graph, entities)
    report = analyze(graph, entities, evidence, llm_usage=llm.usage, threshold=tau, engine_version=version)
    return Analysis(label, text, tag, llm.model, wk, evidence, claims, pairs, pair_info, relations, spec, graph,
                    entities, report, diagnostics, version, tau)


def with_evidence(a: Analysis, evidence, label: str) -> Analysis:
    """The same claims and relations with other user-marked evidence: a new report, no LLM call."""
    evidence = sorted({int(v) for v in evidence})
    report = analyze(a.graph, a.entities, evidence, llm_usage=a.report.llm_usage, threshold=a.threshold,
                     engine_version=a.engine_version)
    return replace(a, label=label, evidence=evidence, report=report)


def rescored(llm: LLM, a: Analysis, world_knowledge: bool, label: str, seed: int = 0,
             tag: str | None = None) -> Analysis:
    """Relations scored again with world knowledge on or off (§7), or with another pair-sampling seed under its own
    fixture tag; claims and entity relations are kept, and so are the engine version and threshold."""
    tag = tag or a.tag
    fixtures = v22_tag(tag) if a.engine_version == "2.2" else tag
    pairs, pair_info = candidate_pairs(llm, a.claims, tag=tag, seed=seed, world_knowledge=world_knowledge,
                                       fixture_tag=fixtures)
    relations, ignored, rescores = _relations(llm, a.claims, pairs, tag=tag, world_knowledge=world_knowledge,
                                              version=a.engine_version)
    graph = build_signed_graph(a.claims, relations)
    report = analyze(graph, a.entities, a.evidence, llm_usage=llm.usage, threshold=a.threshold,
                     engine_version=a.engine_version)
    diagnose = _diagnostics_v22 if a.engine_version == "2.2" else _diagnostics
    return replace(a, label=label, model=llm.model, world_knowledge=world_knowledge, pairs=pairs,
                   pair_info=pair_info, relations=relations, graph=graph, report=report,
                   diagnostics=diagnose(a.claims, pairs, pair_info, relations, ignored, rescores, graph, a.entities))


def analysis_to_dict(a: Analysis) -> dict:
    """The exported report: settings, claims, relations, entity relations and the consistency report."""
    d = {"label": a.label, "engine_version": a.engine_version, "threshold": a.threshold, "model": a.model,
         "world_knowledge": a.world_knowledge, "tag": a.tag, "evidence": a.evidence,
         "claims": [c.model_dump() for c in a.claims.claims],
         "relations": [r.model_dump() for r in a.relations.relations],
         "entity_relations": a.entity_spec.model_dump(), "pair_selection": a.pair_info,
         "diagnostics": a.diagnostics, "report": report_to_dict(a.report)}
    if a.engine_version == "2.2":
        d["iteration"] = REV22_ITERATION
        d["derived_entity_relations"] = [asdict(r) for r in a.entities.relations]
    return d
