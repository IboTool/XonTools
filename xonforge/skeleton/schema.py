"""The skeleton schema (XONFORGE_SPEC.md §5.1).

Two fields are added to §5.1's Fact (CHANGELOG_EXPERIMENTS.md, XonForge step 2): ``relation`` names what a relation
fact states, which §5.1 leaves implicit (``greater``: the subject is above the object on an ordinal attribute;
``same`` or ``different``: the two have equal or unequal values), and ``negated`` marks a value fact stated as false,
which ``direct_negation`` needs. Step 8 adds ``role`` (what a v1 fact is doing: a ledger line, a quotation, a
belief), ``depends`` (the other facts a constraint needs before it applies) and ``unit``. An event may name an
``object`` (who was spoken to, who was given the jars) without being a relation.

A premise without a subject states its categorical attribute's number of values (its ``value``), and the attribute's
``arity`` repeats it. Two fields are added to §5.1's Skeleton for the user's step 2 decisions: ``arity_fact`` names
the fact stating the planted attribute's number of values, recorded apart from the plant's facts, and
``premise_status`` records whether a ``direct_negation`` document's negated claim is a premise.

Variants of one base share its id, seed, genre, entities, attributes, arity fact and premise status, and use the same
fact id for a fact and its counterpart, so a planted variant and its consistent twin can be compared fact by fact.

For the user's decisions of 2026-09-25 (xonforge/docs/decisions.md): a consistent twin records ``twin_facts``, its
counterparts of the plant's facts (item 2), which its checks treat as planted; a trap records ``naive``, what a naive
reading would wrongly conclude (§5.5), which the solver fills and checks, and ``resolving``, the facts a correct
reading uses and a naive reading drops or rewrites. v0's one trap is ``arity_control`` (item
20): binary parity's planted facts with a fact stating three values instead of two, so its variant's planted attribute
has arity 3 where the base's other variants have 2, the only way a trap variant's attributes may differ from theirs.
Entity ids are unique. Display names may repeat: ``coreference_trap`` and ``same_name`` are two people with one name.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

RELATIONS = ("greater", "same", "different")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Entity(_Frozen):
    id: str
    name: str
    pronoun: str
    aliases: tuple[str, ...] = ()


class Attribute(_Frozen):
    key: str
    kind: Literal["ordinal", "categorical", "quantity", "time", "location"]
    arity: int | None = None                  # the number of values, when the text states it
    unit: str | None = None


class Fact(_Frozen):
    id: str
    kind: Literal["relation", "value", "event", "premise"]
    subject: str | None                       # None only when the fact states its attribute's number of values
    attribute: str
    relation: Literal["greater", "same", "different"] | None = None
    object: str | None = None
    value: str | int | float | None = None
    negated: bool = False
    time: str | None = None
    role: str | None = None
    depends: tuple[str, ...] = ()       # other facts; a constraint applies only when every one of them is present
    scope: tuple[str, ...] = ()         # the entities a roster or a quantifier lists
    unit: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> Fact:
        relational = self.relation is not None
        if relational and self.object is None:
            raise ValueError(f"fact {self.id}: a relation needs an object")
        if self.object is not None and not relational and self.kind != "event":
            raise ValueError(f"fact {self.id}: a relation needs an object, and only a relation has one")
        if self.kind == "relation" and not relational:
            raise ValueError(f"fact {self.id}: a relation fact names its relation")
        if self.kind == "value" and relational:
            raise ValueError(f"fact {self.id}: a value fact has no relation")
        if relational and (self.value is not None or self.negated):
            raise ValueError(f"fact {self.id}: a relation has no value and is not negated")
        if not relational and self.kind != "event" and self.value is None:
            raise ValueError(f"fact {self.id}: a value fact names its value")
        if relational and self.object == self.subject:
            raise ValueError(f"fact {self.id}: a relation joins two different entities")
        if self.subject is None and not (self.kind == "premise" and not self.negated and type(self.value) is int
                                         and self.value >= 2):
            raise ValueError(f"fact {self.id}: only a premise stating its attribute's number of values, a whole "
                             "number of at least 2, has no subject")
        if len(set(self.depends)) != len(self.depends) or self.id in self.depends:
            raise ValueError(f"fact {self.id}: depends lists other facts, each once")
        return self

    @property
    def states_arity(self) -> bool:
        """Whether the fact states its attribute's number of values."""
        return self.subject is None


class Plant(_Frozen):
    type: str
    facts: tuple[str, ...]
    params: dict = {}


class Trap(_Frozen):
    type: str
    facts: tuple[str, ...]
    naive: dict = {}         # what a naive reading concludes: "reading", and "contradiction", the facts it would flag
    resolving: tuple[str, ...] = ()   # facts a correct reading uses and a naive reading drops or rewrites


class Skeleton(_Frozen):
    base_id: str
    variant: Literal["consistent", "planted", "trap_only"]
    genre: str
    entities: tuple[Entity, ...]
    attributes: tuple[Attribute, ...]
    facts: tuple[Fact, ...]
    plant: Plant | None = None
    traps: tuple[Trap, ...] = ()
    difficulty: dict = {}
    seed: int
    arity_fact: str | None = None
    premise_status: Literal["premise", "not_premise"] | None = None
    twin_facts: tuple[str, ...] = ()          # a consistent twin's counterparts of the plant's facts

    @model_validator(mode="after")
    def _references(self) -> Skeleton:
        entities = [e.id for e in self.entities]
        attributes = {a.key: a for a in self.attributes}
        facts = [f.id for f in self.facts]
        for what, ids in (("entity ids", entities),
                          ("attribute keys", [a.key for a in self.attributes]), ("fact ids", facts)):
            if len(set(ids)) != len(ids):
                raise ValueError(f"{self.base_id}: {what} are unique")
        stated: dict[str, str] = {}
        for f in self.facts:
            if any(e is not None and e not in entities for e in (f.subject, f.object)):
                raise ValueError(f"{self.base_id}: fact {f.id} names an entity the skeleton lacks")
            if f.attribute not in attributes:
                raise ValueError(f"{self.base_id}: fact {f.id} names an attribute the skeleton lacks")
            if f.relation == "greater" and attributes[f.attribute].kind not in ("ordinal", "location"):
                raise ValueError(f"{self.base_id}: fact {f.id} orders a non-ordinal attribute")
            if not set(f.depends) <= set(facts):
                raise ValueError(f"{self.base_id}: fact {f.id} depends on a fact the skeleton lacks")
            if not set(f.scope) <= set(entities):
                raise ValueError(f"{self.base_id}: fact {f.id} lists an entity the skeleton lacks")
            if f.states_arity:
                if attributes[f.attribute].kind != "categorical" or attributes[f.attribute].arity != f.value:
                    raise ValueError(f"{self.base_id}: fact {f.id} states the number of values of a categorical "
                                     "attribute, and the attribute's arity repeats it")
                if f.attribute in stated:
                    raise ValueError(f"{self.base_id}: at most one fact states the number of values of "
                                     f"{f.attribute}")
                stated[f.attribute] = f.id
        for a in self.attributes:
            if a.arity is not None and a.key not in stated:
                raise ValueError(f"{self.base_id}: attribute {a.key} has an arity only when a fact states it")
        if self.arity_fact is not None and self.arity_fact not in stated.values():
            raise ValueError(f"{self.base_id}: arity_fact names a fact stating an attribute's number of values")
        if self.arity_fact is not None and self.plant is not None and self.arity_fact in self.plant.facts:
            raise ValueError(f"{self.base_id}: the arity fact is recorded apart from the plant's facts")
        if (self.variant == "planted") != (self.plant is not None):
            raise ValueError(f"{self.base_id}: a planted variant, and only a planted variant, has a plant")
        if (self.variant == "trap_only") and not self.traps:
            raise ValueError(f"{self.base_id}: a trap-only variant has traps")
        for group in ([self.plant] if self.plant else []) + list(self.traps):
            if not group.facts or len(set(group.facts)) != len(group.facts) or not set(group.facts) <= set(facts):
                raise ValueError(f"{self.base_id}: a plant or trap lists distinct facts of the skeleton, at least one")
        for trap in self.traps:
            if len(set(trap.resolving)) != len(trap.resolving) or not set(trap.resolving) <= set(facts):
                raise ValueError(f"{self.base_id}: a trap's resolving facts are distinct facts of the skeleton")
        if self.twin_facts and self.variant != "consistent":
            raise ValueError(f"{self.base_id}: only a consistent twin has twin_facts")
        if len(set(self.twin_facts)) != len(self.twin_facts) or not set(self.twin_facts) <= set(facts):
            raise ValueError(f"{self.base_id}: twin_facts lists distinct facts of the skeleton")
        if self.arity_fact is not None and self.arity_fact in self.twin_facts:
            raise ValueError(f"{self.base_id}: the arity fact is recorded apart from the twin's facts")
        return self

    def planted_facts(self) -> tuple[str, ...]:
        """The facts whose sentences are planted, for spacing, spread and forbidden content: a planted variant's
        plant's, a consistent twin's ``twin_facts``, a trap variant's trap facts other than the arity fact."""
        if self.plant is not None:
            return self.plant.facts
        if self.variant == "consistent":
            return self.twin_facts
        return tuple(dict.fromkeys(f for t in self.traps for f in t.facts if f != self.arity_fact))

    def digest(self) -> str:
        """SHA-256 of the skeleton's canonical JSON."""
        text = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Base(_Frozen):
    """One base's variants, which quotas and splits always keep together (§8, §9)."""
    base_id: str
    consistent: Skeleton
    planted: tuple[Skeleton, ...]
    trap_only: tuple[Skeleton, ...] = ()

    @model_validator(mode="after")
    def _together(self) -> Base:
        variants = [self.consistent, *self.planted, *self.trap_only]
        if not self.planted:
            raise ValueError(f"{self.base_id}: a base has at least one planted variant")
        expected = ["consistent"] + ["planted"] * len(self.planted) + ["trap_only"] * len(self.trap_only)
        if [v.variant for v in variants] != expected:
            raise ValueError(f"{self.base_id}: each variant is in its own field")
        c = self.consistent
        shared = {(v.base_id, v.seed, v.genre, v.entities, _attributes(v, c), v.arity_fact, v.premise_status)
                  for v in variants}
        if shared != {(self.base_id, c.seed, c.genre, c.entities, c.attributes, c.arity_fact, c.premise_status)}:
            raise ValueError(f"{self.base_id}: all variants share the base's id, seed, genre, entities, attributes, "
                             "arity fact and premise status")
        return self


def _attributes(variant: Skeleton, twin: Skeleton) -> tuple[Attribute, ...]:
    """The variant's attributes, with an arity_control trap's attribute given the twin's arity."""
    if variant.variant != "trap_only" or not any(t.type == "arity_control" for t in variant.traps):
        return variant.attributes
    stated = {f.attribute for f in variant.facts if f.id == variant.arity_fact}
    theirs = {a.key: a.arity for a in twin.attributes}
    return tuple(Attribute(**{**a.model_dump(), "arity": theirs.get(a.key)}) if a.key in stated else a
                 for a in variant.attributes)
