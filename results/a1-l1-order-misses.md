# A1 rev. 2.2, Step 0: the run of record's missed planted order relations

Produced by `results/a1-l1-order-misses.py`, which reads only the runs' files and makes no API calls: the run of record (`results/a1-20260924-232324/`: `documents.jsonl`, `l1.json`, `analyses/`), the corpus it ran on (`data/consistency/corpus.jsonl`), and the rev. 2.2 full development pass, iteration 0 (`results/a1-rev22-full-20260925-124414/`: `documents_v22.jsonl`, `analyses/`, `diagnostics.json`). Each entity graph is rebuilt from the run's cached extraction as the engine built it, and the matching rule's flags are checked against the run's own before anything is reported. The run of record's reported figures stay as they are. Every rev. 2.2 figure: rev. 2.2 development pass on the seen L1 corpus; not a result of record.

## Summary

- Planted order relations the L1 diagnostic counted as not extracted correctly (seed 0, cycle variants): 6 of 60, in 2 of the 20 order-cycle documents (b00-cycle, b36-cycle).
- By class: scoring artifact 6, not extracted 0, direction flip 0, id mismatch 0, wrong relation 0.
- Run of record: the planted order cycle closes in the entity graph in 20 of 20 order-cycle documents, and is the entity contradiction the engine reports in 20.
- Rev. 2.2, iteration 0: the planted order cycle closes in the entity graph in 20 of 20 order-cycle documents, and is the entity contradiction the engine reports in 18.
  - b21-cycle: the engine reports order_cycle on `arrival_order` over sami, nell, from claim 1, "Sami arrived first."; claim 16, "Nell finished ahead of Sami."
  - b57-cycle: the engine reports order_cycle on `finish_order` over otto, esme, from claim 4, "Esme trailed in last."; claim 19, "Esme finished ahead of Otto."
  A planted order cycle closes when one relation stated by a claim matched to each planted sentence, all on one attribute, chain round the planted entities, one way or the other. The engine reports the shortest contradiction on each attribute, so a closed cycle is not always the one reported.

In each of these documents every planted order relation is extracted the other way round, on one attribute, so the extraction states the planted cycle's mirror image, which closes: the engine reports it, on the planted claims. Each relation, taken alone, also fits the description of a direction flip (the right entities and attribute, the wrong direction); a miss goes to the first class that fits, and scoring artifact comes first.

## By document

| Document | Missed | scoring artifact | not extracted | direction flip | id mismatch | wrong relation | Planted cycle closes | Engine reports it | Engine clauses |
|---|---|---|---|---|---|---|---|---|---|
| b00-cycle | 3 of 3 | 3 | 0 | 0 | 0 | 0 | yes | yes | entity |
| b36-cycle | 3 of 3 | 3 | 0 | 0 | 0 | 0 | yes | yes | entity |

## Each miss, with the cached extraction

### b00-cycle (order cycle)

The engine's entity contradiction: order_cycle on `age` over kai, isla, cy, claims 8, 12, 14, minimum confidence 0.95.

| Planted sentence | Planted relation | Claim | Extracted from that claim | Class |
|---|---|---|---|---|
| Isla is older than Kai. | greater(Isla, Kai), fixed | 8: Isla is older than Kai. | greater(kai, isla) on `age`, 0.95 | scoring artifact |
| Kai is older than Cy. | greater(Kai, Cy), fixed | 12: Kai is older than Cy. | greater(cy, kai) on `age`, 0.95 | scoring artifact |
| Cy is older than Isla. | greater(Cy, Isla), fixed | 14: Cy is older than Isla. | greater(isla, cy) on `age`, 0.95 | scoring artifact |

The same base's consistent variant (b00-consistent), its planted relations matched: forward 3.

### b36-cycle (order cycle)

The engine's entity contradiction: order_cycle on `age` over kira, quinn, dara, claims 9, 12, 15, minimum confidence 0.95.

| Planted sentence | Planted relation | Claim | Extracted from that claim | Class |
|---|---|---|---|---|
| Quinn is older than Kira. | greater(Quinn, Kira), fixed | 9: Quinn is older than Kira. | greater(kira, quinn) on `age`, 0.95 | scoring artifact |
| Kira is older than Dara. | greater(Kira, Dara), fixed | 12: Kira is older than Dara. | greater(dara, kira) on `age`, 0.95 | scoring artifact |
| Dara is older than Quinn. | greater(Dara, Quinn), fixed | 15: Dara is older than Quinn. | greater(quinn, dara) on `age`, 0.95 | scoring artifact |

The same base's consistent variant (b36-consistent), its planted relations matched: reverse 3.

## The two matching rules

| Rule | Run of record: order relations | Run of record: all planted relations | Rev. 2.2, iteration 0: order relations | Rev. 2.2, iteration 0: all planted relations |
|---|---|---|---|---|
| The run of record's (as reported) | 0.900 (54 of 60) | 0.967 (174 of 180) | 1.000 (60 of 60) | 1.000 (180 of 180) |
| Corrected (Step 0, report-only) | 1.000 (60 of 60) | 1.000 (180 of 180) | 1.000 (60 of 60) | 1.000 (180 of 180) |

The run of record's rule counts a planted relation as extracted when a relation stated by a claim matched to the planted sentence has the planted kind and entities, in the planted direction for "greater"; a rank phrasing (direction "either") also counts reversed when all of the document's found rank relations share one direction. The corrected rule is the same, except that a planted relation stated the other way round also counts when the document's planted cycle closes (as defined in the summary): the mirror image of a cycle is a cycle. Neither rule looks at attribute keys; the planted-cycle counts in the summary cover them. The run of record's 0.900 and 0.967 stay as reported.

## The rev. 2.2 full pass's remaining false positives (iteration 0, τ = 0.5; rev. 2.2 development pass on the seen L1 corpus; not a result of record)

4 consistent documents are flagged. By clause: b32-consistent direct; b05-consistent direct; b07-consistent direct, claim_balance; b25-consistent direct. All are flagged by relation clauses (direct, claim balance), none by the entity clause. Each is listed with its claims, the judge's label, confidence and rationale.

### b32-consistent (binary parity base, the binary three-value control)

- Rev. 2.1: flagged (direct, claim_balance). Rev. 2.2: flagged (direct); the minimal engine: flagged (direct).
- The document's number-of-values sentence: "The school had three houses."
- Direct: claim 4, "Hana came in shortly after Milo arrived.", and claim 10, "Milo and Hana were in different houses.": contradicts, confidence 0.70.
  Rationale: "If Hana came in shortly after Milo arrived, both were entering the same place, implying they were in or entering the same house at that time, which contradicts the claim that they were in different houses."

### b05-consistent (binary parity base, the binary three-value control)

- Rev. 2.1: not flagged. Rev. 2.2: flagged (direct); the minimal engine: flagged (direct).
- The document's number-of-values sentence: "The school had three houses."
- Direct: claim 3, "Mina greeted Jude who came in shortly after her.", and claim 22, "Mina and Jude were in different houses.": contradicts, confidence 0.85.
  Rationale: "A implies Mina and Jude were together in the same location (she greeted him as he came in), which contradicts B's claim that they were in different houses."

### b07-consistent (equality break base)

- Rev. 2.1: not flagged. Rev. 2.2: flagged (direct, claim_balance); the minimal engine: flagged (direct).
- Direct: claim 8, "Vik showed up a little later than the others.", and claim 11, "Milo strolled in last.": contradicts, confidence 0.72.
  Rationale: "A claims Vik arrived later than the others, implying Vik was last. B claims Milo was last. Both cannot be last, so these claims conflict unless 'others' in A excludes Milo, but that reading is strained given B's explicit 'last' claim."
- Claim balance: the frustrated cycle over claims 8, 11, 24:
  - 8-11: contradicts, confidence 0.72. "A claims Vik arrived later than the others, implying Vik was last. B claims Milo was last. Both cannot be last, so these claims conflict unless 'others' in A excludes Milo, but that reading is strained given B's explicit 'last' claim."
  - 11-24: supports, confidence 0.75. "If Milo strolled in last, then everyone else, including Vik, arrived before Milo, which is consistent with Vik arriving before Milo as stated in B."
  - 8-24: supports, confidence 0.55. "A states Vik arrived slightly later than others in general, which is consistent with B's specific ordering placing Vik after Bo but before Milo, though it depends on how many 'others' there are and their arrival times."
  - claim 8: "Vik showed up a little later than the others."
  - claim 11: "Milo strolled in last."
  - claim 24: "Vik arrived after Bo but before Milo."

### b25-consistent (equality break base)

- Rev. 2.1: not flagged. Rev. 2.2: flagged (direct); the minimal engine: flagged (direct).
- Direct: claim 0, "Milo was the first to walk in.", and claim 8, "Mina was already seated at the far table, sorting through glazes she had picked out the week before.": contradicts, confidence 0.62.
  Rationale: "If Milo was first to walk in, that suggests no one else was there before him, yet B says Mina was already seated when presumably Milo entered. This creates tension unless B occurs in a different scene, but taken together they are awkward."
