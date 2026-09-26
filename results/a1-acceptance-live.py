"""The two paragraph checks of XON_A1_CONSISTENCY.md §9 that need a key set, run through the engine as the Consistency
view runs them (world knowledge off, recording off). Responses are cached, so running this again replays them.

    python results/a1-acceptance-live.py > results/a1-acceptance-live.txt
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xon.llm.baselines import pairwise_only  # noqa: E402
from xon.llm.client import LLM, RECORD_ENV  # noqa: E402
from xon.llm.engine import analyze_text  # noqa: E402

TEAMS = "Ana and Ben were on different teams, Ben and Cy were on different teams, and Ana and Cy were on different teams."
ORDER = "Ana is older than Ben. Ben is older than Cy. Cy is older than Ana."
THREE_TEAMS = f"There were three teams. {TEAMS}"
TWO_TEAMS = f"There were two teams. {TEAMS}"
BUDGET = 50_000


def contradiction(e) -> str:
    return f"{e.type} on {e.attribute} over {e.entities}, claims {e.claim_ids}, min confidence {e.min_confidence}"


def show(name: str, a) -> bool:
    rep = a.report
    flagged, pairs = pairwise_only(a.graph)
    print(f"\n## {name}\n{a.text}\nclaims:")
    for c in a.claims.claims:
        print(f"  {c.id} ({c.kind}): {c.text}")
    print("relations:")
    for r in a.relations.relations:
        print(f"  {r.a}-{r.b}: {r.relation} {r.confidence} | {r.rationale}")
    print("attributes: " + ", ".join(f"{t.key} ({t.arity}; {t.arity_span!r})" for t in a.entity_spec.attributes))
    print("entity relations:")
    for r in a.entity_spec.relations:
        print(f"  claim {r.claim_id}: {r.attribute} {r.kind}({r.a}, {r.b}) {r.confidence}")
    print(f"verdict_inconsistent: {rep.verdict_inconsistent}; clauses: {rep.verdict_clauses}")
    print("entity contradictions in the verdict: "
          + ("; ".join(map(contradiction, rep.verdict_entity_contradictions)) or "none"))
    print(f"pairwise baseline: {f'inconsistent, pairs {pairs}' if flagged else 'nothing reported'}")
    return flagged


def main() -> int:
    if os.environ.get(RECORD_ENV):
        raise SystemExit(f"{RECORD_ENV} is set: these checks run with recording off.")
    llm = LLM(budget_tokens=BUDGET)
    if llm.dry_run:
        raise SystemExit("No API key in the environment: these checks need a key set.")
    print(f"# XON_A1_CONSISTENCY.md §9, the checks with a key set ({llm.model}, world knowledge off)")
    order = analyze_text(llm, ORDER, world_knowledge=False)
    order_pairwise = show("Order cycle", order)
    three = analyze_text(llm, THREE_TEAMS, world_knowledge=False)
    show("Three teams", three)
    two = analyze_text(llm, TWO_TEAMS, world_knowledge=False)
    show("Two teams", two)

    ids = {c.id for c in order.claims.claims}
    cycle = [e for e in order.report.verdict_entity_contradictions
             if e.type == "order_cycle" and set(e.claim_ids) == ids and len(ids) == 3]
    item2 = order.report.verdict_inconsistent and "entity" in order.report.verdict_clauses and bool(cycle) \
        and not order_pairwise
    item3 = not three.report.verdict_inconsistent and two.report.verdict_inconsistent
    print(f"\nItem 2 (order cycle: inconsistent, clause entity, an order cycle naming all three claims, pairwise "
          f"reports nothing): {'met' if item2 else 'NOT met'}")
    print(f"Item 3 (three teams not flagged, two teams flagged): {'met' if item3 else 'NOT met'}")
    u = llm.usage
    print(f"\nAPI calls {u['api_calls']}, cache hits {u['cache_hits']}; {u['input_tokens']:,} input and "
          f"{u['output_tokens']:,} output tokens; about ${u['estimated_cost_usd']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
