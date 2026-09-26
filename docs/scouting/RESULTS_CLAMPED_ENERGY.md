# Clamped-energy harmony test

*Pre-registered in chat before running. Claude's reimplementation (NumPy). Gasket, 42 vertices; 20 seeds x 5 draws = 100 runs per condition. Code and results in `clamped_energy.zip`.*

## Protocol
- **World:** each seed draws a hidden truth x in {+1, -1}^N (phase 0 or pi); couplings match it, so the world is consistent. 25% of vertices are evidence, clamped to their true phase.
- **Field:** gradient flow on normalized frustration energy E = sum_e w_e (1 - cos(th_i - th_j - beta_e)) / 2 / sum_e w_e, with K = 1, dt = 0.05, 2,000 steps, noise 0.005. Evidence never moves. Harmony H = 1 - E.
- **Conditions:** consistent; k = 1/3/9 flipped couplings; c = 1/3 corrupted evidence; levers T1-T5 applied to the k = 3, c = 1 world.
- **Verdict rule:** survives if Q1, Q2, Q3 pass and Q4's predictions hold.

## Results
| | Criterion | Result | |
|---|---|---|---|
| Q1 tracking | AUC >= 0.9 at k = 1 and c = 1; monotone medians | AUC 0.943 (k = 1), 0.983 (c = 1); medians 0 < .012 < .037 < .100 and .049 < .111 | PASS |
| Q2 stuck states | <= 5% of consistent runs with E > 0.01 | **6%** (6/100; E = 0.035-0.082) | **FAIL** |
| Q3 evidence carries structure | accuracy >= 0.95; freeze lower in >= 18/20 seeds | accuracy 0.986; freeze H 0.54 vs honest 0.92, 20/20 seeds | PASS |
| Q4 levers | T1, T2, T4 raise H in >= 18/20 seeds; T3 within 1% | T1 +4.4%, T2 +3.8%, T4 +4.1% (each 20/20); T3 -0.2% | PASS (all predictions held) |
| Q5 field vs exact | report; expect field within 0.05 of exact | field 0.943 / 0.983 vs exact 1.000 / 1.000; the k = 1 gap (0.057) exceeds 0.05 | field worse |
| Localization | 0.7 | corrupted evidence in top 3: 0.94; flipped edge in top 5: 1.00 | pass |
| 10% evidence (secondary) | | stuck 32%, accuracy 0.93 | much worse |

**Verdict: FAIL by the pre-registered rule (Q2).**

## Diagnostic (outside protocol)
- The 6 stuck runs are **trapped, not slow**: 5x more steps leaves energy unchanged, gradients sit at noise level, and they are twisted local minima with phase errors of 1.0-1.5 rad on some edges.
- Their energy (0.035-0.082) is in the **same range as genuine inconsistency** (k = 3: 0.037; c = 1: 0.049). A stuck consistent world is therefore indistinguishable from a real problem.
- Best of 3 random restarts reduces the stuck rate to 2%. This is a post-hoc remedy, not part of the pre-registration.

## Interpretation
The failure is in the **oscillator field as a way of computing the quantity**, not in the quantity. Clamped, normalized frustration energy passed every definitional test: it tracks inconsistency monotonically, it recovers the truth from 25% evidence, freezing loses, and each rule-breaking lever gains harmony exactly as predicted. The exact method (A1's clamped signed Laplacian) computes the same quantity with no local minima and perfect separation. Per the pre-registered rule: use exact computation for measurement, and keep the field only as dynamics.
