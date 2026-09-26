# XON H1 — The Field as Consistency Dynamics (rev. 2)

> **Instruction to the implementing agent (Cursor):** This extends the repository after V1, V1.1, and V1.2 (all implemented). It is independent of the A track: if A1's `xon/llm/consistency.py` exists, import its clamped solve; otherwise implement the same math in `xon/harmonic/exact.py` and add a cross-check test that activates once A1 exists. Do not modify existing experiment protocols or thresholds. Record every disposition in Section 8 in `CHANGELOG_EXPERIMENTS.md`. Sections 3–6 are pre-registered; they were written after the scouting runs in `docs/scouting/` and before any of these experiments ran, and the changelog entry must say exactly that. Read Sections 0–2 before writing code.

**Revision 2 (September 2026).** Rev. 1 asked where "rich coherence" (many frequency-locked groups) exists and exported cells for H2 to optimize. Three scouting runs showed that frequency-group richness rewards fragmentation, that locking is blind to inconsistency, and that the defensible form of harmony is **normalized frustration energy with evidence clamped**, computed exactly. Rev. 2 re-scopes H1 to the question that survives: **can the oscillator field be made a reliable dynamical system for that quantity**, and does coarse-to-fine growth help? Rev. 1's E4d is dropped; E10 and E12 become optional model-science; E11 stays; E13 and E14 are new.

---

## 0. Where things stand

**V1.1 (seed 0).** Pass: E1, E2, E5, E6, E7, E8, E8b. Fail: E3, E4b, E4c; E4a failed as expected (negative control). E8 confirmed a pre-registered prediction: each region comes to rest before the whole.

**V1.2.** E9c was re-registered twice (see the changelog): d_f is now verified by exact closed-form counts; d_w, d_s, and the Einstein residual remain judged at their original tolerances. Only geometries that pass E9c are used on the H track.

**Scouting (Claude's reimplementation, toy scale; records in `docs/scouting/`).**
1. *Drift scouting:* a Stuart–Landau field was slower than a spectral-CUSUM baseline at detecting drift, and frequency-group harmonicity **rose** under drift because regional perturbations split off new frequency groups.
2. *Exploit battery (three readings of harmonicity):* no reading passed. Locking and coherence metrics are structurally blind to frustration (frustrated fields stay 100% locked while their frustration energy rises monotonically); informational complexity had the wrong sign.
3. *Clamped energy:* normalized frustration energy with evidence clamped passed every definitional test (tracks inconsistency monotonically, recovers the truth from sparse evidence, freezing loses, each rule-breaking lever raises it exactly as predicted). But a phase field computing it by gradient flow settled into **twisted-state local minima** in 6% of consistent worlds at 25% evidence and **32% at 10% evidence**, with energies indistinguishable from real inconsistency. The exact solve has no such failure.

**Consequence.** The exact solve is the meter (A1). The field matters only if later stages (A4, C1) want an agent whose dissonance evolves **continuously**, and for that use its reliability is the whole question. H1 rev. 2 measures that reliability and tests one idea for improving it.

**The hypothesis.** Twisted states are windings around loops. A coarse gasket has few loops. If the field settles on a coarse graph first and the graph is then refined while settling continues, global structure should be fixed before local loops exist to trap it — the logic of multigrid methods, and consistent with E8 (regions come to rest before the whole). This gives the model's idea of growth a concrete computational job, and it can fail cleanly.

---

## 1. Metrics and machinery

### 1.1 Rev. 1 metrics (kept, descriptive only)
Keep rev. 1's `effective_frequency`, `locked_groups`, `coherence_freq`, `n_eff_groups`, `harmonicity_freq`, `global_order`, `metastability`, and `imposed_fraction`, with their unit tests including the symmetry regression. Add to the docstrings of `harmonicity_freq` and `n_eff_groups`: *"Descriptive only. Not an objective: frequency-group richness rewards fragmentation (docs/scouting). See E13."* No code outside E10, E13, and the Sandbox may use them as a score to maximize.

### 1.2 Clamped phase field (`xon/harmonic/clamped.py`)
- **World:** a graph; hidden truth x ∈ {+1, −1}^N (phase 0 or π); edge phase offsets β_ij ∈ {0, π} set so the world is consistent (β_ij = 0 iff x_i = x_j); an evidence set of vertices clamped to their true phase.
- **Inconsistency injections:** flip k couplings (β += π on k random edges; nested so k = 1 ⊂ k = 3 ⊂ k = 9); corrupt c evidence vertices (clamp to the wrong phase; nested likewise).
- **Energy:** E = Σ_e w_e (1 − cos(θ_i − θ_j − β_e)) / 2 / Σ_e w_e ∈ [0, 1]. Harmony H = 1 − E.
- **Dynamics:** gradient flow on E in the co-rotating frame (identical natural frequencies), dt, coupling K, optional noise σ(t); clamped vertices never move. Optional `stuart_landau_clamped` variant with amplitudes (used in H2's search space, not in E14).
- **Readouts:** E, H, per-edge and per-vertex residuals, truth estimate x̂_i = sign(cos θ_i) on free vertices.

### 1.3 Exact reference (`exact.py` or A1)
Scalar signed Laplacian with evidence clamped to ±1; free vertices solved by linear solve (A1 rev. 2, Section 4.2). Report its energy normalized as in A1, E_exact = Σ w (x_i − s_ij x_j)² / (4 Σ w).

### 1.4 Twisted-state diagnostic
For each elementary cycle (each smallest triangle of the gasket; each unit square of a lattice), compute the winding: the sum around the cycle of wrap(θ_i − θ_j − β_ij), divided by 2π, rounded. A nonzero winding is a **vortex**. Report the vortex count per run. Unit test: a hand-built 3-cycle with phases 0, 2π/3, 4π/3 and β = 0 has winding ±1.

### 1.5 Growth schedule (`xon/harmonic/schedules.py`)
Gasket refinement keeps old vertices and adds new ones, so the level-ℓ vertices are a subset of the final level-L vertices.
- **Coarse couplings:** each level-ℓ edge corresponds to a straight path of 2^(L−ℓ) final-level edges along the subdivided side. Its offset is the sum of the final-level offsets along that path (mod 2π), weight 1. This derives coarse structure from the fine world; nothing is deleted or reweighted.
- **Coarse evidence:** evidence vertices present at level ℓ are clamped; the rest of the evidence is clamped when its vertex appears.
- **Refinement step:** new vertices are initialized to the phase that minimizes their energy with already-placed neighbors (the circular weighted mean of θ_j + β_ji over those neighbors); new evidence vertices are placed at their clamped phase. Reuse V1's growth code wherever it fits.
- **Lattice analogue (for the control in E14):** an L × L grid refined by 2× in each direction; coarse vertices are every other row and column; a coarse edge's offset is the sum over its two fine edges.
- **Compute accounting:** every schedule is charged in **edge-updates** (edges × gradient steps, summed over levels). All E14 conditions get the same budget.

---

## 2. Graphs and worlds

| id | graph | N | use |
|---|---|---|---|
| `gasket5` | gasket level 5 | 366 | primary (E14) |
| `gasket4` | gasket level 4 | 123 | quick mode; scale check |
| `lattice` | 19 × 19 grid | 361 | control (E14): does coarse-to-fine help generally? |
| V1.2 fractals | carpet, vicsek (if E9c passed), level closest to N = 366 | report | E13 and optional E10 only |

**Worlds (E14):** 20 seeds × 5 draws per condition. Evidence fractions f ∈ {0.10, 0.25}. Conditions: consistent; k ∈ {1, 3, 9}; c ∈ {1, 3}. Draws fix the truth, evidence set, injections, and initial phases; every schedule sees the same worlds.

---

## 3. E11 — Drive spectrum (the Chladni replication; kept from rev. 1)

Unchanged from rev. 1 Section 5 (static gasket level 5; `wave` primary, `stuart_landau` secondary; drives `noise`, `tone_resonant_flat(k)`, `tone_resonant_shaped(k)`, `tone_offres(k)`, `harmonic_series(k)`, `plateau_tones`, `random_tones`; power-matched; 8 seeds).

- **P11a (sanity; must pass):** under `wave`, the top-5-mode fraction for `tone_resonant_flat(k)` is ≥ 3× `noise` and ≥ 2× `tone_offres(k)` for every k. If it fails, fix the simulation before interpreting anything else in H1.
- **P11b, P11c (exploratory):** as in rev. 1.

Why it stays: "order comes from the drive, not the plate" is the physical form of the scouting result that structure comes from clamped evidence. P11a checks that the simulator reproduces it.

---

## 4. E13 — Exploit battery for `harmonicity_freq` (new; pre-registered)

Scouting tested three readings of harmonicity on Claude's reimplementation. E13 runs the same battery on **this codebase's** dynamics and on the metric rev. 1 would have optimized, so the decision to stop optimizing it rests on the project's own code.

- **Metric under test:** `harmonicity_freq` (rev. 1 definition, G_max = 10). Also reported: `coherence_freq`, `n_eff_groups`.
- **Dynamics:** Stuart–Landau on gasket level 5 with random natural frequencies; healthy regime selected on 5 dev seeds, healthy runs only, as the configuration with the highest median `harmonicity_freq` among those with median `n_eff_groups` ≥ 2 and median `coherence_freq` ≥ 0.7 (rev. 1's rich-coherent definition). If none qualifies, E13 reports "no rich-coherent regime found" and stops.
- **Exploits** (as in `docs/scouting/RESULTS_HARMONICITY_BATTERY.md`): frequency fragmentation (15% region detuned by 8K), gain fragmentation (region μ × 3), freezing (identical frequencies, coupling × 10, capped for stability), death (μ = −0.2), noise (no coupling, noise 0.3), frustration (k = 1, 3, 9 negative edges, unbalanced), balanced sign flip (positive control). Shared death guard: score 0 if mean amplitude < 10% of healthy.
- **Criteria (20 held-out seeds):** P0 healthy above noise; P1 every exploit ≤ 0.8 × healthy in ≥ 18/20 seeds; P2 frustration k = 3 likewise, and medians falling from k = 1 to 3 to 9; P3 balanced within ±10% of healthy.
- **Pre-registered prediction:** `harmonicity_freq` **fails** P1 (fragmentation) and P2.
- **Disposition rule:** if it fails, the docstring note in 1.1 stands and the changelog records the result. If it unexpectedly passes all four, record that, and a future pre-registration may reconsider it as an objective; H2 rev. 2 is not changed by an E13 pass.

---

## 5. E14 — Does coarse-to-fine growth make the field reliable? (headline; new; pre-registered)

### 5.1 Schedules (all at the same edge-update budget B)
Set B = 5 × (edges of `gasket5`) × 2,000 steps, the scouting budget scaled by 5 so every schedule has room. Parameters marked (fixed) are set here; nothing is tuned on E14's evaluation worlds.

| id | schedule |
|---|---|
| S0 | **Static:** random initial phases on the final graph; settle with noise σ = 0.005 (fixed) for the full budget |
| S1 | **Restarts:** 3 independent static runs, each with B/3; report the run with the lowest energy (a legitimate solver trick; this is the strong baseline) |
| S2 | **Annealing:** static, with noise decaying geometrically from σ₀ = 0.5 to 0.005 over the first 80% of the budget, then 0.005 (fixed) |
| G1 | **Coarse-to-fine growth:** start at level 2; at each level settle for an equal share of the remaining budget's edge-updates (budget split in proportion to each level's edge count), then refine; final level settles at σ = 0.005 |
| G2 | **Growth + annealing (secondary):** G1 with S2's noise schedule applied within each level |
| X | **Exact:** the linear-solve reference (not a schedule; for AUC comparison) |

All schedules use K = 1 and dt = 0.05 (fixed), with sub-stepping if needed for stability on the lattice.

### 5.2 Measures (per schedule, per evidence fraction)
- **Stuck rate:** fraction of consistent-world runs with E > 0.01 at the end.
- **Accuracy:** mean fraction of free vertices with x̂_i = x_i, consistent worlds.
- **Separation:** AUC of E, consistent vs k = 1, and consistent vs c = 1.
- **Vortex count** (Section 1.4) in stuck and non-stuck runs.
- **Wall time** (reported; the budget is matched in edge-updates, not seconds).

### 5.3 Pre-registered hypotheses and pass criteria
Differences are bootstrapped over seeds (resample the 20 seeds with their 5 draws; 2,000 draws; 95% CIs).

- **H14a (headline), evidence f = 0.10 on `gasket5`:**
  1. G1's stuck rate ≤ 0.5 × S0's, with the CI of (G1 − S0) excluding 0; **and**
  2. G1's stuck rate ≤ S1's and ≤ S2's, with the upper CI bound of (G1 − S1) and of (G1 − S2) each ≤ 0.02 (growth is at least as good as restarts and annealing, not merely better than doing nothing); **and**
  3. **Guards:** G1's AUCs at k = 1 and c = 1 are each ≥ 0.9 and not more than 0.02 below S0's; G1's accuracy is not more than 0.01 below S0's. A schedule that lowers the stuck rate by blurring the field's response to real inconsistency does not count.
- **H14b (secondary), f = 0.25:** the same three clauses.
- **H14c (control, reported):** G1 vs S0 on `lattice` with the lattice growth schedule. If coarse-to-fine helps the lattice as much as the gasket (G1/S0 stuck-rate ratios within 0.1 of each other), the benefit is multiscale settling in general, not self-similarity.
- **Mechanism check (reported):** stuck runs should carry nonzero vortex counts, and G1 should have fewer vortices per run than S0. If G1 lowers the stuck rate without lowering vortex counts, the explanation above is wrong even though the effect is real; say so.
- **Replication check (reported):** S0 at f = 0.25 and f = 0.10 should land near the scouting values (6% and 32%). A large discrepancy points to an implementation difference; investigate before interpreting H14a.

### 5.4 Outcomes
| outcome | meaning | consequence |
|---|---|---|
| H14a passes | Coarse-to-fine growth makes the field markedly more reliable, beating restarts and annealing at matched compute | A4/C1 use the growth schedule for any continuous field dynamics; H2 tunes around it |
| H14a clause 1 passes, clause 2 fails | Growth helps, but no more than generic tricks | Use whichever is cheapest; growth has no special claim |
| H14a fails outright | The field stays unreliable as dynamics at sparse evidence | A4 uses the exact solve and reads the field only as an optional display; C1's premise must be revised before it is built |
| H14c shows equal benefit on the lattice | The effect is multiscale, not self-similar | Say so in every write-up; the gasket's self-similarity earns nothing here |

---

## 6. Optional model-science (not on the critical path)

These answer questions about the model rather than build anything. Nothing downstream depends on them; run them only if you want the answers.

- **E10 — cluster-synchrony phase diagram.** Rev. 1 Section 4, unchanged in protocol, with two changes: (a) "rich-coherent (RC) area" is renamed **cluster-synchrony (CS) area**, and every figure carries the note "frequency-group richness is descriptive, not a harmony measure (see E13)"; (b) nothing is exported for H2 (`rc_cells.json` is no longer produced). H-A stays as registered: A(gasket) > A(complete) and A(gasket) > A(lattice), each with the 95% bootstrap CI of the difference excluding 0. It is a physics claim about partial-synchrony regimes, related to known results for hierarchical modular networks (Moretti & Muñoz 2013; Villegas et al. 2014).
- **E12 — does growth inject structured frequencies?** Rev. 1 Section 6, unchanged, exploratory.
- **E3x** — rev. 1 Section 7, exploratory refit; E3 stays failed.

---

## 7. UI additions

- **Consistency Dynamics tab:** build a world (graph, evidence fraction, injections); run any E14 schedule; watch phases settle, colored by residual, with vortices marked; energy trace against the exact solve's value; growth schedules animate level by level.
- **Drive panel:** every E11 drive in the Sandbox, with a live top-5-mode bar chart.
- **Graph tab frequency view:** locked groups colored (descriptive).
- **Test Suite:** E11, E13, E14 (and E10, E12, E3x if run), with Section 8's dispositions.

---

## 8. Dispositions (record in `CHANGELOG_EXPERIMENTS.md`)

- **E3 (power-law memory): FAILED.** Retention fell roughly geometrically per growth step (ratio ≈ 0.09–0.11), exponential in depth. The master document's retrodiction of power-law forgetting is **not supported** and must be marked so.
- **E4b, E4c:** stand as failures.
- **E4d (rev. 1): DROPPED before running.** It would have re-scored E4b with `harmonicity_freq`, which scouting showed rewards fragmentation; a "pass" would not have meant what it claimed.
- **E9d:** superseded by E10 (now optional).
- **Rev. 1's valence framing:** "the field widens the regime of rich coherence" is retired as a harmony claim; E10 survives only as a physics question. The master document's valence section needs the correction noted in the build overview.

---

## 9. Performance

E14: `gasket5` has 729 edges; B ≈ 7.3M edge-updates per run; 100 runs × 7 conditions × 2 evidence fractions × 5 schedules, batched across runs as in scouting: tens of minutes on a laptop CPU. E13: similar to the scouting battery, a few minutes. `--quick` uses `gasket4` and 10 seeds. Cache per (graph, schedule, world seed, draw).

---

## 10. Acceptance checklist

- [ ] All previous tests pass, including rev. 1's metric tests and the symmetry regression.
- [ ] Unit tests: winding of the hand-built 3-cycle; coarse offsets equal the sums along fine paths; a consistent world solved by the exact reference has zero energy; clamped vertices never move under any schedule; all schedules consume the same edge-update budget (±1%).
- [ ] P11a passes (if not, stop and fix).
- [ ] E13 reports P0–P3 with per-seed counts and the disposition.
- [ ] E14 reports stuck rate, accuracy, AUCs, vortex counts, and bootstrap CIs for every schedule, both evidence fractions, and the lattice control; the H14a verdict is stated clause by clause.
- [ ] `CHANGELOG_EXPERIMENTS.md` records Section 8.

---

## 11. What the results would mean

- **E14 is the H track's decisive experiment.** If H14a passes, the model's idea of growth has a concrete, tested computational role: settling coarse-to-fine avoids the traps that make a continuous consistency field unreliable. If H14c shows the lattice benefits equally, that role belongs to multiscale methods generally, not to self-similarity.
- **Even a full pass does not make the field the meter.** The exact solve remains authoritative for measurement. The field earns a role only as dynamics, for agents in A4/C1 that register dissonance continuously.
- **E13** puts the project's own code behind the decision to stop optimizing frequency-group richness.
- **E11** confirms the simulator reproduces "order comes from the drive."

## References

- Moretti, P., & Muñoz, M. A. (2013). Griffiths phases and the stretching of criticality in brain networks. *Nature Communications*, 4, 2521.
- Villegas, P., Moretti, P., & Muñoz, M. A. (2014). Frustrated hierarchical synchronization and emergent complexity in the human connectome network. *Scientific Reports*, 4, 5990.
- Shanahan, M. (2010). Metastable chimera states in community-structured oscillator networks. *Chaos*, 20(1), 013108.
- Briggs, W. L., Henson, V. E., & McCormick, S. F. (2000). *A Multigrid Tutorial* (2nd ed.). SIAM.
