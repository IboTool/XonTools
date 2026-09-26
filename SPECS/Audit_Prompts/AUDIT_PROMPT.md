# Full project audit, tidy-up, verification and fresh push

Audit the whole repository (branches `main` and `xonforge`, both worktrees), fix what I approve, verify nothing is broken, then push a fresh copy. The repository will be **private, shared with researchers and grant reviewers**. Work in five phases and **STOP** where marked. Record every decision I give you in `decisions.md` and log the work in `CHANGELOG_EXPERIMENTS.md`.

Standing constraints for the whole task:
- **No API calls** except the single live check in Phase 3. Trust existing caches, fixtures, saved responses and logs.
- **Engine code is report-only** until rev 2.2's result of record: nothing under `xon/llm/` (prompts, schemas, request construction, hashing, analysis, scoring) and no `xon/config.py` value that enters a request or a score may change, because even a harmless refactor can change request hashes and break replay. The same applies to `xonforge/` code that builds requests or cache keys.
- **Never modify** `results/`, `data/consistency/`, `cache/`, `tests/fixtures/`, saved L1-var responses, or any past changelog or `decisions.md` entry. Corrections are new entries.
- The private folder has moved **outside the repository**. Nothing outside the repo root is read by this audit, except to confirm that nothing inside the repo refers to it.

---

## Phase 0 — State report (no changes)

Report:
- `git status`, branches, tags, remotes, and the last 20 commits on each branch; whether the history has already been reset locally;
- uncommitted changes in both worktrees;
- the repo root's file listing, sizes of the top-level folders, and every file over 10 MB;
- the test suite's current result (`pytest`, then `pytest -m slow`).

**STOP.**

---

## Phase 1 — Read-only audit

Write the report to `docs/audits/2026-09-audit.md`. For each finding give: ID, severity (**blocker** / **major** / **minor** / **note**), area, location, evidence, proposed fix, and fix class:
- **safe:** documentation, configuration, repository hygiene, tests that only add checks;
- **needs decision:** anything touching behavior, data, or a recorded protocol;
- **deferred:** engine code (report only, see constraints).

Change nothing in this phase.

### A. Secrets and privacy
- Search every tracked and untracked file for keys (`sk-ant`, other providers' key formats), key assignments, `.env` files, tokens.
- Personal information: local paths (`C:\Users\…`), usernames, names and emails other than the project contact (Ian MacKenna, gratefulrising@proton.me), in code, docs, logs, results, caches and fixtures.
- References to removed files (the old README, the journal, the private folder).
- Logs that contain prompt, response or document text where the rules say they must not.

### B. Repository contents and hygiene
- Stray, temporary, duplicate or generated files; stale scripts; empty folders; files at the root that belong elsewhere.
- `.gitignore` and `.gitattributes` against the rules (`* -text`; caches and sealed data excluded as decided; nothing needed by tests ignored).
- Large files and whether each should be tracked.
- Naming consistency of results folders and scripts.
- The `private/` entry in `.gitignore`: note that the folder has moved out of the repo.

### C. Provenance and protocol compliance
- Every number the README, `SPECS/XON_BUILD_OVERVIEW.txt` and the changelog cite for runs of record (L1, L1b, L1-var, post-hoc, rev 2.2 development passes) matches the result files.
- Spec status: each spec in `SPECS/Implemented/` is implemented, each in `SPECS/ToDo/` is not (or is partly, as the changelog says).
- Every gate and stop rule in the specs (rule 3 gates, budget stops such as rev 2.2's 4,000,000-token estimate stop, D0, XonForge's 20-document sample stop): honored, or the deviation logged with my approval. List any that were not.
- Development-iteration numbering and the iteration count for rev 2.2 are consistent across the changelog and `decisions.md`.
- `decisions.md` agrees with the changelog; flag contradictions and superseded entries not marked as such.
- Tags: which exist, what they point to, whether each one the changelog cites exists.

### D. Data integrity
- The L1 corpus: file hash against the recorded hash; 180 documents; schema valid.
- Fixtures: every call the dry-run tests need has a fixture; no orphaned fixtures.
- Response cache: every entry parses; recompute the request hash for a random sample of 50 entries and confirm it matches the key.
- Results folders: complete (per-document rows, analyses, scores, `results.md`); nothing references a missing file.
- L1-var saved responses complete for all three repetitions.
- XonForge: manifests verify; no sealed or judged text anywhere under the repo root (run the leak test); data under `data/xonforge/` is only development and calibration.

### E. Safety boundaries
- Only `xon/llm/client.py` imports `anthropic` on the A1 side, and only the named XonForge provider module on the XonForge side.
- Each key variable is read only in its one module.
- `xonforge/` imports the engine only through `xonforge/diagnostics/engine_plugin.py`, which refuses sealed and judged paths.
- XonForge never writes to `cache/llm/`.
- The anti-features in `future_features.md` are absent (no score exposure to agents, no self-query interface, no leaderboards, no monitor output used as reward or training data).

### F. Code quality and efficiency (report-only for engine code)
- Dead code, unused functions, unused imports, duplicated logic (including the planned `client.py` / `xon_common` duplication, noted as intended).
- Error handling: broad `except` blocks, swallowed errors, missing fail-closed paths.
- Performance: profile the offline test battery and the simulator runner; list the slowest steps and likely causes.
- Test coverage: modules or branches without tests.
- If `ruff` and a type checker are already installed, run them and summarize; do not add new dependencies.

### G. Documentation truth
- Every command in `README.md` and other docs runs as written (offline ones actually run; live ones checked for syntax and arguments only).
- Every path and link in the docs exists. Note in particular `README.md`'s links to `docs/xon_sim.md`, which I have not yet created: propose either creating it from the simulator sections of the old README (which I will supply) or removing the links.
- The README's status table, results and repository map match the code and results.
- Spec cross-references (for example C2 and A3 pointing to A2 rev 2.1) are listed, not fixed.

### H. Dependencies, licensing, reproducibility
- `pyproject.toml`: dependencies, versions pinned or not, Python version, extras, `pythonpath` setting.
- Each dependency's license, and compatibility with Apache 2.0.
- `LICENSE` file present with the Apache 2.0 text; the README's license line matches.
- Install and run steps work from a fresh clone (checked in Phase 4).

**STOP.** I'll mark which findings to fix.

---

## Phase 2 — Fixes I approve

- Make only the fixes I approve, one commit per finding or small group, each message citing the finding IDs.
- Engine code stays untouched regardless of approval unless I explicitly override the constraint for a named finding.
- Update the audit report with each fix's status.

**STOP** when done and summarize.

---

## Phase 3 — Verification battery

Run each and record pass or fail, duration, and any difference in the audit report:
1. `pytest` (full default suite) and `pytest -m slow`.
2. The headless Streamlit app test, in dry-run mode.
3. The simulator runner (E1–E9c), confirming the same pass and fail pattern as before (E3, E4 and E9a fail by design; exit code 1).
4. L1 and L1b recomputed from the cache, compared against the run of record's `l1.json`.
5. The rev 2.1 byte-identical replay test.
6. L1-var recomputed from its saved responses (`scripts/recompute_l1var.py`), compared against its recorded results.
7. The rev 2.2 development passes recomputed from the cache, compared against their recorded results.
8. XonForge's offline tests, in its worktree.
9. The secret-scan, key-name, import-boundary, sealed-leak and log-text tests.
10. **One live check:** with my key set in the terminal, analyze one short paragraph (under 100 words, with one planted direct contradiction) under rev 2.2, with a session budget of 50,000 tokens. Report the verdict, tokens and cost. Run it a second time and confirm it is served entirely from the cache at zero cost. Do not record fixtures from it.

**STOP** and report.

---

## Phase 4 — Fresh push

1. If the local history has not already been reset: zip the current `.git` directory with a list of every branch, tag and commit hash to my private folder outside the repo, verify the zip opens, then re-initialize (branch `main`, keeping `.gitignore` and `.gitattributes`). If it has, say so and skip this step.
2. Show me `git status` for `main` and the `xonforge` branch. **STOP.**
3. I'll delete the GitHub repository's contents or the repository itself and give you the empty repository's URL. Then push `main`, `xonforge`, and every tag.
4. **Fresh-clone check:** clone the pushed repository into a temporary folder outside both worktrees, install it, and run `pytest` and the dry-run app test there. This proves the repository works with nothing that exists only on this machine. List any failure caused by a missing untracked file. Delete the temporary clone afterward.
5. Recreate the `xonforge` worktree if the reset removed it.

---

## Phase 5 — Record

- `decisions.md`: entries for this audit's decisions, including the private folder's move outside the repository (superseding the earlier `private/` entry).
- `CHANGELOG_EXPERIMENTS.md`: one entry summarizing the audit, the fixes, the verification results, the live check, and the push.
- The final audit report committed at `docs/audits/2026-09-audit.md`.
