"""A1 corpus generator (XON_A1_CONSISTENCY.md §5, rev. 2.1). Makes live API calls for every response that is neither
cached nor recorded, within the session's token budget.

    python scripts/make_consistency_corpus.py --sample                    # 12 documents: stop for review (§8 step 6)
    python scripts/make_consistency_corpus.py --sample-reviewed           # all 60 base documents x 3 variants
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xon.llm.client import LLM  # noqa: E402
from xon.llm.corpus import N_BASE, SAMPLE_BASES, generate, plan, record_to_dict  # noqa: E402

# Fixed before any full-corpus leak-scan flags are seen (re-specification 11 review rule): used to draw the
# 10% unflagged spot-check. Do not change after the first full-corpus run of record.
REVIEW_SEED = 20260923


def review_protocol(stats: dict, n_base: int = N_BASE) -> dict:
    """Every flagged base, plus a fixed-seed 10% of unflagged bases, for the user's review before acceptance."""
    import numpy as np
    flagged = sorted(int(b) for b in stats.get("leak_flags", {}))
    failed = {int(b) for b in stats.get("failed", {})}
    unflagged = [b for b in range(n_base) if b not in set(flagged) and b not in failed]
    n_spot = max(1, round(0.1 * len(unflagged))) if unflagged else 0
    spot = sorted(np.random.default_rng(REVIEW_SEED).choice(unflagged, size=n_spot, replace=False).tolist()
                  ) if n_spot else []
    return {"review_seed": REVIEW_SEED, "flagged_bases": flagged,
            "unflagged_spot_check": spot, "n_unflagged": len(unflagged), "n_spot_check": n_spot,
            "failed_bases": sorted(failed)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sample", action="store_true", help="generate the 12-document review sample only")
    ap.add_argument("--sample-reviewed", action="store_true",
                    help="confirm the review sample was reviewed; required for the full corpus")
    ap.add_argument("--out", default=str(ROOT / "data" / "consistency"), help="output directory")
    ap.add_argument("--budget", type=int, default=None, help="token budget of this run (default: the config's)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if not args.sample and not (args.sample_reviewed and (out / "sample.jsonl").exists()):
        print("The full corpus needs the review sample first: run with --sample, have it reviewed, then run with "
              "--sample-reviewed.", file=sys.stderr)
        return 2
    name = "sample" if args.sample else "corpus"
    plans = [plan(b) for b in (SAMPLE_BASES if args.sample else range(N_BASE))]
    llm = LLM(budget_tokens=args.budget)
    records, stats = generate(llm, plans, qa_scan=True)
    meta = {"model": llm.model, **stats, "usage": llm.usage}
    if not args.sample:
        meta["review"] = review_protocol(stats)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.jsonl").write_text("".join(json.dumps(record_to_dict(r), ensure_ascii=False) + "\n"
                                               for r in records), "utf-8")
    (out / f"{name}_generation.json").write_text(json.dumps(meta, indent=1), "utf-8")
    print(f"{len(records)} documents from {len(plans)} base documents; regenerated {stats['regenerated']}, "
          f"failed {len(stats['failed'])}; {llm.usage['spent_tokens']:,} tokens, about "
          f"${llm.usage['estimated_cost_usd']:.2f}. Written to {out}.")
    if stats["leak_flags"]:
        print(f"The leak-scan pass flagged {sum(len(v) for v in stats['leak_flags'].values())} sentence(s) across "
              f"{len(stats['leak_flags'])} base document(s); see {name}_generation.json's leak_flags. Not "
              "auto-regenerated.", file=sys.stderr)
    if not args.sample and "review" in meta:
        r = meta["review"]
        print(f"Review protocol (seed {r['review_seed']}): {len(r['flagged_bases'])} flagged base(s); "
              f"spot-check {r['n_spot_check']} of {r['n_unflagged']} unflagged: {r['unflagged_spot_check']}.")
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
