"""A1 experiments L1, L1b and L1-var (XON_A1_CONSISTENCY.md §6, rev. 2.1), scored by the rules fixed before any data
(CHANGELOG_EXPERIMENTS.md, A1).

Each corpus document is analysed once per method; the engine and the pairwise baseline share the claims and the
relations. An analysis becomes a JSON row (``document_row``) and every score is computed from rows alone, so a
results file can be scored again without any LLM call.

Matching rules: a claim is a planted claim when its verbatim span, after whitespace normalization, lies inside the
planted sentence or contains it; LLM-direct's cited sentences are mapped the same way. A planted relation counts as
extracted when an entity relation stated by a claim matched to the planted sentence has the planted kind and the
planted entities (by id or mention, case-insensitively), in the planted direction for "greater"; rank phrasings
("finished ahead of") are not covered by the extraction prompt's direction rule, so either direction counts when all
of the document's found rank relations share one.

The minimal engine (XON_A1_MINIMAL_ENGINE.md §4) is scored next to the full engine on the same rows, report-only:
it adds no pass or fail and does not enter the full engine's L1 verdict.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from ..config import LLM_MODELS
from .baselines import DirectResult, llm_direct, pairwise_only
from .claims import ALL_PAIRS_MAX, _score_batches, build_signed_graph, extract_entity_relations, text_tag
from .client import API_KEY_ENV, LLM, LLMError
from .consistency import CULPRIT_K, ConsistencyReport, analyze
from .corpus import CYCLE_TYPES, N_BASE, VARIANTS, normalize_ws
from .engine import Analysis, analyze_text, rescored
from .entity_consistency import EntityGraph, build_entity_graph, canonical_key
from .minimal import MinimalReport, analyze_minimal, minimal_report_to_dict
from .schemas import ClaimList

RECORD_MODEL = LLM_MODELS[0]
SEEDS = (0, 1, 2)            # pair-sampling seeds for documents with more than ALL_PAIRS_MAX claims; 0 is of record
REPEATS = 3                  # L1-var
METHODS = ("engine", "pairwise", "direct_thinking", "direct_no_thinking")
LOCALIZING = ("engine", "direct_thinking", "direct_no_thinking")
# Pre-registered (§6); the pass is judged on the engine and only on the run of record.
L1_PASS = {"direct_f1": 0.85, "cycle_f1": 0.75, "localization": 0.7}
L1_EXPECTED = {"direct_f1": 0.85, "pairwise_cycle_f1_below": 0.5}
L1B_PASS = {"auc": 0.9, "premise_top3": 0.7}
# The user's stop rule (CHANGELOG, A1 re-spec 15): if more than this fraction of the pairs requested at seed 0 is left
# unscored, the eval stops and reports before L1 and L1b are scored.
UNSCORED_MAX = 0.01
# XON_A1_MINIMAL_ENGINE.md §4, stated in advance: the minimal and full verdicts agree on at least this fraction of the
# documents. Report-only: a prediction, not a criterion.
MINIMAL_AGREEMENT = 0.98


# ------------------------------------------------------------------------------------------ matching
def span_matches(span: str, sentence: str) -> bool:
    s, p = normalize_ws(span), normalize_ws(sentence)
    return bool(s) and bool(p) and (s in p or p in s)


def sentence_map(claims: ClaimList, sentences: list[str]) -> dict[int, set[int]]:
    """Claim id -> the indices of the sentences its span matches."""
    return {c.id: {k for k, s in enumerate(sentences) if span_matches(c.span, s)} for c in claims.claims}


def planted_pairs(cmap: dict[int, set[int]]) -> list[tuple[int, int]]:
    """Claim pairs whose two claims match two different planted sentences."""
    ids = sorted(cmap)
    return [(i, j) for k, i in enumerate(ids) for j in ids[k + 1:] if any(p != q for p in cmap[i] for q in cmap[j])]


def engine_localizes(report: ConsistencyReport, cmap: dict[int, set[int]]) -> bool:
    """A reported contradiction (an entity cycle, the frustrated claim cycle, or the top-3 culprits) holds claims
    matched to at least two planted sentences."""
    groups = [c.claim_ids for c in report.entity_contradictions]
    groups += [report.frustrated_cycle] if report.frustrated_cycle else []
    groups.append([c for c, _, _ in report.culprits[:CULPRIT_K]])
    return any(len(set().union(*(cmap.get(i, set()) for i in g))) >= 2 for g in groups)


def minimal_localizes(report: MinimalReport, cmap: dict[int, set[int]]) -> bool:
    """A reported contradiction (a direct pair or an entity contradiction's claims) holds claims matched to at least
    two planted sentences."""
    groups = [list(p) for p in report.direct_contradictions] + [c.claim_ids for c in report.entity_contradictions]
    return any(len(set().union(*(cmap.get(i, set()) for i in g))) >= 2 for g in groups)


def direct_localizes(result: DirectResult, planted: list[str]) -> bool:
    """A listed contradiction cites at least two planted sentences."""
    return any(len({k for s in con.sentences for k, p in enumerate(planted) if span_matches(s, p)}) >= 2
               for con in result.contradictions)


def _is(eg: EntityGraph, entity: str, name: str) -> bool:
    key = canonical_key(name)
    return entity == key or any(canonical_key(m) == key for m in eg.mentions.get(entity, ()))


def matched_relations(rel: dict, claims: ClaimList, eg: EntityGraph) -> list[tuple[str, str]]:
    """(attribute, orientation) of each normalized entity relation stating the planted relation: its claim matches
    the planted sentence and it has the planted kind and entities. "reverse" is a greater relation with the entities
    swapped; same and different relations are unordered."""
    ids = {c.id for c in claims.claims if span_matches(c.span, rel["sentence"])}
    out = []
    for r in eg.relations:
        if r.claim_id not in ids or r.kind != rel["kind"]:
            continue
        fwd = _is(eg, r.a, rel["a"]) and _is(eg, r.b, rel["b"])
        rev = _is(eg, r.a, rel["b"]) and _is(eg, r.b, rel["a"])
        if fwd or (rev and rel["kind"] != "greater"):
            out.append((r.attribute, "forward"))
        elif rev:
            out.append((r.attribute, "reverse"))
    return out


def relations_extracted(relations: list[dict], claims: ClaimList, eg: EntityGraph) -> list[bool]:
    orient = []
    for rel in relations:
        found = {o for _, o in matched_relations(rel, claims, eg)}
        orient.append(("forward" if "forward" in found else "reverse") if found else None)
    free = {o for rel, o in zip(relations, orient) if rel["direction"] == "either" and o}
    return [o == "forward" or (o == "reverse" and rel["direction"] == "either" and len(free) == 1)
            for rel, o in zip(relations, orient)]


def arity_read(relations: list[dict], claims: ClaimList, eg: EntityGraph) -> str:
    """The arity the engine gave the attribute of the entity relations matched to the planted relations (the most
    common attribute; "missing" if none matched)."""
    keys = [att for rel in relations for att, _ in matched_relations(rel, claims, eg)]
    return eg.arity_of(Counter(keys).most_common(1)[0][0]) if keys else "missing"


# ------------------------------------------------------------------------------------------ running
@dataclass
class DocRun:
    record: dict
    analyses: dict[int, Analysis]          # by seed; seeds other than 0 only when the pairs were sampled
    direct: dict[bool, DirectResult]       # LLM-direct with thinking (of record) and without


def run_document(llm: LLM, record: dict) -> DocRun:
    text = record["text"]
    tag = text_tag(text)
    a = analyze_text(llm, text, tag=tag, seed=SEEDS[0], label=record["doc_id"], engine_version="2.1")
    analyses = {SEEDS[0]: a}
    if len(a.claims.claims) > ALL_PAIRS_MAX:
        for s in SEEDS[1:]:
            analyses[s] = rescored(llm, a, a.world_knowledge, label=f"{record['doc_id']} seed {s}", seed=s,
                                   tag=f"{tag}-seed{s}")
    return DocRun(record, analyses, {t: llm_direct(llm, text, tag=tag, thinking=t) for t in (True, False)})


def run_corpus(llm: LLM, records: list[dict], log=print) -> list[DocRun]:
    """Every method on every document. An LLM error stops the run (the completed calls stay cached)."""
    runs = []
    for k, rec in enumerate(records, start=1):
        try:
            runs.append(run_document(llm, rec))
        except LLMError as exc:
            exc.add_note(f"While analysing corpus document {rec['doc_id']} ({k} of {len(records)}).")
            raise
        log(f"{rec['doc_id']} ({k}/{len(records)}): {llm.usage['spent_tokens']:,} tokens spent")
    return runs


def document_row(run: DocRun) -> dict:
    rec, a = run.record, run.analyses[SEEDS[0]]
    rep, planted = a.report, rec["planted"]
    cmap = sentence_map(a.claims, planted)
    by_seed = [run.analyses.get(s, a) for s in SEEDS]
    minimal = [analyze_minimal(s.claims, s.relations, s.entity_spec, unscored_pairs=len(s.diagnostics["pairs_missing"]))
               for s in by_seed]
    premise_top3 = None
    if rec["variant"] == "direct" and rec["premise_contradicted"]:
        ids = {c.id for c in a.claims.claims if any(span_matches(c.span, p) for p in rec["premises"])}
        premise_top3 = bool(ids.intersection(rep.residual_ranking[:3]))
    labels = {(r.a, r.b): r for r in a.relations.relations}
    planted_claims = {c for c, ks in cmap.items() if ks}
    return {"doc_id": rec["doc_id"], "base": rec["base"], "variant": rec["variant"], "cycle_type": rec["cycle_type"],
            "premise_contradicted": rec["premise_contradicted"], "n_claims": len(a.claims.claims),
            "sampled": len(run.analyses) > 1,
            "verdict": {"engine": [s.report.verdict_inconsistent for s in by_seed],
                        "pairwise": [pairwise_only(s.graph)[0] for s in by_seed],
                        "direct_thinking": run.direct[True].inconsistent,
                        "direct_no_thinking": run.direct[False].inconsistent},
            "engine_clauses": list(rep.verdict_clauses),
            "localized": {"engine": [engine_localizes(s.report, cmap) for s in by_seed],
                          "direct_thinking": direct_localizes(run.direct[True], planted),
                          "direct_no_thinking": direct_localizes(run.direct[False], planted)},
            "minimal": {"verdict": [m.verdict_inconsistent for m in minimal], "clauses": list(minimal[0].verdict_clauses),
                        "localized": [minimal_localizes(m, cmap) for m in minimal],
                        "report": minimal_report_to_dict(minimal[0])},
            "planted_found": [any(k in ks for ks in cmap.values()) for k in range(len(planted))],
            "relations_found": relations_extracted(rec["relations"], a.claims, a.entities),
            "arity": arity_read(rec["relations"], a.claims, a.entities),
            "harmony": rep.harmony, "harmony_reason": rep.harmony_reason, "conflict": rep.conflict,
            "unanchored": bool(rep.unanchored_components), "premise_top3": premise_top3,
            "planted_pair_relations": [[i, j, labels[(i, j)].relation, labels[(i, j)].confidence] if (i, j) in labels
                                       else [i, j, None, None] for i, j in planted_pairs(cmap)],
            "unscored_pairs": [len(s.diagnostics["pairs_missing"]) for s in by_seed],
            "unscored_malformed": [len(s.diagnostics["pairs_unscored_malformed"]) for s in by_seed],
            "unscored_planted": any(i in planted_claims or j in planted_claims
                                    for i, j in a.diagnostics["pairs_missing"]),
            "diagnostics": {k: len(v) if isinstance(v, list) else v for k, v in a.diagnostics.items()}}


def run_l1var(llm: LLM, runs: list[DocRun], *, repeats: int = REPEATS, log=print, raw_dir=None) -> list[dict]:
    """Relations, entity relations and LLM-direct again, `repeats` times with the cache bypassed, on the claims and
    pairs of the run of record. Repeats get their own fixture tags, so a recording session keeps the run of record's.
    With `raw_dir`, every response is saved there (`l1var_raw.RawSaver`), so `replay_l1var` can recompute the rows."""
    from .l1var_raw import RawSaver
    if llm.dry_run:
        raise LLMError(f"L1-var measures how repeated live calls differ, so it cannot run in dry-run mode ({API_KEY_ENV} "
                       "is not set in the environment).")
    with RawSaver(llm, raw_dir) as saver:
        return _l1var_rows(llm, runs, repeats, log, saver)


def _l1var_rows(llm: LLM, runs: list[DocRun], repeats: int, log, saver) -> list[dict]:
    rows = []
    for run in runs:
        a = run.analyses[SEEDS[0]]
        for k in range(1, repeats + 1):
            saver.at(run.record["doc_id"], k)
            tag = f"{a.tag}-var{k}"
            relations, _, _ = _score_batches(llm, a.claims, a.pairs, tag=tag, world_knowledge=a.world_knowledge,
                                             bypass_cache=True)
            eg = build_entity_graph(extract_entity_relations(llm, a.claims, tag=tag, bypass_cache=True),
                                    n_claims=len(a.claims.claims))
            graph = build_signed_graph(a.claims, relations)
            report = analyze(graph, eg, a.evidence)
            direct = {t: llm_direct(llm, a.text, tag=tag, thinking=t, bypass_cache=True) for t in (True, False)}
            rows.append({"doc_id": run.record["doc_id"], "repeat": k,
                         "relations": {f"{r.a}-{r.b}": r.relation for r in relations.relations},
                         "entity_relations": sorted({_entity_key(r) for r in eg.relations}),
                         "verdict": {"engine": report.verdict_inconsistent, "pairwise": pairwise_only(graph)[0],
                                     "direct_thinking": direct[True].inconsistent,
                                     "direct_no_thinking": direct[False].inconsistent}})
        log(f"L1-var {run.record['doc_id']}: {llm.usage['spent_tokens']:,} tokens spent")
    return rows


def replay_l1var(runs: list[DocRun], raw_dir, *, cache_dir, repeats: int = REPEATS, log=print) -> list[dict]:
    """L1-var's rows recomputed from the responses `run_l1var` saved in `raw_dir`, with no API calls: the same requests
    are made and each is answered by its saved response, in call order. Every saved response must be used."""
    from .l1var_raw import RawSaver, SavedResponses
    client = SavedResponses(raw_dir)
    if len(client.models) != 1:
        raise LLMError(f"The saved L1-var responses come from more than one model: {sorted(client.models)}.")
    llm = LLM(cache_dir=cache_dir, client=client, fixture_dir=Path(cache_dir) / "fixtures", model=next(iter(client.models)),
              budget_tokens=10**15)
    rows = _l1var_rows(llm, runs, repeats, log, RawSaver(llm, None))
    if client.left_over():
        raise LLMError(f"{client.left_over()} saved L1-var responses were not asked for when recomputing.")
    return rows


def _entity_key(r) -> str:
    a, b = (r.a, r.b) if r.kind == "greater" else sorted((r.a, r.b))
    return f"{r.claim_id}:{r.kind}:{a}:{b}"


# ------------------------------------------------------------------------------------------ scores
def rate(values: list[bool]) -> float | None:
    return sum(map(bool, values)) / len(values) if values else None


def prf(pred: list[bool], truth: list[bool]) -> dict:
    tp = sum(p and t for p, t in zip(pred, truth))
    fp = sum(p and not t for p, t in zip(pred, truth))
    fn = sum(t and not p for p, t in zip(pred, truth))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"n": len(truth), "tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def auc(pos: list[float], neg: list[float]) -> float | None:
    """P(a positive scores above a negative), ties counting one half."""
    if not pos or not neg:
        return None
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def _at(value, seed: int = 0):
    return value[seed] if isinstance(value, list) else value


def _f1(rows: list[dict], planted_variant: str, method: str, seed: int = 0, cycle_type: str | None = None) -> dict:
    pop = [r for r in rows if r["variant"] in ("consistent", planted_variant)
           and (cycle_type is None or r["cycle_type"] == cycle_type)]
    return prf([_at(r["verdict"][method], seed) for r in pop], [r["variant"] == planted_variant for r in pop])


def of_record(rows: list[dict], model: str, subset: bool) -> tuple[bool, str | None]:
    """Whether a run is the run of record, and why not."""
    if subset:
        return False, "the 12-document subset"
    if model != RECORD_MODEL:
        return False, f"model {model} (the model of record is {RECORD_MODEL})"
    if Counter(r["variant"] for r in rows) != {v: N_BASE for v in VARIANTS}:
        return False, f"{len(rows)} documents, not the full corpus"
    return True, None


def _contamination(rows: list[dict]) -> dict:
    pairs = [p for r in rows for p in r["planted_pair_relations"]]
    scored = [p for p in pairs if p[2] is not None]
    hits = sum(p[2] == "contradicts" for p in scored)
    return {"pairs": len(pairs), "scored": len(scored), "unscored": len(pairs) - len(scored), "contradicts": hits,
            "rate": hits / len(scored) if scored else None}


def contamination(rows: list[dict]) -> dict:
    """Cycle variants, seed 0: of the scored claim pairs whose claims match two different planted sentences (pairwise
    compatible by construction), the fraction labeled contradicts, at any confidence; overall and per cycle type."""
    cycles = [r for r in rows if r["variant"] == "cycle"]
    return {**_contamination(cycles),
            "by_type": {t: _contamination([r for r in cycles if r["cycle_type"] == t]) for t in CYCLE_TYPES}}


def _attribution(rows: list[dict]) -> dict:
    hits = [r["engine_clauses"] for r in rows if _at(r["verdict"]["engine"])]
    return {"detections": len(hits), "entity_alone": sum(c == ["entity"] for c in hits),
            "entity_with_direct_or_balance": sum("entity" in c and len(c) > 1 for c in hits),
            "direct_or_balance_without_entity": sum("entity" not in c for c in hits),
            "combinations": dict(Counter("+".join(c) for c in hits))}


def clause_attribution(rows: list[dict]) -> dict:
    """The engine's detections on cycle variants at seed 0, by the verdict clauses that fired; overall and per cycle
    type."""
    cycles = [r for r in rows if r["variant"] == "cycle"]
    return {**_attribution(cycles),
            "by_type": {t: _attribution([r for r in cycles if r["cycle_type"] == t]) for t in CYCLE_TYPES}}


def unscored_report(rows: list[dict]) -> dict:
    """Requested pairs with no relation at seed 0, left out by the model or unscored after a malformed re-score, per
    document and pooled, with the stop rule (UNSCORED_MAX). Seeds 1 and 2 are summed over the sampled documents."""
    requested = sum(r["diagnostics"]["pairs_requested"] for r in rows)
    unscored = sum(r["unscored_pairs"][0] for r in rows)
    malformed = sum(r["unscored_malformed"][0] for r in rows)
    fraction = unscored / requested if requested else 0.0
    return {"pairs_requested": requested, "unscored": unscored, "unscored_malformed": malformed,
            "left_out_by_model": unscored - malformed,
            "relations_rescored": sum(r["diagnostics"]["relations_rescored"] for r in rows),
            "fraction": fraction, "limit": UNSCORED_MAX, "stop": fraction > UNSCORED_MAX,
            "sampled_by_seed": {str(s): sum(r["unscored_pairs"][k] for r in rows if r["sampled"])
                                for k, s in enumerate(SEEDS)},
            "documents_with_planted_unscored": sum(r["unscored_planted"] for r in rows),
            "documents": [{"doc_id": r["doc_id"], "unscored": r["unscored_pairs"][0],
                           "unscored_malformed": r["unscored_malformed"][0], "planted_involved": r["unscored_planted"]}
                          for r in rows if r["unscored_pairs"][0]]}


def _scores_of(rows: list[dict], verdict, localized) -> dict:
    consistent = [r for r in rows if r["variant"] == "consistent"]

    def f1(planted_variant: str, cycle_type: str | None = None) -> dict:
        pop = [r for r in rows if r["variant"] in ("consistent", planted_variant)
               and (cycle_type is None or r["cycle_type"] == cycle_type)]
        return prf([verdict(r) for r in pop], [r["variant"] == planted_variant for r in pop])

    return {"direct": f1("direct"), "cycle": f1("cycle"), "cycle_by_type": {t: f1("cycle", t) for t in CYCLE_TYPES},
            "false_positive_rate": rate([verdict(r) for r in consistent]),
            "binary_control_false_positive_rate": rate([verdict(r) for r in consistent
                                                        if r["cycle_type"] == "binary_parity"]),
            "localization": rate([localized(r) for r in rows if r["variant"] == "cycle"])}


def score_minimal(rows: list[dict]) -> dict:
    """XON_A1_MINIMAL_ENGINE.md §4, report-only, seed 0: the minimal engine's scores next to the full engine's on the
    same rows, and every document where the two verdicts differ, with the clauses that fired in each. The predicted
    kind of disagreement is the full engine's clause (b) firing without (a) or (c). Any other kind, or a document
    where the minimal engine's clauses are not the full engine's (a) and (c), points to a bug in one of the two."""
    disagreements, mismatches = [], []
    for r in rows:
        full, minimal = r["engine_clauses"], r["minimal"]["clauses"]
        entry = {"doc_id": r["doc_id"], "variant": r["variant"], "cycle_type": r["cycle_type"], "full_clauses": full,
                 "minimal_clauses": minimal}
        if [c for c in full if c != "claim_balance"] != minimal:
            mismatches.append(entry)
        if _at(r["verdict"]["engine"]) != r["minimal"]["verdict"][0]:
            disagreements.append({**entry, "predicted": full == ["claim_balance"] and not minimal})
    agreement = 1 - len(disagreements) / len(rows) if rows else None
    predicted = all(d["predicted"] for d in disagreements)
    met = agreement is not None and agreement >= MINIMAL_AGREEMENT
    return {"report_only": True, "documents": len(rows),
            "methods": {"minimal": _scores_of(rows, lambda r: r["minimal"]["verdict"][0],
                                              lambda r: r["minimal"]["localized"][0]),
                        "full": _scores_of(rows, lambda r: _at(r["verdict"]["engine"]),
                                           lambda r: _at(r["localized"]["engine"]))},
            "agreement": agreement, "disagreements": disagreements, "clause_mismatches": mismatches,
            "prediction": {"agreement_at_least": MINIMAL_AGREEMENT, "agreement_met": met,
                           "all_disagreements_predicted": predicted, "held": met and predicted},
            "investigate": bool(mismatches) or not predicted}


def score_l1(rows: list[dict], judged: bool = True) -> dict:
    """Direct F1 on consistent + direct variants; cycle F1 on consistent + cycle, overall and per cycle type (matched
    controls); false-positive rate on consistent variants; localization on cycle variants; seed 0 of record."""
    consistent = [r for r in rows if r["variant"] == "consistent"]
    cycles = [r for r in rows if r["variant"] == "cycle"]
    methods = {m: {"direct": _f1(rows, "direct", m), "cycle": _f1(rows, "cycle", m),
                   "cycle_by_type": {t: _f1(rows, "cycle", m, cycle_type=t) for t in CYCLE_TYPES},
                   "false_positive_rate": rate([_at(r["verdict"][m]) for r in consistent])} for m in METHODS}
    localization = {m: rate([_at(r["localized"][m]) for r in cycles]) for m in LOCALIZING}
    spread = {m: {str(s): {"direct_f1": _f1(rows, "direct", m, s)["f1"], "cycle_f1": _f1(rows, "cycle", m, s)["f1"]}
                  for s in SEEDS} for m in ("engine", "pairwise")}
    spread["engine_localization"] = {str(s): rate([r["localized"]["engine"][s] for r in cycles]) for s in SEEDS}
    binary = [r for r in rows if r["cycle_type"] == "binary_parity" and r["variant"] in ("consistent", "cycle")]
    controls = [r for r in binary if r["variant"] == "consistent"]
    diagnostics = {
        "planted_sentences_extracted": rate([x for r in rows if r["variant"] != "consistent"
                                             for x in r["planted_found"]]),
        "planted_relations_extracted": rate([x for r in cycles for x in r["relations_found"]]),
        "planted_relations_extracted_by_type": {t: rate([x for r in cycles if r["cycle_type"] == t
                                                         for x in r["relations_found"]]) for t in CYCLE_TYPES},
        "arity_accuracy": rate([r["arity"] == ("binary" if r["variant"] == "cycle" else "multi") for r in binary]),
        "arity_read": {v: dict(Counter(r["arity"] for r in binary if r["variant"] == v)) for v in ("cycle", "consistent")},
        "binary_control_false_positive_rate": {m: rate([_at(r["verdict"][m]) for r in controls]) for m in METHODS},
        "documents_sampled": sum(r["sampled"] for r in rows),
        "claims_mean": sum(r["n_claims"] for r in rows) / len(rows) if rows else None,
        "claims_max": max((r["n_claims"] for r in rows), default=None),
        "pairs_missing": sum(r["diagnostics"].get("pairs_missing", 0) for r in rows),
        "relations_ignored": sum(r["diagnostics"].get("relations_ignored", 0) for r in rows),
        "entity_relations_dropped": sum(r["diagnostics"].get("entity_relations_dropped", 0) for r in rows),
        "contamination": contamination(rows), "clause_attribution": clause_attribution(rows),
        "unscored": unscored_report(rows)}
    engine = methods["engine"]
    checks = {"direct_f1": engine["direct"]["f1"] >= L1_PASS["direct_f1"],
              "cycle_f1": engine["cycle"]["f1"] >= L1_PASS["cycle_f1"],
              "localization": (localization["engine"] or 0.0) >= L1_PASS["localization"]}
    expected = {"direct_f1_at_least": {m: methods[m]["direct"]["f1"] >= L1_EXPECTED["direct_f1"] for m in METHODS},
                "pairwise_cycle_f1_below": methods["pairwise"]["cycle"]["f1"] < L1_EXPECTED["pairwise_cycle_f1_below"]}
    return {"documents": dict(Counter(r["variant"] for r in rows)), "methods": methods, "localization": localization,
            "seed_spread": spread, "diagnostics": diagnostics, "judged": judged, "checks": checks,
            "passed": all(checks.values()) if judged else None, "expected": expected, "minimal": score_minimal(rows)}


def score_l1b(rows: list[dict], judged: bool = True) -> dict:
    """Consistent and direct variants, premises clamped; documents with H = None are left out and counted."""
    docs = [r for r in rows if r["variant"] in ("consistent", "direct")]
    kept = [r for r in docs if r["harmony"] is not None]
    pos = [r for r in kept if r["variant"] == "direct"]
    neg = [r for r in kept if r["variant"] == "consistent"]
    auc_h = auc([1 - r["harmony"] for r in pos], [1 - r["harmony"] for r in neg])
    auc_conflict = auc([r["conflict"] for r in pos], [r["conflict"] for r in neg])
    top3 = rate([r["premise_top3"] for r in pos if r["premise_contradicted"]])
    checks = {"auc": auc_h is not None and auc_h >= L1B_PASS["auc"],
              "auc_at_least_conflict": auc_h is not None and auc_conflict is not None and auc_h >= auc_conflict,
              "premise_top3": top3 is not None and top3 >= L1B_PASS["premise_top3"]}
    return {"documents": len(docs), "kept": {"consistent": len(neg), "direct": len(pos)},
            "left_out_harmony_none": {v: sum(r["variant"] == v and r["harmony"] is None for r in docs)
                                      for v in ("consistent", "direct")},
            "auc_harmony": auc_h, "auc_conflict": auc_conflict, "premise_top3": top3,
            "premise_documents": sum(r["premise_contradicted"] for r in pos),
            "unanchored_fraction": rate([r["unanchored"] for r in docs]), "judged": judged, "checks": checks,
            "passed": all(checks.values()) if judged else None}


def score_l1var(rows: list[dict]) -> dict:
    """Agreement across the repeats: a scored pair agrees when its label is the same in every repeat (a missing
    label counts as a label); an entity relation agrees when every repeat has it; a verdict changes when the repeats
    differ. No pass or fail (§6)."""
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_doc[r["doc_id"]].append(r)
    pairs, entities, changes = [], [], {m: [] for m in METHODS}
    for reps in by_doc.values():
        for p in set().union(*(r["relations"] for r in reps)):
            pairs.append(len({r["relations"].get(p, "missing") for r in reps}) == 1)
        for e in set().union(*(r["entity_relations"] for r in reps)):
            entities.append(all(e in r["entity_relations"] for r in reps))
        for m in METHODS:
            changes[m].append(len({r["verdict"][m] for r in reps}) > 1)
    return {"documents": len(by_doc), "repeats": max((len(v) for v in by_doc.values()), default=0),
            "pairs": len(pairs), "relation_agreement": rate(pairs), "entity_relations": len(entities),
            "entity_agreement": rate(entities), "verdict_change_rate": {m: rate(changes[m]) for m in METHODS}}


# ------------------------------------------------------------------------------------------ tables
NAMES = {"engine": "Engine", "pairwise": "Pairwise only", "direct_thinking": "LLM-direct (thinking)",
         "direct_no_thinking": "LLM-direct (no thinking)"}


def _n(x, digits: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def _counts(d: dict) -> str:
    return ", ".join(f"{n} {k}" for k, n in d.items()) or "none"


def _verdict(res: dict, why_not: str | None) -> str:
    if not res["judged"]:
        return f"not judged ({why_not or 'not the run of record'})"
    return "PASS" if res["passed"] else "FAIL"


def l1_markdown(res: dict, why_not: str | None = None) -> str:
    lines = ["### L1", "", f"Documents: {_counts(res['documents'])}.", "",
             "| Method | Direct P | Direct R | Direct F1 | Cycle P | Cycle R | Cycle F1 | "
             + " | ".join(f"{t} F1" for t in CYCLE_TYPES) + " | False-positive rate |",
             "|---" * (8 + len(CYCLE_TYPES)) + "|"]
    for m, v in res["methods"].items():
        d, c = v["direct"], v["cycle"]
        lines.append(f"| {NAMES[m]} | {_n(d['precision'])} | {_n(d['recall'])} | {_n(d['f1'])} | "
                     f"{_n(c['precision'])} | {_n(c['recall'])} | {_n(c['f1'])} | "
                     + " | ".join(_n(v["cycle_by_type"][t]["f1"]) for t in CYCLE_TYPES)
                     + f" | {_n(v['false_positive_rate'])} |")
    loc, dg, chk = res["localization"], res["diagnostics"], res["checks"]
    lines += ["", "Localization hit rate on cycle variants: "
              + ", ".join(f"{NAMES[m]} {_n(loc[m])}" for m in LOCALIZING) + ".", "",
              f"Pass (engine; direct F1 >= {L1_PASS['direct_f1']}, cycle F1 >= {L1_PASS['cycle_f1']}, localization "
              f">= {L1_PASS['localization']}): {_verdict(res, why_not)}. Checks: "
              + ", ".join(f"{k} {'met' if ok else 'not met'}" for k, ok in chk.items()) + ".",
              "Expected (not judged): direct F1 >= 0.85 for "
              + ", ".join(f"{NAMES[m]} {'yes' if ok else 'no'}" for m, ok in res["expected"]["direct_f1_at_least"].items())
              + f"; pairwise cycle F1 below 0.5: {'yes' if res['expected']['pairwise_cycle_f1_below'] else 'no'}.", "",
              f"Seed spread ({dg['documents_sampled']} documents with sampled pairs): "
              + "; ".join(f"{NAMES[m]} direct F1 " + "/".join(_n(res["seed_spread"][m][str(s)]["direct_f1"])
                                                             for s in SEEDS)
                          + ", cycle F1 " + "/".join(_n(res["seed_spread"][m][str(s)]["cycle_f1"]) for s in SEEDS)
                          for m in ("engine", "pairwise"))
              + "; engine localization " + "/".join(_n(res["seed_spread"]["engine_localization"][str(s)])
                                                   for s in SEEDS) + " (seeds 0/1/2).", "",
              f"Diagnostics: planted sentences extracted {_n(dg['planted_sentences_extracted'])}; planted relations "
              f"extracted {_n(dg['planted_relations_extracted'])} ("
              + ", ".join(f"{t} {_n(x)}" for t, x in dg["planted_relations_extracted_by_type"].items())
              + f"); arity accuracy {_n(dg['arity_accuracy'])} (read on binary cycle variants: "
              f"{_counts(dg['arity_read']['cycle'])}; on their controls: {_counts(dg['arity_read']['consistent'])}); "
              "false-positive rate on the binary \"three values\" "
              "controls: " + ", ".join(f"{NAMES[m]} {_n(x)}" for m, x in dg["binary_control_false_positive_rate"].items())
              + f". Claims per document: mean {_n(dg['claims_mean'], 1)}, max {dg['claims_max']}. Relations ignored "
              f"{dg['relations_ignored']}, entity relations dropped {dg['entity_relations_dropped']}.", "",
              _relation_scoring_text(dg["contamination"], dg["clause_attribution"]), "",
              _unscored_text(dg["unscored"]), "", minimal_markdown(res["minimal"])]
    return "\n".join(lines)


def _clauses(clauses: list[str]) -> str:
    return "+".join(clauses) or "none"


def minimal_markdown(res: dict) -> str:
    lines = ["#### Minimal engine (XON_A1_MINIMAL_ENGINE.md, Section 4): report-only, no pass or fail", "",
             "Verdict clauses (a) direct and (c) entity only, on the full engine's claims, relations and entity "
             "relations (seed 0). These numbers do not affect the full engine's L1 verdict.", "",
             "| Engine | Direct P | Direct R | Direct F1 | Cycle P | Cycle R | Cycle F1 | "
             + " | ".join(f"{t} F1" for t in CYCLE_TYPES)
             + " | False-positive rate | Binary-control false-positive rate | Localization |",
             "|---" * (10 + len(CYCLE_TYPES)) + "|"]
    for name, key in (("Minimal", "minimal"), ("Full", "full")):
        v = res["methods"][key]
        d, c = v["direct"], v["cycle"]
        lines.append(f"| {name} | {_n(d['precision'])} | {_n(d['recall'])} | {_n(d['f1'])} | "
                     f"{_n(c['precision'])} | {_n(c['recall'])} | {_n(c['f1'])} | "
                     + " | ".join(_n(v["cycle_by_type"][t]["f1"]) for t in CYCLE_TYPES)
                     + f" | {_n(v['false_positive_rate'])} | {_n(v['binary_control_false_positive_rate'])} | "
                     f"{_n(v['localization'])} |")
    p, dis = res["prediction"], res["disagreements"]
    lines += ["", f"Verdicts agree on {res['documents'] - len(dis)} of {res['documents']} documents "
              f"({_n(res['agreement'])}). Prediction, stated in advance: the two verdicts agree on at least "
              f"{p['agreement_at_least']:.0%} of the 180 documents, and every disagreement is a document where the full "
              f"engine's clause (b) fired without clause (a) or (c). Held: {'yes' if p['held'] else 'no'} (agreement "
              f"{'met' if p['agreement_met'] else 'not met'}; disagreements "
              f"{'all' if p['all_disagreements_predicted'] else 'not all'} of the predicted kind).", "",
              "Documents where the verdicts differ: "
              + ("; ".join(f"{d['doc_id']} (full {_clauses(d['full_clauses'])}, minimal {_clauses(d['minimal_clauses'])}"
                           + ("" if d["predicted"] else ", not the predicted kind") + ")" for d in dis) or "none") + "."]
    if res["clause_mismatches"]:
        lines.append("Documents where the minimal engine's clauses are not the full engine's (a) and (c): "
                     + "; ".join(f"{d['doc_id']} (full {_clauses(d['full_clauses'])}, minimal "
                                 f"{_clauses(d['minimal_clauses'])})" for d in res["clause_mismatches"]) + ".")
    if res["investigate"]:
        lines.append("**A disagreement of another kind indicates a bug in one of the two implementations: investigate "
                     "it before these results are interpreted.**")
    return "\n".join(lines)


def _relation_scoring_text(c: dict, att: dict) -> str:
    split = ("entity_alone", "entity_with_direct_or_balance", "direct_or_balance_without_entity")
    return (f"Relation scoring on cycle variants (seed 0): contamination, the planted-cycle claim pairs labeled "
            f"contradicts, {_n(c['rate'])} ({c['contradicts']} of {c['scored']} scored, {c['unscored']} unscored; "
            + ", ".join(f"{t} {_n(v['rate'])}" for t, v in c["by_type"].items())
            + f"). Engine detections by clause: entity clause alone {att['entity_alone']}, entity with direct or "
            f"balance {att['entity_with_direct_or_balance']}, direct or balance without entity "
            f"{att['direct_or_balance_without_entity']}, of {att['detections']} (by type, in that order: "
            + ", ".join(f"{t} " + "/".join(str(v[k]) for k in split) for t, v in att["by_type"].items())
            + f"; clause combinations: {_counts(att['combinations'])}).")


def _unscored_text(u: dict) -> str:
    docs = "; ".join(f"{d['doc_id']} {d['unscored']}"
                     + (f" ({d['unscored_malformed']} after a malformed re-score)" if d["unscored_malformed"] else "")
                     + (", planted claims involved" if d["planted_involved"] else "") for d in u["documents"])
    return (f"Unscored pairs at seed 0: {u['unscored']} of {u['pairs_requested']} requested ({_n(u['fraction'], 4)}; "
            f"the run stops above {u['limit']:.0%}): {u['left_out_by_model']} left out by the model, "
            f"{u['unscored_malformed']} unscored after a malformed re-score. Pairs re-scored for a malformed "
            f"rationale: {u['relations_rescored']}. Unscored on the sampled documents, seeds 0/1/2: "
            + "/".join(str(u["sampled_by_seed"][str(s)]) for s in SEEDS)
            + f". Documents with unscored pairs: {docs or 'none'} ({u['documents_with_planted_unscored']} with planted "
            "claims involved).")


def unscored_markdown(u: dict) -> str:
    """The report printed when the stop rule halts a run before L1 and L1b are scored."""
    return "\n".join(["### Unscored pairs (checked before L1 and L1b are scored)", "", _unscored_text(u), "",
                      f"More than {u['limit']:.0%} of the requested pairs are unscored: the run stopped before L1 and "
                      "L1b were scored. Rerun with --accept-unscored to score them anyway." if u["stop"] else
                      f"At most {u['limit']:.0%} of the requested pairs are unscored."])


def l1b_markdown(res: dict, why_not: str | None = None) -> str:
    return "\n".join([
        "### L1b", "",
        f"Documents: {res['documents']}; kept {_counts(res['kept'])}; left out with H = None "
        f"{_counts(res['left_out_harmony_none'])}.",
        f"AUC of 1 - H: {_n(res['auc_harmony'])}; AUC of the conflict score (sum of lambda_min): "
        f"{_n(res['auc_conflict'])}; premise among the top-3 residual claims: {_n(res['premise_top3'])} "
        f"({res['premise_documents']} documents); documents with unanchored components: "
        f"{_n(res['unanchored_fraction'])}.",
        f"Pass (AUC >= {L1B_PASS['auc']} and >= the conflict score's, premise top-3 >= {L1B_PASS['premise_top3']}): "
        f"{_verdict(res, why_not)}. Checks: "
        + ", ".join(f"{k} {'met' if ok else 'not met'}" for k, ok in res["checks"].items()) + "."])


def l1var_markdown(res: dict) -> str:
    return "\n".join([
        "### L1-var (no pass or fail)", "",
        f"{res['documents']} documents x {res['repeats']} repeats with the cache bypassed. Relation agreement "
        f"{_n(res['relation_agreement'])} over {res['pairs']} pairs; entity-relation agreement "
        f"{_n(res['entity_agreement'])} over {res['entity_relations']} relations. Documents whose verdict changes: "
        + ", ".join(f"{NAMES[m]} {_n(x)}" for m, x in res["verdict_change_rate"].items()) + "."])
