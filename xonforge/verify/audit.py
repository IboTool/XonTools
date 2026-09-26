"""The fact audit (XONFORGE_SPEC.md §7.4b). A model other than the renderer reads the document and, for each fact,
says whether the text states it, implies it, leaves it absent, or contradicts it. A disagreement with the fact-to-span
map is a reason the document goes to the human queue. Tests use a fake client; this module sends nothing by itself.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from xon_common.caller import Caller
from xonforge import prompts
from xonforge.render.schema import Document
from xonforge.skeleton.schema import Skeleton

PROMPT = prompts.load("fact_audit.txt")
STATUSES = ("stated", "implied", "absent", "contradicted")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Finding(_Frozen):
    fact: str = Field(description="The fact's id, as listed.")
    status: Literal["stated", "implied", "absent", "contradicted"]


class FactAudit(_Frozen):
    findings: list[Finding]


def request(skeleton: Skeleton, document: Document) -> tuple[str, str]:
    """The auditor's system prompt and the document with the fact ids. No plant, variant or label."""
    lines = [document.text or "", "", "Facts:"]
    for fact in skeleton.facts:
        lines.append(f"{fact.id}")
    return PROMPT.text, "\n".join(lines)


def audit(skeleton: Skeleton, document: Document, caller: Caller, *, renderer: str, max_tokens: int) -> FactAudit:
    """The auditor's reply. ``renderer`` is the entry that rendered the document; the auditor is a different one."""
    if caller.adapter.entry.name == renderer:
        raise ValueError(f"the fact auditor is a model other than the renderer, and both are {renderer}")
    if document.text is None:
        raise ValueError("a fact audit reads a document that has text")
    system, user = request(skeleton, document)
    result = caller.complete(system=system, user=user, max_tokens=max_tokens, schema=FactAudit,
                             tag=f"audit:{document.doc_id}")
    found = result.parsed
    ids = [f.id for f in skeleton.facts]
    got = [f.fact for f in found.findings]
    if sorted(got) != sorted(ids) or len(got) != len(set(got)):
        raise ValueError(f"the fact audit must judge each listed fact once, and it judged {', '.join(got) or 'none'}")
    return found


def disagreements(skeleton: Skeleton, document: Document, found: FactAudit) -> list[str]:
    """Where the auditor and the fact-to-span map disagree. A span or an inferred entry means the map says the fact
    is in the document; stated or implied agrees with that, and absent or contradicted does not."""
    present = set(document.spans) | set(document.inferred)
    by_id = {f.fact: f.status for f in found.findings}
    out = []
    for fact in skeleton.facts:
        status = by_id[fact.id]
        if fact.id in present and status in ("absent", "contradicted"):
            out.append(f"fact {fact.id} is in the fact-to-span map and the audit says it is {status}")
        if fact.id not in present and status == "stated":
            out.append(f"fact {fact.id} is not in the fact-to-span map and the audit says it is stated")
    return out
