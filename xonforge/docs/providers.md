# XonForge providers

XonForge calls its providers through `xon_common/providers/` (XONFORGE_SPEC.md §4). The registry is
`xonforge/config/providers.yaml`, the prices are in `xonforge/config/prices.yaml`, and
`python -m xonforge providers` runs the startup check. Which providers and models XonForge uses is the user's
decision (`xonforge/docs/decisions.md`). Only Anthropic is available for now.

## Models checked so far

The three Claude models of the 20-document sample were checked in Anthropic's documentation on 2026-09-25: the ids and
retirement dates in the [models overview](https://docs.claude.com/en/docs/about-claude/models/overview), the prices
in the [pricing page](https://docs.claude.com/en/docs/about-claude/pricing).

| Entry | Model id | USD per MTok in / out | Cache read | Retirement not before | In the sample |
|---|---|---|---|---|---|
| `claude-sonnet` | `claude-sonnet-5` | 2 / 10 | 0.1x | 2027-06-30 | renderer |
| `claude-opus` | `claude-opus-5-5` | 4 / 20 | 0.05x | 2027-09-22 | reviewer |
| `claude-fable` | `claude-fable-5-1` | 10 / 50 | 0.025x | 2027-09-01 | reviewer |

A 5-minute cache write costs 1.25x the input price; XonForge asks for no caching, so it pays for cache reads and
writes only where Anthropic reports them. None of the three accepts temperature, top_p or top_k, so none is sent. All
three think adaptively, and thinking is billed as output. Opus 5.5 and Fable 5.1 always think; only Sonnet 5 can turn
thinking off. XonForge never asks for extended thinking. The default effort, which XonForge does not change, is high
for Fable 5.1 and Sonnet 5 and medium for Opus 5.5. The tokenizer of these models produces about 30% more tokens for
the same text than earlier ones. Structured output is configured as A1's client uses it with every Claude model, and
was not among the facts checked.

The other entries are candidates, whose model ids, capabilities and prices are not verified.

## Run configurations and modes

A run started with a configuration in `defaults.yaml` (`runs`) takes its mode, models and caps from it, and starts only
if `xonforge/runs.py`'s check passes; `python -m xonforge run-check NAME` shows the check without making a call. The
mode is always named, and the pipeline-test mode is never a fallback for missing providers.

- `record`, a corpus of record: no reviewer is of the renderer's provider, and the run needs at least three
  configured providers (verified model ids and prices, and available).
- `pipeline_test`: the renderer and the reviewers may be models of one provider, and must be different models. Its
  documents are labelled `pipeline_test`, never enter a sealed or judged split, and are excluded from any corpus of
  record.

`sample` is the 20-document sample: `pipeline_test`, `claude-sonnet` renders, `claude-opus` and `claude-fable`
review. The user's max spend is $40 for the run and for each entry, and the token cap is 20,000,000, so the dollar
cap is what stops a long response. A live run still needs `XONFORGE_ANTHROPIC_KEY`.
`first_corpus` is the first corpus of record, with initial caps of $250 for the run and $100 for each entry; it
waits for three providers.

## Provider modules

| Provider | Module | API, SDK | Key variable |
|---|---|---|---|
| `anthropic` | `anthropic.py` | Messages API, `anthropic` SDK | `XONFORGE_ANTHROPIC_KEY` |
| `openai` | `openai.py` | Chat Completions, `openai` SDK | `XONFORGE_OPENAI_KEY` |
| `google` | `google.py` | `generate_content`, `google-genai` SDK | `XONFORGE_GEMINI_KEY` |
| `xai` | `xai.py` | xAI's OpenAI-compatible Chat Completions, `openai` SDK | `XONFORGE_XAI_KEY` |
| `openai_compatible` | `openai_compatible.py` | Chat Completions at the entry's `base_url`, `openai` SDK | none, or its own `XONFORGE_<NAME>_KEY` |

The SDKs other than `anthropic` are not dependencies. A provider whose SDK is not installed shows as unavailable.

## Keys

Each key is read from XonForge's own environment variable, only in its provider module, and never appears in a log,
a cache file, an export or the UI. A provider without its key shows as unavailable and is skipped; no other provider
takes its place.

Every SDK client gets its key, base URL and credentials explicitly, with the SDK's own retries off (XonForge
retries, with A1's policy). Left unset, an SDK would take them from its own environment variables: the Anthropic SDK
from A1's key variable and its token and base-URL variables, the OpenAI SDK from its key, base-URL, organization and
project variables, and google-genai from its key variables or Google Cloud credentials.

## Terms of use (§4.3)

Before the first export, check for each provider used whether its terms allow its outputs to be used to build and
publish evaluation datasets, and log the result in `xonforge/config/terms.yaml`: the date, whether they allow it, and
the pages read (the user's item 16 of 2026-09-25). Export refuses documents rendered by a provider whose check is not
logged, or whose terms do not allow it. No check is logged yet: it needs web access. These links are from before 2026
and were not checked when this page was written.

- [ ] Anthropic: [Commercial Terms of Service](https://www.anthropic.com/legal/commercial-terms) and
  [Usage Policy](https://www.anthropic.com/legal/aup)
- [ ] OpenAI: [Services Agreement](https://openai.com/policies/services-agreement/) and
  [Usage Policies](https://openai.com/policies/usage-policies/)
- [ ] Google: [Gemini API Additional Terms of Service](https://ai.google.dev/gemini-api/terms)
- [ ] xAI: [Enterprise Terms of Service](https://x.ai/legal/terms-of-service-enterprise) and
  [Acceptable Use Policy](https://x.ai/legal/acceptable-use-policy)
- [ ] Local models: each model's license, for example the
  [Llama 3.3 Community License](https://www.llama.com/llama3_3/license/)
