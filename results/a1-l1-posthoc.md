# A1 L1 run of record: post-hoc analysis

An analysis, not a re-specification, made on 2026-09-24 at the user's request after the run of record. It reran
nothing, made no API calls, and changed nothing in the run of record (`results/a1-20260924-232324/`) or in any
criterion. The facts below come from `results/a1-l1-posthoc.py` (its output: `results/a1-l1-posthoc-facts.txt`), which
reads only the run's files and `cache/llm/log.jsonl`. The classifications are judgments, made by reading each document.

## 1. The full engine's false positives on consistent documents (11 of 60)

Classes:
- **relation-judge error:** the pairwise judge labeled a compatible pair of claims `contradicts`, or supplied the edges
  of a frustrated cycle;
- **entity-extraction error:** the entity extractor produced a wrong relation;
- **unplanted contradiction:** the text itself contains a contradiction that the corpus didn't plant.

Clause (a) is direct, (b) claim balance, (c) entity. "Base" is the cycle type of the document's base.

1. **b22** (equality-break base). Clause (a): claim 18 "Nell sat quietly reviewing trivia cards." and claim 22 "Noor
   chatted with Nell about favorite quiz categories.", contradicts 0.55 ("making it somewhat less likely she is
   simultaneously chatting with Noor"). **Relation-judge error:** the text doesn't place the two at the same moment.
2. **b26** (binary three-value control). Clause (a), two pairs: claim 6 "Lena set her sketchbook on the table beside
   Rosa." and claim 10 "Lena and Rosa worked different shifts.", contradicts 0.55; claim 7 "Hana and Lena worked
   different shifts." and claim 9 "The five of them chatted about the new clay supplier while waiting for the
   instructor to arrive.", contradicts 0.6. **Relation-judge error:** the shifts are the shop's ("The shop ran three
   shifts"); being together at the evening class doesn't conflict with working different shifts.
3. **b28** (equality-break base). Clause (a): claim 9 "The wind picked up slightly, rippling the surface of the river."
   and claim 21 "The oars sliced through the calm water in unison.", contradicts 0.6. **Relation-judge error,
   borderline:** slightly rippled water can still be called calm, and the text never says the wind dropped; a reader
   may notice a mild descriptive tension, but not a contradiction of the kind the corpus plants.
4. **b30** (order-cycle base). Clause (a): claim 1 "Everyone arrived within a few minutes of each other." and claim 5
   "Nell arrived a little later.", contradicts 0.5. Clause (b): the cycle 1, 3, 5 closes through claim 3 "Isla arrived
   first, carrying a stack of novels she wanted to discuss." (1–3 supports 0.55, 3–5 supports 0.7) and the same
   contradicts edge. **Relation-judge error:** "a little later" fits within "a few minutes"; one edge drives both
   clauses.
5. **b31** (equality-break base). Clause (c): an order cycle on `signup_order` over Kira and Otto, from claim 22 "Kira
   signed the sign-up sheet first." (greater(kira, otto), 0.6) and claim 23 "Otto signed the sign-up sheet after
   Kira." (greater(otto, kira), 0.85). **Entity-extraction error:** the claims agree (the text: "Kira signed first,
   followed by Otto"), but the extractor normalized them in opposite directions on the same attribute.
6. **b32** (binary three-value control). Clause (a): claim 15 "Noor asked everyone to quiet down so the discussion
   could continue." and claim 24 "Noor thanked everyone for coming as the meeting wrapped up.", contradicts 0.5.
   Clause (b): the cycle 1, 15, 24 closes through premise 1 "Noor is the head judge." (1–15 supports 0.5, 24–1
   supports 0.55) and the same contradicts edge. **Relation-judge error:** two successive moments of one meeting.
7. **b33** (order-cycle base). Clause (a): claim 16 "Ivo finished ahead of Kira." and claim 29 "Both Kira's and Ivo's
   designs worked equally well in the trials.", contradicts 0.5. **Relation-judge error, borderline:** the finishing
   order and the designs working equally well in the trials are different things, but the text's sentence ("Kira's
   design used fewer parts than Ivo's, though both worked equally well in the trials") sits close enough to the
   order claims that a reader may pause.
8. **b34** (equality-break base). Clause (a): claim 4 "Ben was carrying a folder of printed diagrams." and claim 5
   "Sami was carrying a folder of printed diagrams.", contradicts 0.55 ("assuming one folder is being referenced").
   **Relation-judge error:** the text says both carried folders.
9. **b45** (order-cycle base). Clause (a): claim 15 "Hana walked with a steady pace, pausing now and then to sketch a
   quick outline of a sparrow perched on a fence post." and claim 18 "Hana finished ahead of Leo.", contradicts 0.55.
   **Relation-judge error:** pausing makes finishing ahead less likely, not impossible.
10. **b54** (order-cycle base). Clause (b) alone, the minimal engine's one disagreement: the cycle 0, 5, 20, with
    claim 0 "The annual club exhibition drew a modest crowd on a cool autumn evening." (asserted), claim 5 "The turnout
    this year seemed larger than the last three gatherings combined." (quoted, Ivo's remark) and claim 20 "The evening
    carried on with quiet anticipation, the kind that settles over a room right before results are announced."
    Edges: 0–5 contradicts 0.6, 5–20 supports 0.55, 20–0 supports 0.6. **Relation-judge error:** a modest crowd can
    outnumber three small past gatherings, and the two supports edges are loose associations. The cycle runs through a
    quoted claim, which clause (a) excludes and clause (b) counts.
11. **b56** (binary three-value control). Clause (a): claim 8 "The lighting in the main room was carefully arranged so
    that every print would be seen under even conditions." and claim 20 "The afternoon light cast long shadows across
    the display tables where framed prints were being arranged in neat rows.", contradicts 0.55. **Relation-judge
    error, borderline:** the arranged lighting is the exhibition's, the shadows fall during setup; a mild tension at
    most.

**Totals:**
- Relation-judge errors: 10, of which 3 are borderline (b28, b33, b56).
- Entity-extraction errors: 1 (b31).
- Unplanted contradictions: 0.

**Confidence of the edges:** all 10 `contradicts` edges behind the clause (a) flags (9 documents; b26 has two) have
confidence 0.50 to 0.60. The two documents where clause (b) fired along with (a), b30 and b32, close their cycle with
the same 0.5 edge that fired (a).

### The binary three-value controls (3 of 20)

The 3 false positives on the binary three-value controls are b26, b32 and b56, classified above:
- b26 and b32: relation-judge errors;
- b56: a borderline relation-judge error.

All three come from the relation judge: clause (a) in all three, and clause (b) in b32 as well. None comes from the
entity clause. The extractor read the arity as `multi` on all 20 controls (arity accuracy 1.000 in the run's
diagnostics), so no parity contradiction could fire. The three-value construction caused none of the three.

## 2. Cost per document

Prices are for claude-sonnet-5, $2 per million input tokens and $10 per million output tokens (the client's price
table). Each request is priced at the API call that paid for it in `cache/llm/log.jsonl`. The run replayed every
request once in the recompute of 23:23:24, which gives the inventory: 3,102 calls, 2,871 distinct requests. Each
method's cost per document is the sum over its requests for that document, using the seed-0 pairing that gives the
verdict.

| Method | Mean | Median | Min | Max | Mean tokens (in / out) | Total, 180 documents |
|---|---|---|---|---|---|---|
| Engine (extraction, pair selection, relations, entities) | $0.1376 | $0.1007 | $0.0236 | $0.2681 | 13,155 / 11,128 | $24.77 |
| Pairwise only (extraction, pair selection, relations) | $0.1266 | $0.0899 | $0.0170 | $0.2576 | 10,993 / 10,462 | $22.79 |
| LLM-direct, thinking | $0.0057 | $0.0047 | $0.0022 | $0.0322 | 1,074 / 355 | $1.03 |
| LLM-direct, no thinking | $0.0034 | $0.0033 | $0.0021 | $0.0074 | 1,074 / 125 | $0.61 |

- The engine and the pairwise baseline share extraction, pair selection and relation scoring; the engine's entity call
  adds $0.011 per document on average.
- Relation scoring dominates: documents with up to 25 claims (76) have every pair scored, and cost the engine $0.1970
  on average; documents above 25 claims (104) have their pairs selected and sampled, and cost $0.0942.
- Pairing seeds 1 and 2, the seed-spread diagnostic, add $0.1143 per sampled document in new requests ($11.88 over 104
  documents; $12.54 counting requests identical to seed 0's). They are not part of any method's verdict.
- LLM-direct with thinking costs about 1/24 of the engine per document.
- **Reconciliation:** engine $24.766, LLM-direct $1.025 and $0.612, and the new seed requests $11.883 add up to
  $38.287. The run spent $38.235. The $0.052 difference is four relation batches that were identical between two
  variants of the same base and were paid once: b16 cycle and direct, b35, b36 and b56 consistent and cycle. The
  per-document figures count each of them for both documents.

## 3. Equality-break contamination (8 of the 60 planted pairs in equality-break documents, 0.133)

Each equality-break cycle plants "A same as B", "B same as C" and "A not same as C". All eight contaminated pairs are
the first and third of these, labeled `contradicts`. Every rationale reasons through the third planted claim, "B same
as C", which the pair doesn't contain:
- seven rationales state it outright ("per other claims", "per claim 15", "combined with Rosa being on Hana's team");
- b52's rationale hedges ("given the group chain implied elsewhere").

The relate prompt tells the judge to "judge each pair using only its two statements, ignoring every other statement in
the list, even if they seem relevant". The batch listed the third claim, and the judge used it.

1. **b04-cycle**, claim 6 "Rosa is in the same class as Finn." and claim 15 "Rosa is not in the same class as Jun.":
   contradicts 0.8. "If Rosa is in the same class as Finn, and Finn is in Jun's class, this contradicts the claim that
   Rosa is not in Jun's class." Engine clauses: direct, entity.
2. **b10-cycle**, claim 6 "Milo is on the same team as Jun." and claim 16 "Milo is not on the same team as Hana.":
   contradicts 0.4. "If Milo is on the same team as Jun, and Jun is (per other claims) on Hana's team, this would
   suggest Milo is on Hana's team, contradicting the claim that Milo is not on Hana's team." Engine clauses: entity.
3. **b25-cycle**, claim 9 "Milo is in the same study group as Fay." and claim 16 "Milo is not in the same study group
   as Nell.": contradicts 0.4. "If Milo is in the same study group as Fay, and Fay is in the same group as Nell (per
   other claims), this would imply Milo is in the same group as Nell, contradicting claim 16 that Milo is not in the
   same group as Nell." Engine clauses: direct, entity.
4. **b37-cycle**, claim 7 "Finn is on the same team as Rosa." and claim 16 "Finn is not on the same team as Hana.":
   contradicts 0.85. "Finn being on Rosa's team combined with Rosa being on Hana's team would imply Finn is on Hana's
   team, contradicting claim 16." Engine clauses: direct, entity.
5. **b40-cycle**, claim 14 "Finn is in the same class as Bo." and claim 24 "Finn is not in the same class as Nell.":
   contradicts 0.55. "If Finn is in the same class as Bo, and Bo is in the same class as Nell (per other claims), this
   would imply Finn is in the same class as Nell, contradicting that Finn is not in Nell's class." Engine clauses:
   direct, entity.
6. **b46-cycle**, claim 14 "Bo is on the same team as Uma." and claim 25 "Bo is not on the same team as Jude.":
   contradicts 0.55. "If Bo is on the same team as Uma, and Uma is on the same team as Jude, then Bo would be on the
   same team as Jude, contradicting that Bo is not on the same team as Jude." Engine clauses: direct, entity.
7. **b52-cycle**, claim 11 "Dara is in the same study group as Rosa." and claim 19 "Dara is not in the same study group
   as Tess.": contradicts 0.4. "If Dara and Rosa are in the same group, and if Rosa and Tess were also in the same
   group, Dara and Tess would be in the same group, contradicting B; but A alone doesn't determine Tess's group,
   though it creates tension with the claim that Dara is not with Tess given the group chain implied elsewhere."
   Engine clauses: entity.
8. **b58-cycle**, claim 11 "Ana is in the same class as Esme." and claim 16 "Ana is not in the same class as Lena.":
   contradicts 0.55. "If Ana is in the same class as Esme, and Esme is in the same class as Lena (per claim 15, not
   assumed here), this would suggest Ana is in the same class as Lena, contradicting claim 16; but taken alone, A
   doesn't establish this link." Engine clauses: direct, entity.

**Effect:**
- Five of the eight are at confidence 0.5 or more (b04, b37, b40, b46, b58). Each of them fires clause (a) in its
  document; the other three, at 0.4, don't.
- The engine's verdict doesn't depend on them: the entity clause flags all eight documents.
- The pairwise baseline's verdict does. It flags 6 of the 20 equality-break cycle documents (its equality-break F1 is
  0.414): the five above, plus b25.
- b25's flag comes from a pair outside the planted cycle: claim 0 "Milo was the first to walk in." and claim 8 "Mina
  was already seated at the far table, sorting through glazes she had picked out the week before.", contradicts 0.6.
  That timing tension is in base 25's shared text. The judge labeled the same two claims unrelated (0.6) in
  b25-consistent and contradicts (0.5) in b25-direct.
