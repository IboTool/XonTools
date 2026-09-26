# Harmonicity exploit battery: three readings

*Scouting run on Claude's reimplementation (NumPy), toy scale (42 vertices), 20 held-out seeds. Code and raw results in `harmonicity_battery.zip`.*

## Protocol (fixed before scoring)
- **Reading 2 (figure):** SL field on the gasket. Score = global lock x non-trivial energy fraction x modal concentration, using modes of the coupling's own signed Laplacian.
- **Reading 1 (chord):** phase oscillators, three regions at base frequencies 1:2:3 (ratios imposed by hand), n:m coupling between regions. Score = locked fraction x number of groups in the largest mutually n:m-locked set (n, m <= 4).
- **Reading 3 (informational):** SL field. Score = TSE neural complexity, Gaussian approximation, noise floor 1% of mean channel variance.
- **Shared death guard (SL readings):** score = 0 if mean amplitude < 10% of healthy.
- **Regime selection:** dev seeds 0-4, healthy runs only. Selected: reading 2 at mu0 = 1.0, Kc = 0.2 (condition L >= 0.9, F >= 0.05); reading 3 at mu0 = 1.0, Kc = 0.1 (max TSE); reading 1 at K = 0.1 (chord >= 2; all K gave chord 3).
- **Exploits:** frequency fragmentation (15% region detuned by 8Kc), gain fragmentation (region mu x3), freezing (identical frequencies, coupling x10), death (mu = -0.2), noise (no coupling, noise 0.3), frustration (k = 1/3/9 negative edges, unbalanced), balanced sign flip (positive control).
- **Criteria:** P0 healthy above noise; P1 every exploit <= 0.8 x healthy in >= 18/20 seeds; P2 frustration k = 3 likewise, and medians falling from k = 1 to 3 to 9; P3 balanced within +/-10% of healthy.

## Results (gasket, medians)
| | healthy | frag-freq | frag-gain | freeze | death | noise | frust 1 / 3 / 9 | balanced | tamper |
|---|---|---|---|---|---|---|---|---|---|
| Figure (2) | 0.365 | 0.226 (11/20) | 0.248 (11/20) | 0 (20) | 0 (20) | 0.016 (20) | .273 / .209 (13/20) / .214 | 1.03x | 0.26x |
| Chord (1) | 3.0 | 1.95 (9/20) | n/a | 1.0 (16/20) | n/a | 0 (20) | 3.0 / 2.93 (3/20) / 1.90 | 1.00x | 1.00x |
| TSE (3) | 370 | 379 (2/20) | 380 (2/20) | 132 (20) | 0 (20) | 277 (14/20) | 383 / 410 (1/20) / 433 | 0.98x | 1.00x |

(Numbers in parentheses = seeds meeting the 20% margin, out of 20.)

## Verdicts
| Reading | P0 | P1 | P2 | P3 | Overall |
|---|---|---|---|---|---|
| Figure (2) | pass | FAIL (fragmentation 11/20) | FAIL (13/20; k = 3 ~ k = 9) | pass | **FAIL**; right sign on every condition, but unreliable per seed |
| Chord (1) | pass | FAIL (fragmentation 9/20, freezing 16/20) | FAIL (3/20) | pass | **FAIL**; blind to mild frustration |
| TSE (3) | pass | FAIL (fragmentation 2/20, noise 14/20) | FAIL, **wrong sign** | pass | **FAIL**; rewards fragmentation and frustration |

On the lattice, all three fail; the figure reading loses its correct sign on fragmentation and frustration there. The lattice ran with gasket-selected parameters and no re-search, so this is not a clean geometry comparison.

P3 passes by construction for all three: the dynamics are gauge-covariant and each metric is gauge-invariant. It confirms the implementation and the choice of signed-Laplacian modes for reading 2, nothing more.

## Diagnostic (outside protocol): locking is not consistency
Frustration energy E = mean over edges of [1 - cos(theta_i - theta_j - beta_ij)]:
- **Phase field:** locked fraction stays 1.00 / 1.00 / 1.00 / 0.95 while E rises 0.065 -> 0.096 -> 0.146 -> 0.243.
- **SL field:** E rises 0.087 -> 0.115 -> 0.159 -> 0.268; the balanced flip gives 0.088, the same as healthy.

A frustrated system can be perfectly locked. Frustration lives in the *values* of the phase offsets relative to what the couplings demand, not in their *stability*. Metrics built on locking or coherence are structurally blind to it. Energy tracks it monotonically and gauge-invariantly, but energy is minimized by freezing (uniform sync gives E = 0 with positive couplings), so energy alone fails the freezing exploit.

## Caveats
Reimplementation; one healthy regime per reading, selected near a locking threshold (hence the seed-level variance); chord ratios imposed by hand; TSE via a Gaussian approximation. The frustration-energy observations are diagnostic, not pre-registered.
