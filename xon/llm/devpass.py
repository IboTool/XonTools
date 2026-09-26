"""A1 rev. 2.2's development pass on the seen L1 corpus (XON_A1_REV2_2_PRECISION.md §6-§8, §8.1).

Claims and pair selections are the run of record's (seed 0, from the cache); relations and entity statements are
new under rev. 2.2; LLM-direct is not run again, its run-of-record verdicts are carried into the rows and marked so.
A document's row holds the verdict of each thresholded method (full engine, minimal engine, pairwise-only) at every
threshold of the grid, so the §6 rule and every §8 diagnostic are computed from rows alone, with no LLM call. Rev.
2.1's rows are computed the same way from the run of record's cache, for its report-only curves and for the
comparisons. Every number here is labeled LABEL.
"""
from __future__ import annotations

import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..config import RELATION_THRESHOLD_V2_1, REV22_ITERATION, THRESHOLD_METHODS
from .baselines import llm_direct, pairwise_only
from .claims import (ALL_PAIRS_MAX, build_signed_graph, candidate_pairs, extract_claims, extract_entity_steps_v22,
                     planned_requests_v22, score_pairs_v22, text_tag, v22_tag)
from .client import LLM, LLMError, cost_usd
from .consistency import analyze
from .corpus import CYCLE_TYPES
from .engine import Analysis, analyze_text
from .entity_consistency import build_entity_graph_v22
from .evaluation import (UNSCORED_MAX, _scores_of, arity_read, clause_attribution, contamination, engine_localizes,
                         minimal_localizes, planted_pairs, rate, relations_extracted, score_l1b, score_minimal,
                         sentence_map, span_matches)
from .minimal import analyze_minimal
from .order_misses import CLASSES, misses, relations_extracted_corrected

LABEL = "rev. 2.2 development pass on the seen L1 corpus; not a result of record"
TAUS = tuple(round(0.5 + 0.05 * k, 2) for k in range(9))      # §6: 0.50, 0.55, ..., 0.90
CARRIED = ("direct_thinking", "direct_no_thinking")            # LLM-direct, from the run of record
CALL_KINDS = ("extract", "pairs", "relate", "entities", "direct")
ENTITY_STEPS = ("inventory", "relations", "coverage")          # rev. 2.2's entity calls (§5.2)
REPEATS = 3


def tau_key(tau: float) -> str:
    return f"{float(tau):.2f}"


# ------------------------------------------------------------------------------------------ running
class CallLog:
    """While active, each call `llm` answers from the API or the cache: its tag, its usage and whether it came from a
    batch. Calls may complete concurrently."""

    def __init__(self, llm: LLM):
        self.llm, self.calls, self._lock = llm, [], threading.Lock()

    def __enter__(self) -> CallLog:
        self._own = "_record" in vars(self.llm)
        self._prev = self.llm._record
        self.llm._record = self._log
        return self

    def __exit__(self, *exc) -> None:
        if self._own:
            self.llm._record = self._prev
        else:
            del self.llm._record

    def _log(self, tag: str, key: str, record: dict) -> None:
        with self._lock:
            self.calls.append({"tag": tag, "usage": dict(record.get("usage") or {}), "batch": "batch_id" in record})
        self._prev(tag, key, record)


def call_kind(tag: str) -> str:
    """extract, pairs, relate (re-scores included), entities or direct, from a call's fixture tag."""
    for kind in ("direct", "entities", "relate", "pairs", "extract"):
        if f"-{kind}" in tag:
            return kind
    raise ValueError(f"unknown call tag {tag!r}")


def entity_step(tag: str) -> str | None:
    """The entity step of a rev. 2.2 entity call's tag (ENTITY_STEPS, its schema fallback included), else None."""
    m = re.search(r"-entities-(inventory|relations|coverage)(?:-fallback)?$", tag)
    return m.group(1) if m else None


def cost_of(calls: list[dict], model: str) -> dict:
    """Tokens and dollars per call kind, and per entity step (§8 item 11: the entity calls broken out), and each
    thresholded method's cost per document: the engine and minimal engine use every call but LLM-direct's,
    pairwise-only every call but the entity calls and LLM-direct's. Thinking tokens are among the output tokens."""
    def zero():
        return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "usd": 0.0}

    kinds, steps = {k: zero() for k in CALL_KINDS}, {s: zero() for s in ENTITY_STEPS}
    for c in calls:
        u = c["usage"]
        step = entity_step(c["tag"])
        for k in (kinds[call_kind(c["tag"])], *([steps[step]] if step else [])):
            k["calls"] += 1
            for f in ("input_tokens", "output_tokens", "thinking_tokens"):
                k[f] += u.get(f, 0)
            k["usd"] += cost_usd(model, {"input_tokens": 0, "output_tokens": 0, **u}, c["batch"])
    usd = {k: v["usd"] for k, v in kinds.items()}
    engine = usd["extract"] + usd["pairs"] + usd["relate"] + usd["entities"]
    return {"by_call": kinds, "entity_steps": steps,
            "methods": {"engine": engine, "minimal": engine, "pairwise": engine - usd["entities"],
                        "direct": usd["direct"]}}


@dataclass
class DevDoc:
    record: dict
    analysis: Analysis
    calls: list[dict] = field(default_factory=list)


def run_document_dev(llm: LLM, record: dict, *, engine_version: str = "2.2", with_direct: bool = False) -> DevDoc:
    """One document, seed 0, at rev. 2.1's threshold (the rows hold every other). ``with_direct`` also answers
    LLM-direct's two calls (rev. 2.1's replay, for their cost); rev. 2.2 never runs them."""
    tag = text_tag(record["text"])
    with CallLog(llm) as log:
        a = analyze_text(llm, record["text"], tag=tag, seed=0, label=record["doc_id"], engine_version=engine_version,
                         threshold=RELATION_THRESHOLD_V2_1)
        if with_direct:
            for thinking in (True, False):
                llm_direct(llm, record["text"], tag=tag, thinking=thinking)
    return DevDoc(record, a, log.calls)


def run_corpus_dev(llm: LLM, records: list[dict], *, engine_version: str = "2.2", with_direct: bool = False,
                   log=print) -> list[DevDoc]:
    """Every document in turn; each document's relation calls run concurrently (cfg.llm_concurrency). An LLM error
    stops the run (the completed calls stay cached)."""
    docs = []
    for k, rec in enumerate(records, start=1):
        try:
            docs.append(run_document_dev(llm, rec, engine_version=engine_version, with_direct=with_direct))
        except LLMError as exc:
            exc.add_note(f"While analysing corpus document {rec['doc_id']} ({k} of {len(records)}) under rev. "
                         f"{engine_version}.")
            raise
        log(f"{rec['doc_id']} ({k}/{len(records)}, rev. {engine_version}): {llm.usage['spent_tokens']:,} tokens spent")
    return docs


def planned_calls(llm: LLM, records: list[dict]) -> list[tuple]:
    """The first-attempt rev. 2.2 calls of the documents, as run_document_dev sends them (for client.BatchRunner).
    Claims and pair selections are answered as in the pass, from the cache."""
    wk = llm.cfg.llm_world_knowledge
    calls = []
    for rec in records:
        tag = text_tag(rec["text"])
        claims = extract_claims(llm, rec["text"], tag=v22_tag(tag))
        pairs, _ = candidate_pairs(llm, claims, tag=tag, seed=0, world_knowledge=wk, fixture_tag=v22_tag(tag))
        calls += planned_requests_v22(llm, claims, pairs, tag=v22_tag(tag), world_knowledge=wk)
    return calls


# ------------------------------------------------------------------------------------------ rows
def _pair(a, b) -> tuple[int, int]:
    return tuple(sorted((int(a), int(b))))


def _cycle_pairs(cycle) -> list[tuple[int, int]]:
    return [_pair(cycle[i], cycle[(i + 1) % len(cycle)]) for i in range(len(cycle))] if cycle else []


def _evidence(report) -> dict:
    return {"direct": [list(p) for p in report.direct_contradictions],
            "cycle": report.confident_frustrated_cycle,
            "entity": [{"type": c.type, "attribute": c.attribute, "entities": c.entities, "claims": c.claim_ids}
                       for c in report.verdict_entity_contradictions]}


def dev_row(doc: DevDoc, carried: dict | None = None) -> dict:
    """A document's row: each thresholded method's verdict at every threshold of TAUS with what made it fire, the
    threshold-free measures, the relations and claims cited, tension, the entity derivation and the cost. ``carried``
    is the run of record's row of the document (LLM-direct's verdicts are taken from it)."""
    rec, a = doc.record, doc.analysis
    version, claims = a.engine_version, a.claims
    cmap = sentence_map(claims, rec["planted"])
    missing = a.diagnostics["pairs_missing"]
    by_tau, cited = {}, set()
    for tau in TAUS:
        rep = analyze(a.graph, a.entities, a.evidence, threshold=tau, engine_version=version)
        mini = analyze_minimal(claims, a.relations, a.entity_spec, unscored_pairs=len(missing),
                               engine_version=version, threshold=tau)
        flagged, pw_pairs = pairwise_only(a.graph, tau)
        ev = _evidence(rep)
        cited |= {_pair(*p) for p in ev["direct"]} | set(_cycle_pairs(ev["cycle"])) | {_pair(*p) for p in pw_pairs}
        by_tau[tau_key(tau)] = {
            "engine": rep.verdict_inconsistent, "engine_clauses": list(rep.verdict_clauses), "evidence": ev,
            "minimal": mini.verdict_inconsistent, "minimal_clauses": list(mini.verdict_clauses),
            "minimal_localized": minimal_localizes(mini, cmap), "pairwise": flagged,
            "pairwise_pairs": [list(p) for p in pw_pairs]}
    labels = {_pair(r.a, r.b): r for r in a.relations.relations}
    tension = [r for r in a.relations.relations if r.relation == "tension"]
    planted_claims = {c for c, ks in cmap.items() if ks}
    pp = planted_pairs(cmap)
    rep = a.report
    premise_top3 = None
    if rec["variant"] == "direct" and rec["premise_contradicted"]:
        ids = {c.id for c in claims.claims if any(span_matches(c.span, p) for p in rec["premises"])}
        premise_top3 = bool(ids.intersection(rep.residual_ranking[:3]))
    cited |= set(pp) | {_pair(r.a, r.b) for r in tension}
    claim_ids = {i for p in cited for i in p}
    for ev in (v["evidence"] for v in by_tau.values()):
        claim_ids |= {i for c in ev["entity"] for i in c["claims"]}
    derivation = a.entities.derivation
    contradictions = [{"type": c.type, "attribute": c.attribute, "claims": c.claim_ids}
                      for c in rep.entity_contradictions]
    cycle = rec["variant"] == "cycle"
    carried = carried or {}
    return {
        "engine_version": version, "iteration": REV22_ITERATION if version == "2.2" else None,
        "doc_id": rec["doc_id"], "base": rec["base"], "variant": rec["variant"],
        "cycle_type": rec["cycle_type"], "premise_contradicted": rec["premise_contradicted"],
        "n_claims": len(claims.claims), "sampled": len(claims.claims) > ALL_PAIRS_MAX, "by_tau": by_tau,
        "localized_engine": engine_localizes(rep, cmap),
        "carried": {m: {"verdict": carried.get("verdict", {}).get(m), "localized": carried.get("localized", {}).get(m)}
                    for m in CARRIED},
        "planted_found": [any(k in ks for ks in cmap.values()) for k in range(len(rec["planted"]))],
        "relations_found": relations_extracted(rec["relations"], claims, a.entities),
        "relations_found_corrected": (relations_extracted_corrected(rec, claims, a.entities, rep.entity_contradictions)
                                      if cycle else []),
        "relation_misses": ([m["class"] for m in misses(rec, claims, a.entities, rep.entity_contradictions)]
                            if cycle else []),
        "arity": arity_read(rec["relations"], claims, a.entities),
        "harmony": rep.harmony, "harmony_reason": rep.harmony_reason, "conflict": rep.conflict,
        "unanchored": bool(rep.unanchored_components), "premise_top3": premise_top3,
        "planted_pair_relations": [[i, j, labels[(i, j)].relation, labels[(i, j)].confidence,
                                    labels[(i, j)].rationale] if (i, j) in labels else [i, j, None, None, None]
                                   for i, j in pp],
        "tension_pairs": [[int(r.a), int(r.b), r.confidence, r.rationale] for r in tension],
        "pairs_requested": len(a.pairs), "unscored_pairs": len(missing),
        "unscored_malformed": len(a.diagnostics["pairs_unscored_malformed"]),
        "unscored_planted": any(i in planted_claims or j in planted_claims for i, j in missing),
        "relations_ignored": a.diagnostics["relations_ignored"], "rescores": a.diagnostics["relations_rescored"],
        "entity": {"relations": len(a.entities.relations), "dropped": a.entities.dropped,
                   "contradictions": contradictions,
                   "sense_overrides": derivation.get("sense_overrides", []),
                   "superlatives": derivation.get("superlatives", []),
                   "extreme_edges": derivation.get("extreme_edges", 0),
                   "restricted_extremes": derivation.get("restricted_extremes", []),
                   "unresolved": derivation.get("unresolved", []),
                   "unsupported_order_claims": derivation.get("unsupported_order_claims", []),
                   "coverage": derivation.get("coverage"),
                   "schema_fallback": derivation.get("schema_fallback", []),
                   "invalid_ids": derivation.get("invalid_ids", 0), "skipped": derivation.get("skipped"),
                   "calls": [{"step": entity_step(c["tag"]), "thinking_tokens": c["usage"].get("thinking_tokens", 0),
                              "output_tokens": c["usage"].get("output_tokens", 0)}
                             for c in doc.calls if entity_step(c["tag"])]},
        "relations_cited": {f"{p}-{q}": [labels[(p, q)].relation, labels[(p, q)].confidence, labels[(p, q)].rationale]
                            for p, q in sorted(cited) if (p, q) in labels},
        "claims_cited": {str(i): claims.claims[i].text for i in sorted(claim_ids) if 0 <= i < len(claims.claims)},
        "cost": cost_of(doc.calls, a.model)}


def view(rows: list[dict], taus: dict[str, float] | float) -> list[dict]:
    """The rows in rev. 2.1's shape (evaluation.document_row, seed 0 only), each thresholded method at its threshold,
    so that evaluation's scorers apply."""
    taus = {m: taus for m in THRESHOLD_METHODS} if isinstance(taus, (int, float)) else taus
    out = []
    for r in rows:
        e, m, p = (r["by_tau"][tau_key(taus[k])] for k in THRESHOLD_METHODS)
        out.append({
            **{k: r[k] for k in ("doc_id", "base", "variant", "cycle_type", "premise_contradicted", "n_claims",
                                 "sampled", "planted_found", "relations_found", "arity", "harmony", "harmony_reason",
                                 "conflict", "unanchored", "premise_top3", "planted_pair_relations")},
            "verdict": {"engine": [e["engine"]], "pairwise": [p["pairwise"]],
                        **{c: r["carried"][c]["verdict"] for c in CARRIED}},
            "engine_clauses": e["engine_clauses"],
            "localized": {"engine": [r["localized_engine"]], **{c: r["carried"][c]["localized"] for c in CARRIED}},
            "minimal": {"verdict": [m["minimal"]], "clauses": m["minimal_clauses"],
                        "localized": [m["minimal_localized"]]}})
    return out


VERDICT = {"engine": lambda r: r["verdict"]["engine"][0], "minimal": lambda r: r["minimal"]["verdict"][0],
           "pairwise": lambda r: r["verdict"]["pairwise"][0],
           **{c: (lambda r, c=c: r["verdict"][c]) for c in CARRIED}}
LOCALIZED = {"engine": lambda r: r["localized"]["engine"][0], "minimal": lambda r: r["minimal"]["localized"][0],
             "pairwise": lambda r: False, **{c: (lambda r, c=c: r["localized"][c]) for c in CARRIED}}


# ------------------------------------------------------------------------------------------ §6 threshold rule
def threshold_curve(rows: list[dict], method: str) -> list[dict]:
    """Direct F1 and cycle F1 of a thresholded method at every threshold of TAUS, and their mean."""
    curve = []
    for tau in TAUS:
        s = _scores_of(view(rows, tau), VERDICT[method], LOCALIZED[method])
        d, c = s["direct"]["f1"], s["cycle"]["f1"]
        curve.append({"tau": tau, "direct_f1": d, "cycle_f1": c, "mean": (d + c) / 2})
    return curve


def select_threshold(curve: list[dict]) -> float:
    """§6.2: the threshold with the largest mean of direct F1 and cycle F1; ties go to the lowest threshold (means
    equal to 12 decimals tie)."""
    best = None
    for point in sorted(curve, key=lambda p: p["tau"]):
        if best is None or round(point["mean"], 12) > round(best["mean"], 12):
            best = point
    return best["tau"]


def threshold_rule(rows: list[dict]) -> dict:
    """§6 on a pass's rows: each method's curve and selected threshold."""
    curves = {m: threshold_curve(rows, m) for m in THRESHOLD_METHODS}
    return {"curves": curves, "selected": {m: select_threshold(c) for m, c in curves.items()}}


# ------------------------------------------------------------------------------------------ §8 diagnostics
def unscored(rows: list[dict]) -> dict:
    """Re-specification 15's stop rule on a rev. 2.2 pass: the fraction of requested pairs left without a relation."""
    requested = sum(r["pairs_requested"] for r in rows)
    missing = sum(r["unscored_pairs"] for r in rows)
    malformed = sum(r["unscored_malformed"] for r in rows)
    fraction = missing / requested if requested else 0.0
    return {"pairs_requested": requested, "unscored": missing, "unscored_malformed": malformed,
            "left_out_by_model": missing - malformed, "relations_rescored": sum(len(r["rescores"]) for r in rows),
            "answers_for_another_pair": sum(r["relations_ignored"] for r in rows),
            "fraction": fraction, "limit": UNSCORED_MAX, "stop": fraction > UNSCORED_MAX,
            "documents_with_planted_unscored": sum(r["unscored_planted"] for r in rows),
            "documents": [{"doc_id": r["doc_id"], "unscored": r["unscored_pairs"],
                           "unscored_malformed": r["unscored_malformed"], "planted_involved": r["unscored_planted"]}
                          for r in rows if r["unscored_pairs"]]}


def method_scores(rows: list[dict], taus) -> dict:
    """§8.1 item 1: per method, direct and cycle precision, recall and F1 (cycle also per cycle type), the
    false-positive rate on consistent documents (also per cycle type) and on the binary three-value controls, and
    localization. LLM-direct's numbers are the run of record's (carried)."""
    v = view(rows, taus)
    out = {}
    for m in THRESHOLD_METHODS + CARRIED:
        s = _scores_of(v, VERDICT[m], LOCALIZED[m])
        s["false_positive_rate_by_type"] = {t: rate([VERDICT[m](r) for r in v if r["variant"] == "consistent"
                                                     and r["cycle_type"] == t]) for t in CYCLE_TYPES}
        if m == "pairwise":
            s["localization"] = None
        out[m] = dict(s, carried=m in CARRIED)
    return out


def _flag(row: dict, tau: float, method: str = "engine") -> dict:
    """What a method said about a document at a threshold: the verdict, the clauses, and the cited claims and
    relations with their rationales."""
    at = row["by_tau"][tau_key(tau)]
    ev = at["evidence"]
    rel = row["relations_cited"]

    def relation(p, q):
        label = rel.get(f"{min(p, q)}-{max(p, q)}")
        return {"a": min(p, q), "b": max(p, q), "relation": label[0], "confidence": label[1],
                "rationale": label[2]} if label else {"a": min(p, q), "b": max(p, q), "relation": None}

    out = {"flagged": at[method], "clauses": at[f"{method}_clauses"] if method != "pairwise" else
           (["pairwise"] if at["pairwise"] else [])}
    if method == "pairwise":
        out["relations"] = [relation(p, q) for p, q in at["pairwise_pairs"]]
    else:
        out["direct"] = [relation(p, q) for p, q in ev["direct"]]
        out["cycle"] = ({"claims": ev["cycle"], "relations": [relation(p, q) for p, q in _cycle_pairs(ev["cycle"])]}
                        if ev["cycle"] and "claim_balance" in out["clauses"] else None)
        out["entity"] = ev["entity"] if "entity" in out["clauses"] else []
    out["claims"] = row["claims_cited"]
    return out


def _planted_labels(row: dict) -> list[dict]:
    return [{"a": i, "b": j, "relation": lab, "confidence": conf, "rationale": why}
            for i, j, lab, conf, why in row["planted_pair_relations"]]


def comparisons(rows22: list[dict], rows21: list[dict], tau22: float, tau21: float = RELATION_THRESHOLD_V2_1,
                method: str = "engine") -> dict:
    """§8 items 2-4 for one method: rev. 2.1's false positives and what rev. 2.2 says about each, the new false
    positives, and the lost detections, each with clauses, claims and rationales."""
    old = {r["doc_id"]: r for r in rows21}
    fp21, new_fp, lost = [], [], []
    for r in rows22:
        o = old.get(r["doc_id"])
        if o is None:
            continue
        was, now = o["by_tau"][tau_key(tau21)][method], r["by_tau"][tau_key(tau22)][method]
        head = {"doc_id": r["doc_id"], "variant": r["variant"], "cycle_type": r["cycle_type"]}
        if r["variant"] == "consistent" and was:
            fp21.append({**head, "rev_2_1": _flag(o, tau21, method), "rev_2_2": _flag(r, tau22, method)})
        if r["variant"] == "consistent" and now and not was:
            new_fp.append({**head, "rev_2_2": _flag(r, tau22, method)})
        if r["variant"] != "consistent" and was and not now:
            lost.append({**head, "rev_2_1": _flag(o, tau21, method), "rev_2_2": _flag(r, tau22, method),
                         "rev_2_2_planted_pairs": _planted_labels(r)})
    return {"method": method, "tau_2_2": tau22, "tau_2_1": tau21,
            "rev_2_1_false_positives": fp21, "still_flagged": sum(x["rev_2_2"]["flagged"] for x in fp21),
            "new_false_positives": new_fp, "lost_detections": lost}


def tension_report(rows22: list[dict], rows21: list[dict]) -> dict:
    """§8 item 5: tension relations per variant type, and the planted pairs of direct variants labeled tension
    (among them those rev. 2.1 labeled contradicts)."""
    old = {r["doc_id"]: {(i, j): lab for i, j, lab, *_ in r["planted_pair_relations"]} for r in rows21}
    per_variant = {}
    for v in ("consistent", "direct", "cycle"):
        docs = [r for r in rows22 if r["variant"] == v]
        per_variant[v] = {"documents": len(docs), "tension_pairs": sum(len(r["tension_pairs"]) for r in docs),
                          "documents_with_tension": sum(bool(r["tension_pairs"]) for r in docs)}
    planted, instead = [], []
    for r in rows22:
        if r["variant"] != "direct":
            continue
        for i, j, lab, conf, why in r["planted_pair_relations"]:
            before = old.get(r["doc_id"], {}).get((i, j))
            entry = {"doc_id": r["doc_id"], "a": i, "b": j, "relation": lab, "confidence": conf, "rationale": why,
                     "rev_2_1": before}
            planted.append(entry)
            if lab == "tension":
                instead.append(entry)
    return {"per_variant": per_variant, "direct_planted_pairs": len(planted),
            "direct_planted_labels": dict(Counter(p["relation"] for p in planted)),
            "direct_planted_tension": instead,
            "direct_planted_tension_was_contradicts": sum(p["rev_2_1"] == "contradicts" for p in instead)}


def contamination_report(rows: list[dict], taus) -> dict:
    """§8 item 6: re-specification 17's contamination under rev. 2.2, and each residual contradicts label."""
    v = view(rows, taus)
    residual = [{"doc_id": r["doc_id"], "cycle_type": r["cycle_type"], "a": i, "b": j, "confidence": conf,
                 "rationale": why}
                for r in rows if r["variant"] == "cycle" for i, j, lab, conf, why in r["planted_pair_relations"]
                if lab == "contradicts"]
    return {**contamination(v), "residual": residual}


def _spread(values: list[int]) -> dict:
    return {"calls": len(values), "total": sum(values), "mean": sum(values) / len(values) if values else None,
            "max": max(values, default=None)}


def entity_report(rows: list[dict]) -> dict:
    """§8 item 8: planted relations recovered, by the matching rule and by Step 0's corrected rule, with Step 0's
    class for each miss; sense overrides, superlatives and their expansions, restricted superlatives, superlative
    collisions, unsupported order claims, unresolved statements; the coverage net, schema fallbacks, ids outside the
    inventory, and the thinking tokens of each entity step."""
    cycles = [r for r in rows if r["variant"] == "cycle"]
    overrides = [dict(o, doc_id=r["doc_id"]) for r in rows for o in r["entity"]["sense_overrides"]]
    superlatives = [dict(s, doc_id=r["doc_id"]) for r in rows for s in r["entity"]["superlatives"]]
    restricted = [dict(s, doc_id=r["doc_id"]) for r in rows for s in r["entity"].get("restricted_extremes", [])]
    collisions = [{"doc_id": r["doc_id"], "variant": r["variant"], **c} for r in rows
                  for c in r["entity"]["contradictions"] if c["type"] == "superlative_collision"]
    covered = [(r["doc_id"], r["entity"]["coverage"]) for r in rows if r["entity"].get("coverage")]
    calls = [c for r in rows for c in r["entity"].get("calls", [])]
    misses_by = {t: Counter(m for r in cycles if r["cycle_type"] == t for m in r.get("relation_misses", []))
                 for t in CYCLE_TYPES}
    return {"planted_relations_extracted": rate([x for r in cycles for x in r["relations_found"]]),
            "planted_relations_extracted_by_type": {t: rate([x for r in cycles if r["cycle_type"] == t
                                                             for x in r["relations_found"]]) for t in CYCLE_TYPES},
            "planted_relations_extracted_corrected": rate([x for r in cycles
                                                           for x in r.get("relations_found_corrected", [])]),
            "planted_relations_extracted_corrected_by_type": {
                t: rate([x for r in cycles if r["cycle_type"] == t for x in r.get("relations_found_corrected", [])])
                for t in CYCLE_TYPES},
            "relation_misses_by_type": {t: {c: misses_by[t][c] for c in CLASSES} for t in CYCLE_TYPES},
            "sense_overrides": len(overrides), "sense_override_list": overrides,
            "superlatives": len(superlatives), "superlative_edges": sum(s["edges"] for s in superlatives),
            "superlative_list": superlatives, "restricted_superlatives": len(restricted),
            "restricted_superlative_list": restricted, "superlative_collisions": collisions,
            "unsupported_order_claims": sum(len(r["entity"]["unsupported_order_claims"]) for r in rows),
            "documents_with_unsupported_order_claims": [r["doc_id"] for r in rows
                                                        if r["entity"]["unsupported_order_claims"]],
            "unresolved_statements": sum(len(r["entity"]["unresolved"]) for r in rows),
            "entity_relations": sum(r["entity"]["relations"] for r in rows),
            "entity_relations_dropped": sum(r["entity"]["dropped"] for r in rows),
            "coverage_net": {
                "lexicon_claims": sum(len(c["lexicon_matched"]) for _, c in covered),
                "uncovered_claims": sum(len(c["uncovered"]) for _, c in covered),
                "follow_up_calls": sum(bool(c["follow_up"]) for _, c in covered),
                "statements_added": sum(c["statements_added"] for _, c in covered),
                "none_answers": sum(len(c["none"]) for _, c in covered),
                "still_uncovered": [{"doc_id": d, "claims": c["still_uncovered"]} for d, c in covered
                                    if c["still_uncovered"]]},
            "schema_fallbacks": [{"doc_id": r["doc_id"], "calls": r["entity"]["schema_fallback"]} for r in rows
                                 if r["entity"].get("schema_fallback")],
            "invalid_ids": sum(r["entity"].get("invalid_ids", 0) for r in rows),
            "entity_steps_skipped": [{"doc_id": r["doc_id"], "reason": r["entity"]["skipped"]} for r in rows
                                     if r["entity"].get("skipped")],
            "thinking_tokens": {s: _spread([c["thinking_tokens"] for c in calls if c["step"] == s])
                                for s in ENTITY_STEPS}}


def cost_report(rows: list[dict]) -> dict:
    """§8 item 11: the measured cost per document of each method, and the total of the calls behind the rows."""
    n = len(rows)
    methods = {m: sum(r["cost"]["methods"][m] for r in rows) for m in ("engine", "minimal", "pairwise", "direct")}
    fields = ("calls", "input_tokens", "output_tokens", "thinking_tokens", "usd")
    calls = {k: {f: sum(r["cost"]["by_call"][k].get(f, 0) for r in rows) for f in fields} for k in CALL_KINDS}
    steps = {s: {f: sum(r["cost"].get("entity_steps", {}).get(s, {}).get(f, 0) for r in rows) for f in fields}
             for s in ENTITY_STEPS}
    return {"documents": n, "per_document_usd": {m: v / n if n else None for m, v in methods.items()},
            "total_usd": sum(c["usd"] for c in calls.values()), "by_call": calls, "entity_steps": steps}


def diagnostics(rows22: list[dict], rows21: list[dict], selected: dict | None = None) -> dict:
    """Every §8 diagnostic of a rev. 2.2 pass next to rev. 2.1's, at τ = 0.5 and, once the §6 rule has been applied,
    at the selected thresholds. ``rows21`` are rev. 2.1's rows of the same documents (from the run of record's
    cache)."""
    ids = {r["doc_id"] for r in rows22}
    rows21 = [r for r in rows21 if r["doc_id"] in ids]
    base = {m: RELATION_THRESHOLD_V2_1 for m in THRESHOLD_METHODS}
    points = {"0.5": base} | ({"selected": dict(selected)} if selected else {})
    out = {"label": LABEL, "documents": len(rows22), "selected_thresholds": selected,
           "unscored": unscored(rows22),
           "methods": {"rev_2_1": method_scores(rows21, base),
                       **{f"rev_2_2_at_{k}": method_scores(rows22, t) for k, t in points.items()}},
           "comparisons": {k: {m: comparisons(rows22, rows21, t[m], method=m) for m in THRESHOLD_METHODS}
                           for k, t in points.items()},
           "tension": tension_report(rows22, rows21),
           "contamination": {"rev_2_1": contamination_report(rows21, base),
                             **{f"rev_2_2_at_{k}": contamination_report(rows22, t) for k, t in points.items()}},
           "clause_attribution": {"rev_2_1": clause_attribution(view(rows21, base)),
                                  **{f"rev_2_2_at_{k}": clause_attribution(view(rows22, t))
                                     for k, t in points.items()}},
           "entity": {"rev_2_1": entity_report(rows21), "rev_2_2": entity_report(rows22)},
           "l1b": {"rev_2_1": score_l1b(view(rows21, base), judged=False),
                   "rev_2_2": score_l1b(view(rows22, base), judged=False)},
           "minimal": {"rev_2_1": score_minimal(view(rows21, base)),
                       **{f"rev_2_2_at_{k}": score_minimal(view(rows22, t)) for k, t in points.items()}},
           "cost": {"rev_2_1": cost_report(rows21), "rev_2_2": cost_report(rows22)}}
    if selected:
        common = {m: selected["engine"] for m in THRESHOLD_METHODS}
        out["minimal"]["rev_2_2_both_at_engine_tau"] = score_minimal(view(rows22, common))
    return out


# ------------------------------------------------------------------------------------------ §8.1 L1-var 2.2
def _entity_key(r) -> str:
    a, b = (r.a, r.b) if r.kind == "greater" else sorted((r.a, r.b))
    return f"{r.claim_id}:{r.kind}:{a}:{b}"


def run_l1var_v22(llm: LLM, docs: list[DevDoc], *, repeats: int = REPEATS, raw_dir=None, log=print) -> list[dict]:
    """Relations and entity statements again, `repeats` times with the cache bypassed, on the claims and pairs of
    the pass (§8.1); every response is saved to `raw_dir` (never to fixtures), so replay_l1var_v22 can recompute the
    rows. LLM-direct is not run."""
    from .client import API_KEY_ENV
    from .l1var_raw import RawSaver
    if llm.dry_run:
        raise LLMError(f"L1-var measures how repeated live calls differ, so it cannot run in dry-run mode ({API_KEY_ENV} "
                       "is not set in the environment).")
    with RawSaver(llm, raw_dir) as saver:
        return _l1var_rows_v22(llm, docs, repeats, log, saver)


def _l1var_rows_v22(llm: LLM, docs: list[DevDoc], repeats: int, log, saver) -> list[dict]:
    rows = []
    for doc in docs:
        a = doc.analysis
        for k in range(1, repeats + 1):
            saver.at(doc.record["doc_id"], k)
            tag = f"{v22_tag(a.tag)}-var{k}"
            relations, _, _ = score_pairs_v22(llm, a.claims, a.pairs, tag=tag, world_knowledge=a.world_knowledge,
                                              bypass_cache=True)
            spec = extract_entity_steps_v22(llm, a.claims, tag=tag, bypass_cache=True)
            eg = build_entity_graph_v22(spec, n_claims=len(a.claims.claims))
            graph = build_signed_graph(a.claims, relations)
            verdicts = {}
            for tau in TAUS:
                verdicts[tau_key(tau)] = {
                    "engine": analyze(graph, eg, a.evidence, threshold=tau, engine_version="2.2").verdict_inconsistent,
                    "minimal": analyze_minimal(a.claims, relations, spec, engine_version="2.2",
                                               threshold=tau).verdict_inconsistent,
                    "pairwise": pairwise_only(graph, tau)[0]}
            rows.append({"engine_version": "2.2", "doc_id": doc.record["doc_id"], "repeat": k,
                         "relations": {f"{r.a}-{r.b}": r.relation for r in relations.relations},
                         "entity_relations": sorted({_entity_key(r) for r in eg.relations}),
                         "verdict_by_tau": verdicts})
        log(f"L1-var 2.2 {doc.record['doc_id']}: {llm.usage['spent_tokens']:,} tokens spent")
    return rows


def replay_l1var_v22(docs: list[DevDoc], raw_dir, *, cache_dir, repeats: int = REPEATS, log=print) -> list[dict]:
    """The §8.1 rows recomputed from the responses run_l1var_v22 saved, with no API calls."""
    from pathlib import Path

    from .l1var_raw import RawSaver, SavedResponses
    client = SavedResponses(raw_dir)
    if len(client.models) != 1:
        raise LLMError(f"The saved L1-var responses come from more than one model: {sorted(client.models)}.")
    llm = LLM(cache_dir=cache_dir, client=client, fixture_dir=Path(cache_dir) / "fixtures",
              model=next(iter(client.models)), budget_tokens=10**15)
    rows = _l1var_rows_v22(llm, docs, repeats, log, RawSaver(llm, None))
    if client.left_over():
        raise LLMError(f"{client.left_over()} saved L1-var responses were not asked for when recomputing.")
    return rows


def direction_disagreements(entity_keys_by_repeat: list[list[str]]) -> tuple[int, int]:
    """(claims-and-entity-pairs with a greater relation in some repeat, those given both directions across the
    repeats) for one document."""
    seen: dict[tuple, set] = defaultdict(set)
    for keys in entity_keys_by_repeat:
        for key in keys:
            claim, kind, a, b = key.split(":", 3)
            if kind == "greater":
                seen[(claim, frozenset((a, b)))].add((a, b))
    return len(seen), sum(len(v) > 1 for v in seen.values())


def score_l1var_v22(rows: list[dict], taus=None) -> dict:
    """§8.1: relation agreement and entity-relation agreement across the repeats (as rev. 2.1's L1-var), direction
    disagreements, and each thresholded method's verdict-change rate at τ = 0.5 and at ``taus``."""
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_doc[r["doc_id"]].append(r)
    pairs, entities, units, flips = [], [], 0, 0
    for reps in by_doc.values():
        for p in set().union(*(r["relations"] for r in reps)):
            pairs.append(len({r["relations"].get(p, "missing") for r in reps}) == 1)
        for e in set().union(*(r["entity_relations"] for r in reps)):
            entities.append(all(e in r["entity_relations"] for r in reps))
        u, f = direction_disagreements([r["entity_relations"] for r in reps])
        units, flips = units + u, flips + f
    points = {"0.5": {m: RELATION_THRESHOLD_V2_1 for m in THRESHOLD_METHODS}} | ({"selected": taus} if taus else {})
    changes = {k: {m: rate([len({r["verdict_by_tau"][tau_key(t[m])][m] for r in reps}) > 1
                            for reps in by_doc.values()]) for m in THRESHOLD_METHODS} for k, t in points.items()}
    return {"label": LABEL, "documents": len(by_doc), "repeats": max((len(v) for v in by_doc.values()), default=0),
            "pairs": len(pairs), "relation_agreement": rate(pairs), "entity_relations": len(entities),
            "entity_agreement": rate(entities), "greater_units": units, "direction_disagreements": flips,
            "direction_disagreement_rate": flips / units if units else None, "verdict_change_rate": changes}


def rev21_direction_disagreements(rows: list[dict]) -> dict:
    """Direction disagreements in rev. 2.1's L1-var rows (l1var_repeats.jsonl), for comparison."""
    by_doc: dict[str, list[list[str]]] = defaultdict(list)
    for r in rows:
        by_doc[r["doc_id"]].append(r["entity_relations"])
    units = flips = 0
    for reps in by_doc.values():
        u, f = direction_disagreements(reps)
        units, flips = units + u, flips + f
    return {"greater_units": units, "direction_disagreements": flips,
            "direction_disagreement_rate": flips / units if units else None}


# ------------------------------------------------------------------------------------------ report
def _n(x, digits: int = 3) -> str:
    return "n/a" if x is None else (f"{x:.{digits}f}" if isinstance(x, float) else str(x))


def dev_markdown(res: dict) -> str:
    """The development pass's report: every table carries LABEL."""
    d = res["diagnostics"]
    lines = [f"# A1 rev. 2.2 development pass ({res.get('pass', 'pass')})", "", f"*{LABEL}.*", "",
             f"Documents: {d['documents']}. Engine version 2.2; claims and pair selections from the run of record's "
             "cache (seed 0); LLM-direct carried from the run of record."]
    u = d["unscored"]
    lines += ["", f"Unscored pairs: {u['unscored']} of {u['pairs_requested']} ({_n(u['fraction'], 4)}; stop above "
              f"{u['limit']}); re-scored: {u['relations_rescored']}; answers for another pair: "
              f"{u['answers_for_another_pair']}."]
    if res.get("threshold_rule"):
        sel = res["threshold_rule"]["selected"]
        lines += ["", "## Threshold rule (§6), applied on this pass", "", f"*{LABEL}.*", "",
                  "| τ | " + " | ".join(f"{m} direct F1 | {m} cycle F1 | {m} mean" for m in THRESHOLD_METHODS) + " |",
                  "|---|" + "---|" * (3 * len(THRESHOLD_METHODS))]
        curves = res["threshold_rule"]["curves"]
        for k, tau in enumerate(TAUS):
            cells = []
            for m in THRESHOLD_METHODS:
                p = curves[m][k]
                cells += [_n(p["direct_f1"]), _n(p["cycle_f1"]), _n(p["mean"])]
            lines.append(f"| {tau:.2f} | " + " | ".join(cells) + " |")
        lines += ["", "Selected: " + ", ".join(f"{m} τ = {sel[m]:.2f}" for m in THRESHOLD_METHODS) + "."]
    if res.get("rev21_curves"):
        lines += ["", "## Rev. 2.1 threshold curves (report-only, from the run of record's cache)", "",
                  "| τ | " + " | ".join(f"{m} mean F1" for m in THRESHOLD_METHODS) + " |",
                  "|---|" + "---|" * len(THRESHOLD_METHODS)]
        for k, tau in enumerate(TAUS):
            lines.append(f"| {tau:.2f} | " + " | ".join(_n(res["rev21_curves"][m][k]["mean"])
                                                       for m in THRESHOLD_METHODS) + " |")
    lines += ["", "## Methods (§8 item 1)", "", f"*{LABEL}.*", "",
              "| method | version | τ | direct P / R / F1 | cycle P / R / F1 | FP rate | binary control FP |",
              "|---|---|---|---|---|---|---|"]
    for key, scores in d["methods"].items():
        version = "2.1" if key == "rev_2_1" else "2.2"
        for m, s in scores.items():
            tau = ("—" if s["carried"] else ("0.50" if key != "rev_2_2_at_selected"
                                             else f"{d['selected_thresholds'][m]:.2f}"))
            name = m + (" (carried)" if s["carried"] else "")
            lines.append(f"| {name} | {version} | {tau} | {_n(s['direct']['precision'])} / {_n(s['direct']['recall'])}"
                         f" / {_n(s['direct']['f1'])} | {_n(s['cycle']['precision'])} / {_n(s['cycle']['recall'])} / "
                         f"{_n(s['cycle']['f1'])} | {_n(s['false_positive_rate'])} | "
                         f"{_n(s['binary_control_false_positive_rate'])} |")
    for key, per_method in d["comparisons"].items():
        c = per_method["engine"]
        lines += ["", f"## Engine at τ = {c['tau_2_2']:.2f}: rev. 2.1's false positives, new false positives, lost "
                  "detections (§8 items 2-4)", "", f"*{LABEL}.*", "",
                  f"Rev. 2.1 false positives: {len(c['rev_2_1_false_positives'])}; still flagged under 2.2: "
                  f"{c['still_flagged']}. New false positives: {len(c['new_false_positives'])}. Lost detections: "
                  f"{len(c['lost_detections'])}."]
        for x in c["rev_2_1_false_positives"]:
            lines.append(f"- {x['doc_id']} ({x['cycle_type']}): 2.1 {'+'.join(x['rev_2_1']['clauses'])}; 2.2 "
                         + ("flags it, " + "+".join(x["rev_2_2"]["clauses"]) if x["rev_2_2"]["flagged"]
                            else "does not flag it") + ".")
        for x in c["new_false_positives"]:
            lines.append(f"- new: {x['doc_id']} ({x['cycle_type']}): {'+'.join(x['rev_2_2']['clauses'])}.")
        for x in c["lost_detections"]:
            lines.append(f"- lost: {x['doc_id']} ({x['variant']}, {x['cycle_type']}): 2.1 "
                         f"{'+'.join(x['rev_2_1']['clauses'])}.")
    t = d["tension"]
    lines += ["", "## Tension (§8 item 5)", "", f"*{LABEL}.*", "",
              "| variant | documents | tension pairs | documents with tension |", "|---|---|---|---|"]
    for v, x in t["per_variant"].items():
        lines.append(f"| {v} | {x['documents']} | {x['tension_pairs']} | {x['documents_with_tension']} |")
    lines += ["", f"Planted pairs in direct variants: {t['direct_planted_pairs']}, labeled "
              f"{t['direct_planted_labels']}; tension: {len(t['direct_planted_tension'])} (rev. 2.1 contradicts: "
              f"{t['direct_planted_tension_was_contradicts']})."]
    lines += ["", "## Contamination, clause attribution, entity extraction, L1b, minimal engine, cost (§8 items 6-11)",
              "", f"*{LABEL}.*", ""]
    for key, c in d["contamination"].items():
        lines.append(f"- Contamination {key}: {c['contradicts']} of {c['scored']} scored planted pairs "
                     f"({_n(c['rate'])}).")
    for key, c in d["clause_attribution"].items():
        lines.append(f"- Clause attribution {key}: {c['combinations']}.")
    for key, e in d["entity"].items():
        order = e["relation_misses_by_type"]["order_cycle"]
        lines.append(f"- Entity {key}: planted relations recovered {_n(e['planted_relations_extracted'])} (Step 0's "
                     f"corrected rule: {_n(e['planted_relations_extracted_corrected'])}); order-cycle misses "
                     + ", ".join(f"{c} {order[c]}" for c in CLASSES) + f"; sense overrides {e['sense_overrides']}; "
                     f"superlatives {e['superlatives']} ({e['superlative_edges']} edges), restricted "
                     f"{e['restricted_superlatives']}; superlative collisions {len(e['superlative_collisions'])}; "
                     f"unsupported order claims {e['unsupported_order_claims']}.")
        net, thinking = e["coverage_net"], e["thinking_tokens"]
        if thinking["inventory"]["calls"]:
            lines.append(f"- Entity steps {key}: lexicon claims {net['lexicon_claims']}, uncovered "
                         f"{net['uncovered_claims']}, follow-up calls {net['follow_up_calls']}, statements added "
                         f"{net['statements_added']}, none answers {net['none_answers']}, still uncovered "
                         f"{sum(len(s['claims']) for s in net['still_uncovered'])}; schema fallbacks "
                         f"{len(e['schema_fallbacks'])}; ids outside the inventory {e['invalid_ids']}; skipped "
                         f"{len(e['entity_steps_skipped'])}; mean thinking tokens "
                         + ", ".join(f"{s} {_n(thinking[s]['mean'], 0)}" for s in ENTITY_STEPS) + ".")
    for key, b in d["l1b"].items():
        lines.append(f"- L1b {key}: AUC(1 − H) {_n(b['auc_harmony'])}, AUC(λ_min) {_n(b['auc_conflict'])}, premise "
                     f"in top-3 {_n(b['premise_top3'])}.")
    for key, m in d["minimal"].items():
        lines.append(f"- Minimal engine {key}: agreement with the full engine {_n(m['agreement'])}, clause "
                     f"mismatches {len(m['clause_mismatches'])}.")
    for key, c in d["cost"].items():
        per = c["per_document_usd"]
        lines.append(f"- Cost {key}: per document engine ${_n(per['engine'], 4)}, pairwise ${_n(per['pairwise'], 4)}, "
                     f"LLM-direct ${_n(per['direct'], 4)}; total ${_n(c['total_usd'], 2)}.")
    if res.get("l1var"):
        v = res["l1var"]
        lines += ["", "## L1-var under rev. 2.2 (§8.1)", "", f"*{LABEL}.*", "",
                  f"Relation agreement {_n(v['relation_agreement'])} (rev. 2.1: 0.933); entity-relation agreement "
                  f"{_n(v['entity_agreement'])} (rev. 2.1: 0.518); direction disagreements "
                  f"{v['direction_disagreements']} of {v['greater_units']}"
                  + (f" (rev. 2.1: {res['l1var_rev21']['direction_disagreements']} of "
                     f"{res['l1var_rev21']['greater_units']})" if res.get("l1var_rev21") else "") + "; verdict "
                  f"changes {v['verdict_change_rate']}."]
    return "\n".join(lines)
