# XON A1 — Consistency Engine (rev. 2.1)

> **Instruction to the implementing agent (Cursor):** This adds `xon/llm/` to the repository (after V1–V1.2; independent of H1/H2). Do not modify V1 interfaces (`XonGraph`, `CellularSheaf`, `Dynamics`, `State`). Every LLM call must go through `xon/llm/client.py`; nothing else imports the `anthropic` package. Read Sections 0–2, 4.5, and 4.7 before writing code. **If you have already built parts of rev. 2, keep them; "Revision 2.1" below lists exactly what changes.**

**Revision 2 (September 2026).** Three scouting runs (`docs/scouting/RESULTS_*.md`) showed that the useful form of "harmonicity" is **normalized frustration energy with evidence clamped**, computed exactly. Rev. 2 added the clamped harmony score (4.3, step 2b), the anchoring rule (4.4), integrity invariants I1–I5 (4.5), and L1b.

**Revision 2.1 (September 2026).** All changes made before any L1 data was generated or run; each is logged in `CHANGELOG_EXPERIMENTS.md`.
1. **Entity-relation graph (new, Section 4.7).** Rev. 2 put claims at the vertices, where balance adds little: any odd cycle of `contradicts` edges contains a `contradicts` edge that the pairwise baseline also sees, and genuinely joint contradictions ("A older than B, B older than C, C older than A") produce no pairwise edges at all. Balance belongs on a graph of **entities**, with relational claims as edges. A1 now builds that graph and checks it for contradictory cycles. This is the capability pairwise checkers structurally lack.
2. **Engine verdict defined (Section 4.6).** Rev. 2 defined document-level verdicts only for the baselines.
3. **Plant verification made independent of the pipeline (Section 5).** Rev. 2 kept a cycle variant only if its plant appeared in the extracted relation graph, which is the graph L1 then scores; that selected documents the engine already got right.
4. **LLM settings (Section 0).** Temperature 0 is rejected by the registered models; determinism is now provided by caching plus measured variance, and thinking is set explicitly.
5. **Corpus cycle plants rebuilt** around entity relations, with matched consistent controls (Section 5); L1 localization and L1b scope adjusted (Section 6).

---

## 0. Decisions already made

| Decision | Choice |
|---|---|
| Provider | Anthropic Claude via the official `anthropic` Python SDK |
| API key | Read **only** from the `ANTHROPIC_API_KEY` environment variable. Never accepted in the UI, never written to disk, never logged. If unset, the app runs in **dry-run mode** (Section 2.4) |
| Models | Default `claude-sonnet-5` for runs of record. Sidebar options: `claude-haiku-4-5-20251001` (cheap; **not for runs of record**, because its announced retirement would make results unreproducible against the live API), `claude-opus-5-5`, `claude-fable-5-1`. Model strings live only in `config.py` |
| Sampling (rev. 2.1) | Omit `temperature`, `top_p`, `top_k` for models that reject non-default values (Sonnet 5, Opus 5.5, Fable 5.1). `client.py` passes sampling parameters only to models that accept them; the cache key records the parameters actually sent |
| Thinking (rev. 2.1) | Disabled (`thinking: {type: "disabled"}`) for claim extraction, relation scoring, and entity-relation extraction. The **LLM-direct baseline runs with adaptive thinking at default effort** (a whole-document reasoning task; a baseline is not handicapped), and is also reported with thinking disabled as a secondary number |
| Determinism (rev. 2.1) | The cache is the record: the L1 run of record is the first run; reruns replay the cache exactly. Variance is **measured** instead (Section 6, L1-var) |
| Structured output | Pydantic models via `client.messages.parse()`; fallback to JSON-schema output (`output_config`) if the installed SDK lacks `parse`. Check both against the installed SDK version and the docs at https://platform.claude.com/docs before implementing; do not trust this spec over the SDK |
| Caching | Every response cached on disk, keyed by SHA-256 of (model, system, user, schema, max_tokens, all request parameters actually sent) |
| Budget | Hard token cap per session (`llm_budget_tokens`, default 500k); calls past the cap raise `BudgetExceeded`. Sonnet 5's tokenizer produces roughly 30% more tokens for the same text, and `max_tokens` covers thinking plus output: **estimate L1's total before running the full corpus and report it** |
| Tests | Unit tests never call the API; they use recorded fixtures in `tests/fixtures/llm/` |
| Harmony computation | **Exact** (linear solve on the clamped signed Laplacian). Never computed by running V1 field dynamics |

---

## 1. Purpose

A consistency engine: Claude extracts claims from text, judges how pairs of claims relate, and extracts the relations those claims state between entities. The claims and their relations become a **signed claim graph** (a cellular sheaf with one-dimensional stalks), which determines whether the claims can all be true together, where any inconsistency lives, and, given premises, how consistent the claims are with that evidence (clamped harmony). The entity relations become an **entity-relation graph**, whose cycles reveal contradictions that exist only jointly, across three or more claims, where no single pair of claims conflicts.

That second capability is the one pairwise checkers structurally lack. It is the core engine for the agent monitor (A2), the harmony meter for the coherence agent (A4), and the source of the relation structure the learning core (A3) learns to produce.

The mathematics is classical and holds independently of the Xon model: signed-graph balance (Harary 1953), algebraic conflict (Kunegis et al. 2010), harmonic extension with boundary conditions, and cycle detection in directed graphs.

---

## 2. `client.py`

### 2.1 Interface
```python
class LLM:
    def __init__(self, model=None, cache_dir="cache/llm", budget_tokens=None): ...
    def parse(self, *, system: str, user: str, schema: type[BaseModel],
              max_tokens=2048, thinking: bool = False, tag: str = "") -> BaseModel: ...
    def text(self, *, system: str, user: str, max_tokens=1024, thinking: bool = False, tag="") -> str: ...
    @property
    def usage(self) -> dict   # input_tokens, output_tokens, calls, cache_hits, estimated_cost_usd
    dry_run: bool
```

### 2.2 Implementation
- Construct `anthropic.Anthropic()` once; it reads the key from the environment. Do not pass the key explicitly.
- `parse`: `client.messages.parse(model=..., max_tokens=..., system=..., messages=[{"role": "user", "content": user}], output_format=schema, thinking=...)`, returning the parsed object per the installed SDK's return type. Fallback: `messages.create(..., output_config={"format": {"type": "json_schema", "schema": schema.model_json_schema()}})` and `schema.model_validate_json`.
- `thinking=False` sends `thinking: {type: "disabled"}`; `thinking=True` omits the field (adaptive default). Sampling parameters per Section 0.
- Retries: 3 with exponential backoff on rate-limit and overload errors only; never retry validation errors.
- Log each call to `cache/llm/log.jsonl`: timestamp, tag, model, tokens, cache_hit, duration. **No prompt text and no key.**
- Cost estimate: a per-token price table in `config.py`, commented as needing verification against the current pricing page; used only for the sidebar's running estimate.
- `bypass_cache=True` option (used only by L1-var).

### 2.3 Fixture recorder
With `XON_LLM_RECORD=1`, every call also writes `tests/fixtures/llm/<tag>.json`. This is how dry-run fixtures are produced.

### 2.4 Dry-run mode
If the key is unset: `dry_run = True`; `parse` and `text` return fixtures matched by `tag`; a missing fixture raises `DryRunMissingFixture` with a clear message. The sidebar shows a persistent banner.

---

## 3. Claims, relations, and entity relations

### 3.1 Schemas (`schemas.py`)
```python
class Claim(BaseModel):
    id: int
    text: str                                   # atomic, self-contained
    span: str                                   # verbatim source excerpt
    kind: Literal["asserted", "premise", "quoted"]   # premise = given/assumed; quoted = attributed to someone else

class ClaimList(BaseModel):
    claims: list[Claim]

class Relation(BaseModel):
    a: int
    b: int
    relation: Literal["supports", "contradicts", "unrelated"]
    confidence: float                           # 0..1
    rationale: str                              # one sentence

class RelationList(BaseModel):
    relations: list[Relation]

class PairList(BaseModel):
    pairs: list[tuple[int, int]]

# rev. 2.1
class Entity(BaseModel):
    id: str                                     # canonical within the document, e.g. "alice"
    mentions: list[str]                         # surface forms ("Alice", "she", "the older sister")

class Attribute(BaseModel):
    key: str                                    # canonical within the document, e.g. "age", "team", "arrival_time"
    arity: Literal["binary", "multi", "unknown"]   # binary only if the text establishes exactly two possible values
    arity_span: str | None                      # the sentence establishing arity, if any

class EntityRelation(BaseModel):
    claim_id: int                               # the claim that states this relation
    attribute: str                              # Attribute.key
    kind: Literal["same", "different", "greater"]   # greater = strict order: a > b on the attribute
    a: str                                      # Entity.id
    b: str                                      # Entity.id
    confidence: float                           # 0..1

class EntityGraphSpec(BaseModel):
    entities: list[Entity]
    attributes: list[Attribute]
    relations: list[EntityRelation]
```

### 3.2 Prompts (`prompts.py`; no prompt text anywhere else)
- `EXTRACT_SYSTEM`: extract atomic factual claims, one proposition each; no opinions or questions; preserve names and numbers exactly; mark premises; mark claims attributed to someone else as `quoted`; return only the schema.
- `RELATE_SYSTEM`: for each pair, decide whether, *if A is true*, B becomes more likely (**supports**), impossible or much less likely (**contradicts**), or neither (**unrelated**). Use only the claims' content unless `use_world_knowledge=True` (sidebar toggle, default off, because the engine checks the text's own consistency).
- **`ENTITY_SYSTEM` (rev. 2.1):** given the numbered claims, (1) list the entities they mention, merging mentions that refer to the same entity; (2) list the attributes on which entities are compared, with canonical keys, and mark an attribute `binary` **only** if the text itself establishes exactly two possible values (quote the sentence in `arity_span`), `multi` if it establishes more than two, else `unknown`; (3) for every claim stating a relation between two entities on an attribute, emit one `EntityRelation`: `same` (equal on the attribute: same team, same age, arrived together), `different` (unequal: different teams), or `greater` (strict order, normalized so that "younger", "earlier", "shorter" become `greater` with the entities swapped and the attribute named consistently). Do not infer relations a claim does not state. One call per document, after claim extraction.
- Pairing: all pairs if n ≤ 25; otherwise one call for a `PairList` of pairs that bear on each other, plus a random 10% of the remaining pairs as a blind check. Batch 20 pairs per call.

### 3.3 `claims.py`
`extract_claims(text) -> ClaimList`, `score_relations(claims) -> RelationList`, `extract_entity_relations(claims) -> EntityGraphSpec`, `build_signed_graph(claims, relations) -> SignedClaimGraph` (vertices = claims; edges = supports (+1) or contradicts (−1) with weight = confidence; unrelated pairs get no edge), `build_entity_graph(spec) -> EntityGraph`.

The user may additionally mark any claim as evidence in the UI (Section 7). User-marked evidence is treated exactly like a premise and recorded in the report's `clamp_set`.

---

## 4. Consistency analysis (`consistency.py`, `entity_consistency.py`)

### 4.1 As a V1 sheaf
Each claim holds a scalar truth value x_i. An edge with sign s and weight w is the rule x_i ≈ s·x_j. Build a V1 `CellularSheaf(k=1)` with `F_head = √w`, `F_tail = s·√w`. Its Laplacian is the **signed Laplacian** L_s = D − S (S_ij = s_ij w_ij), and its Dirichlet energy is E(x) = Σ w_ij (x_i − s_ij x_j)². V1's plotting code applies unchanged. V1 diffusion may be used for visualization only, never to compute reported numbers.

### 4.2 Facts relied on (cite in code comments)
- A signed graph is **balanced** (every cycle has an even number of negative edges) iff E can reach 0 with x ≠ 0 (Harary 1953).
- The smallest eigenvalue of L_s is 0 iff the graph is balanced; otherwise it is positive and measures **algebraic conflict** (Kunegis et al. 2010).
- With clamped values on some vertices, the energy minimizer on the free vertices is the unique solution of L_ff x_f = −L_fc x_c whenever every free component touches a clamp. Each free x_i is a weighted average of s_ij x_j, so |x_i| ≤ 1 when clamps are ±1.
- **Balance is about whether *some* truth assignment works.** A single `contradicts` edge is balanced (make one claim false). A document, however, asserts its claims; that is why the verdict (4.6) has a direct clause.

### 4.3 Claim-graph analysis steps
1. **Balance:** BFS 2-coloring on the sign structure. On failure, reconstruct the **shortest frustrated cycle** from BFS parity distances.
2. **Truth assignment and harmony.**
   a. *Unclamped:* x* = eigenvector of λ_min(L_s).
   b. *Clamped:* if the clamp set is non-empty, clamp premises and user-marked evidence to +1 and solve the free vertices **exactly** on anchored components. Report **clamped harmony** H = 1 − E(x*) / (4 Σ w) ∈ [0, 1].
3. **Residuals:** per claim, r_i = Σ_j w_ij (x*_i − s_ij x*_j)²; per edge, likewise. Rank both. Use the clamped x* when it exists.
4. **Culprits (counterfactual only):** for the top-k claims by residual, remove the claim, recompute λ_min (and H if clamped), and report the change. These are labeled counterfactuals and never replace the headline scores (I2).

### 4.4 Anchoring rule
A connected component of the claim graph with no clamped vertex is **unanchored**. Its clamped energy is trivially minimized at x = 0, so harmony is undefined there. For unanchored components, report λ_min of the component's signed Laplacian and list the component under `unanchored_components`. Never assign them H = 1.

### 4.5 Integrity invariants
Each gets a unit test on hand-built graphs; tests run offline.
- **I1, evidence is never dropped.** `report.clamp_set` equals the input premises plus user-marked evidence, exactly. Re-scoring without a premise is only possible as an explicit user action producing a second report; both are shown.
- **I2, relations are never cut to improve scores.** Headline λ_min, H, residuals, and entity contradictions are computed on the full graphs as scored. Culprit removal is reported only as a counterfactual. No code path re-runs relation scoring after seeing residuals, except the explicit world-knowledge toggle, which keeps both reports.
- **I3, evidence is never rewritten.** Premise text, kind, and clamped value are immutable once extracted.
- **I4, scale invariance.** Multiplying all claim-edge weights by a constant leaves H and the residual ranking unchanged.
- **I5, no free lunch from agnosticism.** On anchored components, E(x*) ≤ E(any other assignment with the same clamps), including all-equal and all-zero.

### 4.6 Document verdict (rev. 2.1)
The engine's document-level verdict is **inconsistent** if any of the following holds:
- **(a) direct:** a `contradicts` edge with confidence ≥ 0.5 joins two claims of kind `asserted` or `premise`. `quoted` claims are excluded from this clause (a document may report that someone else said something false);
- **(b) claim-graph balance:** the claim graph is unbalanced (using edges with confidence ≥ 0.5);
- **(c) entity contradiction:** the entity-relation graph contains a contradiction (4.7) whose relations all have confidence ≥ 0.5 and all come from claims of kind `asserted` or `premise`.

The report records which clauses fired.

### 4.7 Entity-relation analysis (rev. 2.1)
Relations are grouped by attribute; each attribute is checked on its own. Only relations with confidence ≥ 0.5 from `asserted` or `premise` claims enter the verdict; all relations are shown in the UI.

1. **Equality classes.** Union-find over `same` edges. Each class is a set of entities asserted equal on the attribute.
2. **Different-within-class (all arities).** A `different` edge joining two entities in the same equality class is a contradiction: the path of `same` edges between them plus the `different` edge is a cycle with exactly one "different". Report the shortest such cycle (BFS over `same` edges).
3. **Binary parity (arity `binary` only).** Build the signed graph over equality classes with `different` edges as negative. An odd cycle of `different` edges is a contradiction (Harary balance: with exactly two values, "different" is "opposite"). Report the shortest frustrated cycle. **Not applied to `multi` or `unknown` attributes:** with three or more values, A ≠ B, B ≠ C, A ≠ C is consistent. `unknown` is treated as `multi` (the conservative choice: fewer false alarms).
4. **Order cycles.** Contract each equality class to a node; add `greater` edges as directed edges. A `greater` edge inside one class (a > b while a = b) or a directed cycle in the contracted graph (a > b > c > a) is a contradiction. Report the shortest cycle.
5. **Localization.** Each reported entity contradiction lists the claims whose relations form it, and the minimum confidence along it.

```python
@dataclass
class ConsistencyReport:
    n_claims: int; n_edges: int
    verdict_inconsistent: bool
    verdict_clauses: list[str]               # subset of {"direct", "claim_balance", "entity"}
    balanced: bool
    conflict: float                          # λ_min(L_s), evidence-free
    clamp_set: list[int]                     # premises + user-marked evidence (I1)
    harmony: float | None                    # clamped H on anchored components; None if no clamps
    unanchored_components: list[list[int]]
    component_conflict: dict[int, float]
    frustrated_cycle: list[int] | None       # claim graph, shortest, claim ids
    entity_contradictions: list[EntityContradiction]   # rev. 2.1: type, attribute, entity cycle, claim ids, min confidence
    truth_assignment: np.ndarray
    claim_residuals: np.ndarray
    edge_residuals: dict[tuple[int, int], float]
    culprits: list[tuple[int, float, float | None]]   # counterfactuals
    llm_usage: dict
```

### 4.8 Baselines
- **Pairwise-only:** inconsistent if any `contradicts` edge with confidence ≥ 0.5 joins two claims (approximates pairwise self-consistency checkers such as SelfCheckGPT; Manakul et al. 2023). No entity graph, no balance.
- **LLM-direct:** one call on the full text, "list any contradictions in this text," parsed to a schema; inconsistent if any is listed. Adaptive thinking (Section 0); also reported with thinking disabled.

---

## 5. Corpus (`scripts/make_consistency_corpus.py`)

LLM-assisted generation, cached and committed under `data/consistency/`. **60 base documents** (150–300 words) on neutral topics, each stating 1–2 explicit premises ("Assume that…" or equivalent) and containing several relational claims between named entities (ages, arrival times, teams, heights, rankings), so relational language alone is never a tell.

Each base document has **three variants**:
- **(i) consistent:** all relational claims consistent;
- **(ii) direct contradiction:** one claim and its negation planted (in half of these, the contradicted claim is a premise);
- **(iii) cycle contradiction (rev. 2.1):** three or four relational claims that are pairwise compatible but jointly impossible, of one of three types, 20 base documents per type:
  - **order cycle:** A > B, B > C, C > A on one attribute (e.g. ages, arrival order);
  - **equality break:** A same as B, B same as C, A different from C (e.g. teams), with the attribute's number of values left unstated or more than two;
  - **binary parity:** the text establishes exactly two values ("the game had two teams"), then A different from B, B different from C, A different from C.

**Matched consistent controls (rev. 2.1):** each base document's variant (i) contains the same entities and the same relation types as its variant (iii), arranged consistently: an acyclic order (A > B > C, A > C); an equality chain without a break; and, for the binary type, **three "different" relations with the text establishing three or more values** ("three teams"). The last control is the direct test of arity handling: a system that ignores arity will flag it.

**Plant verification (rev. 2.1; independent of the pipeline).** The generator records each planted sentence (and, for binary documents, the arity sentence). The check confirms each appears verbatim, after whitespace normalization, in the final document. **No extraction, relation, or entity call is involved.** Regenerate only if a planted sentence is missing, and log the count. Extraction and relation scoring are part of what L1 tests: if the engine fails to extract or relate a plant, that counts against it.

Ground truth per document: variant type, cycle type, the planted sentences, and the premises.

---

## 6. Experiments (pre-registered)

### L1 — contradiction detection and localization
- All 180 variants; the run of record is the first (cached) run. Three pairing-sample seeds for documents with n > 25 claims.
- Report precision, recall, and F1 of the document-level verdict for the consistency engine (4.6), pairwise-only, and LLM-direct (thinking on; thinking off as secondary). Report per variant type and per cycle type.
- **Localization hit rate (cycle variants):** the engine hits if a reported contradiction (entity cycle, frustrated claim cycle, or top-3 culprits) contains **at least two** of the planted claims. For LLM-direct, a hit is a listed contradiction citing at least two planted sentences.
- **Pass:**
  - document-level F1 ≥ 0.85 on direct contradictions (all methods expected to pass);
  - F1 ≥ 0.75 on **cycle** contradictions for the engine, where the pairwise baseline is expected below 0.5;
  - localization hit rate ≥ 0.7 on cycle contradictions.
- **Diagnostics (reported):** for every method using extraction, the fraction of planted sentences extracted as claims, the fraction of planted relations extracted as the planted entity relation, and the arity classification accuracy on binary documents and their controls; the false-positive rate on the "three values" binary controls, per method.

### L1b — clamped harmony (secondary)
- Consistent variants and **direct-contradiction variants only**, premises clamped. Cycle variants are excluded: entity-level contradictions do not enter the claim-graph energy, so harmony is not expected to see them (Section 10).
- **Pass:** AUC of (1 − H) separating consistent from direct-contradiction variants ≥ 0.9, and at least as high as the AUC of λ_min. When the planted contradiction involves a premise, the premise appears among the top-3 residual claims in ≥ 0.7 of documents.
- Also report the fraction of documents with unanchored components.

### L1-var — judgment variance (reported; rev. 2.1)
On the 12-document fixture subset, re-score relations and entity relations **3 times with the cache bypassed**. Report per-pair relation agreement, per-relation entity agreement, and how often each method's document verdict changes across repetitions. No pass/fail.

Ship fixtures for the 12-document subset (4 per variant, covering all three cycle types) so L1 and L1b run in dry-run mode.

---

## 7. UI: Consistency tab

Paste text or upload a file → **Analyze** → verdict with the clauses that fired; balanced flag, conflict score, and (if clamped) harmony score; claims table colored by residual, with premises marked and a checkbox to mark additional claims as evidence (re-analysis produces a new report; the previous one stays visible); claim graph view (V1 plotting: vertices = claims, edge color by sign, width by weight, vertex color by x*, clamped vertices outlined; unanchored components shaded); **entity graph view (rev. 2.1):** entities as vertices, one panel per attribute, `same` edges solid, `different` dashed, `greater` as arrows, arity shown with its source sentence, contradictory cycles highlighted with their claims listed; culprit list labeled **"counterfactual: if this claim were removed"**; expandable rationale per edge. Buttons: re-score with world knowledge on/off (both reports kept); export the report as JSON. Sidebar **LLM** section: model, world-knowledge toggle, budget and running cost, dry-run banner, clear-cache button.

---

## 8. Implementation order

1. `client.py` with cache, budget, dry-run, fixture recorder, sampling and thinking handling; unit tests on fixtures.
2. `schemas.py`, `prompts.py`.
3. `claims.py`, `consistency.py` on the V1 sheaf; unit tests with hand-built signed graphs; clamped solve, anchoring rule, invariant tests I1–I5; verdict clauses (a) and (b).
4. **`entity_consistency.py` (rev. 2.1):** unit tests on hand-built entity graphs: an order 3-cycle is a contradiction; an acyclic order is not; `a > b` with `a = b` is a contradiction; an equality break is a contradiction for every arity; three `different` edges on a triangle are a contradiction for `binary` and **not** for `multi` or `unknown`; direction normalization ("younger" ↔ "older") is correct. Verdict clause (c).
5. Consistency tab, including the entity graph view.
6. Corpus script with pipeline-independent plant verification; **stop after 12 documents (4 per variant type, all three cycle types) for human review before generating the rest**; then the full corpus.
7. L1, L1b, L1-var; fixtures.
8. Copy the three scouting records into `docs/scouting/`.
9. README: setting the key, what dry-run does, expected cost (with the Section 0 estimate), the integrity invariants, and Section 10.

---

## 9. Acceptance checklist

- [ ] With no key set, the app launches with the dry-run banner, and L1 and L1b run from fixtures.
- [ ] With a key set, a paragraph stating "Ana is older than Ben. Ben is older than Cy. Cy is older than Ana." returns `verdict_inconsistent = True` with clause `entity` and an order cycle naming all three claims, while the pairwise baseline reports nothing.
- [ ] A paragraph stating "There were three teams. Ana and Ben were on different teams, Ben and Cy were on different teams, and Ana and Cy were on different teams." is **not** flagged; the same sentences after "There were two teams." are flagged.
- [ ] With a premise that contradicts two asserted claims, `harmony < 1`, the premise ranks in the top-3 residuals, and `clamp_set` still contains it.
- [ ] Claims with no path to any premise appear under `unanchored_components` and are never assigned harmony 1.
- [ ] Invariant tests I1–I5 and the entity-graph unit tests pass offline.
- [ ] Plant verification makes no LLM call (unit test with the client mocked to raise).
- [ ] `cache/llm/log.jsonl` contains no prompt text and no key; the only occurrences of `ANTHROPIC_API_KEY` in the repo are the environment read and the README.
- [ ] All V1–V1.2 tests still pass.

---

## 10. What the results mean

If L1 passes on cycle contradictions, the engine does something pairwise checkers structurally cannot: it finds contradictions that exist only jointly, across three or more claims, and says which claims form them. That rests on classical mathematics (balance and cycle detection on the entity-relation graph) and on the quality of the LLM's relation extraction, which L1's diagnostics measure separately. It does not rest on the Xon model.

If L1b passes, the engine is also the project's **harmony meter** for claim-level consistency with evidence. Two limits are stated plainly:
- **Harmony does not see entity-level contradictions.** They are reported by clause (c) of the verdict, not by the energy. Folding them into the energy (for example, a signed Laplacian over binary attributes) is possible future work, not part of this revision.
- **The engine is only as good as its extraction.** A contradiction the LLM fails to extract as a claim or relation is invisible to the mathematics. L1's diagnostics separate extraction failures from reasoning failures, so a miss can be attributed to the right stage.

Scouting established the definition's properties on synthetic graphs, and showed that the definition rewards dropping evidence, cutting relations, and rewriting evidence, which is why the invariants in Section 4.5 are requirements.

---

## References

- Harary, F. (1953). On the notion of balance of a signed graph. *Michigan Mathematical Journal*, 2(2), 143–146.
- Kunegis, J., Schmidt, S., Lommatzsch, A., Lerner, J., De Luca, E. W., & Albayrak, S. (2010). Spectral analysis of signed graphs for clustering, prediction and visualization. *Proceedings of the 2010 SIAM International Conference on Data Mining*, 559–570.
- Manakul, P., Liusie, A., & Gales, M. J. F. (2023). SelfCheckGPT: Zero-resource black-box hallucination detection for generative large language models. *EMNLP 2023*.
- Tarjan, R. (1972). Depth-first search and linear graph algorithms. *SIAM Journal on Computing*, 1(2), 146–160.
