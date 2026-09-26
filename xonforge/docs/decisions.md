# XonForge: the user's decisions

The running record of the user's decisions on XonForge (`SPECS/ToDo/XONFORGE_SPEC.md`), newest first. Each section
lists the decisions, says where one re-specifies the spec or supersedes an earlier decision or one of the implementing
agent's readings, and records the readings applied where an answer leaves a detail open. The `CHANGELOG_EXPERIMENTS.md`
entry of the same date logs each section. Decisions made before this file existed are in that file's XonForge entries
of 2026-09-25 for steps 0, 1 and 2.

## 2026-09-26 — The sample may spend at most $40

The user confirmed the recommended composition and set the maximum spend at $40: "That's fine, do it. Max spend $40."
That replaces the sample's earlier $20 run cap and $20 cap on each entry (`decisions.md`, the pipeline-test sample).
`runs.sample` in `defaults.yaml` now caps the run and each of its three entries at $40, so the three together cannot
spend more than $40. `first_corpus` is unchanged.

No token count was given. The budget sends no call without a token cap, so each token cap is 20,000,000. That is what
$40 buys of Claude Sonnet 5's input at $2 per million tokens, the cheapest uncached rate of the three models. Output
costs more, so a long response reaches the dollar cap first. The sample does not request prompt caching.

`python -m xonforge run` now reviews every document that has text with both prompts and both reviewers, which is what
the approved estimate counted, and stops when the budget holds a call back. The fact audit stays off.

## 2026-09-26 — Step 7 stopped: the sample's composition and estimate

The recommended composition, for the user to confirm or replace, is 10 v0 bases, each rendered as a twin and a
planted variant: 20 documents, pipeline-test mode, seed 1, no traps, both review prompts, fact audit off, and no v1
type. The mix is `order_cycle:1:4`, `equality_break:1:3`, `binary_parity:1:2`, `direct_negation:1:1`.

`python -m xonforge estimate sample` with that mix, offline, prices 20 documents and 27 items per reviewer and
prompt, canaries included. claude-sonnet: 20 calls, $0.67 on the first attempt and $3.36 if all 5 are used.
claude-opus: 54 calls, $2.45. claude-fable: 54 calls, $6.13. The total is $1.09 without thinking, $9.25 if every
rendering and derivation passes on its first attempt, and $11.93 if every one uses all 5, under the $20 run cap and
the $20 cap on each entry. Token caps are still unset, so `run sample` refuses. The live sample was not started.
`first_corpus` was not started. This is not a run of record, and there is no tag.

## 2026-09-26 — Readings for v1 step 9

The dashboard (`xonforge/app/dashboard.py`, started on Windows by `run_xonforge.bat`) edits a run's configuration in
the session only. It does not write `xonforge/config/defaults.yaml` and does not set token caps. A key is reported
present or missing and is never shown. Start, Pause and Resume do not send a call. The pages are Configure,
Providers, Run, Review queue, Quality, Corpus and Logs, as in spec §10, and they work offline. The dashboard does
not import the consistency engine.

## 2026-09-26 — Readings for v1 step 8

The spec's §5.2, §5.3, §5.3b, §5.4 and §7.4b leave the details below open. These are the implementing agent's
readings. They do not change a pre-registered threshold. No API call was made, and `defaults.yaml` was not written.

1. **`PLANT_TYPES` stays v0's four** (`order_cycle`, `equality_break`, `binary_parity`, `direct_negation`). The v1
   types are `V1_PLANT_TYPES`; `ALL_PLANT_TYPES` is both. A run's composition still accepts only the four, so the
   paid sample cannot name a v1 type. `python -m xonforge skeletons --type all` builds from `ALL_PLANT_TYPES`.
2. **A subject-less premise with a role is not an arity.** An arity is a subject-less premise with no role and an
   integer value of at least 2. A universal value, a birth year or a count carries a role, so the solver does not
   read it as a statement of how many values an attribute has.
3. **`same_name`.** The naive reading does not merge the two entities. Where they share a name or an alias, it reads
   `different` as `same`, so the plant's three facts stay the only minimal contradiction. A trap whose naive flags
   are not exactly the plant's fact ids is refused. `time_zone`, `overnight_span`, `unit_equivalence` and
   `approximation` store the resolving fact on `naive.resolves`; it is not one of the plant's facts.
4. **Inferred facts.** A fact with a `derivation` is inferred. After ids are assigned, its support is the other
   plant facts, and the document records `mode: inferred`, those facts' stated spans, and the derivation. The prompt
   lists them as inferred and not as sentences of their own. v0 facts have no derivation. Cardinality's listed count
   has none either; only the disagreeing count does, so a stated span exists to support it.
5. **Scans stay fail-closed.** `containment` is the only new same-attribute pattern, because only
   `spatial_containment` plants three entities on one attribute. Other v1 attributes are not scanned that way until
   a plant puts three entities on them. The pattern has cues (`contains`, `inside`, `within`) and the synthetic
   canary `same-containment`.
6. **Judged plants.** `causal_inconsistency`, `commonsense_impossibility` and `implicature_tension` are satisfiable
   either way. The solver checks that no other contradiction exists and labels `ground_truth: judged`. In record
   mode `assign_bases` sends them only to the judged split. A pipeline test that draws one is refused, so none
   enters a sealed test.
7. **Fact audit is off unless `--audit`.** The auditor's entry is not the renderer's. A mapped fact the auditor
   calls absent or contradicted, or an unmapped fact it calls stated, is a queue reason. Tests use a fake client.
   The prompt is `xonforge/prompts/fact_audit.txt`, version `fact-audit-v1`, SHA-256
   `24b1480ea7676da2072290b851a4c682e608432557761e6067a2f9fe56d862fd`.
8. **A sealed or judged path is refused even when only the letter case differs.** `engine_plugin._within` compares
   case-folded paths. The existing test uppercases a sealed path; on a case-sensitive filesystem that path is not
   inside the directory unless the comparison ignores case.
9. **`python -m xonforge run NAME`** chains generate, render, the structural checks and scans, blind review, the
   queue and acceptance. It refuses unless `run-check` passes, and that check runs before a session is opened, so a
   refused run does not need the cache. `--dry-run` uses the cache only. A document whose skeleton digest is already
   stored is kept. The command does not split or seal, and a pipeline-test document stays out of those splits.

## 2026-09-25 — Answers on v0's open questions

Ian's answers to the open questions of steps 3 to 6, which he confirmed as written ("I'm Ian. Those decisions are
confirmed as written here."); that confirms CC BY 4.0 (item 16). Two additions followed the same evening: item 11 on
providers, with a pipeline-test mode, and the pipeline-test sample's caps and models, with model ids and prices checked
in Anthropic's documentation. His numbering follows the regrouped list he was sent. His text is quoted at the end of
this section.

### To accept a first document

1. **Spacing.** At least one sentence that is not planted between any two planted sentences, as a constant; the plant
   distance knob sets the overall spread on top of it. The arity sentence (binary parity's `arity_fact`) is not a
   planted sentence: it is exempt from spacing and from the plant distance, but must be present. This sets §5.4's
   constant and confirms the checks' treatment of the arity sentence.
2. **Consistent twins.** A twin's "planted" facts are the counterpart facts at the plant's positions (the flipped
   relation, the "same" replacing one "different", the compatible negation), recorded as `twin_facts`, with spans,
   under the same spacing and forbidden-content rules. The consistent twin is rendered first, from its skeleton. The
   planted variant is derived from the twin's text by re-rendering only the changed sentences in place, leaving every
   other byte identical, so that the renderer never writes prose around a contradiction it knows about. The structural
   checks run on both texts. This supersedes the renderer built in step 3, which rendered each planted variant from
   its own skeleton and refused twins.
3. **Inferred facts.** An inferred fact's map entry holds `mode: "inferred"`, `support_spans` (the verbatim spans the
   fact follows from, each of which must appear verbatim) and `derivation` (the solver's rule, e.g. "3:00 + 2 h =
   5:00"). For v0's plant types explicitness is only "stated" or "paraphrased"; "inferred" starts in v1 with the
   arithmetic, time and location types. The schema is defined now and generated later. This re-specifies §5.4's
   explicitness knob for v0.
4. **Difficulty levels,** bundles of §5.4's knobs, with the actual values recorded per document:
   - Level 1 (L1-like): 150–300 words; cycle 3–4; stated; 0–1 distractors per planted fact, other attributes only;
     low lexical variety; 3–5 entities, 2–3 attributes; any plant distance.
   - Level 2: 400–800 words; cycle 3–5; stated or paraphrased; 1–2 distractors, same-attribute distractors on; medium
     variety; 5–8 entities, 3–5 attributes; planted sentences spread over at least half the document.
   - Level 3: 1,000–3,000 words; cycle 4–6; paraphrased; 2–3 distractors, same-attribute distractors on; high
     variety; 8–12 entities, 5–8 attributes; the first and last planted sentences in the first and last quarters.

   Length tolerance: within ±15% of the document's target word count, and at least ±25 words; a miss is a failed check
   for retries. This settles the mapping of same-attribute distractors to levels that step 2 left open: off at level
   1, on at levels 2 and 3.
5. **Canaries.**
   - Scan canaries: small synthetic documents written for each scan and each attribute pattern (e.g. two "first"s, a
     same-attribute leak, an activity synonym), plus the real defects the L1 scans found (e.g. base 32's superlative
     clash, the raffle-win leaks).
   - Review canaries: defect canaries from the same sources; clean canaries from L1's 60 consistent documents, in
     which the post-hoc analysis found no unplanted contradictions.
   - L1 material may be used: canaries calibrate reviewers and are never evaluation data. Once the first development
     documents are accepted, canaries derived from them are added (a known defect inserted into an accepted text), so
     that canaries also match XonForge's style.
   - No canary ever comes from, or goes into, a sealed or judged split.
6. **Scans.** A1's scans are copied into `xonforge/verify/`, with their source file and commit recorded in the
   changelog, and extended there: score, speed, club, department, table, cabin, and "arrived later than". A1's copy
   stays unchanged. Each new pattern needs its own scan canary. Meanwhile the current rule stays (fail closed): a
   document with an attribute that no scan pattern covers is not accepted; it waits. This supersedes the reuse of A1's
   scans by import, which the user asked for until copying was decided, and confirms the fail-closed rule built in
   step 6.

### For review

7. **Prompts,** versioned and hashed:
   - contradiction-only: "List every set of two or more statements in this document that cannot all be true at once.
     Quote each statement verbatim. Do not report statements that are merely unlikely or surprising, or that are
     resolved by time, quotation, belief, hypothesis or correction. If there are none, return an empty list."
   - relational-inventory: "First list every statement that relates people or things (order, same or different,
     counts, times, places, roles), quoted verbatim and grouped by attribute. Then check each group and report
     conflicts in the same format."

   The reply, as structured output: `{"conflicts": [{"statements": ["verbatim", ...], "explanation": "one
   sentence"}]}`, plus `"inventory": [...]` for the second prompt, kept for audit. Matching: normalize (NFKC, case
   fold, collapse whitespace, strip quotes); a quoted statement matches a sentence if either contains the other. A
   reported conflict matches the plant (or a canary's defect) if its matched sentences include at least min(2, the
   number of defect sentences) of the defect's sentences. Anything matching neither goes to the human queue.
8. **Batch:** up to 20 generated documents reviewed by one reviewer with one prompt in one run step, sent as one call or
   several (long documents one per call), plus that batch's canaries. Recall is the detected defect canaries over the
   defect canaries in the batch, as an exact fraction with no rounding; the batch is certifiable only if recall ≥ 0.8.
9. **Canaries per batch:** 5 defect canaries (so one miss still passes: 4/5 = 0.8) and 2 clean canaries, drawn by a
   logged seed, covering the defect kinds relevant to the batch's attributes where possible, and shuffled in under
   opaque ids. This exceeds §7.3's minimum of 10%. False alarms on the clean canaries are recorded per batch.
10. **The random 10%:** the seed is fixed and logged before any review; from the unflagged documents sorted by id,
    ceil(0.10 × n) are drawn, at least 1, without replacement. The 20-document sample gets at least 2.

### Providers, models and budgets

11. **Providers:** only Anthropic is available for now.
    - A pipeline-test mode: the renderer and the reviewers may be different models of one provider, and must still be
      different models. Every document made in the mode is labelled `pipeline_test`, can never enter a sealed or
      judged split, and is excluded from any corpus of record; the datasheet says so.
    - The 20-document sample runs in this mode with Claude models (exact ids from Anthropic's documentation,
      recorded), at most $20 per run.
    - The cross-provider rule stays in force for every corpus of record; its first run waits until at least three
      providers are configured. Ian will add Gemini and OpenAI or a local model before then.

    This re-specifies the rule that reviewers are never from the renderer's provider (§0, §7.3), for the pipeline-test
    mode only. It replaces the first answer's item 11, whose provider list was a placeholder, with its "current
    mid-tier model" per provider and its $8 per provider for the sample. The first full corpus keeps that answer's
    caps: estimate first; initial caps of $250 per run and $100 per provider, adjusted from the sample's measured costs.

    **The pipeline-test sample:**
    - Caps: $20 per run and $20 per provider. The earlier $8 per provider assumed three providers.
    - Models: the renderer is `claude-sonnet-5`; the two reviewers are `claude-opus-5-5` and `claude-fable-5-1`, which
      differ from the renderer and from each other.
    - The sample itself needs Ian's go-ahead after the cost estimate.

    **Model ids and prices,** verified in Anthropic's documentation on 2026-09-25
    (https://docs.claude.com/en/docs/about-claude/models/overview and
    https://docs.claude.com/en/docs/about-claude/pricing):

    | Model | API id | Input $/MTok | Output $/MTok | Cache read (× input) | Retirement not before |
    | --- | --- | --- | --- | --- | --- |
    | Claude Fable 5.1 | `claude-fable-5-1` | 10 | 50 | 0.025 | 2027-09-01 |
    | Claude Opus 5.5 | `claude-opus-5-5` | 4 | 20 | 0.05 | 2027-09-22 |
    | Claude Sonnet 5 | `claude-sonnet-5` | 2 | 10 | 0.1 | 2027-06-30 |
    | Claude Haiku 4.5 (not used) | `claude-haiku-4-5-20251001` | 1 | 5 | 0.1 | 2026-10-15 |

    - Other prices: a 5-minute cache write costs 1.25× the input price and a 1-hour write 2×; the Batch API is 50% off
      every price; `inference_geo: "us"` costs 1.1×, and the default, global, is the standard price.
    - Sonnet 5: $2/$10 is its standard price; the increase to $3/$15 planned for 2026-09-01 was cancelled.
    - The rates go into XonForge's own price table (`xonforge/config/prices.yaml`), Fable 5.1's 0.025× cache-read rate
      included; A1's `xon/config.py`, which lacks that rate, is not edited.

    **Request shape,** from the same pages and A1's `LLM_CAPABILITIES`:
    - Sampling: the three models reject a non-default temperature, top_p or top_k, so none is sent, and any variety in
      rendering comes from the prompt and the seeded content.
    - Thinking: adaptive on all three; always on for Opus 5.5 and Fable 5.1, and can be disabled only on Sonnet 5.
      Extended thinking (`thinking.type: "enabled"` with `budget_tokens`) is not accepted. The default effort is high
      on Fable 5.1, medium on Opus 5.5 and high on Sonnet 5. Thinking tokens are billed as output, so estimates and
      caps count them.
    - Tokenizer: Claude 4.7 and later models, the three chosen included, produce about 30% more tokens for the same
      text than earlier ones; the cost estimate uses this when converting words to tokens.

### For the full corpus and export

12. **Quotas:** a full cross of plant type × difficulty level × renderer provider; genre and trap type as separate
    per-dimension quotas, balanced across the cells. A full cross of all five dimensions has too many cells to fill.
13. **Rounding:** largest remainder, so that cell sizes sum exactly to the target; ties are broken by a logged seed.
14. **Unfillable:** a cell is unfillable when its attempts reach max(10, 3 × its quota) without filling it. It is
    reported, the others keep filling, and nothing is redistributed automatically; Ian decides.
15. **Splits:** stratified by plant type × difficulty level, seeded random within each stratum, with largest-remainder
    rounding; the seed is logged before generation. All variants of a base stay together.
16. **License:** CC BY 4.0 for the corpus, with the "not for training" notice, which is a request, not a license term.
    Before the first export, each provider's terms on publishing their outputs as a dataset are checked and the result
    logged. A `LICENSE.txt` in each exported folder: yes, which confirms the implementing agent's reading in step 6.
17. **Leak test,** all of the following:
    - One canary string per split, searched everywhere.
    - Whole-document hashes.
    - Word sequences of k = 8 words, after normalizing (NFKC, case fold, collapsed whitespace, stripped punctuation and
      quotes): a file is flagged if it shares 2 or more distinct 8-word sequences with any one sealed document, after
      excluding sequences that occur in the generator's own prompts and templates.
    - Scope: every file in both worktrees, tracked or not (excluding `.git`), on every test run, plus the commits being
      pushed before each push. The audit also scans the full history.
18. Answered in 17.
19. **One canary string per split,** so that development files carry only the development canary and the search for
    the sealed one stays clean. This supersedes the implementing agent's one canary string per corpus (step 6).

### Smaller points

20. **Traps:** `arity_control` is in v0, as binary parity's partner and part of L1's design. All other traps, and
    `coreference_trap` (which the spec lists as a plant type), are v1. This moves `arity_control` from v1 (§14, step 8)
    into v0, superseding step 2's "built when the spec schedules traps".
21. **Dependencies:** PyYAML and cryptography are declared in `pyproject.toml` under a `xonforge` extra, with minimum
    versions, after confirming that their licenses are compatible with Apache 2.0.

### Readings applied

These come with the instructions that relayed the answers, so that nothing is guessed.

- Item 7's `docs/prompts/` is the spec's path. Under the in-package layout (the step 1 decision's `xonforge/prompts/`)
  the prompts go where the draft rendering prompt lives, so the draft rendering prompt, until now a string in
  `xonforge/render/prompt.py`, moves into `xonforge/prompts/` with the two review prompts, each stored verbatim,
  versioned and hashed. This replaces the implementing agent's `xonforge/docs/prompts/` of step 5.
- Item 10's "(The 20-document sample gets at least 2.)" is a rule: at least 2 for the sample run, or every unflagged
  document if there are fewer than 2.
- Item 17's check of the commits being pushed is a `python -m xonforge` command, and the full-history audit another.
  No git hook is installed and no git configuration is changed; the user decides how the pre-push check is triggered.
- The leak test reads only the committed manifests and the files it scans, and never opens the sealed or judged
  locations. It only reads files in the XON folder, never writes them. With no sealed manifest yet, it passes quickly.
- Item 6: A1's scan code is copied from this branch's copy, with the source file and commit recorded, and replaces the
  import-based reuse; A1's files stay unchanged. The L1 material used for canaries (item 5) is also taken from this
  branch's copy, with its source recorded.
- Item 4's lexical-variety levels have labels but no wording: the instruction for each level is drafted in the draft
  rendering prompt, marked as a draft, for Ian's review.
- Item 21: the minimum versions are the installed versions unless a lower floor is known to work; the licenses are
  checked from the installed packages' metadata; both are logged.
- The pipeline-test mode is chosen explicitly for a run and is never a fallback when providers are missing. Without
  it the cross-provider rule applies, and a corpus-of-record run refuses to start with fewer than three configured
  providers. Only in this mode may the renderer and the reviewers be different models of one provider. Splitting and
  placement refuse to put a `pipeline_test` document into the sealed or judged split; acceptance, sealing and export
  exclude such documents from any corpus of record; the datasheet says so.
- The pipeline-test sample's per-provider cap applies to each of its three registry entries, since XonForge's budget
  caps each entry; the $20 run cap bounds the three together, so the sample's Anthropic spending stays within $20.
  (The implementing agent's reading.)

The implementing agent's readings in building steps 2 to 6 on these answers, each to be confirmed
(`CHANGELOG_EXPERIMENTS.md`, the entry of the same date, lists them all):
- Item 4's spread: at level 2, the planted sentences span at least half the document's words, from the start of the
  first to the end of the last; at level 3, "in the first and last quarters" means the first planted sentence begins
  in the first quarter of the words and the last begins in the last quarter.
- Item 5: the raffle-win leaks are not canaries, since they hint at L1's hidden claim through the narrative's tone and
  contradict nothing; and A1's activity-synonym scan, a leak check for that hidden claim, is not copied, since v0's
  plants have no hidden claim, so no activity-synonym canary is written either.
- Item 7: every quote character is stripped, apostrophes included; a plant's sentences are its planted facts' and the
  arity fact's. Item 8: each reviewed item is its own call. Item 9: a batch's canaries come first from those on its
  attributes, taken round-robin over the defect kinds; a batch that cannot be certified flags each of its documents.
- Item 12: the genre and trap quotas are balanced across the cells by dealing them over the plan's units in
  proportion, and a trap goes only to the plant types that admit it. Items 13 and 15: the quota and split seeds are
  logged in the decision log, as the sample seed is.
- Item 16: `LICENSE.txt` names CC BY 4.0 and links its legal code rather than reproducing it. The terms check is
  logged in `xonforge/config/terms.yaml` and gates export for the renderers' providers, whose outputs the export
  publishes; the reviewers' replies are not exported.
- Item 17: the templates whose 8-word sequences are left out are each sealed document's own skeleton statements, as
  the templates word them. The committed manifests the test reads are fingerprint manifests,
  `data/xonforge/fingerprints/<version>-<split>.json`, written when a split is sealed, holding only hashes. A whole
  document is matched as a whole file or as a JSON string value. A file that is not UTF-8 text is not searched, and
  is reported.
- Item 19: `SEALED.md` and the datasheet record the SHA-256 of a sealed or judged split's canary string, not the
  string, so that the search for it stays clean.

### Still open

- The 20-document sample's composition: what the 20 documents are, whether a consistent twin counts as one of them,
  whether the sample is split and sealed, and whether the fact audit runs in it.
- The check of each provider's terms on publishing its outputs as a dataset, before the first export (item 16), which
  needs web access.
- The providers to add before the first corpus of record.
- Token caps for the sample: none is given, and XonForge's budget sends no call unless its token caps are set as well
  as its dollar caps. (Noted by the implementing agent.)
- Whether each reviewer runs both review prompts, which doubles the review calls; the cost estimate assumes both.
  (Noted by the implementing agent.)
- What a quota unit counts, a document or a base. (Noted by the implementing agent.)
- The lexical-variety wording, drafted for Ian's review (`xonforge/prompts/render_wording.json`).

### Ian's text

Ian's answers, verbatim:

```
ANSWERS — XonForge v0 open questions

TO ACCEPT A FIRST DOCUMENT

1. Spacing: at least one non-planted sentence between any two planted
   sentences (constant). The plant-distance knob controls overall spread
   on top of that. The binary-parity arity sentence is not a planted
   sentence (recorded separately as arity_fact, as decided): it is
   exempt from spacing and from plant distance, but must be present.

2. Twins: the twin's "planted" facts are the counterpart facts at the
   same positions (the flipped relation, the "same" replacing one
   "different", the compatible negation), recorded as twin_facts with
   spans, under the same spacing and forbidden-content rules.
   Rendering: render the CONSISTENT twin first, from its skeleton.
   Derive the planted variant from the twin's text by re-rendering only
   the changed sentence(s) in place, leaving every other byte identical.
   This enforces the minimal-edit decision, and the renderer never
   writes prose around a contradiction it knows about. Structural checks
   run on both texts.

3. "Inferred" facts: the map holds {mode: "inferred", support_spans:
   [verbatim spans the fact follows from], derivation: the solver's
   rule, e.g. "3:00 + 2 h = 5:00"}. Each support span must appear
   verbatim. For v0's plant types (order_cycle, equality_break,
   binary_parity, direct_negation) explicitness is only "stated" or
   "paraphrased"; "inferred" starts in v1 with the arithmetic, time and
   location types. Define the schema now, generate it later.

4. Difficulty levels (bundles of §5.4 knobs; actual values recorded per
   document):
   - Level 1 (L1-like): 150–300 words; cycle 3–4; stated; distractors
     0–1 per planted fact, other attributes only; low lexical variety;
     3–5 entities, 2–3 attributes; any plant distance.
   - Level 2: 400–800 words; cycle 3–5; stated or paraphrased;
     distractors 1–2, same-attribute distractors on; medium variety;
     5–8 entities, 3–5 attributes; planted sentences spread over at
     least half the document.
   - Level 3: 1,000–3,000 words; cycle 4–6; paraphrased; distractors
     2–3, same-attribute on; high variety; 8–12 entities, 5–8
     attributes; first and last planted sentences in the first and last
     quarters.
   Length tolerance: within ±15% of the document's target word count
   (at least ±25 words); a miss counts as a failed check for retries.

5. Canaries:
   - Scan canaries: small synthetic documents written for each scan and
     each attribute pattern (e.g. two "first"s, a same-attribute leak,
     an activity synonym), plus the real defects the L1 scans found
     (e.g. base 32's superlative clash, the raffle-win leaks).
   - Review canaries: defect canaries from the same sources; clean
     canaries from L1's 60 consistent documents (the post-hoc analysis
     found no unplanted contradictions in them).
   - L1 material may be used: canaries calibrate reviewers and are never
     evaluation data. Once the first development documents are
     accepted, add canaries derived from them (a known defect inserted
     into an accepted text), so canaries also match XonForge's style.
   - No canary ever comes from, or goes into, a sealed or judged split.

6. Scans: yes, copy A1's scans into xonforge/verify/, record the source
   file and commit in the changelog, and extend them there: score,
   speed, club, department, table, cabin, and "arrived later than". A1's
   copy stays unchanged. Each new pattern needs its own scan canary.
   Keep the current rule meanwhile (fail closed): a document with an
   attribute that no scan pattern covers is not accepted; it waits.

FOR REVIEW

7. Prompts (docs/prompts/, versioned, hashed):
   - contradiction-only: "List every set of two or more statements in
     this document that cannot all be true at once. Quote each
     statement verbatim. Do not report statements that are merely
     unlikely or surprising, or that are resolved by time, quotation,
     belief, hypothesis or correction. If there are none, return an
     empty list."
   - relational-inventory: "First list every statement that relates
     people or things (order, same or different, counts, times,
     places, roles), quoted verbatim and grouped by attribute. Then
     check each group and report conflicts in the same format."
   Reply (structured output):
     {"conflicts": [{"statements": ["verbatim", ...],
                     "explanation": "one sentence"}]}
   plus "inventory": [...] for the second prompt (kept for audit).
   Matching: normalize (NFKC, case fold, collapse whitespace, strip
   quotes); a quoted statement matches a sentence if either contains
   the other. A reported conflict matches the plant (or a canary's
   defect) if its matched sentences include at least
   min(2, number of defect sentences) of the defect's sentences.
   Anything matching neither goes to the human queue.

8. Batch: up to 20 generated documents reviewed by one reviewer with one
   prompt in one run step, sent as one call or several (long documents
   one per call), plus that batch's canaries. Recall = detected defect
   canaries / defect canaries in the batch, as an exact fraction, no
   rounding; the batch is certifiable only if recall >= 0.8.

9. Canaries per batch: 5 defect canaries (so one miss still passes:
   4/5 = 0.8) and 2 clean canaries, drawn by a logged seed, covering the
   defect kinds relevant to the batch's attributes where possible,
   shuffled in under opaque ids. This exceeds the spec's 10% minimum.
   Record false alarms on the clean canaries per batch.

10. Random 10%: seed fixed and logged before any review; from the
    unflagged documents sorted by id, draw ceil(0.10 × n), minimum 1,
    without replacement. (The 20-document sample gets at least 2.)

BEFORE ANY LIVE CALL

11. Providers and budgets: [IAN: list the providers you have keys for.]
    At least three providers are needed. Models: each provider's
    current mid-tier model, with exact ids taken from the provider's
    documentation at configuration time and recorded. Caps for the
    20-document sample: $20 per run, $8 per provider. For the first
    full corpus: estimate first; initial caps $250 per run, $100 per
    provider, adjusted from the sample's measured costs.

FOR THE FULL CORPUS AND EXPORT

12. Quotas: a full cross of plant type × difficulty level × renderer
    provider; genre and trap type as separate per-dimension quotas
    balanced across the cells. A full cross of all five dimensions has
    too many cells to fill.

13. Rounding: largest remainder, so cell sizes sum exactly to the
    target; ties broken by a logged seed.

14. Unfillable: when a cell's attempts reach max(10, 3 × its quota)
    without filling it. Report it, keep filling the others, and don't
    redistribute automatically; I decide.

15. Splits: stratified by plant type × difficulty level, seeded random
    within each stratum, largest-remainder rounding; the seed is logged
    before generation. All variants of a base stay together.

16. License: CC BY 4.0 for the corpus, with the "not for training"
    notice (a request, not a license term). Before the first export,
    check each provider's terms on publishing their outputs as a
    dataset, and log the result. LICENSE.txt in each exported folder:
    yes. [IAN: confirm CC BY 4.0.]

17. Leak test: all of the following.
    - One canary string per split (answering 19), searched everywhere.
    - Whole-document hashes.
    - Word sequences, k = 8, after normalizing (NFKC, case fold,
      collapsed whitespace, stripped punctuation and quotes): flag any
      file sharing 2 or more distinct 8-word sequences with any one
      sealed document, after excluding sequences that occur in the
      generator's own prompts and templates.
    - Scope: every file in both worktrees, tracked or not (excluding
      .git), on every test run, plus the commits being pushed before
      each push. The audit also scans the full history.

18. (Answered in 17.)

19. One canary string per split, so development files carry only the
    development canary and the search for the sealed one stays clean.

SMALLER POINTS

20. Traps: arity_control is in v0 (it's binary parity's partner and part
    of L1's design). All other traps, and coreference_trap (which the
    spec lists as a plant type), are v1.

21. Yes: declare PyYAML and cryptography in pyproject.toml under a
    xonforge extra, with minimum versions; confirm their licenses are
    compatible with Apache 2.0.

Record all of these in decisions.md and the changelog.
```

His answer to item 11, verbatim:

```
11. Providers: only Anthropic is available for now.
    - Add a pipeline-test mode: renderer and reviewers may be different
      models of one provider (renderer and reviewers must still be
      different models). Every document made in this mode is labeled
      pipeline_test, can never enter a sealed or judged split, and is
      excluded from any corpus of record. The datasheet says so.
    - The 20-document sample runs in this mode with Claude models
      (exact ids from Anthropic's documentation, recorded), at most
      $20 per run.
    - The cross-provider rule stays in force for every corpus of record;
      its first run waits until at least three providers are configured.
      I'll add Gemini and OpenAI or a local model before then.
```

His choices for the pipeline-test sample, from options put to him, as relayed: a per-provider cap of $20, the same as
the run cap; the renderer `claude-sonnet-5`; the reviewers `claude-opus-5-5` and `claude-fable-5-1`. The model table,
prices and request-shape facts above were relayed with them, checked in the two pages cited on 2026-09-25.
