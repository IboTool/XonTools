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

On an ordinal or categorical attribute, an event or a time with no role, and a value fact on an ordinal attribute,
are refused. A negated value on an attribute whose number of values is stated is refused, since whether the negation
names one of the stated values is not decided (no generator produces it). Quantity, time, location, events and times
that carry a role, and the traps, are the v1 catalog below.

## Knobs a skeleton sets (§5.4)

Cycle length (3 to 6 planted facts; `direct_negation`'s plant is always 2), entities (3 to 12; by default only the
plant's), attributes (2 to 8, the planted one included), distractor density (0 to 3 filler facts per planted fact),
and the same-attribute distractor setting. Every entity outside the plant appears in at least one distractor, and
knobs that no world can satisfy are refused. Document length, plant distance, explicitness and lexical variety are
set when a document is rendered (step 3). v1 records the same-attribute setting and does not generate those
distractors: its filler stays on the other attributes.

Distractors are relations true of one hidden world, which never has more values on an attribute than its stated
number. They relate entities on the other attributes and, with the same-attribute setting, also entities outside the
plant on the planted attribute; the solver's check confirms that they neither add a contradiction nor remove the
plant's. The user decided that the setting is off at the lowest difficulty (as in L1) and on at higher levels: off at
level 1 and on at levels 2 and 3 (`xonforge/levels.py`, the user's item 4 of 2026-09-25).

## v1 plant types and traps (step 8)

`PLANT_TYPES` stays the four v0 types, so `python -m xonforge skeletons --type all` still builds only those. The v1
types are named on their own. A base still has a consistent twin and one planted variant. Asking for a trap adds one
trap-only variant and, for the v1 traps, switches the scenario to that trap's story. At most one such trap per base.
Domain families in §5.3b (agent transcripts, code and documentation, cross-document) are step 11a and are not here.

A constraint fact applies only when every fact it `depends` on is present, so each planted fact is essential. Judged
plants are satisfiable; `params["ground"]` is `judged`, `implicature_tension` is `soft`, and the whole base goes to
the judged split.

| type | planted | consistent twin | solver |
|---|---|---|---|
| `temporal_arithmetic` | left at 3:00, traveled 2 hours, arrived at 4:00 | the arrival is 5:00 | start plus duration, in minutes |
| `quantity_arithmetic` | 12 jars, gave 5 and 4 away, 5 left | 3 left | start minus the gifts |
| `spatial_containment` | a cycle of "inside" | one containment reversed | the ordinal cycle check; `greater` on a location means inside |
| `coreference_trap` | two people named Sam, both on the red team, and a fact that they are the same person | the second person is on the blue team | identifying them makes the two teams one contradiction |
| `negation_scope` | each person arrived, and "not all arrived" | the claim is that not all left | the claim fails when every listed arrival matches it |
| `quantifier_violation` | all the guests left, this person is a guest, and they stayed | they left | a violation fact, once its dependencies are present |
| `uniqueness_violation` | only one person had a key, and someone else had a key | the other person had a pass | the second holder of the same thing |
| `colocation_conflict` | at the lake from 12:00 until 17:00, and at the library at 15:00 | at the library at 18:00 | a point inside the span at a different place |
| `calendar_age` | born in 1990, a story set in 2026, turned 40 | turned 36 | year minus birth |
| `cardinality_mismatch` | three named children, and a count of 3 | the count is the number named | the count against the roster |
| `unit_conversion` | 10 km and 8 miles | 6.2 miles | kilometres times 0.621371192; an exact pair may differ by at most 0.05 miles |
| `knowledge_perspective` | announced the code at time 1, and was surprised by the code at time 2 | surprised by the prize | the same news, later |
| `causal_inconsistency` | cancelled the match, and played the match | postponed the match | judged; the solver only checks that nothing else contradicts |
| `commonsense_impossibility` | swam the lake, and found the lake frozen | walked the lake | judged; two tension facts, so a level-3 distractor can still name enough outside entities |
| `implicature_tension` | noted that some passed, and that every one passed | noted that many passed | judged and soft |

Traps are partners of a host plant, not extra plant types. The naive reading is what the solver records.

| trap | host | correct reading | naive reading |
|---|---|---|---|
| `arity_control` | `binary_parity` | three values | "the attribute has two values" |
| `time_zone` | `temporal_arithmetic` | the destination clock is 3 hours behind, so 13:00 plus 4 hours is 14:00 | "the clocks are in one zone"; the offset is dropped. Hours of offset are subtracted |
| `overnight_span` | `temporal_arithmetic` | 23:00 plus 3 hours is 02:00, crossing midnight | "the clock does not cross midnight". The twin's end is 26:00, so the raw sum holds without that fact. Midnight is modulo 1440 |
| `unit_equivalence` | `unit_conversion` | 10 km and 6 miles, within 0.5 miles | "the two numbers are on one scale" |
| `approximation` | `quantity_arithmetic` | about 50 and exactly 48, within 5 | "the number is exact" |
| `same_name` | `coreference_trap` | the two Sams are different people | "one name is one person" |
| `quoted_speech` | `direct_negation` | a quotation is not an assertion | "a quotation is asserted" |
| `hypothetical` | `direct_negation` | a hypothetical is not an assertion | "a hypothetical is asserted" |
| `legitimate_correction` | `direct_negation` | the correction supersedes the earlier day | "a correction does not supersede" |
| `reported_belief` | `direct_negation` | a belief is not the narration | "a belief is asserted" |
| `perspective_error` | `knowledge_perspective` | a mistaken belief, corrected by the narration | "a belief is asserted" |
| `state_change` | `uniqueness_violation` | captain until March, then someone else, and the dates apply | "a role has no time" |
| `role_handover` | `uniqueness_violation` | the same, for treasurer | "a role has no time" |

Where the twin states the same value twice, one of the two facts has role `record`. The solver still treats it as a
value. The wording inserts ", on the record," so the two sentences are not the same sentence. Quotation marks are
allowed only in a `quoted_speech` trap variant.
