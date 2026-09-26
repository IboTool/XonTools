"""Seeded skeleton generators for v0's plant types (XONFORGE_SPEC.md §5.2; §14, step 2).

``generate`` builds one base: a consistent twin and one planted variant, so that each document holds one planted
contradiction and localization stays unambiguous. The two differ only in the planted facts (§5.1), and the twins
follow the user's decisions (CHANGELOG_EXPERIMENTS.md, XonForge step 2):
- ``order_cycle``, A1's matched control: the twin reverses one relation, which leaves an acyclic order
  (A > B > C, A > C).
- ``equality_break``, A1's matched control: the twin turns one "same" into "different" (A same as B, B different
  from C, A different from C).
- ``binary_parity``: a cycle of "same" and "different" relations, an odd number of them "different" and at least
  three, on a categorical attribute that a separate fact states has two values, so the contradiction needs that fact.
  The twin keeps the two values and turns one "different" into "same" (A different from B, B different from C, A
  same as C). The fact stating the number of values is the skeleton's ``arity_fact``: in both variants, apart from
  the plant's facts.
- ``direct_negation``: an entity has a value, and it does not. The twin replaces the negation with one that holds, in
  the same place, on the same entity and attribute: only the negated value changes, to one the solver confirms is
  compatible with every other fact. The claim is a premise in a configurable share of documents, and both variants
  record whether it is in ``premise_status``.
A seed of its own, recorded in the plant's ``twin_seed``, chooses what the twin changes. The twin records the facts at
the plant's positions as its ``twin_facts`` (the user's item 2 of 2026-09-25, xonforge/docs/decisions.md).

With ``traps=("arity_control",)`` a binary_parity base also gets a trap-only variant (the user's item 20): the planted
variant's facts with the arity fact stating three values instead of two. The solver records what a naive reading, of
two values, would flag: the planted facts.

Distractors are relational filler facts (§5.4), all true of one hidden world, so they cannot contradict anything, and
each entity outside the plant appears in at least one. They relate entities on the other attributes and, with the
``same_attribute_distractors`` setting, also entities outside the plant on the planted attribute. The facts are
shuffled before they are numbered, so an id says nothing about a fact's role.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from dataclasses import asdict, dataclass, field

from ..solver import satisfiable
from ..solver.solver import NAIVE_READING, naive_contradiction
from .catalog import CATEGORICAL, NAMES, ORDINAL, PRONOUNS, VALUES
from .schema import Attribute, Base, Entity, Fact, Plant, Skeleton, Trap

PLANT_TYPES = ("order_cycle", "equality_break", "binary_parity", "direct_negation")
TRAP_PLANTS = {
    "arity_control": ("binary_parity",),
    "quoted_speech": ("direct_negation",),
    "hypothetical": ("direct_negation",),
    "legitimate_correction": ("direct_negation",),
    "reported_belief": ("direct_negation",),
    "state_change": ("uniqueness_violation",),
    "role_handover": ("uniqueness_violation",),
    "time_zone": ("temporal_arithmetic",),
    "overnight_span": ("temporal_arithmetic",),
    "unit_equivalence": ("unit_conversion",),
    "approximation": ("quantity_arithmetic",),
    "same_name": ("coreference_trap",),
    "perspective_error": ("knowledge_perspective",),
}
TRAP_VALUES = 3                                          # the number of values an arity_control trap states
LEVELS = (1, 2, 3)                                       # the difficulty levels (xonforge/levels.py)


@dataclass(frozen=True)
class Knobs:
    """The difficulty knobs of §5.4 that a skeleton sets, within the spec's ranges. The others (document length, plant
    distance, explicitness, lexical variety) are set when a document is rendered (§6). ``direct_negation``'s plant is
    always two facts about one entity, so the cycle length does not apply to it."""
    cycle_length: int = 3            # planted facts in the minimal contradiction set: 3 to 6
    entities: int | None = None      # 3 to 12; None: only the plant's
    attributes: int = 2              # 2 to 8, the planted attribute included
    distractors: int = 0             # relational filler facts per planted fact: 0 to 3
    same_attribute_distractors: bool = False   # distractors may relate entities outside the plant on its attribute

    def __post_init__(self):
        ranges = [("cycle_length", self.cycle_length, 3, 6), ("attributes", self.attributes, 2, 8),
                  ("distractors", self.distractors, 0, 3)]
        if self.entities is not None:
            ranges.append(("entities", self.entities, 3, 12))
        for name, v, lo, hi in ranges:
            if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                raise ValueError(f"{name} is from {lo} to {hi} (XONFORGE_SPEC.md §5.4), not {v!r}")
        if self.entities is not None and self.entities < self.cycle_length:
            raise ValueError(f"a plant of {self.cycle_length} facts needs {self.cycle_length} entities")
        if not isinstance(self.same_attribute_distractors, bool):
            raise ValueError(f"same_attribute_distractors is True or False, not {self.same_attribute_distractors!r}")


@dataclass
class _Slot:
    twin: dict                       # a fact's fields, without its id, in the consistent twin
    planted: dict                    # and in the planted variant
    position: int | None = None      # its place in the plant, or None
    states_arity: bool = False       # whether it is the arity fact
    id: str = ""                     # its fact id, once the facts are shuffled


@dataclass
class _Plan:
    slots: list[_Slot]               # the plant's facts in plant order, then any arity fact
    changed: int                     # the position of the fact the twin changes
    params: dict = field(default_factory=dict)
    arity: int | None = None         # the planted attribute's stated number of values
    twin_options: list[dict] = field(default_factory=list)   # the changed fact's twin fields, tried in order


def _relation(subject: str, relation: str, obj: str, attribute: str) -> dict:
    return {"kind": "relation", "subject": subject, "attribute": attribute, "relation": relation, "object": obj}


def _order_cycle(rng: random.Random, twin_rng: random.Random, cycle: list[str], attribute: str,
                 premise: bool | None) -> _Plan:
    """c0 > c1 > ... > c(k-1) > c0; the twin reverses relation j."""
    j = twin_rng.randrange(len(cycle))
    slots = []
    for i, (hi, lo) in enumerate(zip(cycle, cycle[1:] + cycle[:1])):
        planted = _relation(hi, "greater", lo, attribute)
        slots.append(_Slot(_relation(lo, "greater", hi, attribute) if i == j else planted, planted, i))
    return _Plan(slots, j)


def _equality_break(rng: random.Random, twin_rng: random.Random, chain: list[str], attribute: str,
                    premise: bool | None) -> _Plan:
    """c0 same as c1, ..., c(k-2) same as c(k-1), and c(k-1) different from c0; the twin turns "same" j into
    "different"."""
    j = twin_rng.randrange(len(chain) - 1)
    slots = []
    for i, (a, b) in enumerate(zip(chain, chain[1:])):
        planted = _relation(a, "same", b, attribute)
        slots.append(_Slot(_relation(a, "different", b, attribute) if i == j else planted, planted, i))
    closing = _relation(chain[-1], "different", chain[0], attribute)
    slots.append(_Slot(closing, closing, len(chain) - 1))
    return _Plan(slots, j)


def _binary_parity(rng: random.Random, twin_rng: random.Random, cycle: list[str], attribute: str,
                   premise: bool | None) -> _Plan:
    """c0, c1, ..., c(k-1), c0 in a cycle, each relation "same" or "different", an odd number d >= 3 of them
    "different", and a fact stating that the attribute has two values; the twin turns "different" j into "same"."""
    k = len(cycle)
    d = rng.choice(range(3, k + 1, 2))
    apart = sorted(rng.sample(range(k), d))
    j = twin_rng.choice(apart)
    slots = []
    for i, (a, b) in enumerate(zip(cycle, cycle[1:] + cycle[:1])):
        planted = _relation(a, "different" if i in apart else "same", b, attribute)
        slots.append(_Slot(_relation(a, "same", b, attribute) if i == j else planted, planted, i))
    stated = {"kind": "premise", "subject": None, "attribute": attribute, "value": 2}
    slots.append(_Slot(stated, stated, states_arity=True))
    return _Plan(slots, j, params={"differences": d}, arity=2)


def _direct_negation(rng: random.Random, twin_rng: random.Random, entities: list[str], attribute: str,
                     premise: bool) -> _Plan:
    """The entity's value is v, stated as a premise or as a plain value fact, and it is not v; the twin's negation
    names another value, tried in the order the twin seed gives."""
    (e,) = entities
    v = rng.choice(VALUES[attribute])
    claim = {"kind": "premise" if premise else "value", "subject": e, "attribute": attribute, "value": v}
    negation = {"kind": "value", "subject": e, "attribute": attribute, "value": v, "negated": True}
    others = [w for w in VALUES[attribute] if w != v]
    twin_rng.shuffle(others)
    return _Plan([_Slot(claim, claim, 0), _Slot(negation, negation, 1)], 1,
                 twin_options=[{**negation, "value": w} for w in others])


# Each plant type: the attribute keys it may plant on, the entities its plant needs (None: the cycle length), and its
# builder.
PLANTS = {
    "order_cycle": (ORDINAL, None, _order_cycle),
    "equality_break": (CATEGORICAL, None, _equality_break),
    "binary_parity": (CATEGORICAL, None, _binary_parity),
    "direct_negation": (tuple(VALUES), 1, _direct_negation),
}


def _distractors(rng: random.Random, entities: list[str], attributes: list[Attribute], count: int,
                 unmentioned: list[str], planted: Attribute | None = None, outside: list[str] = ()) -> list[dict]:
    """``count`` relational facts, true of one hidden world, that mention every entity in ``unmentioned``: about
    ``attributes``, and, when ``planted`` is given, about it among the entities ``outside`` the plant. A world never
    has more values on an attribute than its stated number."""
    free = [(a, x, y) for a in attributes for x, y in itertools.combinations(entities, 2)]
    if planted:
        free += [(planted, x, y) for x, y in itertools.combinations(outside, 2)]
    need = -(-len(unmentioned) // 2)
    if count < need:
        raise ValueError(f"{len(entities)} entities need at least {need} distractor facts, to mention each; raise "
                         "the distractors or lower the entities")
    if count > len(free):
        raise ValueError(f"{count} distractor facts need {count} distinct pairs of entities, and the attributes "
                         f"they may use offer {len(free)}; raise the entities or the attributes")
    if not count:
        return []
    world = {}
    for a in attributes + ([planted] if planted else []):
        if a.kind == "ordinal":
            world[a.key] = dict(zip(entities, rng.sample(range(len(entities)), len(entities))))
        else:
            groups = rng.randint(2, min(a.arity or 4, len(entities)))
            world[a.key] = {e: rng.randrange(groups) for e in entities}
    rng.shuffle(free)
    chosen, todo = [], list(unmentioned)
    while todo:
        both = next((p for p in free if todo[0] in p[1:] and set(p[1:]) <= set(todo)), None)
        pick = both or next(p for p in free if todo[0] in p[1:])
        chosen.append(pick)
        free.remove(pick)
        todo = [e for e in todo if e not in pick[1:]]
    chosen += free[:count - len(chosen)]
    facts = []
    for a, x, y in chosen:
        values = world[a.key]
        if a.kind == "ordinal":
            hi, lo = (x, y) if values[x] > values[y] else (y, x)
            facts.append(_relation(hi, "greater", lo, a.key))
        else:
            if rng.random() < 0.5:
                x, y = y, x
            facts.append(_relation(x, "same" if values[x] == values[y] else "different", y, a.key))
    return facts


def _spec(plant_type: str):
    if plant_type in PLANTS:
        return PLANTS[plant_type]
    from .v1 import PLANTS as more
    if plant_type not in more:
        raise ValueError(f"not a plant type: {plant_type!r}")
    return more[plant_type]


def feasible(plant_type: str, knobs: Knobs) -> bool:
    """Whether ``generate`` can build a base of the plant type with the knobs: whether its distractors can mention
    every entity outside the plant, on pairs of entities that its attributes offer. v1 plants do not put distractors
    on the planted attribute, so that bonus is counted only for v0's types."""
    _, size, _ = _spec(plant_type)
    k = size or knobs.cycle_length
    n = knobs.entities or k
    if n < k:
        return False
    if plant_type == "direct_negation":
        planted = 2
    elif plant_type in PLANTS:
        planted = k
    else:
        from .v1 import PLANT_FACTS
        planted = PLANT_FACTS.get(plant_type, k)
    outside = n - k
    bonus = math.comb(outside, 2) if knobs.same_attribute_distractors and plant_type in PLANTS else 0
    free = (knobs.attributes - 1) * math.comb(n, 2) + bonus
    return -(-outside // 2) <= knobs.distractors * planted <= free


def _subseed(plant_type: str, seed: int, purpose: str) -> int:
    return int(hashlib.sha256(f"xonforge:{plant_type}:{seed}:{purpose}".encode("utf-8")).hexdigest()[:12], 16)


def generate(plant_type: str, *, seed: int, genre: str, knobs: Knobs = Knobs(), premise: bool | None = None,
             premise_share: float | None = None, traps: tuple[str, ...] = (), level: int | None = None) -> Base:
    """One base of ``plant_type``, the same for the same arguments. For ``direct_negation``, ``premise`` says whether
    the negated claim is a premise; when it is None, a draw from the base's seed makes it one with probability
    ``premise_share`` (defaults.yaml, skeletons.negation_premise_share). ``traps``: the trap-only variants to add;
    ``level``: the difficulty level the knobs were drawn for, recorded in the difficulty."""
    from .v1 import V1_PLANT_TYPES
    if plant_type not in PLANTS and plant_type not in V1_PLANT_TYPES:
        raise ValueError(f"v0's plant types are {', '.join(PLANT_TYPES)}, and v1 adds "
                         f"{', '.join(V1_PLANT_TYPES)}, not {plant_type!r}")
    if not genre:
        raise ValueError("a skeleton records its genre (XONFORGE_SPEC.md §5.1)")
    traps = tuple(traps)
    for t in traps:
        if t not in TRAP_PLANTS:
            raise ValueError(f"the traps are {', '.join(TRAP_PLANTS)}, not {t!r}")
        if plant_type not in TRAP_PLANTS[t]:
            raise ValueError(f"the {t} trap is {' and '.join(TRAP_PLANTS[t])}'s partner, not {plant_type}'s")
    if len(set(traps)) != len(traps):
        raise ValueError("each trap is asked for once")
    if level is not None and (isinstance(level, bool) or level not in LEVELS):
        raise ValueError(f"the difficulty levels are 1, 2 and 3, not {level!r}")
    v1_trap = any(t != "arity_control" for t in traps)
    if plant_type == "direct_negation" and premise is None and not v1_trap:
        if isinstance(premise_share, bool) or not isinstance(premise_share, (int, float)) \
                or not 0 <= premise_share <= 1:
            raise ValueError(f"direct_negation needs premise, or premise_share from 0 to 1, not {premise_share!r}")
        premise = random.Random(_subseed(plant_type, seed, "premise")).random() < premise_share
    elif plant_type != "direct_negation" and premise is not None:
        raise ValueError(f"only direct_negation's claim can be a premise, not {plant_type}'s")
    if premise is not None and not isinstance(premise, bool):
        raise ValueError(f"premise is True or False, not {premise!r}")
    if plant_type in V1_PLANT_TYPES or any(t != "arity_control" for t in traps):
        from .v1 import build as build_v1
        return build_v1(plant_type, seed=seed, genre=genre, knobs=knobs, traps=traps, level=level)
    kinds, size, build = PLANTS[plant_type]
    rng = random.Random(f"xonforge:{plant_type}:{seed}")
    twin_seed = _subseed(plant_type, seed, "twin")
    k = size or knobs.cycle_length
    n = knobs.entities or k
    entities = tuple(Entity(id=f"e{i}", name=name, pronoun=rng.choice(PRONOUNS))
                     for i, name in enumerate(rng.sample(NAMES, n), 1))
    planted_key = rng.choice(kinds)
    others = rng.sample([a for a in ORDINAL + CATEGORICAL if a != planted_key], knobs.attributes - 1)
    ids = [e.id for e in entities]
    in_plant = rng.sample(ids, k)
    plan = build(rng, random.Random(twin_seed), in_plant, planted_key, premise)
    in_order = [s for s in plan.slots if s.position is not None]
    attributes = tuple(Attribute(key=key, kind="ordinal" if key in ORDINAL else "categorical",
                                 arity=plan.arity if key == planted_key else None)
                       for key in sorted([planted_key, *others]))
    planted_attribute = next(a for a in attributes if a.key == planted_key)
    outside = [e for e in ids if e not in in_plant]
    fillers = _distractors(rng, ids, [a for a in attributes if a.key != planted_key], knobs.distractors * len(in_order),
                           outside, planted_attribute if knobs.same_attribute_distractors else None, outside)
    slots = plan.slots + [_Slot(f, f) for f in fillers]
    rng.shuffle(slots)
    for number, slot in enumerate(slots, 1):
        slot.id = f"f{number}"

    def facts(variant: str) -> tuple[Fact, ...]:
        return tuple(Fact(id=s.id, **getattr(s, variant)) for s in slots)

    changed = plan.slots[plan.changed]
    if plan.twin_options:
        for option in plan.twin_options:
            changed.twin = option
            if satisfiable(facts("twin"), {a.key: a for a in attributes}):
                break
        else:
            raise ValueError(f"{plant_type} seed {seed}: no value for the twin's negation is compatible with the other "
                             "facts")
    plant = Plant(type=plant_type, facts=tuple(s.id for s in in_order),
                  params={"attribute": planted_key, "entities": in_plant, "differs_from_twin": [changed.id],
                          "twin_seed": twin_seed, **plan.params,
                          **({"negated_claim": in_order[0].id, "negation": in_order[1].id}
                             if plant_type == "direct_negation" else {})})
    made_from = [plant_type, seed, genre, asdict(knobs)] + ([premise] if plant_type == "direct_negation" else [])
    made_from += ([{"traps": list(traps)}] if traps else []) + ([{"level": level}] if level is not None else [])
    digest = hashlib.sha256(json.dumps(made_from, sort_keys=True).encode("utf-8")).hexdigest()[:8]
    base_id = f"{plant_type}-{seed}-{digest}"
    stated = next((s for s in plan.slots if s.states_arity), None)
    common = {"base_id": base_id, "genre": genre, "entities": entities, "attributes": attributes, "seed": seed,
              "arity_fact": None if stated is None else stated.id,
              "premise_status": None if premise is None else ("premise" if premise else "not_premise"),
              "difficulty": {"cycle_length": len(in_order), "entities": n, "attributes": knobs.attributes,
                             "distractor_density": knobs.distractors,
                             "same_attribute_distractors": knobs.same_attribute_distractors,
                             **({"level": level} if level is not None else {})}}
    trap_only = []
    if "arity_control" in traps:
        three = tuple(Fact(id=s.id, **({**s.planted, "value": TRAP_VALUES} if s is stated else s.planted))
                      for s in slots)
        wider = tuple(Attribute(**{**a.model_dump(), "arity": TRAP_VALUES}) if a.key == planted_key else a
                      for a in attributes)
        trap = Trap(type="arity_control", facts=(*plant.facts, stated.id))
        draft = Skeleton(variant="trap_only", facts=three, traps=(trap,), **{**common, "attributes": wider})
        naive = {"reading": NAIVE_READING, "contradiction": list(naive_contradiction(draft, trap) or ())}
        trap = Trap(type=trap.type, facts=trap.facts, naive=naive)
        trap_only.append(Skeleton(variant="trap_only", facts=three, traps=(trap,), **{**common, "attributes": wider}))
    return Base(base_id=base_id,
                consistent=Skeleton(variant="consistent", facts=facts("twin"), twin_facts=plant.facts, **common),
                planted=(Skeleton(variant="planted", facts=facts("planted"), plant=plant, **common),),
                trap_only=tuple(trap_only))
