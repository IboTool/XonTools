"""The check of each provider's terms on publishing its outputs as a dataset (XONFORGE_SPEC.md §4.3; the user's item 16
of 2026-09-25, xonforge/docs/decisions.md). Before the first export, each provider's terms are checked and the result
logged in xonforge/config/terms.yaml. An export's documents are its renderers' outputs, so nothing is exported with a
document whose renderer's provider has no check logged, or whose terms do not allow it. The reviewers' replies are
not exported.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

PATH = Path(__file__).resolve().parents[1] / "config" / "terms.yaml"


class TermsCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    checked: date | None = None
    allows: bool | None = None
    sources: tuple[str, ...] = ()
    notes: str | None = None

    @model_validator(mode="after")
    def _logged(self) -> TermsCheck:
        if (self.checked is None) != (self.allows is None) or (self.checked is not None and not self.sources):
            raise ValueError("a logged check has its date, its result and the pages read; an open one has none")
        return self


def load(path: str | Path = PATH) -> dict[str, TermsCheck]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {p: TermsCheck.model_validate(c or {}) for p, c in (raw.get("providers") or {}).items()}


def problems(providers: Iterable[str], checks: Mapping[str, TermsCheck]) -> list[str]:
    """Why documents rendered by these providers may not be exported; empty if they may."""
    out = []
    for p in sorted(set(providers)):
        c = checks.get(p)
        if c is None or c.checked is None:
            out.append(f"{p}'s terms on publishing its outputs as a dataset are not checked and logged yet "
                       "(xonforge/config/terms.yaml)")
        elif not c.allows:
            out.append(f"{p}'s terms, checked on {c.checked}, do not allow publishing its outputs as a dataset")
    return out
