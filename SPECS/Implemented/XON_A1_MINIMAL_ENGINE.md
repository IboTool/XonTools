# XON A1 Addendum — Minimal Consistency Engine

> **Instruction to the implementing agent (Cursor):** This adds a minimal consistency engine to `xon/llm/` alongside A1 rev. 2.1. It reuses A1's LLM outputs (claims, relations, entity relations) and makes **no additional API calls**. It must be implemented, tested, and logged in `CHANGELOG_EXPERIMENTS.md` as a re-specification **before the L1 run of record starts**. Its L1 evaluation is **report-only**: it adds no pass/fail criterion and changes nothing about the full engine or L1's registered criteria.

---

## 1. Purpose

Two purposes, one component:

1. **An ablation.** A1's full engine combines three verdict clauses: (a) direct contradiction, (b) claim-graph balance, and (c) entity contradiction, plus an energy layer (λ_min, clamped harmony, residuals). Analysis before L1 predicted that clause (b) and the energy layer add almost nothing to the *yes/no verdict*: any odd cycle of `contradicts` edges already contains a `contradicts` edge that clause (a) sees, and localization comes directly from the contradiction itself. The minimal engine tests that prediction on real data.
2. **The core of the distilled tool.** If the prediction holds, this is the detection core a standalone safety tool would ship by default, with the energy layer as an optional module for uses that need a graded signal (the learning core, the coherence agent, drift detection).

---

## 2. Definition

**Inputs:** the same `ClaimList`, `RelationList`, and `EntityGraphSpec` A1 produces for a document (read from A1's cached outputs for the same document, model, and prompt version).

**Verdict:** the document is **inconsistent** if and only if either holds:
- **(a) direct:** a `contradicts` edge with confidence ≥ 0.5 joins two claims of kind `asserted` or `premise` (`quoted` claims excluded), exactly as in A1 Section 4.6;
- **(c) entity:** the entity-relation graph contains a contradiction (A1 Section 4.7: equality breaks for any arity, binary parity for `binary` attributes only, order cycles after contracting equality classes), whose relations all have confidence ≥ 0.5 and come from `asserted` or `premise` claims.

Same thresholds, same claim-kind rules, same unscored-pair handling as A1. **Not computed:** claim-graph balance, λ_min, clamped harmony, residuals, culprits, anchoring.

**Localization:** each reported contradiction is its own explanation:
- a direct contradiction reports its two claims;
- an entity contradiction reports the claims whose relations form the cycle, with the attribute, the entities, and the minimum confidence.

```python
@dataclass
class MinimalReport:
    verdict_inconsistent: bool
    verdict_clauses: list[str]                      # subset of {"direct", "entity"}
    direct_contradictions: list[tuple[int, int]]    # claim id pairs
    entity_contradictions: list[EntityContradiction]  # A1's type, reused
    unscored_pairs: int                             # carried from A1's relation scoring
```

---

## 3. Implementation (`xon/llm/minimal.py`)

- **Standalone:** Python standard library only. No NumPy, no SciPy, and **no import of V1** (`XonGraph`, `CellularSheaf`, or anything under the simulation packages). The algorithms are union-find, breadth-first search, and two-colouring.
- **Single source of truth for entity logic:** if A1's `entity_consistency.py` can be made dependency-free (standard library only), refactor it so that both A1 and the minimal engine import the same functions. If not, the minimal engine carries its own implementation and an equivalence test (Section 5) guards against divergence. Report which route was taken.
- **Function:** `analyze_minimal(claims, relations, entity_spec) -> MinimalReport`.
- **No LLM calls, ever.** The module does not import `xon.llm.client`.

---

## 4. L1 ablation (pre-registered, report-only)

Computed in the same L1 run, from the same cached LLM outputs as the full engine, so the two differ only in the verdict logic.

**Reported:**
- document-level precision, recall, and F1 for direct and cycle variants (overall and per cycle type), next to the full engine's;
- localization hit rate on cycle variants, using L1's rule (a reported contradiction contains at least two planted claims); the full engine's top-3 culprits have no counterpart here, which is part of what's being measured;
- the false-positive rate on consistent variants, including the three-value binary controls;
- **every document where the minimal and full verdicts differ**, with the clauses that fired in each.

**Prediction, stated in advance:** the two verdicts agree on at least 98% of the 180 documents, and every disagreement is a document where the full engine's clause (b) fired without clause (a) or (c). A disagreement of any other kind indicates a bug in one of the two implementations and must be investigated before the results are interpreted.

**No pass/fail.** The minimal engine cannot pass or fail L1, and its numbers do not affect the full engine's L1 verdict.

**Interpretation:**
- If the prediction holds, the write-up presents the minimal engine as the detection core, and justifies the energy layer by what needs a graded signal (A3, A4, C2), not by detection.
- If the full engine catches real contradictions the minimal one misses, clause (b) earns its place in detection, and the write-up says so, with the examples.

---

## 5. Tests

- **Equivalence:** on every A1 unit-test fixture and on recorded fixtures for the 12-document dry-run subset, the minimal engine's direct and entity contradictions equal the full engine's clause (a) and clause (c) outputs exactly.
- **Hand-built cases:** an order 3-cycle is flagged (entity); a single confident `contradicts` edge between asserted claims is flagged (direct); the same edge with one claim `quoted` is not; three `different` relations are flagged for a `binary` attribute and not for `multi` or `unknown`.
- **Isolation:** importing `xon.llm.minimal` in a fresh interpreter does not import NumPy, SciPy, V1, or `xon.llm.client` (test via `sys.modules`).
- **No API calls:** the module runs with the client mocked to raise.

---

## 6. UI (optional, small)

In the Consistency tab, a toggle "Minimal engine" showing its verdict and contradictions next to the full engine's, and marking any disagreement.

---

## 7. Acceptance checklist

- [ ] `xon/llm/minimal.py` exists, uses the standard library only, and passes the isolation test.
- [ ] Equivalence and hand-built tests pass; all earlier tests pass, including slow ones.
- [ ] L1's report includes the minimal engine's numbers and the list of disagreements, labeled report-only.
- [ ] Logged in `CHANGELOG_EXPERIMENTS.md` as a re-specification made before the L1 run of record, with the prediction in Section 4 recorded verbatim.
