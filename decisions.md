# Decisions

The user's decisions, one entry per decision, newest last. Each entry records what was decided, not the discussion,
and names the `CHANGELOG_EXPERIMENTS.md` entry with the details.

Rules:

- Add an entry whenever the user answers a question that sets or changes how something is built, run, stored or
  evaluated. Commit it with the work it governs.
- Record decisions, not discussion. If a decision reverses an earlier one, add a new entry and mark the old one
  "Superseded by <date/title>"; never edit or delete old entries.
- Read this file at the start of every session, and don't ask again anything it settles.

## 2026-09-25 — Repository — the history reset

Decision: The repository's history was reset on 2026-09-25, starting again from one snapshot commit ("Snapshot: V1-V1.2
and A1 rev 2.1, after the L1 run of record"). The old history, tags and hashes are archived privately as a zip outside
the repository.
Why: Personal and internal documents, such as the project journal and the old README, must never appear in the history
before the repository is shared with researchers and grant reviewers.
Changelog: 2026-09-25 — A1 rev. 2.2, development iteration 1: the user's decisions, and Step 0 (no API calls), item 6

## 2026-09-25 — Repository — `private/` at the repository root

Decision: Personal and internal documents go in `private/`, a gitignored folder at the repository root that is never
pushed and is backed up separately with the XonForge private folders; only the key-name test skips it, and the
sealed-text leak test still scans it.
Why: Personal and internal documents stay out of the history, but the folder sits inside the working folder, where any
session can read it.
Changelog: 2026-09-25 — A1 rev. 2.2, development iteration 1: the user's decisions, and Step 0 (no API calls), item 6
Superseded by: 2026-09-25 — Repository — private documents outside the repository

## 2026-09-25 — Repository — the license

Decision: The repository's code is licensed under the Apache License 2.0. The generated corpus is not: its license is
still open (likely CC BY 4.0, once each provider's terms are checked), and XonForge's export waits for it.
Why: Apache 2.0 is permissive, so labs and collaborators can use the code, and it includes a patent grant.
Changelog: 2026-09-25 — A1 rev. 2.2, development iteration 1: the user's decisions, and Step 0 (no API calls), item 6

## 2026-09-25 — A1 — rev. 2.2's budget, and how gate D0 and the full pass run

Decision: A1's token cap goes from 15,000,000 to 45,000,000, and the spec's 4,000,000-token limit on the full pass is
lifted; calls are sent synchronously, not as a Message Batch, and the full pass follows gate D0 without another stop
if D0 passes. Nothing is pushed until the user says so.
Why: The full pass's estimate, 30.9M tokens, was above both the 4M limit and what was left of A1's cap.
Changelog: 2026-09-25 — A1 rev. 2.2: the user's budget decision, and how gate D0 and the full pass are run (before
any call)

## 2026-09-25 — XonForge — in this repository, as its own package

Decision: XonForge lives in this repository as its own top-level package, `xonforge/`, with its tests in
`tests/xonforge/` and its spec in `SPECS/ToDo/`.
Why: One set of habits, and its own package keeps a later split easy.
Changelog: 2026-09-25 — XonForge — step 0 (`XONFORGE_SPEC.md`): re-specifications made before any code, items 1
and 9

## 2026-09-25 — XonForge — its own branch and worktree

Decision: XonForge work is on the branch `xonforge`, checked out as a worktree at `%USERPROFILE%\Desktop\XON-xonforge`
and logged in `CHANGELOG_EXPERIMENTS.md` on that branch. It is merged into `main` only at milestones (v0 core, the
20-document sample stop, v1) and only when the user says so; agents never merge.
Why: It allows parallel work without switching the folder where A1's precision work is done.
Changelog: 2026-09-25 — XonForge — step 0 (`XONFORGE_SPEC.md`): re-specifications made before any code, items 2, 8
and 10
Superseded by: 2026-09-26 — Repository — one branch, `main`, in one folder

## 2026-09-25 — XonForge — the shared module imports `client.py`'s cache and budget logic

Decision: The shared module `xon_common/` reuses `xon/llm/client.py`'s cache and budget logic by importing it,
extended for the other providers, and no file under `xon/` is edited before the tag `a1-rev2.2-frozen`.
Why: To avoid duplicating A1's code.
Changelog: 2026-09-25 — XonForge — step 0 (`XONFORGE_SPEC.md`): re-specifications made before any code, item 3
Superseded by: 2026-09-25 — XonForge — the shared `xon_common` core

## 2026-09-25 — XonForge — its cache and log under `cache/xonforge/`

Decision: XonForge writes its cache and run log under `cache/xonforge/`, never to `cache/llm/`.
Why: Rev. 2.2's budget stop computes A1's remaining spend from `cache/llm/log.jsonl`.
Changelog: 2026-09-25 — XonForge — step 0 (`XONFORGE_SPEC.md`): re-specifications made before any code, item 4
Superseded by: 2026-09-25 — XonForge — cache and split locations (for the cache; the log stays)

## 2026-09-25 — XonForge — sealed splits outside the repository, development and review splits inside

Decision: Sealed test splits are written only to `XONFORGE_SEALED_DIR`, outside every worktree of this repository,
with only their hash manifests and datasheets committed; development and review splits may live in `data/xonforge/`.
Why: Anything holding test-document text must be unreadable from engine work.
Changelog: 2026-09-25 — XonForge — step 0 (`XONFORGE_SPEC.md`): re-specifications made before any code, item 6
Superseded by: 2026-09-25 — XonForge — which splits live where (for the development and review splits)

## 2026-09-25 — XonForge — provider key variable names

Decision: XonForge reads provider keys only from its own environment variables, one per provider
(`XONFORGE_ANTHROPIC_KEY`, `XONFORGE_OPENAI_KEY`, `XONFORGE_GEMINI_KEY` and so on), each read only in its provider
module and never shown in logs, caches or the UI. It never uses or names A1's key variable, and the Anthropic SDK is
given its key explicitly, so it cannot fall back to A1's.
Why: Separate spend tracking, and the names don't match A1's key-name test.
Changelog: 2026-09-25 — XonForge — step 0 (`XONFORGE_SPEC.md`): re-specifications made before any code, item 7;
2026-09-25 — XonForge — step 1 (`XONFORGE_SPEC.md`): re-specifications from the user's answers, item 9

## 2026-09-25 — XonForge — the shared `xon_common` core

Decision: `xon_common` gets its own provider-neutral cache, budget and call-log core now, importing only `request_hash`
and `request_key` from `xon/llm/client.py`, and XonForge keeps its own model and price registry. `client.py` moves
onto this core after rev. 2.2's result of record, with a regression test that A1's request hashes and the run of
record's replay stay byte-identical.
Why: XonForge needs several providers now, and A1's client must stay unchanged through its measurement.
Changelog: 2026-09-25 — XonForge — step 1 (`XONFORGE_SPEC.md`): re-specifications from the user's answers, item 1;
its "after `a1-rev2.2-frozen`" is corrected by 2026-09-25 — XonForge — correction: `client.py` moves onto
`xon_common` after rev. 2.2's result of record

## 2026-09-25 — XonForge — transport retries as in A1

Decision: XonForge retries rate-limit and overload errors, the other 5xx errors, timeouts and lost connections, as A1
does (3 retries, the first after 2.0 s, doubling, waiting at least the server's `retry-after`), a deviation from the
spec's §4.2. A transport retry resends the identical request and never counts toward the cap on rendering attempts.
Why: Transient failures happen across providers, and a retry resends the identical request, so content is unaffected.
Changelog: 2026-09-25 — XonForge — step 1 (`XONFORGE_SPEC.md`): re-specifications from the user's answers, item 2

## 2026-09-25 — XonForge — cache and split locations

Decision: XonForge's response cache (`XONFORGE_CACHE_DIR`), the sealed test split (`XONFORGE_SEALED_DIR`), the judged
split (`XONFORGE_JUDGED_DIR`) and, under the cache directory's parent, every log with prompt, response or document text
and every review item or reviewer output for a sealed or judged document live only outside the repository, never
under the root of any worktree, and XonForge never writes to `cache/llm/`. Only the spend and call log
(`cache/xonforge/log.jsonl`) stays inside, with a test that it holds no prompt or response text, and another test
fails if any file under the repository root contains text from a sealed document.
Why: Anything holding test-document text must be unreadable from engine work.
Changelog: 2026-09-25 — XonForge — step 1 (`XONFORGE_SPEC.md`): re-specifications from the user's answers, items
3–5 and 7

## 2026-09-25 — XonForge — which splits live where

Decision: Every generated document stays outside the repository until the split assigns it; then only the development
split and the calibration split (the spec's 15%) are copied into `data/xonforge/`, and the sealed and judged splits
stay outside, with only their hash manifests and datasheets committed. The canaries stay in `xonforge/canaries/`.
Why: The development and calibration splits are both used for development: calibration sets thresholds.
Changelog: 2026-09-25 — XonForge — step 1 (`XONFORGE_SPEC.md`): re-specifications from the user's answers, items 5
and 6; 2026-09-25 — XonForge — step 2: the user's decisions on binary parity, direct negation, twins and
distractors, item 7

## 2026-09-25 — A1 — automatic reruns after network failures in rev. 2.2's full pass

Decision: The full pass resumes with the same command and a recomputed budget; after a further connection drop,
timeout or 5xx error it waits until the network is back and reruns automatically, up to 5 times, logging each, and
it stops on any other failure.
Why: The L1 run of record's rerun rule covered only L1's remaining documents.
Changelog: 2026-09-25 — A1 rev. 2.2, the full development pass (iteration 0), item 5

## 2026-09-25 — XonForge — the `rules.md` section

Decision: The XonForge section of `rules.md` is approved, with one line added: generated documents stay outside the
repository until the split assigns them, and only development and calibration documents are then copied into
`data/xonforge/`.
Why: It protects sealed data and keeps the sample stop a gate.
Changelog: 2026-09-25 — XonForge — step 2: the user's decisions on binary parity, direct negation, twins and
distractors, item 9 (the section is in `rules.md` on the `xonforge` branch)

## 2026-09-25 — XonForge — twins

Decision: The order cycle's and equality break's consistent twins are A1's matched controls, with a logged seed
choosing which relation changes; binary parity's twin keeps two values and turns one "different" into "same", the
three-value version staying the separate trap `arity_control`; direct negation's twin replaces the negation, as a
minimal edit, with one the solver confirms holds. One planted variant per base.
Why: The pair should differ only in the contradiction, so that no surface feature predicts the label.
Changelog: 2026-09-25 — XonForge — step 2: the user's decisions on binary parity, direct negation, twins and
distractors, items 1, 3 and 5

## 2026-09-25 — XonForge — premises

Decision: The negated claim of a direct negation is a premise in a configurable share of documents (default 0.5),
recorded per document; the consistent twin keeps its contradictory document's premise status.
Why: It preserves the L1b measurement and keeps "Assume that" from becoming a shortcut.
Changelog: 2026-09-25 — XonForge — step 2: the user's decisions on binary parity, direct negation, twins and
distractors, item 4

## 2026-09-25 — XonForge — the arity fact

Decision: The sentence stating the number of values is recorded separately, as A1 did, in its own field `arity_fact`
with its span; the solver treats it as required (the parity contradiction holds with it and not without it), and it
appears in the contradictory document, in its twin and in exports.
Why: It matches A1's scoring and keeps "two teams" from becoming a shortcut.
Changelog: 2026-09-25 — XonForge — step 2: the user's decisions on binary parity, direct negation, twins and
distractors, item 2

## 2026-09-25 — XonForge — distractors

Decision: Same-attribute distractors are a difficulty setting, not a fixed rule: they may use the planted attribute
among entities outside the plant, the solver confirming they create and break no contradiction, off at the lowest
difficulty (as in L1) and on at higher levels. The mapping to levels waits for the spec's §5.4 difficulty levels.
Why: Harder, more realistic corpora at higher levels.
Changelog: 2026-09-25 — XonForge — step 2: the user's decisions on binary parity, direct negation, twins and
distractors, item 6

## 2026-09-25 — A1 — rev. 2.2: iteration 1 before L1-var

Decision: The revised rev. 2.2 spec is implemented, Step 0 first with no API calls, then the new Fix E1, its tests and
a new budget estimate that says whether the per-pair calls use prompt caching or the Batches API and what each would
save, stopping before D0's calls. L1-var 2.2 waits for iteration 1 instead of running on the old Fix E1.
Why: Don't measure code that's about to be replaced.
Changelog: 2026-09-25 — A1 rev. 2.2, development iteration 1: the user's decisions, and Step 0 (no API calls), item 1

## 2026-09-25 — A1 — how rev. 2.2's development iterations are counted

Decision: The original rev. 2.2 spec, with gate D0 and the full pass under the old Fix E1, is iteration 0; the spec
revision (Step 0 and the new Fix E1) is iteration 1.
Why: D0's numbers had been seen when the spec was revised; the revision was motivated by the run of record's 0.900
order-relation accuracy, before the full pass's results existed.
Changelog: 2026-09-25 — A1 rev. 2.2, development iteration 1: the user's decisions, and Step 0 (no API calls), item 1

## 2026-09-25 — A1 — Step 0's report shows the remaining false positives

Decision: Step 0's report lists the full pass's remaining false positives, each with the verdict clause that fired,
its claims, the judge's rationale and confidence; if any comes from a relation clause, the user sees them before
further iterations.
Why: The new Fix E1 targets only entity-clause false positives.
Changelog: 2026-09-25 — A1 rev. 2.2, development iteration 1: the user's decisions, and Step 0 (no API calls), item 1

## 2026-09-25 — Process — this register

Decision: The user's decisions are kept in `decisions.md` at the repository root, one entry per decision, newest last,
under the rules at the top of this file, backfilled from the user's earlier answers.
Why: One register, so settled questions aren't asked again.
Changelog: 2026-09-25 — A1 rev. 2.2, development iteration 1: the user's decisions, and Step 0 (no API calls), item 6

## 2026-09-25 — A1 — the relation prompt stays as it is in iteration 1

Decision: Having seen the four remaining false positives, all from relation clauses, the user keeps iteration 1 as
specified: the relation prompt is not revised now.
Why: Not recorded.
Changelog: 2026-09-25 — A1 rev. 2.2, development iteration 1: the user's decisions, and Step 0 (no API calls), item 1

## 2026-09-25 — XonForge — correction: `client.py` moves after rev. 2.2's result of record

Decision: `client.py` moves onto `xon_common`'s core after rev. 2.2's result of record, not after the tag
`a1-rev2.2-frozen` as the XonForge step 1 entry says.
Why: A1's client must stay unchanged through its measurement.
Changelog: 2026-09-25 — XonForge — correction: `client.py` moves onto `xon_common` after rev. 2.2's result of record

## 2026-09-25 — Repository — private documents outside the repository

Decision: The user keeps personal and internal documents in a folder outside the repository, maintained separately.
Nothing under the repository root is private, so every repository-wide test scans all of it, with no exception for a
private folder.
Why: To prevent leaks.
Changelog: 2026-09-25 — A1 rev. 2.2, development iteration 1: the user's decisions, and Step 0 (no API calls), item 6

## 2026-09-25 — Repository — the GitHub repository is reset again

Decision: The GitHub repository will be reset again, with no journal, no private documents and only the new README.
Why: The journal, the old README and the six PDFs are still in the pushed history, and personal and internal documents
must not appear in it before the repository is shared.
Changelog: 2026-09-25 — A1 rev. 2.2, development iteration 1: the user's decisions, and Step 0 (no API calls), item 6

## 2026-09-25 — Repository — how the second reset is done

Decision: The user deleted the GitHub repository and re-created it under the same name. Its history starts again from
one root commit holding the working tree after A1 rev. 2.2's iteration 1, without the journal, the PDFs and the old
README, tagged `repo-reset-<date>`, and pushed without force when the user says so. Before the root commit is made,
the tree is scanned for keys, local paths, and personal names or emails other than the project contact, and the user
sees the results; the local paths found are replaced by `%USERPROFILE%`, one of them in an older entry of this file.
The history since the first reset is archived as a zip in the user's private folder, with a list of every branch, tag
and hash, and checked to open.
Why: Not recorded.
Changelog: 2026-09-25 — Repository — the second reset: hashes and `a1-run-of-record` from before it refer to the
archived history
Superseded by: 2026-09-26 — Repository — XonForge merged into `main`, and the history restarted (for the root commit)

## 2026-09-25 — Repository — `a1-run-of-record` is not re-created on the new root

Decision: The tag `a1-run-of-record` stays with the archived history and is not re-created on the new root commit. It,
and every commit hash quoted before the reset, refer to the archived history, and one changelog entry says so.
Why: That name would claim the run of record's state for a tree that includes rev. 2.2's changes.
Changelog: 2026-09-25 — Repository — the second reset: hashes and `a1-run-of-record` from before it refer to the
archived history

## 2026-09-25 — Repository — the journal and the PDFs are ignored

Decision: The journal and the six PDFs are removed from the tree and gitignored (`PROJECT_JOURNAL*`, `pdfs/`), and
nothing else in the tree links to the journal, the PDFs or the old README.
Why: Not recorded.
Changelog: 2026-09-25 — Repository — the second reset: hashes and `a1-run-of-record` from before it refer to the
archived history

## 2026-09-26 — Repository — XonForge merged into `main`, and the history restarted

Decision: XonForge's branch is merged into `main`, and XonForge lives in the one project folder as `xonforge/`. The
history starts again at one root commit, "Initial commit", holding the merged tree, tagged `repo-reset-2026-09-26`
and pushed without force once the user confirms that the empty GitHub repository exists. The whole `.git` before it
is archived privately as `git-archive-2026-09-25-pre-reset.zip`, and every hash and tag from before it,
`repo-reset-2026-09-25` included, refers to the archives.
Why: Pushed as it stood, `main` would have published the pre-reset history, including the journal, through
`xonforge`'s commits. One root commit keeps the published history clean.
Changelog: 2026-09-26 — Repository — the third reset: XonForge merged into `main`, one branch in one folder, items
1 to 5

## 2026-09-26 — Repository — one branch, `main`, in one folder

Decision: The repository has one branch, `main`, in one folder. Parallel Cursor sessions each commit only the files
they changed, and pull or check `git status` before committing. Each logged step ends with a commit, freezes and
runs of record are tagged, and pushed history is never force-pushed or rewritten.
Why: Two branches and a worktree for parallel work caused merge problems and confusion; one folder is simpler and
enough.
Changelog: 2026-09-26 — Repository — the third reset: XonForge merged into `main`, one branch in one folder, item 7

## 2026-09-26 — Repository — what never lives inside the project

Decision: Git archives, XonForge's cache, the sealed and judged splits and the private folder never live inside the
project, and `.gitignore` ignores git archives and history bundles (`git-archive-*.zip`, `*.git-archive*`,
`XON-history-*.zip`, `*.bundle`). A1's cache, `cache/llm/`, stays tracked: the run of record's replay reads it.
Why: Anything holding test-document text or private material must be unreadable from engine work and never
published. A1's cache holds only the L1 development corpus's responses, which the run of record's replay needs.
Changelog: 2026-09-26 — Repository — the third reset: XonForge merged into `main`, one branch in one folder, item 7

## 2026-09-26 — Repository — correction: the history before `1b1749b4` was not archived

Decision: The entry "2026-09-25 — Repository — the history reset" is wrong to say that the old history, tags and
hashes are archived as a zip. No such archive was made, and the history before `1b1749b4` was not preserved, an
oversight on the project's first day. `1b1749b4` records no parent: it is a root commit. The provenance of the runs
before it rests on the changelog, the cache replay and the recorded hashes, not on git history. The archives that do
exist are `XON-history-before-reset-2026-09-25.zip`, which holds the tag `a1-run-of-record` on `1b1749b4`, and
`git-archive-2026-09-25-pre-reset.zip`, SHA-256 `70c4331bc91f5513b42cf8c1c89fa4fe699aeff7e704107a82d7ed4e7adf36f6`.
The earlier entry is left as it is.
Why: The earlier entry misstates what was archived.
Changelog: 2026-09-26 — Repository — the third reset: XonForge merged into `main`, one branch in one folder, item 6

## 2026-09-26 — Repository — the call log is rotated before 45 MB

Decision: A1's call log, `cache/llm/log.jsonl` (34.9 MB at the third reset), stays tracked. If it approaches 45 MB,
work stops and a rotation is proposed (for example one log file per run under `results/`, with the main log
restarted).
Why: To stay below GitHub's 50 MB warning.
Changelog: 2026-09-26 — Repository — the third reset: XonForge merged into `main`, one branch in one folder, item 11

## 2026-09-26 — A1 — the recompute's format differences are known, not regressions

Decision: The L1 recompute's `results.md` version line and the nine fields it adds to each regenerated analysis are
known differences, not regressions; the audit can decide later whether the recompute should reproduce the old format
exactly.
Why: Every scored value matches the run of record byte for byte; the differences are fields added by later code, not
changed results.
Changelog: 2026-09-26 — Repository — the third reset: XonForge merged into `main`, one branch in one folder, item 12

## 2026-09-26 — XonForge — the repository tests pass without `.git`

Decision: The leak test's commit search skips when there is no commit or `HEAD` has no parent, and the worktree
location test checks the project root always and every worktree git lists when there is a repository.
Why: A copy without `.git`, such as a downloaded one, failed them.
Changelog: 2026-09-26 — Repository — the third reset: XonForge merged into `main`, one branch in one folder, item 8
