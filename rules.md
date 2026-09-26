# Rules for this project

These rules apply to every SPEC implementation.

1. Never change a pre-registered threshold, protocol, or criterion. If one looks wrong or ambiguous, stop and
   ask me, without running it and without showing predicted outcomes.
2. Log every deviation, bug fix that affects results, or re-specification in `CHANGELOG_EXPERIMENTS.md` with
   the reason.
3. Stop at every gate (e.g. LC1, P11a) and report before continuing.
4. Stay within the stage's LLM budget cap; stop and report if you'll exceed it.
5. Before generating any full synthetic corpus, generate a small sample and stop for my review.
6. "Tests pass" is not "done": run the stage's eval CLI and report the results table.

## Specs

- Specs are in `SPECS/`. Specs that haven't been implemented yet are in `SPECS/ToDo/`; implemented ones are in
  `SPECS/Implemented/`.
- Move a spec from `SPECS/ToDo/` to `SPECS/Implemented/` **only** after I have explicitly confirmed that the whole
  spec is implemented. Finished work, passing tests, a passed gate, or my approval of part of a spec is not that
  confirmation. Whenever you move a spec, tell me which file you moved. If you're unsure whether I've confirmed
  it, ask; don't move it.
- `SPECS/XON_BUILD_OVERVIEW.txt` is where I keep track of the overall architecture. You can reference it, but
  don't get ahead of yourself: don't implement any spec file I don't explicitly ask you to.

## Git

- One branch, `main`, in one folder. Each session commits only the files it changed, after a pull or `git status`.
- Commit at the end of each logged step, with a message naming the step.
- Tag every freeze and every run of record.
- Never commit secrets.
- Never rewrite pushed history (no force-push, no rebase of pushed commits).
- When `cache/llm/log.jsonl` approaches 45 MB, stop and propose a rotation, before it passes GitHub's 50 MB warning.

## XonForge

- These live only outside the repository, never under the root of any worktree of this repository: the sealed test
  split (`XONFORGE_SEALED_DIR`), the judged split (`XONFORGE_JUDGED_DIR`), XonForge's response cache
  (`XONFORGE_CACHE_DIR`), and, under the cache directory's parent, every review, decision or diagnostic log that
  contains prompt, response or document text and every review-queue item or reviewer output for a sealed or judged
  document. Never open these locations while working on the consistency engine.
- `xonforge/` never imports the consistency engine (`xon/llm/consistency.py`, `entity_consistency.py`, `minimal.py`,
  `engine.py`), directly or transitively, except through `xonforge/diagnostics/engine_plugin.py`, which refuses any
  path under the sealed or judged split's location (`XONFORGE_SPEC.md` §7.5).
- The 20-document sample stop in `XONFORGE_SPEC.md` (§14, step 7) is a gate (rule 3).
- Each `XONFORGE_*_KEY` is read only in its provider module and never appears in logs, caches or the UI.
- XonForge never writes to `cache/llm/`.
- Generated documents stay outside the repository until the split assigns them; only development and calibration
  documents are then copied into data/xonforge/.
