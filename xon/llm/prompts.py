"""Every prompt of the consistency engine (XON_A1_CONSISTENCY.md §3.2): no prompt text lives anywhere else.

System prompts are constants; user messages are built by the functions below from the text or the numbered claims.
Rev. 2.2's prompts (XON_A1_REV2_2_PRECISION.md) come after rev. 2.1's, which are kept verbatim.
"""
from __future__ import annotations

from .schemas import Claim, ClaimList

_JSON_ONLY = "Return only the JSON object required by the output schema."

EXTRACT_SYSTEM = f"""You extract the factual claims a text makes.

Return every atomic factual claim in the text, one proposition per claim:
- Split compound statements: "Ana is older than Ben and taller than Cy" is two claims.
- Make each claim self-contained: replace pronouns and other references with what they refer to.
- Preserve names, numbers, dates and units exactly as written.
- Leave out opinions, questions, instructions and sentences with no factual content.
- Do not add claims the text does not make, and do not correct or reconcile claims that conflict: extract them as \
written.

Fields of each claim:
- id: 0, 1, 2, ... in the order the claims appear in the text.
- text: the claim as one self-contained sentence.
- span: the excerpt of the text that states the claim, copied character for character.
- kind: "premise" if the text presents the claim as given, assumed or stipulated ("Assume that ...", "Suppose ...", \
"It is given that ..."); "quoted" if the text attributes the claim to someone else instead of stating it itself \
("Ben said that ...", "According to the report, ..."), in which case text states the attributed proposition itself, \
without the attribution; otherwise "asserted".

{_JSON_ONLY}"""

_TEXT_ONLY = ("Judge only from what the claims themselves say. Do not use outside knowledge or facts about the world: "
              "a claim bears on another only through its content.")
_WORLD_KNOWLEDGE = "You may use general world knowledge to decide how the claims bear on each other."


def relate_system(world_knowledge: bool = False) -> str:
    return f"""You judge how pairs of claims relate.

For each listed pair (A, B), assume that claim A is true and decide what that does to claim B:
- "supports": B becomes more likely;
- "contradicts": B becomes impossible or much less likely;
- "unrelated": neither.
Judge each pair using only its two statements, ignoring every other statement in the list, even if they seem \
relevant.
{_WORLD_KNOWLEDGE if world_knowledge else _TEXT_ONLY}

Return exactly one relation for each listed pair and no others: a and b are the pair's claim numbers as listed \
(a = A, b = B), rationale is one sentence of reasoning about how A bears on B, relation is the label that reasoning \
leads to, and confidence is your confidence from 0 to 1 that the label is right.

{_JSON_ONLY}"""


def pairs_system(world_knowledge: bool = False) -> str:
    return f"""You select the pairs of claims that bear on each other.

Given numbered claims, list every pair (a, b) with a < b in which the truth of one claim could make the other more \
likely, less likely or impossible, such as claims about the same entities, quantities, times or events. Leave out \
pairs that are clearly independent.
{_WORLD_KNOWLEDGE if world_knowledge else _TEXT_ONLY}

{_JSON_ONLY}"""


ENTITY_SYSTEM = f"""You extract the relations that claims state between entities.

Given numbered claims:
1. entities: the entities the claims mention (people, groups, objects, places, events). Merge mentions that refer to \
the same entity. id is a short lower-case canonical name ("alice"); mentions lists the surface forms used ("Alice", \
"she", "the older sister").
2. attributes: the attributes on which the claims compare entities, each under a canonical lower-case key ("age", \
"team", "arrival_time", "height", "rank"). arity is "binary" only if the text itself establishes that the attribute \
has exactly two possible values ("the game had two teams"), "multi" if the text establishes more than two possible \
values ("there were three teams"), and "unknown" otherwise. arity_span copies the sentence that establishes the \
arity, or is null when arity is "unknown".
3. relations: for every claim that states a relation between two entities on an attribute, one relation, with that \
claim's number as claim_id:
- "same": the two entities are equal on the attribute (same team, same age, arrived together);
- "different": they are unequal on the attribute (different teams);
- "greater": a strict order, a > b on the attribute. Normalize the direction: "younger", "earlier", "shorter" and \
other comparisons toward less become "greater" with the entities swapped, under the attribute's canonical key \
("Ana is younger than Ben" is age with a = ben, b = ana; "Ana arrived before Ben" is arrival_time with a = ben, \
b = ana).
confidence is your confidence from 0 to 1 that the claim states this relation. Use only relations that a claim \
states: do not infer relations that follow from other claims, and do not add relations from world knowledge.

{_JSON_ONLY}"""

DIRECT_SYSTEM = f"""You check a text for contradictions.

List any contradictions in the text: sets of statements in the text that cannot all be true together. For each, \
sentences copies the sentences of the text that form the contradiction, exactly as they appear, and explanation \
says in one sentence why they cannot all be true. If the text has no contradictions, return an empty list.

{_JSON_ONLY}"""


def _numbered(claims: list[Claim]) -> str:
    return "\n".join(f"{c.id}. {c.text}" for c in claims)


def extract_user(text: str) -> str:
    return f"<text>\n{text}\n</text>"


def direct_user(text: str) -> str:
    return f"<text>\n{text}\n</text>"


def relate_user(claims: ClaimList, pairs: list[tuple[int, int]]) -> str:
    used = sorted({i for p in pairs for i in p})
    by_id = {c.id: c for c in claims.claims}
    listed = "\n".join(f"({a}, {b})" for a, b in pairs)
    return f"Claims:\n{_numbered([by_id[i] for i in used])}\n\nPairs (A, B):\n{listed}"


def pairs_user(claims: ClaimList) -> str:
    return f"Claims:\n{_numbered(claims.claims)}"


def entity_user(claims: ClaimList) -> str:
    return f"Claims:\n{_numbered(claims.claims)}"


# ------------------------------------------------------------------------------------------ rev. 2.2
# The worked examples share no name, topic or content word with the L1 corpus (tests/test_rev22.py).
EXAMPLE_TENSION = ("The freezer was unplugged.", "The ice cream in the freezer was frozen solid.")
EXAMPLE_CONTRADICTS = ("The museum was shut all Sunday.", "Ada bought a ticket at the museum on Sunday.")


def relate_system_v2_2(world_knowledge: bool = False) -> str:
    return f"""You judge how a pair of claims relate.

For the pair (A, B), assume that claim A is true and decide what that does to claim B:
- "supports": B becomes more likely;
- "contradicts": A and B cannot both be true as written. Before choosing it, look for an ordinary reading under \
which both hold: different times, occasions, objects or people, or loose everyday wording. If there is one, the \
label is not "contradicts";
- "tension": both can be true, but together they are surprising or awkward, or one makes the other noticeably less \
likely;
- "unrelated": none of the above.
{_WORLD_KNOWLEDGE if world_knowledge else _TEXT_ONLY}

Examples:
- A: "{EXAMPLE_TENSION[0]}" B: "{EXAMPLE_TENSION[1]}" The label is "tension": both can be true (it may have been \
unplugged a moment ago), but A makes B surprising.
- A: "{EXAMPLE_CONTRADICTS[0]}" B: "{EXAMPLE_CONTRADICTS[1]}" The label is "contradicts": no ordinary reading lets \
both be true as written.

Return exactly one relation, for this pair: a and b are the pair's claim numbers as given (a = A, b = B), rationale \
is one or two sentences of reasoning about how A bears on B, relation is the label that reasoning leads to, and \
confidence is your confidence from 0 to 1 that the label is right.

{_JSON_ONLY}"""


RELATE_SYSTEM_V2_2 = relate_system_v2_2(False)
RELATE_SINGLE_USER_V2_2 = "A (claim {a}): {text_a}\nB (claim {b}): {text_b}"


def relate_single_user(claims: ClaimList, pair: tuple[int, int]) -> str:
    """The pair's two statements and ids, and nothing else from the document (§4.1)."""
    by_id = {c.id: c for c in claims.claims}
    a, b = pair
    return RELATE_SINGLE_USER_V2_2.format(a=a, text_a=by_id[a].text, b=b, text_b=by_id[b].text)


# The entity steps (§5.2): inventory, relations, and at most one coverage call. Development iteration 0's single
# entity call (ENTITY_SYSTEM_V2_2) is in the git history before iteration 1.
ENTITY_INVENTORY_SYSTEM_V2_2 = f"""You list the entities that claims mention and the attributes on which the claims \
compare them.

Given numbered claims:
1. entities: the entities the claims mention (people, groups, objects, places, events), each listed once. Merge \
mentions that refer to the same entity. id is a short lower-case canonical name ("alice"); mentions lists the surface \
forms used ("Alice", "she", "the older sister").
2. attributes: the attributes on which the claims compare entities, each listed once under one canonical lower-case \
key ("age", "team", "arrival_time", "height", "rank"), whatever words the claims use for it ("older" and "younger" \
both compare age). arity is "binary" only if the text itself establishes that the attribute has exactly two possible \
values ("the game had two teams"), "multi" if the text establishes more than two possible values ("there were three \
teams"), and "unknown" otherwise. arity_span copies the sentence that establishes the arity, or is null when arity is \
"unknown". order_kind says how the claims order entities on the attribute: "sequence" for an order in time or \
position, where greater means later (arriving, finishing, signing up); "magnitude" for an amount, where greater means \
more (age, height, weight, score); "other" for any other order, such as a ranking, with other_greater_means saying in \
a few words what greater means ("a better, numerically lower, rank"); null if no claim orders entities on the \
attribute. other_greater_means is null unless order_kind is "other".
List only the entities and attributes the claims mention; do not add any from world knowledge.

{_JSON_ONLY}"""

_ENTITY_STATEMENTS_V2_2 = """\
1. same_different: for every claim that states that two entities are equal or unequal on an attribute, one relation, \
with that claim's number as claim_id: "same" (same team, same age, arrived together) or "different" (different \
teams).
2. orders: for every claim that states a strict order between two entities on an attribute, one statement, with that \
claim's number as claim_id. subject and object are the claim's own grammatical subject and object, never swapped to \
normalize the direction, and comparative is the comparative word or phrase copied verbatim from the claim, with the \
"by" of a passive ("Otto signed after Kira" is subject otto, comparative "after", object kira; "Ana is younger than \
Ben" is subject ana, comparative "younger", object ben; "Kira was followed by Otto" is subject kira, comparative \
"followed by", object otto).
3. extremes: for every claim that states that an entity is the greatest or the least on an attribute, one statement \
with the entity and the superlative copied verbatim ("Kira signed first" is entity kira, comparative "first"). \
restriction copies verbatim any qualifier that limits the set the entity is compared with ("Kira signed first of the \
judges" has restriction "of the judges"; "the oldest on the team", "on the team"; "the first to the café", "to the \
café"), and is null when nothing limits it.
4. senses: for each distinct attribute and comparative in orders and extremes, exactly one sense, so that a \
comparative has one direction in the whole document. greater_side is "subject" or "object" for the side of an order \
statement that is greater under the attribute's order, "max" for a superlative naming the greatest entity, and "min" \
for one naming the least.
5. unsupported_order_claims: the numbers of the claims that state an order only with a negated or hedged comparative \
("not before", "maybe after"). Give such a claim no order statement.
confidence is your confidence from 0 to 1 that the claim states this. Use only what a claim states: do not infer \
relations or superlatives that follow from other claims, and do not add any from world knowledge."""

ENTITY_RELATIONS_SYSTEM_V2_2 = f"""You extract what claims state about entities.

Given numbered claims and the entities and attributes listed for them, report what each claim states, using only the \
listed entity ids and attribute keys:
{_ENTITY_STATEMENTS_V2_2}

{_JSON_ONLY}"""

ENTITY_COVERAGE_SYSTEM_V2_2 = f"""You check claims for statements about entities that were missed.

Each numbered claim below contains a word that can state an order ("before", "first", "older", "more"), and no \
statement was extracted from it. Given these claims and the entities and attributes listed for their document, \
decide for each claim whether it states a relation between listed entities on a listed attribute. If it does, report \
it as defined below, using only the listed entity ids and attribute keys. If it does not, list it under none with \
its number as claim_id and a one-sentence reason: many such words are not relational ("for the first time", "more \
people came"). Every listed claim gets a statement, a place in unsupported_order_claims, or an entry under none.
{_ENTITY_STATEMENTS_V2_2}

{_JSON_ONLY}"""


def _order_of(attribute) -> str:
    if attribute.order_kind == "sequence":
        return "sequence, greater = later"
    if attribute.order_kind == "magnitude":
        return "magnitude, greater = more"
    if attribute.order_kind == "other":
        return f"other, greater = {attribute.other_greater_means or 'not stated'}"
    return "no order"


def _inventory(entities: dict[str, list[str]], attributes: dict) -> str:
    listed = "\n".join(f"- {e}: {', '.join(m)}" if m else f"- {e}" for e, m in entities.items())
    keys = "\n".join(f"- {k} ({_order_of(a)})" for k, a in attributes.items())
    return f"Entities (id: mentions):\n{listed}\n\nAttributes (key, order):\n{keys}"


def entity_relations_user(claims: ClaimList, entities: dict[str, list[str]], attributes: dict) -> str:
    """The numbered claims and the inventory: entity id -> mentions, attribute key -> its declaration."""
    return f"Claims:\n{_numbered(claims.claims)}\n\n{_inventory(entities, attributes)}"


def entity_coverage_user(claims: ClaimList, listed: list[int], entities: dict[str, list[str]],
                         attributes: dict) -> str:
    """Only the listed claims, and the same inventory."""
    by_id = {c.id: c for c in claims.claims}
    return f"Claims:\n{_numbered([by_id[i] for i in listed])}\n\n{_inventory(entities, attributes)}"
