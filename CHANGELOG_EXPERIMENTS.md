# Experiment changelog

Pre-registration log for the XON SIM experiments. Every experiment's protocol and pass thresholds are fixed in
`xon/experiments.py` (`REGISTRY`) before it is run. A later change of protocol is a **re-registration**: it is
recorded here with its date, the old criterion, the new criterion and the reason, and the old protocol stays
runnable under a `_v1` id, or `_v2` for a second preserved version (`python -m xon.run_tests --include-v1`, or
the toggle in the Test Suite tab).

Unchanged in V1.1: **E1, E5, E6, E7** (protocols and thresholds exactly as in V1). E6 keeps its V1 criterion; it
now runs because `OscillatorDynamics` is implemented.

V1.2 adds experiments without re-registering any: E9a–E9c and the E1 lattice control live in their own table,
`REGISTRY_V1_2`, so that `REGISTRY` stays exactly as pre-registered for V1 / V1.1. After the first V1.2 run
E9c was re-registered three times (below). Its first registration stays runnable as `E9c_v1` and its first
re-registration as `E9c_v2`; the second was superseded before it was implemented.

A1 (the consistency engine, `xon/llm/`) is not part of either registry: its experiments L1, L1b and L1-var are
pre-registered in `XON_A1_CONSISTENCY.md` and the A1 entry below. Its revision 2.2 (`XON_A1_REV2_2_PRECISION.md`)
has its own, newer entries.

---

## 2026-09-26 — XonForge — the 20-document sample run

The user said to run the sample, with the Anthropic key set as a cloud secret. The run orchestrator of step 7 was not
built, the sample's composition and token caps were open, and the budget sends no call without token caps. No threshold
in the spec was changed. The choices below are the ones the run uses; the sample then stops for review. It does not
accept, export, split or seal, and the first corpus is not started.

1. **Token caps.** `runs.sample` in `xonforge/config/defaults.yaml`: 2,000,000 tokens for the run and for each entry,
   beside the $20 caps already set. At Sonnet 5's output price of $10 per million tokens, $20 buys 2,000,000 tokens, so
   a larger token bill than that would already have passed the dollar cap. The dollar cap remains what stops the run.
2. **Composition.** Ten level-1 bases, seeds 1 to 10, dealt in turn across the four v0 plant types: `order_cycle` and
   `equality_break` three each, `binary_parity` and `direct_negation` two each. Each base is a consistent twin and one
   planted variant, 20 documents. A twin counts as a document. No trap variant. Genre: office memo. The fact audit does
   not run. The sample is a pipeline test, so it is not split and not sealed.
3. **Review.** Each reviewer runs both prompts. Thinking is left at each model's adaptive default (Sonnet 5 is not sent
   the switch that turns thinking off). A review uses the same `max_tokens` as a rendering, 16,384, so the ceiling
   covers reasoning plus the reply. The sample seed is 1, the quota seed 2 and the split seed 3, logged before
   generation. The quota and split seeds are not used to place documents.
4. **The command.** `python -m xonforge run sample` (`xonforge/pipeline.py`) generates the bases, renders, reviews and
   queues, and stops. Documents, skeletons, batches and the review packet stay outside the repository. Re-running the
   same command continues from what was saved and from the response cache.

5. **The live run, stopped for review.** `python -m xonforge run sample`, with `XONFORGE_ANTHROPIC_KEY` set and the cache,
   sealed and judged directories outside the repository. `constraints.txt` SHA-256
   `e9b0e25e3b8f223c5d00c7d94a363611c9e2521b184b7b3c365bebd1b5add2e1` (the pinned versions installed; this machine is
   Python 3.12, and the file was recorded on Python 3.14). The offline estimate at first attempts, with the assumed
   thinking, was $9.27. The run spent $2.7326 and 225,220 tokens, inside the $20 cap:

   | Entry | Tokens | USD |
   | --- | ---: | ---: |
   | claude-sonnet | 79,650 | 0.5909 |
   | claude-opus | 68,759 | 0.4967 |
   | claude-fable | 76,811 | 1.6449 |

   All 20 documents rendered. Three twins needed a second attempt (`order_cycle-5-54821720`, `binary_parity-7-c608ec82`,
   `direct_negation-8-3a6a9019`); every other rendering and every derivation passed on the first attempt. No document
   was flagged by the checks or the scans. Word counts were 172 to 268, against level-1 targets of 200 to 260.

   Each reviewer, with each prompt, scored 5/5 on the batch's defect canaries and 0/2 false alarms, so every batch was
   certifiable. Both reviewers reported the plant on 10/10 planted documents with the relational-inventory prompt, and
   on 9/10 with the contradiction-only prompt. Both missed `direct_negation-8-3a6a9019-planted` on that prompt. A
   missed plant is not a flag, so that document was not queued.

   The queue is the sample's two spot checks of unflagged documents, drawn with seed 1:
   `direct_negation-4-6f274ae4-planted` and `equality_break-10-c4d83c55-planted`.

   The run stopped there. Nothing was accepted, exported, split or sealed, and the first corpus was not started. The
   call log, which holds no document text, is `cache/xonforge/log.jsonl`. The review packet, which holds the texts,
   stays outside the repository.

6. **The spot checks accepted.** The user accepted both queued documents. Each is an `accept` in the decision log,
   reason "Accepted on the spot check.", with no reviewer named. The chain verifies: 5 entries, head
   `8a0bf9e3054f8623829ed7e542bd66779bf4e327e9a5107778fb8bc9ce3e429b`. Acceptance, in pipeline-test mode, accepts both.
   The log stays outside the repository. Nothing was exported or sealed.

---

## 2026-09-26 — Repository — the fresh-clone check: the install fixed, exact versions in `constraints.txt`

After the third reset's push, `main` (`bbf05d9a`) was cloned from GitHub into a temporary folder outside the
project, installed into a new virtual environment as the README said, and tested offline, with A1's key and every
`XONFORGE_*` variable unset. No failure came from a file that exists only on this machine, but the documented
install was incomplete; it is fixed below. No API call was made.

1. **What failed.** The README's `pip install -e ".[dev]"`:
   - left out the `xonforge` extra, so seven of XonForge's test modules could not import `yaml`, and their
     collection errors stopped `pytest`, XonForge's tests and `pytest -m slow` before any test ran. Only the
     dry-run app test, run by name, passed;
   - did not install `httpx`, which `tests/xonforge/test_xonforge_providers.py` imports and one test in
     `tests/test_llm_client.py` skips without. It came with anthropic 0.84.0, and anthropic 1.8.0 depends on
     `httpx2` instead;
   - took the newest versions the lower bounds allow, newer than this machine's: anthropic 1.8.0 (0.84.0 here),
     numpy 2.5.3 (2.4.1), scipy 1.18.1 (1.17.0), pandas 3.0.6 (3.0.0), pydantic 2.13.5 (2.12.5), networkx 3.7
     (3.6.1), pytest 9.1.1 (9.0.2), PyYAML 6.0.3 (6.0.2) and cryptography 50.0.1 (46.0.5). Of the direct
     dependencies, only streamlit (1.64.0) and plotly (7.1.0) matched.
2. **With the `xonforge` extra and `httpx` added**, the clone's results were this machine's: `pytest`, 949 passed,
   1 skipped (the leak test's commit search, on a root commit) and 26 deselected; the dry-run app test passed;
   XonForge's tests, 501 passed and 1 skipped; the 26 slow tests passed. The newer versions changed no tested
   result: the rev. 2.1 recompute of the run of record's `l1.json`, `l1b.json` and `documents.jsonl` is byte for
   byte, and every rev. 2.1 request body is the recorded one. No live call has gone through anthropic 1.x. XonForge
   has no default locations, so the tests could not reach this machine's sealed, judged or cache data, and the runs
   left the clone's tracked files unchanged.
3. **Packaging.** The editable install packages only `xon` and `xon.llm`, so `xon_common` and `xonforge` are found
   only from the project's root. Nothing failed: every documented command runs from the root, and the engine
   imports neither.
4. **The fix.** `pyproject.toml` adds `httpx>=0.28.1` to the `dev` extra and keeps lower bounds only, with no upper
   caps. `constraints.txt`, new, pins this machine's exact versions of the 66 packages the project and its extras
   install (Python 3.14.0, Windows 11); a dry-run resolution of every requirement with it gives exactly those 66,
   and nothing unpinned. The README's install line is now `pip install -e ".[dev,xonforge]" -c constraints.txt`,
   `run_xon.bat`'s hint adds `png` to the same extras, and `xonforge/README.md` points to the line and says to run
   its commands from the root.
5. **From now on** (`rules.md`, rule 7, and `decisions.md`): each run of record records `constraints.txt`'s SHA-256
   in its `run.json` or its changelog entry, and if the installed versions no longer match the file, it is updated
   and committed before the run.
6. **Next.** A fresh clone, installed with the new line, is tested again.

---

## 2026-09-26 — Repository — the third reset: XonForge merged into `main`, one branch in one folder

XonForge's branch is merged into `main`, and the project lives in one folder, `XON`, with XonForge as its package
`xonforge/`. Pushed as it stood, `main` would have published the history from before the second reset, the journal
included, through `xonforge`'s commits, so the repository's history starts again: one root commit, "Initial
commit", tagged `repo-reset-2026-09-26`, holds the merged tree with the changes below. Nothing is force-pushed, and
the push waits for the user's word that the re-created GitHub repository exists and is empty. No API call was made.

1. **Before the merge.** On `xonforge`, the journal, the old README and the six PDFs were removed, as on `main`
   (`f3e8a17e`), and XonForge's steps 2 to 6, which "XonForge — v0's core on the user's answers" (below) left
   uncommitted, were committed (`cc50c1bb`). On `main`, gate D0's stopped start (below) was committed (`a6038134`).
2. **The merge.** `xonforge` forked from `main` at `7a63cfde`, before the second reset, and `main` restarted at the
   second reset's root commit, `5a09e4c7`, so the two branches shared no commit. For the merge, a temporary graft
   (`git replace --graft 5a09e4c7 53997a1f`) gave that root commit the old `main`'s last commit as its parent; the
   two differ only in the second reset's 25 files (its entry below). git then found `7a63cfde` as the merge base.
   The merge commit, `da8515d2`, joins `a6038134` and `cc50c1bb`, and the graft was removed right after it, before
   the archive was made. The merged tree keeps `main`'s README and the second reset's replacements of local paths,
   and this changelog holds both branches' entries.
3. **XonForge's worktree**, `XON-xonforge`. Every file it tracked is in the merged tree: 7,743 identical, 26 that
   `main` changed after the fork, and this changelog, which holds all 24 of XonForge's entries unchanged. Nothing
   had to be copied. The worktree was unregistered (its `.git` link file deleted, then `git worktree prune`), and
   the folder stays as a plain folder until the fresh-clone check; then the user deletes it.
4. **The archives**, in the user's private folder, outside the repository:
   - `git-archive-2026-09-25-pre-reset.zip`, SHA-256
     `70c4331bc91f5513b42cf8c1c89fa4fe699aeff7e704107a82d7ed4e7adf36f6`: the whole `.git` folder as it was before
     this reset, with a listing of every branch, tag, commit and reflog. It holds 35 commits: 26 reachable from
     `main` (`da8515d2`), `xonforge` (`cc50c1bb`) and the tag `repo-reset-2026-09-25` (`5a09e4c7`); 8 reachable
     only from the reflog, `main`'s commits from `a9d0ce25` to `53997a1f`, which the second reset left behind; and
     one that nothing reaches (`6419a035`, with the second reset's message and date). It also keeps the tag object
     of `a1-run-of-record` (`141bc117`, on `1b1749b4`), which no ref has pointed to since the second reset. The zip
     opens with Python's and .NET's extractors, every file in it matches the original's SHA-256, and an extracted
     copy passes `git fsck --full`. The `.git` folder was deleted only after these checks.
   - `XON-history-before-reset-2026-09-25.zip`, made at the second reset: a git bundle of the history since the
     first reset (28 commits, from `1b1749b4` to `53997a1f` on `main` and `5fbd893f` on `xonforge`, the tag
     `a1-run-of-record` on `1b1749b4`, and `origin/main` at `198e68d1`), a list of its refs and hashes, and restore
     notes.
5. **Hashes and tags from before this reset** refer to the archived history, and none of them is in this
   repository: every commit hash quoted in this changelog and in `decisions.md` before this entry, every commit a
   results file records, the tag `a1-run-of-record` (in both archives) and the tag `repo-reset-2026-09-25` (on
   `5a09e4c7`, in `git-archive-2026-09-25-pre-reset.zip`). Neither tag is re-created.
6. **Correction: the history before `1b1749b4` was not archived.** The first reset's records say that the old
   history, tags and hashes are archived privately as a zip outside the repository: item 6 of "A1 rev. 2.2,
   development iteration 1: the user's decisions, and Step 0" (below) and `decisions.md`'s "2026-09-25 —
   Repository — the history reset". That is wrong. No such archive was made, and that history was not preserved;
   it was an oversight on the project's first day. `1b1749b4` ("Snapshot: V1-V1.2 and A1 rev 2.1, after the L1 run
   of record", 2026-09-25T10:09:57-07:00) records no parent: it is a root commit, so git holds nothing from before
   it. The provenance of the runs before it rests on this changelog, the cache replay and the recorded hashes, not
   on git history. The earlier records are left as they are.
7. **From now on** (`decisions.md`): one branch, `main`, in one folder; parallel sessions each commit only the files
   they changed, after pulling or checking `git status`. Git archives, XonForge's cache, the sealed and judged
   splits and the private folder never live inside the project, and `.gitignore` now ignores git archives and
   history bundles (`git-archive-*.zip`, `*.git-archive*`, `XON-history-*.zip`, `*.bundle`). The Git section of
   `rules.md` gains the one-branch rule and the call log's 45 MB stop (item 11).
8. **Fixes and wording**, in tests and text only.
   - The leak test's commit search listed the files `HEAD` changed with `git diff-tree`, which lists none for a
     merge commit, so it failed on the merge commit (949 passed and 1 failed just after the merge). It now compares
     `HEAD~1` with `HEAD`, and skips when there is no commit yet or `HEAD` has no parent, as on the new root
     commit; it first runs at the next commit.
   - `test_a_location_inside_any_worktree_is_refused` asserted that git's files list the project root as a
     worktree, so it failed without `.git`, as in a downloaded copy or between two steps of this reset. As the user
     decided, it now checks the project root always, which XonForge refuses with or without a repository, and
     every worktree git lists when there is one. It passes in a copy without `.git`.
   - "Both worktrees" and "either worktree" now read "every worktree" and "any worktree" in `xonforge/README.md`,
     `xonforge/cli.py` (its help, and the report's label, "Every worktree:"), `xonforge/corpus/leak.py` and the
     leak test (its docstring, an assertion, and its name, now `test_no_sealed_document_is_in_any_worktree`). The
     `decisions.md` header no longer mentions the `xonforge` branch. Left as they are: this changelog's and
     `decisions.md`'s older entries, `xonforge/docs/decisions.md`, and the user's audit prompt, which still
     describes two worktrees and which the user is redesigning.
9. **Local paths.** The nine files in which the second reset replaced the Windows user folder by `%USERPROFILE%`
   keep that text: `results/a1-l1-run-of-record.log`, `results/a1-rev22-full-run.log`,
   `results/a1-l1-recompute.log`, `results/a1-l1var-run.log`, `data/consistency/corpus_generate.log`, and the
   `run.json` of `results/a1-20260924-232324/`, `results/a1-20260924-233306/`,
   `results/a1-rev22-d0-20260925-123136/` and `results/a1-rev22-full-20260925-124414/`. The same replacement is made
   in XonForge's step-0 entry (below), in its worktree's path. In each, only the user folder was replaced; no number
   or message changed. The unredacted originals are in the archives.
10. **The scan before the root commit**, whose results the user saw first: all 30,203 files, for keys and key
    assignments, local paths, and names and emails other than the project contact's.
    - Keys: A1's key is in no file. The key-shaped strings are the tests' fake key and canaries and the README's
      placeholder.
    - Local paths: only XonForge's step-0 entry (item 9). The audit prompt's match is an example path pattern.
    - Emails and names: only the project contact's. The GitHub account's name appears in one entry's remote URL.
      The 337 figures carry no text metadata.
11. **The call log.** The only file over 10 MB is `cache/llm/log.jsonl`, at 34.9 MB, and it stays tracked. As the
    user decided, when it approaches 45 MB work stops and a rotation is proposed (for example one log file per run
    under `results/`, with the main log restarted), rather than letting it pass GitHub's 50 MB warning.
12. **Recomputes and tests**, offline, with A1's key unset.
    - The L1 recompute from the cache (`scripts/run_consistency_eval.py --budget 0`, into a temporary folder,
      without appending to the call log) made no API call. Its `l1.json`, `l1b.json` and `documents.jsonl` are byte
      for byte the run of record's (`results/a1-20260924-232324/`). Known differences, not regressions:
      `results.md` gains a first line, "Engine version 2.1."; each of the 180 files in `analyses/` gains nine
      fields, and no other value changes: `engine_version`, `threshold`, and in `report`, `engine_version`,
      `threshold`, `tension_pairs` and `llm_usage`'s `batch_calls`, `cache_read_tokens`, `cache_write_tokens` and
      `transport_retries`; `run.json` gains `engine_version` and the same four counters, and records the
      recompute's corpus path and dry-run state. The audit can decide later whether the recompute should
      reproduce the old format exactly.
    - The L1-var recompute (`scripts/recompute_l1var.py`) is byte for byte
      `results/a1-20260924-233306/l1var_recomputed/`. Neither recompute wrote to a recorded results folder.
    - The whole suite: 949 passed, 1 skipped (the leak test's commit search) and 26 deselected; the 26 slow tests
      pass, the rev. 2.1 byte-identical replay among them; XonForge's tests: 501 passed, 1 skipped. The sealed-text
      leak test, the key-name, import-boundary and log-text tests and the dry-run app test pass. With no
      fingerprint manifest yet, the leak test has nothing to search for.
13. **Next.** After the push, a fresh clone outside the project is installed and tested, and the user deletes
    `XON-xonforge`.

---

## 2026-09-25 — XonForge — v0's core on the user's answers: steps 2 to 6, offline

Built on Ian's answers of 2026-09-25, items 1 to 21 (`xonforge/docs/decisions.md`), and left uncommitted at his
instruction ("don't commit anything, just finish the build"). No model was called and nothing was installed. The
20-document sample stays a gate: it waits for its token caps, its composition and Ian's go-ahead after the cost
estimate. Offline, the XonForge tests pass (496, in `tests/xonforge/`), and so does the whole suite: 924 passed,
26 deselected, and the 26 slow tests passed.

1. **Skeletons and the solver** (items 2, 3, 4 and 20).
   - A consistent twin records `twin_facts`, its counterparts of the plant's facts, which its checks treat as planted.
   - `arity_control` is in v0: with `traps=("arity_control",)` a `binary_parity` base gets a trap variant whose arity
     fact states three values. The solver checks that it holds and records what a naive two-value reading would flag,
     the planted facts. `python -m xonforge skeletons --arity-control` shows it.
   - An inferred fact's map entry (`mode: "inferred"`, `support_spans`, `derivation`) is defined; v0 renders none.
   - `xonforge/levels.py` holds the three difficulty levels; a document's render rules record its level and the
     length, explicitness and lexical variety drawn for it.
2. **Rendering** (items 1, 2, 4 and 7).
   - Twin first: `render` writes the consistent twin from its skeleton, and `derive` makes each planted variant from
     the twin's text, and a trap variant from its planted variant's, by re-rendering only the sentences of the facts
     that differ and putting them in place, every other byte kept. Acceptance checks that. This replaces step 3's
     renderer, which rendered each planted variant from its own skeleton.
   - The prompts are files in `xonforge/prompts/`, each recorded in `versions.json` with its version and SHA-256, and
     a file that no longer matches its hash is refused until a new version is recorded: `render.txt`
     (render-v0-draft-3), `derive.txt` (derive-v0-draft-1), `render_wording.json` (render-wording-v0-draft-1), and
     Ian's two review prompts, verbatim, which step 5 waited for in `xonforge/docs/prompts/`.
   - The checks: at least one sentence between any two planted sentences; the arity sentence exempt from spacing,
     spread and plant distance but present; a length within 15% of the target, and at least 25 words; at level 2 the
     planted sentences spanning at least half the words, and at level 3 the first beginning in the first quarter and
     the last in the last quarter.
   - **The lexical-variety wording is a draft for Ian's review**, since item 4 names the levels without wording:
     - low: "Use short, plain sentences and everyday words, and call each person, group and attribute by the same
       words throughout."
     - medium: "Vary the wording moderately: use some synonyms, and mix sentence lengths and structures, keeping each
       fact's meaning exact."
     - high: "Vary the wording widely: use synonyms, varied sentence structures and some idiomatic phrasing, avoid
       repeating a phrasing, and keep each fact's meaning exact."
3. **Verification** (items 5 and 6).
   - **The scan copy's source.** A1's scan code is copied into `xonforge/verify/scanners.py` and `sentences.py` from
     commit `1b1749b4afcea1106c439306bcc8600b44095263`; neither source file has changed since. From
     `xon/llm/corpus.py`: `_SUPERLATIVE_CUES`, `_owners_of_cue`, `superlative_collisions`, `_boundaries`,
     `_sentence_spans`, `_sentence_texts` (named `sentences` here), `normalize_ws`, `occurrences`, `QUOTE_CHARS` and
     `TITLES`. From `xon/llm/corpus_qa.py`: `_ORDER_PATTERNS`, `_ATTRIBUTE_CUES`, `_nonplanted_sentences`,
     `same_attribute_hits`, `extract_order_edges`, `_find_cycles` and `order_cycle_scan`. A test compares each copied
     function with A1's source. `xonforge/verify/a1.py`, the reuse by import, is deleted; nothing in `xonforge/`
     imports `xon`, and A1's files are unchanged.
   - The patterns are extended with score, speed, club, department, table, cabin and "arrived later than". The
     attribute names are A1's (`arrival_time` for XonForge's `arrival`), and `scans.py` maps XonForge's onto them.
   - Scan canaries: 34 synthetic ones covering every pattern of every scan, each caught on its own pattern, and base
     32's superlative clash from L1 (`data/consistency/corpus_review_pack.json`, `attempt_flagged/32/text`, at the
     same commit).
   - The fail-closed rule stays. Its reason now reads "waits for a scan pattern: the <scan> scan has no pattern for
     <attributes>, and a document is not accepted until it has".
4. **Review** (items 5, 7, 8, 9 and 10).
   - The reply schemas are Ian's: conflicts of verbatim statements with a one-sentence explanation, and the inventory
     for the second prompt. Matching is item 7's. A batch is up to 20 documents, one reviewer and one prompt, and each
     item is its own call, which item 8 allows.
   - Review canaries: 14 synthetic defect canaries with one contradiction each, covering XonForge's ten attributes and
     five defect kinds (superlative, order cycle, same and different, negation, parity); base 32's superlative clash;
     and L1's 60 consistent documents as clean canaries (`data/consistency/corpus.jsonl`, at the same commit).
   - A batch draws 5 defect and 2 clean canaries with its seed. Recall is an exact fraction, and a batch is
     certifiable at 4/5 or more.
   - Flagged for the human queue: every reported conflict that does not match the plant; no usable reply; a missing
     review (reviewer and prompt); and every document of a batch that cannot be certified.
   - The random share: ceil(n/10) of the unflagged documents sorted by id, at least 1, and at least 2 in the sample
     (or all of them if fewer), with the run's logged seed.
5. **The corpus** (items 12 to 17 and 19).
   - Quotas (`xonforge/corpus/quotas.py`): the full cross of plant type × level × renderer provider, balanced or
     weighted per dimension; genre and trap quotas per dimension; largest remainder with ties broken by a seed; a
     cell unfillable after max(10, 3 × its quota) attempts, reported, and nothing redistributed.
   - Splits (`xonforge/corpus/splits.py`): stratified by plant type × level, seeded within each stratum, with largest
     remainder; the spec's 50 / 15 / 35 by default. A pipeline test gives its own proportions, for development and
     calibration only.
   - The decision log records a quota seed and a split seed beside the sample seed, each once per run and before any
     decision on it.
   - Export: CC BY 4.0, which `LICENSE.txt` names with a link to its legal code, and the "not for training" notice
     worded as a request that is not a term of the license. This replaces the wait for a license. One canary string
     per split: a split's files, and its folder's README and license, carry only their own splits' strings, and
     `SEALED.md` and the datasheet record only the SHA-256 of a sealed or judged split's string.
   - The terms check: `xonforge/config/terms.yaml` logs each provider's check (the date, the result and the pages
     read). None is logged, since the check needs web access, so placement waits.
   - The leak test (`xonforge/corpus/leak.py`): a split's fingerprint manifest, committed when it is sealed, holds
     the SHA-256 of its canary string and, per document, the SHA-256 of its normalized text and the hashes of its
     8-word sequences, less those in the prompts and in its own skeleton statements. A file is flagged as item 17
     says. `tests/xonforge/test_xonforge_leak.py` searches both worktrees on every test run;
     `python -m xonforge leak-check --commits <range>` searches the commits being pushed, and `leak-audit` the whole
     history, with read-only git. No git hook is installed. With no manifest, all of them pass at once.
6. **The cost estimate** (`xonforge/estimate.py`, `python -m xonforge estimate`). It builds the prompts each call
   would send from seeded skeletons, counts 1.3 tokens per word times the Claude tokenizer's 1.3, counts thinking as
   output at tokens per call it assumes (rendering 4,000, derivation 2,000, review 2,000, in `defaults.yaml`), and
   assumes no caching or batch discount. Illustrative figures, since the sample's composition is open, with both
   prompts for each reviewer, without thinking / at first attempts / at 5 attempts each:
   - 10 level-1 bases (20 documents): $1.08 / $9.24 / $11.92;
   - 20 level-1 bases (40 documents): $2.22 / $18.54 / $23.92, above the $20 run cap at 5 attempts;
   - 10 level-2 bases (20 documents): $2.04 / $10.20 / $13.20.

   Thinking is most of the cost, and it is not measured yet.
7. **Readings and choices, mine, to be confirmed** (also in `xonforge/docs/decisions.md`):
   - a level's knobs drawn uniformly among its feasible combinations, its length among its multiples of 10 words,
     its explicitness among its own; direct_negation takes the level's lowest cycle length;
   - item 4's spread, as in 2 above: "at least half" measured in words from the first planted sentence's start to
     the last's end; "in the first and last quarters" as where the first and the last planted sentences begin;
   - item 7: every quote character stripped, apostrophes included; an empty statement matches nothing; a plant's
     sentences are its planted facts' and the arity fact's;
   - item 9: a batch's canaries come first from those on its attributes, round-robin over the defect kinds; a batch
     that cannot be certified flags each of its documents (fail closed);
   - item 10: the random share is capped at the number of unflagged documents;
   - item 12: genre and trap quotas dealt over the plan's units in proportion (a value's i-th copy at (i + ½) / its
     count), a trap only to the plant types that admit it, and what a unit counts, a document or a base, left open;
   - item 16: the terms gate covers the renderers' providers, whose outputs the export publishes; `LICENSE.txt` links
     CC BY 4.0's legal code rather than reproducing it;
   - item 17: the templates are each document's own skeleton statements; fingerprint manifests are the committed
     manifests the test reads; a whole document matches a whole file or a JSON string value; a file that is not UTF-8
     text is not searched, and is reported;
   - item 19: the SHA-256 of a sealed split's canary in `SEALED.md` and the datasheet, never the string;
   - the estimate's model of each call's output and its thinking figures.
8. **Not built as item 5 lists.**
   - A1's activity-synonym scan, a leak check for synonyms of L1's hidden claim outside the planted sentences, is
     not copied: v0's plants have no hidden claim. So there is no activity-synonym canary.
   - The raffle-win leaks are not canaries: they hint at L1's hidden claim through the narrative's tone ("given his
     earlier luck") and contradict nothing, so they are no review defect canary, and without the activity-synonym
     scan no scan canary either.
   - The run orchestrator of step 7, which chains these parts into a run, is not built.

---

## 2026-09-25 — A1 rev. 2.2, development iteration 1: gate D0 started, and stopped by the user before any API answer

Gate D0 under iteration 1 was started at 20:41:56 (UTC−7), after the second reset (the entry below), with
`python -u scripts/run_rev22_dev.py --subset --budget 272834 --out results/a1-rev22-d0-iter1-20260925-204156` and the
corpus and run-of-record arguments. The user stopped it about three seconds later. Gate D0 under iteration 1 has not
been run: it waits for the user's go-ahead.

- **What it did.** It replayed rev. 2.1's 12 documents and the first document's rev. 2.2 claim, pair and relation
  calls, all from the cache. The 346 rows it appended to `cache/llm/log.jsonl` (135 for rev. 2.1, 211 for rev. 2.2)
  are all cache hits, with zero tokens.
- **Spend.** No row from the API was added and no answer was cached, so A1's logged spend is unchanged. The first
  request not in the cache was the first document's inventory call; whether it reached the API before the stop is
  not known, and nothing recorded an answer.
- **Files.** No results folder was written. The console output up to the stop is kept as
  `results/a1-rev22-d0-iter1-run.log`, and the 346 rows stay in the call log, which is append-only.

---

## 2026-09-25 — Repository — the second reset: hashes and `a1-run-of-record` from before it refer to the archived history

The user deleted the GitHub repository and re-created it under the same name. The repository's history starts again at
one root commit, tagged `repo-reset-2026-09-25`. It holds the working tree as it stood after A1 rev. 2.2's iteration 1
(the entry below), without the project journal, the six PDFs of `pdfs/` and the old README. Nothing is force-pushed,
and the user decides when it is pushed. No API call is part of this step.

- **The archive.** The history since the first reset is archived as a zip in the user's private folder, outside the
  repository: a git bundle of every ref, a list of every branch, tag and commit hash, and restore notes. It holds 28
  commits, from the first reset's snapshot commit (`1b1749b4`) to `53997a1f` on `main` and `5fbd893f` on `xonforge`,
  the tag `a1-run-of-record` and the remote-tracking `origin/main`. The zip opens with Python's and with Windows'
  extractors, and a clone of the extracted bundle has the same refs and 28 commits and passes `git fsck --full`.
- **Hashes and the tag from before the reset.** Every commit hash quoted in this changelog and in `decisions.md` before
  this entry, every commit recorded in a results file written before it (`xon/export.py` records `git rev-parse HEAD`),
  and the tag `a1-run-of-record` refer to the archived history; none of them is in this repository. The tag is not
  re-created on the new root, because that name would claim the run of record's state for a tree that includes rev.
  2.2's changes; once archived, it is deleted from the local repository, so that it cannot be pushed. The run of
  record's files are in the tree unchanged.
- **Removed and ignored.** The journal and the PDFs are no longer tracked, and `.gitignore` ignores `PROJECT_JOURNAL*`
  and `pdfs/`. The user keeps both in the private folder.
- **`LICENSE`**, which the README links: the Apache License 2.0 text as apache.org publishes it, byte for byte
  (SHA-256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`).
- **The scan before the root commit**, whose results the user saw before the commit was made. The tree (30,094 files,
  the user's audit prompt included) was scanned for keys and tokens, local paths, emails and personal names, in file
  names, text, UTF-16 logs and the figures' metadata.
  - Keys and tokens: none. The one match is the test suite's `FAKE_KEY`, which is not A1's key.
  - Emails: only the project contact's, in the README. The commits' author identity is the same address.
  - Personal names: only the project contact's. Besides it, the GitHub account's name appears in one entry's remote
    URL, and published authors in the specs' reference lists. The corpus, the cache and the test fixtures use invented
    first names; they were scanned for keys, paths and emails, not for names.
  - Local paths: the Windows user folder appeared 285 times in 10 files. As the user decided, it is replaced by
    `%USERPROFILE%` in all of them, and nothing else in them changes. The files: the run of record's log
    (`results/a1-l1-run-of-record.log`, 207, in error traces), rev. 2.2's full-pass log
    (`results/a1-rev22-full-run.log`, 67), the `run.json` of the run of record's two folders and of iteration 0's D0
    and full pass (6: the corpus and record-run paths), `results/a1-l1-recompute.log`, `results/a1-l1var-run.log` and
    `data/consistency/corpus_generate.log` (4), and `decisions.md`'s entry on XonForge's worktree (1), an edit the
    register's rules otherwise forbid. No code reads these paths, and the run of record's byte-identical replay
    compares other files. The archive keeps the original bytes. Left as they are: the Python installation's folder in
    error traces, and an example path pattern in the user's audit prompt.
- **Links to removed files.** Nothing in the tree links to the journal or the old README.
  `SPECS/ToDo/future_features.md` named `Strain_Head_Experiment.pdf` as the strain head's companion document; as the
  user decided, it now says that the companion document is kept privately. `SPECS/XON_BUILD_OVERVIEW.txt` now says
  that the `a1-run-of-record` tag is in the archived history. This changelog's and `decisions.md`'s records still
  mention the removed files.
- **The user's files.** The root commit holds the user's working-tree versions of the README (the new one),
  `SPECS/ToDo/XON_A1_REV2_2_PRECISION.md`, `SPECS/ToDo/future_features.md` and `SPECS/XON_BUILD_OVERVIEW.txt`, and the
  user's audit prompt, `SPECS/Audit_Prompts/AUDIT_PROMPT.md`.
- **`xonforge`** still starts from the archived history. It is not pushed, and it has to be moved onto the new root
  before it is merged or pushed: pushed as it is, it would publish the archived history, the journal included.

---

## 2026-09-25 — XonForge — the pipeline-test mode, through rendering, acceptance, export, sealing and the datasheet

The user's item 11 (`xonforge/docs/decisions.md`): every document made in the pipeline-test mode is labelled
`pipeline_test`, never enters a sealed or judged split, and is excluded from any corpus of record, and the datasheet
says so. Offline, with tests.

1. **The label.** `Document` and `ExportRecord` gain a required `mode`, `record` or `pipeline_test`. `render()` takes
   the run's mode, always named, and labels the document with it.
2. **Acceptance** takes the corpus's mode. It refuses a pipeline-test document for a corpus of record ("a
   pipeline-test document is excluded from any corpus of record"), and a record document for a pipeline test.
3. **Export and placement** take the corpus's mode, which every document must have. A pipeline test's documents are
   refused in the test and judged splits by `place`, `write_split`, `write_readme` and `destination`. A split's
   records are of one mode. A pipeline test's README opens with a notice that it is not a corpus of record.
4. **Sealing:** `write_manifest` refuses a folder with any document line not labelled `record`, whether it is a
   pipeline-test document, an unlabelled line or an unreadable one.
5. **The datasheet** takes the corpus's mode, refuses records of another mode, and refuses test or judged records and
   a manifest hash for a pipeline test. A pipeline test's datasheet opens with a "Pipeline test" section, says that
   its reviewers were only required to be other models, and says that it is not a corpus of record.
6. **Choices, mine:**
   - a pipeline test's development and calibration splits go under `data/xonforge/pipeline_test/<version>/`, apart
     from every corpus of record;
   - a pipeline test takes only its own documents, just as a corpus of record takes only its own.

---

## 2026-09-25 — XonForge — step 1: the pipeline-test sample's configuration

The user's item 11 and his choices for the 20-document sample (`xonforge/docs/decisions.md`). No call was made.

1. **Models and prices.** `xonforge/config/providers.yaml` gains `claude-opus` (`claude-opus-5-5`) and
   `claude-fable` (`claude-fable-5-1`), and `claude-sonnet` (`claude-sonnet-5`) is marked verified. Each source cites
   Anthropic's models overview, checked on 2026-09-25. In `xonforge/config/prices.yaml`, the Anthropic rows hold the
   checked prices, cache-read rates, the 5-minute cache write's rate (1.25x) and retirement dates, with their sources,
   and Haiku 4.5's row is kept though it is not used. These rows no longer say they need verification; the other
   providers' rows still do. A1's `xon/config.py` is unchanged.
2. **Cache rates.** `Price` gains `cache_read` and `cache_write`, as multiples of the input price (1 when not given),
   and `Usage` gains `cache_write_tokens`, which the Anthropic adapter fills. The caller charges cached tokens at
   their rates, and the call log records cache writes. The worst case held back before a call prices the input at the
   cache-write rate where that is above 1, so it stays an upper bound. XonForge asks for no caching.
3. **Modes** (`xonforge/modes.py`): `record` and `pipeline_test`, always named, with no default. Reviewer selection
   takes the mode. `record` keeps §7.3's rule that no reviewer is of the renderer's provider. `pipeline_test` accepts
   any provider, and needs reviewers whose models differ from the renderer's and from each other.
4. **Run configurations.** `defaults.yaml` gains `runs`, which `xonforge/runs.py` loads and checks before a run
   starts. The check covers verified model ids and prices, roles, availability (except in a dry run), k reviewers for
   each renderer in the run's mode, every cap set, and, in `record` mode, at least three configured providers.
   `Session(run_config=...)` takes the run's mode and caps or raises `RunRefused`, and
   `python -m xonforge run-check NAME` prints the check without making a call.
   - `sample`: `pipeline_test`; `claude-sonnet` renders, and `claude-opus` and `claude-fable` review. The caps are $20
     for the run and $20 for each entry. Its token caps were not given, so the check refuses it for now.
   - `first_corpus`: `record`, with item 11's initial caps of $250 for the run and $100 for each entry, and no models.
5. **Readings, mine, to be confirmed:**
   - the $20 per-provider cap applies to each registry entry, since the budget caps entries;
   - a configured provider is one with a verified model id and price that is available;
   - in `pipeline_test` the two reviewers must also differ from each other, not only from the renderer.

---

## 2026-09-25 — XonForge — step 1: PyYAML and cryptography declared under a `xonforge` extra

The user's item 21 (`xonforge/docs/decisions.md`). `pyproject.toml` gains one optional-dependency group,
`xonforge = ["PyYAML>=6.0.2", "cryptography>=46.0.5"]`, with a comment; A1's dependencies are unchanged, and nothing
was installed, both packages being installed already.

1. **Minimum versions:** the installed versions, since no lower version was tested with XonForge.
2. **Licenses,** read from the installed packages' metadata: PyYAML 6.0.2, MIT (its License field and classifier);
   cryptography 46.0.5, `Apache-2.0 OR BSD-3-Clause` (its License-Expression), whose dependencies are cffi 2.0.0 (MIT)
   and pycparser 3.0 (BSD-3-Clause). All four licenses are permissive and compatible with Apache 2.0, and Apache-2.0
   is one of cryptography's two options. The repository itself declares no license.

---

## 2026-09-25 — A1 rev. 2.2, development iteration 1: the new Fix E1, its tests and its budget estimate (no API calls)

Every rev. 2.2 number here is a rev. 2.2 development number on the seen L1 corpus, not a result of record. No API call
was made; the next step is gate D0 under iteration 1, on the user's go-ahead.

1. **What changed: the entity extraction of the revised §5.** Relation scoring, its prompt and its schema are
   unchanged, so iteration 1's relation requests are iteration 0's and are answered from the cache.
   - **Steps (§5.2).** An inventory call (`ENTITY_INVENTORY_SYSTEM_V2_2`: the entities, and the attributes with arity
     and order kind), then a relations call (`ENTITY_RELATIONS_SYSTEM_V2_2`: same/different relations, order and
     extreme statements, senses, unsupported order claims) whose message lists the inventory, then the coverage net
     with at most one follow-up call (`ENTITY_COVERAGE_SYSTEM_V2_2`). The relations and coverage prompts share one
     definition of the statements. Tags: `<document>-v22-entities-inventory`, `-entities-relations` and
     `-entities-coverage` (`claims.extract_entity_steps_v22`).
   - **Per-document schemas (§5.3, `schemas.document_schema`).** Every entity field of the relations call's schema
     admits only the inventory's entity ids, every attribute field only its attribute keys, and every claim id only
     the document's claim ids, as JSON-schema `enum` (one value is sent as `const`). The ids and keys are those the
     entity graph uses (`canonical_key`). An answer's ids are matched case-insensitively, since the documentation does
     not guarantee an enum's casing.
   - **The fallback.** If the API will not compile a schema (a 400, "Schema is too complex for compilation"), the call
     raises `LLMSchemaRejected`, and the rejection is cached and recorded like an answer, so a replay from the cache,
     from fixtures or from saved L1-var responses takes the same path without asking again. The call is then sent with
     the same schema and plain ids, tagged `-fallback`. The derivation drops any statement whose entity id or
     attribute key the inventory does not list and counts it in `invalid_ids`; `schema_fallback` lists the steps that
     fell back.
   - **The coverage net (§5.6).** After the relations call, a claim of any kind whose text holds a word or phrase of
     the lexicon (whole words, case-insensitive; `comparatives.lexicon_words_in`) is covered if it has an order,
     extreme or same/different statement or is listed as an unsupported order claim. If any is uncovered, one
     follow-up call lists only the uncovered claims, with the same inventory, and answers each with statements or a
     `none` entry with a one-sentence reason. Its statements for the listed claims are added; its senses come after
     the relations call's, so a repeated sense does not replace one. Nothing of the relations call's is removed or
     changed, and there is no second follow-up. The claims still uncovered are reported.
   - **Thinking (§5.7).** The three entity calls send `thinking: {"type": "adaptive"}` with no effort field, which is
     the default effort; the setting is part of the request, and so of its cache key. `max_tokens` is 16,000
     (`llm_max_tokens_entity_steps`) for thinking and output together. Claim extraction and relation scoring still
     disable thinking. `LLM_CAPABILITIES` records which models accept adaptive thinking; one that does not (Haiku 4.5)
     keeps its default.
   - **Restricted superlatives (§5.8).** An extreme statement has a `restriction`, copied verbatim. One that is not
     blank is not expanded, is listed under `restricted_extremes`, and does not make its entity another superlative's
     partner.
   - **The derivation** has one core and two readers: the entity steps' answers, and iteration 0's statements, which
     Step 0 and iteration 0's saved analyses still use. A test checks that both give the same graph from the same
     statements.
   - **Iteration 0's single entity call** (`ENTITY_SYSTEM_V2_2`, `extract_entity_statements_v22`) is removed; it is in
     the git history, and its outputs are saved. `config.REV22_ITERATION = 1` is written into every rev. 2.2 analysis
     and development row, and `run_rev22_dev.py` refuses another `--iteration`.
   - **Batches.** A document's batch plan holds its pair calls and its inventory call; the relations and coverage
     calls need the inventory's answer.
   - **Diagnostics (§8 items 8 and 11).** Each development row gains Step 0's class for each missed planted relation
     and the corrected matching rule's result (cycle variants, under both versions), the restricted superlatives, the
     coverage net, schema fallbacks, invalid ids, a skipped step, and each entity call's thinking and output tokens.
     The entity report adds the corrected rate, the misses by class and cycle type, restricted superlatives, the
     coverage net's counts, schema fallbacks, invalid ids and the thinking tokens per step; the cost report breaks the
     entity calls out by step.
2. **The agent's choices, for the user to review.**
   - The coverage call's schema admits only the listed claims' ids, where the spec says "the same per-document
     schema": the follow-up is about those claims only. Under the fallback, a statement for any other claim is not
     taken, and is counted in `invalid_ids`.
   - With no claims, or an inventory with no entity or no attribute, the relations and coverage calls are skipped: no
     statement could name a listed id. The lexicon's claims then stay uncovered, and `skipped` gives the reason.
   - Adaptive thinking is named in the request rather than left to the model's default (the same on Sonnet 5), so the
     setting is recorded in the request and cannot change with the default.
   - `max_tokens` 16,000: SDK 0.84.0 refuses a non-streaming call whose `max_tokens` implies more than ten minutes
     (above 21,333 here). Iteration 0's largest entity output was 1,515 tokens; LLM-direct's largest thinking on this
     corpus was 2,865.
   - The schema classes sent to the API have no docstrings, because Pydantic sends a class's docstring as the schema's
     `description`, which makes it part of the prompt. Three existing classes already do so. They are left as they
     are, because changing them changes their requests: `RelationV22` (every rev. 2.2 relation call), `SameDifferent`
     (iteration 0's entity call) and `Pair` (rev. 2.1's pair selection, in the run of record).
3. **Checked in the Claude documentation (2026-09-25).** Structured outputs work with thinking (the grammar applies to
   the answer, not to the thinking), and are incompatible only with citations and prefilling. Their limits are 20
   strict tools, 24 optional parameters and 16 union-type parameters per request; a schema too complex otherwise gets
   the 400 above (compilation times out at 180 seconds); no limit on an enum's size is documented. The generated
   schemas have 3 union-type parameters (the inventory's), 1 (relations) and 1 (coverage), and no optional parameter.
   Adaptive thinking is `{"type": "adaptive"}`, with the effort in `output_config.effort` (default high); `max_tokens`
   caps thinking and output together, and thinking tokens are billed as output tokens.
4. **Tests** (`tests/test_rev22.py`, with the fakes in `tests/llm_fakes.py`): the thinking setting of each call, and
   in the cache key; the per-document schema admitting only the inventory's ids and the document's claims (the
   listed claims for the coverage call), case-insensitively, with no description sent; the fallback counting invalid
   ids, and its rejection replayed from the cache, from fixtures and from saved L1-var responses; the coverage net
   (exactly one follow-up, listing only the uncovered claims, a quoted claim among them; none for covered claims;
   `none` answers recorded; a claim the follow-up leaves out stays uncovered; nothing removed or edited); the skipped
   steps; the derivation fixtures, with the restricted superlative ("Kira signed first of the judges." + "Otto signed
   first.": no contradiction, listed under `restricted_extremes`); the prompts' content; the two readers agreeing;
   the minimal engine's standard-library isolation with the steps' answers; the entity calls broken out by step. The
   full suite, slow tests included: 474 passed. Step 0's script still writes a report identical to the committed
   one.
5. **The budget estimate (§7.3)**: `scripts/estimate_rev22_budget.py`, rewritten for iteration 1 (iteration 0's is in
   the git history), with no API call; output `results/a1-rev22-estimate-iter1-20260925-195154.json`.
   - Method. All 23,754 planned relation requests are in the cache (0 missing), so D0 and the full pass score no pair
     anew. Input tokens: least squares on request characters over 24,218 structured requests rebuilt from the cache,
     each call type weighted equally (mean relative error 2% to 7% per type). The inventory request is exact; the
     relations and coverage requests are built from iteration 0's statements for the same document. Visible output:
     iteration 0's measured output per character of its statements. Thinking: rev. 2.1 LLM-direct's measured adaptive
     thinking on this corpus (221 calls: mean 263, 90th percentile 562, maximum 2,865 tokens per call), taken as three
     scenarios.
   - The coverage net applied to iteration 0's statements leaves 570 of 1,554 lexicon claims uncovered, with a
     follow-up in 171 of the 180 documents (all 12 of D0's): nearly every document would make the third call.
   - At the mean, the 90th percentile and the maximum thinking per call:
     - D0 (12 documents, 36 entity calls): 124,599, 135,359 and 218,267 tokens; $0.41, $0.52 and $1.35.
     - The full pass after D0 (168 documents, 495 calls): 1,718,242, 1,866,188 and 3,006,173 tokens; $5.84, $7.32 and
       $18.72; about 0.8, 1.1 and 3.3 hours, one document after another.
     - L1-var 2.2 (§8.1): 5,339,637, 5,371,917 and 5,620,641 tokens; $14.38, $14.70 and $17.19. Of this, its 4,404
       relation calls (the subset's measured usage, re-scores included, three times) are 4,965,840 tokens and $13.15,
       about 0.4 hours at 8 in flight.
     - All of iteration 1: 7,182,478, 7,373,464 and 8,845,081 tokens; $20.64, $22.55 and $37.26.
   - If every entity call used all 16,000 of its `max_tokens`, the full pass after D0 would be 9.34 million tokens.
   - A1 has spent 32,280,679 of its 45,000,000 tokens (`cache/llm/log.jsonl`), so 12,719,321 are left. Every scenario
     fits; the full pass at the maximum thinking is 3,224,440 tokens (the 4,000,000 limit is lifted). No stop.
   - **Prompt caching and the Batches API** (the user's question):
     - The per-pair relation calls: in D0 and the full pass they are answered from the cache, so neither saves
       anything. In L1-var 2.2 they are paid. Prompt caching does not apply: the prompt is about 420 tokens at the
       0.288 tokens per character that claim extraction's prose measures (the earlier estimate was 571), against the
       1,024-token minimum, and iteration 0's 20,596 relation calls wrote and read 0 cached tokens. A batch would save
       $6.57 of the $13.15.
     - The entity steps: prompt caching does not apply (system prompts of about 477, 682 and 838 tokens). A batch can
       hold only the inventory calls, since the others need its answer: about $0.87 saved at the mean in D0 and the
       full pass.
     - Calls are sent synchronously, as the user decided (`decisions.md`).
6. **Next.** Gate D0 under iteration 1, on the user's go-ahead. The spec stays in `SPECS/ToDo/`.

---

## 2026-09-25 — XonForge — the user's answers on v0's open questions, recorded before building

Ian's answers to the open questions of steps 3 to 6, which he confirmed as written, and two additions: item 11 on
providers, with a pipeline-test mode, and the pipeline-test sample's caps and models. `xonforge/docs/decisions.md`,
new, is the running record of the user's decisions on XonForge: it gives each decision in full, the readings applied,
what is still open, and Ian's text verbatim. This entry logs them; nothing is built yet.

1. **Re-specifications of the spec.**
   - §0 and §7.3 (reviewers are never from the renderer's provider): except in a new pipeline-test mode, chosen
     explicitly for a run and never as a fallback, in which the renderer and the reviewers may be different models of
     one provider. Its documents are labelled `pipeline_test`, never enter a sealed or judged split, and are excluded
     from any corpus of record; the datasheet says so. A corpus-of-record run refuses to start with fewer than three
     configured providers.
   - §5.4: explicitness in v0 is only stated or paraphrased; the schema of inferred facts (`mode`, `support_spans`,
     `derivation`) is defined now and generated from v1. The spacing constant is one sentence that is not planted;
     three difficulty levels bundle the knobs; the length tolerance is ±15% of the target, and at least ±25 words.
   - §14: `arity_control` moves from v1 (step 8) into v0. The other traps, and `coreference_trap`, stay in v1.
   - §7.3: 5 defect and 2 clean canaries per batch of at most 20 documents, more than the 10% minimum; recall is an
     exact fraction, and a batch is certifiable at ≥ 0.8. The prompts' folder is `xonforge/prompts/` rather than
     `docs/prompts/`, under step 1's layout.
2. **Superseded earlier decisions and readings.**
   - A1's scans were reused by import (the user's instruction for steps 3 to 6). They are now copied into
     `xonforge/verify/`, with their source recorded, and extended there (score, speed, club, department, table,
     cabin, "arrived later than"), each new pattern with its own scan canary; A1's copy stays unchanged.
   - Step 3 rendered each planted variant from its own skeleton and refused twins. The consistent twin is now rendered
     first, and the planted variant derived from its text by re-rendering only the changed sentences in place; twins
     record their counterpart facts as `twin_facts`, with spans.
   - The implementing agent's one canary string per corpus (step 6) becomes one per split.
   - Step 2's "built when the spec schedules traps" gives way to `arity_control` in v0.
   - The implementing agent's `xonforge/docs/prompts/` (step 5) becomes `xonforge/prompts/`, where the draft
     rendering prompt moves too.
   - The first answer's sample caps ($20 per run, $8 per provider) and "current mid-tier model" of three providers:
     only Anthropic is available for now, and the sample runs in the pipeline-test mode with the renderer
     `claude-sonnet-5` and the reviewers `claude-opus-5-5` and `claude-fable-5-1`, at $20 per run and $20 per
     provider.
3. **Confirmed readings.** A `LICENSE.txt` in each exported folder (step 6). The fail-closed rule for attributes that
   no scan pattern covers (step 6). The arity sentence's exemption from spacing and from the plant distance (step 4).
   Same-attribute distractors off at level 1 and on at levels 2 and 3 (step 2's default).
4. **New values.** The two review prompts' wording, their reply and the matching rule; the random 10% (ceil(0.10 × n),
   at least 1, and at least 2 in the sample); quotas over plant type × level × renderer provider, with genre and trap
   type per dimension; largest-remainder rounding with a logged tie seed; the unfillable rule (max(10, 3 × quota)
   attempts, reported, not redistributed); splits stratified by plant type × level, with a logged seed; CC BY 4.0,
   with the "not for training" notice as a request, and a logged check of each provider's terms before the first
   export; the leak test (a canary per split, whole-document hashes, and shared 8-word sequences after normalizing,
   over both worktrees on every test run, the commits being pushed and the full history); the first full corpus's
   initial caps ($250 per run, $100 per provider, after an estimate); PyYAML and cryptography under a `xonforge`
   extra.
5. **Model ids and prices,** verified in Anthropic's documentation on 2026-09-25 (the models overview and pricing
   pages): Claude Fable 5.1, `claude-fable-5-1`, $10/$50 per MTok, cache read 0.025×; Claude Opus 5.5,
   `claude-opus-5-5`, $4/$20, 0.05×; Claude Sonnet 5, `claude-sonnet-5`, $2/$10, 0.1×; Claude Haiku 4.5,
   `claude-haiku-4-5-20251001`, $1/$5, 0.1×, not used. Cache writes cost 1.25× (5 minutes) or 2× (1 hour) the input
   price; the Batch API is 50% off; `inference_geo: "us"` costs 1.1×. The three chosen models reject sampling
   parameters, think adaptively (only Sonnet 5 can turn it off), bill thinking tokens as output, and produce about 30%
   more tokens for the same text than models before Claude 4.7. The rates go into XonForge's own price table; A1's
   `xon/config.py` is not edited.
6. **Still open:** the 20-document sample's composition (what the documents are, whether a consistent twin counts as
   one, whether the sample is split and sealed, and whether the fact audit runs in it); the check of each provider's
   terms before the first export; the providers to add before the first corpus of record; and token caps for the
   sample, which XonForge's budget requires as well as the dollar caps. The sample waits for Ian's go-ahead after the
   cost estimate.

---

## 2026-09-25 — XonForge — correction: `client.py` moves onto `xon_common` after rev. 2.2's result of record

The XonForge step 1 entry ("re-specifications from the user's answers", item 1, on the `xonforge` branch) says that
`xon/llm/client.py` moves onto `xon_common`'s provider-neutral core "After `a1-rev2.2-frozen`". The user corrected this
on 2026-09-25: the move comes after rev. 2.2's result of record, because A1's client must stay unchanged through its
measurement. The rest of that item stands, including the regression test the move comes with (A1's request hashes and
the run of record's replay stay byte-identical). That entry is not edited; this one is on `main`, and reaches the
`xonforge` branch when it is merged.

---

## 2026-09-25 — A1 rev. 2.2, development iteration 1: the user's decisions, and Step 0 (no API calls)

Every rev. 2.2 number here is a rev. 2.2 development number on the seen L1 corpus, not a result of record.

1. **The user's decisions**, after the full pass's report (item 16 of the entry below):
   - Implement the revised spec: Step 0 first, with no API calls, and report it; then the new Fix E1, its tests and a
     new budget estimate, stopping before D0's calls.
   - Numbering: the original rev. 2.2 spec (`b31c680`), with gate D0 and the full pass under the earlier Fix E1, is
     the starting point, iteration 0. The spec revision (Step 0 and the new Fix E1) is iteration 1. The revision was
     motivated by the run of record's 0.900 order-relation accuracy; it was made before the full pass's results
     existed, and D0's numbers had been seen.
   - Step 0's report includes the full pass's remaining false positives, each with the verdict clause that fired,
     the claims and the rationale. If all come from the entity clause, the new Fix E1 targets them; if any comes from
     a relation clause, the user sees them before any further iteration.
   - The new budget estimate states whether the per-pair calls use prompt caching or the Batches API, and what each
     would save.
   - A register of the user's decisions, `decisions.md` (item 6).

   After Step 0's report (items 3 to 5):
   - Go on with iteration 1 as specified: the new Fix E1, its tests and the new budget estimate, stopping before D0's
     calls. The relation prompt is not revised now.
   - The Step 0 report lists the four relation-clause false positives with their claims, rationale and confidence.
   - The finished full pass stays iteration 0.
   - `client.py` moves onto `xon_common` after rev. 2.2's result of record (the entry above).
   - `decisions.md` is committed once the user's details and reasons are in it (item 6).
2. **Step 0: what was built.**
   - `xon/llm/order_misses.py`: Step 0's five classes, a miss going to the first that fits in the spec's order with
     scoring artifact first; whether a planted order cycle closes in the entity graph (one relation stated by a claim
     matched to each planted sentence, all on one attribute, chaining round the planted entities one way or the
     other) and whether it is the contradiction the engine reports; and a corrected matching rule. The class order
     and the mechanical tests (closure; an id mismatch as a planted name that is a whole word of the id or of a
     mention) are the agent's.
   - `results/a1-l1-order-misses.py` writes `results/a1-l1-order-misses.md`. It reads only the run of record's
     files, the corpus, and the full pass's files. It rebuilds each entity graph from the run's cached extraction as
     the engine built it, and checks the matching rule's flags against the run's own, and rev. 2.2's derived
     relations against the stored ones, before it reports.
   - Tests in `tests/test_rev22.py`: each class on a synthetic order cycle; closure needing one attribute and a
     chain; the reported-cycle check; and the script run in a subprocess under an audit hook, with no network access,
     no write but its output, no read inside the repository beyond `xon/`, the two runs' folders, the corpus, the
     script and the package metadata, and an output identical to the committed report.
   - The full suite, slow tests included: 465 passed.
3. **Step 0: the result.** The run of record's figures stay as reported.
   - 6 of the 60 planted order relations (cycle variants, seed 0) were counted as not extracted correctly, in 2 of
     the 20 order-cycle documents: all three planted relations of b00-cycle and of b36-cycle.
   - By class: scoring artifact 6, every other class 0. In both documents each planted relation ("Isla is older than
     Kai.") is extracted the other way round on `age` (greater(kai, isla)), so the extraction states the planted
     cycle's mirror image, which closes. The engine reported it on the planted claims and flagged both documents by
     the entity clause. The classes overlap here: each relation, taken alone, is also a direction flip against the
     extraction prompt's direction rule. The class order puts the six under scoring artifact; the user may reassign
     them.
   - In the run of record the planted order cycle closes in the entity graph in 20 of the 20 order-cycle documents,
     and it is the contradiction the engine reports in all 20. No missed link broke a planted cycle.
   - The matching rules: the run of record's gives 0.900 on order relations and 0.967 on all planted relations; the
     corrected rule, which also counts a relation stated the other way round when the planted cycle closes, gives
     1.000 and 1.000. Under rev. 2.2 (iteration 0) both rules give 1.000 and 1.000.
   - Under rev. 2.2 (iteration 0) the planted order cycle closes in 20 of 20, but the engine reports it in 18. In
     b21-cycle and b57-cycle it reports a two-relation cycle made by a superlative's derived edges and one planted
     link, on an attribute that mixes arrival with finishing order: "Sami arrived first." with "Nell finished ahead of
     Sami." on `arrival_order`, and "Esme trailed in last." with "Esme finished ahead of Otto." on `finish_order`.
     Both documents were detected anyway, and neither consistent variant was flagged.
4. **The full pass's four remaining false positives (iteration 0, τ = 0.5) all come from relation clauses**, so, as
   the user decided, nothing of iteration 1 is built before the user has seen them:
   - b32-consistent (the binary three-value control), direct: claim 4, "Hana came in shortly after Milo arrived.", and
     claim 10, "Milo and Hana were in different houses.", contradicts 0.70. Rev. 2.1 flagged it too (direct and
     claim balance).
   - b05-consistent (the binary three-value control), direct: claim 3, "Mina greeted Jude who came in shortly after
     her.", and claim 22, "Mina and Jude were in different houses.", contradicts 0.85.
   - b07-consistent (equality break base), direct and claim balance, both through claim 8, "Vik showed up a little
     later than the others.", and claim 11, "Milo strolled in last.", contradicts 0.72; the frustrated cycle adds
     claim 24, "Vik arrived after Bo but before Milo.".
   - b25-consistent (equality break base), direct: claim 0, "Milo was the first to walk in.", and claim 8, "Mina was
     already seated at the far table, sorting through glazes she had picked out the week before.", contradicts 0.62.
   - The agent's reading, a judgment made by reading each document as in the post-hoc analysis: none of the four is a
     contradiction in its document. In b05 and b32 the houses are the school's ("The school had three houses."), but
     a single-pair call shows the judge only the two statements, and it read them as buildings. In b07 the judge
     names the consistent reading ("others" not including Milo) and rejects it as "strained". In b25 the rationale
     itself says "This creates tension", while the label is contradicts.
   - The user has seen them, and keeps iteration 1 as specified, without revising the relation prompt now (item 1).
5. **The per-pair calls, prompt caching and the Batches API**, the user's question for the next budget estimate,
   answered from the full pass's call log:
   - They use neither. They were sent synchronously, as the user decided for this pass. Each carries a cache
     breakpoint, but the part of the request before it is under the 1,024-token minimum, so the API caches nothing:
     cache writes and reads were 0 on all 19,294 relation calls.
   - Measured: 19,294 calls, 19,906,229 input and 1,755,910 output tokens, $57.37 at $2 and $10 per million. Fitting
     each call's input tokens to its two statements' length (residual standard deviation 3 tokens) gives a fixed
     part of about 1,004 tokens per call, with the statements adding 28 on average. How much of the fixed part lies
     before the breakpoint cannot be read offline; the prompt text alone is about 571 tokens.
   - Batches (`--batch`, 50% of every price, results within 24 hours) would have saved about $28.70 of the $57.37.
   - Caching needs the part before the breakpoint to reach 1,024 tokens, so the relation prompt would have to grow.
     That is a prompt change: every relation request's hash changes, and this pass's cached responses would not be
     reused. With about 1,024 tokens then read at 0.1x per call, the saving would be about $35 if the whole fixed
     part already lies before the breakpoint (about 20 tokens to add), or about $18 if only the prompt text does
     (about 450 to add). Writes, at 1.25x, are rare while the cache stays warm. With batches as well (the discounts
     stack; cache hits inside a batch are best-effort), about $11 to $20 would be left.
   - Where it matters: iteration 1's development pass scores no pair anew while the relation prompt and schema are
     unchanged, since its relation requests are this pass's and are answered from the cache. L1-var 2.2 bypasses the
     cache: about 4,400 pair calls, about $13 at synchronous prices. The fresh-corpus run of record pays for every
     pair.
6. **`decisions.md`**, a register of the user's decisions at the repository root, in the format and under the rules
   the user gave, backfilled from the user's answers and the reasons the user gave for them; an entry whose reason
   was not given says so. The user saw the draft before it was committed, and this entry's work is committed with
   it. Recorded with it, the user's decisions on the repository:
   - **The history reset.** The repository's history was reset on 2026-09-25, to the snapshot commit "Snapshot:
     V1-V1.2 and A1 rev 2.1, after the L1 run of record", so that personal and internal documents (the project
     journal, the old README) never appear in the history before the repository is shared with researchers and
     grant reviewers. The old history, tags and hashes are archived privately as a zip outside the repository. The
     user left the date blank; the snapshot commit's date is used.
   - **`private/`.** First a gitignored folder at the repository root for personal and internal documents, never
     pushed and backed up separately with the XonForge private folders, which only the key-name test would skip
     while the sealed-text leak test still scanned it. The user then moved it out of the repository, to be
     maintained separately, to prevent leaks, and deleted `private/README_old.md`, which named A1's key variable
     three times and failed the key-name test. So no test changes: nothing under the root is private, and every
     repository-wide test scans all of it.
   - **The license.** The code is under the Apache License 2.0. The generated corpus's license is still open
     (likely CC BY 4.0, once each provider's terms are checked), and XonForge's export waits for it. The README
     links a `LICENSE` file, which does not exist yet.
   - **A second reset of the GitHub repository**, with no journal, no private documents and only the new README.
     The first reset's snapshot, on `origin/main`, still holds `PROJECT_JOURNAL_2026-09-23.md`, the old README and
     the six PDFs of `pdfs/`.
7. **Next.** Iteration 1: the new Fix E1, its tests and the new budget estimate, stopping before D0's calls. No API
   call has been made.

---

## 2026-09-25 — XonForge — step 6 (part): acceptance, sealing, encryption at rest, export, placement, datasheet

The parts of step 6 that no open question blocks. The choices are the implementing agent's, open to overrule; what
waits for the user is item 7.

1. **Acceptance** (`xonforge/corpus/acceptance.py`, §8): a document is accepted when the solver passes its skeleton;
   its stored rendering passes the structural checks and the scans, run again rather than read from its record; each
   applicable scan's clean result is trusted; it took no more attempts than the retry cap; and, if it was queued for
   human review, the latest human decision on it in the decision log is accept. A refusal lists its reasons. A base
   is accepted when every one of its variants is. A test checks, statically on every module acceptance reaches and at
   run time with an audit hook on file opens, that acceptance neither imports `xonforge/diagnostics/` nor opens
   anything there or in the diagnostic log (`diagnostics/engine.jsonl` under the cache directory's parent).
2. **Never accepted yet, with a reason that says it waits:** a consistent twin, whose checks need to know which of
   its facts count as planted; a trap-only variant (v1); a document rendered with no minimum spacing set; and a
   document one of whose scans has no pattern for one of its attributes.
3. **The manifest** (`xon_common/manifest.py` for its format and check, `seal.py` for making it): each file's
   SHA-256, the corpus's canary string, and a manifest hash over them. The check reports a changed, missing or unlisted
   file, and a manifest hash that does not match what the manifest lists. It needs nothing outside `xon_common`.
4. **Sealing** (`seal.py`, §9): the manifest goes into the sealed split's folder, which must be outside every worktree.
   `SEALED.md` gets a section per corpus version (manifest hash, date, file count, canary string) and refuses a
   version already sealed. The canary string, `XONFORGE-CANARY-` and a random UUID per corpus, is in every file of a
   split, the manifest included, and in its README.
5. **Encryption at rest** (`seal.py`): optional, as an encrypted copy of the sealed folder written beside it, never
   inside it. The key comes from the passphrase through scrypt (n = 2**15, r = 8, p = 1, a random salt per file), and
   the cipher is AES-256-GCM, from the `cryptography` package, which is installed but, like PyYAML, not declared in
   `pyproject.toml`. A wrong passphrase or an altered file is refused.
6. **Export, placement and the datasheet** (`export.py`, `datasheet.py`, §9, §12): a JSONL record per document with
   the fields §9 lists, and also the fact→span map, the scan results, the arity fact and the premise status; each
   split's skeletons in a file of their own; and in each folder a `README.md` and a `LICENSE.txt`, each with the "not
   for training" notice, the license and the canary string (§9's "in the export and README" is read as a license file
   in each exported folder). Placement takes each base's split, as the user's split method will give it, keeps a
   base's variants together, places only accepted documents, and writes the development and calibration splits to
   `data/xonforge/<version>/`, the test split to `XONFORGE_SEALED_DIR/<version>/` and the judged split to
   `XONFORGE_JUDGED_DIR/<version>/`. The datasheet is generated from the records, without any document text: §12's
   nine sections, with counts, renderers, reviewers, canary scores, human decisions, and as known issues the scans'
   missing patterns and untrusted clean results; the license reads as not chosen until it is. `docs/schema.md`
   describes the export.
7. **Waiting for the user:** the license, without which nothing is exported; the quotas (how the mix is divided into
   cells and rounded) and the scheduler that fills them; how bases are assigned to splits (the proportions, 50 / 15 /
   35, are given; the method and its rounding are not); the leak test's granularity and normalization; whether a
   scan's missing pattern blocks acceptance; the consistent twins' checks; and the judged split, which comes with v1's
   judged types.

---

## 2026-09-25 — XonForge — step 5 (part): reviewer selection, blind batches, canary scores, review queue, decision log

The parts of step 5 that no open question blocks. The choices are the implementing agent's, open to overrule; what
waits for the user is item 6.

1. **Reviewers** (`xonforge/review/reviewers.py`, §7.3): K per document (2, §7.3's default, set as `review.k`), from
   the registry entries with the review role that the user lists (`review.reviewers`, empty until then). The first K
   in the listed order whose provider is not the renderer's review the document. Entries reached through the generic
   OpenAI-compatible adapter count as one provider per address. The K reviewers may share a provider with each other.
2. **Blind requests** (`blind.py`): a reviewer receives the review prompt and one document's review id and text, in a
   request of its own, and nothing else. Review ids are opaque, a hash of a batch's secret salt and the item's id, so
   that they show neither which items are canaries, nor a document's variant, nor which documents share a base. A
   batch's order is shuffled with its seed. Its salt, seed and map back to documents and canaries are kept in a batch
   record under the cache directory's parent (`reviews/batches/<run>/`). Call-log tags name only the prompt and the
   review id. A test checks the serialized requests and the call log.
3. **Canary scores** (`calibration.py`): per reviewer and batch, the recall on the defect canaries and the false-alarm
   rate on the clean ones, as exact fractions, with the canaries missed and flagged. Review canaries are JSON files in
   `xonforge/canaries/review/` (an id, the kind, the text, and for a defect canary, the defect). None is registered.
4. **The queue** (`queue.py`, §7.4): every document with a rendering flag (every attempt used, or checks still
   failing), a scan's hits, or a reviewer's flag, with the reasons it is queued. It is kept under the cache
   directory's parent (`reviews/queue/<run>.json`), since flags can quote the document.
5. **The decision log** (`decisions.py`, §7.4): append-only and hash-chained, in `reviews/decisions.jsonl` under the
   cache directory's parent. Each entry holds the previous entry's hash, and its own hash covers every field, so
   altering, removing, inserting or reordering an entry breaks the chain, which `verify` reports with the line.
   Removing entries from the end shows only against a head hash kept elsewhere, which `verify` returns. An entry is
   either a decision (accept, regenerate or discard, with a reason and optionally the reviewer) or a run's sample
   seed, which is logged once per run and refused after any decision on the run.
6. **Waiting for the user:** the two review prompts, and with them the reply's schema and how a reported conflict is
   matched to the plant (for reviewer flags) or to a canary's defect (for the scores); the certification gate (what a
   batch is, and how the recall is rounded); the canaries, and how many of each kind a batch holds; how the random
   share of unflagged documents is drawn; and the reviewers themselves.

---

## 2026-09-25 — XonForge — step 4 (part): structural checks, measurements, A1's scans by import, canary trust

The parts of step 4 that no open question blocks. The choices are the implementing agent's, open to overrule; what
waits for the user is item 6.

1. **Structural checks** (`xonforge/verify/structural.py`, §7.1). With the scans they are the renderer's check, and
   their problems are quoted back to the next attempt (§6).
   - Spans: one per fact, found character for character in the text, found once, and each one whole sentence of its
     own. Sentences are split as A1's plant verification splits them, so that the checks and the scans agree.
   - What a span states: its fact's people, by name; its fact's value (a number as a word or in digits, and no other
     number beside a stated number of values); a negation exactly where a fact about a value has one, none in a
     comparison or a shared group, and a difference in a difference; and a comparison the right way round, where its
     wording is one the checks list. These run on every fact, distractors included, since a distractor stated wrongly
     can add a contradiction of its own. §7.1 names numbers only; the value, negation and direction checks are the
     agent's addition, since with paraphrase allowed a dropped "not" or a reversed comparison would take the plant
     out of a document labelled planted.
   - Forbidden content, on planted variants: no sentence but the plant's and the arity fact's names a planted entity
     together with the planted attribute's words (`vocabulary.py`: nouns, comparatives and superlatives; values only
     for clubs, the other values being everyday words such as red, sales, north or two).
   - No quotation marks (A1's set: straight and curly double quotes); 150 to 3,000 words (§5.4's range, with no
     tolerance around the document's target); the minimum spacing, refused while it is not set.
2. **The prompt** (`render-v0-draft-2`) gains two rules that match these checks, which A1 did not need with its
   word-for-word sentences: each fact's sentence names its people, and keeps the fact's sense. The restriction now
   forbids mentioning "any of" the plant's people with the attribute.
3. **Measurements** (§5.4), recorded on each document: words (whitespace-separated), sentences, the plant distance
   (the words between the first and the last planted sentence), and the fewest other sentences between two planted
   sentences. Planted sentences are the plant's facts' own; whether the arity sentence counts is part of the open
   question on spacing.
4. **Scans** (§7.2): A1's, imported from `xon/llm/corpus.py` and `xon/llm/corpus_qa.py` through
   `xonforge/verify/a1.py`, the one module of `xonforge/` that imports `xon` (a test holds it so). They are
   superlative collisions, order cycles outside the planted sentences, and same-attribute leaks; A1's scan reads three
   people, so for a larger plant it runs on every three of them. A1's activity-synonym scan has no counterpart in v0.
   What they cover of XonForge's attributes: superlatives and order cycles cover age, height and arrival, not score
   or speed; same-attribute leaks cover age, height, arrival and team, not score, speed, club, department, table or
   cabin; and the order-cycle scan reads A1's arrival wording ("arrived before", "arrived after") but not the
   prompt's ("arrived later than"). Each document records, per scan, the attributes it could not scan. The scans run
   once the planted sentences are whole sentences of the text, and their hits are quoted back like failed checks.
5. **Canary trust** (§7.2, §13): a scan's clean results are trusted once at least one canary is registered for it
   and it catches every one; a canary is a JSON file in `xonforge/canaries/scans/`. None is registered, so every
   scan's clean results are recorded as untrusted, while its hits still count.
6. **Waiting for the user:** the canaries; the minimum spacing, and whether the arity sentence is spaced like the
   plant's; whether the scans are copied over and extended to the attributes and wordings they miss; and whether a
   document must also fall within some range of its target length.

---

## 2026-09-25 — XonForge — step 3 (part): renderer core, draft prompt, retries, provenance, rotation, document store

The parts of step 3 that no open question blocks. The choices are the implementing agent's, open to overrule; what
waits for the user is item 7.

1. **What was built** (`xonforge/render/`): the renderer's reply schema (the text, and one span per fact); the rules a
   document is rendered by (target length of 150 to 3,000 words, explicitness, lexical variety, minimum spacing,
   retry cap); a draft prompt (`render-v0-draft-1`); the retry loop; provenance per document (registry entry,
   provider, model, parameters, reasoning, prompt version, and per attempt its request key and failed checks);
   renderer rotation; and a document store outside the repository. Nothing is rendered live: no renderer is chosen
   and no call is made, and the tests use fake clients.
2. **The draft prompt** follows A1's document prompt where A1 had a rule: one sentence per fact, the facts spread
   through the document, one assumption only, no quotation marks, no superlative shared by two people, no other
   statement on the facts' attributes, and the number of values only where a fact states it. Each fact is written in a
   sentence of its own and its span is that whole sentence, so that planted sentences are well defined for the
   spacing, the restriction and the scans. A premise about an entity is written as an assumption ("Assume that ..."),
   as A1 wrote its premise; a stated number of values is written as a plain statement, as A1 wrote its arity sentence.
   Facts that do not fit together are to be stated as listed, without correction or comment. The spacing and
   restriction instructions name the plant's facts and entities without calling them planted. The restriction also
   exempts the arity fact's sentence, which it would otherwise forbid; the spacing covers the plant's facts only,
   and whether it covers the arity sentence too is part of the open spacing question. The wording of the
   explicitness and lexical-variety instructions is the agent's.
3. **Retries.** Up to the retry cap (5, §5.4), each attempt a cached request of its own, so that a resumed run replays
   the same attempts from the cache. The failed checks are quoted back to the next attempt. A reply that is not a JSON
   object of the schema, is cut off or is declined counts as a failed attempt and is quoted back the same way;
   transport retries never count. A document that needed every attempt is flagged, and one whose last attempt still
   fails is kept with the status failed, for a human to regenerate or discard. A human reviewer's problems (§6's
   `review_problems`: a problem, and optionally its fact and sentence) and the earlier text can be passed for a
   targeted re-rendering.
4. **Rotation.** All variants of a base get the same renderer, so that a planted variant and its twin differ in their
   facts and not in who wrote them. Renderers are balanced: the one with the fewest bases so far, a tie going to the
   one listed first. Other mixes come with the quota scheduler.
5. **Where documents wait.** Under the cache directory's parent, in `documents/<run>/`, beside the other files that
   hold text (rules.md: generated documents stay outside the repository until the split assigns them). A store
   refuses a root inside any worktree of the repository.
6. **Settings** in `xonforge/config/defaults.yaml`, under `render`: the renderers (none; the user chooses them), the
   retry cap (5), the minimum spacing (not set), `max_tokens` of 16,384 per rendering, reasoning included (the
   agent's choice), and sampling parameters (none, so each provider's defaults).
7. **Refused until the user answers:** a consistent twin (which of its facts count as planted, and whether it is
   rendered on its own or derived from its planted variant by replacing one sentence, as A1 derived its variants); a
   document without a minimum spacing (§5.4's constant has no value); explicitness "inferred" (what the fact→span map
   holds for an inferred fact); trap-only variants (v1).

---

## 2026-09-25 — XonForge — step 2: binary parity, direct negation, the arity fact, premise status, same-attribute distractors

Step 2 finished as the user decided (the entry below). The choices here are the implementing agent's, open to
overrule.

1. **What was built.** The `binary_parity` and `direct_negation` generators, the solver's handling of a stated number
   of values, the skeleton fields `arity_fact` and `premise_status`, the same-attribute distractor setting, and the
   recorded twin seed. Step 2 is complete for v0's four plant types. The trap `arity_control` is not built: the spec
   schedules traps in v1 (§14, step 8), and whether it belongs in v0 is asked.
2. **Binary parity's plant.** A cycle of k relations (the cycle length), an odd number d of them "different", with d
   from 3 to k and the places of the "same" relations chosen by the seed; d is recorded in the plant's `differences`.
   d is at least 3 because a cycle with two "different" relations or fewer that cannot hold with two values cannot
   hold with any number of values either, so its contradiction would not need the arity fact. At k = 3 the plant is
   A ≠ B, B ≠ C, C ≠ A, as in A1.
3. **The arity fact.** It is a premise without a subject whose value is the number of values (2), on the planted
   attribute. The attribute's `arity` repeats it, at most one fact states it per attribute, and it is recorded apart
   from the plant's facts. The solver bounds the number of values only through such facts: the entities the facts
   name take at most k values between them, the named values among them. A negated value on an attribute whose number
   of values is stated is refused, since whether "A is not on the blue team" names one of the two teams is not
   decided; no v0 generator produces it.
4. **Direct negation.** The claim is a premise or a plain value fact about one entity. Its value is drawn by the seed
   from four names per categorical attribute (`xonforge/skeleton/catalog.py`, `VALUES`), and the twin's negation names
   another value from the same list, tried in the order the twin seed gives until the solver confirms that the twin's
   facts can all be true. The plant is always two facts, so the cycle-length knob does not apply and the difficulty
   records a cycle length of 2. By default the base has only the plant's one entity.
5. **The premise share.** `skeletons.negation_premise_share` in `xonforge/config/defaults.yaml` holds the user's
   default, 0.5. A caller can set a base's status; otherwise a draw from the base's seed makes the claim a premise
   with that probability, so a corpus's share is near 0.5 rather than exactly 0.5. An exact share would be a quota
   question for step 6.
6. **The twin seed.** It is the first 12 hexadecimal digits of the SHA-256 of `xonforge:<type>:<seed>:twin`, recorded
   in the plant's `twin_seed`; the twin's change uses only this seed, and a test reproduces each type's change from
   it. The premise draw uses the same derivation with `premise`. This changes the order-cycle and equality-break bases
   that the first step 2 commit produced for the same seeds; none was stored.
7. **Same-attribute distractors.** `Knobs.same_attribute_distractors`, off by default and recorded in the difficulty.
   When it is on, distractors may also relate entities outside the plant on the planted attribute. The hidden world
   they are drawn from never gives an attribute more values than its stated number, so they cannot form a parity
   contradiction, and the solver's check of each base confirms that they add no contradiction. The mapping to
   difficulty levels is asked, as §5.4's levels are still open.
8. **The CLI.** `python -m xonforge skeletons` builds all four types, gains `--same-attribute-distractors` and
   `--premise-share` (default: `defaults.yaml`), shows each base's arity fact and premise status, and reports an error
   in one type without stopping the others (exit status 2).
9. **Tests** (`tests/xonforge/test_xonforge_solver.py`, `test_xonforge_skeleton.py`): parity with and without the
   stated number of values, cycles of every parity, named values under a bound, conflicting bounds, the arity fact in
   the minimal contradiction, the refused negation, the schema's rules for the new fields; every base of all four
   types over seven knob settings (four for direct negation) and 40 seeds passing the solver, the twin seed
   reproducing each change, the premise share at 0, 0.5 and 1, and the distractor setting on and off.

---

## 2026-09-25 — XonForge — step 2: the user's decisions on binary parity, direct negation, twins and distractors

The user's answers to the questions of the entry below ("step 2 (part)"), recorded before they are implemented. They
supersede the choices that entry left open to overrule (its items 3, 5 and 7), and item 7 below settles the
calibration wording left open in the step 1 entry (its item 6).

1. **Binary parity's twin.** Two values are kept and one "different" becomes "same" (A ≠ B, B ≠ C, A = C). The
   three-value version stays the separate trap `arity_control`, reported separately, as in A1's corpus. It is built
   when the spec schedules traps; if it is unclear whether it belongs in v0, the implementing agent asks.
2. **The arity sentence.** The sentence that states the number of values is recorded separately, as A1 did, in its
   own field `arity_fact`, with its span. The solver treats it as required: the parity contradiction must exist with
   it and not without it. It appears in both the contradictory document and its consistent twin, and exports include
   it, so that scoring can report its recovery separately.
3. **Direct negation's twin.** The negation is replaced by one that holds, as a minimal edit: the same position,
   entity, attribute and sentence structure. Only the negated value changes, to a value that the solver confirms is
   compatible with everything else in the document.
4. **Negation as a premise.** The negated claim is a premise in a configurable share of documents (default 0.5),
   recorded per document, so that results can be reported for premise and non-premise cases separately. The
   consistent twin keeps its contradictory document's premise status.
5. **The earlier step 2 choices.** The twins are A1's matched controls, except binary parity's and direct negation's
   (items 1 and 3). The seed choosing which relation changes is confirmed, and that seed is logged. One planted
   variant per base is confirmed: one planted contradiction per document, so that localization stays unambiguous.
6. **Same-attribute distractors** become a difficulty setting instead of a fixed rule: distractors may use the planted
   attribute among entities outside the plant, and the solver confirms that they create and break no contradiction.
   The default is off at the lowest difficulty (as in L1) and on at higher levels. The mapping to levels waits for the
   difficulty levels of §5.4, which are still open; meanwhile the setting is built and the mapping is asked.
7. **Calibration.** Step 6 copies the calibration split (the spec's 15%) into `data/xonforge/` after the split assigns
   it, alongside the development split. The canaries themselves stay in `xonforge/canaries/`.
8. **Tests** stay in `tests/xonforge/`, as the user decided at the start.
9. **rules.md.** The user approved the XonForge section and added one line: generated documents stay outside the
   repository until the split assigns them, and only development and calibration documents are then copied into
   `data/xonforge/`. The section was committed on its own.

---

## 2026-09-25 — XonForge — step 2 (part): skeleton schema, solver, and the order-cycle and equality-break generators

Step 2 of `XONFORGE_SPEC.md` §14 ("skeleton schema and generators for the three L1 plant types plus
`direct_negation`; solver"), built as far as the user's answers allow. The implementing agent made the choices in
items 2 to 6; none sets a registered threshold, and the user may overrule each. The rest waits (item 7).

1. **Built.** The schema (§5.1, `xonforge/skeleton/schema.py`), the solver (§5.5, `xonforge/solver/`), seeded
   generators for `order_cycle` and `equality_break` (§5.2, `xonforge/skeleton/generators.py`), and
   `python -m xonforge skeletons`, which generates bases, checks each with the solver and writes nothing. No model is
   called.
2. **Two fields added to §5.1's fact.** `relation` (`greater`, `same` or `different`) names what a relation fact
   states, which §5.1 leaves implicit and without which "same team" and "different team" cannot be told apart; and
   `negated` marks a value fact stated as false, for `direct_negation`.
3. **Twins.** The order cycle's and the equality break's consistent twins are the matched consistent controls the
   user chose for A1's corpus (`XON_A1_CONSISTENCY.md` §5, rev. 2.1; the equality-break control as resolved in this
   file): one relation of the cycle reversed (A > B, B > C, A > C), and one "same" turned into "different" (A same as
   B, B different from C, A different from C). The seed chooses which relation changes; A1's examples always changed
   the same one. Each base has one planted variant (§5.1 allows one or more).
4. **Solver semantics.** Facts about different attributes never interact; each entity has one value of an attribute;
   with no stated number of values any number is possible, as A1 treats an unknown arity; a premise counts as a fact
   like any other. The solver refuses what v0 does not define rather than guessing: attributes with a stated number of
   values (item 7), events, facts with a time, other attribute kinds, and traps. It keeps a base only if the twin's
   facts can all be true and the plant is the planted variant's only minimal contradiction (§5.5): the plant's facts
   cannot all be true, and leaving out any one of them leaves facts that can.
5. **Facts around the plant.** The planted facts are the only facts about the planted attribute. Distractors are the
   relational filler facts of §5.4, about the other attributes and true of one hidden world; every entity outside the
   plant appears in at least one, and knobs that no world can satisfy are refused. Facts are shuffled before they are
   numbered.
6. **Knobs and genre.** A skeleton sets the knobs of §5.4 that belong to it, within the spec's ranges: cycle length
   (3 to 6), entities (3 to 12), attributes (2 to 8) and distractor density (0 to 3). Document length, plant distance,
   explicitness and lexical variety are left to rendering (step 3), where the open questions about spacing, distance
   bins, lexical-variety levels and "inferred" facts apply. The genre is required input with no default list; the
   Configure page of §10 sets the mix.
7. **Waiting for the user's answers.** For `binary_parity`: its consistent twin, and whether the sentence that states
   the number of values ("the game had two teams") is a planted fact, and so part of the minimal contradiction set.
   In A1's corpus the twin was the three-value control, and the generator recorded the arity sentence apart from the
   planted sentences; this spec lists the three-value version as the trap `arity_control` (§5.3). The solver's
   handling of a stated number of values waits with this answer. For `direct_negation`: its consistent twin (A1's
   consistent variant lacked the negation; a twin could instead replace it with a negation that holds), and whether
   the negated claim is sometimes a premise, as in half of A1's direct contradictions.

---

## 2026-09-25 — A1 rev. 2.2, the full development pass (iteration 0)

Every number here is a rev. 2.2 development number on the seen L1 corpus, not a result of record.

1. **Run.** `python -u scripts/run_rev22_dev.py --budget 35172458 --iteration 0 --out
   results/a1-rev22-full-20260925-124414`, recording off, the machine kept awake (set and cleared), started
   2026-09-25 12:44:14 (UTC−7). Console output in `results/a1-rev22-full-run.log`. Rev. 2.1's 180 documents and
   D0's 12 were answered from the cache (0 tokens).
2. **Interrupted by a network outage; not resumed.** From 20:05:03 UTC, calls of document 43 of 180
   (`b14-consistent`, tag `text-c4041fcdb110`) failed. The client logged 39 transport retries (32 connection errors,
   7 timeouts); 8 calls failed after their last retry, and the run stopped at 20:06:26 UTC with exit code 1:
   `anthropic.APIConnectionError`, caused by `getaddrinfo failed` (Errno 11001: the machine could not resolve the
   API's address). No failed call returned a response, was charged, or left a cache entry. Nothing was scored and
   no results folder was written.
3. **State at the stop.** Documents 1–42 are complete (D0's 12 from the cache, 30 new), and document 43's completed
   calls are cached. The pass so far: 3,137 API calls, 3,642,532 tokens (3,325,119 input, 317,413 output). A1 has
   spent 13,470,074 of the 45,000,000-token cap; 31,529,926 are left. At the rate so far (about 121,000 tokens per
   new document), the 138 remaining documents would take about 16.8M tokens.
4. **Checks (all passed).** No file under `xon/` or `scripts/` changed since the pass started (commit `a9d0ce2`);
   the call log parses (38,536 lines) and ends with a newline; the cache holds no `.tmp` file; the 8 failed
   requests left no cache file. When checked afterwards, the API's name resolved and a TCP connection to port 443
   succeeded.
5. **The user's decision: resume, with automatic reruns.** The L1 rerun rule covered L1's remaining documents only,
   so the user was asked. The answer: resume now with the same command and a recomputed budget; on a further
   connection drop, timeout or 5xx error, wait until the network is back, then rerun automatically, up to 5 times,
   logging each; stop on any other failure. `results/a1-rev22-launcher.py` applies it, adapted from the L1
   launcher: it keeps the machine awake, starts the same command (same `--out`, recording off) with `--budget`
   45,000,000 minus A1's spend, reruns only after `anthropic.APIConnectionError` (timeouts included) or a 5xx
   `APIStatusError`, and before each start waits until the API's name resolves and port 443 accepts a connection,
   for at most 60 minutes, stopping for a report after that. It appends to the same console log.
6. **Resumed** at 13:10:40 (UTC−7) through the launcher, with `--budget 31529926`. Documents 1–42 and document
   43's completed calls came from the cache.
7. **Stopped: the API account's credit ran out; not resumed.** From 20:50:46 UTC, calls of document 97 of 180
   (`b32-consistent`, tag `text-317113bb5957`) failed with `anthropic.BadRequestError` (400): "Your credit balance
   is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits." 22 calls
   failed this way, none charged or cached. The run exited with code 1 at 13:50:50 (UTC−7), and the launcher
   stopped for a report: the rerun rule does not cover a 400, and the client never retries one.
8. **State at the stop.** Documents 1–96 are complete, and document 97's completed calls are cached. The pass so
   far, both invocations: 9,866 API calls, 11,385,614 tokens (10,414,703 input, 970,911 output), about $30.05; with
   D0 ($3.84), rev. 2.2 has cost about $33.89. A1 has spent 21,213,156 of the 45,000,000-token cap; 23,786,844 are
   left. The 84 new documents done took 0.82 of their per-document estimates; at that ratio the 84 remaining take
   about 12.4M tokens (about $33), and L1-var 2.2 about 5.1M (about $13.50, from D0's measured usage per call).
9. **Checks (all passed).** No file under `xon/` or `scripts/` changed since the pass started; the call log parses
   (53,282 lines) and ends with a newline; the cache holds no `.tmp` file; the 22 failed requests left no cache
   file.
10. Resuming needs credit on the API account, which only the user can add, and the user's decision.
11. **The user's decision: resume and finish.** "added credits. go ahead and finish and then do the whole run."
    The pass is resumed through the same launcher, under the same rerun rule, with `--budget` 45,000,000 minus A1's
    spend; then L1-var 2.2 (§8.1) runs as planned in the budget entry, since its estimate (about 5.1M tokens) fits
    in what the cap leaves. The §6 threshold rule is still not applied: whether this pass is the final iteration is
    the user's decision after its diagnostics.
12. **Resumed at 16:30:09 (UTC−7) with `--budget 23786844`; refused again; holding.** Documents 1–96 came from the
    cache, and from 23:30:43 UTC the calls of document 97 failed with the same 400 ("Your credit balance is too
    low"): 27 calls, none charged or cached. The launcher stopped at 16:30:45 (UTC−7). The user then reported that
    the payment had failed, and asked to wait for their confirmation before resuming. The attempt added 14,724
    cache rows (0 tokens) and the 27 failed calls to the call log; A1's spend is unchanged at 21,213,156 tokens.
13. **The user confirmed the payment** ("okay, now payment is confirmed", 16:39 UTC−7). The pass is resumed through
    the launcher as in item 11, then L1-var 2.2.
14. **Finished.** Resumed at 16:39:51 (UTC−7) with `--budget 23786844`; documents 1–96 came from the cache, and all
    180 documents were complete at 17:40:02, exit code 0, with no failure. This invocation: 11,067,523 tokens, about
    $29.14. The full pass over its four invocations: 19,462 API calls, 22,453,137 tokens (20,545,144 input,
    1,907,993 output), about $59.20; 57 calls failed with no response and no charge (8 connection errors, 49 refused
    for credit), and 39 transport retries were logged. A1 has spent 32,280,679 of the 45,000,000-token cap;
    12,719,321 are left. Results in `results/a1-rev22-full-20260925-124414/`; no pair unscored (0 of 23,754).
15. **The §8 diagnostics** (`results.md` and `diagnostics.json` there), at τ = 0.5, since the §6 rule is not
    applied; rev. 2.1's values in parentheses:
    - Engine: direct and cycle P / R / F1 0.938 / 1.000 / 0.968 (0.845 / 1.000 / 0.916). False-positive rate on
      consistent documents 0.067, 4 of 60 (0.183, 11); on the binary three-value controls 0.100 (0.150). By cycle
      type, precision 1.000 on order cycles (0.833), 0.909 on equality breaks (0.833) and 0.909 on binary parity
      (0.870); recall 1.000 throughout. The minimal engine scores as the engine does and agrees with it on all 180
      documents (0.994).
    - Of rev. 2.1's 11 false positives, 10 are no longer flagged; b32-consistent still is (clause direct). New false
      positives: b05-consistent (direct), b07-consistent (direct and claim balance), b25-consistent (direct). No lost
      detection for the engine or the minimal engine.
    - Pairwise baseline: direct 0.938 / 1.000 / 0.968; cycle recall 0.100 (0.233): 11 cycle documents it flagged
      under rev. 2.1 are no longer flagged, as §11 expects, since contamination fell from 8 of 240 scored planted
      pairs (0.033) to 0.
    - Tension: 402 pairs, 140 in 45 of the 60 consistent documents, 129 in 48 direct and 133 in 47 cycle documents.
      All 60 planted pairs of the direct variants are labeled contradicts, none tension.
    - Clause attribution of the cycle detections: entity 54, direct and entity 5, direct, claim balance and entity 1.
    - Entity extraction: planted relations recovered 1.000 (0.967); 19 sense overrides; 348 superlatives giving 429
      derived edges; no superlative collision; 21 unsupported order claims.
    - L1b: AUC(1 − H) 0.975 (0.926), AUC(λ_min) 0.500 (0.528), premise in the top 3 1.000 (0.933).
    - Measured cost per document: the engine $0.424 ($0.138), pairwise $0.414 ($0.127).
16. **The spec was revised during the pass; L1-var not run.** `SPECS/ToDo/XON_A1_REV2_2_PRECISION.md` changed at
    16:53 (UTC−7), while the pass was running (the user's edit). The revision adds Step 0, a classification of the
    run of record's missed planted order relations with no API call, before Fix E1 is implemented. It redesigns Fix
    E1: three entity steps (an inventory call; a relations call whose per-document schema constrains entity ids,
    attribute keys and claim ids; a deterministic coverage net with at most one follow-up call), adaptive thinking
    on those calls, and restricted superlatives, which are not expanded. It also widens the budget estimate, the §8
    diagnostics, the §9 tests and the checklist, and adds §12 (out of scope). §3, §4 and §6 are unchanged apart
    from stating that relation scoring keeps thinking disabled, as it does. This pass implements the spec as of
    `b31c680`, so its entity numbers measure the earlier E1, while its relation calls stay valid under the
    revision. L1-var 2.2 would re-run the entity steps, so it is held until the user decides how to proceed.

---

## 2026-09-25 — XonForge — step 1: A1's anthropic-import test allows one more named file

`test_nothing_but_the_client_imports_anthropic` (`tests/test_llm_client.py`) required `xon/llm/client.py` to be the
only module outside `tests/` that imports `anthropic`. It now also allows exactly one more named file,
`xon_common/providers/anthropic.py`, XonForge's Anthropic provider module, and still fails for any other file. The
user decided this before step 1 (the entry below, item 9): XonForge's provider-neutral core needs its own Anthropic
module, and this change to an A1 test is logged on its own. The test's pattern and the files it scans are unchanged,
and so is A1's test of the key variable's name: the new module never names A1's key variable, and it passes the key,
base URL and authentication to the SDK explicitly, so that the SDK never reads A1's variables.

---

## 2026-09-25 — XonForge — step 1 (`XONFORGE_SPEC.md`): re-specifications from the user's answers

The user's answers to the step 0 questions, recorded before any step 1 code. Where they differ from the step 0 entry
below, they supersede it: in part its items 3 and 4, and the last sentence of its item 6.

1. **Provider-neutral core (§4).** `xon_common` gets its own provider-neutral cache, budget and call-log core. From
   `xon/llm/client.py` it imports only the hashing functions, `request_hash` and `request_key`, so request hashes are
   computed exactly as A1 computes them; it imports no other name from that module. After `a1-rev2.2-frozen`,
   `client.py` moves onto this core, with a regression test that A1's request hashes and the replay of the run of
   record stay byte-identical. That move is outside this work, and until it happens two cache-and-budget
   implementations exist. The user's reason: XonForge needs several providers from the start, because cross-model
   review is the point. Routing only Claude through A1's `LLM` until the freeze, or waiting for the freeze to make
   `client.py` pluggable, would block that, and copied overrides of `client.py`'s code would drift. XonForge keeps
   its own model and price registry. This replaces step 0 item 3's reuse of `client.py`'s cache and budget logic.
2. **Transport retries as in A1, a deviation from §4.2 (the user's decision).** §4.2 retries rate-limit and overload
   errors only. XonForge also retries the other 5xx errors, timeouts and lost connections, as A1 does, waiting at
   least as long as the server's `retry-after`. The policy is implemented in `xon_common` for every provider, not
   imported from `client.py`. Its values are in `xonforge/config/defaults.yaml` and match A1's `llm_retries` and
   `llm_backoff_s`: 3 retries, the first after 2.0 s, the wait doubling each time. A transport retry resends the
   identical request and never counts toward the 5-retry cap on rendering attempts (§6). Content retries, which
   quote a failed check back to the model, stay as the spec defines them.
3. **Response cache outside the repository.** The response cache is in the directory named by `XONFORGE_CACHE_DIR`,
   never under the root of any worktree of this repository, because cached responses hold prompt and response text,
   including the rendered documents of every split. The code refuses a cache location that is unset or inside a
   worktree; tests and dry runs use temporary directories outside the repository. For the cache, this replaces step
   0 item 4's `cache/xonforge/`.
4. **Spend and call log in the repository.** Only the spend and call log stays in the repository, at
   `cache/xonforge/log.jsonl`, because like A1's `cache/llm/log.jsonl` it holds no prompt or response text. A test
   checks this. XonForge never writes to `cache/llm/`.
5. **Other locations outside the repository**, never under the root of any worktree: the sealed test split
   (`XONFORGE_SEALED_DIR`); the judged split (`XONFORGE_JUDGED_DIR`); and, under the parent of the cache directory,
   every review, decision or diagnostic log that contains prompt, response or document text, and every review-queue
   item or reviewer output for a sealed or judged document. The judged split is evaluation data, because results on
   it are reported, so as for the sealed split only its hash manifest and datasheet are committed. The code refuses
   these locations when they are unset or inside a worktree. The repository holds only text-free summaries,
   datasheets and hash manifests, the splits of item 6, and XonForge's own files inside `xonforge/`.
6. **Splits in the repository.** Only the development split and calibration material are stored in the repository,
   under `data/xonforge/`. Every generated document stays outside it until the split assigns the document. Whether
   the calibration material means the calibration documents or the calibration canaries is being confirmed with the
   user, and the copy into the repository (step 6) waits for that. This replaces step 0 item 6's "development and
   review splits".
7. **Manifests.** The manifest format and a function that verifies a corpus against its manifest are in
   `xon_common`; creating manifests is part of the sealing workflow in `xonforge/corpus`. A1's future result of
   record and the repository's leak test must verify a corpus without importing `xonforge`, so the leak test imports
   only `xon_common`. The leak test is built with the sealing code (step 6). How it detects excerpts, which needs a
   minimum length and a text normalization, is put to the user then.
8. **Engine plugin.** `xonforge/diagnostics/engine_plugin.py` is the one module allowed to import the consistency
   engine. It refuses any path under `XONFORGE_SEALED_DIR` or the judged split's location, with a test, so that the
   engine never screens its own test corpus. It stays an inert stub until `a1-rev2.2-frozen`.
9. **Keys.** Each `XONFORGE_*_KEY` is read only in its provider module and never appears in logs, caches or the UI.
   The Anthropic SDK never falls back to A1's environment variables: the key, base URL and authentication are passed
   explicitly, and an empty key is never passed. A1's test that only `xon/llm/client.py` imports `anthropic` gets
   exactly one more named file, with its own entry.
10. **pytest's path.** `pyproject.toml` gets `pythonpath = ["."]` under `[tool.pytest.ini_options]`. An editable
    install of `xon-sim` maps `xon` to the folder it was installed from, so without this line a plain `pytest` in a
    worktree would test another folder's `xon/`, and `tests/xonforge/` would stand in for the `xonforge` package. In
    the XON folder it changes nothing.
11. **Layout.** XonForge's non-code files live inside the package, in `xonforge/config/`, `xonforge/canaries/`,
    `xonforge/prompts/`, `xonforge/docs/` and `xonforge/README.md`, instead of the spec's top-level folders (§3), so
    that XonForge can later be split out by moving one folder.

---

## 2026-09-25 — A1 rev. 2.2, gate D0 (the 12-document subset): run, and passes the condition set before it

Every number here is a rev. 2.2 development number on the seen L1 corpus, not a result of record.

1. **Run.** `python -u scripts/run_rev22_dev.py --subset --budget 2400000 --out
   results/a1-rev22-d0-20260925-123136`, recording off, the machine kept awake (set and cleared). Calls from
   19:31:40 to 19:39:52 UTC; exit code 0 after 499 s. Output in `results/a1-rev22-d0-20260925-123136/`, console
   output in `results/a1-rev22-d0-run.log`.
2. **Calls and cost.** 1,500 rev. 2.2 calls: 1,257 API calls (1,245 relation calls, 12 entity calls) and 243
   answered from the cache: 12 claim extractions and 8 pair selections from the run of record, and 223 single-pair
   requests identical to one already made in D0 (the variants of a base share most statements, and the judge sees
   only the pair). 1,457,957 tokens (1,335,180 input, 122,777 output), about $3.84: 0.76 of the estimate (1,919,076).
   No transport retry. The entity system prompt is above the cacheable minimum, so the API cached it: written once
   (3,270 tokens) and read 11 times (35,970 tokens), both counted in the input tokens. The rev. 2.1 replay added 135
   cache rows to the call log. A1 has now spent 9,827,542 of the 45,000,000-token cap; 35,172,458 are left.
3. **The §8 diagnostics for the 12 documents** (four each of consistent, direct and cycle variants):
   - Methods at τ = 0.5 score as under rev. 2.1 on these documents. The engine and the minimal engine: direct and
     cycle P / R / F1 1.000, no false positive, none on the binary controls. Pairwise: direct 1.000, cycle 0.000 (it
     cannot see cycles). Rev. 2.1 had no false positive among these 12 documents, so D0 cannot show whether the fixes
     remove false positives: all 11 of rev. 2.1's are among the other 168.
   - No new false positive and no lost detection, for any of the three methods.
   - Unscored: 0 of 1,468 requested pairs; no re-score; no answer for another pair.
   - Tension: 26 pairs, 6 in 2 of the 4 consistent documents, 10 in 3 of the 4 direct ones and 10 in all 4 cycle
     ones. The 4 planted pairs of the direct variants are all labeled contradicts, none tension.
   - Contamination: 0 of 15 scored planted pairs (rev. 2.1: 0). Clause attribution: the entity clause for all 4
     cycle detections, under both versions.
   - Entity extraction: planted relations recovered 1.000 (rev. 2.1: 0.750); 15 superlatives, giving 27 derived
     edges; no superlative collision, sense override or unsupported order claim.
   - L1b as under rev. 2.1: AUC(1 − H) 1.000, AUC(λ_min) 0.500, premise in the top 3 1.000. The minimal engine agrees
     with the full engine on all 12.
   - Measured cost per document: the engine $0.397 (rev. 2.1: $0.130), pairwise $0.387 ($0.121).
4. **The pass condition** (previous entry): all four parts hold.
   1. D0 completed with no pair unscored, and rev. 2.1 recomputed from the cache agrees with the run of record.
   2. Replaying D0 from the cache with no key and `XON_LLM_RECORD=1` wrote 1,500 rev. 2.2 fixtures
      (`tests/fixtures/llm/*-v22-*.json`), changed no rev. 2.1 fixture, and added 1,635 cache rows (0 tokens) to the
      call log. A dry-run replay from a working directory without the cache answered all 1,500 rev. 2.2 calls from
      the fixtures (none stale, no API call) and gave the same rows, diagnostics and analyses except their cost and
      usage fields, which a fixture replay reports as zero: the cost measure counts the calls answered by the API or
      the cache (decision 16 of the implementation entry). Nothing the analysis says differs.
   3. D0 used 0.76 of its estimate, so the full pass's other 168 documents scale to 21,999,347 tokens, within the
      35,172,458 left.
   4. No lost detection and no new false positive for the engine, the minimal engine or the pairwise baseline.
5. **Next:** the full pass, iteration 0, with `--budget 35172458`, recording off. D0's 12 documents are answered from
   the cache.

---

## 2026-09-25 — XonForge — step 0 (`XONFORGE_SPEC.md`): re-specifications made before any code

The spec (`SPECS/ToDo/XONFORGE_SPEC.md`) assumes a standalone `xonforge` repository, with `xon-common` developed under
`packages/xon-common/` and its own `CHANGELOG.md` (the header, §3 and §12). The user decided instead that XonForge
lives in this repository, laid out as below; where the spec differs, these decisions supersede it. They were made
before any XonForge code, data or call.

1. **Location.** XonForge is its own top-level package, `xonforge/`, with its tests in `tests/xonforge/` and its own
   CLI (`python -m xonforge`) and dashboard entry points.
2. **Branch and worktree.** All XonForge work is on the branch `xonforge`, created from `main` at `7a63cfd` and
   checked out as a git worktree at `%USERPROFILE%\Desktop\XON-xonforge`. The worktree is outside the XON folder
   because XON's repository-wide tests scan every file under the root.
3. **Shared module.** The spec's `xon-common` (providers, cache, budgets, hashing) is a shared module in this
   repository, the top-level package `xon_common/`, for use by both `xon/` and `xonforge/`. It reuses
   `xon/llm/client.py`'s cache and budget logic by importing it, extended for the other providers, instead of
   duplicating it. Until the tag `a1-rev2.2-frozen` exists, no file under `xon/` is edited; if the reuse cannot work
   without copying code, the implementing agent stops and asks.
4. **Own cache and log.** XonForge writes its cache and run log under its own directory, `cache/xonforge/`, never to
   `cache/llm/`: rev. 2.2's budget stop computes A1's remaining spend from `cache/llm/log.jsonl`.
5. **Import boundary.** `xonforge/` never imports the consistency engine (`xon/llm/consistency.py`,
   `entity_consistency.py`, `minimal.py`, `engine.py`), directly or transitively, except through the isolated
   diagnostic of §7.5. A test enforces this for `xonforge/` and `xon_common/`, with a static scan and a run-time
   check. The diagnostic stays an inert stub until `a1-rev2.2-frozen`.
6. **Sealed splits.** Sealed test splits are written only outside the repository, to the directory named by the
   environment variable `XONFORGE_SEALED_DIR`, and never under the root of any worktree of this repository. Only
   their hash manifests and datasheets are committed. Development and review splits may live in the repository,
   under `data/xonforge/`.
7. **Keys.** XonForge reads provider keys only from its own environment variables, one per provider
   (`XONFORGE_ANTHROPIC_KEY`, `XONFORGE_OPENAI_KEY`, `XONFORGE_GEMINI_KEY` and so on), instead of the `key_env` names
   in §4.1. A1's rules apply: environment only, never in the UI, on disk or in logs. XonForge never uses A1's key
   variable, and no XonForge file names it (A1's repository-wide test allows the name only in `xon/llm/client.py`
   and the README).
8. **Changelog.** XonForge logs in this file, not in a `CHANGELOG.md`, on the `xonforge` branch, under headings of
   the form `## <date> — XonForge — ...`.
9. **Spec.** The spec stays in `SPECS/ToDo/XONFORGE_SPEC.md` and is not copied; git history records its versions.
10. **Merges.** `xonforge` is merged into `main` only at milestones (v0 core, the 20-document sample stop, v1) and
    only when the user says so. The implementing agent never merges.

---

## 2026-09-25 — A1 rev. 2.2: the user's budget decision, and how gate D0 and the full pass are run (before any call)

1. **The user's decision**, after the estimate in the next entry:
   - A1's token cap goes from 15,000,000 to 45,000,000 tokens (input plus output, summed from the call log, as
     before). The option put to the user said "about 45M"; the cap is taken as 45,000,000 exactly.
   - §7.2's limit of 4,000,000 tokens for the full pass is lifted.
   - Calls are sent synchronously, at full price, not as a Message Batch.
   - Gate D0 runs first, and the full pass follows without another stop if D0 passes: the go-ahead of §10 item 4 is
     given in advance, on that condition. This departs from §7.3, which stops after D0.
   - The implementation commit (`b31c680`) is not pushed yet.
2. **What "D0 passes" means**, fixed here before D0 runs. The spec sets no pass or fail on the development set
   (§8), so this is a condition for spending more, not a result. D0 passes if all four hold; otherwise the stage
   stops and D0 is reported.
   1. D0 runs to completion: no error, no budget stop, at most 1% of the requested pairs unscored (so no
      `--accept-unscored`), and rev. 2.1 recomputed from the cache agrees with the run of record (the script checks
      this).
   2. D0's rev. 2.2 fixtures are recorded; D0 replays from them in dry-run mode, with no API call, to the same rows;
      and no rev. 2.1 fixture changes.
   3. Its cost is in line with the estimate: the estimate for the full pass's other 168 documents (28,957,246
      tokens), scaled by D0's measured-to-estimated token ratio, fits in what is left of the 45,000,000 cap after D0.
   4. No sign that the fixes broke detection: on the 12 documents at τ = 0.5 (rev. 2.2's threshold until the §6
      rule is applied), none of the engine, the minimal engine and the pairwise baseline has a lost detection (§8
      item 4) or a new false positive (§8 item 3).
3. **How the runs are made.**
   - D0: `python -u scripts/run_rev22_dev.py --subset --budget 2400000` (1.25 times D0's estimate), with recording
     off, so that a fixture error cannot stop a paid run. The fixtures are then recorded by replaying D0 from the
     cache with no key and `XON_LLM_RECORD=1`, where no API call is possible, and the dry-run replay is checked from
     a working directory without the cache.
   - The full pass: `python -u scripts/run_rev22_dev.py --budget <45,000,000 minus A1's spend> --iteration 0`,
     recording off. No `--final`: whether this pass is the final iteration is the user's decision after its
     diagnostics, and the §6 rule can then be applied to the cached pass with no call.
   - L1-var 2.2 (§8.1) runs after the full pass only if its estimate (5,757,228 tokens), scaled the same way, fits in
     what is left of the cap; otherwise the stage stops and asks. At the estimates it does not quite fit: 8,369,585
     spent + 30,876,322 + 5,757,228 = 45,003,135 tokens.
   - The machine is kept awake during each paid run with `SetThreadExecutionState`, cleared when the run ends, as
     for L1-var; no power setting is changed.
   - No prompt, threshold or code change once D0 starts; if anything breaks, the stage stops and reports.

---

## 2026-09-25 — A1 rev. 2.2 (`XON_A1_REV2_2_PRECISION.md`): implemented and tested offline; stopped at the budget estimate, before any call

Nothing in this entry changes the L1 run of record or its numbers. No rev. 2.2 call has been made: the spec's budget
rule (§7.2) stops the stage before gate D0 (item 4). Every rev. 2.2 number, when there are any, is labeled "rev. 2.2
development pass on the seen L1 corpus; not a result of record."

1. **What is implemented.** Code in `xon/llm/` (new: `comparatives.py`, `devpass.py`), `scripts/run_rev22_dev.py`,
   `scripts/estimate_rev22_budget.py` and the app's Consistency mode; tests in `tests/test_rev22.py`.
   - **Versioning (§2).** `engine_version` ("2.1" or "2.2") is in the config, the consistency report, the exported
     analysis, both scripts' `run.json` and every rev. 2.2 output. Rev. 2.1's prompts, schemas, batching and verdict
     logic are unchanged under their names. The Consistency view has an engine selector in the sidebar (default
     2.2), shows a report side by side with another, with a table of the pairs whose labels differ, and colors
     tension pairs amber in the relations table. The minimal engine follows the version and the threshold.
   - **Fix R1 (§3).** `RelationV22` with `tension`; `RELATE_SYSTEM_V2_2` with the four definitions and the
     ordinary-reading rule. Tension makes no edge, is listed in the report's `tension_pairs`, and is ignored by the
     pairwise baseline and the minimal engine.
   - **Fix R2 (§4).** One pair per call (`RELATE_SINGLE_USER_V2_2`: the pair's two statements and ids, nothing
     else). The malformed-output rule per pair: one re-score, then unscored. Transport retries are logged apart. The
     1% stop rule is in the development-pass script (exit code 3 before scoring; `--accept-unscored`). Calls run
     concurrently with a limit, and there are prompt-cache breakpoints and a Message Batches runner (decision 9).
   - **Fix E1 (§5).** `EntityGraphSpecV22` (attributes with `order_kind`, same/different relations, order and extreme
     statements, senses, `unsupported_order_claims`), `ENTITY_SYSTEM_V2_2`, the lexicon (the §5.3 table verbatim,
     standard library only) and the §5.4 derivation: edges from extremes marked `derived_from_extreme`, none to the
     entity's own equality class, and `superlative_collision` for two entities that are both first or both last.
     Diagnostics: `sense_overrides`, `unresolved`, `superlatives`, `unsupported_order_claims`.
   - **Threshold rule (§6).** `devpass.threshold_rule` on a pass's rows: τ from 0.50 to 0.90 in steps of 0.05, per
     method, the largest mean of direct and cycle F1, ties to the lowest τ. `RELATION_THRESHOLD_V2_2` in
     `xon/config.py` holds None per method until the rule is applied, on the final iteration's full pass only
     (`--final`, refused with `--subset`); until then rev. 2.2 uses 0.5. Rev. 2.1's curves come from the run of
     record's cache, report-only.
   - **Development pass (§7, §8, §8.1).** `scripts/run_rev22_dev.py`: gate D0 with `--subset`, the full pass,
     `--iteration`, `--final`, `--batch`, `--l1var`. Claims and pair selections come from the run of record's cache.
     Rev. 2.1's rows are recomputed from the cache with a budget of 0 and checked against the run of record's
     verdicts. LLM-direct is carried from the run of record's rows and marked as carried. A document's row holds each
     thresholded method's verdict at every τ of the grid, so the rule and every §8 diagnostic are computed from rows,
     with no call. L1-var 2.2 saves its raw responses (not fixtures) and can be recomputed from them.
2. **Decisions and deviations** (made while implementing, before any call).
   1. **Engine default.** The library's default stays 2.1 (`XonConfig.llm_engine_version`), so rev. 2.1's scripts,
      replays and tests run unchanged; `evaluation.run_document` pins 2.1. The Consistency view defaults to 2.2, as
      §2 asks.
   2. **Fixture tags.** Rev. 2.2's calls are tagged `<tag>-v22-...`: one relation call per pair
      (`-v22-relate-AAA-BBB`; re-scores `-v22-relate-rescore-AAA-BBB`; world knowledge `-v22-relate-wk-...`), the
      entity call (`-v22-entities`), L1-var (`-v22-varK-...`). The claim-extraction and pair-selection requests are
      byte-identical to rev. 2.1's, so they are answered from the run of record's cache; recorded, they are written
      under `-v22-` tags, so rev. 2.1's fixtures are untouched. The blind-sample seed still comes from the rev. 2.1
      tag, so both versions score the same pairs.
   3. **Worked examples replaced.** The spec's examples ("The road was icy." / "The courier arrived early."; "The
      shop was closed all day Sunday." / "Ada bought bread at the shop on Sunday.") share content words with the L1
      corpus: arrived, early, road; bread, closed, day, shop. "Arrived" is the verb of the planted arrival-order
      sentences, and "shop" is in a binary-parity arity sentence. The prompt uses "The freezer was unplugged." / "The
      ice cream in the freezer was frozen solid." (tension) and "The museum was shut all Sunday." / "Ada bought a
      ticket at the museum on Sunday." (contradicts). They share only function words (a, all, at, in, on, the, was)
      with the corpus and no name or topic word; a test checks this.
   4. **Rev. 2.1's wording kept, one sentence dropped.** `RELATE_SYSTEM_V2_2` keeps rev. 2.1's framing ("assume that
      claim A is true ..."), its world-knowledge switch verbatim, and its return instructions, for one pair. The
      sentence "Judge each pair using only its two statements, ignoring every other statement in the list, even if
      they seem relevant." is dropped: there is no list. The rationale is "one or two sentences" (the spec's
      schema), not rev. 2.1's "one sentence".
   5. **Lexicon matching.** "Whole words after trimming" is a whole-phrase match after lower-casing, collapsing
      spaces and removing surrounding punctuation, a leading "the" and a trailing "than": "older than" is "older",
      "the first" is "first". A phrase with any other word ("no later than", "not older", "followed by") is not
      covered and keeps the model's sense.
   6. **Passive voice.** The table's "followed" (the subject is later) would misread "Kira was followed by Otto".
      `ENTITY_SYSTEM_V2_2` asks for the comparative with the "by" of a passive ("followed by"), which the lexicon
      does not cover, so the model's sense decides it. The table is not extended.
   7. **Same/different schema.** `same_different` has its own schema, `SameDifferent`, whose kind is "same" or
      "different" only. The spec reuses `EntityRelation`, whose kind also allows "greater". Same semantics.
   8. **Re-score cache keys.** A re-score sends the same request as the first attempt. Its cache key is the hash of
      {attempt: 2, request}, and its cached record holds `attempt` and `sent` (the request's hash), so each attempt
      has its own answer and L1-var's saved responses replay in order. First attempts keep the plain request hash.
   9. **Prompt caching and batches** (Claude docs, 2026-09-25; the installed SDK, 0.84.0, supports both). The
      relation and entity system prompts carry an ephemeral cache breakpoint, which is part of the request key. The
      rev. 2.2 relation system prompt is about 571 tokens, below the 1,024-token minimum on Sonnet models, so the
      API caches nothing for relation calls (silently); the prompt was not padded to reach the minimum.
      `client.BatchRunner` sends a pass's first attempts as one Message Batch at 50% of every price (`--batch`),
      caches each result under the key the synchronous request has, leaves failed results to the synchronous calls,
      keeps only keys, tags and the batch id on disk, and resumes an interrupted wait. The cost model counts cache
      writes (1.25x), cache reads (0.1x) and batch prices.
   10. **Concurrency within the budget.** Relation calls run on a thread pool (`llm_concurrency`, default 8). Each
       call in flight reserves its worst case (estimated input plus `max_tokens`, which is 1,024 for one pair), and a
       batch reserves its total before it is sent, so concurrency cannot take a session past its budget.
   11. **Transport retries widened.** Rev. 2.1 retried 429 and 529 only. The client now also retries any other 5xx
       and the SDK's connection errors (its timeout included), waits at least the server's `retry-after`, logs each
       retry on its own row (source "retry") and counts them in `usage["transport_retries"]`. A 400 is never
       retried. This applies to rev. 2.1's calls as well; it changes no request, so no hash and no replay.
   12. **`relations_ignored` under rev. 2.2** counts answers for another pair than the one asked about; each such
       answer is re-scored once.
   13. **Where the version is recorded.** `engine_version` and the threshold are in the report, the exported
       analysis, both `run.json` files, the first line of rev. 2.1's `results.md` and every rev. 2.2 file. They are
       not added to rev. 2.1's `documents.jsonl` rows, its minimal-engine block, `l1.json` or `l1b.json`, which must
       stay byte-identical (§2). Rev. 2.1 analysis exports written from now on also hold `engine_version`,
       `threshold` and an empty `tension_pairs`.
   14. **Minimal-engine isolation.** `build_entity_graph_v22` imports the lexicon inside the function, so the minimal
       engine under rev. 2.1 loads exactly the modules its unchanged isolation test lists. A second isolation test
       covers rev. 2.2: it adds `xon.llm.comparatives` and nothing outside the standard library.
   15. **Config name.** The spec's `relation_threshold_v2_2` is the constant `RELATION_THRESHOLD_V2_2`, one value per
       method, read through `relation_threshold(method, version)`.
   16. **Cost per document** is measured from each call's recorded usage, calls answered from the cache included,
       with batched calls at the batch price: it is each method's cost per document, not the pass's spend.
3. **A §9 test fixture is wrong (flagged for the user).** §9 lists "Ana is older than Ben." + "Ben is younger than
   Cy." + "Cy is older than Ana." as an order cycle. It orders Cy > Ana > Ben and is consistent. The test asserts
   what the derivation gives for it (consistent) and checks the order cycle on a set that has one, with mixed
   comparatives: "Ana is older than Ben." + "Cy is younger than Ben." + "Cy is older than Ana." (Ana > Ben > Cy > Ana).
4. **Budget estimate (§7.2), before any call: stop.**
   - **Method** (`scripts/estimate_rev22_budget.py`, read-only, no API call; output
     `results/a1-rev22-estimate-20260925-113656.json`). Rev. 2.1's seed-0 calls are answered from the run of
     record's cache: 2,080 calls, 4,843,798 tokens, $26.40. Input tokens are fitted to request characters per call
     type (relation: 219 + 0.3922 per character; entity: 487 + 0.3465 per character) and applied to the requests
     rev. 2.2 would send for each document's run-of-record pairs. Relation output is fitted to pairs per call (67.0
     + 62.8 per pair) and taken at one pair (130 tokens); entity output is rev. 2.1's for the same document. Claims
     and pair selections come from the cache.
   - **Gate D0 (12 documents):** 1,480 calls, 1,919,076 tokens (1,722,270 input, 196,805 output), about $5.41
     ($2.71 as a batch).
   - **Full development pass (180 documents):** 23,934 calls, 30,876,322 tokens (27,674,052 input, 3,202,270
     output), about $87.37 ($43.69 as a batch). With the entity output 1.5 times larger: 30,936,274 tokens.
   - **L1-var 2.2 (§8.1):** 4,440 calls, 5,757,228 tokens, about $16.24.
   - Most of the input is the system prompt and the output schema, sent again with each of the 23,754 single-pair
     calls. Prompt caching does not apply (decision 9), and a batch halves the price, not the tokens.
   - **A1's spend** from `cache/llm/log.jsonl` (API rows): 8,369,585 of the 15,000,000-token cap; 6,630,415 left.
   - **Result:** the full pass's estimate exceeds both 4,000,000 tokens and the remaining cap, so under §7.2 the
     stage stops here without any call, D0 included, until the user decides.
5. **Spend not recorded in this changelog before.** Item 24 of the A1 entry records 8,348,355 tokens. The log has 10
   more API calls, on 2026-09-25 between 17:42 and 17:50 UTC: 21,230 tokens, rev. 2.1 calls (claim extraction,
   relations, entity relations) on two texts of the Consistency view, tags `text-b129b596d159` and
   `text-5f730b8e7577`. The implementing agent did not make them. Their 10 cached responses are committed with this
   step. The estimate's first run appended 2,080 cache-hit rows (0 tokens) to the log; the script is read-only now.
6. **Tests.** The full suite passes: 454 tests, 26 of them slow. Among the new tests: rev. 2.1
   recomputes the run of record's `l1.json`, `l1b.json` and `documents.jsonl` byte for byte from the cache; the
   12-document subset replays from rev. 2.1's fixtures with no stale fixture (every rev. 2.1 request hashes as
   recorded); the development pass runs end to end offline on the sample corpus with a scripted rev. 2.2 oracle.
   Existing tests changed: the minimal engine's cross-check test takes the threshold argument that `conftest.py` now
   passes (its isolation test is unchanged); the client's retry test covers 5xx, timeouts and `retry-after`; the app
   tests select 2.1 where they test rev. 2.1.
7. **Status.** §10 items 1–3 are met, item 2 with the fixture of item 3 corrected. Items 4–7 (gate D0, the full
   pass, the threshold rule, the freeze) wait for the user. The spec stays in `SPECS/ToDo/`.

---

## 2026-09-23 — A1 (`XON_A1_CONSISTENCY.md` rev. 2.1): re-specifications made before any results

Everything in this entry was fixed before any L1, L1b or L1-var result. The only API calls so far generated the
12-document review sample (re-specification 5) and, after sample approval, the full 60-base corpus (with
leak-scan QA); besides those, the user's Test 1 in the app (4 calls on a text of their own) led to
re-specifications 13–17, and its re-run after them made 2 more (both at the end of this entry). L1, L1b and L1-var
have not run.
The code is in `xon/llm/`, `scripts/make_consistency_corpus.py`, `scripts/run_consistency_eval.py` and the app's
Consistency mode. The three scouting records the spec cites are in `docs/scouting/` (§8 step 8).

### Revision 2.1 of the spec

Revision 2.1 arrived during implementation, before any results. The spec says each of its changes is logged here:
- **Entity-relation graph** (§3.1 schemas, §3.2 prompt, §4.7 checks): relations `same`, `different` and
  `greater` between entities, per attribute, with the attribute's arity (`binary`, `multi`, `unknown`).
- **Document verdict** (§4.6): inconsistent if any of three clauses fires: (a) a `contradicts` edge with
  confidence ≥ 0.5 between two asserted or premise claims; (b) the claim graph restricted to edges with
  confidence ≥ 0.5 is unbalanced; (c) the entity graph has a contradiction among relations with confidence ≥ 0.5
  stated by asserted or premise claims.
- **LLM interface** (§2.1): a `thinking` flag on every call, and `bypass_cache` for L1-var only.
- **Corpus** (§5): 60 base documents × 3 variants; 20 base documents per cycle type (order cycle, equality break,
  binary parity); matched consistent controls; plant verification independent of the pipeline.
- **Experiments** (§6): L1 reports precision, recall and F1 per method, variant type and cycle type, a
  localization hit rate and diagnostics; L1b uses consistent and direct-contradiction variants only; L1-var
  measures judgment variance on the 12-document subset.

### The user's decisions (before revision 2.1; still in force)

1. **LLM settings of the runs of record.**
   - Claude Sonnet 5 is the model of record. It accepts no temperature, so determinism comes from the response
     cache (the cache is the record) and the variance is measured: L1-var re-scores the 12-document subset
     3 times with the cache bypassed. Temperature is sent only to models that accept it. Haiku 4.5 is not for runs
     of record.
   - Thinking is disabled for claim extraction, relation scoring and entity extraction.
   - LLM-direct runs with adaptive thinking (the run of record) and again with thinking disabled (a secondary
     number).
   - L1's total is estimated against the 500k-token session cap and reported before the full corpus runs (below).
2. **Engine verdict.** Inconsistent if the claim graph is unbalanced or a `contradicts` edge with confidence ≥ 0.5
   joins two asserted or premise claims; quoted claims are excluded. Revision 2.1 (§4.6) adds clause (c) and
   applies the confidence filter to the balance clause too.
3. **Plant verification** is a verbatim sentence check: "plant verification never uses the system being
   evaluated." Extraction and relation failures count against the engine, and L1 reports them as diagnostics.
   Revision 2.1 (§5) says the same.
4. **Connected components.**
   - The conflict score is the sum over connected components of each component's smallest eigenvalue λ_min.
   - x* is computed per component, from the component's own lowest eigenvector, also on components without a
     clamped claim when other components have one.
   - A single claim with no relations has λ = 0, x* = +1 and residual 0.
   - A culprit's conflict drop is computed after recomputing the components without it.
   - Sign of x*: the sum of x* over asserted and premise claims is ≥ 0; on a tie, the first entry of largest
     magnitude is positive.
   - When a component's λ_min is repeated, x* shows the first basis vector of its eigenspace and the report says
     so.
5. **Residuals on a repeated λ_min (the user's correction of the formula).** In the user's words: "B: the average
   over the eigenspace, w · (1/m) · Σ_k (u_k,i − s·u_k,j)² with a ±1 incidence vector, so each component's
   residuals sum to its λ_min and all residuals sum to the conflict score. This corrects my earlier formula,
   which double-counted the weight." The degeneracy test also checks that the residuals sum to λ_min for
   multiplicity 1 and for multiplicity > 1.
6. **Harmony when nothing constrains it.** H is None with `harmony_reason` "no relations reach the evidence"
   when no relation touches a component with a clamped claim, and "no premises or evidence" when nothing is
   clamped. The UI shows "not measured". Isolated premises contribute nothing. L1b leaves out documents with
   H = None and reports how many per variant type. (Re-specification 2 below extends the rule to asserted
   claims and renames the reasons.)
7. **Hold.** The corpus and L1 were held until revision 2.1. It has arrived; nothing that calls the API runs until
   the user decides on the budget (below).

### Found while implementing, before any results

- **Zero residuals are not ranked.** A consistent component leaves residuals of floating-point size (around
  1e-30), and their order is noise; the I4 test caught a residual ranking that changed with the weight scale for
  this reason. A claim whose residual is at most 1e-12 × the total weight (edge weights, plus μ per asserted claim
  with a relation edge since re-specifications 2 and 7 below) now counts as zero and is not ranked. The report's
  `residual_ranking` lists the ranked claims, largest first; residuals equal to 9 significant digits (relative to
  the largest) tie and go by claim id. Culprits and L1b's "premise among the top-3 residual claims" use this
  ranking. The threshold is relative, so scaling all weights (and μ) leaves the ranking unchanged (I4).
- **Bug fix.** For documents with at most 25 claims, the pair selection reported `"blind": 0` instead of an empty
  list, and every such analysis failed in the diagnostics step. The pipeline tests found it.
- **Acceptance item "a premise that contradicts two asserted claims gives harmony < 1".** This holds only when
  the two claims are tied to another clamped claim or lie on a frustrated cycle. With the premise as the only
  clamp and a balanced component, the exact clamped minimum makes both claims false and H = 1. The test marked
  two claims that support them as evidence (H = 1 − 3.6/16.8 ≈ 0.786). Put to the user. **Resolved** by the
  harmony re-specification below: the workaround is removed, and with only the premise clamped the test gives
  H ≈ 0.877 with the premise first in the residual ranking.
- **Matched control of the equality-break type (§5).** The spec asks for "the same entities and the same relation
  types" as the cycle variant and calls the control "an equality chain without a break". With A same as B and
  B same as C, no consistent `different` relation among A, B and C exists, so both cannot hold. Put to the
  user. **Resolved** below: A same as B, B different from C, A different from C.

### Re-specifications of rev. 2.1, made before any data (the user's decisions)

The user decided these together, before any corpus document or result existed.

1. **Equality-break control** (§5): A same as B, B different from C, A different from C: the cycle variant's
   entities and relation types, arranged consistently. The phrase "an equality chain without a break" in §5 is
   superseded.
2. **Harmony** (§4.3, §4.5). In the user's words: "The spec treated asserted claims as free truth values, so a
   contradicted assertion flips to false at zero cost and harmony can't register it. Scouting's free vertices
   were hidden beliefs, not assertions, so this wasn't caught there."
   - Energy E(x) = Σ_edges w (x_i − s x_j)² + μ Σ_asserted (x_i − 1)², with μ = 1, fixed. Premises and
     user-marked evidence stay hard-clamped at +1. Quoted claims get no assertion term. On components that hold a
     hard clamp or an asserted claim (the anchored components) the energy is a positive-definite quadratic, so x*
     is an exact linear solve, (L_ff + μ A_f) x_f = μ a_f − L_fc 1, and |x_i| ≤ 1 still holds.
   - H = 1 − E(x*) / (4 Σw + 4 μ n_asserted), over the anchored components (n_asserted: re-specification 7).
     H = None when no relation reaches them. The reasons are now "no premises, evidence or asserted claims" and
     "no relations reach the premises, evidence or asserted claims".
   - A claim's residual includes its assertion term. Culprits are unchanged.
   - I4 (scale invariance) scales all edge weights and μ together; its test does. I5 is unchanged; its energy now
     includes the assertion term.
   - L1b and the acceptance item stay as written, and the acceptance test's workaround is removed: it passes with
     only the premise clamped (H ≈ 0.877, the premise first in the residual ranking).
   - New unit tests: a premise contradicting one asserted claim (w = 1) gives x = 0 on that claim and H = 0.75;
     two asserted claims contradicting each other with no premises give H < 1 (x = 1/3 on both); a quoted claim
     contradicted by a premise flips to false at zero cost.
   - A2 note, recorded in `NAMES.md`: agent-source claims (reports, beliefs, plan steps) are assertions and carry
     the μ term; trusted observations and user or system intents are the hard clamps.

   Readings taken in implementing it:
   - Only quoted claims can now form unanchored components. There x* stays the component's lowest eigenvector,
     with the eigenspace-averaged residuals of decision 5. The first part of the sign rule of decision 4 (the sum
     over asserted and premise claims is ≥ 0) is then always a tie, so only its tie rule applies.
   - A claim's residual on an anchored component is the sum of its edges' residuals plus its assertion term; on
     an unanchored component it is the sum of its edges' residuals (which sum to 2 λ_min there).
3. **L1 scoring** (§6).
   - Direct F1 on the consistent and direct variants (60 + 60). Cycle F1 on the consistent and cycle variants,
     overall (60 + 60) and per cycle type (20 + 20, matched controls). A false-positive rate per method on the
     consistent variants. Precision and recall are reported with each F1.
   - A claim is a planted claim when its verbatim span, after whitespace normalization, lies inside the planted
     sentence or contains it. LLM-direct's cited sentences are mapped the same way.
   - A planted relation counts as extracted when an entity relation's `claim_id` is a claim matched to the planted
     sentence, both entities match (case-insensitive), and the kind matches, with the direction of `greater` under
     the extraction prompt's rule. The prompt's rule does not cover rank phrasings ("finished ahead of"), so for
     rank either direction counts if all of the document's planted rank relations agree. This anchors the
     relation to its sentence without normalizing attribute keys.
   - Arity accuracy is read from the attribute of the entity relations matched to the planted relations: "binary"
     is expected on binary cycle variants and "multi" on their controls.
   - Localization: the engine hits if a reported contradiction (an entity cycle, the frustrated claim cycle, or
     the top-3 culprits) holds claims matched to at least two planted sentences. LLM-direct hits if a listed
     contradiction cites at least two planted sentences.
   - Seed 0 is the run of record; seeds 1 and 2 (documents with more than 25 claims) are reported as spread.
4. **Budget.** The user raised A1's cap to cover L1, L1b and L1-var: about $100 for all of A1. It is enforced
   as a 10M-token cap over all of A1's API calls, summed from the call log and passed to each run as `--budget`.
   At the table's Sonnet 5 prices ($2 / $10 per million input / output tokens), 10M tokens cannot cost more
   than $100 even if every token were output. A1's estimate is 3.0M–9.8M tokens (about $18–67).
5. **Review sample.** The user set the API key, and the 12-document sample was generated: 4 base documents
   (bases 0–3, all three cycle types) × 3 variants. The call log holds no prompt text and no key. Generation
   stops here for the user's review (rule 5). Producing and reviewing the sample took five rounds, 32 calls
   (28 of them fresh, 4 served from the cache) and 36,813 tokens, about $0.16, summed from the call log:
   - the first draft (7 calls, 3 regenerations, none failed) surfaced three generator problems, re-specified
     below as 8–10;
   - the sample was regenerated against the fixed generator (4 regenerations, none failed), which surfaced the
     harder paraphrase problem behind re-specification 11 below;
   - base 3 was regenerated under the broadened restriction and bases 0–2's existing text was rescanned (not
     regenerated) under the new leak-scan pass, surfacing three flags;
   - bases 1 and 2 were regenerated against a confirmed leak each; base 1 came back clean, base 2 leaked again
     through the same claim's narrative tone;
   - base 2 was regenerated once more with its planted fact swapped to one with no emotional valence (below),
     and came back clean.
6. **L1's pass** (§6): the "Pass" criteria apply to the engine only. The baseline numbers listed with them
   (direct F1 ≥ 0.85 "expected" of all methods, pairwise cycle F1 expected below 0.5) are reported expectations,
   not additional pass conditions.
7. **n_asserted in the harmony bound** counts only asserted claims with at least one relation edge. In the user's
   words: "An asserted claim with no edges settles at x_i = 1 with zero assertion cost (nothing pulls it
   elsewhere), so including it in the bound would inflate H for free — the same padding failure mode as the
   exploit battery." A unit test checks that one contradicted assertion plus N unrelated asserted claims gives
   the same H for N = 0, 1, 5 and 20, with and without a premise. The zero threshold of the residual ranking uses
   the same count.

The first review-sample draft (re-specification 5) surfaced three generator problems, put to the user with the
sample: the required sentences came as a consecutive block right after the opening sentence in every document
(a position tell); one base alluded to its claim's event without repeating it verbatim ("the hall booking",
after the required "Gus booked the hall."); one base's text carried a stray, unpaired curly quotation mark; and
one base needed all 3 (then the maximum) attempts to pass plant verification. The user re-specified the
generator before generating again:

8. **Spread.** The required sentences must not sit in adjacent sentences or all fall within one stretch of the
   document — position must not be a tell. Enforced automatically on the consistent variant (the one Claude
   writes; the direct and cycle variants only add or swap one sentence in it): no two required sentences may be
   in adjacent sentences, and their sentence-index span must cover at least half of the document's sentences.
   The prompt now asks for this explicitly. A document that fails is regenerated.
9. **Tighten.** (a) The stray quotation mark was a formatting bug: the prompt now forbids quotation marks
   anywhere in the document, and any of `"`, `\u201c`, `\u201d` in the text fails verification. (b) No sentence but
   the required ones may refer to the premise's role or the claim's event, directly or indirectly, other than in
   the required sentence itself; incidental detail and cross-references among non-planted content are unaffected
   and stay, since they make the documents realistic. The prompt states this restriction; it is additionally
   verified with a keyword check on ROLES' and FACTS' fixed, closed vocabulary (e.g. "hall" for "booked the
   hall"), which caught and forced the regeneration of all three of the first draft's remaining leaks ("hall",
   "raffle", "minibus") once introduced. This check is necessarily partial: a paraphrase that names no keyword
   (for example, describing a captain's duties without saying "captain") is not caught and is left to review, as
   §5's plant verification is a string check only.
10. **Attempts.** `MAX_ATTEMPTS` is raised from 3 to 5, since more of a document's structure is now being
   verified and needs more room for the model to fix it, and 60 base documents must all pass for a corpus to be
   of record. The retry prompt now states the specific problems from the previous attempt (previously a generic
   message), so retries address the real failure rather than guessing at it. A base document that only passes on
   the final attempt is flagged in the generation stats (`flagged`) rather than silently accepted; the retries
   exist only to satisfy plant verification's structural, pipeline-independent checks, never to search for a
   draft that scores better on extraction or relation-matching.

Regenerating under 8–10 fixed the reported problems, but the regenerated base 3 still had a document-level
paraphrase leak the keyword check of re-specification 9b cannot see by construction (it matches a fixed
vocabulary, not meaning): the sentence right after "Assume that Nell is the team captain." described her
organizing the roster and pairing sheets — a captain's duties, without the word "captain". Put to the user with
the sample. **Resolved** as re-specification 11, since a bigger keyword list would not generalize to this
category of problem:

11. **Leak-scan QA pass.** (a) The generator's restriction is broadened from specific phrasings to a general
   one: no sentence but the required ones may describe, hint at, or make guessable a person's planted role or
   relationship, or a planted fact's subject matter, literally or indirectly, including by describing what it
   implies. (b) A second, independent LLM call — its own prompt (`LEAK_QA_SYSTEM`), outside the scored
   extraction/relation pipeline, no schema or code shared with it — reads each accepted document and flags any
   sentence it believes leaks a planted fact by paraphrase. It only reports flags (`generate(..., qa_scan=True)`
   writes them to `stats["leak_flags"]`); it does not regenerate. The user decides, per flagged document, whether
   to act, since the pass is a second, differently-prompted read of the text, not a ground truth. Base 3 was
   regenerated under the broadened restriction (clean, no flags) and bases 0–2's existing, already-verified text
   was rescanned without being regenerated, surfacing three flags put to the user with the sample (below).
   - **Base 0, confirmed false positive:** a height comparison between Uma and Cy, flagged as implying the
     planted age order among Isla, Kai and Cy. Different attribute, and Uma is outside the planted trio, so
     there is no inferential path to the planted relations — the kind of cross-person, cross-attribute filler
     the generator's own prompt asks for. Left unchanged; logged in `sample_generation.json`'s
     `confirmed_false_positives` in case the pattern (the checker over-triggering on same-category,
     different-subject comparisons) recurs.
   - **Base 1, confirmed leak, fixed by regeneration:** "...where Leo and Dev had worked separately earlier that
     week," restating "Leo is not on the same team as Dev." Regenerated once; the new draft has no leak.
   - **Base 2, confirmed leak, recurring across two drafts, fixed by swapping the claim:** the planted fact "Vik
     won the raffle" leaked twice through narrative tone rather than restatement — first "given his earlier
     luck," then, after one regeneration, "still smiling about the earlier excitement" — a claim-specific
     tendency of this particular fact (an emotionally loaded "win" moment), not a random draft issue. Rather than
     iterate on phrasing instructions, which likely relocates the tell without removing it, the user swapped
     base 2's planted fact to a neutral, logistical one with no emotional valence to leak through ("brought the
     first-aid kit"; `FACT_OVERRIDES = {2: 0}` in `xon/llm/corpus.py`, a single-base override, not a change to
     the fact balance across the corpus). The regenerated draft is clean. This pairing (base 2's identity, "won
     the raffle") is logged as a known problematic combination; the generalization (avoid planting emotionally
     loaded win/loss facts as the hidden claim) is not adopted from this one case and will only be acted on if
     the same pattern recurs elsewhere in the 60-base run.

   **Review rule for the full 60-base corpus (the user's decision, logged with the others, before any full-corpus
   data):** the leak-scan pass runs report-only on all 60 base documents. The user reviews every flagged document
   (flags are rare enough to make this tractable) plus a random 10% of unflagged ones, with the sample's seed
   fixed before the flag list is seen (`REVIEW_SEED = 20260923` in `scripts/make_consistency_corpus.py`, written
   into `corpus_generation.json` as `review`). A confirmed leak gets that base regenerated and rescanned; a
   confirmed false positive is logged and left as-is. The run reports the total flag count and the confirmed-
   leak/false-positive split alongside the corpus.

**Deviation (base 32, logged at the review gate):** Re-specification 10 caps plant-verification retries at
`MAX_ATTEMPTS = 5` (a base that only passes on the final attempt is flagged, not given further attempts). On the
full-corpus run base 32 failed all 5 attempts (always "adjacent required sentences"). To complete the 60 × 3
corpus so review could proceed, it was regenerated once more with `max_attempts=8`, passed only on attempt 8, and
was recorded in `flagged` / `base32_extra_attempts` in `corpus_generation.json`. That exceeds the registered
cap: a deviation, not a silent re-specification. The draft is held for the user's review with the rest of the
flag pack; it is not treated as auto-accepted. (The user referred to this as a deviation from re-specification
11; the registered attempt cap is item 10.)

12. **Leak-scan: cross-attribute comparisons are expected filler.** An independent blind review (a different
   model, no plant list) flagged three sentences as foreshadowing — matching the same cross-attribute-comparison
   pattern already logged twice as a false positive (base 0 Uma/Cy height vs planted age; now also base 1
   Leo/Dev age and Mina/Ben arrival near the team-equality plant). None looked like confirmed leaks: different
   attribute, filler as the generator prompt asks for. The pattern has now recurred independently four times
   (and a fifth confirmed false positive on base 0: Kai/Isla contest ranking / "crooked rows", not age — logged
   as confirmed false positive #3 in `sample_generation.json`). The leak-scan prompt (`LEAK_QA_SYSTEM`) and its
   user message now state explicitly: any comparison on a different attribute than the planted one (height,
   ranking, team, arrival time, age, …), even between people who also appear in a planted relation, is expected
   filler and must not be flagged unless it specifically implies the planted attribute's value or order. The
   user message names the planted attribute so the checker can apply the rule. Logged before any full-corpus
   data.

**LLM client (`xon/llm/client.py`).**
- **`messages.create` instead of `messages.parse`.** The output schema goes out as `output_config.format`.
  `messages.parse` validates inside the SDK and raises on a refused or truncated response before its stop
  reason can be read. The client checks the stop reason first ("refusal" raises `LLMRefusal`, "max_tokens" raises
  `LLMTruncated`), then validates. Neither is cached, and invalid output is not retried.
- **Own schema transform.** SDK 0.84's `transform_schema` moves `enum` into the description, although the API
  enforces `enum`. `output_schema` keeps `enum`, sets `additionalProperties: false` on every object and rejects
  keywords the API does not support (numeric bounds, string lengths). Enum values are lower-cased before
  validation, because their casing is not guaranteed. Confidences are clipped to [0, 1] where they are used.
- **Retries.** The SDK client is built with `max_retries=0`; the LLM client retries HTTP 429 and 529 only,
  3 times, after 2, 4 and 8 s. SDK 0.84 exports no top-level `OverloadedError`, so retries key on the status code.
- **Budget pre-check.** A call is refused if the tokens spent + ceil(request characters / 2.5) + `max_tokens`
  would exceed the budget; 2.5 characters per token allows for Sonnet 5's tokenizer. Cache and fixture hits cost
  nothing. Spent tokens are input (including cache creation and cache reads) plus output.
- **Model parameters.** `temperature` is sent only to models that accept sampling parameters (Haiku 4.5).
  `thinking: disabled` is sent only to models that can disable thinking (Sonnet 5, Haiku 4.5). Opus 5.5 and
  Fable 5.1 always think, and the UI says so. `thinking=True` leaves the field out: the model's default, adaptive
  for Sonnet 5, Opus 5.5 and Fable 5.1, none for Haiku 4.5.
- **Dry-run** answers from the response cache first, then from fixtures (`tests/fixtures/llm/`, one file per
  tag). Setting `XON_LLM_RECORD=1` records fixtures during live calls; reusing a tag for a different request
  raises. Tags are sanitized to letters, digits, `.`, `_` and `-`, at most 150 characters.
- **Call log** (`cache/llm/log.jsonl`): timestamp, tag, model, kind, schema name, `max_tokens`, thinking,
  temperature, a 16-character request hash, source (API, cache or fixture), cache hit, tokens, duration and any
  error or stop reason. No prompt text and no key. The key is read only from the API key environment variable,
  by the SDK.
- **Price table** in `xon/config.py`, dated 2026-09-23 and marked as needing verification (USD per million
  input / output tokens): Sonnet 5 2 / 10, Haiku 4.5 1 / 5, Opus 5.5 4 / 20, Fable 5.1 10 / 50. It feeds only
  the running cost estimate.

**Schemas and prompts.**
- The pair list is a list of `{a, b}` objects, not `tuple[int, int]`: the API cannot constrain tuples.
- All prompt text of the engine is in `xon/llm/prompts.py`; the corpus generator's is in `xon/llm/corpus.py`.

**Graphs and analysis.**
- `supports` and `contradicts` relations with confidence 0 make no edge (w = 0 adds nothing) and are counted.
  `unrelated` relations make no edge. For a repeated pair, the first relation is kept and the rest are counted.
- λ_min is set to exactly 0 on balanced components (the eigensolver returns about 1e-16).
- A component's λ_min counts as repeated when other eigenvalues lie within 1e-8 × the component's largest
  eigenvalue of it.
- On unanchored components a claim's residual is the sum of its edges' residuals, so the component's claim
  residuals sum to 2 λ_min (its edge residuals to λ_min). On anchored components the assertion term is added
  (re-specification 2).
- Culprits: the top 3 claims of the residual ranking (the spec's "top-k"; L1 localizes with the top 3).
- Unanchored components include single quoted claims.
- Entity graph: an attribute is `binary` only if every entry for its key says so (`multi` if any says `multi`,
  otherwise `unknown`). Attribute keys that are comparatives ("younger", "shorter", "earlier" and others) are
  renamed to the attribute they compare, and their `greater` relations are swapped, as a safety net behind the
  prompt's direction rule. A `different` or `greater` relation inside an equality class is a contradiction for
  every arity. The shortest contradiction of each type on each attribute is reported.
- Report fields added to the spec's: `harmony_reason`, `components`, `component_degenerate`, `degenerate`,
  `direct_contradictions`, `confident_frustrated_cycle`, `verdict_entity_contradictions`, `residual_ranking`.
- The pairwise-only baseline counts a `contradicts` edge with confidence ≥ 0.5 between any two claims, quoted
  ones included.

**UI.**
- Consistency is a fourth option of the sidebar's Mode selector, not a tab: a V1.1 test pins the tab list.
- The dry-run banner shows in the sidebar in every mode while the API key environment variable is unset.

**Corpus generator** (written and unit-tested; not run).
- Claude writes only the consistent variant (i), which must contain the plan's sentences verbatim. Variant (ii)
  is (i) plus the planted negation, inserted at a seeded sentence boundary; variant (iii) is (i) with the
  control's differing sentence replaced by the cycle's (order, equality) or the "three values" sentence replaced
  by "two values" (binary). The three variants differ only in their planted sentences.
- Plans are fixed in advance: the cycle type is the base index mod 3 (20 each); the premise is negated on even
  indices (10 per cycle type); one premise per document ("Assume that D is <role>."); one asserted claim;
  three relational claims per cycle (the spec allows three or four); arity sentences "There were two teams." /
  "There were three teams." (and the same for houses and shifts). The negation is the explicit "not" form.
- Plant verification: every required and planted sentence occurs exactly once, starting at a word boundary,
  after whitespace normalization, and no sentence belonging only to another variant occurs; no two required
  sentences are adjacent and their span covers at least half the document (re-specification 8); no stray
  quotation mark (re-specification 9a); no keyword leak of the premise's role or claim's event outside the
  required sentences (re-specification 9b). A base document that fails is regenerated with the specific
  problems fed back, up to 5 attempts (re-specification 10); the counts, and any base flagged for passing only
  on the last attempt, go to `<name>_generation.json`. Truncation (`LLMTruncated`) is treated the same way as a
  verification failure (retry with a changed request) rather than aborting the corpus; `MAX_TOKENS` for
  generation is 4096 (raised after base 10 hit 2048 mid-JSON on the first full-corpus attempt).
- The full corpus needs `--sample-reviewed` and an existing review sample. Generation calls run without thinking,
  with `max_tokens` 2048.
- Records carry the planted relations as structured `relations` (sentence, kind, the two people, direction), so
  the relation-matching rule needs no parsing. For `greater` the people are ordered by the extraction prompt's
  rule ("X arrived before Y" is Y > X on arrival time); rank relations are marked "either".

**Experiment runners** (`xon/llm/evaluation.py`, `scripts/run_consistency_eval.py`; written and unit-tested
with scripted clients; not run).
- Every score is computed from per-document JSON rows (`documents.jsonl`), so a run can be scored again without
  any call.
- Relations are compared after the engine's normalization: an entity matches a planted person when its
  canonical id or one of its mentions equals the name, case-insensitively, and comparative attribute keys have
  been renamed and their `greater` relations swapped (the engine's safety net).
- Rank relations whose found orientations are mixed: only those in the planted orientation ("X finished ahead
  of Y" read as X > Y) count.
- Arity is read from the most common attribute among the matched relations; with no matched relation it reads
  "missing" and counts as wrong.
- The pass is judged on the engine: direct F1 ≥ 0.85, cycle F1 ≥ 0.75 and localization ≥ 0.7. The spec's
  expectations for the baselines ("all methods expected to pass" the direct threshold; pairwise cycle F1 expected
  below 0.5) are reported, not judged. The user confirmed this (re-specification 6).
- Only the full corpus (60 base documents × 3 variants) with the model of record is judged; any other run prints
  "not judged" and the reason.
- L1b's premise criterion uses the direct variants whose premise is negated and whose H is defined. The fraction
  with unanchored components is over all consistent and direct variants.
- Seeds 1 and 2 re-draw the blind-check pairs under their own fixture tags and keep seed 0's claims and entity
  relations. The engine's localization per seed is part of the spread.
- L1-var repeats relation scoring, entity extraction and both LLM-direct calls, 3 times with the cache
  bypassed, on seed 0's claims and pairs. It re-runs LLM-direct because the spec asks how often each method's
  verdict changes; the logged L1-var estimate is consistent with that. Repeats use their own fixture tags, and
  L1-var refuses to run in dry-run mode, where every repeat would replay one answer. A pair agrees when its label
  (a missing label counts as one) is the same in every repeat; an entity relation (claim, kind and entities,
  unordered for `same` and `different`) agrees when every repeat has it.
- An LLM error (refusal, truncation, invalid output, budget) stops the run and names the document; completed
  calls stay cached. No document is scored with a method missing.

### Budget estimate (rule 4), before any call

Estimated from the real prompts and output schemas, 4 characters per token for prose and 3 for JSON, plus 30%
for Sonnet 5's tokenizer (spec §0), and 2,000 thinking tokens per LLM-direct call with thinking. Relation scoring
dominates: a document with 18 claims has 153 pairs in 8 calls, and each relation carries a one-sentence
rationale.

| Claims per document | L1 (180 variants) | L1-var (12 documents × 3) | Corpus (60 base documents) | All of A1 | Cost at the table's Sonnet 5 price |
|---|---|---|---|---|---|
| 12 | 2.5M | 0.44M | 0.06M | 3.0M | about $18 |
| 18 | 4.6M | 0.83M | 0.06M | 5.4M | about $36 |
| 25 | 8.2M | 1.5M | 0.06M | 9.8M | about $67 |

The 500k-token session cap covers the 12-document review sample (about 4k tokens) and the full corpus
generation, but not L1, L1b or L1-var. The user will raise the cap and give the figure (re-specification 4);
until then only the review sample runs.

### Re-specifications after the user's Test 1, before any L1 data

The user ran a text of their own through the app's Consistency mode (Test 1, call tag `text-baf3d6dc5da6`: 9
claims, all 36 pairs in 2 relation calls, 1 entity call). In the user's words: "the entity graph found the order
cycle correctly (claims 1/5/7, conf 0.95). But relation scoring has two problems to fix before L1 (log as A1
re-specifications, before data)". What Test 1 showed, rebuilt from the cached responses:
- Pair (1, 7) was labeled `contradicts` at 0.85, while its rationale concluded "no direct contradiction exists
  between just these two statements alone" and ended in a leaked `', 'confidence': 0.3}`.
- The judge used a third claim to judge the pair ("given typical transitive ordering context").
- That one label fired the direct clause on (1, 7) and the balance clause on the frustrated cycle 0 → 1 → 7, so
  the verdict clauses were `direct, claim_balance, entity`. The pairwise-only baseline also reported the text
  inconsistent, on (1, 7).

The items below were decided together and implemented before any L1, L1b or L1-var call. The spec file is
unchanged, as with re-specifications 1–12. No relation-scoring fixtures had been recorded, so none went stale.
Test 1's old relation answers stay in the response cache under their old request hashes; the new prompt and schema
give new hashes, so those answers are never replayed.

13. **The rationale comes first** (§3.1). The `Relation` fields are now `a, b, rationale, relation, confidence`,
   all required. In the user's words: "put rationale first, then relation, then confidence, so the model reasons
   before committing." Structured outputs write an object's properties in the schema's order, required ones first
   (Anthropic's structured-outputs documentation, "Property ordering"), so with every field required the model
   writes its reasoning before the label and the confidence. The pair's ids stay first: the model names the pair
   before it reasons about it. The relation prompt describes the fields in the new order.
14. **A malformed rationale is scored once more, on its own** (§3.2). In the user's words: "Add a malformed-output
   check: if a rationale contains JSON-like fragments, re-score that pair once and log it."
   - A rationale is malformed when it matches `JSON_FRAGMENT` in `xon/llm/claims.py`,
     `[{}]|["'][A-Za-z_]\w*["']\s*:|\b(?:relation|confidence|rationale)["']?\s*:`: a brace, a quoted key followed
     by a colon, or an output field's name followed by a colon. On Test 1's 36 cached rationales it flags exactly
     (1, 7).
   - After a document's batches, each flagged pair gets one call of its own: the same system prompt, schema and
     `max_tokens`, with a user message that lists only that pair and its two claims. Its tag is
     `<tag>-relate[-wk]-rescore-aaa-bbb` (the pair's claim numbers, three digits each), so it shows in the call
     log. It bypasses the cache exactly when its batch does (L1-var).
   - The second answer replaces the first only if it returns the pair with a clean rationale. If it is malformed
     too or leaves the pair out, the pair stays unscored: no relation and no edge. There is no third call. The user
     decided this, in their words: "If the single-pair re-score is also malformed or omits the pair, leave the
     pair unscored (no edge) and flag it. This is decided from the output's form before any analysis and applied
     identically to all pairs and methods, so it doesn't violate I2."
   - The rule applies wherever relations are scored: the engine and the pairwise-only baseline (they share the
     relations), seeds 1 and 2, the world-knowledge re-score and L1-var. An analysis's diagnostics list the
     re-scored pairs with both answers and the outcome (`relations_rescored`) and the pairs the rule left unscored
     (`pairs_unscored_malformed`); `pairs_missing` still lists every unscored pair, whatever the cause. The app's
     "Relations and rationales" table shows the rationale before the label and explains each re-scored pair
     below it. The README's I2 line and the engine's docstring say the same.
15. **Unscored pairs are reported per document, and more than 1% stops the run** (§6). In the user's words:
   "Report per document: unscored pair count, and whether any unscored pair involves planted claims. If unscored
   pairs turn out not to be rare (say more than 1% of pairs), stop and report before L1."
   - An unscored pair is a requested pair with no relation: left out by the model, or unscored after a malformed
     re-score. Each document row records its unscored pairs per seed, how many of them the malformed-rationale
     rule left unscored, and whether any unscored pair at seed 0 involves a claim matched to a planted sentence.
   - The stop rule reads seed 0, pooled over the run's documents: unscored pairs over pairs requested, both causes
     together. `scripts/run_consistency_eval.py` checks it after the LLM calls and before L1 or L1b is scored.
     Above 1% it prints the per-document report, writes only `unscored_gate.json` and `run.json` (marked
     `"stopped": "unscored pairs"`), and exits with code 3. `--accept-unscored` scores L1 and L1b anyway, after the
     user's decision, and `run.json` records that it was used. At or below 1% the run goes on, and the L1 report
     gives the counts by cause, the re-scores, the sampled documents' counts per seed and the per-document list.
16. **Each pair is judged on its own** (§3.2). In the user's words: "The judge used a third claim ("transitive
   ordering context") to judge a pair, which makes the pairwise baseline not pairwise and lets the engine's
   direct/balance clauses fire on cycle documents for the wrong reason. Update RELATE_SYSTEM: judge each pair
   using only its two statements, ignoring every other statement in the batch, even if they seem relevant." Both
   variants of the relation prompt (world knowledge off and on) now say: "Judge each pair using only its two
   statements, ignoring every other statement in the list, even if they seem relevant." "Batch" became "list"
   because the model sees one numbered list of claims per call, never the word batch. The user message is
   unchanged.
17. **Two L1 diagnostics, reported and not judged** (§6). In the user's words: "on cycle variants, (a) the
   contamination rate: the fraction of planted-cycle claim pairs labeled contradicts; (b) per-clause attribution:
   how many engine detections came from the entity clause alone vs. also from direct/balance." Both are computed
   on the cycle variants at seed 0, overall and per cycle type, and go to `l1.json` (`diagnostics`) and the L1
   report.
   - (a) Contamination: of the scored claim pairs whose two claims match two different planted sentences, the
     fraction labeled `contradicts`, at any confidence. The planted sentences are the cycle's relational
     sentences, plus the arity sentence on binary-parity documents. These pairs are pairwise compatible by
     construction, so every `contradicts` label on them is contamination. Unscored planted pairs are counted
     separately.
   - (b) Clause attribution: the engine's detections, split into the entity clause alone; the entity clause with
     the direct or balance clause (or both); the direct or balance clause without the entity clause. The count of
     each exact combination of clauses is reported too.

Tests (offline): the schema's order; the isolation sentence in both prompts; the detector on Test 1's rationale
and on clean ones; the three re-score outcomes, with no third call, and re-scores bypassing the cache with their
batch; contamination and attribution on hand-made rows and on the oracle pipeline (contamination 0 of 15, all 4
detections from the entity clause alone, no unscored pair); the 1% stop and `--accept-unscored` in the eval CLI;
the app's caption for a re-scored pair. The full offline suite passes (371 tests; the 25 slow ones deselected as
usual).

### Test 1 re-run after re-specifications 13–17 (a check, not an L1 result)

Test 1's cached claims went through the rest of the pipeline again, as Analyze does on the same text (world
knowledge off, no evidence): all 36 pairs in 2 live relation calls under the new prompt and schema. The entity call
was a cache hit, since its request is unchanged. That came to 2 API calls, 2,141 input and 2,415 output tokens,
about $0.03 at the table's price. The new answers are in the response cache, so Analyze on the same text replays
them.

| | Before (the user's Test 1) | After |
|---|---|---|
| Verdict clauses | direct, claim_balance, entity | entity |
| Entity contradiction | order cycle on claims 1, 5, 7 | the same |
| Direct contradiction; confident frustrated cycle | (1, 7); 0 → 1 → 7 | none; none |
| Pairwise-only baseline | inconsistent, on (1, 7) | not inconsistent |
| Contamination: of (1, 5), (1, 7), (5, 7), labeled `contradicts` | 1 of 3 | 0 of 3 |
| Malformed rationales; re-scores; unscored pairs | 1; not yet in force; 0 | 0; 0; 0 |
| Edges (relations other than `unrelated`) | 5 | 3 |

Two labels changed:
- (1, 7) went from `contradicts` 0.85, with the malformed rationale quoted above, to `unrelated` 0.6: "If Priya
  arrived before Tomas, this doesn't directly determine whether Lena arrived before Priya."
- (2, 5) went from `supports` 0.5 to `unrelated` 0.55. Its rationale now weighs the coffee stop both ways before
  it concludes that it "doesn't directly support arriving before Lena".

(0, 1), (0, 5) and (0, 7) still support (0.6, down from 0.7): the general claim of different arrival times against
each ordering. (1, 5) and (5, 7) stay `unrelated`, though (1, 5)'s rationale still wavers ("compatible and combine
to support the order … however …") before it settles at 0.55. This is one sample from a model that takes no
temperature: it shows the fixes acting as intended on this text, not how often the problems recur. L1's
contamination diagnostic and L1-var measure that.

### Corpus QA: superlative-collision check (before L1; after blind contradiction review)

18. **Superlative / universal-extremal collision** (§5 plant verification). Blind review found an unplanted
   contradiction in all three variants of base 32: "Milo arrived first" vs "Quinn … had arrived a full ten
   minutes before anyone else". Gemini's contradiction-only pass on the 180-document blind packs missed it in
   all three, so its clean results cannot be relied on alone. A deterministic check now flags when two different
   listed people are given the same pole on the same attribute (arrival earliest/latest, height tallest/shortest,
   age oldest/youngest, rank highest/lowest). Cues include paraphrases of first/last: "before anyone else",
   "ahead of everyone", "last to arrive", "after everyone", etc. Ownership is the nearest listed name before the
   cue in the sentence (so "Esme mentioned that Leo was the tallest" credits Leo only). The check is in
   `superlative_collisions` / plant `verify`, and the generator prompt forbids the pattern.
   - **Pre-regeneration scan of all 180 documents:** only base 32's three variants hit (arrival/earliest: Milo,
     Quinn). Hits written to `data/consistency/superlative_collisions.json`.
   - **Base 32** was regenerated (2 attempts; leak-scan clean; post-regen collision check empty). The prior
     8-attempt deviation draft is replaced. Full-corpus collision scan after the swap: no hits.

19. **Deterministic corpus QA suite** (`xon/llm/corpus_qa.py`) and review regenerations. After blind review
   confirmed that the only accidental contradiction in the 180 documents was base 32's arrival clash (caught by
   the superlative scan; Gemini's contradiction-only pass missed it), two further deterministic scans were
   added and wired into plant `verify` and into `generate` (stored under `stats["deterministic_qa"]` after every
   accepted draft; leak-scan still report-only behind `qa_scan`):
   - **Activity-synonym check:** residual sentences must not use listed paraphrases of the claim event
     (`ACTIVITY_SYNONYMS`, beyond the single `FACT_KEYWORDS` token).
   - **Same-attribute filler check** (consistent variant only): residual sentences must not relate two of the
     planted trio on the planted attribute.
   - **Pairwise order-cycle scan:** extract order phrases per attribute; report cycles on all edges and on
     edges whose sentence is not planted. Unplanted cycles fail `verify`.
   - **FACT_OVERRIDES** extended: `{2: 0, 47: 0}` (base 47 raffle → first-aid kit, same cheerfulness-leak pattern
     as base 2).
   - **Regenerated bases** 29, 32, 33, 34, 44, 47, 49, 51 (8 bases × 3 = 24 documents). Attempts:
     29:2, 32:2, 33:1, 34:5 (flagged), 44:2, 47:1, 49:5 (flagged), 51:2. Cost ≈ $0.15 (39k tokens).
   - **Post-regen full-corpus QA** (`data/consistency/corpus_qa_report.json`): 180 documents; 225 order phrases;
     all 20 planted order-cycle bases recognized; **0** same-attribute hits; **0** superlative collisions;
     **0** unplanted order cycles. Regenerated bases: **0** activity-synonym hits. Residual activity-synonym
     hits remain on non-regenerated bases 4, 7, 17, 22, 37, 59 (photo/prize/shot/"earlier excitement" narrative);
     not acted on in this pass. Leak-scan report-only flags on regen: 33, 44, 47 (one sentence each).

20. **Review of the post-regeneration QA: the user's decisions, logged together before the regenerations they
   call for.** The review covered the five checks run on all 180 documents after re-specification 19
   (`data/consistency/corpus_confirm_report.json`).
   - **Bases 34 and 49 accepted.** Both passed only on attempt 5 (flagged under re-specification 10); all five
     checks pass on them.
   - **Raffle fact swapped on bases 7, 17, 22 and 37**, as for bases 2 and 47. In the user's words: "Raffle-win
     leaks are systematic (prize and reaction sentences in b07, b17, b22, b37, after bases 2 and 47)." Base 2's
     entry deferred the generalization until the pattern recurred; it has now recurred in six bases, and the user
     fixed it base by base. `FACT_OVERRIDES = {2: 0, 7: 0, 17: 0, 22: 0, 37: 0, 47: 0}`, all "brought the
     first-aid kit". The first-aid kit is now the claim of 18 of the 60 bases and the raffle of 6 (12 each
     before). The plan-balance test covers cycle types, premise negation and topics, not facts. The other raffle
     bases (12, 27, 32, 42, 52, 57) keep their fact.
   - **Base 59 regenerated.** The user's rule: regenerate if the "group shot" sentence shows Ivo taking, framing
     or handling the photo. The sentence directly follows "Ivo took the photographs.": "He crouched near the tide
     pools to catch the best light before the sun climbed too high, and everyone paused briefly to smile for one
     group shot." "He" is Ivo, framing the shot.
   - **Base 47 regenerated.** The user's rule: regenerate if the sentence states or implies a number of teams or
     groups. The sentence, identical in all three variants: "As the sun climbed higher, the group split up to
     cover more ground, each pair moving along a different section of the marsh." The document opens with "five
     friends", so splitting into pairs implies two or three subgroups: an implied group count, in a document
     whose planted contradiction is the number of teams.
   - **Accepted unchanged:** every other activity-synonym hit and every other leak-scan hit (premise roles,
     companionship, cross-attribute comparisons, weak hints).
   - **Regenerating against a reviewed problem.** Base 47's last draft was written with the current prompt, so an
     unchanged request replays it from the cache. `generate(..., review_problems={base: [...]})` starts such a
     base at attempt 2 and states the reviewed problem in the existing retry message ("an earlier draft had these
     problems: …"), the way plant-verification failures are fed back. The attempt cap (5) and the final-attempt
     flag are unchanged. Bases 47 and 59 get the quoted sentence as their problem. The swap changes the required
     sentences of bases 7, 17, 22 and 37, so their requests are new without it.
   - **Go-ahead rule for L1 (the user's).** After the regenerations, all five checks are rerun on the whole
     corpus. If the same-attribute, superlative and order-cycle checks are clean and the activity-synonym check
     has no hits on the regenerated bases, the L1 run of record (L1, L1b, L1-var, as registered) may start. No
     prompt, threshold or code changes after it starts; if something breaks, stop and report.
   - **Result.** All six bases regenerated, and plant verification passed on all 18 documents. None failed or
     needed the final attempt. Attempts: 7: 3, 17: 2, 22: 1, 37: 2, 47: 3, 59: 3 (47 and 59 started at attempt
     2). About $0.10 (32k tokens in 20 API calls). The unchanged documents' leak-scans replayed from the cache,
     identical to the reviewed scan. The previous corpus is kept as `corpus_before_respec20.jsonl`.
   - **The five checks on all 180 documents** (`data/consistency/corpus_confirm_report.json`):
     - same-attribute: none;
     - superlative collisions: none;
     - unplanted order cycles: none (231 order phrases; all 20 planted order cycles recognized);
     - activity synonyms: only base 4's accepted "photo" sentence (3 variants), none on the regenerated bases;
     - leak-scan: 158 flags. 120 are the direct and cycle variants' own planted sentences, because the scan is
       given the consistent variant's planted list. That leaves 38 filler flags, three of them new (all on
       regenerated bases). Base 17: "Dev checked in with volunteers throughout the day, making sure every table
       had enough space and that the extension cords were taped down safely." (premise role, 3 variants) and
       "Zeno mentioned that his shift felt shorter than expected, though he didn't say why." (Zeno's own shift,
       no relation to anyone; 3 variants). Base 22: "The two of them exchanged a quick fist bump before settling
       into their seats, clearly comfortable working together." (the planted same-class pair; consistent and
       direct variants).
   - The go-ahead conditions hold.
   - **Raised with the user before starting L1.** Two raffle bases this review did not cover have a reaction
     sentence right after the claim:
     - base 12: "The room buzzed with quiet excitement, and Hana clapped along with the others, smiling at the
       good news." The leak-scan flagged it in b12-direct only, and the report this review was based on did not
       list it. The premise is the negated fact here, so the raffle claim is never contradicted.
     - base 57: "Several volunteers cheered when the announcement echoed over the small speaker system set up
       near the registration table." No check flagged it. The claim is the negated fact in b57-direct.
   - **The user's decisions on those two bases and on the new flags**, logged before the regenerations they call
     for:
     - Raffle fact swapped on bases 12 and 57 as well, all their variants regenerated and the five checks rerun.
       Bases 27, 32, 42 and 52 keep the raffle. `FACT_OVERRIDES = {2: 0, 7: 0, 12: 0, 17: 0, 22: 0, 37: 0, 47: 0,
       57: 0}`, all "brought the first-aid kit": the first-aid kit is now the claim of 20 of the 60 bases and the
       raffle of 4. The swap changes the required sentences of both bases, so their requests are new without
       `review_problems`.
     - Accepted: the three new filler flags (base 17's Dev line, a premise role; base 17's Zeno line, which relates
       no one; base 22's fist bump, companionship for the planted pair), and the four earlier flags the reviewed
       report did not list: base 1 (a different attribute), base 3 (a weak hint), base 52 (a premise role).
       The fourth, base 12's, is covered by the swap.
   - **Result.** Both bases regenerated, and plant verification passed on all six documents. Neither needed the
     final attempt. Attempts: 12: 2 (the first draft left out the claim sentence and used "first-aid" elsewhere),
     57: 1. About $0.05 (14k tokens in 9 API calls). The previous corpus is kept as
     `corpus_before_raffle_swap.jsonl`, the previous check report as
     `corpus_confirm_report_before_raffle_swap.json`.
   - **The five checks on all 180 documents** (`data/consistency/corpus_confirm_report.json`):
     - same-attribute, superlative collisions and unplanted order cycles: none (234 order phrases; all 20
       planted order cycles recognized);
     - activity synonyms: only base 4's accepted "photo" sentence (3 variants), none on the regenerated bases;
     - leak-scan: 161 flags, 120 of them planted sentences, 41 filler. The unchanged documents' flags are
       identical to the previous scan. Base 12 has no filler flag now (its earlier one, the reaction sentence,
       went with the old draft). Base 57 lost its earlier premise-role flag ("Cleo walked
       the length of the beach with a clipboard, …") and has five new ones, on three sentences of an arrival
       sequence among the planted trio that follows the planted finishing order (Otto, Kira, Esme): "Otto
       arrived first, stretching his arms and greeting everyone with a wide grin." (3 variants), "Kira showed up
       a few minutes later, carrying a stack of mesh bags for collecting debris." and "Esme trailed in last, still
       tying her shoelaces as she jogged across the sand." (direct variant).
   - **Raised with the user before starting L1.** Base 57's arrival sequence above, and the same pattern in base
     12's new draft, which no check flagged: "Otto arrived first …", "Kai came in a few minutes later …", "Xavi
     trailed in shortly after …", following the planted age order (Otto, Kai, Xavi).
   - **The user's decision: keep both as cross-attribute filler**, consistent with base 33. The user's reason:
     the arrival order follows the consistent planted order, so it cannot create or remove a cycle even if the
     extractor merged the two attributes. Neither draft is changed.

21. **Minimal consistency engine (`XON_A1_MINIMAL_ENGINE.md`), added before the L1 run of record; report-only in
   L1.** The user's addendum, implemented as specified. It makes no API calls: it reads the claims, relations and
   entity relations A1 extracts for each document.
   - **Definition.** A document is inconsistent iff clause (a) direct or clause (c) entity fires, with A1's
     thresholds (confidence ≥ 0.5), claim-kind rules (asserted and premise claims; quoted claims excluded) and
     unscored-pair handling (an unscored pair has no relation, so it cannot fire clause (a)). Not computed:
     claim-graph balance, λ_min, clamped harmony, residuals, culprits, anchoring. `analyze_minimal(claims,
     relations, entity_spec)` in `xon/llm/minimal.py` returns a `MinimalReport`: the verdict, the clauses that
     fired, the direct pairs, the entity contradictions and the number of unscored pairs.
   - **Entity logic: one source of truth (the refactor route).** `entity_consistency.py` needed two changes to be
     standard-library only. The schema import moved under `TYPE_CHECKING`, since it was used in annotations only.
     `normalize_relation` copies a relation with pydantic's `model_copy` when it has one, as before, and with
     `dataclasses.replace` otherwise. A1's full engine and the minimal engine import the same functions. The
     verdict constants (`CONFIDENCE_MIN = 0.5`, `ASSERTING_KINDS`) moved into it from `consistency.py`, which
     imports them from there, so both engines read one definition. The full engine's code and outputs are
     otherwise unchanged.
   - **Clause (a)** is re-implemented without NumPy and reads the relations as `build_signed_graph` does: a pair
     is unordered, the first relation given for a pair is kept, and confidence is clipped to [0, 1] with NaN read
     as 0.
   - **Tests** (`tests/test_minimal_engine.py`, `tests/conftest.py`):
     - equivalence: while the A1 test modules run, every full-engine analysis is cross-checked against the
       minimal engine on the same inputs: 298 analyses in the existing A1 tests (unit fixtures, the scripted
       pipelines and the oracle run of the 12-document sample), plus 300 random documents with duplicate pairs
       and boundary, out-of-range, NaN and infinite confidences. The recorded-fixture half, the 12-document
       dry-run subset, replays `tests/fixtures/llm`; no fixtures are recorded yet, so it is skipped until they
       are;
     - hand-built cases: an order 3-cycle is flagged; a confident contradicts edge between asserted claims is
       flagged, and not when one claim is quoted; three `different` relations are flagged for a binary attribute
       only;
     - isolation: a fresh interpreter imports the module and runs it on plain dataclasses, loading nothing
       outside the standard library besides `xon.llm.minimal` and `xon.llm.entity_consistency` (no NumPy, SciPy,
       pydantic, V1 or `xon.llm.client`);
     - no API calls: it runs with the LLM client mocked to raise.
   - **In L1 (report-only).** Computed in the same run from the same analyses, seed 0: precision, recall and F1
     for direct and cycle variants, overall and per cycle type, next to the full engine's; localization on cycle
     variants (L1's rule, applied to the minimal engine's direct pairs and entity contradictions); the
     false-positive rate on consistent variants and on the three-value binary controls; every document where
     the two verdicts differ, with the clauses that fired in each. Also listed: any document whose minimal-engine
     clauses are not the full engine's (a) and (c), which equivalence rules out. The block is in `l1.json` under
     `minimal` and in the L1 section of `results.md`, labeled report-only. The full engine's L1 criteria, scores
     and verdict are unchanged.
   - **Section 4 of the addendum, recorded verbatim:**

     > **Prediction, stated in advance:** the two verdicts agree on at least 98% of the 180 documents, and every disagreement is a document where the full engine's clause (b) fired without clause (a) or (c). A disagreement of any other kind indicates a bug in one of the two implementations and must be investigated before the results are interpreted.
     >
     > **No pass/fail.** The minimal engine cannot pass or fail L1, and its numbers do not affect the full engine's L1 verdict.
     >
     > **Interpretation:**
     > - If the prediction holds, the write-up presents the minimal engine as the detection core, and justifies the energy layer by what needs a graded signal (A3, A4, C2), not by detection.
     > - If the full engine catches real contradictions the minimal one misses, clause (b) earns its place in detection, and the write-up says so, with the examples.

   - **Fixtures for the 12-document subset: the user's decision.** They are recorded during the L1 run of record,
     with `XON_LLM_RECORD=1`. Right after L1 finishes, before any result is interpreted, the equivalence test runs
     on the 12-document subset. If it fails, the minimal engine is fixed and only its report is recomputed, with no
     API calls, and the fix is logged here; the full engine's results are not rerun or changed.
     - **Confirmed before L1: the flag only writes fixture files.** It is read in one place,
       `LLM._record` (`xon/llm/client.py:316–326`), which runs after the response is cached and logged, both on
       an API call (lines 238–240) and on a cache hit (line 207). It changes neither the request, the key, the
       cache record nor the returned value. `request()` (161–173) and `request_hash()` (91–93) read no
       environment variable; elsewhere the flag's name appears only in an error message (302). An offline run
       of all 180 corpus texts (the tests' oracle client, temporary directories, no API key), once with the flag
       unset and once set, gave identical request bodies and hashes (1,981 calls), cache files (names and bytes),
       call logs (timestamps aside), usage, claims, relations, entity relations, reports and document rows. The
       only difference was 1,998 fixture files (4.7 MB), each equal to the cached record of its request (a
       request shared by two tags is cached once and recorded under each tag). A dry run replaying those
       fixtures reproduced every row, with no stale fixture. The real cache and `tests/fixtures/llm` were not
       touched. `test_recording_fixtures_changes_nothing_but_the_fixture_files` pins this on the sample.
     - **Resumed run:** cache hits are recorded (line 207), so a run resumed from the cache writes the same
       fixtures byte for byte (checked).
     - **Where and how many:** `tests/fixtures/llm/<tag>.json`, one file per tag:
       `text-<12 hex>-extract`, `-relate-NNN`, `-relate-rescore-A-B`, `-entities`, `-direct-thinking`,
       `-direct-no-thinking`, plus `-pairs` and `-seed1`/`-seed2` tags for documents above 25 claims. That is
       about 2,000 files for L1; the exact count depends on how many claims the model extracts.
     - **Failure modes:** a fixture that cannot be written raises an `OSError`, not an `LLMError`. The run then
       stops with a traceback (the script catches only `LLMError`, `scripts/run_consistency_eval.py:56–62`), after
       that call's response was cached and logged. A rerun resumes from the cache and records again. `_record`
       also raises an `LLMError` on an empty tag or on a tag reused for a different request in one session. No L1
       call has an empty tag, and the 180 texts have 180 distinct tag prefixes; the offline run had no collision.
     - **L1-var:** the flag is not needed. Its repeats get their own `-var<k>` tags, and nothing replays them
       (L1-var refuses a dry run). With the flag set, the run would rewrite the subset's L1 fixtures unchanged
       (checked) and add its own.
   - Not done: the optional UI toggle (Section 6).

22. **The L1 run of record: go-ahead, budget, and L1-var's saved responses** (the user's decisions, before L1).
   - **Go-ahead, as stated:** "Go ahead: run L1 and L1b on all 180 documents with recording on, run the subset
     equivalence test right after, then stop and report (L1-var waits for a separate go-ahead)."
   - **Budget: A1's cap goes from 10M to 15M tokens total.** The user's reason: "I don't expect it to be used, but
     I'd rather the integrity of the test not be compromised or interrupted." As before, the cap is enforced over
     all of A1's API calls: the run's `--budget` is 15,000,000 minus the A1 tokens already spent (input plus output
     tokens over the `source == "api"` entries of `cache/llm/log.jsonl`), recomputed right before the start. Spent
     before L1: 711,454 tokens (458 API calls), so `--budget 14288546`. At the table's Sonnet 5 prices the
     remaining 14.3M tokens could cost at most about $143 if every token were output; L1's estimate is unchanged
     (2.5M–8.2M tokens).
   - **L1-var: recording off; raw responses saved.** Fixtures come only from the L1 run of record. L1-var saves
     every response of all three repetitions, one file per call, to `l1var/` in its results folder
     (`results/a1-<date>-<time>/l1var/`), never to `tests/fixtures/`, so the variance analysis is reproducible.
     Each file holds the record the cache would hold (request hash, tag, model, kind, schema, output, usage,
     stop_reason) plus the document, the repetition and the call's position. Implemented before L1 and confined
     to the L1-var path: `run_l1var` takes a `raw_dir` (the script passes `<out>/l1var`), and
     `xon/llm/l1var_raw.py` saves each completed call from the point where a recording session would record it,
     on L1-var's session only. The cache bypass is unchanged. `scripts/recompute_l1var.py <folder>` recomputes the
     rows and scores from the folder with no API calls: the run of record's claims and pairs come from a temporary
     copy of the cache, each repeated request is answered by its saved response in call order, and a missing or
     unused response is an error. `test_l1var_saves_every_response_and_is_recomputed_from_them_alone` pins it
     with a fake client whose answers vary between calls: the recomputed `l1var.json` and rows equal the live ones.
     Nothing L1 or L1b runs was changed; the recording-invariance test and the engine tests pass unchanged.
   - **Pre-flight and start.** Full suite: 418 passed, 1 skipped (the recorded-subset test). The corpus is the
     reviewed 180 documents (sha256 `be518e5f280639c7263232e35ead42a3283809c15085fdee53c4ecf9e68cfd47`; plant
     verification flags only base 4's accepted "photo" sentence). `tests/fixtures/llm` did not exist. Started
     2026-09-24 14:20:56 (UTC−7): `python scripts/run_consistency_eval.py --budget 14288546`, with
     `XON_LLM_RECORD=1` for that process only; output in `results/a1-l1-run-of-record.log`.
   - **Interrupted by a connection error; not resumed.** After 2 h 4 min, the first call of document 49 of 180
     (`b16-consistent`, tag `text-a2e9c63c034d-extract`) failed after 900 s with `anthropic.APIConnectionError`
     ("An existing connection was forcibly closed by the remote host", WinError 10054). The client retries only
     rate-limit and overload errors, so the run stopped with exit code 1. Nothing was scored and no results folder
     was written. Documents 1–48 (bases 0–15) are complete. In the cache: 742 API calls and 64 cache hits, with
     no other error, no refusal, no truncation and no budget stop; 805 fixture files. The run spent 1,763,447
     tokens (976,059 input, 787,388 output; about $9.83), so A1 has spent 2,474,901 of the 15M cap. Whether to
     resume is the user's decision.
   - **Cause and decision.** The laptop went into sleep mode, which dropped the connection. The user's decision:
     "Yes, resume. Thought laptop was plugged in, it went into sleep mode. My mistake. Continue if the core
     integrity of the experiment is not affected." The resumed run is still the L1 run of record: documents 1–48
     are answered from the cache, as the first invocation got them.
   - **Integrity checks before resuming (all passed):**
     - no file under `xon/` or `scripts/` (prompts included) changed since the start; the config is in code
       (`xon/config.py` reads no file). The files changed since the start are this changelog and the user's
       edits to `XonTools_Vision.pdf`, `SPECS/XON_BUILD_OVERVIEW.txt` and five specs in `SPECS/ToDo/`, none of
       which the run reads;
     - the corpus sha256 is still `be518e5f280639c7263232e35ead42a3283809c15085fdee53c4ecf9e68cfd47`;
     - `cache/llm/log.jsonl` ends with a newline and every line parses (1,883 lines). The run logged 806
       entries: 742 API entries, 741 of them successful plus the failed extraction, and 64 cache hits. Every
       cache file parses and is named by its request (1,192 files, 741 written during the run, no `.tmp` left),
       and every successful API entry of the run has its cache file;
     - each of the 805 fixtures equals the cached record for its request; every tag the run logged has a
       fixture, and every fixture's tag was logged by the run;
     - the failed call (`text-a2e9c63c034d-extract`, request `02a2ddea67717fb0`) left no cache entry and no
       fixture.
   - **Automatic reruns (the user's rule).** If a call fails before any response arrives, the same command is
     rerun automatically, with no code change and the budget recomputed, up to 5 times in total, each logged
     here. Only `anthropic.APIConnectionError` (which includes `APITimeoutError`) or an `anthropic.APIStatusError`
     with a 5xx status qualifies. Any other failure stops the run for a report: any other exception, an
     `LLMError` (refusal, truncation, invalid output), `BudgetExceeded`, an `OSError`, a refusal to score over
     unscored pairs, or a sixth failure.
   - **Keeping the machine awake.** The launcher (`results/a1-l1-launcher.py`) calls
     `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` for as long as it runs and clears it at the
     end; the power settings are not touched. It starts the same command with `XON_LLM_RECORD=1` and
     `PYTHONIOENCODING=utf-8` for the child process only (the second so printing the results cannot fail on the
     console's encoding), appends its output to `results/a1-l1-run-of-record.log`, and applies the rerun rule.
   - **Resumed, then stopped by the rerun rule at a sixth failure; not resumed again.** The wake request was set.
     Times are UTC−7.
     - Resume, 17:11:53, `--budget 12525099`: documents 1–48 came from the cache (0 tokens). It died at 20:34:17,
       after 3 h 22 min, on the first relation batch of document 132 (`b43-cycle`, tag
       `text-477d137cc46f-seed2-relate-000`): `APIConnectionError` (WinError 10054, connection reset).
     - Automatic rerun 1, 20:35:17, `--budget 9320789`: died at 22:27:53, after 1 h 53 min, on document 178
       (`b59-consistent`, tag `text-0a3493794aa8-direct-thinking`, its last call): `APIConnectionError`
       (WinError 10054).
     - Automatic reruns 2–5, 22:28:53, 22:30:34, 22:31:46 and 22:32:58, each with `--budget 7548523`: each
       replayed documents 1–177 from the cache and died within 13 s on the same call with `APIConnectionError`
       caused by `getaddrinfo failed` (Errno 11001: the name `api.anthropic.com` could not be resolved, so the
       machine was offline). The fifth rerun's failure was the sixth failure, so the launcher stopped at
       22:33:10 and cleared the wake request. The name resolved again when checked afterwards.
     - State: documents 1–177 are complete; the last call of document 178 and documents 179–180 remain. Nothing
       was scored and no results folder was written. The run logged 7 failed calls, all `APIConnectionError`,
       none of which left a cache entry or a fixture. There were no other errors, refusals, truncations, budget
       stops or unscored-pair stops. 3,062 fixture files.
     - Spend across all the run's invocations: 6,740,023 tokens (3,708,039 input, 3,031,984 output; about
       $37.74). A1 has spent 7,451,477 of the 15M cap, so the next `--budget` would be 7,548,523.
   - **Resumed** 2026-09-24 17:11:53 (UTC−7) with `--budget 12525099`; documents 1–48 were answered from the cache.
   - **Automatic rerun 1 of 5.** At 20:34:16 the call tagged `text-477d137cc46f-seed2-relate-000` (request
     `85a1d98a73349d50`), a seed-2 relation call of document 132 of 180 (`b43-cycle`), failed after 6.6 s with
     `anthropic.APIConnectionError` (WinError 10054, the connection reset by the remote host; the machine was
     awake). No response arrived and no tokens were charged. The run had completed documents 1–131. The launcher
     reran the same command at 20:35:17 with `--budget 9320789` (15,000,000 minus the 5,679,211 A1 tokens spent
     by then); documents 1–131 and document 132's completed calls were answered from the cache.
   - **Automatic reruns 2–5, and the stop.** At 22:27:52 the call tagged `text-0a3493794aa8-direct-thinking`
     (request `68cd367e832fa1fc`), the thinking-on LLM-direct call of document 178 (`b59-consistent`, whose
     extraction, relation and entity calls had completed), failed after 90.4 s with `anthropic.APIConnectionError`
     (WinError 10054, the connection reset by the remote host). The run had completed documents 1–177. Reruns 2–5
     started at 22:28:53, 22:30:34, 22:31:46 and 22:32:58, each with `--budget 7548523`. Each answered the
     completed calls from the cache and failed on the same call within about 1.5 s with `getaddrinfo failed`
     (`httpx.ConnectError`, Errno 11001): the machine could not resolve the API's address, so no request left it.
     The sixth failure, at 22:33:10, stopped the launcher for a report, and the launcher cleared the keep-awake
     request. No failed call returned a response or was charged in the log. At 22:36, `api.anthropic.com` resolved
     again and a TCP connection to port 443 succeeded.
   - **State at the stop.** Remaining: document 178's two LLM-direct calls and every call of documents 179 and 180
     (base 59). Nothing is scored yet. The run so far: 2,842 API calls, 7 of them failed (the seven above);
     6,740,023 tokens (3,708,039 input, 3,031,984 output; about $37.74). A1 has spent 7,451,477 of the 15M cap.
     3,062 fixture files. Whether to resume is the user's decision.
   - **Resumed for base 59 (the user's decision: run the launcher again as it is), and finished.** Before the
     restart, the checks were repeated and passed:
     - no file under `xon/` or `scripts/` had changed since the start, and the launcher had not changed since
       17:11:29;
     - the corpus hash matched;
     - `cache/llm/log.jsonl` parsed (19,449 lines, ending with a newline);
     - the 3,286 cache files parsed and were named by their requests, with no `.tmp` file;
     - each of the 3,062 fixtures equaled its cached record.

     Restarted at 22:39:29 with `--budget 7548523`. Documents 1–177 and document 178's completed calls came from
     the cache, and all 180 documents were complete at 22:45:25. The run of record in total: 2,878 API calls, 7 of
     them failed with no response; 6,827,298 tokens (3,754,804 input, 3,072,494 output; about $38.23). A1 has spent
     7,538,752 of the 15M cap. 3,102 fixture files.
   - **The subset equivalence test (the user's post-L1 step): passed.** It ran right after the calls finished,
     before any result was read. `test_the_two_engines_agree_on_the_recorded_subset` replayed the 12-document
     subset from the recorded fixtures (not skipped): no clause mismatch, and every disagreement of the predicted
     kind.
   - **The script then failed while writing the results: a bug; no result read, nothing fixed yet.** After
     scoring, `json.dumps` raised `TypeError: Object of type bool is not JSON serializable` on `l1b.json`
     (`checks` → `auc`). `auc()` receives NumPy harmony values and so returns a NumPy float; comparing it with the
     threshold gives a NumPy boolean, which the JSON encoder rejects. The tests did not catch it. Written before
     the failure, in `results/a1-20260924-223930/`: `documents.jsonl`, `analyses/` and `l1.json`. Not written:
     `l1b.json`, `run.json`, `results.md`. The launcher stopped for a report, since the rerun rule does not cover
     this failure. A fix is a code change after the run started, so it waits for the user's decision.
   - **The JSON bug fixed after the run (the user's decision: the writer-level fix).**
     - `scripts/run_consistency_eval.py` now writes every JSON file through `_json`, whose `default` turns a
       NumPy scalar into its Python value (`.item()`). `scripts/recompute_l1var.py` does the same, so a
       recomputed `l1var.json` still equals the live one.
     - The encoder calls a `default` only for values it cannot write, so every file that was already writable
       comes out byte for byte the same. No score, threshold or library code changed; `xon/` is untouched.
     - `test_the_eval_cli_writes_scores_computed_from_numpy_values` feeds NumPy harmony and conflict values
       through the real `score_l1b` and the script, as in the run of record. Without the fix it fails with the
       run's `TypeError`. The tests had missed the bug because the oracle sample's AUC is None, which
       short-circuits the checks to plain booleans.
     - Full suite: 420 passed; the recorded-subset test now runs.
   - **Results recomputed from the cache.** At 23:23:24 the same command ran with `--budget 0`, with the API key set
     and recording off; a zero budget refuses any call before it reaches the API. All 3,102 calls came from the
     cache (0 API calls, 0 tokens), and `run.json` has `of_record: true`. Output: `results/a1-20260924-232324/`.
     Its `documents.jsonl` and `l1.json` are byte-identical to the ones the run wrote before the failure. Its 180
     analyses match too, apart from `report.llm_usage`, the session's usage counters each analysis snapshots
     (the budget, and the live calls of the final invocation). The partial folder `results/a1-20260924-223930/`
     is kept as written.
   - **Result of the run of record (reported as it came out).**
     - **L1: PASS.** Engine: direct F1 0.916, cycle F1 0.916 (order_cycle 0.909, equality_break 0.909,
       binary_parity 0.930), localization 1.000; precision 0.845 and recall 1.000 on both, false-positive rate
       0.183 on consistent variants. Expected but not judged:
       - direct F1 ≥ 0.85 for every method holds except LLM-direct without thinking (0.805);
       - pairwise cycle F1 is below 0.5 (0.329).

       LLM-direct with thinking: direct and cycle F1 0.930, false-positive rate 0.150.
     - **L1b: PASS.** AUC of 1 − H 0.926, against 0.528 for the conflict score; premise among the top-3 residual
       claims 0.933 (30 documents). Documents with unanchored components: 0.342.
     - **Minimal engine (report-only): the prediction held.** The verdicts agree on 179 of 180 documents (0.994).
       The one disagreement, `b54-consistent`, is flagged by the full engine's clause (b) alone, a false positive
       on a consistent variant. Minimal engine: direct and cycle F1 0.923, false-positive rate 0.167.
23. **After L1: L1-var, a post-hoc analysis, and the minimal engine's spec** (the user's go-ahead and requests,
   2026-09-24, after the L1 report).
   - **L1-var: the run.**
     - Command: `python -u scripts/run_consistency_eval.py --l1var --budget 7461248` (the 15M cap minus A1's
       spend), with recording off and the machine kept awake. Started 23:33:05; finished at 00:20:35 with exit 0,
       after 2,850 s.
     - The 12 subset documents' run-of-record analyses came from the cache (0 tokens).
     - 345 API calls, none failed: 796,645 tokens (466,299 input, 330,346 output), about $4.24. A1 has spent
       8,335,397 of the 15M cap.
     - Output: `results/a1-20260924-233306/`. The raw responses are in its `l1var/` (345 files), and no fixture
       was written (still 3,102).
   - **L1-var: recomputed from its saved responses alone.** `python scripts/recompute_l1var.py
     results/a1-20260924-233306/l1var` made no API calls. Its `l1var.json` and `l1var_repeats.jsonl`, in
     `l1var_recomputed/`, are byte-identical to the live ones.
   - **L1-var: result (reported as it came out; no pass or fail).**
     - 12 documents × 3 repeats with the cache bypassed, on the claims and pairs of the run of record.
     - Relation agreement: 0.933 over 1,468 pairs.
     - Entity-relation agreement: 0.518 over 112 relations.
     - Documents whose verdict changes across the repeats: engine 0.167, pairwise only 0.167, LLM-direct with and
       without thinking 0.000.
   - **L1-var: what changed (an observation from the saved responses).**
     - The engine's two changes are consistent documents flagged in one repeat:
       - b01-consistent, repeat 2: clause (a), on "The forecast predicted a dry spell." / "Everyone agreed the
         garden was in good shape for the coming months.", contradicts 0.5;
       - b02-consistent, repeat 3: clause (c). The extraction gives "Dara arrived first." as vik later than dara
         (0.6) and "Vik showed up shortly after Dara." as dara later than vik (0.9), an order 2-cycle on
         `arrival_time`. It is the same mixed-direction error as b31 in the run of record.
     - The pairwise baseline's two changes: b01-consistent, repeat 2 (the same edge), and b01-cycle, repeat 3,
       where two planted-cycle pairs are labeled contradicts 0.55 with rationales that cite the third planted
       claim ("from other claims", "per claim 10").
     - The engine's verdict on the 8 direct and cycle documents is the same in every repeat.
     - Of the 54 entity relations missing from at least one repeat, 32 are direction flips: the same claim and
       entities with the opposite `greater` direction. A repeat that flips every relation of an attribute (as in
       b00-consistent's third) leaves the verdict unchanged; a repeat that mixes directions within an attribute
       can close a cycle. Of the other 22, 12 differ in entity ids, 6 are relations a repeat didn't extract, and
       4 differ otherwise.
   - **Post-hoc analysis of the run of record (an analysis, not a re-specification).**
     - It reran nothing, made no API calls, and changed nothing in `results/a1-20260924-232324/` or in any
       criterion.
     - Report: `results/a1-l1-posthoc.md`. Its facts come from `results/a1-l1-posthoc.py`, which reads only the
       run's files and `cache/llm/log.jsonl`; its output is `results/a1-l1-posthoc-facts.txt`. The
       classifications are judgments made by reading each document.
     - **The full engine's 11 false positives on consistent documents:**
       - 10 are relation-judge errors, of which 3 are borderline (b28, b33, b56): mild descriptive tensions, not
         contradictions of the planted kind;
       - 1 is an entity-extraction error (b31): "Kira signed first" and "Otto signed after Kira" were normalized in
         opposite directions on `signup_order`;
       - 0 are unplanted contradictions.

       All 10 `contradicts` edges behind the clause (a) flags have confidence 0.50–0.60. b54, the minimal engine's
       one disagreement, is a clause (b) cycle through a quoted claim, which clause (a) excludes.
     - **The 3 false positives on the binary three-value controls** (b26, b32, b56) all come from the relation judge,
       none from the entity clause. The arity was read as `multi` on all 20 controls.
     - **Cost per document**, at $2 and $10 per million input and output tokens:
       - engine $0.1376 on average (median $0.1007);
       - pairwise only $0.1266;
       - LLM-direct with thinking $0.0057;
       - LLM-direct without thinking $0.0034.

       Pairing seeds 1 and 2 add $0.1143 per sampled document. The figures reconcile to the run's $38.235; the
       per-document sum is $0.052 higher, the cost of four relation batches that were identical between two
       variants of the same base, paid once, and counted here for both documents.
     - **Equality-break contamination (8 pairs):**
       - Every pair is "A same as B" against "A not same as C". Every rationale reasons through the third planted
         claim, "B same as C", although the relate prompt tells the judge to ignore every other statement in the
         list.
       - Five are at confidence 0.5 or more. They fire clause (a) in their documents and account for 5 of the
         pairwise baseline's 6 equality-break detections.
       - The engine's verdict on all eight documents rests on the entity clause as well.
     - **Observed along the way:** the pair "Milo was the first to walk in." / "Mina was already seated …" in base
       25's shared text was labeled unrelated in b25-consistent, contradicts 0.6 in b25-cycle, and contradicts 0.5
       in b25-direct.
   - **The minimal engine's spec: acceptance checklist met, moved from `SPECS/ToDo/` to `SPECS/Implemented/`**
     (the user's instruction: move it if every item is met). The file is now
     `SPECS/Implemented/XON_A1_MINIMAL_ENGINE.md`; nothing referred to its old path. The checklist, item by item:
     1. `xon/llm/minimal.py` exists and imports only `math`, `dataclasses` and `entity_consistency`, which imports
        only `re`, `collections`, `dataclasses` and `typing`. The isolation test passes.
     2. The equivalence tests pass: the cross-check of every full-engine analysis in the A1 tests, 300 random
        documents, and the recorded 12-document subset, which now runs instead of skipping. The hand-built tests
        pass. The full suite passes with the slow tests: 420 passed.
     3. L1's report has the minimal engine's report-only block, with its numbers and the list of disagreements.
     4. Re-specification 21 was logged before the run of record, with Section 4's prediction verbatim.

     The optional UI toggle (Section 6) was not built; it is not on the checklist.
24. **The A1 spec's acceptance checklist (§9): the launcher's key handling removed, and the live paragraph checks
   run** (the user's decisions, 2026-09-25).
   - **Audit.** Asked whether `XON_A1_CONSISTENCY.md` is fully implemented, 7 of the 9 checklist items were met.
     - Items 2 and 3, the paragraph checks "with a key set", had passed only as offline tests with scripted
       responses. Neither paragraph appeared in the call log or the fixtures.
     - Item 8 failed on `results/a1-l1-launcher.py`. It read the key from the environment, or else from the
       Windows registry, and passed it to the run.
     - Item 1 was checked directly. With no key and an empty temporary cache, L1 and L1b ran on the 12-document
       subset from the shipped fixtures: 209 fixture hits, 0 API calls. The temporary cache and output were
       deleted.
     - The full suite passed: 420 tests, including V1–V1.2.
   - **The launcher no longer handles the key (the user's decision).** The registry read and the key lookup are
     removed; the child process inherits the caller's environment. The rerun rule, the budget computation and the
     recording flag are unchanged from the run of record. Outside `SPECS/` and `cache/`, the variable's name now
     appears only in `xon/llm/client.py` (the environment read) and `README.md`. The call log was checked too:
     26,207 entries, with no prompt text and no key.
   - **The live paragraph checks (the user's decision: recording off).**
     - Script: `results/a1-acceptance-live.py`, which runs the paragraphs through `analyze_text` as the
       Consistency view does, with world knowledge off. Output: `results/a1-acceptance-live.txt`.
     - 9 API calls, none failed: 12,958 tokens (10,535 input, 2,423 output), about $0.045. A1 has spent 8,348,355
       of the 15M cap. No fixture was written (still 3,102).
     - **Item 2: met.** "Ana is older than Ben. Ben is older than Cy. Cy is older than Ana." gives three asserted
       claims and `age` relations greater(ana, ben), greater(ben, cy), greater(cy, ana), each at 0.98. The verdict
       is inconsistent with clause `entity` alone: an order cycle on `age` through claims 0, 1 and 2. The pairwise
       baseline reports nothing; the judge labeled all three pairs unrelated (0.55–0.6).
     - **Item 3: met.** After "There were three teams." the attribute is `multi` and the paragraph is not
       flagged. After "There were two teams." it is `binary`, and the paragraph is flagged by clause `entity`: a
       binary-parity cycle on `team` through claims 1, 2 and 3. The pairwise baseline reports nothing in either
       case.
   - **Also fixed:** `results/a1-l1-posthoc.py` hardcoded the model name, although §0 keeps model strings in
     `config.py`. It now reads the model from the run's `run.json`, and its output is byte-identical.
   - **Status:** all nine checklist items are met. The user confirmed the spec is implemented, and it was moved from
     `SPECS/ToDo/` to `SPECS/Implemented/XON_A1_CONSISTENCY.md`; nothing referred to its old path.
25. **The repository's first commit, after the run of record** (the user's request and decisions, 2026-09-25).
   - **Everything above predates the repository.** The project was first committed to git on 2026-09-25, after the
     L1 run of record (item 22), L1-var, the post-hoc analysis and the minimal engine's spec move (item 23), and
     the checklist audit and live paragraph checks (item 24). The snapshot is commit
     `1b1749b4afcea1106c439306bcc8600b44095263`, tagged `a1-run-of-record`. Git history does not prove the code's
     state during the run; that rests on this changelog, the cache replay and the recorded hashes.
   - **The snapshot holds the launcher as it ran.** Item 24's launcher edit was made before the first commit and
     reversed for the snapshot. The reversed file is byte-identical to the launcher as created before the run
     (4,332 bytes, SHA-256 `4d4377556b34c2fbcea87e00690040ce0463081a36acdb90a4b8d566cae7e0d7`). Its creation is
     recorded in the Cursor agent transcript of the session that wrote it, outside the repository. Nothing edited
     it between its creation and the run, and the checks before the 22:39 restart found it unchanged since
     17:11:29 (item 22). The snapshot's item 24 and `SPECS/` match its tree: item 24 read "8 of the 9 checklist
     items are met", and `XON_A1_CONSISTENCY.md` was in `SPECS/ToDo/`.
   - **This commit** re-applies the launcher edit, so the key is left to the environment, with no registry read
     and no mention of the key's variable. The reason is checklist item 8, which allows the variable only in the
     environment read and the README. The original launcher is preserved in the snapshot commit. Item 24's text
     is restored as it was before the snapshot, the spec is moved back to
     `SPECS/Implemented/XON_A1_CONSISTENCY.md`, and the README's status names items 24 and 25.
   - **What is committed:** everything except Python bytecode, the pytest cache, `xon_sim.egg-info/`, virtual
     environments, `.env` files, `.streamlit/secrets.toml`, and IDE and OS files (of `.cursor/`, only `rules/` is
     kept). `cache/llm/` is committed (the user's decision): the call log, from which the budget total and the
     post-hoc costs are computed, and the cached responses, which the L1-var recompute replays. `.gitattributes`
     holds `* -text`, so git stores every file byte for byte; each of the snapshot's 7,654 files was checked to be
     stored with exactly its bytes on disk.
   - **Secret scan** of every file before the first commit: no credentials. The only key-like strings are the
     README's placeholders and a 36-character dummy key in `tests/test_llm_client.py`.
   - **Tests** before this commit: the full suite passed, slow tests included (420 tests).
   - **Remote:** the private repository `https://github.com/IboTool/XonTools`. Both commits and the tag are pushed
     together.
   - **Standing rules from now on (the user's):** commit at the end of each logged step, with a message naming the
     step; tag every freeze and every run of record; never commit secrets; never rewrite pushed history (no
     force-push, no rebase of pushed commits).

---

## 2026-09-23 — E9c re-registrations 2 and 3: exact construction check (code 1.2.2)

Both are the user's decisions, made after the run of re-registration 1 (the next entry). Re-registration 3 is
written into `REGISTRY_V1_2`, this entry and `docs/geometry_closed_forms.md` before any run of it.

### Re-registration 2 (superseded before it was implemented)

- **Reason (the user's words).** "Estimator choice was made after seeing results, so neither estimator can be
  the pass criterion."
- **Criterion.** For each geometry, over the last three construction levels,
  log(N_{n+1}/N_n) / log(D_{n+1}/D_n) within 0.02 of the theoretical d_f, with N counting cells (vertices
  reported too) and D the graph diameter, and the ratios converging toward it with level. Box-counting and
  mass-radius reported only.
- **Why it never ran.** Before implementing it I reported that "the last three construction levels" had
  several readings, and that under one of them (three ratios up to 400,000 vertices) S(4, n) would fail
  whatever the construction: its textbook diameter 2^(L+1) − 1 makes its ratio 1.977 at level 6. The user
  replaced it with re-registration 3. It was never run, so there is no protocol to preserve.

### Re-registration 3 (the current E9c)

- **Reason (the user's words).** "The rev. 2 criterion ignored known additive offsets in diameter (S(4, n)'s
  first ratio is 1.977 because D = 2^(L+1) − 1); the level choice was ambiguous and is resolved here on
  principle, not by outcome."
- **Old criteria.** Re-registration 1 (uniform-center mass-radius and box-counting d_f, both judged) is
  preserved as `E9c_v2` and the first registration as `E9c_v1`. Both run with `--include-v1`.
- **New criterion.** A geometry matches when both parts hold, and E9c passes when all four predicted geometries
  match:
  1. **Exact counts.** At every level built up to the 400,000-vertex limit, the vertex count, the edge count
     (distinct vertex pairs joined by an edge) and the exact graph diameter equal the closed forms in
     `docs/geometry_closed_forms.md`. Integer equality, no tolerance.
     - Levels: gasket 0–11, Vicsek 0–7, S(4, n) 0–8, carpet 0–6.
     - The gasket and S(4, n) forms are published. The Vicsek and carpet forms were derived by hand from the
       construction rules in `XON_SIM_GEOMETRY_V1_2.md`.
     - The gasket was not named in the user's instruction. It is one of E9c's four geometries, so it is
       checked against its published forms.
  2. **d_w, d_s and the Einstein residual** (the user chose to keep these judged), as in the first
     registration:
     - At the largest level with N ≤ 50,000: gasket 9, Vicsek 6, S(4, n) 6, carpet 5.
     - Tolerances: d_w and d_s within 0.10 of the reference (gasket, Vicsek) or 0.15 (carpet); S(4, n) has
       no reference for them.
     - The residual |d_s − 2 d_f / d_w| must be at most 0.10 (gasket, Vicsek) or 0.15 (carpet, S(4, n)). It
       uses the theoretical d_f (ln 3/ln 2, ln 5/ln 3, ln 4/ln 2, ln 8/ln 3), which the exact counts certify.
     - A geometry that misses on this part is rerun once at the next level (N ≤ 400,000) and judged there.
       The exact counts have no retry.
- **Reported, not judged.**
  - The ratio ln(N_{L+1}/N_L) / ln(D_{L+1}/D_L) at every level, counting vertices and counting cells.
  - Box-counting d_f, which is that vertex ratio at the E9c level.
  - Mass-radius d_f at the E9c level, with uniform centers (`E9c_v2`'s estimator) and deep centers (`E9c_v1`'s).
  - Vicsek's mass-radius trend: d_f at levels 4–7, with 200 deep centers and with 200 uniform centers per
    level. The deep ones are the kind that gave the post-hoc 1.613, with more centers to cut sampling noise.
- **The exact diameter.** The search uses eccentricity bounds (Takes and Kosters 2011): a BFS from v bounds
  every w by max(d(v, w), ecc(v) − d(v, w)) ≤ ecc(w) ≤ ecc(v) + d(v, w).
  - It stops only when no vertex can exceed the largest eccentricity found, so the result is exact; there is
    no cap.
  - Vertices that a verified automorphism maps onto each other share one eccentricity:
    - the letter permutations of S(p, n);
    - the triangle's and the square's symmetries of the other layouts.
  - Each candidate map is kept only if it maps the edge set onto itself.
- **Known before registering.**
  - The published forms predict the gasket and S(4, n) exactly. Their double-sweep diameters (lower bounds)
    equal those forms at every level tried, and exact diameters were certified on gasket levels 5–9 and
    S(4, n) levels 3–5 while choosing the algorithm.
  - Vicsek's and the carpet's double-sweep diameters at levels 6–7 and 5–6 were measured in earlier runs (730,
    2,188; 486, 1,458) and fit the derived forms. Their exact diameters had not been computed.
  - The builder's vertex-count predictions contain the Vicsek and carpet vertex recurrences, and I had read
    them. The edge and diameter forms appear nowhere in the code.
  - d_w and d_s at the E9c levels were measured in every earlier run, and they pass these tolerances. So do
    the residuals with the theoretical d_f, computed from the last run's d_w and d_s: gasket 0.021, Vicsek
    0.020, S(4, n) 0.073, carpet 0.006.
  - The outcome is therefore largely predictable. What the check adds is exactness: the edge counts and the
    exact diameters of every level.
- **Random streams.** d_w, d_s and the E9c-level mass-radius estimates use each geometry's stream exactly as
  in `E9c_v2`, so they reproduce its numbers at the same level. Vicsek's trend uses one stream per level and
  estimator.

### Result of re-registration 3 (seed 0): PASS

`python -m xon.run_tests --include-v1 --include-controls`, `results/20260923-154748_0/`, exit code 1: E3, E4
and E9a fail, as before. Every number outside E9c is unchanged. `E9c_v2` reproduces re-registration 1's run
exactly, and `E9c_v1` the first V1.2 run.

**Exact counts: all equal.** The vertex count, edge count and exact diameter equal the closed forms at every
level (gasket 0–11, Vicsek 0–7, S(4, n) 0–8, carpet 0–6). At the top levels:

| Geometry | Top level | Vertices | Edges | Diameter |
|---|---|---|---|---|
| gasket | 11 | 265,722 | 531,441 | 2,048 |
| Vicsek | 7 | 156,252 | 234,376 | 2,188 |
| S(4, n) | 8 | 262,144 | 524,286 | 511 |
| carpet | 6 | 330,720 | 630,312 | 1,458 |

**d_w, d_s and the residual with the theoretical d_f: all pass at the E9c level, with no retry.**

| Geometry | E9c level (N) | d_w | d_s | Residual (theoretical d_f) |
|---|---|---|---|---|
| gasket | 9 (29,526) | 2.310 | 1.352 | 0.021 |
| Vicsek | 6 (31,252) | 2.511 | 1.146 | 0.020 |
| S(4, n) | 6 (16,384) | 2.495 | 1.530 | 0.073 |
| carpet | 5 (41,584) | 2.154 | 1.763 | 0.006 |

**Reported: the ratio sequences converge to the theoretical d_f.** Counting vertices, from level 1 up:
- gasket: 1.000, 1.322, 1.485, 1.550, 1.573, 1.581, 1.5836, 1.5845, 1.5848, 1.5849, 1.5849, against
  ln 3/ln 2 = 1.5850;
- Vicsek: 1.585, 1.600, 1.533, 1.492, 1.475, 1.468, 1.4661, against ln 5/ln 3 = 1.4650, approaching from above
  after level 2;
- S(4, n): 1.262, 1.636, 1.819, 1.910, 1.955, 1.977, 1.989, 1.9944, against 2;
- carpet: 1.262, 1.631, 1.793, 1.855, 1.879, 1.8874, against ln 8/ln 3 = 1.8928.

Counting cells, the gasket and the carpet give ln 3/ln 2 and ln 8/ln 3 exactly at every level, because their
diameters double and triple exactly. S(4, n)'s cell ratio equals its vertex ratio (a quarter as many cells as
vertices). Vicsek's falls from 2.322 at level 1 to 1.4662 at level 7. Box-counting at the E9c level, which is
that level's vertex ratio, gives gasket 1.585, Vicsek 1.468, S(4, n) 1.977 and carpet 1.879.

**Reported: mass-radius.** At the E9c level, with uniform / deep centers: gasket 1.601 / 1.585, Vicsek
1.740 / 1.679, S(4, n) 1.976 / 1.981, carpet 1.734 / 1.852. These are `E9c_v2`'s and `E9c_v1`'s numbers at the
same levels.

**Reported: Vicsek's mass-radius trend does not approach 1.465.**

| Level (N) | R_max | d_f, deep centers | d_f, uniform centers |
|---|---|---|---|
| 4 (1,252) | 34 | 1.652 (156 centers: all that were deep enough) | 1.726 |
| 5 (6,252) | 105 | 1.640 | 1.738 |
| 6 (31,252) | 314 | 1.657 | 1.717 |
| 7 (156,252) | 944 | 1.669 | 1.710 |

With re-registration 2 the user gave a rule for this trend. A trend toward 1.465 would mark the excess as a
finite-size or log-periodic effect of the estimator. No trend would mean investigating the construction before
trusting Vicsek. The exact check is that investigation, and Vicsek's vertex counts, edge counts and exact
diameters equal the closed forms at every level. So the construction is right, and the registered mass-radius
estimator does not measure Vicsek's d_f at these sizes.

A possible reason, not tested: R_max is 0.41–0.43 of the diameter at every level, so the fit window
[R_max / 4, R_max] always covers the same part of the self-similar structure around the central cross. A
log-periodic bias tied to that window would not shrink with level.

**Implementation choices made after the registration.** They are not in the registration text, and none
changes a verdict:
- The symmetry candidates are two generators per geometry: a transposition and a p-cycle of the letters for
  S(p, n), and a rotation and a reflection of the triangle or the square otherwise. Both were verified as
  automorphisms at every level.
- E9c's box-counting d_f uses the exact diameters. These equal the double-sweep diameters at every level here,
  so its numbers equal `E9c_v2`'s.
- Geometry Compare checks the exact counts at the matched level and the one below. Its verdicts are indicative
  only.

**When the counts were first seen.** The exact counts on all four geometries were first seen while timing the
implementation. That was after this entry, the registry entry and the closed-forms document were written, and
before this run, which reproduces them.

**Runtime.** E9c took 80 s, about 25 s of it on the exact counts. S(4, n) level 8 is the slowest step: 13 s for
242 full BFS and 268 eccentricity-only BFS over its 11,051 symmetry orbits. `E9c_v2` took 279 s and `E9c_v1`
122 s.

### Added after the result: the symmetry-based diameter against brute force

Until now, the unit test compared the symmetry-based exact diameter with brute force (BFS from every vertex)
only on the gasket at levels 1 and 4, the carpet at levels 1 and 2, and Vicsek and S(4, n) at level 1. At those
sizes the eccentricity-only phase runs at most once, yet it did about half the work on S(4, n) level 8 (268 of
510 BFS runs).

- **The check was run once before it was added, and it passed.** A one-off script compared the two diameters
  at every level up to about 7,000 vertices: gasket 0–7, Vicsek 0–5, S(4, n) 0–5 and carpet 0–4, 25 levels in
  all. It used E9c's code path: both symmetry generators verified, then the exact diameter over the orbits. The
  diameters were equal at every level. This includes S(4, n) levels 2–5, where the eccentricity-only phase ran
  4 to 37 times.
- **The tests added** (`tests/test_geometry_metrics.py`):
  - `test_symmetry_diameter_equals_brute_force` runs in the default run, at every level up to 2,000 vertices
    (21 levels).
  - `test_symmetry_diameter_equals_brute_force_slow` is the one-off comparison, up to 7,000 vertices. It is
    marked `slow`, left out of the default run, and runs with `pytest -m slow` (11 s).
- **No experiment code changed.** The code version stays 1.2.2 and no result changes.

---

## 2026-09-23 — E9c re-registered (code 1.2.1)

The user's decision after the first V1.2 run. The Vicsek diagnosis (in the V1.2 section below) came with three
options: keep the estimator, judge d_f with uniformly drawn centers, or judge d_f by box-counting. The user chose
both of the last two. The new criterion was written into `REGISTRY_V1_2` and this entry before any run of it.
E9a is unchanged; the user did not choose to re-register it.

- **Old criterion (now `E9c_v1`, runnable with `--include-v1`).** d_f from the mass-radius relation, with 30
  centers drawn from the vertices at least R_max hops from the outer boundary. d_f, d_w and d_s within their
  tolerances, and the Einstein residual with that d_f under its threshold.
- **New criterion.** d_f is measured two ways, and both are judged against the same reference and tolerance:
  1. mass-radius with 200 centers drawn uniformly from all vertices. At each r, M(r) averages the centers at
     least r hops from the outer boundary, so every ball counted is still a ball of the unbounded geometry.
     R_max (the boundary distance reached by 10% of the vertices) and the fit range [R_max / 4, R_max] are
     unchanged;
  2. box-counting across levels, ln(N_L / N_{L−1}) / ln(diam_L / diam_{L−1}): the `d_f_box` column, reported
     since the first run.

  The Einstein residual must hold with each estimate, under the old thresholds. d_w, d_s, the tolerances, the
  levels and the retry rule are unchanged. The first registration's d_f is reported as `d_f (E9c_v1)`.
- **Reason.** The first registration's centers all sit around Vicsek's central cross. Its mass-radius d_f came
  out 1.679 and 1.675, where box-counting on the same graphs gives 1.466 against the reference 1.465.
- **Known before registering.**
  - The box-counting half was already visible in the first run's report: gasket 1.585, Vicsek 1.466,
    S(4, n) 1.977, carpet 1.879. Its residuals follow from the reported d_w and d_s (Vicsek 0.036).
  - The uniform-center estimator had been tried on Vicsek level 6 only, in the diagnosis: about 1.46, over
    slightly different fit ranges.
  - It had not been run on the gasket, the carpet or S(4, n).
- **Checked on the lattice only.** On square lattices the two estimators agree exactly, because every interior
  ball is the same: 1.953 at N = 14,641 and 1.986 at N = 160,801. About 20 of the 200 uniform centers reach
  R_max, and the estimate takes 0.8 s at 160,801 vertices.
- **Random streams.** Each geometry's stream still drives the first registration's estimators in their
  original order, so `E9c_v1` reproduces the first V1.2 run. The uniform centers come from a separate stream per
  geometry.

### Result of the re-registered E9c (seed 0): FAIL, on Vicsek and the carpet

`python -m xon.run_tests --include-v1 --include-controls`, `results/20260923-143928_0/`, exit code 1. Every
number outside E9c is unchanged, and `E9c_v1` reproduces the first run exactly (FAIL on Vicsek).

| Geometry | Level (N) | d_f (mass, uniform) | d_f (box) | d_w | d_s | Residual (mass) | Residual (box) | E9c |
|---|---|---|---|---|---|---|---|---|
| gasket | 9 (29,526) | 1.601 | 1.585 | 2.310 | 1.352 | 0.035 | 0.021 | match |
| Vicsek | 7 (156,252), after 6 | 1.736 (level 6: 1.740) | 1.466 | 2.494 | 1.140 | 0.252 | 0.036 | MISMATCH |
| S(4, n) | 6 (16,384) | 1.976 | 1.977 | 2.495 | 1.530 | 0.054 | 0.055 | match |
| carpet | 6 (330,720), after 5 | 1.769 (level 5: 1.734) | 1.887 | 2.152 | 1.798 | 0.154 | 0.044 | MISMATCH |

Box-counting and its residual pass on all four geometries. The uniform-center mass-radius estimate fails on
Vicsek (too high) and on the carpet (too low, where the first registration's estimate, 1.852, had passed). By
§5.2 both constructions are flagged, and the E9 report marks their E9a and E9b as not interpretable. The
verdict stands.

Diagnosis, after the run (scripts outside the suite, on random draws of 200 centers, not E9c's own):
- **The registered averaging mixes position with radius.** At each r only the centers whose ball fits
  contribute, so as r grows the average shifts toward the deepest vertices. The mean boundary distance of the
  contributing centers rises from 221 to 332 over Vicsek's fit range (level 6). Deep vertices differ from
  typical ones:
  - on Vicsek they surround the central cross, with 9% more mass at the bottom of the fit range, so M(r)
    grows too fast;
  - on the carpet they line the central hole, with 15% less mass, so M(r) grows too slowly.
- **Holding the centers fixed removes the shift.** Using only the centers that fit at R_max:
  - Vicsek level 6: 1.613, against 1.739 with the shifting population;
  - carpet level 5: 1.869, against 1.769;
  - gasket level 9: 1.591, against 1.604 (there deep and typical vertices differ by 2%).
  Vicsek's 1.613 is still far above 1.465: its fixed centers all sit around the central cross, like the first
  registration's deep centers.
- **Why the earlier diagnosis read about 1.46.** It averaged the same way (200 uniform centers, at least 20
  contributing at each r), but fitted Vicsek level 6 over [27, 243] and [9, 243]: 1.463 and 1.452. Its own
  [30, 270] fit gave 1.534. The registered fit runs to R_max = 314, where 20 of the 200 centers still
  contribute. On the same centers, changing only the fit range: [27, 314] gives 1.588, [79, 314] 1.733, and
  the at-least-20 rule changes nothing. The entry above called those fit ranges "slightly different"; the
  upper end of the fit was the difference, and the diagnosis already showed the estimate climbing with it.

E9c took 277 s, against 119 s before: the carpet's retry at level 6 has 330,720 vertices.

---

## 2026-09-23 — V1.2 (`XON_SIM_GEOMETRY_V1_2.md`)

New geometries (`carpet`, `vicsek`, `sierpinski_p`), geometry metrics and the E9 predictions. Registered before
the first run, with the spec's thresholds:

- **E9a — Spectral self-similarity across geometries.** At the level with 500 ≤ N ≤ 3000: gasket, Vicsek and
  S(4, n) (finitely ramified) have `degenerate_fraction` ≥ 0.5 **and** `plateau_persistence`(L−1, L) ≥ 0.8;
  carpet (infinitely ramified) and lattice (control) have `degenerate_fraction` ≤ 0.3. Pearson r across levels
  L−2, L−1, L is reported only.
- **E9b — Spectral individuation across geometries.** Same levels. k-way spectral clustering (k = top-level
  sub-regions) on the lowest k eigenvectors including the constant, k-means with 20 restarts, purity by best
  matching: purity ≥ 0.85 for gasket, Vicsek, S(4, n) and tree (control); carpet exploratory. `seam_fraction`
  and the seam-vs-purity relation are reported.
- **E9c — Known dimensions (construction test).** Largest level with N ≤ 50,000. Gasket and Vicsek: d_f, d_w,
  d_s each within 0.10 of the reference, `einstein_residual` ≤ 0.10. Carpet: d_f within 0.10, d_w and d_s within
  0.15, residual ≤ 0.15. S(4, n): d_f within 0.10 of ln 4 / ln 2, residual ≤ 0.15. A failing geometry is rerun
  once at the next level; failing again flags its construction.
- **E9d — not implemented.** Skipped at the user's request: no registration, no code, no UI. The E9 report
  header says so.
- **E1_lattice — control reported next to E1** (`--include-controls`; a negative control, never gates).

### E1 — annotation only (V1.2 §5.4)

E1's criteria are unchanged. Its Pearson-r criterion (r ≥ 0.95 between consecutive index-normalized spectra) is
weak evidence of self-similarity: a smooth spectrum that keeps its shape under resampling passes it too, so the
plateau criterion (multiplicity at λ ∈ {3, 5, 6} above 5% of N) carries E1. `E1_lattice` runs E1's statistics
on square lattices of matched N so the two can be read side by side.

### First V1.2 run (seed 0): results and diagnostics made after it

`python -m xon.run_tests --include-controls`, `results/20260923-134643_0/`, exit code 1 (E3, E4, E9a and E9c
fail). The V1.1 experiments reproduce their earlier numbers exactly. Nothing below changes a registration or a
verdict. The diagnostics were run after the results were seen, and are labeled as such.

Rerun with `--include-v1 --include-controls` after three presentation changes: the version bump to 1.2.0, a
legend instead of overlapping text labels in the seam-vs-purity figure, and E1_lattice's summary reporting the
smallest plateau fraction, as E1's does (0.000; it had shown the largest, 0.111). `results/20260923-141147_0/`,
every number identical.

The E9 numbers were first seen in development runs with the same seed. Two reported-only columns were added
after that, to diagnose them: `plateau_containment` (E9a) and `d_f_box` (E9c). Neither is judged. This full
run reproduces the development numbers.

**E9a: mismatch for gasket, Vicsek and S(4, n); carpet and lattice match.**
- `plateau_persistence` misses for all three finitely ramified geometries, but no plateau is lost.
  `plateau_containment` (reported, not judged) is the fraction of level L−1's plateau values found again at
  level L, and it is 1.000 for all three. The Jaccard index falls because every level adds new plateau values:
  gasket 7 → 17 → 34, S(4, n) 10 → 22 → 46, Vicsek 0 → 8 → 86. With containment 1 the index equals
  |A_{L−1}| / |A_L| = 0.50, 0.48 and 0.09. Under spectral decimation each level adds preimages of the previous
  level's eigenvalues, so the plateau count keeps growing, and the registered threshold of 0.8 is out of reach
  at every level. Recorded as a mismatch, with the containment column of the E9 report as the evidence. Not
  re-registered.
- Vicsek's `degenerate_fraction` is 0.314 at level 4 (predicted ≥ 0.5). It rises with the level: 0.12 at
  level 3, 0.31 at level 4, and 0.49 at level 5 (6,252 vertices, outside the band). A diagnostic outside the
  suite compared the boundary skeleton the spec prescribes with the textbook Vicsek graph, whose plus-shaped
  cells are glued at single points. The textbook graph has `degenerate_fraction` 0.93 at N = 625 and 0.96 at
  N = 3,125, with containment 1.0. In the skeleton, sub-copies meet along whole cell sides instead of at
  points, and at the band's size that lifts most of the exact degeneracies. Vicsek's E9a mismatch is therefore
  specific to the prescribed representation.
- By spec §5.2, Vicsek's E9a and E9b are not interpretable while its E9c fails (below). The E9 report says so.

**E9b: pass.** Purity: gasket 0.998, Vicsek 0.944, S(4, n) 1.000, tree 1.000; carpet 0.783 (exploratory).
Across the five geometries, seam fraction and purity have Spearman ρ = −0.82: more seams, lower purity.

**E9c: mismatch for Vicsek only.** Gasket, carpet and S(4, n) match.
- Vicsek fails on d_f and therefore on the Einstein residual. d_f is 1.679 at level 6 and 1.675 at level 7
  after the retry, against ln 5 / ln 3 = 1.465; the residual is 0.19 and 0.20.
- Its d_w (2.494 vs 2.465) and d_s (1.140 vs 1.189) match.
- At level 7 the walk window hit the 400,000-step cap before the MSD reached 25% of saturation.

By §5.2 this flags Vicsek's construction. Diagnosis, after the run:
- **The construction has the right dimension.** The box-counting dimension from consecutive levels,
  ln(N_L / N_{L−1}) / ln(diam_L / diam_{L−1}), is 1.468 at level 6 and 1.466 at level 7. It is reported in the
  E9c rows as `d_f_box`, and not judged. With it, the residual would be |1.140 − 2 · 1.466 / 2.494| = 0.036.
- **The mass-radius estimator is the outlier.** Its centers are drawn from the 10% of vertices farthest from
  the outer boundary. Vicsek's outer boundary is its 8 arm tips, so all 30 centers sit around the central
  cross, the fixed point of the similarity maps.

  The estimate depends on that choice. At level 6:
  - candidates from the deepest 25% or 50% of vertices give 1.58 and 1.43;
  - centers drawn uniformly, with each r using only the balls that stay inside, give about 1.46;
  - the textbook Vicsek graph gives 1.653 with the registered estimator, so the bias belongs to the estimator,
    not to the skeleton.

  A likely mechanism: M(r) oscillates log-periodically in r, and centers at one point oscillate in phase
  instead of averaging out.
- **The registered estimator and the verdict stand.** Re-registering the mass-radius estimator (for example
  with uniform centers, keeping the current one as a reported variant) is the user's decision and has not been
  made.

---

## Implementation choices fixed before the first V1.2 run

Fixed in `xon/config.py`, `xon/growth.py`, `xon/metrics.py`, `xon/geometry.py` and `xon/experiments.py` before
E9 was first run. The one change made after a smoke test (the mass-radius fit) is marked; it came before any E9
run and was calibrated on the lattice only.

**Geometries (§3)**
- Carpet and Vicsek are boundary skeletons of the unit square: vertices at cell corners, edges along cell sides,
  merged by coordinates rounded to 1e-9. Sub-squares are numbered row by row from the bottom-left (carpet 0–7,
  skipping the center; Vicsek 0–4 = bottom, left, center, right, top). At the first subdivision a vertex shared
  by several sub-squares takes the lowest index; later levels inherit the parent cell's label.
- Vicsek keeps no corner sub-square, so every subdivision drops the parent cell corners and each level replaces
  all vertices. New vertices (all of them for Vicsek, the added ones for the carpet) get the bilinear
  interpolation of their parent cell's corner amplitudes: weighted mean of |a| and weighted circular mean of the
  phases, which for two equal weights is exactly the gasket's midpoint rule. Carpet vertices keep their ids and
  state.
- S(p, n): level L is S(p, L + 1) (the seed is K_p = S(p, 1)), so N = p^(L+1). Growth maps the word w to w·w_n,
  which keeps w's id and state; the p − 1 new words w·x are born on the clique edge from w toward the letter x
  and interpolate that edge's endpoints as in the gasket. `labels["subregion"]` = the first letter.
- `outer_boundary`, where a larger copy of the geometry attaches (used by `mass_dimension`): the carpet's outer
  sides, Vicsek's 8 arm-tip vertices, the p extreme vertices of S(p, n), the gasket's seed corners, the
  lattice's outer ring and the tree's frontier.
- Sandbox: a growth step that replaces every vertex (Vicsek) resets an active sheaf to identity maps, since
  vertex ids carry no meaning across it.

**Metrics (§4)**
- `mass_dimension`: 30 centers among the vertices at least R_max from the outer boundary, with R_max = the 90th
  percentile of the boundary distance, so every ball is the same as in the unbounded geometry. The fit is
  log M against log r over r ∈ [⌈R_max/4⌉, R_max]. **Changed after a smoke test, before any E9 run:** the first
  version fitted every r = 1..R_max with R_max = diameter/8 and returned d_f = 1.79 on a 101 × 101 lattice (true
  value 2) and 1.38 on the level-7 gasket. The smallest shells follow the lattice scale: on the square lattice
  M(r) = 2r² + 2r + 1, whose log-log slope is 1.88 over r = 1..64 but 1.97 over r = 16..64. The replacement was
  calibrated on the lattice only: d_f = 1.943 at 101 × 101 and 1.971 at 201 × 201.
- `walk_dimension`: 1000 lazy walkers (stay with probability 1/2) split over 50 random start vertices. The walks
  are simulated as simple walks; the lazy MSD at time t is the Binomial(t, 1/2) mixture over the number of
  moves. Fit: log MSD against log t on 40 log-spaced times from t = 10. **Window end:** the spec's default is
  the time at which the MSD reaches 25% of the squared diameter. But the saturated MSD (mean squared distance
  from a walker's start to a degree-weighted random vertex) is only 0.14 of the squared diameter on the lattice
  (and, by the same geometry, about that on the carpet) and 0.33 on the level-7 gasket. So the default is never
  reached on the carpet and falls inside the saturation crossover on the gasket. The window ends instead when
  the MSD reaches **25% of its saturation value**, or at 400,000 lazy steps if that comes first. Lattice check:
  d_w = 2.06 at 101² and at 201².
- d_s in E9c: `spectral_dimension_est` over t ∈ [10, 1000] (exact eigenvalues when N ≤ 3000, else Hutchinson
  with 64 probes) instead of the sandbox window [5, 60]. The return probability of a finitely ramified fractal
  oscillates log-periodically in t (period factor 5 on the gasket, 15 on Vicsek), so the window must span more
  than one period; t = 1000 is far below the mixing times at the E9c sizes.
- `degenerate_fraction` and `plateau_persistence` use levels of eigenvalues chained within 1e-6, as in E1.
  `plateau_persistence` = |A ∩ B| / |A ∪ B| over the level means of multiplicity ≥ 3, matched one-to-one within
  1e-6; NaN when neither spectrum has a plateau.
- `seam_fraction`: fraction of edges whose endpoints carry different top-level labels (edges at unlabeled
  vertices, such as the tree's root, are skipped). With the lowest-index rule, the gasket's only seam edges are
  the junction vertices' edges into their other sub-gasket (6 of 3^(L+1)).

**E9a / E9b**
- Level: the largest level with 500 ≤ N ≤ 3000 (only S(3, n) has two). With the defaults: gasket L6 (N = 1095),
  Vicsek L4 (1252), S(4, 5) (1024), carpet L3 (688), tree L6 (1093), lattice 28 × 28 (784).
- The lattice's E9a levels are sides 3^ℓ + 1 (4, 10, 28), the vertex grid of a level-ℓ carpet cell.
- All N eigenvalues (dense) for E9a.
- E9b uses the canonical basis where the lowest k vectors cut through a degenerate eigenspace (Fiedler
  rotation for λ₂'s eigenspace, the localized basis otherwise); whether they do is reported
  (`splits_eigenspace`, with λ_{k+1}/λ_k). The tree's sub-regions are the root's child subtrees; the root is
  unlabeled. k-means++ with 20 restarts on one random stream per geometry. The seam-vs-purity relation is
  Spearman's ρ across geometries.

**E9c**
- Largest level with N ≤ 50,000: gasket L9 (N = 29,526), Vicsek L6 (31,252), carpet L5 (41,584), S(4, 7)
  (16,384).
- Retry: a failing geometry is rerun once at the next level if that level has N ≤ 400,000, and judged there;
  both runs are reported.
- One random stream per geometry (seeded by the first draw of E9c's stream and the geometry name), so a
  geometry's numbers do not depend on which others run.

**UI**
- The growth-rule dropdown lists `RULES` in group order (candidates, bridge, controls) and shows the groups in a
  caption under it: Streamlit's selectbox has no option groups, and a V1.1 test pins the dropdown options to the
  plain rule names.
- Geometry Compare is a third sidebar mode rather than a ninth tab: a V1.1 test pins the eight tabs.

---

## 2026-09-23 — V1.1 (`XON_SIM_FIX_V1_1.md`)

### E2 — Individuation from structure

- **Old criterion (kept as `E2_v1`):** Gasket level 5: `partition_purity` (sign of the single Fiedler vector
  φ₂ against the three sub-gaskets) ≥ 0.9 and `frac_localized` ≥ 0.25; lattice control `frac_localized` < 0.05.
- **New criterion (`E2`):** Gasket level 5: k-means (k = 3, 20 seeded restarts) on the rows of the low eigenspace
  (the constant and every eigenvector with λ ≤ λ₂(1 + 1e-6); 3 vectors on the gasket); purity of the best
  one-to-one matching of the 3 clusters to `labels["subgasket"]` ≥ 0.9; `frac_localized` ≥ 0.25; lattice
  `frac_localized` < 0.05 (unchanged). The V1 single-vector purity and the purity range over the λ₂ eigenspace
  are reported alongside.
- **Reason:** E2 fails narrowly (purity 0.888 vs 0.9) because λ₂ of the gasket is degenerate (multiplicity 2,
  from the triangle's three-fold symmetry). "The" Fiedler vector is not unique; purity across the eigenspace
  ranges 0.839–0.970. The experiment's definition is the problem, not the claim. Fix: use the whole low
  eigenspace (3-way spectral clustering), which is the standard, label-free treatment of a degenerate λ₂.

### E3 — Power-law memory

- **Old criterion (kept as `E3_v1`):** Gasket level 6 under noise drive (depth damping γ(depth)):
  R²_powerlaw > R²_exponential for the time-averaged depth-energy profile E[d]. Tree control expected to show
  R²_exponential ≥ R²_powerlaw (reported, not a failure).
- **New criterion (`E3`):** `wave` with Rayleigh damping (α = 0.005, β = 0.05), Γ_sink off, no drive. Gasket
  grown from level 3 to level 7 with G = 200 dynamics steps between growths. Unit energy is injected on each
  newly born layer; R_s(k) = energy remaining on that layer's vertices k growth steps later, averaged over layers
  into R(k). The known uniform factor e^{−2αGk} (in time units e^{−2α·kG·dt}) is divided out before fitting.
  Pass over k = 1..4: gasket R²_powerlaw > R²_exponential **and** tree (branch 3) R²_exponential ≥
  R²_powerlaw. Lattice control (no growth; elapsed time in units of G steps) is reported.
- **Reason:** E3 fails because the depth-energy profile under the old dynamics mostly reflects the *imposed*
  functional form of `γ(depth)` (steady-state energy per vertex ≈ noise/γ(depth) when coupling is weak), not the
  graph's intrinsic diffusion. The graph's intrinsic memory kernel *is* power-law — E7 proves it on this exact
  graph via return probability. Fix: re-register E3 to measure memory as **retention over growth steps of energy
  injected at a layer's birth**, under commuting damping, which tests the model's actual claim (depth = time of
  birth; coupling falls off with depth as a power law) without an arbitrary damping shape in the way.

### E4 — Harmonicity rises (now E4a / E4b / E4c)

- **Old criterion (kept as `E4_v1`):** Gasket grown from level 2 to level 5 under noise drive with depth damping
  (`wave_v1`); frontier harmonicity end-mean > start-mean, one-sided paired t-test p < 0.05 across 5 seeds,
  **and** increase ≥ 2× the increase of the uniform-damping control (γ1 = 0). Judged under the primary coherence
  factor, reported under all three.
- **New criterion:**
  - **E4a (linear negative control, never affects the exit code):** the V1 E4 criteria on the V1.1 `wave`, with
    "sink" = Γ_sink on at the maximum allowed γ_s and "control" = Γ_sink off. Expected to fail; its status is
    reported as `negative_control`.
  - **E4b (headline):** gasket grown from level 2 to level 5 (G = 500 steps per level), `stuart_landau` with ω by
    depth and noise σ = 0.05 at the frontier, 5 seeds; `harmonicity_osc` at the frontier with the 3-way
    spectral clusters recomputed after each growth. Pass: end − start > 0 with one-sided paired t-test p < 0.05
    **and** gasket end > complete-graph (same N) end with p < 0.05 **and** the μ = 0 control shows no
    significant rise. All four harmonicity variants are reported; the pass is on `harmonicity_osc`.
  - **E4c:** the same protocol and criteria with `oscillator` (Kuramoto, K = 1, ω by depth). A pass on either
    E4b or E4c passes E4.
- **Reason:** *(part 1)* E8 and E4 (part 1) fail because the depth-dependent damping `Γ = diag(γ(depth_i))` is
  diagonal in the *vertex* basis while `L` is diagonal in the *spectral* basis. They do not commute, so the wave
  equation no longer has clean modal decay. What survives undriven is whatever has least overlap with damped
  (old) vertices — a frontier-localized high-frequency mode (observed: k = 243, λ = 5 decays at γ₀ = 0.05 while
  the constant mode decays at the mean rate 0.153). The "collapse to the fundamental" prediction assumed
  commuting damping. Fix: **spectral (Rayleigh) damping** `Γ = αI + βL`, which commutes with `L` by
  construction, with an optional *weak* vertex-based depth sink whose strength is constrained so that modal
  ordering dominates.

  *(part 2)* E4 (part 2) fails for a deeper reason that would persist even with commuting damping: **linear**
  stochastic dynamics have no mechanism that prefers coherence. With Gaussian noise drive and linear damping, the
  stationary state has each mode's energy ∝ (noise fed) / (damping rate) — a thermal-like distribution, never a
  selection of few, phase-locked modes. Real resonant self-organization (Chladni figures, coupled oscillators)
  is nonlinear. Fix: add two **nonlinear** dynamics that share the V1 `Dynamics` interface and `State.a` —
  Stuart–Landau (amplitude + phase) and Kuramoto (phase only) — and re-register E4 on them. The linear E4 is kept
  as a negative control.

### E8 — The peace trap (now E8 and E8b)

- **Old criterion (kept as `E8_v1`):** `wave_v1` (depth damping), gasket level 5. No drive for T = 2000 steps:
  `fundamental_fraction` ≥ 0.9 at the end. Then noise drive for T steps: stays ≤ 0.5 (judged on the second
  half).
- **New criterion (`E8`):** `wave` (Rayleigh damping), Γ_sink off, gasket level 5. Phase 1 without drive; phase 2
  with noise drive at the frontier. Pass: `low_subspace_fraction(k_gap)` (modes k ≤ k_gap, the first spectral
  gap; k_gap = 3 on the gasket: the constant and the two sub-gasket modes) ≥ 0.9 at the end of phase 1 **and**
  ≤ 0.5 during phase 2. `fundamental_fraction` and the predicted global-collapse time 1/(2βλ₂) are reported.
  **`E8b`:** the same with Γ_sink on at the maximum allowed γ_s = 0.1βλ₂; identical criteria (verifies the weak
  sink does not break the collapse).
- **Reason:** E8 and E4 (part 1) fail because the depth-dependent damping `Γ = diag(γ(depth_i))` is diagonal in
  the *vertex* basis while `L` is diagonal in the *spectral* basis. They do not commute, so the wave equation no
  longer has clean modal decay. What survives undriven is whatever has least overlap with damped (old) vertices —
  a frontier-localized high-frequency mode (observed: k = 243, λ = 5 decays at γ₀ = 0.05 while the constant mode
  decays at the mean rate 0.153). The "collapse to the fundamental" prediction assumed commuting damping. Fix:
  **spectral (Rayleigh) damping** `Γ = αI + βL`, which commutes with `L` by construction, with an optional
  *weak* vertex-based depth sink whose strength is constrained so that modal ordering dominates. (Individuation
  means "peace per node" precedes global peace, hence the low subspace rather than the fundamental alone.)

---

## Implementation choices fixed before the first V1.1 run

The fix specification leaves some details open. They were fixed as below, in `xon/config.py` and
`xon/experiments.py`, before any re-registered experiment (E2, E3, E4a/b/c, E8, E8b) was run. Changing any of
them after seeing results would itself be a re-registration and belongs in a new dated entry above.

**All experiments**
- Each experiment draws from its own random stream, `SeedSequence([seed, n])` for E*n*, plus `ord(letter)` for
  lettered variants (E4a, E4b, E4c, E8b). The `_v1` variants reuse the V1 stream `[seed, n]`, so they reproduce
  the V1 numbers exactly.
- Gate groups for the exit code: E4 = E4b **or** E4c; E4a is a negative control and never counts; the `_v1`
  variants never count. E8 and E8b are separate gates (E8 = base + b), so a failure of either sets exit code 1.
- One-sided paired t-tests (`scipy.stats.ttest_rel`, `alternative="greater"`). An undefined p-value (zero
  variance) counts as "not significant".
- `gamma0`, `gamma1` and `damping_p` stay in `XonConfig` but only `WaveDynamicsV1` reads them.

**E2**
- k-means++ seeding with the generator seeded by `cfg.seed`; the restart with the lowest inertia is kept (Lloyd
  iterations capped at 300). Purity uses the Hungarian best one-to-one matching over all vertices, with the
  junction vertices labelled by the V1 junction rule.

**E3**
- "Unit energy uniformly across the vertices born at step s" = |a_i|² = 1/n_s on each newborn vertex with
  **independent uniform random phases**, averaged over 4 phase draws per layer. The judged fits use this
  injection. The equal-phase ("coherent") injection is reported but not judged: its projection on the constant
  mode (n_s/N of the energy) never decays under βL and spreads over the whole graph, so it measures dilution by
  growth rather than memory.
- The initial layer is the depth-3 layer at t = 0. Each layer is propagated as its own tagged column (the
  dynamics are linear); vertices born later start at zero in every tagged column. R_s(k) is measured after k
  epochs of G steps; growth itself does not move energy, so measuring just before or just after a growth gives
  the same value.
- α correction: every R_s(k) is multiplied by e^{2α·τ}, τ = k·G·dt, before averaging and fitting (exact, since
  αI commutes with L).
- Tree control: branch 3, grown over the same number of epochs from its level 3. Lattice control: the default
  lattice, one layer (all vertices) injected at t = 0 and measured every G steps for the same number of epochs.

**E4a**
- "Sink" condition: Γ_sink on at γ_s = 0.1βλ₂ of the current level (recomputed after each growth, since λ₂
  shrinks), D_sink = 2; "control": Γ_sink off. Otherwise the V1 E4 protocol (noise drive at the frontier,
  start/end = first/last epoch means, all three coherence factors reported).

**E4b / E4c**
- ω_i = ω₀ + Δω·depth_i/d_max with ω₀ = 1, Δω = 1. Noise at the newest layer (the V1 frontier drive): SL
  complex noise σ = 0.05, Kuramoto phase noise σ = 0.05. Stuart–Landau: μ = 1, c = 1, α = 0, β = 0.02.
  Kuramoto: K = 1, K_s = 0.
- Start/end = means over the first and last growth epochs (levels 2 and 5), as in V1 E4. Harmonicity is
  measured on the frontier (depth ≥ d_max − `frontier_window`).
- Clusters: 3-way spectral clusters of the current gasket (`n_clusters = 3`, 20 restarts, seed `cfg.seed`),
  recomputed after each growth. `n_clusters_eff`: cluster mean frequencies are least-squares slopes of the
  unwrapped cluster mean phases over the last W = 200 steps. Sorted frequencies closer than
  Δ = 1 rad / (W·dt) are merged, i.e. clusters whose relative phase drifts by less than 1 rad over the window
  count as one frequency. `n_clusters_max` = 3.
- Complete-graph control: same vertices, depths, ω, noise, clusters and frontier, coupled through K_N with
  uniform weight (gasket mean degree)/(N − 1), so each node's total coupling matches the gasket. The V1
  harmonicity variants use the gasket's modes in every condition.
- Null controls: E4b μ = 0 (as specified). E4c has no μ, so its null is **K = 0** (uncoupled phases; the
  nonlinearity that could select coherence is switched off).
- The same 5 seeds (drawn from the experiment's stream) are used for every condition, so the tests are paired.

**E8 / E8b**
- The spec leaves phase 1's length T open. It is fixed at **one predicted global-collapse time**,
  T₁ = ⌈1/(2βλ₂)/dt⌉ steps (≈ 34,800 steps at level 5). The V1 length (2000 steps) is far shorter than
  1/(2βλ₂) ≈ 1742 time units, so the fractions at step 2000 are reported as well.
- Phase 2 lasts 2000 steps (the V1 length) and is judged on its second half, as in V1 (the first half is
  burn-in from the end of phase 1).
- k_gap = argmax λ_{k+1}/λ_k over 2 ≤ k ≤ 10 (3 on the gasket). Default α = 0.02, β = 0.05. α is uniform, so it
  does not change any energy fraction.
- E8b: γ_s set exactly to the bound 0.1βλ₂, D_sink = 2, RK4 integrator (the modal integrator needs the sink
  off).

**E6** (protocol unchanged; the solver it names was a stub in V1)
- `OscillatorDynamics` with J = −A (antiferromagnetic), K = 1, ω = 0 (the frame of the sub-harmonic injection),
  K_s ramped linearly from 0 to 1 over 1500 of the 2000 steps, phase noise 0.05 at every vertex; spins =
  sign(Re a). These are the V1 config values.
