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


def _reading(fact: Fact, text: str) -> str:
    """A quote, a hypothesis, a belief or a corrected claim, wrapped around the assertion it would be."""
    lead = {"quote": "It was said that ", "hypothetical": "Suppose that ", "belief": "It was believed that ",
            "corrected": "A correction: "}
    return text if fact.reading == "assertion" else lead[fact.reading] + text[0].lower() + text[1:]


def _subjectless(fact: Fact) -> str:
    """A premise with no person: a universal, a year, a count, or the mark that a span crosses midnight."""
    word = noun(fact.attribute)
    if fact.role == "universal" and fact.value == "everyone":
        return f"Everyone shares one {word}"
    if fact.role == "universal" and fact.value == "not_everyone":
        return f"Not everyone shares one {word}"
    if fact.role == "universal":
        return f"Everyone's {word} is {fact.value}"
    if fact.role == "birth_year":
        return f"The birth year is {fact.value}"
    if fact.role == "story_year":
        return f"The story is set in {fact.value}"
    if fact.role == "age_years":
        return f"The age in years is {fact.value}"
    if fact.role == "count":
        return f"The number of {word} is {fact.value}"
    if fact.role == "overnight":
        return "The span crosses midnight"
    return f"The {word} is {fact.value}"


def _role(fact: Fact, name: dict[str, str]) -> str | None:
    """A v1 fact the solver reads by its role, or None when the v0 wording applies."""
    s = name[fact.subject]
    word = noun(fact.attribute)
    if fact.relation == "contains":
        return f"{s}'s {word} contains {name[fact.object]}"
    if fact.role == "departure":
        return f"{s} departed at {fact.time or fact.value}"
    if fact.role == "duration":
        return f"The journey took {fact.value} minutes"
    if fact.role == "arrival":
        return f"{s} arrived at {fact.value or fact.time}"
    if fact.role == "offset":
        return f"The clock offset is {fact.value} minutes"
    if fact.role == "opening":
        return f"{s} started with {fact.value} {word}"
    if fact.role == "transfer":
        return f"{s} gave away {fact.value} {word}"
    if fact.role == "closing":
        return f"{s} finished with {fact.value} {word}"
    if fact.role == "place":
        return f"{s} was at the {fact.value} during {fact.time}"
    if fact.role == "measure":
        return f"{s}'s {word} is {fact.value} {fact.unit or ''}".rstrip()
    if fact.role == "tolerance":
        return f"The figures may differ by {fact.value}"
    if fact.role == "only":
        return f"Only {s} has {word} {fact.value}"
    if fact.role == "announced":
        return f"{s} announced {fact.value} at {fact.time}"
    if fact.role == "surprised":
        return f"{s} was surprised by {fact.value} at {fact.time}"
    if fact.role in ("cause", "effect", "scene", "act", "soft"):
        return f"{s}'s {fact.role} is {fact.value}"
    if fact.kind == "event":
        return f"{s} did this at {fact.time}" if fact.time else f"{s} did this"
    return None


def statement(fact: Fact, skeleton: Skeleton) -> str:
    """The fact in plain words, without a final full stop."""
    name = {e.id: e.name for e in skeleton.entities}
    a = fact.attribute
    if fact.states_arity:
        return f"There are exactly {NUMBERS.get(fact.value, fact.value)} {GROUP[a][3]}"
    if fact.subject is None:
        return _reading(fact, _subjectless(fact))
    role = _role(fact, name)
    if role is not None:
        return _reading(fact, role)
    s = name[fact.subject]
    if fact.relation == "greater":
        return _reading(fact, GREATER[a].format(s=s, o=name[fact.object]))
    if fact.relation in ("same", "different"):
        o = name[fact.object]
        if a in GROUP:
            text = f"{s} is {GROUP[a][0 if fact.relation == 'same' else 1]} {o}"
        else:
            text = (f"{s} has the same {noun(a)} as {o}" if fact.relation == "same"
                    else f"{s} does not have the same {noun(a)} as {o}")
        return _reading(fact, text)
    if a in GROUP:
        held = GROUP[a][2].format(v=fact.value)
        text = f"{s} is not {held}" if fact.negated else f"{s} is {held}"
    else:
        text = f"{s}'s {noun(a)} is not {fact.value}" if fact.negated else f"{s}'s {noun(a)} is {fact.value}"
    return _reading(fact, text)


def is_assumption(fact: Fact) -> bool:
    """A premise about an entity is written as the document's assumption, as A1 wrote its premise ("Assume that
    ..."); a fact stating a number of values is written as a plain statement, as A1 wrote its arity sentence."""
    return fact.kind == "premise" and not fact.states_arity
