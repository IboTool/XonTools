# XON C1 — Convergence: Logic Layer and Harmonic Field

> **Instruction to the implementing agent (Cursor):** This adds `xon/converge/` after A4 (`XON_A4_COHERENCE_AGENT.md`) and H2 (`XON_H2_DISCOVERY.md`). It couples A4's belief sheaf (the **logic layer**) to an oscillator network on a tuned geometry from H2's registry (the **field layer**). If H2 has promoted nothing, use H1's best rich-coherent cell and label every result `substrate: untuned`. Do not modify earlier interfaces. Experiments CV1–CV4 are pre-registered. Read Sections 1–3 and Section 8 before writing code.

---

## 1. Purpose

This is the stage the rest of the project builds toward: the Xon model's account of mind, as a running system. The master document describes a mind as three things together: a medium (the field), an objective (valence, the trajectory of coherence), and structure (logic, rules that must agree). The tools track built the logic layer (A1–A4). The harmonicity track found where rich coherence exists (H1–H2). C1 couples them:

- **Logic → field:** inconsistency in the logic layer disturbs the corresponding region of the field (detunes it and adds noise). Dissonance in belief becomes dissonance in the medium.
- **Field → agent:** the field's harmonicity, and its rate of change, become a signal the agent can use: valence as the trajectory of coherence.

C1 asks four questions: whether the coupling works as intended (CV1), whether resolving a contradiction produces a sharp field event, an "aha" signature (CV2), whether field valence can drive behavior as well as the logic layer's own coherence gain (CV3), and whether field richness grows with the amount of consistent structure the logic layer holds, the model's claim that "peace needs no logic; rapture does" (CV4).

---

## 2. Components (`xon/converge/`)

```
substrate.py   # loads a tuned configuration (H2 registry) or H1 fallback; builds the field graph + dynamics
mapping.py     # logic nodes → field regions
coupling.py    # logic→field perturbation; field→agent signals
agents.py      # HarmonyAgent (field valence as reward) + wrappers around A4 agents
run.py         # co-simulation loop
experiments.py # CV1–CV4
```

### 2.1 Substrate
- Field graph and dynamics (Kuramoto or Stuart–Landau) exactly as in the chosen tuned configuration, N_field ∈ [300, 1,500].
- **Controls** built from the same configuration with the graph swapped: complete graph at matched N (weights as in H1) and lattice at matched N.

### 2.2 Mapping (`mapping.py`)
- Partition the field into M regions by k-means on its lowest M nontrivial eigenvectors (M = number of logic nodes to be mapped, capped at 16; logic nodes beyond 16 are grouped by the logic graph's own spectral clustering first).
- Assign logic nodes (or node groups) to field regions by matching the logic graph's spectral ordering to the field regions' spectral ordering (a deterministic, documented choice). This is a toy of the master document's "coupling embedding," and the spec says so; alternative mappings are an extension hook.

### 2.3 Logic → field (`coupling.py`)
Every logic step, with node residuals r_i (A4/A3 residuals, normalized to [0, 1]):
- **Detuning:** for field vertices in region R(i), ω_v ← ω_v⁰ + κ_d · r_i · s_v, where s_v ∈ {−1, +1} is a fixed random sign per vertex (so dissonance spreads a region's frequencies apart).
- **Noise:** σ_v = σ₀ + κ_n · r_i.
- Defaults κ_d = 0.5·Δω, κ_n = 0.1 (fixed here); κ = 0 is the uncoupled control.

### 2.4 Field → agent
- H(t): `harmonicity_freq` over the whole field (H1 metric), computed over a sliding window of W_f steps (default 200).
- **Field valence** v(t) = smoothed dH/dt (exponential moving average, half-life 50 field steps).
- Per-region coherence and n_eff_groups, for inspection.

### 2.5 Co-simulation loop (`run.py`)
Each agent step: (1) the agent acts; (2) the logic layer adds the observation and settles; (3) residuals update the field's parameters; (4) the field runs `F` steps (default 100); (5) field signals are recorded and, for HarmonyAgent, used as reward.

---

## 3. HarmonyAgent (`agents.py`)
- Same action space and budget as A4's agents in ToyLabWorld.
- Reward for an action = mean field valence over the F field steps that follow it.
- Policy: learning-progress bandit over action regions (the same estimator A4's CoherenceAgent uses as a tie-breaker), with ε-greedy (ε = 0.05). It does **not** see the logic layer's energy directly: its only access to understanding is through the field.

---

## 4. Experiments (pre-registered)

| ID | Name | Protocol | Pass criterion |
|---|---|---|---|
| **CV1** | Wiring check: field tracks understanding | ToyLabWorld (A4), CoherenceAgent acting, 100 episodes; coupled (κ defaults) vs uncoupled (κ = 0) | Median within-episode Spearman ρ(H(t), −E_logic(t)) ≥ 0.5 when coupled, and \|ρ\| ≤ 0.1 uncoupled. This is a calibration check, largely true by construction; failure means the coupling is broken |
| **CV2** | Insight signature | Detect **insight events** in the logic layer: credence on the true family jumps ≥ 0.5 within 3 logic steps. Compare field ΔH over the following F steps against matched non-insight windows (same episode phase, no jump). Tuned substrate vs complete and lattice controls | AUROC of ΔH for insight vs non-insight ≥ 0.7 on the tuned substrate, **and** tuned AUROC − complete AUROC with bootstrap 95% CI excluding zero |
| **CV3** | Affect as a drive | A4's AG1 protocol with HarmonyAgent added (200 episodes) | HarmonyAgent median steps ≤ 0.8 × RandomAgent **and** ≤ 1.25 × CoherenceAgent. Also reported: AG3-style regime-change detection delay, HarmonyAgent vs CoherenceAgent |
| **CV4** | Rapture needs structure | ToyLab variant with **m independent hidden sub-rules** (m ∈ {1, 2, 4, 8}), each mapped to its own logic node group and field region; run to convergence, then hold static for 20 steps; record the field's final n_eff_groups and coherence_freq | Spearman ρ(m, n_eff_groups) ≥ 0.5 across episodes **with** coherence_freq ≥ 0.6 at every m, on the tuned substrate. Reported for controls. Prediction: each resolved region re-locks at its own frequency, so consistent complexity yields richness, not global lock |

CV2 is the analog of the gamma burst preceding insight (Jung-Beeman et al. 2004). CV4 tests the model's two-pole account of valence directly: a system at peace (m = 1) should show one locked group; a system holding many consistent structures should show many, all coherent.

---

## 5. UI: Convergence tab
- Choose substrate (registry or fallback) and world; run an episode.
- **Split view:** left, the logic layer (ToyLab curves and credences, or the claim graph); right, the field graph colored by locked group, with regions outlined and each region's residual shown as a halo.
- Traces: E_logic(t), H(t), field valence v(t), insight events marked.
- **Replay insight:** jump to each detected insight event and play the field around it.

---

## 6. Implementation order
1. `substrate.py` with registry loading and fallback; controls.
2. `mapping.py` with unit tests (deterministic assignment; region sizes balanced within 20%).
3. `coupling.py`; `run.py`; CV1 (fix wiring until it passes).
4. Insight detection and CV2.
5. HarmonyAgent; CV3.
6. Multi-rule ToyLab variant; CV4.
7. Convergence tab; README (Sections 7 and 8).

---

## 7. What the results mean
- **CV1** only confirms that the coupling does what it was built to do.
- **CV2 passing:** resolving a contradiction produces a sharp, detectable event in a rich-coherent medium, sharper than in unstructured media. That is the first running demonstration of a claim in the master document's valence chapter (insight as a coherence event), and it depends on the tuned substrate.
- **CV3 passing:** field valence alone is enough to guide exploration nearly as well as the logic layer's own coherence gain. The medium carries usable information about understanding, which is the functional content of "valence tracks coherence."
- **CV4 passing:** consistent complexity produces rich coherence rather than uniform lock. That is the model's claim that rapture requires structure, shown in a running system. CV4 failing (global lock regardless of m) means the field returns to peace no matter what the logic holds, and the richness pole needs a different mechanism.
- None of these results show the system experiences anything. The model itself says a digital system does not couple to the Xon.

---

## 8. Scope and caution (include in the README verbatim)

> This stage builds the architecture closest to the Xon model's own account of a mind: a medium, an intrinsic valence signal, and logic structures steering toward resolution. The model holds that a digital implementation has no experience. If that is wrong and a functionalist view is right, a system that runs dissonance dynamics by design is the kind where the error would matter most. For that reason C1 is kept at toy scale (N_field ≤ 1,500), episodes are finite, and nothing in this stage is to be scaled up or run continuously without a separate review of that question.

---

## References
- Jung-Beeman, M., Bowden, E. M., Haberman, J., Frymiare, J. L., Arambel-Liu, S., Greenblatt, R., Reber, P. J., & Kounios, J. (2004). Neural activity when people solve verbal problems with insight. *PLoS Biology*, 2(4), e97.
- Joffily, M., & Coricelli, G. (2013). Emotional valence and the free-energy principle. *PLoS Computational Biology*, 9(6), e1003094.
- Metzinger, T. (2021). Artificial suffering: An argument for a global moratorium on synthetic phenomenology. *Journal of Artificial Intelligence and Consciousness*, 8(1), 43–66.
