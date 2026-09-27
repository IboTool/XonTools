# Commitments

A commitment is posted here **before** a run of record, so that anyone can check afterwards that the code,
the environment and the test corpus were fixed before any result existed. This file is the public record;
xontools.ai/results mirrors it.

## Standing instructions

1. **Post before running.** Every run of record gets an entry here, committed and pushed to GitHub, before the
   run starts. A run of record with no prior entry here is reported at the *Recorded* level, not *Committed*.
2. **Append only.** Never edit or delete an entry once it is pushed. A mistake is corrected by a new entry that
   names the entry it corrects and says why. Never rewrite pushed history (the Git rule in `rules.md`).
3. **One commit, nothing else in it.** The commit that adds an entry changes only this file, with the message
   `Commitment: <run ID>`. Push it, then note the push time in the entry's first outcome line after the run.
4. **Freeze first.** The entry names a freeze tag that already exists and is pushed (`rules.md`: tag every
   freeze and every run of record), and the full commit hash that tag points to. The run uses exactly that
   commit; the working tree is clean when it starts.
5. **What an entry commits to:**
   - the freeze tag and full commit hash;
   - the SHA-256 of `constraints.txt` at that commit (`rules.md`, rule 7);
   - the sealed test split's **manifest hash** and document count, as `xon_common/manifest.py` computes them,
     and the SHA-256 of its canary string (never the string itself, never the documents);
   - where the pass criteria are written: the spec file and section, and the changelog entry that fixed them;
   - the budget cap for the run.
6. **Nothing that could be regenerated to fit.** Hash only artifacts that exist in full when the entry is posted.
   The sealed split stays outside the repository (the XonForge rules in `rules.md`); only its hashes appear here.
7. **After the run,** add an *Outcome* block under the entry, never inside its fields: the date, the verdict as
   reported, the tag of the run of record, and a link to its results folder. Anything that went differently
   from the commitment (a rerun, an interruption, a deviation) is stated there and logged in
   `CHANGELOG_EXPERIMENTS.md`.
8. **What this proves, and what it doesn't.** Git commit dates are set locally and can be anything; the
   evidence is the push to GitHub, visible in the repository's public history, and the fact that the hashes
   match the files released later. It shows the inputs were fixed before the run. It does not show the
   criteria were good ones; that is what the specs and the changelog are for.

## How to compute the hashes

```bash
git rev-parse <freeze-tag>^{commit}          # full commit hash
git show <freeze-tag>:constraints.txt | sha256sum
```

The manifest hash, document count and canary SHA-256 come from the sealed split's manifest and `SEALED.md`,
as written by XonForge's sealing step.

## Entry template

```
### <run ID>: <one-line description>

- Posted: <YYYY-MM-DD HH:MM, UTC−7>
- Freeze tag: <tag>
- Commit: <40-character hash>
- constraints.txt SHA-256: <hash>
- Sealed split: <name>, <N> documents, manifest hash <hash>
- Canary SHA-256: <hash>
- Pass criteria: <spec file, section>; fixed in the changelog entry "<entry title>"
- Budget cap: <tokens>

#### Outcome
(added after the run; see instruction 7)
```

## Planned

These runs will get entries before they start. Nothing here is a commitment yet.

- **A1 rev. 2.2, run of record:** the consistency engine's precision fixes, on a fresh sealed corpus.

## Entries

(none yet)
