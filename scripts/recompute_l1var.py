"""A1 L1-var recomputed from the responses an L1-var run saved (results/<run>/l1var/), with no API calls.

    python scripts/recompute_l1var.py results/a1-<date>-<time>/l1var

The run of record's claims and pairs are read from a temporary copy of the cache, so the cache and its call log are
left untouched; a response missing from the cache or from the saved folder is an error, never an API call.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xon.llm.client import LLM, LLMError  # noqa: E402
from xon.llm.corpus import SAMPLE_BASES  # noqa: E402
from xon.llm.evaluation import l1var_markdown, replay_l1var, run_corpus, score_l1var  # noqa: E402


def _plain(value):
    """A NumPy scalar as its Python value, as scripts/run_consistency_eval.py writes it."""
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class NoCalls:
    """An SDK client that refuses every call: all the run of record's responses must come from the cache."""

    def __init__(self):
        self.messages = self

    def create(self, **body):
        raise LLMError("A run-of-record response is missing from the cache; recomputing L1-var makes no API calls.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("raw_dir", help="the l1var/ folder of an L1-var results folder")
    ap.add_argument("--corpus", default=str(ROOT / "data" / "consistency" / "corpus.jsonl"), help="corpus JSONL")
    ap.add_argument("--cache", default=str(ROOT / "cache" / "llm"), help="the LLM cache of the run of record")
    ap.add_argument("--out", default=None, help="output directory (default: l1var_recomputed/ next to raw_dir)")
    args = ap.parse_args(argv)
    raw_dir = Path(args.raw_dir)
    records = [json.loads(line) for line in Path(args.corpus).read_text("utf-8").splitlines() if line.strip()]
    records = [r for r in records if r["base"] in SAMPLE_BASES]
    out = Path(args.out) if args.out else raw_dir.parent / "l1var_recomputed"
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "cache"
        shutil.copytree(args.cache, cache)
        try:
            runs = run_corpus(LLM(cache_dir=cache, client=NoCalls(), fixture_dir=Path(tmp) / "fixtures"), records,
                              log=lambda s: None)
            rows = replay_l1var(runs, raw_dir, cache_dir=Path(tmp) / "replay", log=lambda s: None)
        except LLMError as exc:
            print(f"{type(exc).__name__}: {exc}", *getattr(exc, "__notes__", []), sep="\n", file=sys.stderr)
            return 1
    res = score_l1var(rows)
    out.mkdir(parents=True, exist_ok=True)
    (out / "l1var_repeats.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, default=_plain) + "\n" for r in rows), "utf-8")
    (out / "l1var.json").write_text(json.dumps(res, indent=1, default=_plain), "utf-8")
    text = l1var_markdown(res)
    (out / "results.md").write_text(text + "\n", "utf-8")
    print(text)
    print(f"\nRecomputed from {raw_dir}, with no API calls. Written to {out}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
