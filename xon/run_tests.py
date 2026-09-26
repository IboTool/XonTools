"""CLI: python -m xon.run_tests --out results/ [--experiments E1,E4b] [--include-v1] [--include-controls]
[--geometries gasket,carpet] [--seed 0] [--no-figures]

Runs every registered experiment except the preserved protocols (the V1 protocols and E9c's earlier
registrations, E9c_v1 and E9c_v2), which need --include-v1, and the V1.2 controls, which need --include-controls
(E1_lattice then runs right after E1). --geometries limits E9a–E9c to a subset of the V1.2 geometries;
E9d is not implemented (skipped at the user's request).
Exit code 2 if any experiment raised; else 1 if a gate failed (E4b and E4c form one gate, E4, that
fails only if both fail; negative controls and V1 variants never count); else 0. not_implemented
counts as skipped.
"""
from __future__ import annotations

import argparse
import sys
import textwrap

from .config import XonConfig
from .experiments import (REGISTRY, V1_2_PAIRS, V1_PAIRS, all_experiment_ids, control_ids, gate_verdicts,
                          preserved_v1_2_ids, registration, run_experiment, suite_ids, v1_ids)
from .export import export_run
from .geometry import GEOMETRIES, e9_report


def exit_code(results) -> int:
    if any(r.status == "error" for r in results):
        return 2
    return 1 if "failed" in gate_verdicts(results).values() else 0


def format_table(results) -> str:
    lines = [f"{'ID':<10} {'Status':<17} {'Time':>7}  {'Name':<50} Key numbers", "-" * 134]
    for r in results:
        summary = textwrap.wrap(r.summary, 64) or [""]
        lines.append(f"{r.id:<10} {r.status.upper():<17} {r.runtime_s:>6.1f}s  {r.name[:50]:<50} {summary[0]}")
        lines.extend(f"{'':<89} {s}" for s in summary[1:])
    return "\n".join(lines)


def preserved(pairs, eid: str) -> tuple[str, ...]:
    """The preserved protocols paired with eid (a pair's value is one id or a tuple of them, newest first)."""
    old = pairs.get(eid) or ()
    return (old,) if isinstance(old, str) else tuple(old)


def comparison_table(results, pairs=V1_PAIRS, labels=("V1.1", "V1")) -> str:
    """The current protocol next to its preserved predecessors, for every pair that ran."""
    by_id = {r.id: r for r in results}
    w = max(map(len, labels))
    lines = []
    for new in pairs:
        news = [r for r in results if r.id == new or (r.group == new and r.role == "gate")]
        olds = [o for o in preserved(pairs, new) if o in by_id]
        if not olds or not news:
            continue
        verdict = gate_verdicts(news).get(new, news[0].status)
        lines.append(f"{new:<4} {labels[0]:<{w}} {verdict.upper():<7} " + " | ".join(f"{r.id}: {r.summary}" for r in news))
        lines += [f"{'':<4} {labels[1]:<{w}} {by_id[o].status.upper():<7} {o}: {by_id[o].summary}" for o in olds]
    return "\n".join(lines)


def format_report(rows: list[dict], wide=("Pearson r", "N, E, D vs closed forms", "Predicted vs observed")) -> str:
    """Fixed-width table; the long columns go on an indented line under each row."""
    cols = [c for c in rows[0] if c not in wide]
    width = {c: max(len(c), *(len(r[c]) for r in rows)) for c in cols}
    lines = ["  ".join(f"{c:<{width[c]}}" for c in cols)]
    lines.append("-" * len(lines[0]))
    for r in rows:
        lines.append("  ".join(f"{r[c]:<{width[c]}}" for c in cols))
        lines.extend(f"    {c}: {r[c]}" for c in wide if c in r)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="python -m xon.run_tests", description="Run the XON SIM experiments.")
    ap.add_argument("--out", default="results", help="output root (a <timestamp>_<seed> folder is created)")
    ap.add_argument("--experiments", default="",
                    help="comma-separated subset, e.g. E1,E4b (default: every experiment except the V1 variants "
                         "and the controls)")
    ap.add_argument("--include-v1", action="store_true",
                    help="also run the preserved protocols: V1 (" + ", ".join(v1_ids()) + ") and the earlier "
                         "registrations of re-registered V1.2 experiments (" + ", ".join(preserved_v1_2_ids()) + ")")
    ap.add_argument("--include-controls", action="store_true",
                    help="also run the V1.2 controls next to the experiment they check (" + ", ".join(control_ids())
                         + ")")
    ap.add_argument("--geometries", default="",
                    help="comma-separated geometries for E9a-E9c (default: " + ",".join(GEOMETRIES) + ")")
    ap.add_argument("--seed", type=int, default=XonConfig().seed)
    ap.add_argument("--no-figures", action="store_true", help="skip writing figure files")
    args = ap.parse_args(argv)

    known = all_experiment_ids()
    lookup = {eid.upper(): eid for eid in known}
    if args.experiments:
        ids = [lookup.get(e.strip().upper(), e.strip()) for e in args.experiments.split(",") if e.strip()]
        unknown = [e for e in ids if e not in known]
        if unknown:
            ap.error(f"unknown experiments {unknown}; choose from {known}")
        old = [e for e in ids if e in v1_ids() + preserved_v1_2_ids()]
        if old and not args.include_v1:
            ap.error(f"{old} are preserved protocols: add --include-v1")
        if args.include_v1:
            for e in list(ids):
                key = e if e in V1_PAIRS else (REGISTRY[e].group if e in REGISTRY else "")
                for old in preserved(V1_PAIRS, key) or preserved(V1_2_PAIRS, e):
                    if old in known and old not in ids:
                        ids.append(old)
        if args.include_controls:
            for c in control_ids():
                if registration(c).group in ids and c not in ids:
                    ids.insert(ids.index(registration(c).group) + 1, c)
    else:
        ids = suite_ids(args.include_v1, args.include_controls)
    cfg = XonConfig(seed=args.seed)
    if args.geometries:
        geos = [g.strip().lower() for g in args.geometries.split(",") if g.strip()]
        bad = [g for g in geos if g not in GEOMETRIES]
        if bad:
            ap.error(f"unknown geometries {bad}; choose from {list(GEOMETRIES)}")
        cfg = cfg.replace(e9_geometries=tuple(geos))

    results = []
    for eid in ids:
        print(f"[{eid}] {registration(eid).name} ...", flush=True)
        res = run_experiment(eid, cfg)
        print(f"      {res.status} in {res.runtime_s:.1f}s: {res.summary}", flush=True)
        if res.status == "error":
            print(textwrap.indent(res.notes, "      "), flush=True)
        results.append(res)

    figures = {} if args.no_figures else {f"{r.id}_{k}": f for r in results for k, f in r.figures.items()}
    verdicts = gate_verdicts(results)
    header, report = e9_report(results, cfg)
    run_dir, fig_info = export_run(args.out, cfg, experiments=results, figures=figures,
                                   extra={"experiments_run": ids, "gate_verdicts": verdicts,
                                          **({"e9_report_header": header} if report else {})},
                                   tables={"e9_report": report})
    print()
    print(format_table(results))
    print()
    groups = {g: v for g, v in verdicts.items() if sum(r.group == g for r in results if r.role == "gate") > 1}
    for g, v in groups.items():
        members = [r.id for r in results if r.group == g and r.role == "gate"]
        print(f"{g} ({' or '.join(members)}): {v.upper()}")
    table = comparison_table(results)
    if table:
        print("\nV1.1 vs V1:")
        print(table)
    table = comparison_table(results, V1_2_PAIRS, ("current", "earlier"))
    if table:
        print("\nV1.2 re-registrations vs their earlier registrations:")
        print(table)
    if report:
        print("\n" + header)
        print(format_report(report))
    print()
    for r in results:
        if r.status in ("failed", "error") and r.role == "gate":
            print(f"{r.id} notes: {r.notes if r.status == 'failed' else 'see traceback above'}")
    if fig_info.get("note"):
        print(fig_info["note"])
    if report:
        print(f"E9 report table written to {run_dir / 'e9_report.csv'}")
    print(f"Results written to {run_dir / 'experiments.json'}")
    code = exit_code(results)
    print(f"Exit code {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
