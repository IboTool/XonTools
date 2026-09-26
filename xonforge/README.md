# XonForge

XonForge builds test corpora for consistency checkers, LLM judges and agent monitors. Ground truth comes from
structured skeletons checked by a deterministic solver; models only render the skeletons as prose
(`SPECS/ToDo/XONFORGE_SPEC.md`). It lives in this repository as the package `xonforge/`, with its provider layer in
`xon_common/` and its tests in `tests/xonforge/`.

Status: v0's core, steps 1 to 6 of the spec's implementation order (§14), built and tested offline:
- the provider layer, with the pipeline-test mode and run configurations;
- the skeleton schema, the solver, and generators for v0's four plant types and the arity-control trap
  (`docs/plant_catalog.md`), with three difficulty levels;
- the renderer: consistent twins rendered, and planted and trap variants derived from them, with prompts stored
  verbatim, versioned and hashed in `prompts/`;
- verification: the structural checks and A1's scans, copied, with a scan canary for every pattern;
- blind review with both of the user's prompts, calibrated by review canaries, and the review queue with its random
  spot checks;
- acceptance; quotas and splits; export under CC BY 4.0 with one canary string per split, after each renderer's
  terms are checked; sealing; the datasheet; the leak test; and the cost estimate.

The 20-document sample's configuration is in place (`docs/providers.md`): a pipeline-test run in which Claude Sonnet 5
renders and Claude Opus 5.5 and Fable 5.1 review, with at most $20 for the run and for each model. It waits for its
token caps, its composition and the user's go-ahead after the cost estimate, so nothing has been rendered or reviewed
live. Nothing is exported until each renderer's terms are checked and logged (`config/terms.yaml`).

## Quick start

```
python -m xonforge providers             # the provider registry and startup check; no call is made
python -m xonforge run-check sample      # whether the sample's run may start, and why not; no call is made
python -m xonforge skeletons --genre G   # seeded skeletons checked by the solver; offline, nothing written
python -m xonforge estimate sample --bases order_cycle:1:5   # a run's cost for a composition; offline
python -m xonforge leak-check            # sealed documents in any worktree; --commits R also searches commits
python -m xonforge leak-audit            # the same, and every commit in the history
python -m pytest tests/xonforge          # offline; no test calls an API; includes the leak test
```

## Keys and locations

Keys are read only from the environment: `XONFORGE_ANTHROPIC_KEY`, `XONFORGE_OPENAI_KEY`, `XONFORGE_GEMINI_KEY`,
`XONFORGE_XAI_KEY`, and optionally a local endpoint's own `XONFORGE_<NAME>_KEY` (`docs/providers.md`).

These live outside the repository, each in the directory named by its variable, and XonForge refuses a location that
is unset or inside any worktree of the repository:

- `XONFORGE_CACHE_DIR`: the response cache. Its parent directory holds the review, decision and diagnostic logs that
  contain text, and the review-queue items and reviewer outputs of sealed or judged documents.
- `XONFORGE_SEALED_DIR`: the sealed test split.
- `XONFORGE_JUDGED_DIR`: the judged split.

The spend and call log, `cache/xonforge/log.jsonl`, holds no text and stays in the repository.

## Costs

Budget caps per run and per provider entry, in tokens and in USD, are set in `config/defaults.yaml`: its own caps,
none of them set, and each run configuration's (`runs`). The sample's dollar caps are $20 for the run and $20 for
each entry; its token caps are not given yet, and no call is sent without them. In `config/prices.yaml`, the three
Claude models' prices were checked on 2026-09-25, and the others are unverified. `python -m xonforge estimate` prices a
run before it starts: the prompts each call would send, the thinking tokens assumed per call (`config/defaults.yaml`,
`estimate`; assumptions until the sample measures them), and the Claude tokenizer's 1.3 factor.

## Rules

The spec's Section 0 and the XonForge section of `rules.md`: ground truth never comes from a model's judgment; the
consistency engine never influences acceptance and is imported only by `diagnostics/engine_plugin.py`; keys stay in
the environment; reviews are blind and cross-model.
