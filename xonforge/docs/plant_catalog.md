# Plant catalog (v0)

v0's plant types (`XONFORGE_SPEC.md` §5.2; §14, step 2), with the solver's logic and each type's consistent twin, as
the user decided them (`CHANGELOG_EXPERIMENTS.md`, XonForge step 2). The generators are in
`xonforge/skeleton/generators.py`, the solver in `xonforge/solver/solver.py`, and
`python -m xonforge skeletons --genre G` builds and checks a few bases of each, offline.

Every base has a consistent twin and one planted variant, so each document holds one planted contradiction and
localization stays unambiguous. The two differ only in the planted facts. The solver keeps a base only if its twin's
facts can all be true and the planted variant's required facts are its only minimal contradiction: they cannot all be
true, and leaving out any one of them leaves facts that can. The required facts are the plant's and, for
`binary_parity`, the arity fact.

| type | planted | consistent twin | solver |
|---|---|---|---|
| `order_cycle` | k facts (3 to 6): A > B, B > C, ..., K > A on one ordinal attribute (age, height, arrival, score, speed) | one relation reversed: an acyclic order (A > B, B > C, A > C) | equality classes contracted, then a directed cycle, or an order within one class |
| `equality_break` | k facts: A same as B, ..., J same as K, and K different from A, on one categorical attribute (team, club, department, table, cabin) whose number of values the text leaves unstated | one "same" turned into "different" (A same as B, B different from C, A different from C) | union-find over "same"; a "different" inside one class |
| `binary_parity` | k facts: a cycle A, B, ..., K, A of "same" and "different" relations on one categorical attribute, an odd number d of them "different" (d from 3 to k, chosen by the seed); and, apart from the plant, the arity fact stating that the attribute has two values | one "different" turned into "same", with the two values kept (A different from B, B different from C, A same as C) | classes coloured with at most the stated number of values |
| `direct_negation` | 2 facts on one entity and categorical attribute: its value is v (a premise in a configurable share of documents), and it is not v | the negation replaced by one that holds: same place, entity, attribute and form, with only the negated value changed, to one the solver confirms is compatible with every other fact | a value and its negation on one entity |

The first two twins are the matched consistent controls the user chose for A1's corpus (`XON_A1_CONSISTENCY.md` §5,
rev. 2.1, and `CHANGELOG_EXPERIMENTS.md`). Binary parity's three-value control is the separate trap `arity_control`,
reported separately as in A1's corpus; it comes with the traps. A seed of its own, recorded in the plant's
`twin_seed`, chooses what the twin changes: the relation, or the order in which values are tried for the twin's
negation.

`binary_parity`'s d is at least 3 so that the contradiction needs the arity fact: with two "different" relations or
fewer, a cycle of "same" and "different" relations that cannot hold with two values cannot hold with any number
either. Its arity fact is recorded in the skeleton's `arity_fact`, appears in both variants, and goes into exports, so
that scoring can report its recovery separately.

`direct_negation` records in `premise_status` whether the claim is a premise, the same in both variants. The share of
premises is `skeletons.negation_premise_share` in `xonforge/config/defaults.yaml` (the user's default, 0.5). A base
whose status is not set by the caller draws it from its seed with that probability.

## The solver's semantics

Facts about different attributes never interact. Each entity has one value of an attribute. `same` and `different`
state equal or unequal values; when no fact states the number of values, any number is possible. A premise without a
subject states the number of values k of a categorical attribute: the entities the facts name take at most k values
between them, the named values among them. `greater` states a strictly higher value on an ordinal attribute (older,
taller, later, a higher score, faster). A value fact states that an entity's value is, or is not, the named value. A
premise otherwise counts as a fact like any other.

Still refused rather than guessed: an attribute kind other than ordinal, categorical, quantity, time or location; a
value fact on an ordinal attribute; a trap the solver does not list; and a negated value on an attribute whose number
of values is stated, since whether the negation names one of the stated values is not decided (no v0 generator
produces it).

## Knobs a skeleton sets (§5.4)

Cycle length (3 to 6 planted facts; `direct_negation`'s plant is always 2), entities (3 to 12; by default only the
plant's), attributes (2 to 8, the planted one included), distractor density (0 to 3 filler facts per planted fact),
and the same-attribute distractor setting. Every entity outside the plant appears in at least one distractor, and
knobs that no world can satisfy are refused. Document length, plant distance, explicitness and lexical variety are
set when a document is rendered (step 3).

Distractors are relations true of one hidden world, which never has more values on an attribute than its stated
number. They relate entities on the other attributes and, with the same-attribute setting, also entities outside the
plant on the planted attribute; the solver's check confirms that they neither add a contradiction nor remove the
plant's. The user decided that the setting is off at the lowest difficulty (as in L1) and on at higher levels: off at
level 1 and on at levels 2 and 3 (`xonforge/levels.py`, the user's item 4 of 2026-09-25).

## v1 plants, traps and hard negatives

v1's types are in `xonforge/skeleton/plants_v1.py`. `PLANT_TYPES` stays v0's four, so a sweep of those four is
unchanged; `V1_PLANT_TYPES` and `ALL_PLANT_TYPES` name the rest. Each generated base passes `check_base`.

| type | planted | consistent twin | solver |
|---|---|---|---|
| `temporal_arithmetic` | departed 15:00, 120 minutes, arrived 16:00 | arrived 17:00, which is 15:00 plus 120 minutes | arrival = departure + duration + offset |
| `quantity_arithmetic` | opened with 12, gave away 5, closed with 12 | closed with 7 | opening − transfers = closing |
| `spatial_containment` | A contains B, B contains C, C contains A | A contains C, and no cycle | a containment cycle |
| `coreference_trap` | the two are the same person, and one is red and the other blue | they are different people | one person, two values |
| `negation_scope` | everyone shares the attribute, and one person does not | the person does | a negated exception to everyone |
| `quantifier_violation` | everyone's value is one value, and one person's is another | the person has the universal's value | an exception to a named universal |
| `uniqueness_violation` | only one person has the value, and another has it too | the other has a different value | a second holder of an "only" |
| `colocation_conflict` | at the lake 12:00–17:00 and at the library 15:00–16:00 | the library is 18:00–19:00 | overlapping places |
| `calendar_age` | born 1990, story set in 2026, age 40 | age 36 | age = story year − birth year |
| `cardinality_mismatch` | the count is 2 and the count is 3 | both counts are 2 | two counts of one attribute |
| `unit_conversion` | 10 km and 8 miles | 10 km and 6.21371 miles | miles within tolerance, or exactly |
| `knowledge_perspective` | announced at 09:00, surprised at 10:00 | surprised at 08:00, before the announcement | surprise after one's own announcement |
| `causal_inconsistency`, `commonsense_impossibility`, `implicature_tension` | a labeled tension | the other value of the same pair | satisfiable either way; `ground_truth: judged`; the judged split only, never a sealed test |

Arithmetic, time and location conclusions carry a `derivation`. A rendered document records them as inferred map
entries (`mode: inferred`, the support spans, the derivation), not as sentences of their own. v0 facts stay stated
or paraphrased.

Traps, each on the plant named in `TRAP_PLANTS`, stay satisfiable when read correctly. The solver records what a
naive reading flags. `arity_control` is unchanged. The others: a quote, a hypothesis or a belief is not an assertion;
a corrected claim does not still stand; a value at one time is not a value at every time; a shared name is not one
person. Resolvable traps store the resolving fact (`offset`, `overnight`, `tolerance`) on `naive.resolves`, and the
naive reading drops it.
