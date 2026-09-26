"""The budget estimate of A1 rev. 2.2's development iteration 1 (XON_A1_REV2_2_PRECISION.md §7.3), with no API call.

    python scripts/estimate_rev22_budget.py

Iteration 1 changes only the entity extraction (§5): its gate D0 and full pass send the entity steps for every
document (the inventory call, the relations call, and the coverage call where the net finds an uncovered claim).
Claims, pair selections and the relation calls, whose requests are unchanged, are answered from the cache; each
relation request is checked. L1-var 2.2 (§8.1) sends the subset's relation calls and entity steps three times with
the cache bypassed. Iteration 0's version of this script is in the git history, and its output in results/.

Per document:
- input tokens: least squares of input tokens on request characters (system, message and output schema) over the
  structured requests rebuilt from the cache (claim extraction, pair selection and rev. 2.1's entity call from the run
  of record, rev. 2.2's relation calls from iteration 0), each call type weighted equally, applied to each step's
  request. The inventory request is exact. The relations and coverage requests are built from iteration 0's
  statements for the same document: its entities and attributes stand in for the inventory, and the coverage net is
  applied to its statements.
- visible output tokens: iteration 0's measured entity-call output tokens per character of its statements, applied to
  the part each step returns; a none entry counts NONE_TOKENS.
- thinking tokens: rev. 2.1 LLM-direct's measured adaptive thinking per call on the same corpus, in three scenarios
  (its mean, 90th percentile and maximum); max_tokens bounds any single call.
- L1-var's relation calls: each request's measured usage in the cache (and its re-score's, where iteration 0 made
  one), three times.
The gate compares the full pass with what is left of A1's cap (45,000,000 tokens less the API tokens in
cache/llm/log.jsonl); the spec's 4,000,000-token limit on the full pass is lifted (decisions.md). Read-only: nothing
is appended to the call log.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xon.config import LLM_BATCH_PRICE_MULT  # noqa: E402
from xon.llm import prompts  # noqa: E402
from xon.llm.claims import (_coverage_call, _relations_call, candidate_pairs, claims_with_statements,  # noqa: E402
                            extract_claims, extract_entity_relations, inventory_ids, lexicon_claims,
                            planned_requests_v22, text_tag, v22_tag)
from xon.llm.client import LLM, LOG_NAME, cost_usd, request_key  # noqa: E402
from xon.llm.corpus import SAMPLE_BASES  # noqa: E402
from xon.llm.devpass import REPEATS  # noqa: E402
from xon.llm.schemas import EntityGraphSpecV22, EntityRelationsV22, InventoryV22  # noqa: E402

A1_CAP = 45_000_000              # decisions.md, 2026-09-25: rev. 2.2's budget
PASS_LIMIT = 4_000_000           # §7.3's limit on the full pass, lifted by the same decision
CACHE_MIN_TOKENS = 1024          # Claude docs, prompt caching: the minimum cacheable prompt on Sonnet models
NONE_TOKENS = 30                 # a none entry: a claim number and a one-sentence reason
SLOW_S = 60                      # calls slower than this (a stalled connection) are left out of the duration fit
ITERATION0 = ROOT / "results" / "a1-rev22-full-20260925-124414"
REQUEST_ARGS = ("system", "user", "max_tokens", "thinking", "schema", "cache_system")
STEPS = ("inventory", "relations", "coverage")


def chars_of(body: dict) -> int:
    """The request characters the budget pre-check counts: system, messages and the output schema."""
    system = body["system"] if isinstance(body["system"], str) else "".join(b["text"] for b in body["system"])
    return (len(system) + sum(len(m["content"]) for m in body["messages"])
            + (len(json.dumps(body["output_config"])) if "output_config" in body else 0))


def compact(value) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False))


def fit(x, y, w=None) -> tuple[float, float]:
    """(intercept, slope) of the least-squares line y = a + b x, each point weighted by w."""
    b, a = np.polyfit(np.asarray(x, float), np.asarray(y, float), 1,
                      w=None if w is None else np.sqrt(np.asarray(w, float)))
    return float(a), float(b)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=str(ROOT / "data" / "consistency" / "corpus.jsonl"))
    ap.add_argument("--cache", default=str(ROOT / "cache" / "llm"))
    ap.add_argument("--iteration0", default=str(ITERATION0), help="iteration 0's full pass (its analyses)")
    ap.add_argument("--out", default=None,
                    help="JSON output (default: results/a1-rev22-estimate-iter1-<date>-<time>.json)")
    args = ap.parse_args(argv)
    cache = Path(args.cache)
    records = [json.loads(line) for line in Path(args.corpus).read_text("utf-8").splitlines() if line.strip()]
    log = [json.loads(line) for line in (cache / LOG_NAME).read_text("utf-8").splitlines() if line.strip()]
    api = [r for r in log if r.get("source") == "api"]
    spent = sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in api)
    remaining = A1_CAP - spent
    iter0_output = {r["tag"]: r["output_tokens"] for r in api if r["tag"].endswith("-v22-entities")}
    direct = [r for r in api if "-direct" in r["tag"] and r.get("thinking") == "adaptive"]
    thinking = sorted(r.get("thinking_tokens", 0) for r in direct)
    scenarios = {"mean": sum(thinking) / len(thinking), "p90": thinking[int(0.9 * (len(thinking) - 1))],
                 "max": thinking[-1]}
    direct_ids = {id(r) for r in direct}
    timed = [r for r in api if (r["tag"].endswith("-v22-entities") or id(r) in direct_ids)
             and r["duration_s"] <= SLOW_S]
    per_call_s = fit([r["output_tokens"] for r in timed], [r["duration_s"] for r in timed])
    relate_s = [r["duration_s"] for r in api if "-v22-relate" in r["tag"]]

    llm = LLM(cache_dir=cache, budget_tokens=0)
    llm._log = lambda *a, **k: None
    wk = llm.cfg.llm_world_knowledge
    captured = []
    send = llm._call

    def capture(body, schema, tag, thinking, bypass_cache, attempt=1):
        captured.append((tag, body, request_key(body, attempt)))
        return send(body, schema, tag, thinking, bypass_cache, attempt)

    llm._call = capture
    points = {"extract": [], "pairs": [], "entities_v21": [], "relate_v22": []}
    docs = []
    for rec in records:
        tag = text_tag(rec["text"])
        stem = v22_tag(tag)
        start = len(captured)
        claims = extract_claims(llm, rec["text"], tag=stem)
        pairs, _ = candidate_pairs(llm, claims, tag=tag, seed=0, world_knowledge=wk, fixture_tag=stem)
        extract_entity_relations(llm, claims, tag=tag)
        for t, body, key in captured[start:]:
            kind = "entities_v21" if t.endswith("-entities") else "pairs" if t.endswith("-pairs") else "extract"
            points[kind].append((chars_of(body), llm._read_cache(key)["usage"]["input_tokens"]))
        planned = planned_requests_v22(llm, claims, pairs, tag=stem, world_knowledge=wk)
        relate, inventory = [p[0] for p in planned[:-1]], planned[-1][0]
        measured = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0}
        uncached = 0
        for body in relate:
            hit = llm._read_cache(request_key(body))
            if hit is None:
                uncached += 1
                continue
            points["relate_v22"].append((chars_of(body), hit["usage"]["input_tokens"]))
            for record in (hit, llm._read_cache(request_key(body, 2))):     # the re-score, if iteration 0 made one
                if record is not None:
                    measured["calls"] += 1
                    measured["input_tokens"] += record["usage"]["input_tokens"]
                    measured["output_tokens"] += record["usage"]["output_tokens"]
                    measured["usd"] += cost_usd(llm.model, record["usage"])
        analysis = json.loads((Path(args.iteration0) / "analyses" / f"{rec['doc_id']}.json").read_text("utf-8"))
        assert len(analysis["claims"]) == len(claims.claims), rec["doc_id"]
        spec = EntityGraphSpecV22.model_validate(analysis["entity_relations"])
        entities, attributes = inventory_ids(InventoryV22(entities=spec.entities, attributes=spec.attributes))
        answer = EntityRelationsV22.model_validate({
            "same_different": [s.model_dump() for s in spec.same_different],
            "orders": [s.model_dump() for s in spec.orders],
            "extremes": [dict(s.model_dump(), restriction=None) for s in spec.extremes],
            "senses": [s.model_dump() for s in spec.senses],
            "unsupported_order_claims": list(spec.unsupported_order_claims)})
        steps = {"inventory": {"chars": chars_of(inventory),
                               "output_chars": compact({"entities": [e.model_dump() for e in spec.entities],
                                                        "attributes": [a.model_dump() for a in spec.attributes]})},
                 "relations": None, "coverage": None}
        uncovered = []
        if entities and attributes:
            call = _relations_call(llm, claims, entities, attributes, tag=stem)
            steps["relations"] = {"chars": chars_of(llm.request(**{k: call[k] for k in REQUEST_ARGS})),
                                  "output_chars": compact(answer.model_dump())}
            uncovered = [c for c in lexicon_claims(claims) if c not in claims_with_statements(answer)]
            if uncovered:
                call = _coverage_call(llm, claims, uncovered, entities, attributes, tag=stem)
                steps["coverage"] = {"chars": chars_of(llm.request(**{k: call[k] for k in REQUEST_ARGS})),
                                     "output_tokens": NONE_TOKENS * len(uncovered)}
        docs.append({"doc_id": rec["doc_id"], "base": rec["base"], "claims": len(claims.claims),
                     "relation_calls": len(relate), "relation_calls_uncached": uncached, "relate_measured": measured,
                     "iteration0_output_tokens": iter0_output.get(f"{stem}-entities"),
                     "iteration0_output_chars": compact(spec.model_dump()), "lexicon_claims": lexicon_claims(claims),
                     "uncovered": uncovered, "steps": steps})
    del llm._call

    a, b = fit(*zip(*[(c, t) for pts in points.values() for c, t in pts]),
               w=[1 / len(pts) for pts in points.values() for _ in pts])
    fit_error = {k: float(np.mean([abs(a + b * c - t) / t for c, t in pts])) for k, pts in points.items()}
    # the schemas make requests denser than prose: within claim extraction only the document's text varies
    prose_per_char = fit(*zip(*points["extract"]))[1]
    relate_rows = [r for r in api if "-v22-relate" in r["tag"]]
    relate_cached_tokens = sum(r.get("cache_write_tokens", 0) + r.get("cache_read_tokens", 0) for r in relate_rows)
    with_output = [d for d in docs if d["iteration0_output_tokens"]]
    per_char = sum(d["iteration0_output_tokens"] for d in with_output) / sum(d["iteration0_output_chars"]
                                                                            for d in with_output)
    for d in docs:
        for name, s in d["steps"].items():
            if s is not None:
                s["input_tokens"] = a + b * s["chars"]
                s["output_tokens"] = s.get("output_tokens", per_char * s.get("output_chars", 0))

    price = LLM_BATCH_PRICE_MULT

    def usd(tin, tout) -> float:
        return cost_usd(llm.model, {"input_tokens": tin, "output_tokens": tout})

    def entity_steps(rs, think: float) -> dict:
        calls = [s for d in rs for s in d["steps"].values() if s is not None]
        inv = [d["steps"]["inventory"] for d in rs]
        tin, tout = sum(s["input_tokens"] for s in calls), sum(s["output_tokens"] + think for s in calls)
        inv_usd = usd(sum(s["input_tokens"] for s in inv), sum(s["output_tokens"] + think for s in inv))
        seconds = sum(per_call_s[0] + per_call_s[1] * (s["output_tokens"] + think) for s in calls)
        return {"calls": len(calls), "by_step": {n: sum(d["steps"][n] is not None for d in rs) for n in STEPS},
                "input_tokens": round(tin), "output_tokens": round(tout), "tokens": round(tin + tout),
                "usd": usd(tin, tout), "batch_saving_usd": inv_usd * (1 - price),
                "max_tokens_bound": round(tin + len(calls) * llm.cfg.llm_max_tokens_entity_steps),
                "sequential_hours": seconds / 3600}

    subset = [d for d in docs if d["base"] in SAMPLE_BASES]
    after_d0 = [d for d in docs if d["base"] not in SAMPLE_BASES]
    relate_l1var = {k: REPEATS * sum(d["relate_measured"][k] for d in subset) for k in ("calls", "input_tokens",
                                                                                        "output_tokens", "usd")}
    relate_l1var["tokens"] = relate_l1var["input_tokens"] + relate_l1var["output_tokens"]
    relate_l1var["batch_saving_usd"] = relate_l1var["usd"] * (1 - price)
    relate_l1var["hours_at_concurrency"] = (relate_l1var["calls"] * float(np.mean(relate_s))
                                            / llm.cfg.llm_concurrency / 3600)
    by_scenario = {}
    for name, think in scenarios.items():
        d0, full, rest = entity_steps(subset, think), entity_steps(docs, think), entity_steps(after_d0, think)
        l1var_steps = {k: v * REPEATS if isinstance(v, (int, float)) else v for k, v in d0.items()}
        l1var_tokens = relate_l1var["tokens"] + l1var_steps["tokens"]
        total = d0["tokens"] + rest["tokens"] + l1var_tokens
        by_scenario[name] = {"thinking_tokens_per_call": think, "d0": d0, "full": full, "full_after_d0": rest,
                             "l1var_entity_steps": l1var_steps,
                             "l1var_tokens": l1var_tokens, "l1var_usd": relate_l1var["usd"] + l1var_steps["usd"],
                             "iteration_1_tokens": total, "iteration_1_usd": d0["usd"] + rest["usd"]
                             + relate_l1var["usd"] + l1var_steps["usd"],
                             "fits_remaining": total <= remaining}
    system_tokens = {"relate": prose_per_char * len(prompts.relate_system_v2_2(False)),
                     "entity_inventory": prose_per_char * len(prompts.ENTITY_INVENTORY_SYSTEM_V2_2),
                     "entity_relations": prose_per_char * len(prompts.ENTITY_RELATIONS_SYSTEM_V2_2),
                     "entity_coverage": prose_per_char * len(prompts.ENTITY_COVERAGE_SYSTEM_V2_2)}
    high = by_scenario["max"]["full"]["tokens"]
    res = {"model": llm.model, "iteration": 1,
           "fits": {"input_intercept": a, "input_per_char": b, "input_mean_relative_error": fit_error,
                    "calls_fitted": {k: len(v) for k, v in points.items()},
                    "output_tokens_per_statement_char": per_char, "none_tokens": NONE_TOKENS,
                    "seconds_per_call": {"intercept": per_call_s[0], "per_output_token": per_call_s[1],
                                         "calls_fitted": len(timed)},
                    "relation_call_seconds_mean": float(np.mean(relate_s))},
           "thinking": {"source": "rev. 2.1 LLM-direct with adaptive thinking, measured", "calls": len(thinking),
                        "scenarios": scenarios, "median": thinking[len(thinking) // 2],
                        "max_tokens_per_entity_call": llm.cfg.llm_max_tokens_entity_steps},
           "relation_calls": {"planned": sum(d["relation_calls"] for d in docs),
                              "uncached": sum(d["relation_calls_uncached"] for d in docs)},
           "iteration0_entity_calls": {"calls": len(iter0_output),
                                       "input_tokens_mean": float(np.mean([r["input_tokens"] for r in api
                                                                           if r["tag"].endswith("-v22-entities")])),
                                       "output_tokens_mean": float(np.mean(list(iter0_output.values())))},
           "coverage_net_on_iteration0": {"documents": sum(bool(d["uncovered"]) for d in docs),
                                          "lexicon_claims": sum(len(d["lexicon_claims"]) for d in docs),
                                          "uncovered_claims": sum(len(d["uncovered"]) for d in docs)},
           "l1var_relation_calls": relate_l1var, "scenarios": by_scenario,
           "prompt_cache": {"prose_tokens_per_char": prose_per_char, "system_tokens_estimated": system_tokens,
                            "minimum_cacheable_tokens": CACHE_MIN_TOKENS,
                            "applies": {k: v >= CACHE_MIN_TOKENS for k, v in system_tokens.items()},
                            "iteration0_relation_calls": len(relate_rows),
                            "iteration0_relation_cache_tokens": relate_cached_tokens},
           "batch": {"price_multiplier": price,
                     "batchable": "in D0 and the full pass, the inventory calls only (the relation calls are "
                                  "answered from the cache; the relations and coverage calls need the inventory's "
                                  "answer); in L1-var, the relation calls too",
                     "decision": "synchronous calls (decisions.md, 2026-09-25: rev. 2.2's budget)"},
           "a1": {"cap": A1_CAP, "spent": spent, "remaining": remaining},
           "gate": {"pass_limit": PASS_LIMIT, "pass_limit_lifted": True, "full_tokens_max_thinking": high,
                    "exceeds_remaining_cap": high > remaining, "stop": high > remaining},
           "documents": docs}
    out = Path(args.out) if args.out else ROOT / "results" / (
        f"a1-rev22-estimate-iter1-{time.strftime('%Y%m%d-%H%M%S')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1), "utf-8")

    print(f"Relation calls: {res['relation_calls']['planned']:,} planned, {res['relation_calls']['uncached']:,} not "
          "in the cache.")
    print(f"Input fit: {a:.0f} + {b:.4f}/char over {sum(len(v) for v in points.values()):,} calls; mean relative "
          f"error " + ", ".join(f"{k} {v:.1%}" for k, v in fit_error.items()) + ".")
    print(f"Thinking per call (LLM-direct, {len(thinking)} calls): mean {scenarios['mean']:.0f}, 90th percentile "
          f"{scenarios['p90']}, max {scenarios['max']}; max_tokens {llm.cfg.llm_max_tokens_entity_steps:,}.")
    net = res["coverage_net_on_iteration0"]
    print(f"Coverage net on iteration 0's statements: {net['uncovered_claims']} of {net['lexicon_claims']} lexicon "
          f"claims uncovered, a follow-up in {net['documents']} of {len(docs)} documents.")
    for name, s in by_scenario.items():
        print(f"Thinking at its {name} ({s['thinking_tokens_per_call']:.0f} per call):")
        for label, t in (("D0 (12 documents)", s["d0"]), ("Full pass (180)", s["full"]),
                         ("Full pass after D0 (168)", s["full_after_d0"])):
            print(f"  {label}: {t['calls']:,} entity calls, {t['tokens']:,} tokens ({t['input_tokens']:,} in, "
                  f"{t['output_tokens']:,} out), ${t['usd']:.2f}; about {t['sequential_hours']:.1f} h sequential.")
        print(f"  L1-var 2.2: {s['l1var_tokens']:,} tokens, ${s['l1var_usd']:.2f}. Iteration 1 in all "
              f"(D0, the full pass after it, L1-var): {s['iteration_1_tokens']:,} tokens, ${s['iteration_1_usd']:.2f}"
              f" ({'fits' if s['fits_remaining'] else 'does not fit'} in the {remaining:,} left).")
    print(f"L1-var's relation calls: {relate_l1var['calls']:,} calls, {relate_l1var['tokens']:,} tokens, "
          f"${relate_l1var['usd']:.2f} (measured usage x{REPEATS}); about {relate_l1var['hours_at_concurrency']:.1f} h "
          f"at concurrency {llm.cfg.llm_concurrency}.")
    print(f"Prompt cache: at {prose_per_char:.3f} tokens per character of prose, system prompts of about "
          + ", ".join(f"{k} {v:.0f}" for k, v in system_tokens.items())
          + f" tokens; the minimum is {CACHE_MIN_TOKENS}, so caching applies to "
          + (", ".join(k for k, v in res["prompt_cache"]["applies"].items() if v) or "none")
          + f". Iteration 0's {len(relate_rows):,} relation calls wrote or read {relate_cached_tokens:,} cached tokens.")
    mean = by_scenario["mean"]
    print(f"Batches: half price. D0 and the full pass could batch only their inventory calls (saving "
          f"${mean['d0']['batch_saving_usd'] + mean['full_after_d0']['batch_saving_usd']:.2f} at the mean); L1-var's "
          f"relation calls would save ${relate_l1var['batch_saving_usd']:.2f}. Decided: synchronous.")
    print(f"A1: {spent:,} of {A1_CAP:,} tokens spent, {remaining:,} left; the full pass at the maximum thinking, "
          f"{high:,} tokens: {'STOP, no calls' if res['gate']['stop'] else 'within the cap'} (the 4,000,000 limit "
          "is lifted).")
    print(f"Written to {out}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
