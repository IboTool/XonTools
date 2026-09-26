"""A1 rev. 2.2's development pass on the seen L1 corpus (XON_A1_REV2_2_PRECISION.md §7, §8). Makes live API calls
for every rev. 2.2 response that is neither cached nor recorded, within the session's token budget. Every number it
writes is a rev. 2.2 development number on the seen L1 corpus, not a result of record.

    python scripts/run_rev22_dev.py --subset --budget N             # gate D0: the 12-document subset
    python scripts/run_rev22_dev.py --budget N                      # a full pass, after D0 and the go-ahead
    python scripts/run_rev22_dev.py --budget N --final              # the final iteration: applies the §6 rule
    python scripts/run_rev22_dev.py --subset --l1var --budget N     # §8.1, L1-var under rev. 2.2 (live calls only)

Claims and pair selections come from the run of record's cache (seed 0), and so do rev. 2.1's rows, with a budget of
0, so that a missing response stops the run instead of calling. LLM-direct is carried from the run of record's rows.
--batch sends the pass's first attempts as one Message Batch at half price and waits for it; the synchronous pass then
answers them from the cache. With XON_LLM_RECORD=1 the calls are recorded as fixtures under "-v22" tags.

If more than 1% of the requested pairs are left unscored, the run reports them and stops with exit code 3 before
anything is scored; --accept-unscored scores them anyway, and run.json records it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xon.config import DEFAULT, REV22_ITERATION  # noqa: E402
from xon.llm.client import LLM, BatchRunner, LLMError  # noqa: E402
from xon.llm.corpus import SAMPLE_BASES  # noqa: E402
from xon.llm.devpass import (LABEL, dev_markdown, dev_row, diagnostics, planned_calls,  # noqa: E402
                             rev21_direction_disagreements, run_corpus_dev, run_l1var_v22, score_l1var_v22,
                             threshold_rule, unscored)
from xon.llm.engine import analysis_to_dict  # noqa: E402

RECORD_RUN = ROOT / "results" / "a1-20260924-232324"
RECORD_L1VAR = ROOT / "results" / "a1-20260924-233306"


def _plain(value):
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _json(value, **kw) -> str:
    return json.dumps(value, default=_plain, **kw)


def _jsonl(rows) -> str:
    return "".join(_json(r, ensure_ascii=False) + "\n" for r in rows)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=str(ROOT / "data" / "consistency" / "corpus.jsonl"), help="corpus JSONL")
    ap.add_argument("--record-run", default=str(RECORD_RUN), help="the L1 run of record's folder")
    ap.add_argument("--record-l1var", default=str(RECORD_L1VAR), help="rev. 2.1's L1-var folder")
    ap.add_argument("--subset", action="store_true", help=f"gate D0: only the base documents {list(SAMPLE_BASES)}")
    ap.add_argument("--l1var", action="store_true", help="§8.1 on the 12-document subset (live calls only)")
    ap.add_argument("--final", action="store_true", help="apply the §6 threshold rule (the final iteration's full pass)")
    ap.add_argument("--iteration", type=int, default=REV22_ITERATION,
                    help=f"the development iteration (CHANGELOG); this code implements {REV22_ITERATION} only")
    ap.add_argument("--batch", action="store_true", help="send the first attempts as one Message Batch")
    ap.add_argument("--concurrency", type=int, default=None, help="relation calls in flight (default: the config's)")
    ap.add_argument("--budget", type=int, default=None, help="token budget of this run (default: the config's)")
    ap.add_argument("--out", default=None, help="output directory (default: results/a1-rev22-<date>-<time>)")
    ap.add_argument("--accept-unscored", action="store_true", help="score even if more than 1%% of pairs are unscored")
    args = ap.parse_args(argv)
    subset = args.subset or args.l1var
    if args.iteration != REV22_ITERATION:
        print(f"This code implements development iteration {REV22_ITERATION}; iteration {args.iteration} is in the "
              "git history (CHANGELOG).", file=sys.stderr)
        return 2
    if args.final and subset:
        print("The threshold rule is applied on a full pass only (§6).", file=sys.stderr)
        return 2
    path, record_run = Path(args.corpus), Path(args.record_run)
    if not path.exists() or not (record_run / "documents.jsonl").exists():
        print(f"Needs the corpus ({path}) and the run of record's rows ({record_run / 'documents.jsonl'}).",
              file=sys.stderr)
        return 2
    records = _read_jsonl(path)
    if subset:
        records = [r for r in records if r["base"] in SAMPLE_BASES]
    carried = {r["doc_id"]: r for r in _read_jsonl(record_run / "documents.jsonl")}
    cfg = DEFAULT if args.concurrency is None else replace(DEFAULT, llm_concurrency=args.concurrency)
    llm = LLM(budget_tokens=args.budget, cfg=cfg)
    replay = LLM(budget_tokens=0, cfg=cfg)
    out = Path(args.out) if args.out else ROOT / "results" / f"a1-rev22-{time.strftime('%Y%m%d-%H%M%S')}"
    run = {"engine_version": "2.2", "label": LABEL, "pass": "D0 (12-document subset)" if subset else "full",
           "iteration": args.iteration, "final": bool(args.final), "l1var": bool(args.l1var),
           "corpus": str(path), "documents": len(records), "record_run": str(record_run), "model": llm.model,
           "dry_run": llm.dry_run, "concurrency": cfg.llm_concurrency, "batch": None}
    try:
        docs21 = run_corpus_dev(replay, records, engine_version="2.1", with_direct=True)
        rows21 = [dev_row(d, carried.get(d.record["doc_id"])) for d in docs21]
        drift = [r["doc_id"] for r in rows21
                 if r["by_tau"]["0.50"]["engine"] != carried[r["doc_id"]]["verdict"]["engine"][0]]
        if drift:
            print(f"Rev. 2.1 recomputed from the cache disagrees with the run of record on {drift}.", file=sys.stderr)
            return 1
        if args.batch:
            run["batch"] = BatchRunner(llm, out / "batch.json").run(planned_calls(llm, records))
        docs = run_corpus_dev(llm, records, engine_version="2.2")
        var_rows = run_l1var_v22(llm, docs, raw_dir=out / "l1var") if args.l1var else None
    except LLMError as exc:
        print(f"{type(exc).__name__}: {exc}", *getattr(exc, "__notes__", []), f"{llm.usage['spent_tokens']:,} tokens "
              "spent; the completed calls are cached.", sep="\n", file=sys.stderr)
        return 1
    rows = [dev_row(d, carried.get(d.record["doc_id"])) for d in docs]
    out.mkdir(parents=True, exist_ok=True)
    gate = dict(unscored(rows), accepted=bool(args.accept_unscored))
    run["unscored_gate"] = gate
    if gate["stop"] and not args.accept_unscored:
        (out / "unscored_gate.json").write_text(_json(gate, indent=1), "utf-8")
        (out / "run.json").write_text(_json(dict(run, stopped="unscored pairs", usage=llm.usage), indent=1), "utf-8")
        print(f"{gate['unscored']} of {gate['pairs_requested']} requested pairs are unscored, more than "
              f"{gate['limit']:.0%}. Stopped before scoring. Written to {out}.", file=sys.stderr)
        return 3
    rule = threshold_rule(rows) if args.final else None
    res = {"pass": run["pass"], "label": LABEL, "threshold_rule": rule,
           "rev21_curves": threshold_rule(rows21)["curves"],
           "diagnostics": diagnostics(rows, rows21, rule["selected"] if rule else None)}
    if var_rows is not None:
        res["l1var"] = score_l1var_v22(var_rows, rule["selected"] if rule else None)
        l1var21 = Path(args.record_l1var) / "l1var_repeats.jsonl"
        if l1var21.exists():
            res["l1var_rev21"] = rev21_direction_disagreements(_read_jsonl(l1var21))
        (out / "l1var_repeats_v22.jsonl").write_text(_jsonl(var_rows), "utf-8")
    (out / "documents_v22.jsonl").write_text(_jsonl(rows), "utf-8")
    (out / "documents_v21.jsonl").write_text(_jsonl(rows21), "utf-8")
    (out / "analyses").mkdir(exist_ok=True)
    for d in docs:
        (out / "analyses" / f"{d.record['doc_id']}.json").write_text(
            _json(analysis_to_dict(d.analysis), indent=1, ensure_ascii=False), "utf-8")
    (out / "diagnostics.json").write_text(_json(res, indent=1, ensure_ascii=False), "utf-8")
    (out / "run.json").write_text(_json(dict(run, usage=llm.usage), indent=1), "utf-8")
    text = dev_markdown(res)
    (out / "results.md").write_text(text + "\n", "utf-8")
    print(text)
    print(f"\n{llm.usage['spent_tokens']:,} tokens, about ${llm.usage['estimated_cost_usd']:.2f}. Written to {out}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
