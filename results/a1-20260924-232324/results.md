### L1

Documents: 60 consistent, 60 direct, 60 cycle.

| Method | Direct P | Direct R | Direct F1 | Cycle P | Cycle R | Cycle F1 | order_cycle F1 | equality_break F1 | binary_parity F1 | False-positive rate |
|---|---|---|---|---|---|---|---|---|---|---|
| Engine | 0.845 | 1.000 | 0.916 | 0.845 | 1.000 | 0.916 | 0.909 | 0.909 | 0.930 | 0.183 |
| Pairwise only | 0.845 | 1.000 | 0.916 | 0.560 | 0.233 | 0.329 | 0.345 | 0.414 | 0.222 | 0.183 |
| LLM-direct (thinking) | 0.870 | 1.000 | 0.930 | 0.870 | 1.000 | 0.930 | 0.952 | 0.909 | 0.930 | 0.150 |
| LLM-direct (no thinking) | 0.674 | 1.000 | 0.805 | 0.674 | 1.000 | 0.805 | 0.930 | 0.870 | 0.667 | 0.483 |

Localization hit rate on cycle variants: Engine 1.000, LLM-direct (thinking) 1.000, LLM-direct (no thinking) 1.000.

Pass (engine; direct F1 >= 0.85, cycle F1 >= 0.75, localization >= 0.7): PASS. Checks: direct_f1 met, cycle_f1 met, localization met.
Expected (not judged): direct F1 >= 0.85 for Engine yes, Pairwise only yes, LLM-direct (thinking) yes, LLM-direct (no thinking) no; pairwise cycle F1 below 0.5: yes.

Seed spread (104 documents with sampled pairs): Engine direct F1 0.916/0.909/0.909, cycle F1 0.916/0.909/0.909; Pairwise only direct F1 0.916/0.909/0.916, cycle F1 0.329/0.418/0.368; engine localization 1.000/1.000/1.000 (seeds 0/1/2).

Diagnostics: planted sentences extracted 1.000; planted relations extracted 0.967 (order_cycle 0.900, equality_break 1.000, binary_parity 1.000); arity accuracy 1.000 (read on binary cycle variants: 20 binary; on their controls: 20 multi); false-positive rate on the binary "three values" controls: Engine 0.150, Pairwise only 0.200, LLM-direct (thinking) 0.150, LLM-direct (no thinking) 1.000. Claims per document: mean 25.5, max 33. Relations ignored 1, entity relations dropped 0.

Relation scoring on cycle variants (seed 0): contamination, the planted-cycle claim pairs labeled contradicts, 0.033 (8 of 240 scored, 0 unscored; order_cycle 0.000, equality_break 0.133, binary_parity 0.000). Engine detections by clause: entity clause alone 48, entity with direct or balance 12, direct or balance without entity 0, of 60 (by type, in that order: order_cycle 16/4/0, equality_break 14/6/0, binary_parity 18/2/0; clause combinations: 48 entity, 10 direct+entity, 2 direct+claim_balance+entity).

Unscored pairs at seed 0: 0 of 23754 requested (0.0000; the run stops above 1%): 0 left out by the model, 0 unscored after a malformed re-score. Pairs re-scored for a malformed rationale: 0. Unscored on the sampled documents, seeds 0/1/2: 0/0/1. Documents with unscored pairs: none (0 with planted claims involved).

#### Minimal engine (XON_A1_MINIMAL_ENGINE.md, Section 4): report-only, no pass or fail

Verdict clauses (a) direct and (c) entity only, on the full engine's claims, relations and entity relations (seed 0). These numbers do not affect the full engine's L1 verdict.

| Engine | Direct P | Direct R | Direct F1 | Cycle P | Cycle R | Cycle F1 | order_cycle F1 | equality_break F1 | binary_parity F1 | False-positive rate | Binary-control false-positive rate | Localization |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Minimal | 0.857 | 1.000 | 0.923 | 0.857 | 1.000 | 0.923 | 0.930 | 0.909 | 0.930 | 0.167 | 0.150 | 1.000 |
| Full | 0.845 | 1.000 | 0.916 | 0.845 | 1.000 | 0.916 | 0.909 | 0.909 | 0.930 | 0.183 | 0.150 | 1.000 |

Verdicts agree on 179 of 180 documents (0.994). Prediction, stated in advance: the two verdicts agree on at least 98% of the 180 documents, and every disagreement is a document where the full engine's clause (b) fired without clause (a) or (c). Held: yes (agreement met; disagreements all of the predicted kind).

Documents where the verdicts differ: b54-consistent (full claim_balance, minimal none).

### L1b

Documents: 120; kept 60 consistent, 60 direct; left out with H = None 0 consistent, 0 direct.
AUC of 1 - H: 0.926; AUC of the conflict score (sum of lambda_min): 0.528; premise among the top-3 residual claims: 0.933 (30 documents); documents with unanchored components: 0.342.
Pass (AUC >= 0.9 and >= the conflict score's, premise top-3 >= 0.7): PASS. Checks: auc met, auc_at_least_conflict met, premise_top3 met.
