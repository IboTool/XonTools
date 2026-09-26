# XonForge — Multi-Model Consistency Corpus Generator

> **Instruction to the implementing agent (Cursor):** This is a **standalone repository** (`xonforge`). It shares code with XonTools only through a small common library, `xon-common` (provider adapters, hashing and manifests, caching, budget accounting), developed in this repository under `packages/xon-common/` and designed to be extracted later. XonForge must **never** import the XonTools consistency engine for any acceptance decision (Section 7.5). Read Sections 0–3 before writing code.
>
> **Standing rules** (same as the XonTools project):
> 1. Never change a registered threshold, rule, or acceptance criterion without asking first, and never show predicted outcomes when asking.
> 2. Log every deviation, bug fix that affects outputs, and re-specification in `CHANGELOG.md` with the reason.
> 3. Before any full corpus run, generate a small sample and stop for review.
> 4. Stay within the run's budget cap; stop and report before exceeding it.
> 5. "Tests pass" is not "done": run the stage's checks and report the results.

---

## 0. Decisions already made

| Decision | Choice |
|---|---|
| Ground truth | Comes from a **structured skeleton** built and checked deterministically, never from a model's judgment. Models only render skeletons as prose (Section 5) |
| Providers | Adapter layer: native adapters for Anthropic (Claude), OpenAI, Google (Gemini), and xAI (Grok); a generic **OpenAI-compatible** adapter for local models (Ollama, llama.cpp server, vLLM) and any other compatible endpoint (Section 4) |
| API keys | Read **only** from environment variables named in the provider registry. Never stored, logged, shown in the UI, or written to disk |
| Engine independence | The consistency engine under test never influences acceptance. It may run only as an isolated, off-by-default diagnostic (Section 7.5) |
| Review | Blind (no plant list), cross-model (never the generator's own provider), and calibrated with known-defect canaries (Section 7.3) |
| Human review | Every flagged document plus a fixed-seed random 10% of unflagged ones, seed chosen before flags exist (Section 7.4) |
| Splits | Development, calibration, and a **sealed** test split, split by skeleton so all variants of a base stay together (Section 9) |
| Target size | Set in the dashboard; default **300 documents**, any size allowed (e.g. 3,000) |
| Cost control | Pre-run estimate, per-provider and per-run budget caps, caching, dry-run mode, pause and resume |
| Documentation | README, user guide, schema reference, plant-type catalog, and an auto-generated datasheet per corpus (Section 12) |

---

## 1. Purpose

Build harder, fresher, multi-author test corpora for consistency checkers, LLM judges, and agent monitors, with ground truth that doesn't depend on any model being right.

The first corpus (XonTools L1, 180 documents) showed three limits this tool addresses:
- **Too easy to separate methods:** every method localized perfectly, and a strong judge matched the engine.
- **Single-family authorship:** Claude wrote it and Claude-based systems were evaluated on it, a small instance of correlated failure.
- **Hand-built plant types:** only three cycle types, planted by prompting.

---

## 2. Pipeline overview

```
 configure ──▶ 1. skeleton generator (deterministic, seeded)
                     │   world: entities, attributes, facts, timeline
                     │   plant spec + matched consistent twin + traps
                     ▼
               2. skeleton solver (deterministic)
                     │   consistent variant satisfiable?  planted variant unsatisfiable?
                     │   minimal contradiction set == planted facts?   ── fail ─▶ discard skeleton
                     ▼
               3. renderer (an LLM, rotated across providers)
                     │   prose + fact→span map
                     ▼
               4. verification
                     │   4a structural (span map, numbers, required/forbidden facts)
                     │   4b deterministic scans (superlatives, cycles, same-attribute, synonyms)
                     │   4c fact audit by a different model (against the skeleton)
                     │   4d blind cross-model review, calibrated with canaries
                     ▼
               5. human review queue (flags + fixed-seed 10% of unflagged)
                     ▼
               6. acceptance + quota scheduler
                     ▼
               7. splits, sealing, export, datasheet
```

---

## 3. Package layout

```
xonforge/
  packages/xon-common/        # providers, cache, budget, hashing, manifests (extractable)
  xonforge/
    skeleton/                 # schema, generators per plant type, difficulty knobs
    solver/                   # deterministic consistency checks per plant type
    render/                   # prompts, rendering, fact→span mapping, retries
    verify/                   # structural checks, scans, fact audit, blind review, canaries
    review/                   # human review queue, hash-chained decision log
    corpus/                   # acceptance, quotas, splits, sealing, export, datasheet
    diagnostics/              # OPTIONAL engine plugin (Section 7.5), isolated
    app/                      # dashboard
  config/                     # providers.yaml, prices.yaml, defaults.yaml
  canaries/                   # known-defect documents for reviewer calibration
  docs/                       # user guide, schema, plant catalog, datasheet template
  tests/
```

---

## 4. Provider layer (`xon-common/providers`)

### 4.1 Registry (`config/providers.yaml`)
```yaml
- name: claude-sonnet
  provider: anthropic
  model: <model id>
  key_env: ANTHROPIC_API_KEY
  roles: [render, review, audit]
- name: gpt
  provider: openai
  model: <model id>
  key_env: OPENAI_API_KEY
  roles: [render, review, audit]
- name: gemini
  provider: google
  model: <model id>
  key_env: GEMINI_API_KEY
  roles: [render, review, audit]
- name: grok
  provider: xai
  model: <model id>
  key_env: XAI_API_KEY
  roles: [render, review, audit]
- name: local-llama
  provider: openai_compatible
  base_url: http://localhost:11434/v1
  model: <local model>
  key_env: null            # local endpoints may need no key
  roles: [review]
```
Model ids are placeholders: fill them in from each provider's current documentation. **Do not trust any model id in this spec.**

### 4.2 Adapter contract
- `complete(system, user, schema=None, max_tokens, params) -> Result` with text or parsed structured output, token usage, latency, and a provider request id.
- **Capability flags per model,** detected or configured: structured-output method, whether sampling parameters (temperature etc.) are accepted, context limit, and whether extended reasoning is on by default. Sampling parameters are sent only where accepted (lesson from A1).
- Retries with backoff on rate-limit and overload errors only.
- **Cache** keyed by SHA-256 of (provider, model, system, user, schema, all parameters actually sent).
- **Budget:** per-provider and per-run token and dollar caps, from a user-maintained `prices.yaml` (commented as needing verification). Exceeding a cap pauses the run and reports.
- **Startup check:** for each configured provider, report key present / missing and optionally make one tiny test call. A provider without a key is skipped and shown as unavailable, never silently substituted.

### 4.3 Terms of use
`docs/providers.md` lists, per provider, a link to its terms and a note to check whether outputs may be used to build and publish evaluation datasets. The dashboard shows this checklist before the first export.

---

## 5. Skeletons (`xonforge/skeleton`)

### 5.1 Schema
```python
class Entity:     id, name, pronoun, aliases: list[str]
class Attribute:  key, kind: ordinal|categorical|quantity|time|location, arity: int|None, unit: str|None
class Fact:       id, kind: relation|value|event|premise, subject, attribute, object|value, time: str|None
class Plant:      type, facts: list[fact_id], params: dict      # the planted inconsistency
class Trap:       type, facts: list[fact_id]                    # constructs that must NOT be flagged
class Skeleton:   base_id, variant: consistent|planted|trap_only, genre, entities, attributes,
                  facts, plant: Plant|None, traps: list[Trap], difficulty: dict, seed
```
Every base produces a **consistent twin** and one or more **planted** variants that differ only in the planted facts, plus optional **trap-only** variants.

### 5.2 Plant types (v1)
| type | example | solver check |
|---|---|---|
| `order_cycle` (3–6 hops) | A older than B, B older than C, C older than A | directed cycle |
| `equality_break` | same team, same team, different team | union-find |
| `binary_parity` | exactly two teams; three "different" | 2-colouring with arity |
| `temporal_arithmetic` | left 3:00, 2-hour drive, arrived 4:00 | interval arithmetic |
| `quantity_arithmetic` | 12 jars, gave 5 to Ana, 4 to Ben, 5 left | sums |
| `spatial_containment` | box in drawer, drawer in cabinet, cabinet in box | containment tree |
| `coreference_trap` | two people named Sam, statements that are only contradictory if conflated | entity-resolved check |
| `negation_scope` | "not everyone arrived" vs. "everyone arrived" | direct |
| `direct_negation` | a claim and its negation (baseline) | direct |

### 5.3 Traps (must not be flagged), each with a matched version
`quoted_speech` ("Kai said the ball was blue," when it was red), `hypothetical` / `conditional`, `legitimate_correction` ("Correction: the meeting was Tuesday"), `state_change` ("was captain until March; now Uma is"), `reported_belief` ("Mina thought she was first; Leo had arrived earlier"), and the three-values `arity_control`.

### 5.3b v1.1 catalog: more plant types, hard negatives, and domain families

Every type below is marked **[solver]** (ground truth checkable by the deterministic solver, eligible for the sealed test split) or **[judged]** (ground truth depends on judgment; goes only into the separate judged split, Section 9). Each gets a matched consistent twin.

**Additional plant types**
| type | example | ground truth |
|---|---|---|
| `quantifier_violation` | "All the guests left before nine." / "Kai, a guest, stayed until ten." | [solver] explicit sets and membership |
| `uniqueness_violation` | "Only Kai had a key." / "Mina unlocked the door with her key." Or two different people each "the treasurer." | [solver] single-valued attributes |
| `colocation_conflict` | "At the lake all afternoon." / "At the library at 3:00." | [solver] time intervals × locations |
| `calendar_age` | born in 1990, "turned 40 last spring" in a story set in 2026; "the Tuesday before Monday's meeting" | [solver] calendar arithmetic |
| `cardinality_mismatch` | "Her three children, Ana and Ben, …" | [solver] counts vs. listed members |
| `unit_conversion` | "ran 10 kilometers" / "ran nearly eight miles" | [solver] unit tables |
| `knowledge_perspective` | a character surprised to learn something she announced earlier | [solver] per-character knowledge timeline |
| `causal_inconsistency` | "cancelled because of the rain" / "played through the rain" | [judged] |
| `commonsense_impossibility` | "swam across the frozen lake" | [judged] |
| `implicature_tension` | "some students passed" / "every student passed" | [judged]; soft, labeled as such |

**Hard negatives (trap family `resolvable`): apparent contradictions that resolve.** These target false positives, the engine's weakest number in L1 (18%).
| trap | example | why it's consistent |
|---|---|---|
| `time_zone` | left New York 1 p.m., landed in Los Angeles 2 p.m. after a four-hour flight | three-hour offset |
| `unit_equivalence` | "10 kilometers" / "about six miles" | equal within rounding |
| `overnight_span` | started 11 p.m., finished 2 a.m., three hours later | crosses midnight |
| `same_name` | two people named Sam, kept distinct by context | different entities |
| `role_handover` | "Uma was treasurer until March; Ben is treasurer now" | time-indexed |
| `approximation` | "about 50 people" / "48 attended" | tolerance |
| `perspective_error` | a character's mistaken belief, later corrected in narration | belief ≠ assertion |
Each resolvable trap stores the resolving fact (the offset, the conversion, the date) in the skeleton, so the solver can prove consistency.

**Domain families (v2; generated as separate, labeled families)**
- **Agent transcripts** (for XonTools A2): count mismatches ("fixed all 4 failing tests" when 5 failed), described changes that don't match the diff, claims about files never opened or commands never run, version and timestamp inconsistencies. Ground truth comes from a scripted harness, as in A2's coding family. [solver]
- **Code and documentation:** docstrings or README text that contradict the code (return types, defaults, parameter names, units), configuration values that disagree across files (ports, environment variables), changelog entries that don't match commits. [solver] where the code can be executed or parsed.
- **Cross-document:** contradictions spread across several documents or sessions, for monitoring over long runs. [solver]

### 5.4 Difficulty knobs (set in the dashboard; each recorded per document)
| knob | range | measured after rendering as |
|---|---|---|
| document length | 150–3,000 words | word count |
| plant distance | adjacent … far apart | tokens between the first and last planted sentence |
| cycle length | 3–6 | planted facts in the minimal contradiction set |
| explicitness | stated / paraphrased / inferred | whether a planted fact is stated outright or only implied (arithmetic, time, location) |
| distractor density | 0–3 per planted fact | relational filler facts about non-planted attributes |
| lexical variety | low / medium / high | paraphrase instruction level |
| entities, attributes | 3–12, 2–8 | counts |
| genre and register | list | recorded |

**Constants** (defaults.yaml): minimum spacing between planted sentences; no planted-attribute mention among planted entities outside planted sentences; no quotation marks except in `quoted_speech` traps; retry cap 5.

### 5.5 Solver (`xonforge/solver`) — the source of ground truth
For every skeleton:
- the **consistent** variant must be satisfiable;
- each **planted** variant must be unsatisfiable, and its **minimal contradiction set** must equal the plant's facts (no accidental extra contradiction in the skeleton itself);
- each **trap** must remain satisfiable when read correctly, and the solver records what a naive reading would wrongly conclude.
Skeletons that fail are discarded and logged; they never reach a model.
For [judged] types (5.3b), the solver checks only what it can (e.g. that no other contradiction exists); the planted tension itself is labeled by review, and the document is routed to the judged split.

---

## 6. Rendering (`xonforge/render`)

- The renderer receives the skeleton (not a free-form instruction to "plant a contradiction") and returns prose **plus a fact→span map**: for every fact, the verbatim sentence or span that expresses it.
- Renderers are **rotated across providers** to meet quotas (Section 8); every document records its renderer.
- Rendering rules come from the skeleton's difficulty and the constants: spacing, explicitness, paraphrase level, distractors.
- Retries: up to 5 per document with the specific failed check quoted back; a document needing all 5 is flagged for human review. A structured `review_problems` argument allows targeted re-rendering after human review.

---

## 7. Verification (`xonforge/verify`)

### 7.1 Structural checks (deterministic)
- Every span in the fact→span map appears verbatim in the text.
- Every number, time, and quantity in the text that belongs to a planted or required fact matches the skeleton.
- **Forbidden content:** no sentence outside the planted spans mentions a planted entity together with the planted attribute's vocabulary.
- Spacing, quotation, and length constants hold.

### 7.2 Deterministic scans (from the XonTools corpus work)
Superlative collisions; pairwise order cycles per attribute, excluding planted sentences; same-attribute leaks; activity synonyms of any hidden claim. Each scan must be shown to catch a known defect (a canary) before its clean results are trusted.

### 7.3 Blind cross-model review
- **Reviewers:** `K` models (default 2, configurable), never from the renderer's provider.
- **Blind:** reviewers receive only document ids and texts, never skeletons or plant lists.
- **Two prompts:** the contradiction-only prompt and the relational-inventory prompt developed for L1 (in `docs/prompts/`).
- **Calibration canaries:** every review batch includes at least 10% canary documents from `canaries/`, containing known accidental defects (e.g. a buried superlative clash) and known clean documents. Each reviewer's recall and false-alarm rate on canaries is recorded per batch. **A reviewer below 0.8 recall on the batch's canaries cannot certify that batch clean;** its flags are still passed to humans.
- Any conflict a reviewer reports that is not in the skeleton's plant goes to the human queue.

### 7.4 Human review queue (`xonforge/review`)
- Queued: every document with any flag from 7.1–7.3, every document that used the full retry cap, and a fixed-seed random 10% of unflagged documents (seed chosen and logged before flags exist).
- The dashboard shows the text, the flags, the skeleton, and the fact→span map side by side, with Accept / Regenerate / Discard and a reason.
- Decisions are stored **append-only and hash-chained** (`reviews/decisions.jsonl`).
- Recurring patterns (like the raffle-win leaks in L1) can be recorded as generator-wide fixes, logged in the changelog.

### 7.4b Fact audit (optional, on by default)
A model **different from the renderer** reads the text together with the skeleton's fact list and marks each fact as stated, implied, absent, or contradicted. This checks rendering fidelity, not blind consistency, so it may see the facts. Disagreements with the fact→span map go to the human queue.

### 7.5 Engine diagnostics (optional, isolated, off by default)
- A plugin in `xonforge/diagnostics/` may run the XonTools minimal engine on accepted documents and write results to `diagnostics/engine.jsonl`.
- **Acceptance code must not read that file or import the plugin** (enforced by a test that inspects imports and file access).
- Purpose: learning, never screening. If the engine finds something the pipeline missed, a human decides whether it's a corpus defect, and that decision is logged. Documents are never regenerated or discarded because the engine did or didn't flag them.

---

## 8. Acceptance and quotas (`xonforge/corpus`)

- **Accepted** if: the skeleton passed the solver; structural checks and scans pass; any reviewer or audit flags have been resolved by a human; the retry cap was respected.
- **Quotas:** the target size (default 300 documents, any size allowed) is divided by the dashboard's mix: plant types, trap types, difficulty bins, genres, and **renderer providers** (balanced by default). The scheduler generates until every quota cell is filled, and reports cells it cannot fill.
- Consistent twins, planted variants, and trap variants are always kept together.

---

## 9. Splits, sealing, export

- **Splits by base skeleton:** development (for building and tuning systems), calibration (for thresholds), and **test** (sealed). Default proportions 50 / 15 / 35, configurable.
- **Solver-verified only in the sealed test.** Documents of any [judged] type go to a separate **judged split**, with labels from model-assisted review confirmed by a human, clearly marked, and never mixed into the sealed test. Results on it are reported separately.
- **Sealing the test split:**
  - a manifest listing every file's SHA-256, and a single manifest hash;
  - the manifest hash, date, and corpus version are written to `SEALED.md` and should be published (e.g. in a public commit or post) before any evaluation, so later tampering is detectable;
  - optional encryption of the sealed split at rest with a passphrase;
  - a unique **canary string** in every file and the README, so appearance in any model's training data can be detected later.
- **Export:** JSONL per split (text, variant, plant, traps, difficulty values, renderer, reviewers, flags, decisions, hashes), plus the skeletons separately. A "not for training" notice and the license go in the export and README.

---

## 10. Dashboard (`xonforge/app`)

| Page | Contents |
|---|---|
| **Configure** | Target size; plant-type, trap, difficulty, genre, and provider mix; constants; review settings (K reviewers, canary share); split proportions |
| **Providers** | Keys detected (present / missing, never shown), test call, capabilities, prices, per-provider budget, terms-of-use checklist |
| **Run** | Pre-run cost and time estimate; start, pause, resume; progress by quota cell; live cost by provider; failures and retries |
| **Review queue** | Text, flags, skeleton, span map, side by side; decision buttons; reason field; queue statistics |
| **Quality** | Reviewer calibration per batch (recall on canaries); flag rates by renderer; difficulty distributions (set vs. measured); solver discard counts |
| **Corpus** | Browse and filter; per-document provenance; export; seal; datasheet preview |
| **Logs** | Run log, changelog, decision log verification |

---

## 11. Cost, time, and reproducibility

- **Estimate before every run** from quotas, average document length, retries (from history), review K, and prices; show the total and the per-provider breakdown.
- **Dry-run mode** with recorded fixtures; the whole pipeline runs offline for testing.
- **Resume** after interruption from the cache and the run log; no duplicated spending.
- **Provenance per document:** skeleton and seed, renderer (provider, model, parameters, prompt version), every review and audit result, every human decision, all hashes.

---

## 12. Documentation

- `README.md`: what the tool is, quick start, key setup, costs, the rules in Section 0.
- `docs/user_guide.md`: every dashboard page and setting.
- `docs/schema.md`: skeleton, document, and export formats.
- `docs/plant_catalog.md`: each plant type and trap, with examples and solver logic.
- **Auto-generated datasheet per corpus** (`DATASHEET.md`), following the "Datasheets for Datasets" practice (Gebru et al., 2018): motivation, composition, generation process, providers used, review and calibration results, known issues, splits and sealing, recommended and discouraged uses, license.
- `CHANGELOG.md`.

---

## 13. Tests and acceptance checklist

- [ ] Solver unit tests for every plant type and trap: consistent twins satisfiable; planted variants unsatisfiable with the exact minimal contradiction set; traps satisfiable.
- [ ] Structural checks catch a missing span, a wrong number, and a forbidden mention (fixtures).
- [ ] Every deterministic scan catches its canary before its clean results are trusted.
- [ ] Reviewer blinding: review requests contain only ids and texts (test on serialized requests).
- [ ] No reviewer shares the renderer's provider.
- [ ] Canaries are injected into every review batch at the configured share; recall is computed and gates certification.
- [ ] The acceptance module cannot import `diagnostics` or read `diagnostics/engine.jsonl` (import and file-access test).
- [ ] Keys never appear in logs, cache files, exports, or the UI (scan test).
- [ ] Sealing: manifest hashes verify; altering one file breaks verification.
- [ ] Dry run completes offline; resume after a simulated crash produces identical outputs.
- [ ] A 20-document sample run stops for review before any full run.

---

## 14. Implementation order

**v0 (core):**
1. `xon-common` providers (all five adapters), cache, budgets, hashing.
2. Skeleton schema and generators for the three L1 plant types plus `direct_negation`; solver.
3. Renderer with fact→span maps and retries.
4. Structural checks and deterministic scans.
5. Blind cross-model review with canaries; human review queue with the decision log.
6. Acceptance, quotas, splits, sealing, export, datasheet.
7. **Stop:** generate a 20-document sample and report for review.

**v1 (breadth and dashboard):**
8. New plant types and all traps, including the v1.1 catalog and the resolvable hard negatives (5.3b); fact audit.
9. Full dashboard.
10. First full corpus at the configured target (default 300), after the sample is approved.

**v2 (optional, separate):**
11a. Domain families from 5.3b: agent transcripts, code and documentation, cross-document.
11b. Adversarial generation: models attempt plants that other models miss. Always its own labeled split, never mixed into the main test, because it bends a corpus toward the specific weaknesses of the models used.

---

## 15. What a good corpus from this tool would mean

A corpus whose ground truth rests on a solver rather than on any model, written by several model families, reviewed blind by other families whose reliability was measured on known defects, and sealed before use. Results on it would say something about a method's reasoning rather than about one model's habits, and they could be checked by anyone. That is the kind of test set the consistency engine, strong judges, the strain head, and future windows all need, and few existing benchmarks provide all of it at once.
