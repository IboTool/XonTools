"""The reviewers' replies, as structured output (the user's item 7 of 2026-09-25, xonforge/docs/decisions.md): the
conflicts found, each with its statements quoted verbatim and a one-sentence explanation, and, for the
relational-inventory prompt, the inventory, kept for audit."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Conflict(_Frozen):
    statements: list[str] = Field(description="Each statement quoted verbatim.")
    explanation: str = Field(description="One sentence.")


class ContradictionReply(_Frozen):
    conflicts: list[Conflict]


class InventoryGroup(_Frozen):
    attribute: str = Field(description="The attribute the statements relate people or things on.")
    statements: list[str] = Field(description="Each statement quoted verbatim.")


class InventoryReply(_Frozen):
    inventory: list[InventoryGroup]
    conflicts: list[Conflict]
