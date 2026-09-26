# Drift-detector scouting run (field-as-detector vs CUSUM)

*Scouting run on Claude's reimplementation (NumPy), not the V1 codebase. Toy scale. Seeds and all code in `drift_scout.zip`.*

## Protocol (fixed before any detection results)
- Graph: Sierpinski gasket, 42 vertices, 81 edges. Noise: AR(1), rho = 0.3, unit variance, per vertex.
- Scenarios: regional ramp on a BFS region of 15% of vertices (slopes 0.002 / 0.005 / 0.01 sd per step); diffuse ramp with equal total mean; transient spike (3 sd, tau = 5, 20 steps) on a region. Onset at step 500, horizon 600 (censored).
- Calibration: every threshold set on dev null to 1 upcrossing per 2,000 steps; realized rate checked on held-out null.
- Tuning: 6 settings per detector on dev (5 seeds x 4 runs); evaluation on held-out (20 seeds x 5 runs).
- SL field: dz/dt = (mu_i + i w_i) z - (1 + 0.5i)|z|^2 z + Kc sum_j A_ij (z_j - z_i), with the input modulating local gain, mu_i = mu0 + eps x_i. Natural frequencies 1 + 0.15 N(0,1), fixed.
- Harmonicity H = (locked fraction) x (number of distinct frequency groups). Locked edge: windowed PLV > 0.9 (W = 50); groups = components of size >= 3; frequencies within 0.02 are merged. The H-B detector alarms on a one-sided drop in H.
- Spectral-CUSUM grid includes EWMA pre-smoothing (lam_s = 0.02) as well as the literal unsmoothed form. This strengthens the baseline.

## Deviation log
1. **Rich-coherence gate FAILED as pre-registered** (0 of 32 regimes). Cause: the mu = 0 control is a dead field (amplitude ~1e-25) that collapses onto one mode and is trivially "locked". Also, uncoupled oscillators (Kc = 0) score median richness 2 with 15% locked, which is a metric artifact floor.
2. **Amendment** (null data only, before any drift data): the control becomes Kc = 0; the gate becomes median richness >= 3 and locked fraction >= 0.5. 9 regimes pass; the top 6 by null H form the SL grid. **H-B is therefore exploratory, not pre-registered.**

## Results (held-out; median delay in steps)
| Detector | reg .002 | reg .005 | reg .01 | dif .002 | dif .005 | dif .01 | transient FA | FA/target |
|---|---|---|---|---|---|---|---|---|
| max-CUSUM | 202 | 114 | 74 | 448 | 261 | 166 | 0.32 | 0.93 |
| sum-CUSUM | 212 | 122 | 80 | 212 | 122 | 80 | 0.31 | 1.14 |
| EWMA | 202 | 120 | 76 | 202 | 120 | 76 | 0.50 | 0.89 |
| spectral-CUSUM | **164** | **99** | **71** | 272 | 158 | 109 | 0.54 | 1.08 |
| linear field | 361 | 191 | 104 | 397 | 217 | 117 | 0.76 | 0.96 |
| SL low-mode | 227 | 120 | 74 | 356 | 196 | 128 | 0.49 | 0.83 |
| SL harmonicity | 600 (37% det.) | 600 (41%) | 600 (30%) | 600 | 600 | 600 | 0.04 | 0.86 |

Chance detection within 600 steps at the calibrated false-alarm rate is about 26-30%.

## Verdicts
- Validity (calibration): PASS (0.83-1.14 of target).
- Validity (pipeline, linear vs spectral within +/-15%): FAIL (1.84x). Diagnostic: overdamped linear fields outside the grid (alpha = 1-2) reach 1.18x / 1.11x / 1.01x. This points to a poorly chosen linear grid, not a bug.
- **H-A: FAIL.** SL/spectral = 1.38 [1.19, 1.52], 1.21 [1.12, 1.30], 1.05 [0.98, 1.13]. The SL field is slower than its linear equivalent.
- **H-B: FAIL** (exploratory). SL harmonicity/spectral = 3.7x, 6.1x, 8.5x; detection is at chance.
- Specificity/recovery for H-B: nominally pass, but meaningless, since H barely responds to anything.

## Key finding: harmonicity rises under drift
Late-drift H: null 2.10 (sd 0.52) -> 2.15 / 2.30 / 2.42 by slope. The locked fraction is unchanged (~0.79); richness rises (2.66 -> 3.13). Raising gain in one region shifts its amplitude, and through shear its frequency, so it splits off as a new "group", and the metric counts that as richer. Even a two-sided |dH| detector is weak (detection 35% / 46% / 61%).

## Secondary
- Geometry control (SL low-mode): gasket 227/120/75, lattice 234/121/77, complete 507/241/139. Locality matters; self-similarity does not beat a lattice here.
- Diffuse drift: no field advantage; spectral and max-CUSUM lose ground, as expected.
- Transient negatives: every responsive detector fires 31-76% of the time, so a 3-sd spike is indistinguishable from drift onset on residuals alone.

## Caveats
One input coupling (gain modulation), one harmonicity definition, 42 vertices, a reimplementation. Additive forcing or a different richness definition could behave differently, but any such change is a new pre-registration, not a patch to this one.
