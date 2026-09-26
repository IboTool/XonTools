"""What a renderer returns, the rules it renders by, and the document record XonForge keeps (XONFORGE_SPEC.md §5.4,
§6, §11).

For the user's decisions of 2026-09-25 (xonforge/docs/decisions.md): the minimum spacing is a constant of one sentence
(item 1); the rules record the difficulty level and its spread of the planted sentences (item 4); and an inferred
fact's map entry is defined (item 3), though v0 renders no inferred fact, "inferred" starting in v1.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EXPLICITNESS = ("stated", "paraphrased")         # §5.4's "inferred" starts in v1 (the user's item 3)
LEXICAL_VARIETY = ("low", "medium", "high")
MIN_SPACING = 1                                  # sentences not planted between two planted ones (the user's item 1)
SPREADS = ("any", "half", "quarters")            # the plant distance at levels 1, 2 and 3 (the user's item 4)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SpanEntry(_Frozen):
    fact: str = Field(description="The fact's id, as listed.")
    span: str = Field(description="The whole sentence of the document that states the fact, copied character for "
                                  "character.")


class Rendering(_Frozen):
    """The renderer's reply: the document, and for every fact the sentence that states it."""
    text: str = Field(description="The document.")
    spans: list[SpanEntry] = Field(description="One entry per listed fact.")

    def span_map(self) -> dict[str, str]:
        return {s.fact: s.span for s in self.spans}


class Revision(_Frozen):
    fact: str = Field(description="The fact's id, as listed.")
    sentence: str = Field(description="The new sentence, which states the fact.")


class Revisions(_Frozen):
    """The renderer's reply when it re-renders sentences of a document (the user's item 2): one per listed fact."""
    sentences: list[Revision] = Field(description="One entry per listed fact.")


class InferredSpan(_Frozen):
    """An inferred fact's map entry (the user's item 3): the verbatim spans the fact follows from, and the solver's
    rule that derives it, e.g. "3:00 + 2 h = 5:00". Defined for v1's arithmetic, time and location plant types; v0
    renders no inferred fact."""
    mode: Literal["inferred"]
    support_spans: tuple[str, ...] = Field(min_length=1)
    derivation: str = Field(min_length=1)

    def missing(self, text: str) -> list[str]:
        """The support spans that do not appear verbatim in the text."""
        return [s for s in self.support_spans if s not in text]


class ReviewProblem(_Frozen):
    """A problem a human reviewer found, for a targeted re-rendering (§6's ``review_problems``)."""
    problem: str
    fact: str | None = None          # the fact it concerns, if any
    sentence: str | None = None      # the sentence it concerns, if any


class RenderRules(_Frozen):
    """What a document is rendered to, from its difficulty knobs and the constants (§5.4)."""
    words: int                                            # the target length, 150 to 3,000 words
    explicitness: Literal["stated", "paraphrased"]
    lexical_variety: Literal["low", "medium", "high"]
    min_spacing: int = MIN_SPACING                        # sentences not planted between any two planted sentences
    spread: Literal["any", "half", "quarters"] = "any"    # how far apart the planted sentences must be (item 4)
    level: int | None = None                              # the difficulty level the rules were drawn for, if any
    retry_cap: int = 5

    @model_validator(mode="after")
    def _ranges(self) -> RenderRules:
        if not 150 <= self.words <= 3000:
            raise ValueError(f"a document is 150 to 3,000 words long (XONFORGE_SPEC.md §5.4), not {self.words}")
        if self.min_spacing < MIN_SPACING:
            raise ValueError(f"the minimum spacing is at least {MIN_SPACING} sentence, the user's constant")
        if self.level is not None and self.level not in (1, 2, 3):
            raise ValueError(f"the difficulty levels are 1, 2 and 3, not {self.level}")
        if self.retry_cap < 1:
            raise ValueError("the retry cap allows at least one rendering")
        return self


class Renderer(_Frozen):
    """Which model rendered a document, and how (§11's provenance)."""
    entry: str                       # the registry entry's name
    provider: str
    model: str
    params: dict = {}
    thinking: bool = False
    prompt_version: str
    prompt_sha256: str | None = None     # the SHA-256 of the prompt's file (xonforge/prompts/versions.json)


class Attempt(_Frozen):
    number: int
    request: str | None = None       # the first 16 hexadecimal digits of the request's cache key
    source: str | None = None        # "api" or "cache"
    failed: tuple[str, ...] = ()     # the checks that failed, as quoted back to the next attempt
    error: str | None = None         # a provider error that counted as a failed attempt


class ScanRecord(_Frozen):
    """What one deterministic scan (§7.2) found on a document."""
    scan: str
    result: Literal["clean", "hits", "not_applicable", "not_run"]
    trusted: bool                    # the scan caught every registered canary, and at least one is registered
    uncovered: tuple[str, ...] = ()  # the skeleton's attributes the scan has no pattern for


class Document(_Frozen):
    """One rendered variant. Kept outside the repository until the split assigns it (rules.md, XonForge)."""
    doc_id: str
    base_id: str
    variant: Literal["consistent", "planted", "trap_only"]
    skeleton_digest: str
    mode: Literal["record", "pipeline_test"]      # the mode of the run that made it (xonforge/modes.py)
    renderer: Renderer
    rules: RenderRules
    status: Literal["rendered", "failed"]
    text: str | None = None          # the last readable reply's document, if any reply was readable
    spans: dict[str, str] = {}
    # Inferred facts (§5.4, item 3): arithmetic, time and location conclusions, keyed by fact id. v0 leaves this empty.
    inferred: dict[str, InferredSpan] = {}
    attempts: tuple[Attempt, ...]
    flags: tuple[str, ...] = ()
    review_problems: tuple[ReviewProblem, ...] = ()
    measured: dict[str, int | None] = {}   # §5.4's measurements after rendering (xonforge/verify/structural.py)
    scans: tuple[ScanRecord, ...] = ()
    derived_from: str | None = None  # the document whose text this one keeps, its changed sentences re-rendered
    changed: tuple[str, ...] = ()    # the facts whose sentences were re-rendered
