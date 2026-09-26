"""Seeded skeletons for v1's plant types (XONFORGE_SPEC.md §5.2, §5.3b).

Each builder returns (slots, changed, params). A slot is (twin fields, planted fields, position). ``changed`` is the
slot whose twin and planted fields differ. Judged types are satisfiable either way; the tension is labeled, not
solved.
"""
from __future__ import annotations

MILES_PER_KM = 0.621371


def _f(**kw) -> dict:
    kw.setdefault("kind", "value")
    return kw


def temporal_arithmetic(rng, twin_rng, entities, attribute, premise):
    (e,) = entities
    dep = _f(kind="event", subject=e, attribute=attribute, role="departure", time="15:00")
    dur = _f(kind="premise", subject=e, attribute=attribute, role="duration", value=120)
    twin = _f(subject=e, attribute=attribute, role="arrival", value="17:00",
              derivation="15:00 + 2 h = 17:00")
    planted = {**twin, "value": "16:00", "derivation": "15:00 + 2 h = 16:00"}
    return [(dep, dep, 0), (dur, dur, 1), (twin, planted, 2)], 2, {}


def quantity_arithmetic(rng, twin_rng, entities, attribute, premise):
    (e,) = entities
    opening = _f(kind="premise", subject=e, attribute=attribute, role="opening", value=12)
    transfer = _f(kind="event", subject=e, attribute=attribute, role="transfer", value=5)
    twin = _f(subject=e, attribute=attribute, role="closing", value=7, derivation="12 - 5 = 7")
    planted = {**twin, "value": 12, "derivation": "12 - 5 = 12"}
    return [(opening, opening, 0), (transfer, transfer, 1), (twin, planted, 2)], 2, {}


def spatial_containment(rng, twin_rng, entities, attribute, premise):
    a, b, c = entities
    def edge(s, o):
        return _f(kind="relation", subject=s, attribute=attribute, relation="contains", object=o)
    one, two = edge(a, b), edge(b, c)
    return [(one, one, 0), (two, two, 1), (edge(a, c), edge(c, a), 2)], 2, {}


def coreference_trap(rng, twin_rng, entities, attribute, premise):
    a, b = entities
    same = _f(kind="relation", subject=a, attribute=attribute, relation="same", object=b)
    different = {**same, "relation": "different"}
    red = _f(subject=a, attribute=attribute, value="red")
    blue = _f(subject=b, attribute=attribute, value="blue")
    return [(different, same, 0), (red, red, 1), (blue, blue, 2)], 0, {}


def negation_scope(rng, twin_rng, entities, attribute, premise):
    (e,) = entities
    everyone = _f(kind="premise", subject=None, attribute=attribute, role="universal", value="everyone")
    held = _f(subject=e, attribute=attribute, value="arrived", negated=False)
    denied = {**held, "negated": True}
    return [(everyone, everyone, 0), (held, denied, 1)], 1, {}


def quantifier_violation(rng, twin_rng, entities, attribute, premise):
    (e,) = entities
    universal = _f(kind="premise", subject=None, attribute=attribute, role="universal", value="left")
    stayed = _f(subject=e, attribute=attribute, value="stayed")
    left = {**stayed, "value": "left"}
    return [(universal, universal, 0), (left, stayed, 1)], 1, {}


def uniqueness_violation(rng, twin_rng, entities, attribute, premise):
    a, b = entities
    only = _f(kind="premise", subject=a, attribute=attribute, role="only", value="yes")
    other_no = _f(subject=b, attribute=attribute, value="no")
    other_yes = {**other_no, "value": "yes"}
    return [(only, only, 0), (other_no, other_yes, 1)], 1, {}


def colocation_conflict(rng, twin_rng, entities, attribute, premise):
    (e,) = entities
    lake = _f(subject=e, attribute=attribute, role="place", value="lake", time="12:00-17:00")
    later = _f(subject=e, attribute=attribute, role="place", value="library", time="18:00-19:00")
    clash = {**later, "time": "15:00-16:00"}
    return [(lake, lake, 0), (later, clash, 1)], 1, {}


def calendar_age(rng, twin_rng, entities, attribute, premise):
    birth = _f(kind="premise", subject=None, attribute=attribute, role="birth_year", value=1990)
    story = _f(kind="premise", subject=None, attribute=attribute, role="story_year", value=2026)
    twin = _f(kind="premise", subject=None, attribute=attribute, role="age_years", value=36,
              derivation="2026 - 1990 = 36")
    planted = {**twin, "value": 40, "derivation": "2026 - 1990 = 40"}
    return [(birth, birth, 0), (story, story, 1), (twin, planted, 2)], 2, {}


def cardinality_mismatch(rng, twin_rng, entities, attribute, premise):
    listed = _f(kind="premise", subject=None, attribute=attribute, role="count", value=2)
    twin = _f(kind="premise", subject=None, attribute=attribute, role="count", value=2)
    planted = {**twin, "value": 3, "derivation": "three, against a list of two"}
    return [(listed, listed, 0), (twin, planted, 1)], 1, {}


def unit_conversion(rng, twin_rng, entities, attribute, premise):
    (e,) = entities
    km = _f(subject=e, attribute=attribute, role="measure", value=10, unit="km")
    twin = _f(subject=e, attribute=attribute, role="measure", value=10 * MILES_PER_KM, unit="miles",
              derivation="10 km = 6.21371 miles")
    planted = {**twin, "value": 8, "derivation": "10 km is not 8 miles"}
    return [(km, km, 0), (twin, planted, 1)], 1, {}


def knowledge_perspective(rng, twin_rng, entities, attribute, premise):
    (e,) = entities
    told = _f(kind="event", subject=e, attribute=attribute, role="announced", time="09:00", value="the news")
    before = _f(kind="event", subject=e, attribute=attribute, role="surprised", time="08:00", value="the news")
    after = {**before, "time": "10:00"}
    return [(told, told, 0), (before, after, 1)], 1, {}


def _judged(role_a, value_a, role_b, twin_b, planted_b):
    def build(rng, twin_rng, entities, attribute, premise):
        (e,) = entities
        a = _f(subject=e, attribute=attribute, role=role_a, value=value_a)
        twin = _f(subject=e, attribute=attribute, role=role_b, value=twin_b)
        planted = {**twin, "value": planted_b}
        return [(a, a, 0), (twin, planted, 1)], 1, {"ground_truth": "judged"}
    return build


causal_inconsistency = _judged("cause", "rain", "effect", "played", "cancelled")
commonsense_impossibility = _judged("scene", "frozen", "act", "skated", "swam")
implicature_tension = _judged("soft", "every", "soft", "every", "some")


BUILDERS = {
    "temporal_arithmetic": (("schedule",), 1, temporal_arithmetic),
    "quantity_arithmetic": (("jars",), 1, quantity_arithmetic),
    "spatial_containment": (("containment",), 3, spatial_containment),
    "coreference_trap": (("identity",), 2, coreference_trap),
    "negation_scope": (("attendance",), 1, negation_scope),
    "quantifier_violation": (("presence",), 1, quantifier_violation),
    "uniqueness_violation": (("duty",), 2, uniqueness_violation),
    "colocation_conflict": (("place",), 1, colocation_conflict),
    "calendar_age": (("years",), 1, calendar_age),
    "cardinality_mismatch": (("children",), 1, cardinality_mismatch),
    "unit_conversion": (("distance",), 1, unit_conversion),
    "knowledge_perspective": (("news",), 1, knowledge_perspective),
    "causal_inconsistency": (("cause",), 1, causal_inconsistency),
    "commonsense_impossibility": (("scene",), 1, commonsense_impossibility),
    "implicature_tension": (("wording",), 1, implicature_tension),
}

# How many facts the plant lists. feasible() uses this, not the entity count.
PLANT_FACTS = {
    "temporal_arithmetic": 3, "quantity_arithmetic": 3, "spatial_containment": 3, "coreference_trap": 3,
    "negation_scope": 2, "quantifier_violation": 2, "uniqueness_violation": 2, "colocation_conflict": 2,
    "calendar_age": 3, "cardinality_mismatch": 2, "unit_conversion": 2, "knowledge_perspective": 2,
    "causal_inconsistency": 2, "commonsense_impossibility": 2, "implicature_tension": 2,
}

JUDGED = frozenset({"causal_inconsistency", "commonsense_impossibility", "implicature_tension"})


def apply_trap(name: str, planted):
    """A trap-only variant of ``planted``: satisfiable read correctly, and the naive reading's only contradiction is
    the plant's facts. The naive reading's fact ids are computed, not guessed."""
    from xonforge.solver.solver import NAIVE_OF, naive_contradiction
    from xonforge.skeleton.schema import Skeleton, Trap

    facts = list(planted.facts)
    by_id = {f.id: f for f in facts}
    plant_ids = list(planted.plant.facts)
    resolves: list[str] = []

    def put(fact):
        by_id[fact.id] = fact

    if name in ("quoted_speech", "hypothetical", "conditional", "reported_belief", "perspective_error"):
        reading = {"quoted_speech": "quote", "hypothetical": "hypothetical", "conditional": "hypothetical",
                   "reported_belief": "belief", "perspective_error": "belief"}[name]
        put(by_id[plant_ids[-1]].model_copy(update={"reading": reading}))
    elif name == "legitimate_correction":
        put(by_id[plant_ids[0]].model_copy(update={"reading": "corrected"}))
    elif name == "state_change":
        put(by_id[plant_ids[0]].model_copy(update={"time": "March"}))
        put(by_id[plant_ids[-1]].model_copy(update={"time": "April", "negated": True}))
    elif name == "role_handover":
        put(by_id[plant_ids[0]].model_copy(update={"time": "March"}))
        other = by_id[plant_ids[-1]]
        put(other.model_copy(update={"time": "April", "value": by_id[plant_ids[0]].value}))
    elif name == "time_zone":
        arrival = by_id[plant_ids[-1]].model_copy(update={"value": "14:00", "derivation": "15:00 + 4 h, minus 3 h"})
        put(arrival)
        offset = arrival.model_copy(update={"id": "f_offset", "role": "offset", "value": -180, "derivation": None})
        facts.append(offset)
        resolves.append(offset.id)
    elif name == "overnight_span":
        put(by_id[plant_ids[0]].model_copy(update={"time": "23:00"}))
        put(by_id[plant_ids[1]].model_copy(update={"value": 180}))
        put(by_id[plant_ids[-1]].model_copy(update={"value": "02:00", "derivation": "23:00 + 3 h = 02:00"}))
        mark = by_id[plant_ids[0]].model_copy(update={"id": "f_overnight", "role": "overnight", "time": None,
                                                     "kind": "premise", "value": 1, "derivation": None})
        facts.append(mark)
        resolves.append(mark.id)
    elif name in ("unit_equivalence", "approximation"):
        share = 0.05 if name == "unit_equivalence" else 0.1
        miles = 6 if name == "unit_equivalence" else 6
        put(by_id[plant_ids[-1]].model_copy(update={"value": miles, "derivation": None}))
        measure = by_id[plant_ids[-1]]
        tol = measure.model_copy(update={"id": "f_tolerance", "role": "tolerance", "value": share, "unit": None,
                                         "derivation": None})
        facts.append(tol)
        resolves.append(tol.id)
    elif name == "same_name":
        put(by_id[plant_ids[0]].model_copy(update={"relation": "different"}))
    else:
        raise ValueError(f"no trap is named {name!r}")

    ordered, seen = [], set()
    for fact in facts:
        current = by_id.get(fact.id, fact)
        if current.id not in seen:
            ordered.append(current)
            seen.add(current.id)
    draft = Skeleton(**{**planted.model_dump(), "variant": "trap_only", "plant": None,
                        "facts": [f.model_dump() for f in ordered],
                        "traps": [{"type": name, "facts": plant_ids, "naive": {"reading": NAIVE_OF[name],
                                                                              "contradiction": plant_ids,
                                                                              "resolves": resolves}}]})
    found = naive_contradiction(draft, draft.traps[0])
    if found is None or set(found) != set(plant_ids):
        raise ValueError(f"{name}: a naive reading flags {found}, and the plant's facts are {plant_ids}")
    trap = Trap(type=name, facts=tuple(plant_ids), naive={"reading": NAIVE_OF[name],
                                                         "contradiction": list(found), "resolves": resolves})
    return draft.model_copy(update={"traps": (trap,)})
