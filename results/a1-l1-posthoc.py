"""Post-hoc analysis of the A1 L1 run of record (results/a1-20260924-232324), from its files and the call log only.

Prints the facts behind results/a1-l1-posthoc.md: the full engine's false positives on consistent documents, the cost
per document of each method, and the planted-cycle pairs the relation judge labeled contradicts. No LLM calls.

    python results/a1-l1-posthoc.py > results/a1-l1-posthoc-facts.txt
"""
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xon.llm.client import LLM_PRICES_USD_PER_MTOK  # noqa: E402

RUN = ROOT / "results" / "a1-20260924-232324"
# The recompute of 2026-09-24 23:23:24 (PDT) replayed every request of the run of record from the cache, once each.
INVENTORY_WINDOW = ("2026-09-25T06:23:20", "2026-09-25T06:24:00")
INVENTORY_SIZE = 3102
RUN_START = "2026-09-24T21:20:56"
METHODS = {"engine": ("extract", "pairs", "relate", "entities"), "pairwise": ("extract", "pairs", "relate"),
           "llm_direct_thinking": ("direct_thinking",), "llm_direct_no_thinking": ("direct_no_thinking",)}


def jsonl(path):
    return [json.loads(x) for x in Path(path).read_text("utf-8").splitlines() if x.strip()]


def analysis(doc_id):
    return json.loads((RUN / "analyses" / f"{doc_id}.json").read_text("utf-8"))


def seed0(verdict):
    return verdict[0] if isinstance(verdict, list) else verdict


def claim_line(claims, i):
    return f"{i} ({claims[i]['kind']}): {claims[i]['text']}"


def relation_line(rels, i, j):
    r = rels.get(tuple(sorted((i, j))))
    return f"{i}-{j}: {r['relation']} {r['confidence']} | {r['rationale']}" if r else f"{i}-{j}: no relation"


def false_positives(rows):
    fps = [r for r in rows if r["variant"] == "consistent" and seed0(r["verdict"]["engine"])]
    print(f"# Full engine false positives on consistent documents: {len(fps)} of "
          f"{sum(r['variant'] == 'consistent' for r in rows)}")
    for r in fps:
        a = analysis(r["doc_id"])
        claims = {c["id"]: c for c in a["claims"]}
        rels = {tuple(sorted((x["a"], x["b"]))): x for x in a["relations"]}
        entity_relations = a["entity_relations"]["relations"] if a["entity_relations"] else []
        rep = a["report"]
        control = " (binary three-value control)" if r["cycle_type"] == "binary_parity" else ""
        print(f"\n## {r['doc_id']}, base {r['cycle_type']}{control}")
        print(f"full engine clauses: {rep['verdict_clauses']}; minimal engine clauses: {r['minimal']['clauses']}")
        for i, j in rep["direct_contradictions"]:
            print(f"direct: {claim_line(claims, i)}\n        {claim_line(claims, j)}\n        {relation_line(rels, i, j)}")
        for e in rep["verdict_entity_contradictions"]:
            print(f"entity: {e['type']} on {e['attribute']} over {e['entities']}, min confidence {e['min_confidence']}")
            for k in e["relations"]:
                print(f"        relation {k}: {entity_relations[k]}")
            for i in e["claim_ids"]:
                print(f"        {claim_line(claims, i)}")
        cycle = rep.get("confident_frustrated_cycle")
        if "claim_balance" in rep["verdict_clauses"] and cycle:
            print(f"claim balance: frustrated cycle {cycle}")
            for i in cycle:
                print(f"        {claim_line(claims, i)}")
            for i, j in zip(cycle, cycle[1:] + cycle[:1]):
                print(f"        {relation_line(rels, i, j)}")


def category(tag):
    rest = tag.split("-", 2)[2]
    if rest.startswith("seed"):
        return "extra_seeds"
    return {"direct-thinking": "direct_thinking", "direct-no-thinking": "direct_no_thinking"}.get(
        rest, "relate" if rest.startswith("relate-") else rest)


def costs():
    model = json.loads((RUN / "run.json").read_text("utf-8"))["model"]
    p_in, p_out = LLM_PRICES_USD_PER_MTOK[model]
    log = jsonl(ROOT / "cache" / "llm" / "log.jsonl")
    inventory = [r for r in log if r["source"] == "cache" and INVENTORY_WINDOW[0] <= r["timestamp"] < INVENTORY_WINDOW[1]]
    assert len(inventory) == INVENTORY_SIZE, len(inventory)
    paid = {}
    for r in log:
        if r["source"] == "api" and not r.get("error"):
            paid.setdefault(r["request"], r)
    assert all(r["request"] in paid for r in inventory)
    assert all(paid[r["request"]]["timestamp"] >= RUN_START for r in inventory)

    def cost(reqs):
        i = sum(paid[q]["input_tokens"] for q in reqs)
        o = sum(paid[q]["output_tokens"] for q in reqs)
        return i, o, (i * p_in + o * p_out) / 1e6

    docs = {}
    for r in inventory:
        docs.setdefault("-".join(r["tag"].split("-")[:2]), {}).setdefault(category(r["tag"]), set()).add(r["request"])
    print(f"\n# Cost per document ({model}, ${p_in}/M input, ${p_out}/M output; each request priced at its paid call)")
    for method, cats in METHODS.items():
        per = [cost(set().union(*(d.get(c, set()) for c in cats))) for d in docs.values()]
        usd = [c[2] for c in per]
        print(f"{method}: {len(per)} documents; mean ${statistics.mean(usd):.4f}, median ${statistics.median(usd):.4f}, "
              f"min ${min(usd):.4f}, max ${max(usd):.4f}; mean tokens {statistics.mean(c[0] for c in per):,.0f} in, "
              f"{statistics.mean(c[1] for c in per):,.0f} out; total ${sum(usd):.2f}")
    seeded = [d for d in docs.values() if d.get("extra_seeds")]
    gross = [cost(d["extra_seeds"])[2] for d in seeded]
    new = [cost(d["extra_seeds"] - set().union(*(d.get(c, set()) for c in METHODS["engine"])))[2] for d in seeded]
    print(f"pairing seeds 1 and 2 (seed-spread diagnostic, sampled documents only): {len(seeded)} documents; "
          f"all their requests: mean ${statistics.mean(gross):.4f}, total ${sum(gross):.2f}; "
          f"requests not already made for seed 0: mean ${statistics.mean(new):.4f}, total ${sum(new):.2f}")
    shared = [(t, c, q) for t, d in docs.items() for c, reqs in d.items() for q in reqs
              if sum(q in other for other in d.values()) > 1]
    print(f"requests listed under more than one category of their document: {len(shared)} "
          f"({sorted({c for _, c, _ in shared})})")
    across = {}
    for t, d in docs.items():
        for q in set().union(*d.values()):
            across.setdefault(q, set()).add(t)
    doc_ids = {"text-" + hashlib.sha256(r["text"].encode("utf-8")).hexdigest()[:12]: r["doc_id"]
               for r in jsonl(ROOT / "data" / "consistency" / "corpus.jsonl")}
    tags = {(r["request"], "-".join(r["tag"].split("-")[:2])): r["tag"].split("-", 2)[2] for r in inventory}
    for q, ts in across.items():
        if len(ts) > 1:
            print(f"request {q} is shared by " + ", ".join(f"{doc_ids[t]} ({tags[q, t]})" for t in sorted(ts))
                  + f": {paid[q]['input_tokens'] + paid[q]['output_tokens']:,} tokens, ${cost({q})[2]:.4f}")
    for label, sampled in (("all pairs scored (<= 25 claims)", False), ("pairs sampled (> 25 claims)", True)):
        e = [cost(set().union(*(d.get(c, set()) for c in METHODS["engine"])))[2]
             for d in docs.values() if bool(d.get("pairs")) is sampled]
        print(f"engine, {label}: {len(e)} documents, mean ${statistics.mean(e):.4f}")
    everything = set().union(*(reqs for d in docs.values() for reqs in d.values()))
    i, o, usd = cost(everything)
    print(f"all requests of the run: {len(everything)} distinct, {i:,} input + {o:,} output tokens, ${usd:.2f}")
    parts = {m: sum(cost(set().union(*(d.get(c, set()) for c in METHODS[m])))[2] for d in docs.values())
             for m in ("engine", "llm_direct_thinking", "llm_direct_no_thinking")}
    print(f"reconciliation: engine ${parts['engine']:.4f} + LLM-direct ${parts['llm_direct_thinking']:.4f} "
          f"+ ${parts['llm_direct_no_thinking']:.4f} + new seed requests ${sum(new):.4f} = "
          f"${sum(parts.values()) + sum(new):.4f}, against ${usd:.4f}")


def contamination(rows):
    print("\n# Planted-cycle pairs the relation judge labeled contradicts")
    n = 0
    for r in rows:
        if r["variant"] != "cycle":
            continue
        hits = [p for p in r["planted_pair_relations"] if p[2] == "contradicts"]
        if not hits:
            continue
        a = analysis(r["doc_id"])
        claims = {c["id"]: c for c in a["claims"]}
        rels = {tuple(sorted((x["a"], x["b"]))): x for x in a["relations"]}
        print(f"\n## {r['doc_id']}, {r['cycle_type']}; engine clauses {r['engine_clauses']}")
        for i, j, _, _ in hits:
            n += 1
            print(f"[{n}] {claim_line(claims, i)}\n    {claim_line(claims, j)}\n    {relation_line(rels, i, j)}")
    print(f"\n{n} pairs")


def main():
    rows = jsonl(RUN / "documents.jsonl")
    false_positives(rows)
    costs()
    contamination(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
