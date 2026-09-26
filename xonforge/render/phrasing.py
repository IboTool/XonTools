"""The plain wording of each fact that the renderer's prompt lists (XONFORGE_SPEC.md §6). How a document finally
phrases a fact is the renderer's work, within the explicitness and lexical-variety instructions."""
from __future__ import annotations

from xonforge.skeleton.schema import Fact, Skeleton

GREATER = {"age": "{s} is older than {o}", "height": "{s} is taller than {o}", "arrival": "{s} arrived later than {o}",
           "score": "{s} scored higher than {o}", "speed": "{s} is faster than {o}"}
ORDINAL_NOUN = {"age": "age", "height": "height", "arrival": "arrival time", "score": "score", "speed": "speed"}
# Each categorical attribute: "same", "different", a value, and the plural noun.
GROUP = {"team": ("on the same team as", "on a different team from", "on the {v} team", "teams"),
         "club": ("in the same club as", "in a different club from", "in the {v} club", "clubs"),
         "department": ("in the same department as", "in a different department from", "in the {v} department",
                        "departments"),
         "table": ("at the same table as", "at a different table from", "at table {v}", "tables"),
         "cabin": ("in the same cabin as", "in a different cabin from", "in the {v} cabin", "cabins")}
NUMBERS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
           11: "eleven", 12: "twelve"}


def noun(attribute: str) -> str:
    """What the attribute is called in a restriction ("their age", "their team")."""
    return ORDINAL_NOUN.get(attribute) or attribute


def statement(fact: Fact, skeleton: Skeleton) -> str:
    """The fact in plain words, without a final full stop."""
    name = {e.id: e.name for e in skeleton.entities}
    a = fact.attribute
    if fact.states_arity:
        return f"There are exactly {NUMBERS.get(fact.value, fact.value)} {GROUP[a][3]}"
    s = name[fact.subject]
    if fact.relation == "greater":
        return GREATER[a].format(s=s, o=name[fact.object])
    if fact.relation in ("same", "different"):
        o = name[fact.object]
        if a in GROUP:
            return f"{s} is {GROUP[a][0 if fact.relation == 'same' else 1]} {o}"
        return (f"{s} has the same {noun(a)} as {o}" if fact.relation == "same"
                else f"{s} does not have the same {noun(a)} as {o}")
    held = GROUP[a][2].format(v=fact.value)
    return f"{s} is not {held}" if fact.negated else f"{s} is {held}"


def is_assumption(fact: Fact) -> bool:
    """A premise about an entity is written as the document's assumption, as A1 wrote its premise ("Assume that
    ..."); a fact stating a number of values is written as a plain statement, as A1 wrote its arity sentence."""
    return fact.kind == "premise" and not fact.states_arity
