"""A1 experiments L1, L1b and L1-var (XON_A1_CONSISTENCY.md §6, rev. 2.1). Makes live API calls for every response
that is neither cached nor recorded, within the session's token budget.

    python scripts/run_consistency_eval.py                  # L1 and L1b on the full corpus: the run of record
    python scripts/run_consistency_eval.py --subset         # L1 and L1b on the 12-document subset (runs on fixtures)
    python scripts/run_consistency_eval.py --l1var          # L1-var on the 12-document subset (live calls only)

L1-var saves every response of every repetition to <out>/l1var/, one file per call, and records no fixtures;
scripts/recompute_l1var.py recomputes the variance analysis from that folder with no API calls.

Before L1 and L1b are scored, the unscored pairs are checked: if more than 1% of the pairs requested at seed 0 have no
relation, the run reports them per document and stops with exit code 3, having scored nothing. --accept-unscored
scores them anyway, and run.json records it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xon.llm.client import LLM, LLMError  # noqa: E402
from xon.llm.corpus import SAMPLE_BASES  # noqa: E402
from xon.llm.engine import analysis_to_dict  # noqa: E402
from xon.llm.evaluation import (SEEDS, document_row, l1_markdown, l1b_markdown, l1var_markdown,  # noqa: E402
                                of_record, run_corpus, run_l1var, score_l1, score_l1b, score_l1var, unscored_markdown,
                                unscored_report)


def _plain(value):
    """A NumPy scalar as its Python value: the scores compare NumPy floats, and json cannot write a NumPy bool."""
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _json(value, **kw) -> str:
    return json.dumps(value, default=_plain, **kw)


def _jsonl(rows) -> str:
    return "".join(_json(r, ensure_ascii=False) + "\n" for r in rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=str(ROOT / "data" / "consistency" / "corpus.jsonl"), help="corpus JSONL")
    ap.add_argument("--subset", action="store_true", help=f"only the base documents {list(SAMPLE_BASES)}")
    ap.add_argument("--l1var", action="store_true", help="L1-var on the 12-document subset, instead of L1 and L1b")
    ap.add_argument("--out", default=None, help="output directory (default: results/a1-<date>-<time>)")
    ap.add_argument("--budget", type=int, default=None, help="token budget of this run (default: the config's)")
    ap.add_argument("--accept-unscored", action="store_true",
                    help="score L1 and L1b even if more than 1%% of the requested pairs are unscored")
    args = ap.parse_args(argv)
    path = Path(args.corpus)
    if not path.exists():
        print(f"No corpus at {path}: generate it with scripts/make_consistency_corpus.py.", file=sys.stderr)
        return 2
    records = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
    subset = args.subset or args.l1var
    if subset:
        records = [r for r in records if r["base"] in SAMPLE_BASES]
    llm = LLM(budget_tokens=args.budget)
    out = Path(args.out) if args.out else ROOT / "results" / f"a1-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        runs = run_corpus(llm, records)
        var_rows = run_l1var(llm, runs, raw_dir=out / "l1var") if args.l1var else None
    except LLMError as exc:
        print(f"{type(exc).__name__}: {exc}", *getattr(exc, "__notes__", []), f"{llm.usage['spent_tokens']:,} tokens "
              "spent; the completed calls are cached.", sep="\n", file=sys.stderr)
        return 1
    rows = [document_row(r) for r in runs]
    judged, why_not = of_record(rows, llm.model, subset)
    out.mkdir(parents=True, exist_ok=True)
    run = {"engine_version": "2.1", "corpus": str(path), "documents": len(records), "subset": subset,
           "model": llm.model, "dry_run": llm.dry_run, "of_record": judged, "not_of_record_because": why_not}
    if var_rows is None:
        gate = dict(unscored_report(rows), accepted=bool(args.accept_unscored))
        run["unscored_gate"] = gate
        if gate["stop"] and not args.accept_unscored:
            (out / "unscored_gate.json").write_text(_json(gate, indent=1), "utf-8")
            (out / "run.json").write_text(_json(dict(run, stopped="unscored pairs", usage=llm.usage), indent=1),
                                          "utf-8")
            print(unscored_markdown(gate))
            print(f"\nStopped before L1 and L1b were scored. Written to {out}.", file=sys.stderr)
            return 3
    (out / "documents.jsonl").write_text(_jsonl(rows), "utf-8")
    if var_rows is not None:
        res = {"l1var": score_l1var(var_rows)}
        (out / "l1var_repeats.jsonl").write_text(_jsonl(var_rows), "utf-8")
        text = l1var_markdown(res["l1var"])
    else:
        res = {"l1": score_l1(rows, judged), "l1b": score_l1b(rows, judged)}
        (out / "analyses").mkdir(exist_ok=True)
        for r in runs:
            (out / "analyses" / f"{r.record['doc_id']}.json").write_text(
                _json(analysis_to_dict(r.analyses[SEEDS[0]]), indent=1, ensure_ascii=False), "utf-8")
        text = l1_markdown(res["l1"], why_not) + "\n\n" + l1b_markdown(res["l1b"], why_not)
    for name, value in res.items():
        (out / f"{name}.json").write_text(_json(value, indent=1), "utf-8")
    (out / "run.json").write_text(_json(dict(run, usage=llm.usage), indent=1), "utf-8")
    (out / "results.md").write_text(f"Engine version {run['engine_version']}.\n\n" + text + "\n", "utf-8")
    print(text)
    print(f"\n{llm.usage['spent_tokens']:,} tokens, about ${llm.usage['estimated_cost_usd']:.2f}. Written to {out}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
