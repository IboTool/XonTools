"""Solver checks for v1's plant types and traps (XONFORGE_SPEC.md §5.2, §5.3, §5.3b).

v0's facts (no role, no time, no containment, an assertion) are judged by solver.py as before. A fact with a role, a
time, a containment, or a reading other than an assertion is judged here. A reading other than an assertion is not
an assertion: a quote, a hypothesis, a belief or a corrected claim is ignored, which is what makes those traps hold.
"""
from __future__ import annotations

from collections import defaultdict

from xonforge.skeleton.schema import Attribute, Fact

# Miles in one of these units. Enough for the plant and the unit traps; anything else is refused by the generator.
TO_MILES = {"miles": 1.0, "kilometers": 0.621371, "km": 0.621371}
DAY = 24 * 60


def _minutes(value) -> int | None:
    if type(value) is int:
        return value
    if not isinstance(value, str) or ":" not in value:
        return None
    hour, minute = value.split(":", 1)
    if not (hour.isdigit() and minute.isdigit()):
        return None
    return int(hour) * 60 + int(minute)


def _interval(text: str) -> tuple[int, int] | None:
    """A time or a range, in minutes. "afternoon" is 12:00-17:00; one time is a point."""
    if text == "afternoon":
        return 12 * 60, 17 * 60
    if "-" in text and ":" in text:
        a, b = text.split("-", 1)
        start, end = _minutes(a), _minutes(b)
        if start is None or end is None:
            return None
        if end <= start:
            end += DAY
        return start, end
    point = _minutes(text)
    return None if point is None else (point, point)


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def holds(facts: list[Fact], attributes: dict[str, Attribute]) -> bool:
    """Whether the v1 constraints of these facts hold. Facts whose reading is not an assertion are ignored."""
    facts = [f for f in facts if f.reading == "assertion"]
    return (_quantity(facts) and _schedule(facts) and _containment(facts) and _universals(facts)
            and _uniqueness(facts) and _places(facts) and _calendar(facts) and _members(facts)
            and _measures(facts) and _knowledge(facts))


def _quantity(facts: list[Fact]) -> bool:
    """opening − the transfers = closing, when a closing is stated. An opening and a closing with no transfer are
    equal."""
    by: dict[tuple, dict] = defaultdict(lambda: {"opening": None, "transfers": 0.0, "closing": None, "n": 0})
    for f in facts:
        if f.role not in ("opening", "transfer", "closing"):
            continue
        slot = by[(f.attribute, f.subject)]
        slot["n"] += 1
        if f.role == "transfer":
            slot["transfers"] += float(f.value)
        elif slot[f.role] is not None:
            return False
        else:
            slot[f.role] = float(f.value)
    for slot in by.values():
        if slot["opening"] is None or slot["closing"] is None:
            continue
        if abs(slot["opening"] - slot["transfers"] - slot["closing"]) > 1e-6:
            return False
    return True


def _schedule(facts: list[Fact]) -> bool:
    """arrival = departure + duration + offset. With an overnight fact, the two may differ by whole days."""
    by: dict[tuple, dict] = defaultdict(dict)
    overnight = {f.attribute for f in facts if f.role == "overnight"}
    for f in facts:
        if f.role not in ("departure", "duration", "arrival", "offset"):
            continue
        slot = by.setdefault((f.attribute, f.subject), {})
        if f.role in slot:
            return False
        if f.role == "departure":
            slot[f.role] = _minutes(f.time if f.time is not None else f.value)
        elif f.role == "arrival":
            slot[f.role] = _minutes(f.value if f.value is not None else f.time)
        else:
            slot[f.role] = f.value if type(f.value) is int else None
    for (attribute, _), slot in by.items():
        if not {"departure", "duration", "arrival"} <= set(slot):
            continue
        if any(slot[k] is None for k in ("departure", "duration", "arrival")):
            return False
        expected = slot["departure"] + slot["duration"] + slot.get("offset", 0)
        arrival = slot["arrival"]
        if attribute in overnight:
            if expected % DAY != arrival % DAY:
                return False
        elif expected != arrival:
            return False
    return True


def _containment(facts: list[Fact]) -> bool:
    """A location contains another. A cycle cannot hold."""
    above: dict[str, set[str]] = defaultdict(set)
    nodes: set[str] = set()
    for f in facts:
        if f.relation != "contains":
            continue
        above[f.subject].add(f.object)
        nodes |= {f.subject, f.object}
    state: dict[str, int] = {}
    for start in sorted(nodes):
        if start in state:
            continue
        state[start] = 1
        stack = [(start, iter(sorted(above.get(start, ()))))]
        while stack:
            node, nxts = stack[-1]
            nxt = next(nxts, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                return False
            elif nxt not in state:
                state[nxt] = 1
                stack.append((nxt, iter(sorted(above.get(nxt, ())))))
    return True


def _universals(facts: list[Fact]) -> bool:
    """'Everyone' and 'not everyone' cannot both be stated. 'Everyone' cannot meet a negated exception, and a
    universal that names a value ('everyone left') cannot meet another value."""
    for attribute in {f.attribute for f in facts}:
        universals = [f for f in facts if f.attribute == attribute and f.role == "universal"]
        if not universals:
            continue
        said = {f.value for f in universals}
        if "everyone" in said and "not_everyone" in said:
            return False
        concrete = {v for v in said if v not in ("everyone", "not_everyone")}
        if "everyone" not in said and not concrete:
            continue
        for f in facts:
            if f.attribute != attribute or not f.subject or f.role == "universal":
                continue
            if "everyone" in said and f.negated:
                return False
            if concrete and not f.negated and f.value not in concrete:
                return False
    return True


def _uniqueness(facts: list[Fact]) -> bool:
    """'Only' one entity has the value. Another entity with it cannot hold."""
    for f in facts:
        if f.role != "only":
            continue
        others = [g for g in facts if g is not f and g.attribute == f.attribute and g.subject not in (None, f.subject)
                  and g.role != "only" and not g.negated and g.value == f.value
                  and not (f.time and g.time and f.time != g.time)]
        if others:
            return False
    return True


def _places(facts: list[Fact]) -> bool:
    """One entity in two places whose times overlap cannot hold."""
    by: dict[tuple, list[tuple]] = defaultdict(list)
    for f in facts:
        if f.role != "place" or not f.time:
            continue
        span = _interval(f.time)
        if span is None:
            return False
        by[(f.attribute, f.subject)].append((span, f.value))
    for stays in by.values():
        for i, (a, place_a) in enumerate(stays):
            for b, place_b in stays[i + 1:]:
                if place_a != place_b and _overlap(a, b):
                    return False
    return True


def _calendar(facts: list[Fact]) -> bool:
    """age = the story's year − the birth year, when all three are stated."""
    by: dict[str, dict] = defaultdict(dict)
    for f in facts:
        if f.role in ("birth_year", "story_year", "age_years"):
            if f.role in by[f.attribute]:
                return False
            by[f.attribute][f.role] = f.value
    for slot in by.values():
        if {"birth_year", "story_year", "age_years"} <= set(slot):
            if slot["age_years"] != slot["story_year"] - slot["birth_year"]:
                return False
    return True


def _members(facts: list[Fact]) -> bool:
    """A stated count of members, against the member facts. Two counts of one attribute cannot disagree."""
    counts: dict[str, set] = defaultdict(set)
    members: dict[str, int] = defaultdict(int)
    for f in facts:
        if f.role == "count":
            counts[f.attribute].add(f.value)
        elif f.role == "member":
            members[f.attribute] += 1
    for attribute, said in counts.items():
        if len(said) > 1:
            return False
        if members[attribute] and next(iter(said)) != members[attribute]:
            return False
    return True


def _measures(facts: list[Fact]) -> bool:
    """Two measures of one thing, converted to miles. A tolerance fact is a share of the larger; without one they
    must be equal."""
    groups: dict[tuple, list[float]] = defaultdict(list)
    tolerance: dict[str, float] = {}
    for f in facts:
        if f.role == "tolerance" and type(f.value) in (int, float):
            tolerance[f.attribute] = float(f.value)
        elif f.role == "measure":
            unit = f.unit or (attributes_unit(f, facts))
            if unit not in TO_MILES or type(f.value) not in (int, float):
                return False
            groups[(f.attribute, f.subject)].append(float(f.value) * TO_MILES[unit])
    for (attribute, _), values in groups.items():
        if len(values) < 2:
            continue
        span = max(values) - min(values)
        allowed = tolerance.get(attribute, 0.0) * max(abs(v) for v in values)
        if span > allowed + 1e-6:
            return False
    return True


def attributes_unit(fact: Fact, facts: list[Fact]) -> str:
    return fact.unit or ""


def _knowledge(facts: list[Fact]) -> bool:
    """A person is not surprised, later, by something they announced earlier."""
    announced: dict[tuple, int] = {}
    for f in facts:
        if f.role == "announced" and f.time:
            announced[(f.attribute, f.subject)] = _minutes(f.time) or 0
    for f in facts:
        if f.role != "surprised" or not f.time:
            continue
        earlier = announced.get((f.attribute, f.subject))
        if earlier is not None and (_minutes(f.time) or 0) > earlier:
            return False
    return True
