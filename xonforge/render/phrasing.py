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


def _word(value) -> str:
    if type(value) is int:
        return "one" if value == 1 else NUMBERS.get(value, str(value))
    return str(value)


def _person(skeleton: Skeleton, entity: str) -> str:
    found = next(e for e in skeleton.entities if e.id == entity)
    return f"{found.name}, {found.aliases[0]}," if found.aliases else found.name


def _role_statement(fact: Fact, skeleton: Skeleton) -> str | None:
    """v1 facts, in plain words. None when the fact is one v0 already phrases."""
    if fact.role is None and not (fact.relation == "greater" and fact.attribute == "place"):
        return None
    name = {e.id: e.name for e in skeleton.entities}
    s = name.get(fact.subject, "")
    o = name.get(fact.object, "") if fact.object else ""
    n = _word(fact.value)
    role = fact.role
    if fact.relation == "greater" and fact.attribute == "place":
        return f"{s} is inside {name[fact.object]}"
    if role == "q_start":
        return f"{s} had {n} jars"
    if role == "q_transfer":
        return f"{s} gave {n} jars to {o}"
    if role == "q_end":
        return f"{s} had {n} jars left"
    if role == "t_start":
        return f"{s} left at {fact.value}"
    if role == "t_duration":
        return f"{s} traveled for {n} hours"
    if role == "t_end":
        return f"{s} arrived at {fact.value}"
    if role == "t_offset":
        return f"For {s}, the destination clock is {n} hours behind"
    if role == "t_midnight":
        return f"{s} worked across midnight"
    if role == "conflate":
        return f"{_person(skeleton, fact.subject)} is the same person as {_person(skeleton, fact.object)}"
    if role == "distinct":
        return f"{_person(skeleton, fact.subject)} is a different person from {_person(skeleton, fact.object)}"
    if role == "quote":
        return f'{o} said "{s} is on the {fact.value} team"'
    if role == "present":
        return f"{s} had status {fact.value}"
    if role == "not_all":
        return f"Not every colleague of {s} shares status {fact.value}"
    if role == "guest_all":
        return f"All the guests with {s} left"
    if role == "guest_member":
        return f"{s} is a guest"
    if role == "guest_violates":
        return f"{s} stayed"
    if role == "only":
        return f"Only {s} had a key"
    if role == "also_holds":
        return f"{s} had a {fact.value}"
    if role == "until":
        return f"{s} was {fact.value} until March"
    if role == "after":
        return f"{s} is {fact.value} now"
    if role == "times_apply":
        return f"{s} held the office on a stated date"
    if role == "during":
        return f"{s} was at the {fact.value} from 12:00 until 17:00"
    if role == "at":
        return f"{s} was at the {fact.value} at {fact.time}"
    if role == "age_birth":
        return f"{s} was born in {n}"
    if role == "age_year":
        return f"{s} is in a story set in {n}"
    if role == "age_claimed":
        return f"{s} turned {n}"
    if role == "roster":
        children = ", ".join(name[e] for e in fact.scope[:-1]) + " and " + name[fact.scope[-1]]
        return f"{s}'s children are {children}"
    if role == "count":
        return f"{s} has {n} children"
    if role == "measure":
        unit = "kilometers" if fact.unit == "km" else "miles"
        return f"{s} ran {n} {unit}"
    if role == "approx":
        return f"{s} expected about {n} people"
    if role == "exact":
        return f"{s} counted {n} people"
    if role == "tolerance":
        return f"{s} allows a difference of {n}"
    if role == "announce":
        return f"{s} announced the {fact.value} at {fact.time}"
    if role == "surprise":
        return f"{s} was surprised by the {fact.value} at {fact.time}"
    if role == "belief":
        return f"{s} believed the result was {fact.value}"
    if role == "hypothetical":
        return f"If it rained, {s}'s match would be {fact.value}"
    if role == "correction":
        return f"Correction: {s}'s meeting was on {fact.value}"
    if role == "tension":
        return f"{s} {fact.value}"
    return None


def statement(fact: Fact, skeleton: Skeleton) -> str:
    """The fact in plain words, without a final full stop."""
    if fact.role == "record":
        plain = statement(fact.model_copy(update={"role": None}), skeleton)
        person = _person(skeleton, fact.subject)
        if plain.startswith(person):
            return f"{person}, on the record,{plain[len(person):]}"
        return f"On the record, {plain[0].lower() + plain[1:]}"
    phrased = _role_statement(fact, skeleton)
    if phrased is not None:
        return phrased
    a = fact.attribute
    if fact.states_arity:
        return f"There are exactly {NUMBERS.get(fact.value, fact.value)} {GROUP[a][3]}"
    s = _person(skeleton, fact.subject)
    if fact.relation == "greater":
        return GREATER[a].format(s=s, o=_person(skeleton, fact.object))
    if fact.relation in ("same", "different"):
        o = _person(skeleton, fact.object)
        if a in GROUP:
            return f"{s} is {GROUP[a][0 if fact.relation == 'same' else 1]} {o}"
        return (f"{s} has the same {noun(a)} as {o}" if fact.relation == "same"
                else f"{s} does not have the same {noun(a)} as {o}")
    if a not in GROUP:
        return f"{s} does not have {fact.value}" if fact.negated else f"{s} has {fact.value}"
    held = GROUP[a][2].format(v=fact.value)
    return f"{s} is not {held}" if fact.negated else f"{s} is {held}"


def is_assumption(fact: Fact) -> bool:
    """A premise about an entity is written as the document's assumption, as A1 wrote its premise ("Assume that
    ..."); a fact stating a number of values is written as a plain statement, as A1 wrote its arity sentence."""
    return fact.kind == "premise" and not fact.states_arity
