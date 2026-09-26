# XON H2 — Discovery and Tuning: Reliable Consistency Dynamics (rev. 2)

> **Instruction to the implementing agent (Cursor):** This adds `xon/discover/` to the repository after H1 rev. 2 (`XON_H1_RICH_COHERENCE.md`). It uses H1's clamped phase field, exact reference, vortex diagnostic, and schedules (`xon/harmonic/`), and warm-starts from E14's results if present. Nothing in V1–H1 changes. Read Section 1 before writing code: H2 is an **engineering** stage, and its rules differ from the pre-registered experiment suite in specific ways.

**Revision 2 (September 2026).** Rev. 1 searched for configurations maximizing `harmonicity_freq` (frequency-group richness). Scouting showed that metric rewards fragmentation, so an optimizer on it would efficiently find fragmented states; that search is **removed** and must not be built. Rev. 2 keeps rev. 1's machinery (Optuna, held-out validation, promotion, registry) and its robustness battery (D3), and points the search at the question H1 rev. 2 opened: **settings under which the field reliably computes clamped consistency.** Rev. 1's adaptive growth (D4) is folded into the search space as growth-schedule variants.

---

## 1. Purpose, and how it differs from the experiment suite

The experiment suite tests claims about the model, so its protocols and thresholds are fixed in advance. H2 has a different goal: **find field settings that settle to the right answer reliably**, so that A4 and C1 have a dependable substrate if they use continuous field dynamics. Searching is right for that goal.

Three rules keep the search honest:

1. **The failure mode is overfitting.** Every candidate must survive held-out seeds, a larger graph, new evidence fractions, and parameter perturbation before it is promoted.
2. **Search results are existence results, not model claims.** "Schedule Y settles reliably on graph X, and replicates" is a legitimate output. "Growth is how minds avoid inconsistency traps" is not. The registry records the distinction.
3. **The objective must not be gameable (new).** The stuck rate can be lowered by making the field insensitive: enough noise, weak coupling, or a schedule that quietly unclamps evidence all produce low energy regardless of the world. Section 4.2's hard constraints block each of these. This is the exploit-battery lesson applied to search.

---

## 2. Package layout

```
xon/discover/
  __init__.py
  space.py        # search space (Section 3)
  objective.py    # objective + anti-gaming constraints (Section 4)
  search.py       # Optuna driver, pruning, parallelism, caching
  validate.py     # held-out validation and promotion (Section 5)
  registry.py     # promoted configurations (configs/tuned/*.yaml)
  robustness.py   # robustness battery for passed experiments (Section 6)
  cli.py          # xon-discover search|validate|promote|robustness
```

Dependency: `optuna` (TPE sampler, median pruner). Optional extra `pip install -e .[discover]`.

---

## 3. Search space (`space.py`)

| dimension | values |
|---|---|
| geometry | gasket, lattice, carpet, vicsek, sierpinski_p (p ∈ {3, 4}), only those that passed E9c |
| size | level with N ∈ [250, 1500] (search); validation also uses the next level up |
| dynamics | `phase` (H1's clamped gradient flow); `stuart_landau_clamped` (amplitudes may dip, which allows phase slips) |
| schedule | `static`; `restarts(r)`, r ∈ {2, 3, 5}; `anneal(σ₀, frac)`; `grow(ℓ₀, split)`; `grow_anneal`; `grow_adaptive(rule)` |
| coupling K | log-uniform [0.3, 3] |
| dt | from `dt_auto` × uniform [0.5, 1] |
| final noise σ | log-uniform [0.001, 0.02] |
| anneal σ₀ | log-uniform [0.05, 1]; `frac` (share of budget annealed) uniform [0.3, 0.9] |
| growth ℓ₀ | {1, 2, 3} (fractals); coarsest grid {3×3, 5×5} (lattice) |
| growth `split` | budget per level ∝ edges^γ, γ uniform [0, 1.5] |
| adaptive rule | `residual` (refine leaf cells with the highest local energy first), `random` (control); the 75th-percentile threshold and 5% random floor from rev. 1's D4 |
| Stuart–Landau μ | log-uniform [0.1, 3] (only for `stuart_landau_clamped`) |

**Budget:** every trial runs at H1's fixed edge-update budget B (scaled to the graph's edge count). The budget is not a search dimension; a schedule cannot buy reliability with extra compute.

Conditional parameters follow Optuna's define-by-run style.

---

## 4. Objective and anti-gaming constraints (`objective.py`)

### 4.1 Objective
For a candidate, run H1's world generator at evidence fraction f = 0.10 on **6 seeds × 5 draws** (search phase): consistent worlds for the stuck rate, plus k = 1 and c = 1 worlds for the constraints. Objective = **1 − stuck rate** (consistent worlds, E > 0.01), computed per seed and taking the **25th percentile across seeds**, which rewards candidates that work on every seed rather than on average.

### 4.2 Hard constraints (candidate scores 0 if any is violated)
- **Sensitivity:** AUC of E, consistent vs k = 1, ≥ 0.9; and consistent vs c = 1, ≥ 0.9. (A field that no longer registers real inconsistency is not reliable, just numb.)
- **Accuracy:** truth recovery on free vertices in consistent worlds ≥ 0.9.
- **Evidence clamped throughout:** clamped vertices never move, at any level or stage of any schedule (asserted in the integrator; a violation is a bug, and the trial is discarded and logged).
- **Structure fixed:** coarse couplings come only from H1's path-sum rule; no edge is deleted or reweighted by any schedule.
- **Budget:** edge-updates within ±1% of B.
- **Connected graph.**

### 4.3 Reported alongside every score
Stuck rate at f = 0.25; accuracy; both AUCs; mean vortex count; wall time; and the same candidate's stuck rate on a matched-N **lattice** (if its geometry isn't already the lattice) for context. These do not affect the score.

---

## 5. Search, validation, promotion

### 5.1 Search (`search.py`) — experiment D1
- Optuna TPE sampler, median pruner (intermediate score reported after each seed).
- **Warm start:** enqueue H1 E14's five schedules (S0, S1, S2, G1, G2) with their fixed settings as initial trials.
- Budget: `--trials` (default 300); `--jobs` for parallel workers; results cached by parameter hash so interrupted studies resume.
- Output: `results/discover/<study>/trials.csv`, an Optuna SQLite study, and fANOVA parameter importances (which choices actually control reliability).

### 5.2 Validation (`validate.py`) — experiment D2
Top 10 candidates by search objective. For each:
- **Held-out seeds:** 20 fresh seeds × 5 draws, never used in search.
- **Scale-up:** the next refinement level of the same geometry, budget scaled by edge count.
- **Evidence shift:** f ∈ {0.05, 0.25} on held-out seeds.
- **Perturbation:** each continuous parameter jittered ±20% independently (20 variants).

### 5.3 Promotion rule (fixed here)
A candidate is **promoted** if all of the following hold on held-out data:
- stuck rate at f = 0.10 ≤ 0.05;
- held-out objective ≥ 0.9 × its search objective (the overfitting check);
- every Section 4.2 constraint holds;
- stuck rate ≤ 0.10 after scale-up, and ≤ 0.10 at f = 0.05;
- ≥ 80% of perturbed variants meet the f = 0.10 stuck-rate bound.

### 5.4 Registry (`registry.py`)
Promoted configurations go to `configs/tuned/<name>.yaml` with every parameter, the validation numbers, the lattice context score, provenance (study id, trial, git hash, date), `task: clamped_consistency`, and the fixed field `claim_type: existence_by_search`. The Sandbox and the Consistency Dynamics tab get a "Load tuned configuration" dropdown.

---

## 6. Robustness battery (`robustness.py`) — experiment D3 (kept from rev. 1)

The experiments that passed are claims too, each checked at a single setting. D3 reruns each passing experiment across a small neighborhood of its settings, applying its own pass criterion unchanged.

| experiment | varied | values |
|---|---|---|
| E1 | level | 4, 5, 6 (as triples) |
| E2 | level; geometry | levels 4, 5, 6; gasket and sierpinski_3 |
| E5 | stalk dim; level; clamp fraction | {1, 2, 4}; {3, 4, 5}; {0.2, 0.3, 0.5} |
| E6 | problem size | n ∈ {20, 40, 80}, 10 instances each |
| E7 | target N | 2k, 8k, 30k |
| E8 | α, β; level; seeds | ×0.5, ×1, ×2 each; levels 4, 5, 6; 5 seeds |
| E11 P11a | level; k | levels 4, 5, 6; the registered k values |
| E14 (if H14a passed) | K; evidence fraction; level | K × {0.5, 1, 2}; f ∈ {0.05, 0.10, 0.25}; levels 4, 5, 6 |

Report a **robustness map**: the fraction of each neighborhood where the experiment passes. Classify results as **robust** (≥ 90%), **conditional** (50–90%; list the failing region), or **fragile** (< 50%). Fragile results are flagged in the master document as holding only at their original settings.

---

## 7. UI additions

- **Discovery tab:** start or resume a study; live trial table with constraint status (violations shown in red with the reason); parameter importances; best-so-far with "Load in Consistency Dynamics."
- **Validation panel:** held-out, scale-up, evidence-shift, and perturbation results per candidate, with a promote/reject verdict and the reason.
- **Tuned configurations:** dropdown listing the registry.
- **Robustness tab:** the D3 map as a grid (experiments × settings, colored pass/fail).

---

## 8. Performance

One search trial (6 seeds × 5 draws × three world types, N ≤ 1,500, fixed budget, batched): seconds to about a minute. A 300-trial study with 4 workers: a few hours. `--quick`: 60 trials, 3 seeds. Validation of 10 candidates: roughly an hour. D3: run per experiment (`xon-discover robustness --experiment E8`).

---

## 9. Acceptance checklist

- [ ] `xon-discover search --quick` runs, warm-starts from E14's schedules, and writes trials and importances.
- [ ] Constraint unit tests: a high-noise configuration that lowers the stuck rate but fails the sensitivity constraint scores 0; a schedule that moves a clamped vertex raises an error; a disconnected graph scores 0; a trial over budget scores 0.
- [ ] `validate` produces held-out, scale-up, evidence-shift, and perturbation results; `promote` writes YAML with `claim_type: existence_by_search` and `task: clamped_consistency`.
- [ ] Tuned configurations load in the Consistency Dynamics tab.
- [ ] D3 produces a robustness map with the robust / conditional / fragile classification.
- [ ] No code in `xon/discover/` imports `harmonicity_freq` or `n_eff_groups` (a test enforces this).

---

## 10. What the results mean

- **Promoted configurations** are the substrate for any continuous field dynamics in A4 and C1: settings under which the field settles to the right answer reliably, stays sensitive to real inconsistency, and never moves its evidence. They are existence results obtained by search. The exact solve remains the meter.
- **Parameter importances** show what controls reliability, for example whether growth, annealing, restarts, or amplitude dynamics matter most, which points to the next question worth pre-registering.
- **`grow_adaptive(residual)` vs `grow_adaptive(random)`** is the engineering form of rev. 1's "grow where dissonance is." If refinement guided by residuals beats random refinement at matched budget, that becomes a candidate for its own pre-registered test.
- **If nothing is promoted,** no tested setting makes the field reliable enough at sparse evidence; A4 and C1 then use the exact solve and treat the field as an optional display.
- **The D3 robustness map** says which of the model's passed results are solid. The master document should reflect it.
