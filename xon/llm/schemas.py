"""Structured-output schemas of the consistency engine (XON_A1_CONSISTENCY.md §3.1).

Every instruction to the model lives in ``prompts.py``, so the schemas carry no descriptions. The API does not
guarantee the casing of enum values, so enum fields are lower-cased before validation, and the ids of a per-document
schema (``document_schema``) are matched to the document's ids case-insensitively. Confidences are clipped to
[0, 1] where they are used: the API cannot enforce numeric bounds. All models are frozen: extracted claims,
relations and evidence are never rewritten (invariant I3).
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, create_model, field_validator


def _lower(value):
    return value.strip().lower() if isinstance(value, str) else value


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Claim(_Frozen):
    id: int
    text: str                                        # atomic, self-contained
    span: str                                        # verbatim source excerpt
    kind: Literal["asserted", "premise", "quoted"]   # premise = given/assumed; quoted = attributed to someone else

    @field_validator("kind", mode="before")
    @classmethod
    def lower_kind(cls, value):
        return _lower(value)


class ClaimList(_Frozen):
    claims: list[Claim]


class Relation(_Frozen):
    # The API writes an object's properties in schema order, required ones first: every field stays required and the
    # rationale stays ahead of relation and confidence, so the model reasons before it commits to a label.
    a: int
    b: int
    rationale: str                                   # one sentence
    relation: Literal["supports", "contradicts", "unrelated"]
    confidence: float                                # 0..1

    @field_validator("relation", mode="before")
    @classmethod
    def lower_relation(cls, value):
        return _lower(value)


class RelationList(_Frozen):
    relations: list[Relation]


class RelationV22(_Frozen):
    """Rev. 2.2 (XON_A1_REV2_2_PRECISION.md §3): one pair per call, with "tension" for pairs that can both be true
    but sit badly together. Tension makes no edge. Field order as in rev. 2.1: rationale before relation and
    confidence."""
    a: int
    b: int
    rationale: str                                   # one or two sentences, written first
    relation: Literal["supports", "contradicts", "tension", "unrelated"]
    confidence: float                                # 0..1

    @field_validator("relation", mode="before")
    @classmethod
    def lower_relation(cls, value):
        return _lower(value)


class RelationListV22(_Frozen):
    """The relations of one document under rev. 2.2 (never sent as a schema: each call returns one RelationV22)."""
    relations: list[RelationV22]


class Pair(_Frozen):
    """One pair of claim ids. The spec's tuple[int, int] becomes an object: the API cannot constrain tuples."""
    a: int
    b: int


class PairList(_Frozen):
    pairs: list[Pair]


class Entity(_Frozen):
    id: str                                          # canonical within the document, e.g. "alice"
    mentions: list[str]                              # surface forms ("Alice", "she", "the older sister")


class Attribute(_Frozen):
    key: str                                         # canonical within the document, e.g. "age", "team"
    arity: Literal["binary", "multi", "unknown"]     # binary only if the text establishes exactly two values
    arity_span: str | None                           # the sentence establishing arity, if any

    @field_validator("arity", mode="before")
    @classmethod
    def lower_arity(cls, value):
        return _lower(value)


class EntityRelation(_Frozen):
    claim_id: int                                    # the claim that states this relation
    attribute: str                                   # Attribute.key
    kind: Literal["same", "different", "greater"]    # greater = strict order: a > b on the attribute
    a: str                                           # Entity.id
    b: str                                           # Entity.id
    confidence: float                                # 0..1

    @field_validator("kind", mode="before")
    @classmethod
    def lower_kind(cls, value):
        return _lower(value)


class EntityGraphSpec(_Frozen):
    entities: list[Entity]
    attributes: list[Attribute]
    relations: list[EntityRelation]


# ------------------------------------------------------------------------------------------ rev. 2.2 entity statements
# XON_A1_REV2_2_PRECISION.md §5: the model reports what each claim states, with its comparative verbatim and its own
# subject and object; the engine derives the direction (entity_consistency.build_entity_graph_v22).
class AttributeV22(_Frozen):
    key: str
    arity: Literal["binary", "multi", "unknown"]
    arity_span: str | None
    order_kind: Literal["sequence", "magnitude", "other"] | None   # sequence: greater = later; magnitude: more
    other_greater_means: str | None                                # what greater means when order_kind is "other"

    @field_validator("arity", "order_kind", mode="before")
    @classmethod
    def lower_enums(cls, value):
        return _lower(value)


class SameDifferent(_Frozen):
    """EntityRelation's same and different, unchanged; the schema admits no other kind."""
    claim_id: int
    attribute: str
    kind: Literal["same", "different"]
    a: str
    b: str
    confidence: float

    @field_validator("kind", mode="before")
    @classmethod
    def lower_kind(cls, value):
        return _lower(value)


class OrderStatement(_Frozen):
    claim_id: int
    attribute: str
    subject: str                                     # Entity.id of the claim's grammatical subject
    comparative: str                                 # verbatim from the claim: "after", "younger"
    object: str                                      # Entity.id of the claim's grammatical object
    confidence: float


class ExtremeStatement(_Frozen):
    claim_id: int
    attribute: str
    entity: str
    comparative: str                                 # verbatim: "first", "last", "oldest"
    confidence: float


class ComparativeSense(_Frozen):
    attribute: str
    comparative: str
    greater_side: Literal["subject", "object", "max", "min"]

    @field_validator("greater_side", mode="before")
    @classmethod
    def lower_side(cls, value):
        return _lower(value)


# Development iteration 0's single entity call (CHANGELOG), kept to read its saved results. Its schema's class names
# and descriptions (pydantic sends a docstring as one) are part of its requests, so they stay as they are.
class EntityGraphSpecV22(_Frozen):
    entities: list[Entity]
    attributes: list[AttributeV22]
    same_different: list[SameDifferent]
    orders: list[OrderStatement]
    extremes: list[ExtremeStatement]
    senses: list[ComparativeSense]
    unsupported_order_claims: list[int]              # claims stating an order only in a negated or hedged comparative


# ------------------------------------------------------------------------------------------ rev. 2.2 entity steps
# The revised §5, from development iteration 1: an inventory call, a relations call whose schema accepts only the
# inventory's ids and the document's claim ids (document_schema), and at most one coverage call. The classes sent as
# schemas have no docstrings: pydantic would send one as the schema's description.
class ExtremeStatementV22(_Frozen):     # an extreme statement with its restriction (§5.3)
    claim_id: int
    attribute: str
    entity: str
    comparative: str                                 # verbatim: "first", "last", "oldest"
    restriction: str | None                          # verbatim: "of the judges", "on the team"; None if unrestricted
    confidence: float


class InventoryV22(_Frozen):
    entities: list[Entity]
    attributes: list[AttributeV22]


class EntityRelationsV22(_Frozen):
    same_different: list[SameDifferent]
    orders: list[OrderStatement]
    extremes: list[ExtremeStatementV22]
    senses: list[ComparativeSense]
    unsupported_order_claims: list[int]              # claims stating an order only in a negated or hedged comparative


class NoStatement(_Frozen):             # the coverage call's answer for a listed claim that states nothing (§5.6)
    claim_id: int
    reason: str                                      # one sentence


class EntityCoverageV22(EntityRelationsV22):
    none: list[NoStatement]


class EntityStepsV22(_Frozen):
    """What the entity calls of one document returned, and the coverage net's record (§5.2, §5.6). Never sent."""
    inventory: InventoryV22
    relations: EntityRelationsV22
    coverage: EntityCoverageV22 | None               # the follow-up's answer; None if no claim was uncovered
    lexicon_matched: list[int]                       # claims whose text holds a word or phrase of the lexicon
    uncovered: list[int]                             # of those, the claims left without a statement: the follow-up's
    schema_fallback: list[str]                       # the calls whose per-document schema the API would not compile
    skipped: str | None = None                       # why the relations and coverage calls were not made


def _one_of(values, plain: type):
    if values is None:
        return plain
    values = tuple(dict.fromkeys(values))
    lower = {str(v).lower(): v for v in values}

    def match(value):
        return lower.get(value.strip().lower(), value) if isinstance(value, str) else value
    return Annotated[Literal[values], BeforeValidator(match)]


def _narrowed(cls: type[BaseModel], **types) -> type[BaseModel]:
    return create_model(cls.__name__, __base__=cls, __doc__=None,
                        **{name: (t, ...) for name, t in types.items()})


def document_schema(base: type[EntityRelationsV22], entity_ids=None, attribute_keys=None,
                    claim_ids=None) -> type[BaseModel]:
    """``base`` (EntityRelationsV22, or EntityCoverageV22 for the coverage call) with every entity field accepting
    only ``entity_ids``, every attribute field only ``attribute_keys`` and every claim field only ``claim_ids``
    (§5.3), each list non-empty. With no ids, the same schema with plain strings and integers: the fallback, whose
    ids are checked after the call. Its instances are instances of ``base``."""
    entity, attribute, claim = _one_of(entity_ids, str), _one_of(attribute_keys, str), _one_of(claim_ids, int)
    types = {"same_different": list[_narrowed(SameDifferent, claim_id=claim, attribute=attribute, a=entity,
                                              b=entity)],
             "orders": list[_narrowed(OrderStatement, claim_id=claim, attribute=attribute, subject=entity,
                                      object=entity)],
             "extremes": list[_narrowed(ExtremeStatementV22, claim_id=claim, attribute=attribute, entity=entity)],
             "senses": list[_narrowed(ComparativeSense, attribute=attribute)],
             "unsupported_order_claims": list[claim]}
    if issubclass(base, EntityCoverageV22):
        types["none"] = list[_narrowed(NoStatement, claim_id=claim)]
    return _narrowed(base, **types)


class LeakFlag(_Frozen):
    """A1 corpus generator's QA pass (§5 rev. 2.1 tighten re-specification): one sentence outside the planted ones
    that reveals or implies a planted fact, by paraphrase or otherwise."""
    sentence: str                                    # verbatim, the flagged sentence
    reason: str                                      # which planted fact it leaks, and why, in one sentence


class LeakScan(_Frozen):
    flags: list[LeakFlag]


class Contradiction(_Frozen):
    """LLM-direct baseline (§4.8): one contradiction, citing the sentences of the text that form it."""
    sentences: list[str]
    explanation: str


class ContradictionList(_Frozen):
    contradictions: list[Contradiction]
