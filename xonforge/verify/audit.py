"""The fact audit (XONFORGE_SPEC.md §7.4b). Optional, on by default for a corpus run.

A model other than the renderer reads the text and the skeleton's fact list and marks each fact stated, implied,
absent or contradicted. This checks rendering fidelity, so it may see the facts. A mark that disagrees with the
fact→span map is a flag for the human queue. The 20-document sample does not call it.
"""
from __future__ import annotations

from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field

from xonforge.render.phrasing import statement
from xonforge.skeleton.schema import Skeleton

STATUSES = ("stated", "implied", "absent", "contradicted")
SYSTEM = ("Mark each fact as stated, implied, absent or contradicted in the document. "
          "Use only the text and the fact list. Do not look for contradictions beyond what the list asks.")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FactMark(_Frozen):
    fact: str = Field(description="The fact's id.")
    status: str = Field(description="stated, implied, absent or contradicted.")


class AuditReply(_Frozen):
    facts: list[FactMark]


def require_other_model(renderer: str, auditor: str) -> None:
    """The auditor is a different model from the renderer (§7.4b)."""
    if not renderer or not auditor or renderer == auditor:
        raise ValueError("the fact audit uses a model different from the renderer (XONFORGE_SPEC.md §7.4b)")


def prompt(skeleton: Skeleton, text: str) -> str:
    """The text and every fact, by id, in the renderer's plain wording."""
    lines = [f"{f.id}: {statement(f, skeleton)}" for f in skeleton.facts]
    return f"Document:\n{text}\n\nFacts:\n" + "\n".join(lines)


def disagreements(skeleton: Skeleton, spans: Mapping[str, str], marks: Mapping[str, str]) -> list[str]:
    """Where the audit disagrees with the fact→span map. A span means the fact is in the text, so stated or implied
    agrees and absent or contradicted does not. No span agrees only with absent."""
    ids = [f.id for f in skeleton.facts]
    problems = []
    unknown = sorted(set(marks) - set(ids))
    if unknown:
        problems.append(f"the audit marks {', '.join(unknown)}, which "
                        + ("is not a fact" if len(unknown) == 1 else "are not facts"))
    missing = [i for i in ids if i not in marks]
    if missing:
        problems.append(f"the audit did not mark {', '.join(missing)}")
    for fid in ids:
        if fid not in marks:
            continue
        status = marks[fid]
        if status not in STATUSES:
            problems.append(f"the audit marks fact {fid} as {status!r}, not stated, implied, absent or contradicted")
            continue
        has_span = bool(str(spans.get(fid, "")).strip())
        if has_span and status in ("absent", "contradicted"):
            problems.append(f"fact {fid} has a span and the audit marks it {status}")
        elif not has_span and status != "absent":
            problems.append(f"fact {fid} has no span and the audit marks it {status}")
    return problems


def audit(caller, skeleton: Skeleton, text: str, spans: Mapping[str, str], *, renderer_model: str,
          auditor_model: str, max_tokens: int = 4096):
    """Run the audit and return the disagreements. ``caller`` is the auditor's, already not the renderer's model."""
    require_other_model(renderer_model, auditor_model)
    reply = caller.complete(system=SYSTEM, user=prompt(skeleton, text), max_tokens=max_tokens, schema=AuditReply,
                            tag="xonforge.audit")
    marks = {item.fact: item.status for item in reply.parsed.facts}
    return disagreements(skeleton, spans, marks)
