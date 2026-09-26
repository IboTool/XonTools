"""Whether a skeleton's facts can all be true, and whether a base's variants are what they claim to be
(XONFORGE_SPEC.md §5.5).

Facts about different attributes never interact. On one attribute:
- ``same`` and ``different``: the two entities have equal or unequal values. Each entity has one value, and when no
  fact states the number of values, any number is possible (as A1 treats an unknown arity).
- ``greater`` (ordinal attributes only): the subject's value is strictly above the object's.
- value facts (categorical attributes): the subject's value is, or when negated is not, the named value.
- a premise without a subject (categorical attributes only) states the number of values k: the entities the facts
  name take at most k values between them, the named values among them (other values may belong to entities the facts
  don't name). Values the facts don't name are interchangeable.
- ``premise`` facts are otherwise facts like any other: the kind matters to rendering, not to truth.

A trap (§5.5) must hold when read correctly, and the solver records what a naive reading would wrongly conclude. v0's
one trap, ``arity_control`` (the user's item 20), is binary parity's planted facts with a fact stating three values:
read correctly, an odd cycle of differences fits three values; read naively, as if the attribute had two, it cannot,
and the planted facts are that reading's only contradiction. The other traps (step 8) each have their own naive
reading: a dropped resolving fact, or a role rewritten into an assertion.

v1 facts (step 8) carry a ``role``. A constraint fact applies only when every fact it ``depends`` on is present, so
each planted fact is essential. Quantity, time and location attributes, events and times are read when they have a
role the solver knows, or when the attribute itself is one of those kinds. ``greater`` on a location is containment.
Judged plants (§5.3b) are not solver contradictions: the other facts must still be able to hold, and the tension is
only labeled.

Refused (``Unsupported``): an event or a time on an ordinal or categorical attribute with no role; a value fact on an
ordinal attribute; a negated value on an attribute whose number of values is stated (v0 never generates it); and a
trap type that is not in the catalog.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping

from xonforge.skeleton.catalog import JUDGED_PLANTS, TRAPS
from xonforge.skeleton.schema import Attribute, Base, Fact, Skeleton, Trap

NAIVE_VALUES = 2         # arity_control's naive reading: the attribute has two values
NAIVE_READING = "the attribute has two values"
READINGS = {
    "arity_control": NAIVE_READING,
    "time_zone": "the clocks are in one zone",
    "overnight_span": "the clock does not cross midnight",
    "unit_equivalence": "the two numbers are on one scale",
    "approximation": "the number is exact",
    "same_name": "one name is one person",
    "quoted_speech": "a quotation is asserted",
    "hypothetical": "a hypothetical is asserted",
    "legitimate_correction": "a correction does not supersede",
    "state_change": "a role has no time",
    "role_handover": "a role has no time",
    "reported_belief": "a belief is asserted",
    "perspective_error": "a belief is asserted",
}
# Miles per kilometre. An exact pair may differ by at most EXACT_MILES; a tolerance fact widens that.
KM_TO_MILES = 0.621371192
EXACT_MILES = 0.05
DAY = 24 * 60


class Unsupported(ValueError):
    """A fact, attribute or variant the solver cannot judge yet."""


def _check_supported(attribute: Attribute, fact: Fact) -> None:
    if attribute.kind not in ("ordinal", "categorical", "quantity", "time", "location"):
        raise Unsupported(f"attribute {attribute.key!r} is {attribute.kind}; the solver handles ordinal, categorical, "
                          "quantity, time and location")
    if attribute.kind in ("quantity", "time", "location"):
        return
    if (fact.kind == "event" or fact.time is not None) and not fact.role:
        raise Unsupported(f"fact {fact.id}: an event or a time needs a role the solver can read")
    if fact.role or fact.kind == "event" or fact.time is not None:
        return
    if fact.relation is None and attribute.kind != "categorical":
        raise Unsupported(f"fact {fact.id}: value facts and stated numbers of values are handled on categorical "
                          "attributes only")


class _Classes:
    """Union-find over entity ids: the classes of entities stated to have the same value."""

    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def _has_cycle(above: Mapping[str, set[str]]) -> bool:
    state: dict[str, int] = {}                        # 1: on the current path, 2: done
    for start in sorted(above):
        if start in state:
            continue
        state[start] = 1
        stack = [(start, iter(sorted(above.get(start, ()))))]
        while stack:
            node, below = stack[-1]
            nxt = next(below, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                return True
            elif nxt not in state:
                state[nxt] = 1
                stack.append((nxt, iter(sorted(above.get(nxt, ())))))
    return False


def _within(facts: list[Fact], classes: _Classes, named: Mapping[str, object], k: int) -> bool:
    """Whether the classes the facts name can take at most k values between them: one value per class, classes stated
    different take different values, and a class with a named value takes it."""
    nodes = {classes.find(e) for f in facts for e in (f.subject, f.object) if e is not None}
    apart: dict[str, set[str]] = defaultdict(set)
    for f in facts:
        if f.relation == "different":
            a, b = classes.find(f.subject), classes.find(f.object)
            apart[a].add(b)
            apart[b].add(a)
    names = sorted(set(named.values()), key=repr)
    if len(names) > k:
        return False
    order = sorted(nodes, key=lambda c: (-len(apart[c]), c))
    value: dict[str, tuple] = {}

    def choices(c: str) -> list[tuple]:
        if c in named:
            return [("named", named[c])]
        fresh = sum(1 for kind, _ in set(value.values()) if kind == "fresh")
        return [("named", v) for v in names] + [("fresh", i) for i in range(min(fresh + 1, k - len(names)))]

    def place(i: int) -> bool:
        if i == len(order):
            return True
        c = order[i]
        for option in choices(c):
            if all(value.get(n) != option for n in apart[c]):
                value[c] = option
                if place(i + 1):
                    return True
                del value[c]
        return False

    return place(0)


def _consistent(facts: list[Fact]) -> bool:
    """Whether facts about one attribute can all be true."""
    bounds = {f.value for f in facts if f.states_arity}
    if len(bounds) > 1:
        return False
    facts = [f for f in facts if not f.states_arity]
    classes = _Classes()
    for f in facts:
        if f.relation == "same":
            classes.union(f.subject, f.object)
    for f in facts:
        if f.relation == "different" and classes.find(f.subject) == classes.find(f.object):
            return False
    above: dict[str, set[str]] = defaultdict(set)
    for f in facts:
        if f.relation == "greater":
            s, o = classes.find(f.subject), classes.find(f.object)
            if s == o:
                return False
            above[s].add(o)
    if _has_cycle(above):
        return False
    has: dict[str, set] = defaultdict(set)
    lacks: dict[str, set] = defaultdict(set)
    for f in facts:
        if f.relation is None:
            (lacks if f.negated else has)[classes.find(f.subject)].add(f.value)
    if any(len(v) > 1 or v & lacks[c] for c, v in list(has.items())):
        return False
    for f in facts:
        if f.relation == "different":
            a, b = has.get(classes.find(f.subject)), has.get(classes.find(f.object))
            if a and a == b:
                return False
    if bounds:
        return _within(facts, classes, {c: next(iter(v)) for c, v in has.items() if v}, bounds.pop())
    return True


def _clock(text: str) -> float:
    if ":" in text:
        hour, minute = text.split(":")
        return int(hour) * 60 + int(minute)
    return float(text)


def _num(fact: Fact) -> float:
    value = fact.value
    if isinstance(value, bool) or value is None:
        raise Unsupported(f"fact {fact.id}: a measured fact names a number")
    if isinstance(value, (int, float)):
        return float(value)
    return _clock(str(value))


def _minutes(fact: Fact) -> float:
    """The fact's amount in minutes. A clock is ``HH:MM``; a duration or offset in hours is multiplied by 60."""
    amount = _num(fact)
    return amount * 60 if fact.unit == "hours" else amount


def _apply_identity(facts: list[Fact]) -> list[Fact] | None:
    """Union entities a ``conflate`` fact identifies, and drop identity facts. None when a ``distinct`` fact names a
    pair that is also conflated."""
    if not any(f.role in ("conflate", "distinct") for f in facts):
        return facts
    classes = _Classes()
    for f in facts:
        if f.role == "conflate":
            classes.union(f.subject, f.object)
    for f in facts:
        if f.role == "distinct" and classes.find(f.subject) == classes.find(f.object):
            return None

    def root(entity: str | None) -> str | None:
        return None if entity is None else classes.find(entity)

    out = []
    for f in facts:
        if f.role in ("conflate", "distinct"):
            continue
        subject, obj = root(f.subject), root(f.object)
        if subject != f.subject or obj != f.object:
            f = f.model_copy(update={"subject": subject, "object": obj})
        out.append(f)
    return out


def _legacy(attribute: Attribute, facts: list[Fact]) -> bool:
    if any(f.role or f.unit or f.kind == "event" or f.time is not None for f in facts):
        return False
    if attribute.kind in ("ordinal", "categorical"):
        return True
    return attribute.kind == "location" and all(f.relation == "greater" for f in facts)


def _ready(fact: Fact, ids: set[str]) -> bool:
    return all(d in ids for d in fact.depends)


def _to_miles(fact: Fact) -> float:
    amount = _num(fact)
    if fact.unit == "km":
        return amount * KM_TO_MILES
    return amount


def _in_span(point: str, span: str) -> bool:
    start, end = span.split("/")
    return _clock(start) <= _clock(point) <= _clock(end)


_INERT = {"quote", "belief", "hypothetical", "tension", "t_offset", "t_midnight", "tolerance", "times_apply",
          "correction", "q_start", "q_transfer", "q_end", "t_start", "t_duration", "t_end", "age_birth", "age_year",
          "age_claimed", "count", "roster", "measure", "approx", "exact", "guest_all", "guest_member",
          "guest_violates", "only", "also_holds", "single", "announce", "surprise", "during", "at", "everyone",
          "not_all", "present", "until", "after", "conflate", "distinct"}


def _constrained(facts: list[Fact]) -> bool:
    """Whether a v1 constraint in ``facts`` fails. A constraint runs only when every fact it depends on is here, so a
    proper subset of a plant need not fail."""
    ids = {f.id for f in facts}
    suppressed: set[str] = set()
    for f in facts:
        if f.role == "correction" and _ready(f, ids):
            suppressed.update(f.depends)
    live = [f for f in facts if f.id not in suppressed]
    ids = {f.id for f in live}

    def need(fact: Fact, role: str) -> Fact:
        return next(g for g in live if g.id in fact.depends and g.role == role)

    for end in (f for f in live if f.role == "q_end" and _ready(f, ids)):
        transfers = [g for g in live if g.id in end.depends and g.role == "q_transfer"]
        if _num(need(end, "q_start")) - sum(_num(g) for g in transfers) != _num(end):
            return True
    for end in (f for f in live if f.role == "t_end" and _ready(f, ids)):
        expected = _minutes(need(end, "t_start")) + _minutes(need(end, "t_duration"))
        expected += sum(-_minutes(g) for g in live if g.role == "t_offset")
        if any(g.role == "t_midnight" for g in live):
            expected %= DAY
        if expected != _minutes(end):
            return True
    for claimed in (f for f in live if f.role == "age_claimed" and _ready(f, ids)):
        if _num(need(claimed, "age_year")) - _num(need(claimed, "age_birth")) != _num(claimed):
            return True
    for count in (f for f in live if f.role == "count" and _ready(f, ids)):
        if _num(count) != len(need(count, "roster").scope):
            return True
    for measure in (f for f in live if f.role == "measure" and f.depends and _ready(f, ids)):
        other = need(measure, "measure")
        tolerances = [g for g in live if g.role == "tolerance"]
        tol = _num(tolerances[0]) if tolerances else EXACT_MILES
        if abs(_to_miles(measure) - _to_miles(other)) > tol:
            return True
    for exact in (f for f in live if f.role == "exact" and _ready(f, ids)):
        tolerances = [g for g in live if g.role == "tolerance"]
        tol = _num(tolerances[0]) if tolerances else 0
        if abs(_num(need(exact, "approx")) - _num(exact)) > tol:
            return True
    for at in (f for f in live if f.role == "at" and _ready(f, ids)):
        during = need(at, "during")
        if at.value != during.value and at.time is not None and during.time is not None \
                and _in_span(at.time, during.time):
            return True
    for surprise in (f for f in live if f.role == "surprise" and _ready(f, ids)):
        announced = need(surprise, "announce")
        if surprise.subject == announced.subject and surprise.value == announced.value \
                and surprise.time is not None and announced.time is not None \
                and _clock(surprise.time) > _clock(announced.time):
            return True
    for violation in (f for f in live if f.role == "guest_violates" and _ready(f, ids)):
        return True
    for claim in (f for f in live if f.role == "not_all" and _ready(f, ids)):
        presents = [g for g in live if g.id in claim.depends and g.role == "present"]
        if presents and all(g.value == claim.value for g in presents):
            return True
    for also in (f for f in live if f.role == "also_holds" and _ready(f, ids)):
        if also.subject != need(also, "only").subject and also.value == need(also, "only").value:
            return True
    for single in (f for f in live if f.role == "single" and _ready(f, ids)):
        parts = [g for g in live if g.id in single.depends]
        if len({g.subject for g in parts}) > 1 and len({g.value for g in parts}) == 1:
            return True
    if any(f.role in ("until", "after") for f in live) and not any(f.role == "times_apply" for f in live):
        held: dict[object, set] = defaultdict(set)
        for f in live:
            if f.role in ("until", "after"):
                held[f.value].add(f.subject)
        if any(len(subjects) > 1 for subjects in held.values()):
            return True
    return False


def _v1_holds(facts: list[Fact], attribute: Attribute) -> bool:
    if _constrained(facts):
        return False
    ids = {f.id for f in facts}
    suppressed: set[str] = set()
    for f in facts:
        if f.role == "correction" and _ready(f, ids):
            suppressed.update(f.depends)
    projected = [f for f in facts if f.id not in suppressed and f.role not in _INERT]
    if not projected:
        return True
    if attribute.kind in ("quantity", "time", "location") and not all(f.relation == "greater" for f in projected):
        held: dict[str, set] = defaultdict(set)
        for f in projected:
            if f.relation is None and f.value is not None:
                held[f.subject].add(f.value)
        return all(len(v) <= 1 for v in held.values())
    if any(f.states_arity for f in projected) and any(f.negated for f in projected):
        raise Unsupported(f"attribute {attribute.key!r}: a negated value on an attribute whose number of values is "
                          "stated; whether the negation names one of the stated values is not decided")
    return _consistent(projected)


def satisfiable(facts: Iterable[Fact], attributes: Mapping[str, Attribute]) -> bool:
    rewritten = _apply_identity(list(facts))
    if rewritten is None:
        return False
    by_attribute: dict[str, list[Fact]] = defaultdict(list)
    for f in rewritten:
        _check_supported(attributes[f.attribute], f)
        by_attribute[f.attribute].append(f)
    for key, fs in by_attribute.items():
        attribute = attributes[key]
        if _legacy(attribute, fs):
            if any(f.states_arity for f in fs) and any(f.negated for f in fs):
                raise Unsupported(f"attribute {key!r}: a negated value on an attribute whose number of values is "
                                  "stated; whether the negation names one of the stated values is not decided")
            if not _consistent(fs):
                return False
        elif not _v1_holds(fs, attribute):
            return False
    return True


def minimal_contradiction(facts: Iterable[Fact], attributes: Mapping[str, Attribute]) -> tuple[str, ...] | None:
    """The ids of one minimal set of the facts that cannot all be true, or None if they all can. Each fact in turn is
    left out if the rest still cannot all be true."""
    core = list(facts)
    if satisfiable(core, attributes):
        return None
    for f in list(core):
        rest = [g for g in core if g.id != f.id]
        if not satisfiable(rest, attributes):
            core = rest
    return tuple(g.id for g in core)


_DROP = {
    "time_zone": {"t_offset"},
    "overnight_span": {"t_midnight"},
    "unit_equivalence": {"tolerance"},
    "approximation": {"tolerance"},
    "legitimate_correction": {"correction"},
    "state_change": {"times_apply"},
    "role_handover": {"times_apply"},
}
_ASSERT = {"quoted_speech": "quote", "hypothetical": "hypothetical", "reported_belief": "belief",
           "perspective_error": "belief"}


def _naive_facts(skeleton: Skeleton, trap: Trap) -> list[Fact]:
    """The skeleton's facts as a naive reading of the trap takes them."""
    if trap.type not in TRAPS:
        raise Unsupported(f"the {trap.type} trap is not one the solver reads")
    if trap.type == "arity_control":
        if skeleton.arity_fact is None or skeleton.arity_fact not in trap.facts:
            raise Unsupported("an arity_control trap lists the arity fact that resolves it")
        return [Fact(**{**f.model_dump(), "value": NAIVE_VALUES}) if f.id == skeleton.arity_fact else f
                for f in skeleton.facts]
    drop = _DROP.get(trap.type, set())
    out = []
    for f in skeleton.facts:
        if f.role in drop:
            continue
        if trap.type == "unit_equivalence" and f.role == "measure":
            f = f.model_copy(update={"unit": None})
        elif trap.type == "same_name" and f.role == "distinct":
            f = f.model_copy(update={"role": "conflate"})
        elif trap.type in _ASSERT and f.role == _ASSERT[trap.type]:
            f = f.model_copy(update={"role": None, "kind": "value"})
        out.append(f)
    return out


def naive_contradiction(skeleton: Skeleton, trap: Trap) -> tuple[str, ...] | None:
    """The facts a naive reading of the trap would flag as unable to all be true, or None if it would flag none.
    ``arity_control`` leaves out the arity fact, which the reading rewrites rather than flags."""
    core = minimal_contradiction(_naive_facts(skeleton, trap), {a.key: a for a in skeleton.attributes})
    if core is None:
        return None
    if trap.type == "arity_control":
        return tuple(fid for fid in core if fid != skeleton.arity_fact)
    return core


def _only_contradiction(facts: list[Fact], required: list[str], attributes: Mapping[str, Attribute],
                        arity_fact: str | None, what: str) -> list[str]:
    """The problems unless ``required`` is the facts' only minimal contradiction: they cannot all be true, and leaving
    out any one of them leaves facts that can. (Then every minimal contradiction contains every required fact, so it
    is exactly them.)"""
    problems = []
    if satisfiable([f for f in facts if f.id in required], attributes):
        problems.append(f"{what} with the arity fact can all be true" if arity_fact else f"{what} can all be true")
    for fid in required:
        core = minimal_contradiction([f for f in facts if f.id != fid], attributes)
        if core is not None:
            role = "arity fact" if fid == arity_fact else "planted fact"
            problems.append(f"without the {role} {fid}, the facts {', '.join(core)} still cannot all be true")
    return problems


def check_skeleton(skeleton: Skeleton) -> list[str]:
    """What is wrong with one variant; empty if nothing is. A consistent variant's facts can all be true. A planted
    variant's cannot, and its required facts (the plant's, and its arity fact when it has one) are its only minimal
    contradiction, except a judged plant (§5.3b), whose facts can all be true and whose tension is only labeled.
    A trap-only variant's facts can all be true, and under each trap's naive reading the facts that reading still
    sees are its only minimal contradiction; ``naive`` records that reading and the facts it flags."""
    if skeleton.traps and skeleton.variant != "trap_only":
        raise Unsupported("a trap is recorded on a trap-only variant, not on a consistent or planted variant "
                          "(XONFORGE_SPEC.md §5.1)")
    attributes = {a.key: a for a in skeleton.attributes}
    if skeleton.variant == "consistent":
        core = minimal_contradiction(skeleton.facts, attributes)
        return [] if core is None else [f"the consistent variant's facts {', '.join(core)} cannot all be true"]
    if skeleton.variant == "planted" and skeleton.plant.type in JUDGED_PLANTS:
        core = minimal_contradiction(skeleton.facts, attributes)
        problems = [] if core is None else [f"the judged variant's facts {', '.join(core)} cannot all be true"]
        if skeleton.plant.params.get("ground") != "judged":
            problems.append("a judged plant records that its ground is judged")
        if skeleton.plant.type == "implicature_tension" and skeleton.plant.params.get("soft") is not True:
            problems.append("implicature_tension is labeled soft")
        return problems
    if skeleton.variant == "planted":
        required = list(skeleton.plant.facts) + ([skeleton.arity_fact] if skeleton.arity_fact else [])
        return _only_contradiction(list(skeleton.facts), required, attributes, skeleton.arity_fact,
                                   "the plant's facts")
    core = minimal_contradiction(skeleton.facts, attributes)
    problems = [] if core is None else [f"read correctly, the trap variant's facts {', '.join(core)} cannot all be "
                                        "true"]
    for trap in skeleton.traps:
        if trap.type not in READINGS:
            raise Unsupported(f"the {trap.type} trap is not one the solver reads")
        naive = naive_contradiction(skeleton, trap)
        recorded = tuple(trap.naive.get("contradiction", ()))
        reading = READINGS[trap.type]
        if naive is None:
            problems.append(f"the {trap.type} trap: a naive reading finds no contradiction")
        elif set(naive) != set(recorded) or trap.naive.get("reading") != reading:
            problems.append(f"the {trap.type} trap: the naive reading ({reading}) flags {', '.join(naive)}, "
                            f"and the trap records {', '.join(recorded) or 'nothing'}")
        naive_facts = _naive_facts(skeleton, trap)
        present = {f.id for f in naive_facts}
        required = list(trap.facts) if trap.type == "arity_control" else [fid for fid in trap.facts if fid in present]
        arity = skeleton.arity_fact if trap.type == "arity_control" else None
        problems += [f"the {trap.type} trap's naive reading: {p}" for p in _only_contradiction(
            naive_facts, required, attributes, arity, "the trap's facts")]
    return problems


def _differing(a: Skeleton, b: Skeleton, allowed: Iterable[str]) -> list[str]:
    ours, theirs = {f.id: f for f in a.facts}, {f.id: f for f in b.facts}
    return sorted(fid for fid in ours.keys() | theirs.keys() if ours.get(fid) != theirs.get(fid) and fid not in allowed)


def check_base(base: Base) -> list[str]:
    """What is wrong with a base; empty if nothing is. Besides each variant's own check: each planted variant differs
    from the consistent twin only in its planted facts (§5.1); the twin's ``twin_facts`` are the plants' facts (the
    user's item 2); and each trap-only variant differs from the planted variant whose facts its trap uses only in the
    arity fact."""
    problems = [f"consistent twin: {p}" for p in check_skeleton(base.consistent)]
    planted_ids = list(dict.fromkeys(fid for s in base.planted for fid in s.plant.facts))
    if list(base.consistent.twin_facts) != planted_ids:
        problems.append(f"consistent twin: its twin_facts are {', '.join(base.consistent.twin_facts) or 'none'}, and "
                        f"the plants' facts {', '.join(planted_ids)}")
    for i, skeleton in enumerate(base.planted, 1):
        problems += [f"planted variant {i}: {p}" for p in check_skeleton(skeleton)]
        outside = _differing(base.consistent, skeleton, skeleton.plant.facts)
        if outside:
            problems.append(f"planted variant {i}: differs from the consistent twin outside its plant, in facts "
                            f"{', '.join(outside)}")
    for i, skeleton in enumerate(base.trap_only, 1):
        problems += [f"trap variant {i}: {p}" for p in check_skeleton(skeleton)]
        for trap in skeleton.traps:
            extra = set(trap.resolving)
            if skeleton.arity_fact:
                extra.add(skeleton.arity_fact)
            match = [s for s in base.planted if set(s.plant.facts) - extra == set(trap.facts) - extra]
            if not match:
                problems.append(f"trap variant {i}: the {trap.type} trap's facts are no planted variant's plant")
                continue
            outside = _differing(match[0], skeleton, extra)
            if outside:
                where = "the arity fact" if extra == {skeleton.arity_fact} else "its resolving facts"
                problems.append(f"trap variant {i}: differs from its planted variant outside {where}, in facts "
                                f"{', '.join(outside)}")
    return problems
