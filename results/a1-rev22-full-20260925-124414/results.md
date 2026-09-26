# A1 rev. 2.2 development pass (full)

*rev. 2.2 development pass on the seen L1 corpus; not a result of record.*

Documents: 180. Engine version 2.2; claims and pair selections from the run of record's cache (seed 0); LLM-direct carried from the run of record.

Unscored pairs: 0 of 23754 (0.0000; stop above 0.01); re-scored: 0; answers for another pair: 0.

## Rev. 2.1 threshold curves (report-only, from the run of record's cache)

| τ | engine mean F1 | minimal mean F1 | pairwise mean F1 |
|---|---|---|---|
| 0.50 | 0.916 | 0.923 | 0.623 |
| 0.55 | 0.938 | 0.945 | 0.635 |
| 0.60 | 0.968 | 0.976 | 0.613 |
| 0.65 | 1.000 | 1.000 | 0.577 |
| 0.70 | 1.000 | 1.000 | 0.562 |
| 0.75 | 1.000 | 1.000 | 0.562 |
| 0.80 | 1.000 | 1.000 | 0.562 |
| 0.85 | 1.000 | 1.000 | 0.548 |
| 0.90 | 1.000 | 1.000 | 0.532 |

## Methods (§8 item 1)

*rev. 2.2 development pass on the seen L1 corpus; not a result of record.*

| method | version | τ | direct P / R / F1 | cycle P / R / F1 | FP rate | binary control FP |
|---|---|---|---|---|---|---|
| engine | 2.1 | 0.50 | 0.845 / 1.000 / 0.916 | 0.845 / 1.000 / 0.916 | 0.183 | 0.150 |
| minimal | 2.1 | 0.50 | 0.857 / 1.000 / 0.923 | 0.857 / 1.000 / 0.923 | 0.167 | 0.150 |
| pairwise | 2.1 | 0.50 | 0.845 / 1.000 / 0.916 | 0.560 / 0.233 / 0.329 | 0.183 | 0.200 |
| direct_thinking (carried) | 2.1 | — | 0.870 / 1.000 / 0.930 | 0.870 / 1.000 / 0.930 | 0.150 | 0.150 |
| direct_no_thinking (carried) | 2.1 | — | 0.674 / 1.000 / 0.805 | 0.674 / 1.000 / 0.805 | 0.483 | 1.000 |
| engine | 2.2 | 0.50 | 0.938 / 1.000 / 0.968 | 0.938 / 1.000 / 0.968 | 0.067 | 0.100 |
| minimal | 2.2 | 0.50 | 0.938 / 1.000 / 0.968 | 0.938 / 1.000 / 0.968 | 0.067 | 0.100 |
| pairwise | 2.2 | 0.50 | 0.938 / 1.000 / 0.968 | 0.600 / 0.100 / 0.171 | 0.067 | 0.100 |
| direct_thinking (carried) | 2.2 | — | 0.870 / 1.000 / 0.930 | 0.870 / 1.000 / 0.930 | 0.150 | 0.150 |
| direct_no_thinking (carried) | 2.2 | — | 0.674 / 1.000 / 0.805 | 0.674 / 1.000 / 0.805 | 0.483 | 1.000 |

## Engine at τ = 0.50: rev. 2.1's false positives, new false positives, lost detections (§8 items 2-4)

*rev. 2.2 development pass on the seen L1 corpus; not a result of record.*

Rev. 2.1 false positives: 11; still flagged under 2.2: 1. New false positives: 3. Lost detections: 0.
- b22-consistent (equality_break): 2.1 direct; 2.2 does not flag it.
- b26-consistent (binary_parity): 2.1 direct; 2.2 does not flag it.
- b28-consistent (equality_break): 2.1 direct; 2.2 does not flag it.
- b30-consistent (order_cycle): 2.1 direct+claim_balance; 2.2 does not flag it.
- b31-consistent (equality_break): 2.1 entity; 2.2 does not flag it.
- b32-consistent (binary_parity): 2.1 direct+claim_balance; 2.2 flags it, direct.
- b33-consistent (order_cycle): 2.1 direct; 2.2 does not flag it.
- b34-consistent (equality_break): 2.1 direct; 2.2 does not flag it.
- b45-consistent (order_cycle): 2.1 direct; 2.2 does not flag it.
- b54-consistent (order_cycle): 2.1 claim_balance; 2.2 does not flag it.
- b56-consistent (binary_parity): 2.1 direct; 2.2 does not flag it.
- new: b05-consistent (binary_parity): direct.
- new: b07-consistent (equality_break): direct+claim_balance.
- new: b25-consistent (equality_break): direct.

## Tension (§8 item 5)

*rev. 2.2 development pass on the seen L1 corpus; not a result of record.*

| variant | documents | tension pairs | documents with tension |
|---|---|---|---|
| consistent | 60 | 140 | 45 |
| direct | 60 | 129 | 48 |
| cycle | 60 | 133 | 47 |

Planted pairs in direct variants: 60, labeled {'contradicts': 60}; tension: 0 (rev. 2.1 contradicts: 0).

## Contamination, clause attribution, entity extraction, L1b, minimal engine, cost (§8 items 6-11)

*rev. 2.2 development pass on the seen L1 corpus; not a result of record.*

- Contamination rev_2_1: 8 of 240 scored planted pairs (0.033).
- Contamination rev_2_2_at_0.5: 0 of 240 scored planted pairs (0.000).
- Clause attribution rev_2_1: {'entity': 48, 'direct+entity': 10, 'direct+claim_balance+entity': 2}.
- Clause attribution rev_2_2_at_0.5: {'entity': 54, 'direct+claim_balance+entity': 1, 'direct+entity': 5}.
- Entity rev_2_1: planted relations recovered 0.967; sense overrides 0; superlatives 0 (0 edges); superlative collisions 0; unsupported order claims 0.
- Entity rev_2_2: planted relations recovered 1.000; sense overrides 19; superlatives 348 (429 edges); superlative collisions 0; unsupported order claims 21.
- L1b rev_2_1: AUC(1 − H) 0.926, AUC(λ_min) 0.528, premise in top-3 0.933.
- L1b rev_2_2: AUC(1 − H) 0.975, AUC(λ_min) 0.500, premise in top-3 1.000.
- Minimal engine rev_2_1: agreement with the full engine 0.994, clause mismatches 0.
- Minimal engine rev_2_2_at_0.5: agreement with the full engine 1.000, clause mismatches 0.
- Cost rev_2_1: per document engine $0.1376, pairwise $0.1266, LLM-direct $0.0091; total $26.40.
- Cost rev_2_2: per document engine $0.4244, pairwise $0.4136, LLM-direct $0.0000; total $76.40.
