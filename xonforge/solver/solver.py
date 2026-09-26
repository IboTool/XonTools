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
and the planted facts are that reading's only contradiction.

Refused (``Unsupported``): events, facts with a time, other attribute kinds, and the other traps, which come with v1
(§14, step 8); and a negated value on an attribute whose number of values is stated, since whether the negation names
one of the stated values is not decided (v0 never generates it).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping

from xonforge.skeleton.schema import Attribute, Base, Fact, Skeleton, Trap

TRAPS = ("arity_control",)
NAIVE_VALUES = 2         # arity_control's naive reading: the attribute has two values
NAIVE_READING = "the attribute has two values"


class Unsupported(ValueError):
    """A fact, attribute or variant the solver cannot judge yet."""


def _check_supported(attribute: Attribute, fact: Fact) -> None:
    if attribute.kind not in ("ordinal", "categorical"):
        raise Unsupported(f"attribute {attribute.key!r} is {attribute.kind}; v0 handles ordinal and categorical ones")
    if fact.kind == "event" or fact.time is not None:
        raise Unsupported(f"fact {fact.id}: events and facts with a time come with v1's plant types")
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


def satisfiable(facts: Iterable[Fact], attributes: Mapping[str, Attribute]) -> bool:
    by_attribute: dict[str, list[Fact]] = defaultdict(list)
    for f in facts:
        _check_supported(attributes[f.attribute], f)
        by_attribute[f.attribute].append(f)
    for key, fs in by_attribute.items():
        if any(f.states_arity for f in fs) and any(f.negated for f in fs):
            raise Unsupported(f"attribute {key!r}: a negated value on an attribute whose number of values is stated; "
                              "whether the negation names one of the stated values is not decided")
    return all(_consistent(fs) for _, fs in sorted(by_attribute.items()))


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


def _naive_facts(skeleton: Skeleton, trap: Trap) -> list[Fact]:
    """The skeleton's facts as a naive reading of the trap takes them."""
    if trap.type not in TRAPS:
        raise Unsupported(f"the {trap.type} trap comes with v1 (XONFORGE_SPEC.md §5.3, §14 step 8)")
    if skeleton.arity_fact is None or skeleton.arity_fact not in trap.facts:
        raise Unsupported("an arity_control trap lists the arity fact that resolves it")
    return [Fact(**{**f.model_dump(), "value": NAIVE_VALUES}) if f.id == skeleton.arity_fact else f
            for f in skeleton.facts]


def naive_contradiction(skeleton: Skeleton, trap: Trap) -> tuple[str, ...] | None:
    """The facts a naive reading of the trap would flag as unable to all be true, or None if it would flag none: for
    arity_control, the facts that cannot all be true if the attribute had two values, the arity fact aside."""
    core = minimal_contradiction(_naive_facts(skeleton, trap), {a.key: a for a in skeleton.attributes})
    return None if core is None else tuple(fid for fid in core if fid != skeleton.arity_fact)


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
    contradiction. A trap-only variant's facts can all be true, and under each trap's naive reading its trap's facts
    are the only minimal contradiction, the facts other than the arity fact being the ones its ``naive`` records."""
    if skeleton.traps and skeleton.variant != "trap_only":
        raise Unsupported("traps in consistent or planted variants come with v1 (XONFORGE_SPEC.md §5.3, §14 step 8)")
    attributes = {a.key: a for a in skeleton.attributes}
    if skeleton.variant == "consistent":
        core = minimal_contradiction(skeleton.facts, attributes)
        return [] if core is None else [f"the consistent variant's facts {', '.join(core)} cannot all be true"]
    if skeleton.variant == "planted":
        required = list(skeleton.plant.facts) + ([skeleton.arity_fact] if skeleton.arity_fact else [])
        return _only_contradiction(list(skeleton.facts), required, attributes, skeleton.arity_fact,
                                   "the plant's facts")
    core = minimal_contradiction(skeleton.facts, attributes)
    problems = [] if core is None else [f"read correctly, the trap variant's facts {', '.join(core)} cannot all be "
                                        "true"]
    for trap in skeleton.traps:
        naive = naive_contradiction(skeleton, trap)
        recorded = tuple(trap.naive.get("contradiction", ()))
        if naive is None:
            problems.append(f"the {trap.type} trap: a naive reading finds no contradiction")
        elif set(naive) != set(recorded) or trap.naive.get("reading") != NAIVE_READING:
            problems.append(f"the {trap.type} trap: the naive reading ({NAIVE_READING}) flags {', '.join(naive)}, "
                            f"and the trap records {', '.join(recorded) or 'nothing'}")
        problems += [f"the {trap.type} trap's naive reading: {p}" for p in _only_contradiction(
            _naive_facts(skeleton, trap), list(trap.facts), attributes, skeleton.arity_fact, "the trap's facts")]
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
            used = set(trap.facts) - {skeleton.arity_fact}
            match = [s for s in base.planted if set(s.plant.facts) == used]
            if not match:
                problems.append(f"trap variant {i}: the {trap.type} trap's facts are no planted variant's plant")
                continue
            outside = _differing(match[0], skeleton, [skeleton.arity_fact])
            if outside:
                problems.append(f"trap variant {i}: differs from its planted variant outside the arity fact, in facts "
                                f"{', '.join(outside)}")
    return problems
