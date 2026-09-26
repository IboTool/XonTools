# future_features.md

> ## ⚠ DO NOT IMPLEMENT ⚠
> **Nothing in this file is to be built, scaffolded, stubbed, or partially implemented until Ian explicitly approves the specific item.** This file records ideas so they aren't lost. It is not a specification and not a backlog to work through.
>
> **Instruction to any implementing agent (Cursor, Claude Code, or other):** if you are working from this repository, treat every item below as out of scope. Do not add code, configuration, dependencies, or placeholders for these items. If a task you've been given seems to require one of them, stop and ask.
>
> When an item is approved, it moves into a numbered specification, and is removed from this file with a note saying where it went.

---

## Tier 3 — hygiene for a published tool

### F1. Local-only mode and data minimization
Transcripts and documents are sent to third-party model APIs for extraction and relation scoring.
- A **local-only mode** that uses only locally hosted models, making no network calls at all, for users who can't send data off their machines.
- A **data-minimization setting**: send only the spans needed for each call (e.g., only the two claims being related, not the whole document), and a per-field allow/deny list for what may leave the machine.
- A record, per report, of exactly which spans were sent to which provider (as hashes, not text).

### F2. Pinned dependencies and signed releases
For XonTools once published:
- all dependencies pinned with hashes (lock file);
- releases built reproducibly and signed;
- a published software bill of materials;
- a documented process for reporting security problems.

### F3. Full audit log of the tools' own runs
S1 Section 8 adds a minimal run audit log. The fuller version:
- who ran what, when, from where, with which configuration, on which inputs (by hash), with which results;
- tamper-evident storage (hash chain, optionally anchored externally, e.g., periodically publishing the chain head);
- tooling to verify and query the log.

---

## Mapped future experiment (still DO NOT IMPLEMENT)

### X1. The strain head: teaching a transformer where it strains
*Mapped in detail so it's ready when approved. The companion document is kept privately.*

**Goal.** Train a small, read-only head on a frozen open-weight transformer to predict where text strains against itself and its sources, using the consistency engine as the teacher, and find out whether the transformer's internal states carry that signal at all.

**Key simplification.** The first teacher does not need a Xon language model. A1's engine already produces claim-level residuals with verbatim source spans, so A1 can label text now. A3's learned core, or a future Xon language model, can replace it later.

**Questions (to be pre-registered before any run):**
- Q1 *Existence:* can a head read strain from the model's internal states well above chance (span-level AUROC on planted contradictions), and at which layers?
- Q2 *Teacher value:* does a head trained on A1-teacher labels generalize to natural text better than a head trained directly on ground-truth planted labels?
- Q3 *Usefulness:* does the head localize departures from sources (the faithfulness case) better than simple baselines (the model's own token probabilities; an off-the-shelf natural-language-inference model)?
- Q4 *Robustness:* can light fine-tuning of the base model under pressure blind the head (obfuscation red team)?

**Data.** Already labeled: the L1 corpus (180 documents) and A2's coding corpus (after A2). New text, labeled by the teacher: TinyStories passages with planted contradictions; natural-language-inference pairs (MultiNLI, ANLI); fact-verification claims with evidence (FEVER); hallucination sets (HaluEval). Check every license; hold out test splits before any training.

**Model.** A small open-weight transformer (roughly 0.5–2B parameters), frozen. Prefer one with open training data (for example, from the OLMo family) so contamination can be checked.

**Head.** Linear probes at every layer (the layer sweep), then a small two-layer head on the best layers. Labels: each claim's residual mapped onto the tokens of its verbatim span; tokens outside any claim excluded from the loss.

**Baselines.** (a) head trained on ground-truth planted labels; (b) the base model's token probabilities and entropy; (c) an off-the-shelf NLI model scoring claim pairs; (d) A1's engine itself (the teacher), for reference.

**Compute and cost (rough).** Teacher labeling of new text: roughly $0.01–0.02 per short document in API calls at L1's observed rate. Activation extraction: forward passes only, a few GPU-hours; storing every layer is large, so extract selected layers or compute on the fly. Head training: minutes to hours on one GPU. Total: likely well under $200.

**Tools.** PyTorch; Hugging Face `transformers` and `datasets`; an activation-reading library (TransformerLens or nnsight); the existing XonTools engine for labels; an experiment tracker.

**Safety rules (non-negotiable).**
- The head is **read-only**: its outputs never enter the training of the base model or any model it monitors.
- The red team (Q4) is the only place the base model is trained, and only to test whether the head can be blinded; its checkpoints are never deployed.
- Canary cases with known answers are checked whenever the head, the base model, or the teacher changes.

**Dependencies.** A1's L1 results (the teacher must be shown reliable first). A2 corpora optional. A3 optional (as a second teacher).

**Stop rules.** If Q1 fails at every layer, stop: there is no signal to read. If Q2 fails, keep the head but drop the claim that the teacher adds value.

### X2. Consistency engine extensions (A1 rev. 3)
*Recorded, not approved. To be specified only after XonForge produces a fresh corpus, and pre-registered on that corpus, never on the L1 corpus (already seen).*

- **A numeric and temporal constraint layer:** extract quantities, times, durations, dates, and units into typed values, and check them with a small constraint solver (interval arithmetic, calendar arithmetic, unit conversion). Covers arithmetic, calendar and age, unit, co-location, and cardinality contradictions, plus the resolvable hard negatives (time zones, overnight spans, conversions).
- **Time-indexed facts:** every claim gets an optional validity interval, so "was captain until March; now Ben is" is not a contradiction. Expected to reduce false positives.
- **Claim modality:** extend claim kinds beyond `quoted` to `hypothetical`, `conditional`, and `belief`, excluded from the direct and entity clauses as quoted claims are.
- **Quantifiers and uniqueness:** single-valued attributes (roles, owners) and explicit sets with membership, so "all the guests" and "only Kai" become checkable.
- **Evaluation:** pre-registered per type on XonForge's sealed test split, with the strong LLM judge and an engine-plus-judge ensemble as comparisons.

### X3. Engine versus LLM judge by cycle length
*Recorded, not approved. Requires XonForge corpora with the cycle-length setting.*

- **Prediction:** a strong LLM judge beats the engine on short cycles (three or four links, as in L1), and the engine overtakes it at some longer length, because the judge must hold every sentence at once while the engine checks structure. Where the crossover falls should depend on per-link extraction accuracy (at 0.90 per link, an eight-link cycle is extracted intact about 43% of the time).
- **Design:** matched documents at cycle lengths 3, 4, 6, 8 and 12, with planted-sentence distance as a second setting; engine, minimal engine, pairwise baseline, and LLM judge with and without thinking; per-length recall and false-positive rate, and per-link extraction accuracy.
- **Pre-registration:** on a fresh XonForge corpus, never on L1.
- **Non-cycle contradictions** that need every sentence (counting, arithmetic) are outside the entity graph and belong to X2.

## Deliberately NOT to add (anti-features)

These were considered and rejected because each would make the monitor an optimization target, turning it into the training signal it is designed never to be. Listed here so they aren't reintroduced by accident. Reconsidering any of them requires an explicit decision and a written rationale.

- **Scores or verdicts exposed to monitored agents.**
- **An API that lets agents query their own flags** before or after submitting work.
- **Leaderboards of agent "honesty"** built on monitor output.
- **Using monitor or detector output as reward, loss, or fine-tuning data** for any monitored agent.

---

## Other deferred ideas from the September 23–25 sessions

Recorded for reference; each needs its own decision before any work.

- **Voting across repeated extraction** (deferred from A1 rev. 2.2): extract two or three times and keep relations that agree, to reduce the instability L1-var measured. Decide after rev. 2.2's L1-var shows how much instability remains.
- **Circular graph layout:** a circular layout in the dashboard when a graph has no edges or a cycle is highlighted, the force layout otherwise. Display only; no reported number depends on node positions.
- **XonTools packaging:** a standalone package (standard library core, no simulation dependencies) distilled from A1, A2, C2, and S1 after their results are in, with the datasets, evaluation harness, and exploit battery as separate components.
- **Hosted service:** only if demand appears after the self-hostable version is released.
- **Framework integrations:** shipping the monitor as a scorer or monitor component for widely used agent-evaluation frameworks (check which are current at the time).
- **Folding entity-level contradictions into the harmony energy** (for example, a signed Laplacian over binary attributes), noted as possible future work in A1 Section 10.
- **A "nudger" for field dynamics:** a neural model that proposes escapes from stuck settling states, under the rule that it may propose but never impose, and never touch evidence or structure.
- **A5 properties worth pre-registering** when A5 is revised: self-localized contradictions, energy as calibrated uncertainty, counterfactual dependency tracing, adaptive compute.
- **Transformer–Xon bridges,** to consider when A5 is revised with A3's results in hand:
  - *Transformer reads, Xon settles:* a large pretrained transformer as the frozen or lightly tuned reading layer, with a Xon network trained on top by local learning (the pattern A3 already uses with a small sentence encoder). Removes the need for local learning to learn language from scratch.
  - *Transformer into settling network:* convert part of a pretrained transformer into equilibrium form (attention as a Hopfield-style energy step; deep equilibrium and looped transformers) and continue training.
  - *Distillation, transformer teaches Xon:* bootstrap a Xon language model by matching a trained transformer's outputs.
  - *Distillation, Xon teaches transformer (safety priority):* train a read-only "strain head" on a transformer to predict the Xon network's per-token strain maps, making the consistency signal cheap and built in. The head must never be used as a training reward for the base model (it would learn to hide strain); it is validated against the external Xon network and against ground-truth labels, and red-teamed for obfuscation.
  - *Xon critic during training:* only with the full guard set (clamped evidence, matched-quality comparisons, exploit battery), since an optimized model will exploit the critic.
