# XonForge dashboard

The dashboard is the seven pages in `XONFORGE_SPEC.md` §10. Open it from the repository root:

```
python -m xonforge dashboard
```

That runs `streamlit run xonforge/app/dashboard.py`. No API call is made by opening a page. A key is shown as present or missing, never as its value.

The pages read `xonforge/config/defaults.yaml` and, when `XONFORGE_CACHE_DIR` is set, the run files under that directory's parent: documents, skeletons, the review queue, the decision log and the run record. The sealed and judged directories are not opened. The first corpus is not started.

## Configure

- **Target size.** Starts at 300. A quota unit's meaning, a document or a base, is still open; the preview counts units.
- **Plant types, traps, difficulty levels, genre, renderer mix.** The plant types include v0 and v1. Judged plant types (`causal_inconsistency`, `commonsense_impossibility`, `implicature_tension`) are omitted from the proportional preview: those bases go to the judged split.
- **Reviewers (K).** Starts at 2, the default in the configuration.
- **Split shares.** Development, calibration and test, as percentages that sum to 100. The committed default is 50 / 15 / 35.
- **Constants.** Minimum spacing, the retry cap, the length tolerance, `max_tokens`, the canary share (1/10, and at least 2 in the sample) and the negation premise share. These are the values the checks use. Saving a draft does not change them.
- **Quota preview.** Units per plant type, level and renderer, with preview seed 2. That seed is not written to the decision log.
- **Save draft.** Writes `dashboard/configure.yaml` under the cache directory's parent, outside the repository. Runs keep loading `defaults.yaml`. The sample's caps stay where they are.

## Providers

Each registry entry: model, whether the model id is verified, whether its key is present, missing or not needed, whether it can be called, structured output, price per million tokens, the entry's caps, and the test-call status. The status on this page is "not run". A test call is `python -m xonforge providers --test-call`, which spends the budget.

Top-level token and dollar caps are shown underneath, and under those each run configuration's own caps. The sample's caps are 2,000,000 tokens and USD 20.

The terms checklist is `xonforge/config/terms.yaml`. A provider whose check is open, or whose terms do not allow publishing, is listed as a reason nothing may be exported.

## Run

Choose a run configuration. The page shows whether it may start.

The sample has an offline cost estimate: documents, reviewed items, and dollars per entry at first attempts with the assumed thinking, beside the run cap. Duration is not estimated. No duration model is registered.

When a run record exists, the page shows its status, each base of the composition and whether a document from it rendered, how many documents failed, and how many took more than one attempt. Answered calls in the call log are the live cost, in tokens and dollars.

Pause is the budget cap stopping the run (`paused-rendering` or `paused-reviewing` on the run record). Resume is the same command as start: `python -m xonforge run sample`, which continues from the cache.

**Start or resume** sends the sample's API calls, within its caps. It runs only when the checkbox is on and the name `sample` is typed. Any other configuration, including `first_corpus`, is refused. The first corpus waits until the sample has been reviewed.

## Review queue

One stored run at a time. The statistics are the number queued, how many are still open, how many have a decision, and how many are spot checks of unflagged documents.

A document is shown beside its skeleton. The text is one column. The other column is each fact's plain statement and the span recorded for it. The flags are the queue item's reasons.

**Record decision** appends `accept`, `regenerate` or `discard` to the decision log, with the reason. A blank reason is refused. The log stays outside the repository, and the chain is checked on write.

## Quality

For a run that has documents:

- **Flag rates by renderer.** Documents, and how many carry a rendering flag or a scan hit.
- **Difficulty.** The level, target words, explicitness and lexical variety that were set, beside the measured word count and spacing.
- **Reviewer calibration.** Recall and false alarms from the review packet's calibration lines. The document text later in that packet is not shown on this page.

**Solver discards.** Bases in the skeleton store that fail the solver's check of a base, and bases that pass. A missing store is reported as absent, not as zero discards.

## Corpus

Filter the stored documents by variant, status, renderer and document id. One document's provenance is its base, variant, mode, genre, seed, plant type, skeleton digest, renderer, prompt version, attempts and the human decisions on it.

The datasheet preview lists the datasheet's sections and the notice that applies. It does not include document text.

Export and seal stay closed while any document is a pipeline test, while there is nothing to export, or while a renderer's terms are unchecked or do not allow publishing. The page does not write a split. Sealing waits on an export, and the first corpus is a later step.

## Logs

- **Run log.** The latest rows of the call log (`cache/xonforge/log.jsonl` in the configuration). A row is the provider, model, tag, tokens, cost and stop reason. It holds no document text and no key.
- **Changelog.** The newest entry in `CHANGELOG_EXPERIMENTS.md`.
- **Decision log.** The chain check: the number of entries and the head hash, or the line where the chain breaks.
