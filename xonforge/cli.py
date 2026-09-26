"""CLI: python -m xonforge

The XonForge command line (XONFORGE_SPEC.md). Commands are added with the implementation steps (§14); without one it
prints its help.

  python -m xonforge providers              the provider registry and startup check; no call is made
  python -m xonforge providers --test-call  also one tiny call per available provider, within the budget caps
  python -m xonforge run-check NAME         whether a run configuration may start, and why not; no call is made
  python -m xonforge skeletons --genre G    seeded bases of each plant type, checked by the solver; offline
  python -m xonforge estimate NAME --bases T:L:N   a run's cost estimate for a composition; offline
  python -m xonforge leak-check             sealed documents in any worktree; --commits R: also those commits
  python -m xonforge leak-audit             sealed documents in any worktree or anywhere in the history
  python -m xonforge run sample             the 20-document sample; stops for review, and does not export or seal
"""
from __future__ import annotations

import argparse

from . import estimate as estimates
from . import locations, pipeline, registry, runs
from .corpus import leak
from .review import blind
from .skeleton.generators import LEVELS, PLANT_TYPES, Knobs, generate
from .skeleton.v1 import V1_PLANT_TYPES
from .solver import check_base


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m xonforge",
        description="XonForge: builds test corpora for consistency checkers, with ground truth from a deterministic "
                    "solver rather than from any model (XONFORGE_SPEC.md).")
    sub = ap.add_subparsers(dest="command", metavar="command")
    p = sub.add_parser("providers", help="the provider registry and startup check: each key present or missing "
                                         "(never its value), capabilities, prices and caps; no call is made")
    p.add_argument("--test-call", action="store_true",
                   help="also send one tiny call to each available provider whose budget caps are set")
    r = sub.add_parser("run-check", help="whether a run configuration in defaults.yaml may start: its mode, models "
                                         "and caps, and each reason it may not; no call is made")
    r.add_argument("name", help="the run configuration's name, e.g. sample")
    r.add_argument("--dry-run", action="store_true",
                   help="check it for a dry run, which only replays the response cache and needs no key or SDK")
    s = sub.add_parser("skeletons", help="generate seeded bases of skeletons and check each with the solver; "
                                         "offline, and nothing is written")
    s.add_argument("--type", dest="plant_type", choices=["all", *PLANT_TYPES, *V1_PLANT_TYPES], default="all")
    s.add_argument("--genre", required=True, help="the genre each skeleton records")
    s.add_argument("--count", type=int, default=5, help="bases per plant type (default 5)")
    s.add_argument("--seed", type=int, default=1, help="the first base's seed; each further base adds 1")
    s.add_argument("--cycle-length", type=int, default=3, help="planted facts, 3 to 6")
    s.add_argument("--entities", type=int, help="3 to 12; default: the plant's")
    s.add_argument("--attributes", type=int, default=2, help="2 to 8, the planted one included")
    s.add_argument("--distractors", type=int, default=0, help="filler facts per planted fact, 0 to 3")
    s.add_argument("--same-attribute-distractors", action="store_true",
                   help="let distractors relate entities outside the plant on the planted attribute")
    s.add_argument("--premise-share", type=float,
                   help="the share of direct_negation claims that are premises (default: defaults.yaml)")
    s.add_argument("--arity-control", action="store_true",
                   help="also give each binary_parity base its arity_control trap variant, which states three values")
    e = sub.add_parser("estimate", help="what a run configuration would cost for a composition of bases, per entry "
                                        "and in total, against its caps; offline, and no call is made")
    e.add_argument("name", help="the run configuration's name, e.g. sample")
    e.add_argument("--bases", action="append", required=True, metavar="TYPE:LEVEL:COUNT",
                   help="COUNT bases of plant type TYPE at difficulty level LEVEL; repeat for more")
    e.add_argument("--seed", type=int, default=1, help="the first base's seed; each further base adds 1")
    e.add_argument("--arity-control", action="store_true", help="give each binary_parity base its trap variant")
    e.add_argument("--prompts", nargs="+", choices=list(blind.PROMPTS), default=list(blind.PROMPTS),
                   help="the review prompts each reviewer runs (default: both)")
    e.add_argument("--genre", default="office memo", help="the genre the skeletons record")
    for name, text in (("leak-check", "search every worktree for sealed documents, from the committed fingerprint "
                                      "manifests; read only"),
                       ("leak-audit", "search every worktree and every commit in the history; read only")):
        c = sub.add_parser(name, help=text)
        if name == "leak-check":
            c.add_argument("--commits", nargs="+", metavar="RANGE",
                           help="also search the commits being pushed, e.g. origin/main..HEAD")
    sub.add_parser("run", help="run the 20-document sample and stop for review; nothing is exported or sealed"
                   ).add_argument("name", help="the run configuration; only sample is run at this gate")
    return ap


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(len(str(r[i])) for r in [headers, *rows]) for i in range(len(headers))]
    line = lambda r: "  ".join(str(v).ljust(w) for v, w in zip(r, widths)).rstrip()
    return [line(headers), line(["-" * w for w in widths]), *map(line, rows)]


def _money(v) -> str:
    return "not set" if v is None else f"{v:,.2f}"


def format_providers(rows: list[dict], caps, policy) -> str:
    def cap(v, usd=False) -> str:
        return "not set" if v is None else (f"${v:,.2f}" if usd else f"{v:,}")

    first = [[r["name"], r["provider"], r["model"], "verified" if r["model_verified"] else "unverified",
              "not needed" if r["key_env"] is None else f"{r['key_env']}: {r['key']}",
              f"{r['sdk']}: {'installed' if r['sdk_installed'] else 'missing'}",
              "yes" if r["available"] else f"no ({r['why']})"] for r in rows]
    second = [[r["name"], r["structured_output"], "yes" if r["sampling"] else "no",
               "unknown" if r["context_tokens"] is None else f"{r['context_tokens']:,}",
               r["reasoning_default"] + (", can be off" if r["reasoning_can_be_off"] else ""),
               f"{_money(r['price_in'])} / {_money(r['price_out'])}",
               "verified" if r["price_verified"] else ("unverified" if r["price_in"] is not None else "no price"),
               f"{cap(r['cap_tokens'])} / {cap(r['cap_usd'], usd=True)}", r["test_call"]] for r in rows]
    out = ["XonForge providers (XONFORGE_SPEC.md, section 4). No key's value is shown, and no call is made without "
           "--test-call.", ""]
    out += _table(["name", "provider", "model", "model id", "key", "SDK", "available"], first)
    out += [""]
    out += _table(["name", "structured output", "sampling", "context", "reasoning", "USD per MTok in / out", "price",
                   "caps: tokens / USD", "test call"], second)
    out += ["", f"Run caps: tokens {cap(caps.run_tokens)}, USD {cap(caps.run_usd, usd=True)}. Transport retries: "
                f"{policy.retries}, the first after {policy.backoff_s:.1f} s, doubling (A1's policy)."]
    return "\n".join(out)


def providers(args) -> int:
    defaults = registry.load_defaults()
    entries = registry.load_entries()
    rows = registry.startup_check(entries, registry.adapters(entries, defaults), defaults, test_call=args.test_call)
    print(format_providers(rows, registry.caps_of(defaults, entries), registry.retry_policy(defaults)))
    return 0


def format_run_check(config: runs.RunConfig, entries: dict, problems: list[str], *, dry_run: bool) -> str:
    def cap(v, usd=False) -> str:
        return "not set" if v is None else (f"${v:,.2f}" if usd else f"{v:,}")

    def models(names) -> str:
        return ", ".join(f"{n} ({entries[n].model})" for n in names) or "none"

    caps = config.caps
    mode = {"record": "record, a corpus of record",
            "pipeline_test": "pipeline_test: its documents are labelled pipeline_test, and never enter a sealed or "
                             "judged split or a corpus of record"}[config.mode]
    rows = [[n, cap(caps.provider_tokens.get(n)), cap(caps.provider_usd.get(n), usd=True)] for n in config.entries]
    out = ["XonForge run check (xonforge/runs.py). No call is made.", "",
           f"Run configuration {config.name}; mode {mode}.",
           f"Renderers: {models(config.renderers)}. Reviewers: {models(config.reviewers)}.",
           f"Run caps: tokens {cap(caps.run_tokens)}, USD {cap(caps.run_usd, usd=True)}.", ""]
    if rows:
        out += _table(["entry", "cap: tokens", "cap: USD"], rows) + [""]
    if not problems:
        return "\n".join(out + ["It may start" + (" as a dry run." if dry_run else ".")])
    return "\n".join(out + ["It may not start" + (" even as a dry run:" if dry_run else ":")]
                     + [f"- {p}" for p in problems])


def run_check(args) -> int:
    defaults = registry.load_defaults()
    entries = {e.name: e for e in registry.load_entries()}
    try:
        config = runs.load(args.name, defaults, entries)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    found = runs.problems(config, entries, registry.adapters(list(entries.values()), defaults),
                          k=int(defaults["review"]["k"]), dry_run=args.dry_run)
    print(format_run_check(config, entries, found, dry_run=args.dry_run))
    return 1 if found else 0


def skeletons(args) -> int:
    share = args.premise_share
    try:
        knobs = Knobs(cycle_length=args.cycle_length, entities=args.entities, attributes=args.attributes,
                      distractors=args.distractors, same_attribute_distractors=args.same_attribute_distractors)
        if share is None:
            share = registry.load_defaults()["skeletons"]["negation_premise_share"]
        if isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 <= share <= 1:
            raise ValueError(f"the premise share is from 0 to 1, not {share!r}")
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    types = PLANT_TYPES if args.plant_type == "all" else (args.plant_type,)
    rows, summary, failed = [], [], False
    for t in types:
        kept = made = 0
        traps = ("arity_control",) if args.arity_control and t == "binary_parity" else ()
        for seed in range(args.seed, args.seed + args.count):
            try:
                base = generate(t, seed=seed, genre=args.genre, knobs=knobs, premise_share=share, traps=traps)
            except ValueError as exc:
                summary.append(f"{t}: stopped at seed {seed}: {exc}")
                failed = True
                break
            problems = check_base(base)
            made += 1
            kept += not problems
            planted = base.planted[0]
            trap = "-" if not base.trap_only else (
                f"arity_control: a naive reading flags {' '.join(base.trap_only[0].traps[0].naive['contradiction'])}")
            rows.append([t, base.base_id, str(len(planted.facts)), " ".join(planted.plant.facts),
                         " ".join(planted.plant.params["differs_from_twin"]), planted.arity_fact or "-",
                         (planted.premise_status or "-").replace("_", " "), trap,
                         "; ".join(problems) or "twin satisfiable; the plant is the only contradiction"
                         + ("; the trap holds" if base.trap_only else ""),
                         "no" if problems else "yes"])
        summary.append(f"{t}: {made} bases, {kept} kept, {made - kept} discarded.")
    entities = "the plant's" if knobs.entities is None else knobs.entities
    out = ["XonForge skeletons (XONFORGE_SPEC.md, section 5). Offline: the generators and the solver call no model, "
           "and nothing is written.", "",
           f"Knobs: cycle length {knobs.cycle_length} (direct_negation's plant is always 2 facts), "
           f"entities {entities}, attributes {knobs.attributes}, distractors per planted fact {knobs.distractors}, "
           f"same-attribute distractors {'on' if knobs.same_attribute_distractors else 'off'}; premise share "
           f"{share:g}; genre {args.genre!r}.", ""]
    if rows:
        out += _table(["type", "base", "facts", "planted facts", "twin differs in", "arity fact", "premise", "trap",
                       "solver", "kept"], rows) + [""]
    print("\n".join(out + summary))
    return 2 if failed else 0


def composition(specs: list[str], seed: int, trap: bool) -> list[estimates.BaseSpec]:
    bases = []
    for spec in specs:
        parts = spec.split(":")
        known = (*PLANT_TYPES, *V1_PLANT_TYPES)
        if len(parts) != 3 or parts[0] not in known or not parts[1].isdigit() or not parts[2].isdigit():
            raise ValueError(f"a composition's bases are TYPE:LEVEL:COUNT, with a plant type of "
                             f"{', '.join(known)}, not {spec!r}")
        if int(parts[1]) not in LEVELS:
            raise ValueError(f"the difficulty levels are {', '.join(map(str, LEVELS))}, not {parts[1]}")
        bases += [(parts[0], int(parts[1]))] * int(parts[2])
    return [estimates.BaseSpec(t, level, seed + n, trap) for n, (t, level) in enumerate(bases)]


def format_estimate(config: runs.RunConfig, entries: dict, settings: dict, first: estimates.Estimate,
                    every: estimates.Estimate, prompts: list[str]) -> str:
    def usd(v) -> str:
        return "no price" if v is None else f"${v:,.2f}"

    rows, totals = [], [0.0, 0.0, 0.0]
    for name, t in first.tallies.items():
        e = entries[name]
        costs = [estimates.usd(t, e, settings, with_thinking=False), estimates.usd(t, e, settings),
                 estimates.usd(every.tallies[name], e, settings)]
        totals = [a + (b or 0) for a, b in zip(totals, costs)]
        cap = config.caps.provider_usd.get(name)
        rows.append([name, e.model, f"{t.calls:,.0f}", f"{estimates.tokens(t.input_words, e, settings):,.0f}",
                     f"{estimates.tokens(t.output_words, e, settings):,.0f}", f"{t.thinking_tokens:,.0f}",
                     *map(usd, costs), "not set" if cap is None else f"${cap:,.2f}"])
    run_cap = config.caps.run_usd
    think = settings["thinking_per_call"]
    out = ["XonForge cost estimate (xonforge/estimate.py). Offline: no call is made.", "",
           f"Run configuration {config.name}, mode {config.mode}. {first.documents} documents; "
           f"{first.reviewed_items} items per reviewer and prompt, canaries included; review prompts: "
           f"{', '.join(prompts)}.",
           f"Tokens: {settings['tokens_per_word']} per word, times each model's tokenizer factor. Thinking assumed "
           f"per call (not measured): rendering {think['render']:,}, derivation {think['derive']:,}, review "
           f"{think['review']:,}. No prompt caching or batch discount. Calls and tokens are the first-attempt case's.",
           ""]
    out += _table(["entry", "model", "calls", "input tokens", "output tokens", "thinking tokens",
                   "USD, no thinking", "USD, first attempts", "USD, all 5 attempts", "cap: USD"], rows)
    out += ["", f"Total: {usd(totals[0])} without thinking; {usd(totals[1])} if every rendering and derivation passes "
                f"on its first attempt; {usd(totals[2])} if every one uses all 5. Run cap: "
                + ("not set." if run_cap is None else f"${run_cap:,.2f}.")]
    return "\n".join(out)


def estimate(args) -> int:
    defaults = registry.load_defaults()
    entries = {e.name: e for e in registry.load_entries()}
    try:
        config = runs.load(args.name, defaults, entries)
        bases = composition(args.bases, args.seed, args.arity_control)
        settings = defaults["estimate"]
        kw = {"renderers": config.renderers, "reviewers": config.reviewers, "review_prompts": args.prompts,
              "thinking": settings["thinking_per_call"], "genre": args.genre,
              "premise_share": defaults["skeletons"]["negation_premise_share"]}
        first = estimates.plan(bases, attempts=1, **kw)
        every = estimates.plan(bases, attempts=int(defaults["render"]["retry_cap"]), **kw)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    print(format_estimate(config, entries, settings, first, every, args.prompts))
    return 0


def leak_check(args, *, audit: bool) -> int:
    reports = [("every worktree", leak.check_worktrees())]
    revisions = ["--all"] if audit else (args.commits or [])
    if revisions:
        try:
            reports.append(("the history" if audit else f"the commits {' '.join(revisions)}",
                            leak.check_history(revisions)))
        except ValueError as exc:
            print(f"error: {exc}")
            return 2
    out = ["XonForge leak " + ("audit" if audit else "check") + " (xonforge/corpus/leak.py). Read only: nothing is "
           "written, and the sealed and judged locations are never opened.", ""]
    for where, report in reports:
        out += [f"{where[0].upper()}{where[1:]}:"] + [f"  {line}" for line in report.lines()]
    print("\n".join(out))
    return 1 if any(r.findings for _, r in reports) else 0


def run_sample(args) -> int:
    if args.name != "sample":
        print("error: this gate runs only the sample configuration. The first corpus waits until the sample has "
              "been reviewed.")
        return 2
    try:
        report = pipeline.execute(registry.Session(args.name, run_config=args.name))
    except (pipeline.Waiting, runs.RunRefused, locations.LocationRefused, ValueError) as exc:
        print(f"error: {exc}")
        return 2
    print(report.text())
    return 0 if report.status == "stopped for review" else 1


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.command == "providers":
        return providers(args)
    if args.command == "run-check":
        return run_check(args)
    if args.command == "skeletons":
        return skeletons(args)
    if args.command == "estimate":
        return estimate(args)
    if args.command in ("leak-check", "leak-audit"):
        return leak_check(args, audit=args.command == "leak-audit")
    if args.command == "run":
        return run_sample(args)
    ap.print_help()
    return 0
