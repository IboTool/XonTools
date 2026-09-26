# A1 rev. 2.2 development pass (D0 (12-document subset))

*rev. 2.2 development pass on the seen L1 corpus; not a result of record.*

Documents: 12. Engine version 2.2; claims and pair selections from the run of record's cache (seed 0); LLM-direct carried from the run of record.

Unscored pairs: 0 of 1468 (0.0000; stop above 0.01); re-scored: 0; answers for another pair: 0.

## Rev. 2.1 threshold curves (report-only, from the run of record's cache)

| τ | engine mean F1 | minimal mean F1 | pairwise mean F1 |
|---|---|---|---|
| 0.50 | 1.000 | 1.000 | 0.500 |
| 0.55 | 1.000 | 1.000 | 0.500 |
| 0.60 | 1.000 | 1.000 | 0.500 |
| 0.65 | 1.000 | 1.000 | 0.500 |
| 0.70 | 1.000 | 1.000 | 0.500 |
| 0.75 | 1.000 | 1.000 | 0.500 |
| 0.80 | 1.000 | 1.000 | 0.500 |
| 0.85 | 1.000 | 1.000 | 0.500 |
| 0.90 | 1.000 | 1.000 | 0.500 |

## Methods (§8 item 1)

*rev. 2.2 development pass on the seen L1 corpus; not a result of record.*

| method | version | τ | direct P / R / F1 | cycle P / R / F1 | FP rate | binary control FP |
|---|---|---|---|---|---|---|
| engine | 2.1 | 0.50 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 | 0.000 | 0.000 |
| minimal | 2.1 | 0.50 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 | 0.000 | 0.000 |
| pairwise | 2.1 | 0.50 | 1.000 / 1.000 / 1.000 | 0.000 / 0.000 / 0.000 | 0.000 | 0.000 |
| direct_thinking (carried) | 2.1 | — | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 | 0.000 | 0.000 |
| direct_no_thinking (carried) | 2.1 | — | 0.667 / 1.000 / 0.800 | 0.667 / 1.000 / 0.800 | 0.500 | 1.000 |
| engine | 2.2 | 0.50 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 | 0.000 | 0.000 |
| minimal | 2.2 | 0.50 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 | 0.000 | 0.000 |
| pairwise | 2.2 | 0.50 | 1.000 / 1.000 / 1.000 | 0.000 / 0.000 / 0.000 | 0.000 | 0.000 |
| direct_thinking (carried) | 2.2 | — | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 | 0.000 | 0.000 |
| direct_no_thinking (carried) | 2.2 | — | 0.667 / 1.000 / 0.800 | 0.667 / 1.000 / 0.800 | 0.500 | 1.000 |

## Engine at τ = 0.50: rev. 2.1's false positives, new false positives, lost detections (§8 items 2-4)

*rev. 2.2 development pass on the seen L1 corpus; not a result of record.*

Rev. 2.1 false positives: 0; still flagged under 2.2: 0. New false positives: 0. Lost detections: 0.

## Tension (§8 item 5)

*rev. 2.2 development pass on the seen L1 corpus; not a result of record.*

| variant | documents | tension pairs | documents with tension |
|---|---|---|---|
| consistent | 4 | 6 | 2 |
| direct | 4 | 10 | 3 |
| cycle | 4 | 10 | 4 |

Planted pairs in direct variants: 4, labeled {'contradicts': 4}; tension: 0 (rev. 2.1 contradicts: 0).

## Contamination, clause attribution, entity extraction, L1b, minimal engine, cost (§8 items 6-11)

*rev. 2.2 development pass on the seen L1 corpus; not a result of record.*

- Contamination rev_2_1: 0 of 15 scored planted pairs (0.000).
- Contamination rev_2_2_at_0.5: 0 of 15 scored planted pairs (0.000).
- Clause attribution rev_2_1: {'entity': 4}.
- Clause attribution rev_2_2_at_0.5: {'entity': 4}.
- Entity rev_2_1: planted relations recovered 0.750; sense overrides 0; superlatives 0 (0 edges); superlative collisions 0; unsupported order claims 0.
- Entity rev_2_2: planted relations recovered 1.000; sense overrides 0; superlatives 15 (27 edges); superlative collisions 0; unsupported order claims 0.
- L1b rev_2_1: AUC(1 − H) 1.000, AUC(λ_min) 0.500, premise in top-3 1.000.
- L1b rev_2_2: AUC(1 − H) 1.000, AUC(λ_min) 0.500, premise in top-3 1.000.
- Minimal engine rev_2_1: agreement with the full engine 1.000, clause mismatches 0.
- Minimal engine rev_2_2_at_0.5: agreement with the full engine 1.000, clause mismatches 0.
- Cost rev_2_1: per document engine $0.1303, pairwise $0.1207, LLM-direct $0.0085; total $1.67.
- Cost rev_2_2: per document engine $0.3973, pairwise $0.3871, LLM-direct $0.0000; total $4.77.
