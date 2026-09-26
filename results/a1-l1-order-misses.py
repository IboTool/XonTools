"""Step 0 of A1 rev. 2.2 (XON_A1_REV2_2_PRECISION.md §7.1): the run of record's missed planted order relations,
classified, and the rev. 2.2 full pass's remaining false positives, from the runs' files only. No LLM calls.

Reads the run of record (results/a1-20260924-232324: documents.jsonl, l1.json, analyses/), the corpus it ran on
(data/consistency/corpus.jsonl), and the rev. 2.2 full development pass, iteration 0
(results/a1-rev22-full-20260925-124414: documents_v22.jsonl, analyses/, diagnostics.json).

    python results/a1-l1-order-misses.py [--out results/a1-l1-order-misses.md]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xon.llm.entity_consistency import EntityGraph, build_entity_graph, build_entity_graph_v22  # noqa: E402
from xon.llm.evaluation import matched_relations, relations_extracted  # noqa: E402
from xon.llm.order_misses import (CLASSES, misses, planted_cycle_closes, planted_cycle_reported,  # noqa: E402
                                  relations_extracted_corrected)
from xon.llm.schemas import ClaimList, EntityGraphSpec, EntityGraphSpecV22  # noqa: E402

RECORD = ROOT / "results" / "a1-20260924-232324"
DEV = ROOT / "results" / "a1-rev22-full-20260925-124414"
CORPUS = ROOT / "data" / "consistency" / "corpus.jsonl"
OUT = ROOT / "results" / "a1-l1-order-misses.md"
DEV_LABEL = "rev. 2.2 development pass on the seen L1 corpus; not a result of record"
TYPES = {"order_cycle": "order cycle", "equality_break": "equality break", "binary_parity": "binary parity"}
DERIVED_FIELDS = ("claim_id", "attribute", "kind", "a", "b", "confidence")


def jsonl(path):
    return [json.loads(x) for x in Path(path).read_text("utf-8").splitlines() if x.strip()]


def load(run, doc_id, version):
    """The claims, the entity graph rebuilt as the engine built it, and the engine's entity contradictions."""
    a = json.loads((run / "analyses" / f"{doc_id}.json").read_text("utf-8"))
    claims = ClaimList.model_validate({"claims": a["claims"]})
    spec, n = a["entity_relations"], len(claims.claims)
    if not spec:
        eg = EntityGraph([], {}, {}, {})
    elif version == "2.1":
        eg = build_entity_graph(EntityGraphSpec.model_validate(spec), n_claims=n)
    else:
        eg = build_entity_graph_v22(EntityGraphSpecV22.model_validate(spec), n_claims=n)
        rebuilt = [{k: getattr(r, k) for k in DERIVED_FIELDS} for r in eg.relations]
        assert rebuilt == [{k: r[k] for k in DERIVED_FIELDS} for r in a["derived_entity_relations"]], doc_id
    return a, claims, eg, a["report"]["entity_contradictions"]


def rate(flags):
    return f"{sum(flags) / len(flags):.3f} ({sum(flags)} of {len(flags)})"


def rel_text(r):
    return f"greater({r['a']}, {r['b']}), {r['direction']}" if r["kind"] == "greater" else f"{r['kind']}({r['a']}, {r['b']})"


def stated_text(r):
    return f"{r.kind}({r.a}, {r.b}) on `{r.attribute}`, {r.confidence}"


def orientation(record, claims, eg):
    """How each planted relation of a document is matched: forward, reverse, both, or not matched."""
    out = []
    for rel in record["relations"]:
        found = {o for _, o in matched_relations(rel, claims, eg)}
        out.append("both" if len(found) > 1 else next(iter(found)) if found else "none")
    return out


def score(run, rows, corpus, version):
    """Per cycle variant: the matching rule's flags (checked against the run's own), the corrected rule's, whether
    the planted cycle closes and whether the engine reports it, and the misses with their classes."""
    out = {}
    for row in rows:
        if row["variant"] != "cycle":
            continue
        rec = corpus[row["doc_id"]]
        a, claims, eg, contradictions = load(run, row["doc_id"], version)
        found = relations_extracted(rec["relations"], claims, eg)
        assert found == row["relations_found"], row["doc_id"]
        out[row["doc_id"]] = {
            "record": rec, "analysis": a, "claims": claims, "eg": eg, "found": found,
            "corrected": relations_extracted_corrected(rec, claims, eg, contradictions),
            "closes": planted_cycle_closes(rec, claims, eg, contradictions),
            "reported": planted_cycle_reported(rec, claims, contradictions),
            "misses": misses(rec, claims, eg, contradictions)}
    return out


def rates(scored, key):
    order = [x for s in scored.values() if s["record"]["cycle_type"] == "order_cycle" for x in s[key]]
    return rate(order), rate([x for s in scored.values() for x in s[key]])


def order_cycles(scored):
    return {d: s for d, s in scored.items() if s["record"]["cycle_type"] == "order_cycle"}


def cycle_lines(name, scored):
    """The planted order cycles that close, those the engine reports, and what it reports instead for the rest."""
    order = order_cycles(scored)
    lines = [f"- {name}: the planted order cycle closes in the entity graph in {sum(s['closes'] for s in order.values())}"
             f" of {len(order)} order-cycle documents, and is the entity contradiction the engine reports in "
             f"{sum(s['reported'] for s in order.values())}."]
    for d, s in order.items():
        if s["reported"]:
            continue
        text = {c.id: c.text for c in s["claims"].claims}
        for c in s["analysis"]["report"]["entity_contradictions"]:
            lines.append(f"  - {d}: the engine reports {c['type']} on `{c['attribute']}` over "
                         f"{', '.join(c['entities'])}, from " + "; ".join(f"claim {i}, \"{text[i]}\""
                                                                          for i in c["claim_ids"]))
    return lines


def false_positives(dev_rows):
    engine = json.loads((DEV / "diagnostics.json").read_text("utf-8"))["diagnostics"]["comparisons"]["0.5"]["engine"]
    items = [x for x in engine["rev_2_1_false_positives"] if x["rev_2_2"]["flagged"]] + engine["new_false_positives"]
    return [(x, dev_rows[x["doc_id"]]["by_tau"]["0.50"]) for x in items]


def fp_lines(x, tau, corpus):
    rec, now = corpus[x["doc_id"]], x["rev_2_2"]
    claims = now["claims"]
    before = x.get("rev_2_1")
    control = ", the binary three-value control" if x["cycle_type"] == "binary_parity" else ""
    lines = [f"### {x['doc_id']} ({TYPES[x['cycle_type']]} base{control})", "",
             f"- Rev. 2.1: " + (f"flagged ({', '.join(before['clauses'])})." if before else "not flagged.")
             + f" Rev. 2.2: flagged ({', '.join(now['clauses'])}); the minimal engine: "
             + (f"flagged ({', '.join(tau['minimal_clauses'])})." if tau["minimal"] else "not flagged.")]
    if rec.get("arity_sentence"):
        lines.append(f"- The document's number-of-values sentence: \"{rec['arity_sentence']}\"")
    for d in now["direct"]:
        lines += [f"- Direct: claim {d['a']}, \"{claims[str(d['a'])]}\", and claim {d['b']}, "
                  f"\"{claims[str(d['b'])]}\": {d['relation']}, confidence {d['confidence']:.2f}.",
                  f"  Rationale: \"{d['rationale']}\""]
    if "claim_balance" in now["clauses"] and now["cycle"]:
        cyc = now["cycle"]
        lines.append(f"- Claim balance: the frustrated cycle over claims {', '.join(map(str, cyc['claims']))}:")
        lines += [f"  - {r['a']}-{r['b']}: {r['relation']}, confidence {r['confidence']:.2f}. \"{r['rationale']}\""
                  for r in cyc["relations"]]
        lines += [f"  - claim {c}: \"{claims[str(c)]}\"" for c in cyc["claims"]]
    for e in now["entity"]:
        lines.append(f"- Entity: {json.dumps(e, ensure_ascii=False)}")
    return lines + [""]


def report(record, dev, corpus, dev_rows, l1):
    missed = [(d, m) for d, s in order_cycles(record).items() for m in s["misses"]]
    counts = {c: sum(m["class"] == c for _, m in missed) for c in CLASSES}
    docs = sorted({d for d, _ in missed})
    order_total = sum(len(s["found"]) for s in record.values() if s["record"]["cycle_type"] == "order_cycle")
    n_order = sum(s["record"]["cycle_type"] == "order_cycle" for s in record.values())
    rr_order, rr_all = rates(record, "found")
    reported = l1["diagnostics"]
    assert (float(rr_order.split()[0]), float(rr_all.split()[0])) == (
        round(reported["planted_relations_extracted_by_type"]["order_cycle"], 3),
        round(reported["planted_relations_extracted"], 3))
    fps = false_positives(dev_rows)
    L = ["# A1 rev. 2.2, Step 0: the run of record's missed planted order relations", "",
         "Produced by `results/a1-l1-order-misses.py`, which reads only the runs' files and makes no API calls: the run "
         "of record (`results/a1-20260924-232324/`: `documents.jsonl`, `l1.json`, `analyses/`), the corpus it ran on "
         "(`data/consistency/corpus.jsonl`), and the rev. 2.2 full development pass, iteration 0 "
         "(`results/a1-rev22-full-20260925-124414/`: `documents_v22.jsonl`, `analyses/`, `diagnostics.json`). Each "
         "entity graph is rebuilt from the run's cached extraction as the engine built it, and the matching rule's "
         "flags are checked against the run's own before anything is reported. The run of record's reported figures "
         f"stay as they are. Every rev. 2.2 figure: {DEV_LABEL}.", "",
         "## Summary", "",
         f"- Planted order relations the L1 diagnostic counted as not extracted correctly (seed 0, cycle variants): "
         f"{len(missed)} of {order_total}, in {len(docs)} of the {n_order} order-cycle documents "
         f"({', '.join(docs)}).",
         "- By class: " + ", ".join(f"{c} {counts[c]}" for c in CLASSES) + ".",
         *cycle_lines("Run of record", record), *cycle_lines("Rev. 2.2, iteration 0", dev),
         "  A planted order cycle closes when one relation stated by a claim matched to each planted sentence, all "
         "on one attribute, chain round the planted entities, one way or the other. The engine reports the shortest "
         "contradiction on each attribute, so a closed cycle is not always the one reported.", ""]
    if missed and all(m["class"] == "scoring artifact" for _, m in missed):
        L += ["In each of these documents every planted order relation is extracted the other way round, on one "
              "attribute, so the extraction states the planted cycle's mirror image, which closes: the engine "
              "reports it, on the planted claims. Each relation, taken alone, also fits the description of a direction "
              "flip (the right entities and attribute, the wrong direction); a miss goes to the first class that "
              "fits, and scoring artifact comes first.", ""]
    L += ["## By document", "",
          "| Document | Missed | " + " | ".join(CLASSES) + " | Planted cycle closes | Engine reports it | Engine "
          "clauses |",
          "|---" * (len(CLASSES) + 5) + "|"]
    for d in docs:
        s = record[d]
        L.append(f"| {d} | {len(s['misses'])} of {len(s['found'])} | "
                 + " | ".join(str(sum(m['class'] == c for m in s['misses'])) for c in CLASSES)
                 + f" | {'yes' if s['closes'] else 'no'} | {'yes' if s['reported'] else 'no'} | "
                 + f"{', '.join(s['analysis']['report']['verdict_clauses'])} |")
    L += ["", "## Each miss, with the cached extraction", ""]
    for d in docs:
        s = record[d]
        text = {c.id: c.text for c in s["claims"].claims}
        L += [f"### {d} ({TYPES[s['record']['cycle_type']]})", ""]
        for c in s["analysis"]["report"]["entity_contradictions"]:
            L.append(f"The engine's entity contradiction: {c['type']} on `{c['attribute']}` over "
                     f"{', '.join(c['entities'])}, claims {', '.join(map(str, c['claim_ids']))}, minimum confidence "
                     f"{c['min_confidence']}.")
        L += ["", "| Planted sentence | Planted relation | Claim | Extracted from that claim | Class |",
              "|---|---|---|---|---|"]
        for m in s["misses"]:
            rel = m["relation"]
            L.append(f"| {rel['sentence']} | {rel_text(rel)} | "
                     + "; ".join(f"{i}: {text[i]}" for i in m["claims"]) + " | "
                     + ("; ".join(stated_text(r) for r in m["stated"]) or "nothing") + f" | {m['class']} |")
        twin = f"{d.rsplit('-', 1)[0]}-consistent"
        _, claims, eg, _ = load(RECORD, twin, "2.1")
        o = orientation(corpus[twin], claims, eg)
        L += ["", f"The same base's consistent variant ({twin}), its planted relations matched: "
              + ", ".join(f"{k} {o.count(k)}" for k in ("forward", "reverse", "both", "none") if o.count(k)) + ".", ""]
    dv_order, dv_all = rates(dev, "found")
    cr_order, cr_all = rates(record, "corrected")
    dc_order, dc_all = rates(dev, "corrected")
    L += ["## The two matching rules", "",
          "| Rule | Run of record: order relations | Run of record: all planted relations | "
          "Rev. 2.2, iteration 0: order relations | Rev. 2.2, iteration 0: all planted relations |",
          "|---|---|---|---|---|",
          f"| The run of record's (as reported) | {rr_order} | {rr_all} | {dv_order} | {dv_all} |",
          f"| Corrected (Step 0, report-only) | {cr_order} | {cr_all} | {dc_order} | {dc_all} |", "",
          "The run of record's rule counts a planted relation as extracted when a relation stated by a claim matched "
          "to the planted sentence has the planted kind and entities, in the planted direction for \"greater\"; a "
          "rank phrasing (direction \"either\") also counts reversed when all of the document's found rank relations "
          "share one direction. The corrected rule is the same, except that a planted relation stated the other way "
          "round also counts when the document's planted cycle closes (as defined in the summary): the mirror image "
          "of a cycle is a cycle. Neither rule looks at attribute keys; the planted-cycle counts in the summary cover "
          "them. The run of record's 0.900 and 0.967 stay as reported.", "",
          f"## The rev. 2.2 full pass's remaining false positives (iteration 0, τ = 0.5; {DEV_LABEL})", "",
          f"{len(fps)} consistent documents are flagged. By clause: "
          + "; ".join(f"{x['doc_id']} {', '.join(x['rev_2_2']['clauses'])}" for x, _ in fps) + ". "
          + ("All are flagged by relation clauses (direct, claim balance), none by the entity clause. Each is listed "
             "with its claims, the judge's label, confidence and rationale."
             if not any("entity" in x["rev_2_2"]["clauses"] for x, _ in fps)
             else "Some are flagged by the entity clause."), ""]
    for x, tau in fps:
        L += fp_lines(x, tau, corpus)
    return "\n".join(L).rstrip("\n") + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    corpus = {r["doc_id"]: r for r in jsonl(CORPUS)}
    record = score(RECORD, jsonl(RECORD / "documents.jsonl"), corpus, "2.1")
    dev_rows = {r["doc_id"]: r for r in jsonl(DEV / "documents_v22.jsonl")}
    dev = score(DEV, list(dev_rows.values()), corpus, "2.2")
    l1 = json.loads((RECORD / "l1.json").read_text("utf-8"))
    args.out.write_text(report(record, dev, corpus, dev_rows, l1), "utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
