"""v1 plant types and traps (XONFORGE_SPEC.md §5.2, §5.3, §5.3b; §14, step 8).

Each base is a consistent twin and one planted variant. A trap, when asked for, adds a trap-only variant that differs
only in its resolving facts. A constraint fact applies only when every fact it depends on is present, so the plant's
facts are the only minimal contradiction. Judged plants are satisfiable; the tension is labeled, not solved.

Readings recorded in CHANGELOG_EXPERIMENTS.md and xonforge/docs/decisions.md: ``coreference_trap`` plants a real
contradiction that appears once two same-named people are identified (a ``conflate`` fact); ``same_name`` keeps them
distinct. ``greater`` on a location means "is inside".
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field

from xonforge.skeleton.catalog import CATEGORICAL, JUDGED_PLANTS, NAMES, ORDINAL, PRONOUNS, V1_PLANT_TYPES
from xonforge.skeleton.schema import Attribute, Base, Entity, Fact, Plant, Skeleton, Trap
from xonforge.solver.solver import READINGS, naive_contradiction

from .generators import Knobs, _distractors, _relation, _subseed

PLANT_FACTS = {
    "temporal_arithmetic": 3, "quantity_arithmetic": 4, "negation_scope": 4, "quantifier_violation": 3,
    "uniqueness_violation": 2, "colocation_conflict": 2, "calendar_age": 3, "cardinality_mismatch": 2,
    "unit_conversion": 2, "knowledge_perspective": 2, "coreference_trap": 3, "causal_inconsistency": 2,
    "commonsense_impossibility": 2, "implicature_tension": 2,
}


@dataclass
class Slot:
    twin: dict
    planted: dict
    trap: dict | None = None
    depends: list = field(default_factory=list)
    position: int | None = None
    only_trap: bool = False
    id: str = ""


@dataclass
class Plan:
    slots: list
    changed: int
    kind: str
    unit: str | None = None
    extra: list = field(default_factory=list)
    renames: dict = field(default_factory=dict)
    trap: str | None = None
    ground: str = "solver"
    soft: bool = False
    params: dict = field(default_factory=dict)


def _s(planted: dict, twin: dict | None = None, trap: dict | None = None, *, position: int | None = None,
       only_trap: bool = False) -> Slot:
    return Slot(twin if twin is not None else planted, planted, trap, [], position, only_trap)


def _v(**kw) -> dict:
    return kw


# ------------------------------------------------------------------------------------------ builders
def _temporal(rng, twin_rng, entities, attribute, traps) -> Plan:
    (who,) = entities
    start = _s(_v(kind="value", subject=who, attribute=attribute, value="3:00", role="t_start"), position=0)
    duration = _s(_v(kind="value", subject=who, attribute=attribute, value=2, unit="hours", role="t_duration"),
                  position=1)
    end = _v(kind="value", subject=who, attribute=attribute, value="4:00", role="t_end")
    arrived = _s(end, {**end, "value": "5:00"}, position=2)
    arrived.depends = [start, duration]
    return Plan([start, duration, arrived], 2, "time")


def _time_zone(rng, twin_rng, entities, attribute, traps) -> Plan:
    (who,) = entities
    start = _s(_v(kind="value", subject=who, attribute=attribute, value="13:00", role="t_start"), position=0)
    duration = _s(_v(kind="value", subject=who, attribute=attribute, value=4, unit="hours", role="t_duration"),
                  position=1)
    end = _v(kind="value", subject=who, attribute=attribute, value="14:00", role="t_end")
    arrived = _s(end, {**end, "value": "17:00"}, position=2)
    arrived.depends = [start, duration]
    offset = _s(_v(kind="value", subject=who, attribute=attribute, value=3, unit="hours", role="t_offset"),
                only_trap=True)
    return Plan([start, duration, arrived], 2, "time", extra=[offset], trap="time_zone")


def _overnight(rng, twin_rng, entities, attribute, traps) -> Plan:
    (who,) = entities
    start = _s(_v(kind="value", subject=who, attribute=attribute, value="23:00", role="t_start"), position=0)
    duration = _s(_v(kind="value", subject=who, attribute=attribute, value=3, unit="hours", role="t_duration"),
                  position=1)
    end = _v(kind="value", subject=who, attribute=attribute, value="02:00", role="t_end")
    arrived = _s(end, {**end, "value": "26:00"}, position=2)
    arrived.depends = [start, duration]
    midnight = _s(_v(kind="event", subject=who, attribute=attribute, role="t_midnight"), only_trap=True)
    return Plan([start, duration, arrived], 2, "time", extra=[midnight], trap="overnight_span")


def _quantity(rng, twin_rng, entities, attribute, traps) -> Plan:
    holder, ana, ben = entities
    start = _s(_v(kind="value", subject=holder, attribute=attribute, value=12, role="q_start"), position=0)
    first = _s(_v(kind="event", subject=holder, attribute=attribute, object=ana, value=5, role="q_transfer"),
               position=1)
    second = _s(_v(kind="event", subject=holder, attribute=attribute, object=ben, value=4, role="q_transfer"),
                position=2)
    end = _v(kind="value", subject=holder, attribute=attribute, value=5, role="q_end")
    left = _s(end, {**end, "value": 3}, position=3)
    left.depends = [start, first, second]
    return Plan([start, first, second, left], 3, "quantity", unit="jars")


def _approximation(rng, twin_rng, entities, attribute, traps) -> Plan:
    (who,) = entities
    approx = _s(_v(kind="value", subject=who, attribute=attribute, value=50, role="approx"), position=0)
    exact = _v(kind="value", subject=who, attribute=attribute, value=48, role="exact")
    counted = _s(exact, {**exact, "value": 50}, position=1)
    counted.depends = [approx]
    tolerance = _s(_v(kind="value", subject=who, attribute=attribute, value=5, role="tolerance"), only_trap=True)
    return Plan([approx, counted], 1, "quantity", extra=[tolerance], trap="approximation")


def _spatial(rng, twin_rng, entities, attribute, traps) -> Plan:
    j = twin_rng.randrange(len(entities))
    slots = []
    for i, (hi, lo) in enumerate(zip(entities, entities[1:] + entities[:1])):
        planted = _relation(hi, "greater", lo, attribute)
        twin = _relation(lo, "greater", hi, attribute) if i == j else planted
        slots.append(Slot(twin, planted, position=i))
    return Plan(slots, j, "location")


def _coreference(rng, twin_rng, entities, attribute, traps) -> Plan:
    a, b = entities
    red = _s(_v(kind="value", subject=a, attribute=attribute, value="red"), position=0)
    blue = _v(kind="value", subject=b, attribute=attribute, value="blue")
    other = _s(blue, {**blue, "value": "red"}, position=1)
    conflate = _v(kind="event", subject=a, attribute=attribute, object=b, role="conflate")
    distinct = _v(kind="event", subject=a, attribute=attribute, object=b, role="distinct")
    ident = _s(conflate, trap=distinct, position=2)
    return Plan([red, other, ident], 1, "categorical",
                renames={a: ("Sam", "the clerk"), b: ("Sam", "the driver")},
                trap="same_name" if traps else None)


def _negation_scope(rng, twin_rng, entities, attribute, traps) -> Plan:
    presents = [_s(_v(kind="value", subject=e, attribute=attribute, value="arrived", role="present"), position=i)
                for i, e in enumerate(entities)]
    claim = _v(kind="value", subject=entities[0], attribute=attribute, value="arrived", role="not_all", negated=True)
    scope = _s(claim, {**claim, "value": "left"}, position=len(entities))
    scope.depends = presents
    return Plan([*presents, scope], len(entities), "categorical")


def _quantifier(rng, twin_rng, entities, attribute, traps) -> Plan:
    (who,) = entities
    universal = _s(_v(kind="value", subject=who, attribute=attribute, value="left", role="guest_all"), position=0)
    member = _s(_v(kind="value", subject=who, attribute=attribute, value="guest", role="guest_member"), position=1)
    stayed = _v(kind="value", subject=who, attribute=attribute, value="stayed", role="guest_violates")
    left = _v(kind="value", subject=who, attribute=attribute, value="left", role="present")
    violation = _s(stayed, left, position=2)
    violation.depends = [universal, member]
    return Plan([universal, member, violation], 2, "categorical")


def _uniqueness(rng, twin_rng, entities, attribute, traps) -> Plan:
    kai, mina = entities
    only = _s(_v(kind="value", subject=kai, attribute=attribute, value="key", role="only"), position=0)
    held = _v(kind="value", subject=mina, attribute=attribute, value="key", role="also_holds")
    other = _s(held, {**held, "value": "pass"}, position=1)
    other.depends = [only]
    return Plan([only, other], 1, "categorical")


def _handover(rng, twin_rng, entities, attribute, traps) -> Plan:
    """``state_change`` uses captain; ``role_handover`` uses treasurer. The naive reading ignores the dates."""
    uma, ben = entities
    role = "captain" if traps == ("state_change",) else "treasurer"
    trap = traps[0]
    first = _v(kind="value", subject=uma, attribute=attribute, value=role, role="until", time="March")
    uma_s = _s(first, position=0)
    later = _v(kind="value", subject=ben, attribute=attribute, value=role, role="after", time="now")
    ben_s = _s(later, {**later, "value": "member"}, position=1)
    dated = _s(_v(kind="event", subject=uma, attribute=attribute, role="times_apply"), only_trap=True)
    return Plan([uma_s, ben_s], 1, "categorical", extra=[dated], trap=trap)


def _colocation(rng, twin_rng, entities, attribute, traps) -> Plan:
    (who,) = entities
    during = _s(_v(kind="value", subject=who, attribute=attribute, value="lake", role="during", time="12:00/17:00"),
                position=0)
    at = _v(kind="value", subject=who, attribute=attribute, value="library", role="at", time="15:00")
    later = _s(at, {**at, "time": "18:00"}, position=1)
    later.depends = [during]
    return Plan([during, later], 1, "location")


def _calendar(rng, twin_rng, entities, attribute, traps) -> Plan:
    (who,) = entities
    birth = _s(_v(kind="value", subject=who, attribute=attribute, value=1990, role="age_birth"), position=0)
    year = _s(_v(kind="value", subject=who, attribute=attribute, value=2026, role="age_year"), position=1)
    age = _v(kind="value", subject=who, attribute=attribute, value=40, role="age_claimed")
    claimed = _s(age, {**age, "value": 36}, position=2)
    claimed.depends = [birth, year]
    return Plan([birth, year, claimed], 2, "time")


def _cardinality(rng, twin_rng, entities, attribute, traps) -> Plan:
    parent, *children = entities
    roster = _s(_v(kind="event", subject=parent, attribute=attribute, role="roster", scope=tuple(children)), position=0)
    count = _v(kind="value", subject=parent, attribute=attribute, value=3, role="count")
    total = _s(count, {**count, "value": len(children)}, position=1)
    total.depends = [roster]
    return Plan([roster, total], 1, "quantity")


def _units(rng, twin_rng, entities, attribute, traps) -> Plan:
    """The default plant is 10 km against eight miles. ``unit_equivalence`` is 10 km against six miles, resolved by a
    tolerance of half a mile."""
    (who,) = entities
    km = _s(_v(kind="value", subject=who, attribute=attribute, value=10, unit="km", role="measure"), position=0)
    miles_value = 6 if traps else 8
    miles = _v(kind="value", subject=who, attribute=attribute, value=miles_value, unit="miles", role="measure")
    twin = {**miles, "value": 6.2}
    claim = _s(miles, twin, position=1)
    claim.depends = [km]
    extra = []
    trap = None
    if traps:
        extra = [_s(_v(kind="value", subject=who, attribute=attribute, value=0.5, role="tolerance"), only_trap=True)]
        trap = "unit_equivalence"
    return Plan([km, claim], 1, "quantity", extra=extra, trap=trap)


def _knowledge(rng, twin_rng, entities, attribute, traps) -> Plan:
    (who,) = entities
    told = _s(_v(kind="event", subject=who, attribute=attribute, value="code", role="announce", time="1"), position=0)
    surprise = _v(kind="event", subject=who, attribute=attribute, value="code", role="surprise", time="2")
    later = _s(surprise, {**surprise, "value": "prize"}, position=1)
    later.depends = [told]
    return Plan([told, later], 1, "categorical")


def _perspective(rng, twin_rng, entities, attribute, traps) -> Plan:
    (who,) = entities
    belief = _v(kind="value", subject=who, attribute=attribute, value="first", role="belief")
    asserted = _v(kind="value", subject=who, attribute=attribute, value="first")
    thought = _s(asserted, {**asserted, "value": "second"}, trap=belief, position=0)
    narration = _s(_v(kind="value", subject=who, attribute=attribute, value="second", role="record"), position=1)
    return Plan([thought, narration], 0, "categorical", trap="perspective_error")


def _quoted(rng, twin_rng, entities, attribute, traps) -> Plan:
    speaker, who = entities
    said = _v(kind="value", subject=who, attribute=attribute, value="blue")
    quote = _v(kind="event", subject=who, attribute=attribute, object=speaker, value="blue", role="quote")
    speech = _s(said, {**said, "value": "red"}, trap=quote, position=0)
    actual = _s(_v(kind="value", subject=who, attribute=attribute, value="red", role="record"), position=1)
    return Plan([speech, actual], 0, "categorical", trap="quoted_speech")


def _hypothetical(rng, twin_rng, entities, attribute, traps) -> Plan:
    (who,) = entities
    plain = _v(kind="value", subject=who, attribute=attribute, value="cancelled")
    hypo = _v(kind="event", subject=who, attribute=attribute, value="cancelled", role="hypothetical")
    claim = _s(plain, {**plain, "value": "played"}, trap=hypo, position=0)
    played = _s(_v(kind="value", subject=who, attribute=attribute, value="played", role="record"), position=1)
    return Plan([claim, played], 0, "categorical", trap="hypothetical")


def _correction(rng, twin_rng, entities, attribute, traps) -> Plan:
    (who,) = entities
    monday = _v(kind="value", subject=who, attribute=attribute, value="Monday")
    first = _s(monday, {**monday, "value": "Tuesday"}, position=0)
    tuesday = _s(_v(kind="value", subject=who, attribute=attribute, value="Tuesday", role="record"), position=1)
    fix = _s(_v(kind="event", subject=who, attribute=attribute, value="Tuesday", role="correction"), only_trap=True)
    fix.depends = [first]
    return Plan([first, tuesday], 0, "categorical", extra=[fix], trap="legitimate_correction")


def _belief(rng, twin_rng, entities, attribute, traps) -> Plan:
    (who,) = entities
    plain = _v(kind="value", subject=who, attribute=attribute, value="first")
    belief = _v(kind="event", subject=who, attribute=attribute, value="first", role="belief")
    thought = _s(plain, {**plain, "value": "second"}, trap=belief, position=0)
    narration = _s(_v(kind="value", subject=who, attribute=attribute, value="second", role="record"), position=1)
    return Plan([thought, narration], 0, "categorical", trap="reported_belief")


def _judged(values: tuple[str, str], twin_value: str, *, soft: bool = False):
    def build(rng, twin_rng, entities, attribute, traps) -> Plan:
        (who,) = entities
        first = _v(kind="event", subject=who, attribute=attribute, value=values[0], role="tension")
        opening = _s(first, {**first, "value": twin_value}, position=0)
        second = _s(_v(kind="event", subject=who, attribute=attribute, value=values[1], role="tension"), position=1)
        return Plan([opening, second], 0, "categorical", ground="judged", soft=soft)
    return build


# scenario, attribute keys, entity count (None: the cycle length), kind, unit, builder
_SCENARIOS = {
    "temporal_arithmetic": (("clock",), 1, "time", None, _temporal),
    "time_zone": (("clock",), 1, "time", None, _time_zone),
    "overnight_span": (("clock",), 1, "time", None, _overnight),
    "quantity_arithmetic": (("stock",), 3, "quantity", "jars", _quantity),
    "approximation": (("headcount",), 1, "quantity", None, _approximation),
    "spatial_containment": (("place",), None, "location", None, _spatial),
    "coreference_trap": (("team",), 2, "categorical", None, _coreference),
    "same_name": (("team",), 2, "categorical", None, _coreference),
    "negation_scope": (("status",), 3, "categorical", None, _negation_scope),
    "quantifier_violation": (("status",), 1, "categorical", None, _quantifier),
    "uniqueness_violation": (("badge",), 2, "categorical", None, _uniqueness),
    "state_change": (("office",), 2, "categorical", None, _handover),
    "role_handover": (("office",), 2, "categorical", None, _handover),
    "colocation_conflict": (("place",), 1, "location", None, _colocation),
    "calendar_age": (("clock",), 1, "time", None, _calendar),
    "cardinality_mismatch": (("headcount",), 3, "quantity", None, _cardinality),
    "unit_conversion": (("distance",), 1, "quantity", None, _units),
    "unit_equivalence": (("distance",), 1, "quantity", None, _units),
    "knowledge_perspective": (("news",), 1, "categorical", None, _knowledge),
    "perspective_error": (("finish",), 1, "categorical", None, _perspective),
    "quoted_speech": (("team",), 2, "categorical", None, _quoted),
    "hypothetical": (("status",), 1, "categorical", None, _hypothetical),
    "legitimate_correction": (("day",), 1, "categorical", None, _correction),
    "reported_belief": (("finish",), 1, "categorical", None, _belief),
    "causal_inconsistency": (("status",), 1, "categorical", None,
                             _judged(("cancelled the match", "played the match"), "postponed the match")),
    "commonsense_impossibility": (("status",), 1, "categorical", None,
                                  _judged(("swam the lake", "found the lake frozen"), "walked the lake")),
    "implicature_tension": (("status",), 1, "categorical", None,
                            _judged(("noted that some passed", "noted that every one passed"),
                                    "noted that many passed", soft=True)),
}

PLANTS = {name: (spec[0], spec[1], spec[4]) for name, spec in _SCENARIOS.items() if name in V1_PLANT_TYPES}


def _fact(slot: Slot, variant: str) -> Fact:
    if variant == "trap":
        fields = dict(slot.trap if slot.trap is not None else slot.planted)
    else:
        fields = dict(slot.twin if variant == "twin" else slot.planted)
    if slot.depends:
        fields["depends"] = tuple(d.id for d in slot.depends)
    return Fact(id=slot.id, **fields)


def build(plant_type: str, *, seed: int, genre: str, knobs: Knobs, traps: tuple[str, ...] = (),
          level: int | None = None) -> Base:
    """One v1 base. ``traps`` selects a trap scenario on the plant type's partner; at most one."""
    if len(traps) > 1:
        raise ValueError("a base carries one of these traps")
    scenario = traps[0] if traps else plant_type
    if scenario not in _SCENARIOS:
        raise ValueError(f"no v1 scenario is named {scenario!r}")
    kinds, size, kind, unit, builder = _SCENARIOS[scenario]
    rng = random.Random(f"xonforge:{plant_type}:{seed}:{scenario}")
    twin_seed = _subseed(plant_type, seed, "twin")
    k = size if size is not None else knobs.cycle_length
    n = knobs.entities or k
    if n < k:
        raise ValueError(f"a {scenario} plant needs {k} entities")
    entities = [Entity(id=f"e{i}", name=name, pronoun=rng.choice(PRONOUNS))
                for i, name in enumerate(rng.sample(NAMES, n), 1)]
    planted_key = kinds[0]
    pool = [a for a in ORDINAL + CATEGORICAL if a != planted_key]
    others = rng.sample(pool, knobs.attributes - 1)
    ids = [e.id for e in entities]
    in_plant = rng.sample(ids, k)
    plan = builder(rng, random.Random(twin_seed), in_plant, planted_key, traps)
    if plan.renames:
        entities = [e.model_copy(update={"name": plan.renames[e.id][0], "aliases": (plan.renames[e.id][1],)})
                    if e.id in plan.renames else e for e in entities]
    entities = tuple(entities)
    attributes = []
    for key in sorted([planted_key, *others]):
        if key == planted_key:
            attributes.append(Attribute(key=key, kind=plan.kind, unit=plan.unit))
        else:
            attributes.append(Attribute(key=key, kind="ordinal" if key in ORDINAL else "categorical"))
    attributes = tuple(attributes)
    outside = [e for e in ids if e not in in_plant]
    plant_slots = [s for s in plan.slots if s.position is not None]
    fillers = _distractors(rng, ids, [a for a in attributes if a.key != planted_key],
                           knobs.distractors * len(plant_slots), outside)
    main = plan.slots + [Slot(f, f) for f in fillers]
    rng.shuffle(main)
    for number, slot in enumerate(main, 1):
        slot.id = f"f{number}"
    for number, slot in enumerate(plan.extra, len(main) + 1):
        slot.id = f"f{number}"
    in_order = sorted(plant_slots, key=lambda s: s.position)
    changed = plan.slots[plan.changed]

    def facts(variant: str, slots: list[Slot]) -> tuple[Fact, ...]:
        return tuple(_fact(s, variant) for s in slots)

    plant = Plant(type=plant_type, facts=tuple(s.id for s in in_order),
                  params={"attribute": planted_key, "entities": in_plant, "differs_from_twin": [changed.id],
                          "twin_seed": twin_seed, "ground": plan.ground, **plan.params,
                          **({"soft": True} if plan.soft else {})})
    made_from = [plant_type, seed, genre, asdict(knobs), scenario]
    made_from += ([{"traps": list(traps)}] if traps else []) + ([{"level": level}] if level is not None else [])
    digest = hashlib.sha256(json.dumps(made_from, sort_keys=True).encode("utf-8")).hexdigest()[:8]
    base_id = f"{plant_type}-{seed}-{digest}"
    common = {"base_id": base_id, "genre": genre, "entities": entities, "attributes": attributes, "seed": seed,
              "difficulty": {"cycle_length": len(in_order), "entities": n, "attributes": knobs.attributes,
                             "distractor_density": knobs.distractors,
                             "same_attribute_distractors": knobs.same_attribute_distractors,
                             **({"level": level} if level is not None else {})}}
    consistent = Skeleton(variant="consistent", facts=facts("twin", main), twin_facts=plant.facts, **common)
    planted = Skeleton(variant="planted", facts=facts("planted", main), plant=plant, **common)
    trap_only = ()
    if plan.trap:
        trap_slots = main + plan.extra
        resolving = tuple(s.id for s in trap_slots if s.only_trap or s.trap is not None)
        trap_facts = facts("trap", trap_slots)
        trap = Trap(type=plan.trap, facts=plant.facts + tuple(s.id for s in plan.extra), resolving=resolving)
        draft = Skeleton(variant="trap_only", facts=trap_facts, traps=(trap,), **common)
        found = naive_contradiction(draft, trap)
        trap = Trap(type=trap.type, facts=trap.facts, resolving=trap.resolving,
                    naive={"reading": READINGS[plan.trap], "contradiction": list(found or ())})
        trap_only = (Skeleton(variant="trap_only", facts=trap_facts, traps=(trap,), **common),)
    return Base(base_id=base_id, consistent=consistent, planted=(planted,), trap_only=tuple(trap_only))
