# XON SIM — Handoff Specification and Build Prompt

> **Instruction to the implementing agent (Cursor):** Build the application described below in one pass. Follow the module boundaries, interfaces, and experiment definitions exactly; they are designed so that Phase 2 (oscillator / constraint solving) drops in without retrofitting. Prefer correctness and clarity over cleverness. Where the spec says "configurable," expose it in the UI sidebar and in `config.py`. Where the spec gives an equation, implement that equation. Do not invent additional metrics; the ones listed are deliberate. Read Sections 1–3 fully before writing any code.

---

## 0. Decisions already made (change here if needed)

| Decision | Choice |
|---|---|
| Language / runtime | Python 3.11+ |
| Core numerics | NumPy, SciPy (sparse + `eigsh`), NetworkX (topology helpers only, not for numerics) |
| UI | Streamlit; Plotly for all plots (interactive, exportable to PNG) |
| Scale | Variable. Dense `numpy.linalg.eigh` for N ≤ 3,000 vertices; `scipy.sparse.linalg.eigsh` for the lowest *k* modes above that (k configurable, default 64) |
| Default dynamics | First-order complex wave on the graph (Section 3.2). Oscillator dynamics (Section 6) shares the same interface |
| Reproducibility | Every run has a seed; every export records params, seed, and code version |
| Packaging | Single repo, `pip install -e .`, `streamlit run app.py` |

---

## 1. Purpose

This is a **testing platform** for a conceptual model of consciousness called the Xon. The model proposes that a fundamental "interior" is a growing, self-similar graph whose Laplacian spectrum determines unity, individuation, memory, valence, and thought. The platform's job is to test whether the properties the model claims actually **co-occur** when the dynamics are run — i.e., whether the model is internally coherent — and to provide a sandbox for exploring its parameters.

The platform does **not** test whether the model is true of the world. Say this in the README.

Two operating modes:

1. **Sandbox** — interactive: grow the graph, run dynamics, probe it, paint eigenmodes, tune constants, watch metrics.
2. **Test Suite** — scripted: run the eight experiments in Section 5 with fixed protocols, report pass/fail against pre-registered thresholds, export results.

---

## 2. The model in the minimum detail needed to implement it

You do not need the philosophy. You need these five claims:

1. **The interior is a graph** that **grows by refinement**: new vertices are added at a *frontier*; each vertex carries a `depth` label = the growth step at which it was created. Older vertices have smaller depth. The canonical growth rule is Sierpiński-type subdivision (triangle → three corner triangles, generalized to n-simplices).

2. **Modes are Laplacian eigenvectors.** Graph Laplacian `L = D − A`. Eigenpairs `(λ_k, φ_k)`, `0 = λ_1 ≤ λ_2 ≤ …`. Mode *frequency* `ω_k = sqrt(λ_k)`. The constant mode (`λ_1 = 0`) is called the **fundamental**.

3. **Dynamics are driven at the frontier and damped with depth.** Energy is injected at the newest vertices; damping increases with depth. This makes the system driven–dissipative. The model predicts that under these dynamics the state settles toward *coherent* configurations (few, commensurable, phase-locked modes) at the frontier while incoherent energy recedes into depth.

4. **Individuation = spectral gaps.** Nearly disconnected regions show up as small eigenvalues; the Fiedler vector (eigenvector of `λ_2`) partitions the graph along its sparsest cut. Localized eigenvectors (high inverse participation ratio) mark separate regions.

5. **Logic = a sheaf; inference = sheaf diffusion; computation = dissonance minimization.** A cellular sheaf assigns a vector space (stalk) to each vertex and linear maps to each edge; the sheaf Laplacian's kernel is the set of globally consistent states. Phase-coupled oscillators that minimize a dissonance energy solve constraint problems (oscillator Ising machines). Section 6.

---

## 3. Core architecture

```
xon/
  __init__.py
  config.py            # defaults; every tunable constant lives here
  graph.py             # XonGraph: vertices, simplices, edges, depth, layout
  growth.py            # GrowthRule interface + gasket / simplex / adaptive / tree / lattice
  spectrum.py          # cached Laplacian eigendecomposition (dense / sparse)
  dynamics.py          # Dynamics interface + WaveDynamics (Phase 1) + OscillatorDynamics (Phase 2 stub, see §6)
  metrics.py           # Metric interface + all metrics in §3.4
  sheaf.py             # CellularSheaf: stalks, restriction maps, sheaf Laplacian, diffusion, learning
  problems.py          # ConstraintProblem interface: to_ising(), to_sheaf() (Phase 2; scaffold now)
  experiments.py       # E1–E8, each a function returning ExperimentResult
  export.py            # JSON/CSV/PNG export with run metadata
  run_tests.py         # CLI: python -m xon.run_tests --out results/ [--experiments E1,E4]
app.py                 # Streamlit UI
tests/                 # pytest unit tests for graph, growth, spectrum, dynamics, metrics
README.md
pyproject.toml
```

### 3.1 `XonGraph`

```python
@dataclass
class XonGraph:
    coords: np.ndarray        # (N, d_embed) float — layout coordinates (2D for gasket; project for n>2)
    simplices: np.ndarray     # (M, n+1) int — vertex indices of the current *leaf* simplices (the frontier cells)
    edges: np.ndarray         # (E, 2) int — unique undirected edges derived from all simplices ever created
    depth: np.ndarray         # (N,) int — growth step at which each vertex was born
    parent: np.ndarray        # (N,) int — for subdivision vertices, an id of the edge/cell they were born on (-1 for seed)
    version: int              # increments on every structural change (used for spectrum cache keys)
    labels: dict[str, np.ndarray]  # optional per-vertex annotations, e.g. "subgasket" ∈ {0,1,2} at level 1

    def adjacency(self) -> scipy.sparse.csr_matrix
    def laplacian(self) -> scipy.sparse.csr_matrix
    def n(self) -> int
    def frontier_vertices(self) -> np.ndarray   # vertices with depth == depth.max()
```

- Edges must be **deduplicated**; vertices created at the same coordinates by neighboring cells must be **merged** (use rounded-coordinate keys, tolerance 1e-9).
- Keep `simplices` as the set of leaf cells so that subdivision is O(cells). Do not rebuild from scratch on each growth step.
- `labels["subgasket"]`: for the gasket rule, tag every vertex by which of the three top-level sub-gaskets it belongs to (assigned at the first subdivision, inherited thereafter). Needed by E2.

### 3.2 `GrowthRule` interface

```python
class GrowthRule(Protocol):
    name: str
    def seed(self, cfg) -> XonGraph: ...
    def grow(self, g: XonGraph, state: "State", cfg) -> tuple[XonGraph, "State"]: ...
```

`grow` must (a) add vertices/edges, (b) set their `depth` to `g.depth.max() + 1`, (c) **extend the state** to the new vertices by interpolation from the vertices they were born between (mean of endpoint amplitudes, mean phase), so dynamics continue smoothly.

Rules to implement (Phase 1):

| name | seed | grow |
|---|---|---|
| `gasket` | one triangle (3 vertices) | subdivide **every** leaf triangle into 3 corner triangles (midpoints become new vertices) |
| `simplex` | one n-simplex, `n = cfg.simplex_dim` (2 = gasket, 3 = tetrix, …) | subdivide every leaf n-simplex into n+1 corner sub-simplices |
| `adaptive` | same as `gasket`/`simplex` | subdivide only leaf cells whose mean vertex energy `|a|²` exceeds `cfg.refine_threshold × (global mean)`; **also** subdivide a random `cfg.refine_floor` fraction so growth never stalls |
| `tree` | single root | every frontier vertex spawns `cfg.branch` children |
| `lattice` | `cfg.lattice_side²` grid, all depth 0 | no growth (control) |

Layout: gasket/simplex have natural coordinates; for `simplex_dim > 2`, store full coordinates and project to 2D via the first two principal components for display. Tree: radial layout by depth. Lattice: grid.

### 3.3 `Dynamics` interface and `WaveDynamics`

```python
@dataclass
class State:
    a: np.ndarray          # (N,) complex — amplitude+phase per vertex (WaveDynamics)
                           # for OscillatorDynamics: a = exp(i*theta), |a| = 1
    t: float
    step: int

class Dynamics(Protocol):
    name: str
    def init_state(self, g: XonGraph, cfg, rng) -> State: ...
    def step(self, g: XonGraph, s: State, cfg, rng) -> State: ...
    def energy(self, g: XonGraph, s: State) -> float: ...     # scalar the dynamics minimizes (or conserves)
```

**`WaveDynamics` (Phase 1 default).** First-order complex dynamics on the graph:

```
da/dt = -i * c² * L a  -  Γ a  +  F(t)
```

- `L` = graph Laplacian (sparse).
- `Γ = diag(γ(depth_i))` with depth-dependent damping:
  `γ(d) = γ0 + γ1 * ((d_max - d) / d_max)^p`  — **older vertices (smaller d) are damped more**; `γ0, γ1, p` configurable. (`d_max` = current max depth; recompute after growth.)
- `F(t)` = drive at frontier vertices only:
  - `drive="noise"`: complex Gaussian, amplitude `cfg.drive_amp`, fresh each step.
  - `drive="tone"`: `cfg.drive_amp * exp(i ω_drive t)` where `ω_drive = sqrt(λ_k)` for a chosen mode index `k` (lets you drive a specific mode).
  - `drive="probe"`: a one-off injection at a user-chosen vertex (UI probe tool).
- Integrate with a split step: exact rotation in the eigenbasis when the spectrum is cached and N is small (`a ← Φ exp(-i c² Λ dt) Φᵀ a`), otherwise explicit RK4 on the sparse operator. Time step `cfg.dt` configurable; default chosen so that `c² λ_max dt < 0.5`.
- `energy` = `Σ |a_i|²`.

Rationale for first-order complex form: phase is explicit (needed for coherence metrics and visualization), and the oscillator dynamics in §6 uses the same `a = exp(iθ)` representation, so metrics and plots are shared.

### 3.4 Metrics (`metrics.py`)

All metrics take `(g, s, spec)` where `spec` is the cached spectrum object and return a float (or small dict). Implement exactly these; each is referenced by an experiment.

**Modal decomposition (helper):** `c = Φᵀ a` (modal coefficients), `p_k = |c_k|² / Σ|c|²` (modal energy fractions). For sparse mode use the *k* lowest modes and report the captured fraction.

1. `fundamental_fraction` = `p_1` (energy in the constant mode).
2. `spectral_entropy` = `−Σ p_k log p_k`; `n_eff` = `exp(spectral_entropy)` (**richness**: effective number of active modes).
3. `spectral_concentration` = `1 − spectral_entropy / log(K)` (K = number of modes considered). A coherence proxy.
4. `roughness` (Plomp–Levelt dissonance): for all mode pairs with `p_j p_k > ε`, `R = Σ_{j<k} sqrt(p_j p_k) · r(ω_j, ω_k)` where `r` is the Plomp–Levelt roughness curve of the frequency difference (use the Sethares parameterization: `r(x) = e^{-3.5 s x} − e^{-5.75 s x}`, `s = 0.24/(0.021 f_min + 19)`, with `x = |ω_j − ω_k|`, `f_min = min(ω_j, ω_k)`; scale ω to an audio-like range by a configurable constant so the curve is meaningful). `consonance = 1 / (1 + R)`.
5. `phase_order` = `|mean_i exp(i · arg a_i)|` (Kuramoto order parameter over vertices; for `WaveDynamics` use vertex phases).
6. **`harmonicity`** (the model's valence proxy) = `consonance × log(1 + n_eff) / log(1 + K)`. Coherence × richness. **This is a modeling choice; expose it, and let the UI switch the coherence factor between `consonance`, `spectral_concentration`, and `phase_order`.**
7. `depth_energy` → array `E[d] = Σ_{i: depth_i = d} |a_i|²`, plus `fit_powerlaw(E)` and `fit_exponential(E)` returning `R²` for each (log–log vs log–linear linear regression over depths with `E[d] > 0`).
8. `ipr` (per mode) = `Σ φ_k(i)^4 / (Σ φ_k(i)^2)^2`; `frac_localized` = fraction of modes with `ipr > 5/N`.
9. `degeneracy` → number of distinct eigenvalues (tol 1e-6), max multiplicity, fraction of eigenvalues in degenerate levels.
10. `spectral_gap_ratio` = `λ_3 / λ_2` (large ⇒ clean two-way partition); `fiedler_partition` = sign of `φ_2`; `partition_purity` = agreement between `fiedler_partition` and `labels["subgasket"]` (best of the three two-vs-one groupings).
11. `return_probability(t)` — mean diagonal of the lazy random-walk matrix power (`P = ½I + ½D⁻¹A`); `spectral_dimension_est` = `−2 × slope` of log RP vs log t over a configurable window (default t ∈ [5, 60]).

### 3.5 `spectrum.py`

- `Spectrum(g, k=None)`: if `g.n() ≤ cfg.dense_max` (default 3000) compute full dense `eigh` of the Laplacian; else `eigsh(L, k=k, sigma=-1e-4, which="LM")` (shift-invert to get the smallest). Store `lam`, `phi`, `k_used`, `captured_fraction_hint`.
- Cache keyed on `g.version`; invalidate on growth. Use `st.cache_resource` keyed by `(version, k)` in the app.
- Expose `mode(k)` for painting.

---

## 4. UI specification (`app.py`)

**Sidebar (all modes):**
- Mode: `Sandbox` | `Test Suite`
- Graph: growth rule (dropdown), `simplex_dim`, target level / max vertices, `refine_threshold`, `refine_floor`, seed
- Dynamics: dynamics (dropdown: `wave`, `oscillator` — the latter greyed out until Phase 2), `c`, `dt`, `γ0`, `γ1`, `p`, drive type, `drive_amp`, drive mode index
- Metrics: coherence factor selector for `harmonicity`; K modes for sparse
- Buttons: **Grow ×1**, **Step ×N** (N input), **Run/Pause** (continuous with `st.empty()` refresh at a configurable FPS), **Reset**, **Probe** (vertex id input → one-off injection), **Export**

**Main area — tabs:**

1. **Graph** — Plotly scatter of vertices (color = phase via cyclic colormap, size ∝ `|a|`, hover = id/depth/|a|/phase), edges as light line segments (downsample edges for display if E > 20k). Overlay toggle: paint a selected eigenmode `φ_k` instead of the state (diverging colormap), show Fiedler partition as two colors, show depth as color. Vertex click → sets probe target.
2. **Spectrum** — sorted eigenvalues vs index/N (the "staircase"); overlay of the same curve from previous growth levels (keep history); histogram of eigenvalues; degeneracy stats.
3. **Traces** — time series of `harmonicity`, `consonance`/`spectral_concentration`/`phase_order`, `n_eff`, `fundamental_fraction`, total energy, and (when a sheaf is active) consistency energy. Vertical markers at growth events.
4. **Depth** — bar/line of `E[d]` vs depth on log–log and log–linear axes with both fits and their R².
5. **Modes** — table of `(k, λ_k, ω_k, p_k, ipr_k)`; click a row to paint that mode on the Graph tab.
6. **Sheaf** — (Section 6.1) stalk dim selector, initialize maps (identity / random / learned), run diffusion, show consistency energy, run inference test (clamp % of vertices, recover the rest, report error).
7. **Constraints** — (Phase 2) problem loader and solver view; present in Phase 1 as a placeholder tab that explains what will go here.
8. **Test Suite** — checkboxes for E1–E8, seeds count, **Run selected**; results table with pass/fail and key numbers; **Export** button.

**Export (`export.py`):** writes to `results/<timestamp>_<seed>/`: `params.json` (full config + seed + git commit hash if available), `traces.csv`, `spectrum.csv`, `depth_energy.csv`, `experiments.json`, and PNGs of each tab's current figure (Plotly `write_image`; if kaleido unavailable, write HTML instead and say so).

Keep all state in `st.session_state`; never recompute the spectrum unless `g.version` changed.

---

## 5. Experiments (`experiments.py`) — pre-registered protocols

Each experiment is a function `E#(cfg, rng) -> ExperimentResult` with fields `name, passed: bool, metrics: dict, notes: str, figures: dict[str, plotly.Figure]`. Thresholds are fixed **here, before the first run**; the UI must display them next to results. If a threshold turns out to be unreasonable, change it in code with a comment explaining why — do not tune silently.

| ID | Name | Protocol | Pass criterion |
|---|---|---|---|
| **E1** | Spectral self-similarity | Gasket, levels 3, 4, 5. Sorted-eigenvalue curves resampled to 200 points on x = index/N. | Pearson r between consecutive levels ≥ 0.95; plateaus at λ ∈ {3, 5, 6} present at all levels (multiplicity > 5% of N). |
| **E2** | Individuation from structure | Gasket level 5. Fiedler vector sign vs `labels["subgasket"]`. | `partition_purity ≥ 0.9`; `frac_localized ≥ 0.25`; lattice control `frac_localized < 0.05`. |
| **E3** | Power-law memory | Gasket level 6. Run `WaveDynamics` with noise drive for `T` steps after final growth; take `E[d]`. Also run `tree` (branch 3, depth 6) and `lattice` controls. | Gasket: `R²_powerlaw > R²_exponential`. Tree: `R²_exponential ≥ R²_powerlaw` (documented expectation; if violated, report but do not fail E3). |
| **E4** | **Harmonicity rises under drive-and-sink** | Gasket, grow one level every `G` steps from level 2 to level 5 while running `WaveDynamics` with noise drive. Record `harmonicity` at the frontier (vertices with depth ≥ d_max − 1) each step. Repeat for 5 seeds. **Control:** identical run with `γ1 = 0` (no depth gradient; uniform damping `γ0`). | Frontier `harmonicity` end-mean > start-mean with one-sided paired test p < 0.05 across seeds; **and** the increase is larger than in the control by ≥ 2× (else report "gradient not attributable to sink"). |
| **E5** | Sheaf inference | Gasket level 4, stalk dim 2. Train restriction maps (Section 6.1) on 50 random consistent states generated from a hidden ground-truth sheaf. Then clamp 30% of vertices with a fresh ground-truth state and diffuse. | Recovery MSE on unclamped vertices < 25% of the MSE of the identity-map baseline. |
| **E6** | Constraint solving by dissonance minimization | *(Phase 2)* Max-cut on a random 3-regular graph with 40 nodes via `OscillatorDynamics`; compare to brute-force/known optimum. | Cut value ≥ 90% of optimum in ≥ 8/10 seeds. Skipped with status `not_implemented` in Phase 1. |
| **E7** | Spectral dimension vs simplex dimension | `simplex` rule with n = 2, 3, 4 at comparable N. `spectral_dimension_est` from return probability. | Within 0.08 of theory `d_s = 2 ln(n+1) / ln(n+3)`. |
| **E8** | The peace trap | Gasket level 5. Run with **no** drive for `T` steps; then with noise drive. | No drive: `fundamental_fraction` → ≥ 0.9 by end. With drive: stays ≤ 0.5. (Confirms the model's own prediction that without external dissonance the system collapses to the fundamental.) |

`run_tests.py` runs any subset, writes `experiments.json`, and prints a table. Exit code 0 if all run experiments passed, 1 otherwise, 2 if any raised.

---

## 6. Phase 2 scaffolding — build the interfaces now

### 6.1 `CellularSheaf` (Phase 1: implement; small)

```python
@dataclass
class CellularSheaf:
    k: int                                  # stalk dimension
    F_head: np.ndarray                      # (E, k, k) restriction map from edge to head vertex stalk
    F_tail: np.ndarray                      # (E, k, k)
    def coboundary(self, g) -> scipy.sparse.csr_matrix     # (E·k, N·k)
    def laplacian(self, g) -> scipy.sparse.csr_matrix      # δᵀ δ
    def dirichlet_energy(self, g, x: np.ndarray) -> float  # xᵀ L_F x, x shape (N·k,)
    def diffuse(self, g, x, eta, steps, clamp_mask=None, clamp_values=None) -> np.ndarray
    def learn(self, g, examples: list[np.ndarray], eta, steps, l2=1e-3) -> None
        # gradient descent on Σ_examples dirichlet_energy w.r.t. F_head, F_tail, with L2 toward current maps;
        # normalize maps per edge to unit Frobenius norm after each step to avoid the trivial zero solution.
    def consistency(self, g, x) -> float                   # dirichlet_energy / (‖x‖² + ε)
```

Ground-truth sheaf generator for E5: random orthogonal `k×k` maps per edge; consistent states = kernel vectors of the resulting sheaf Laplacian (compute via `eigsh` smallest, or construct by parallel transport from a root vertex along a spanning tree and verify).

The sheaf layer must accept the **same `XonGraph`** and read its `edges`; when the graph grows, extend `F_head/F_tail` for new edges with identity maps (so growth never breaks the sheaf).

### 6.2 `OscillatorDynamics` (Phase 1: stub with the interface; Phase 2: implement)

Same `Dynamics` interface. State `a = exp(iθ)`. Dynamics (oscillator Ising machine form):

```
dθ_i/dt = ω_i − K Σ_j J_ij sin(θ_i − θ_j) − K_s sin(2 θ_i) + noise
```

- `J` = coupling weights on graph edges (from `ConstraintProblem.to_ising()` or from the Xon graph's adjacency); `K_s` = sub-harmonic injection locking strength (binarizes phases toward {0, π}); anneal `K_s` up over the run.
- `energy = −Σ_{ij} J_ij cos(θ_i − θ_j)` (Ising energy in phase form). Note this is a **dissonance** energy: phases that fail to align under the coupling raise it.
- In Phase 1, `OscillatorDynamics.step` raises `NotImplementedError("Phase 2")` but the class exists, is registered in the dynamics dropdown, and `energy` is implemented.

### 6.3 `ConstraintProblem` (Phase 1: interface + one trivial example)

```python
class ConstraintProblem(Protocol):
    name: str
    def graph(self) -> XonGraph            # problem graph (may be a subgraph or overlay of the Xon graph)
    def to_ising(self) -> np.ndarray       # J matrix (sparse OK)
    def to_sheaf(self) -> CellularSheaf    # sheaf encoding where applicable (e.g., linear constraints)
    def score(self, state: State) -> dict  # e.g., {"cut": ..., "optimum": ..., "ratio": ...}
```

Implement `MaxCutProblem(random_regular(n, 3, seed))` fully (it is a few lines) so E6 can be wired in Phase 2 by implementing only `OscillatorDynamics.step`.

**Design rule that prevents retrofitting:** every dynamics operates on `State.a` (complex, per vertex); every metric reads `State.a`; every plot reads `State.a`. Oscillators are the special case `|a| = 1`. Do not create a separate phase-array representation.

---

## 7. Performance notes

- Sparse everywhere: `L` as CSR; matrix–vector products only. Dense `eigh` only under `dense_max`.
- Cache spectrum by `g.version`; cache modal projections per step only when a Traces tab is visible.
- RK4 with sparse matvec handles N ≈ 10⁵ at a few steps/second; the exact modal integrator is for N ≤ dense_max.
- Display downsampling: if N > 5,000 plot a random subset of vertices (keep frontier + probe target) and at most 20,000 edges; say so in the figure title.
- Use `numpy.random.default_rng(seed)` everywhere; thread the `rng` through, never use the global RNG.

---

## 8. Implementation order (for a single pass)

1. `config.py`, `graph.py`, `growth.py` (gasket + simplex + lattice + tree; adaptive last) with pytest tests: vertex counts for gasket level n must equal `(3^(n+1) + 3) / 2`; edges deduplicated; depth labels correct; subgasket labels correct.
2. `spectrum.py` with cache; test: gasket level 5 has 70 distinct eigenvalues and eigenvalue 6 has multiplicity 120 (these are known values; use them as regression tests).
3. `dynamics.py` `WaveDynamics`; test: with `Γ = 0` and `F = 0`, energy is conserved to 1e-6 over 1,000 steps under the modal integrator.
4. `metrics.py` all metrics; test: on the pure constant mode `fundamental_fraction = 1`, `n_eff = 1`, `consonance = 1`.
5. `app.py` Sandbox with Graph, Spectrum, Traces, Depth, Modes tabs and export.
6. `experiments.py` E1, E2, E3, E4, E7, E8 + `run_tests.py`; Test Suite tab.
7. `sheaf.py` + E5 + Sheaf tab.
8. `OscillatorDynamics` stub, `problems.py` with `MaxCutProblem`, Constraints placeholder tab, E6 registered as `not_implemented`.
9. README: what this is, what it is not (Section 1), how to run, how to add a growth rule / dynamics / metric / experiment (each is one class + one registry entry).

---

## 9. Acceptance checklist

- [ ] `streamlit run app.py` opens; Sandbox grows a gasket to level 5 and runs dynamics at ≥ 5 steps/s on a laptop.
- [ ] Painting eigenmode 2 on a level-5 gasket visibly partitions it into sub-gaskets.
- [ ] Spectrum tab shows the staircase with plateaus at 3, 5, 6.
- [ ] `python -m xon.run_tests --out results/` runs E1–E5, E7, E8 and writes `experiments.json`; E6 reports `not_implemented`.
- [ ] Export produces `params.json` with seed and code version, plus CSVs and figures.
- [ ] Switching the harmonicity coherence factor changes the Traces plot without recomputing the spectrum.
- [ ] `OscillatorDynamics` appears in the dynamics dropdown (disabled) and `MaxCutProblem` exists with a passing unit test for `score`.
- [ ] All pytest tests pass.

---

## 10. What the results will and will not mean (put this in the README)

If E1–E4, E7, E8 pass together, the model's core claims — self-similar spectrum, structural individuation, power-law memory, harmonicity rising under drive-and-sink, spectral dimension tracking simplex dimension, and collapse to the fundamental without external dissonance — **co-occur in one system**. That establishes internal coherence at the level of a toy model. It does **not** establish that the model describes minds or the world.

If E4 fails, the model's derivation of valence from resonance (growth as drive, depth as sink) is wrong as stated, and the platform will have earned its keep by showing that.

Harmonicity is defined by choice (Section 3.4, item 6). Report every E4 result under all three coherence factors. A conclusion that holds under only one of them is not a conclusion.

---

## 11. Extension hooks (not for the first pass)

- **Adaptive growth driven by harmonicity gradient** rather than raw energy (grow where coherence is increasing).
- **Sheaf learning online** during dynamics (restriction maps updated each step toward consistency of the live state) — the "field finds its rules by selection" experiment.
- **Depth-attenuation kernel fit**: fit `C(d)` and compare its exponent to the human forgetting exponent from Wixted & Ebbesen (1991).
- **Two-region coupling**: construct two gaskets joined by a few edges; measure cross-coherence vs coupling strength (a toy of two minds).
- **Coupling embedding**: overlay a small "connectome-like" hierarchical modular graph inside the gasket and measure mode overlap — the model's brain-coupling story as a computation.
