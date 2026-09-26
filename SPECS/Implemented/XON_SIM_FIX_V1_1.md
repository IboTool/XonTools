# XON SIM — V1.1 Fix Specification

> **Instruction to the implementing agent (Cursor):** This modifies the repository built from `XON_SIM_SPEC.md` (V1). All 78 unit tests currently pass; experiments E1, E5, E7 pass; E2, E3, E4, E8 fail against pre-registered thresholds. A diagnosis (Section 1) attributes the failures to three identifiable causes, two of them in the dynamics model and one in an experiment's definition. Implement the changes below **without editing any threshold of an experiment whose protocol is unchanged**. Every experiment whose protocol *does* change is re-registered here with its reason, and the old version is kept runnable under a `_v1` suffix so results can be compared. Record every change in `CHANGELOG_EXPERIMENTS.md`.

---

## 1. Diagnosis (do not skip)

**E2** fails narrowly (purity 0.888 vs 0.9) because λ₂ of the gasket is degenerate (multiplicity 2, from the triangle's three-fold symmetry). "The" Fiedler vector is not unique; purity across the eigenspace ranges 0.839–0.970. The experiment's definition is the problem, not the claim. Fix: use the whole low eigenspace (3-way spectral clustering), which is the standard, label-free treatment of a degenerate λ₂.

**E8 and E4 (part 1)** fail because the depth-dependent damping `Γ = diag(γ(depth_i))` is diagonal in the *vertex* basis while `L` is diagonal in the *spectral* basis. They do not commute, so the wave equation no longer has clean modal decay. What survives undriven is whatever has least overlap with damped (old) vertices — a frontier-localized high-frequency mode (observed: k = 243, λ = 5 decays at γ₀ = 0.05 while the constant mode decays at the mean rate 0.153). The "collapse to the fundamental" prediction assumed commuting damping. Fix: **spectral (Rayleigh) damping** `Γ = αI + βL`, which commutes with `L` by construction, with an optional *weak* vertex-based depth sink whose strength is constrained so that modal ordering dominates.

**E4 (part 2)** fails for a deeper reason that would persist even with commuting damping: **linear** stochastic dynamics have no mechanism that prefers coherence. With Gaussian noise drive and linear damping, the stationary state has each mode's energy ∝ (noise fed) / (damping rate) — a thermal-like distribution, never a selection of few, phase-locked modes. Real resonant self-organization (Chladni figures, coupled oscillators) is nonlinear. Fix: add two **nonlinear** dynamics that share the V1 `Dynamics` interface and `State.a` — Stuart–Landau (amplitude + phase) and Kuramoto (phase only) — and re-register E4 on them. The linear E4 is kept as a negative control.

**E3** fails because the depth-energy profile under the old dynamics mostly reflects the *imposed* functional form of `γ(depth)` (steady-state energy per vertex ≈ noise/γ(depth) when coupling is weak), not the graph's intrinsic diffusion. The graph's intrinsic memory kernel *is* power-law — E7 proves it on this exact graph via return probability. Fix: re-register E3 to measure memory as **retention over growth steps of energy injected at a layer's birth**, under commuting damping, which tests the model's actual claim (depth = time of birth; coupling falls off with depth as a power law) without an arbitrary damping shape in the way.

---

## 2. Dynamics changes (`dynamics.py`)

### 2.1 Replace depth damping in `WaveDynamics` with Rayleigh damping

```
da/dt = -i c² L a  -  (α I + β L) a  -  Γ_sink a  +  F(t)
```

- `α ≥ 0` (uniform), `β ≥ 0` (spectral: mode k decays at rate α + β λ_k). Both configurable; defaults `α = 0.02, β = 0.05`.
- `Γ_sink = diag(γ_sink(depth_i))` is **optional** (default **off**). When on: `γ_sink(d) = γ_s` for `d ≤ d_max − D_sink`, else 0 (an absorbing region at the oldest `D_sink` layers; defaults `γ_s = 0.01, D_sink = 2`). **Constraint enforced in code:** `γ_s ≤ 0.1 · β · λ₂`; if the config violates it, refuse to run and print the bound. This keeps the non-commuting perturbation small relative to modal ordering.
- Keep the exact modal integrator: with `Γ_sink` off, `a ← Φ exp(−(i c² Λ + αI + βΛ) dt) Φᵀ a`. With `Γ_sink` on, use RK4 on the sparse operator.
- **Unit test (new):** with `Γ_sink` off and `F = 0`, the modal energies `|c_k|²` decay at exactly `2(α + β λ_k)` to 1e-8 relative over 500 steps.
- Remove the old `γ0, γ1, p` parameters from the wave config. Keep them available under `WaveDynamicsV1` (renamed old class) for the `_v1` experiment variants.

### 2.2 `StuartLandauDynamics` (new; nonlinear amplitude + phase)

Same interface; `State.a` complex.

```
da_i/dt = (μ − |a_i|²) a_i  −  i ω_i a_i  −  i c² (L a)_i  −  (α + β L)_i a  +  F_i(t)
```

- `μ` = limit-cycle gain (default 1.0): each node wants amplitude `√μ`; this is the nonlinearity that selects against incoherent superpositions.
- `ω_i` = natural frequency per node. Options: `identical` (all `ω₀`), `by_depth` (`ω_i = ω₀ + Δω · depth_i / d_max`), `random` (Gaussian, σ configurable). Default `by_depth` so different layers have different natural frequencies and cluster synchrony is non-trivial.
- Coupling through `L` as before; Rayleigh damping as in 2.1 (defaults `α = 0, β = 0.02` so the nonlinearity, not damping, does the selecting).
- Integrate with RK4, `dt` chosen so `c² λ_max dt < 0.5` and `μ dt < 0.1`.
- **Unit test (new):** a single isolated node from `a = 0.1` converges to `|a| = √μ` within 1e-3.
- **Unit test (new):** two nodes joined by one edge with identical ω synchronize: phase difference → 0 within tolerance.

### 2.3 `OscillatorDynamics` (implement now; was Phase 2 stub)

Kuramoto on the graph, `State.a = exp(iθ)`:

```
dθ_i/dt = ω_i  −  K Σ_j A_ij sin(θ_i − θ_j)  −  K_s sin(2θ_i)  +  σ ξ_i(t)  [ξ at frontier only when used as drive]
```

- `K` coupling (default 1.0), `K_s` sub-harmonic locking (default 0, used only by E6), `σ` noise (default 0).
- `ω_i` options as in 2.2.
- `energy = −Σ A_ij cos(θ_i − θ_j)`.
- For E6 (MaxCut), `A` is replaced by the problem's `J` and `K_s` is annealed up over the run.
- **Unit test (new):** complete graph, identical ω, `K = 2`: order parameter `r → > 0.99` within 200 steps from random phases.
- **Unit test (new):** MaxCut on a 6-node cycle reaches the known optimum (3 or 6 depending on parity convention; assert against brute force) in ≥ 8/10 seeds.

### 2.4 Registry
`dynamics/` registry entries: `wave` (2.1), `wave_v1` (old), `stuart_landau`, `oscillator`. All appear in the sidebar dropdown; none greyed out.

---

## 3. Metric additions (`metrics.py`)

- `cluster_order(g, s, clusters)`: mean over clusters of the Kuramoto order parameter computed within each cluster. `clusters` = labels from 3-way spectral clustering (Section 4.1) or `labels["subgasket"]`.
- `cluster_frequency_spread(g, s, clusters)`: number of distinct cluster mean-frequencies (estimated by phase unwrapping over the last `W` steps; frequencies within `Δ` are merged) → `n_clusters_eff`.
- `harmonicity_osc = cluster_order × log(1 + n_clusters_eff) / log(1 + n_clusters_max)` — coherence × richness for oscillator states. Expose alongside the three V1 coherence factors.
- `low_subspace_fraction(g, s, spec, k_gap)`: energy fraction in modes `k ≤ k_gap`, where `k_gap` is the index of the first spectral gap (largest ratio `λ_{k+1}/λ_k` for `k ≤ 10`). For the gasket this is `k_gap = 3` (constant + the degenerate pair).

---

## 4. Experiment changes (`experiments.py`)

Keep E1, E5, E6, E7 exactly as they are. E6 now runs (2.3).

### 4.1 E2 — re-registered (reason: degenerate λ₂)
- Compute the low eigenspace: all eigenvectors with `λ ≤ λ₂(1 + 1e-6)` plus the constant → for the gasket, 3 vectors. Run k-means (`k = 3`, 20 restarts, seeded) on the rows of that `N × 3` matrix. Purity = best matching of the 3 clusters to `labels["subgasket"]`.
- Also report the old single-vector purity and the eigenspace purity range as `_v1` numbers.
- **Pass:** 3-way purity ≥ 0.9; `frac_localized ≥ 0.25`; lattice `frac_localized < 0.05` (unchanged).

### 4.2 E3 — re-registered (reason: confounded by imposed γ(depth); the claim is about time-of-birth)
- Dynamics: `wave` (2.1) with `Γ_sink` off, `α = 0.005` (small), `β = 0.05`, no drive.
- Protocol: grow the gasket from level 3 to level 7. At each growth step `s`, inject unit energy uniformly across the vertices born at step `s` (as a one-off addition to `a`, tagged so its contribution can be tracked). Track, for each birth layer, the energy remaining **on that layer's vertices** after `k` further growth steps, `R_s(k)`, with `G` dynamics steps between growths (`G` configurable, default 200). Average `R(k)` over birth layers.
- Controls: `tree` (branch 3) and `lattice` (no growth: use elapsed time in units of `G` steps instead of growth steps).
- **Pass:** gasket `R²_powerlaw(k) > R²_exponential(k)` over `k = 1..4`; tree `R²_exponential ≥ R²_powerlaw`. Because the `α` term contributes a known factor `e^{−2αGk}`, divide it out before fitting and say so in the report.
- Keep the old protocol as `E3_v1`.

### 4.3 E4 — re-registered (reason: linear dynamics cannot select coherence; nonlinearity required)
Three sub-experiments; the headline is E4b.

- **E4a (linear negative control):** the existing E4 on `wave` (2.1). Expected to fail. Status is reported as `negative_control`; it does not affect the exit code.
- **E4b (Stuart–Landau, headline):** gasket, grow from level 2 to level 5 with `G` steps between growths, `stuart_landau` with `ω` by depth and noise drive at the frontier (`σ` default 0.05). Record `harmonicity_osc` (with clusters = 3-way spectral clustering recomputed after each growth) and the three V1 harmonicity variants at the frontier each step; 5 seeds.
  - **Controls:** (i) `μ = 0` (no limit cycle → linear; expected no rise); (ii) complete graph of the same N (expected: global synchrony, `n_clusters_eff → 1`, so harmonicity_osc *lower* than on the gasket — this tests that the *fractal structure*, not just coupling, produces the rich-and-coherent shape).
  - **Pass:** `harmonicity_osc` end − start > 0, one-sided paired test across seeds p < 0.05; **and** gasket end-value > complete-graph end-value with p < 0.05; **and** `μ = 0` control shows no significant rise. Report all four harmonicity variants; the pass is on `harmonicity_osc`, the others are reported.
- **E4c (Kuramoto):** same protocol with `oscillator`, `K = 1`, `ω` by depth. Same criteria. Reported; a pass on either E4b or E4c passes E4.

### 4.4 E8 — re-registered (reason: non-commuting damping; individuation means "peace per node" precedes global peace)
- Dynamics: `wave` (2.1), `Γ_sink` off, gasket level 5. Phase 1: no drive, `T` steps. Phase 2: noise drive at frontier.
- **Pass:** end of phase 1, `low_subspace_fraction(k_gap) ≥ 0.9` (energy has collapsed into the constant mode and the two sub-gasket modes — each node at rest in its own fundamental); report `fundamental_fraction` separately and the predicted time to global collapse `≈ 1/(2βλ₂)`. Phase 2: `low_subspace_fraction ≤ 0.5` (drive keeps it out).
- Add **E8b (with sink):** same with `Γ_sink` on at the maximum allowed `γ_s`; pass criteria identical. Verifies the weak sink does not break the collapse.
- Keep the old protocol as `E8_v1`.

### 4.5 Bookkeeping
- `run_tests.py`: negative controls never affect the exit code; `_v1` variants are run only with `--include-v1`.
- `CHANGELOG_EXPERIMENTS.md`: one entry per re-registered experiment with the date, the old criterion, the new criterion, and the one-paragraph reason from Section 1.
- Test Suite tab: show old and new results side by side when `--include-v1` results exist.

---

## 5. UI additions

- Dynamics dropdown: all four dynamics enabled; per-dynamics parameter panels (α, β, sink toggle + γ_s + D_sink for `wave`; μ, ω mode, Δω for `stuart_landau`; K, K_s, σ for `oscillator`).
- Graph tab: for `stuart_landau`/`oscillator`, color = phase (cyclic colormap), size ∝ |a|; add a **cluster overlay** (3-way spectral clusters as three hues at 30% opacity behind the vertices) so cluster synchrony is visible.
- Traces tab: add `harmonicity_osc`, `cluster_order`, `n_clusters_eff`, `low_subspace_fraction`.
- Constraints tab: replace the placeholder with a working MaxCut demo (`MaxCutProblem`) driven by `oscillator` with `K_s` annealing; show energy trace and the cut found vs the brute-force optimum for `n ≤ 20`.

---

## 6. Acceptance checklist

- [ ] All previous unit tests pass; new tests in 2.1–2.3 pass.
- [ ] `python -m xon.run_tests --out results/` runs E1–E8 (E4 = a/b/c, E8 = base + b); E6 is implemented and passes on the 10 stored MaxCut instances (optima 54, 54, 54, 55, 52, 54, 53, 55, 56, 54) in ≥ 8/10.
- [ ] E2 3-way purity reported with the `_v1` single-vector number alongside.
- [ ] E3 report shows `R(k)` for gasket and tree with both fits and the `e^{−2αGk}` correction stated.
- [ ] E4b figure: harmonicity_osc traces for gasket, complete-graph control, and `μ = 0` control on one axis.
- [ ] E8 report shows `low_subspace_fraction` and `fundamental_fraction` over both phases and the predicted global-collapse time.
- [ ] `CHANGELOG_EXPERIMENTS.md` has entries for E2, E3, E4, E8.
- [ ] Exit code 1 only on failures of E1, E2, E3, E4 (b or c), E5, E6, E7, E8; never on E4a.

---

## 7. What the results would mean

- **E8 passing** shows the "peace" prediction holds once damping respects the spectral structure, and that individuation (three sub-gaskets at rest before the whole) precedes global rest — a consequence the model had not stated and that follows from E2.
- **E3 passing** shows power-law memory over depth-as-birth-time emerges from the graph itself, not from an imposed damping shape.
- **E4b passing** would be the first genuine test of the valence derivation's (P1): that a nonlinear, driven, self-interacting structure on the Xon's graph organizes into rich, coherent cluster synchrony — and that the fractal structure, not coupling alone, is what makes it rich rather than merely synchronized. **E4b failing** with the controls behaving as expected would be real evidence against (P1) as stated, and should be reported as such.
- **E4a** is retained so that the negative result on linear dynamics stays on the record.
