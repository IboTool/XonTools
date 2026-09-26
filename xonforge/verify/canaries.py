"""Scan canaries (XONFORGE_SPEC.md §7.2, §13): each scan must be shown to catch a known defect before its clean
results are trusted. A scan is trusted when at least one canary is registered for it and it catches every one; with
none registered, its clean results are recorded as untrusted, and its hits still count.

Canaries are JSON files in xonforge/canaries/scans/, each holding one canary or a list of them: ``id``, ``scan``,
``text`` (a short document with the defect), ``people`` (every person's name), and, for the scans that need them,
``attribute`` and ``plant_people`` (the planted ones) and ``planted`` (the sentences the scan leaves out), with
``defect`` saying what the scan must catch, ``pattern`` the scan pattern it exercises (scans.patterns) and ``source``
where it comes from. For the user's item 5 of 2026-09-25 (xonforge/docs/decisions.md): synthetic canaries for each
scan and pattern, and the real defects the L1 scans found, which may be used since canaries calibrate and are never
evaluation data; no canary comes from, or goes into, a sealed or judged split.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from . import scans

FOLDER = Path(__file__).resolve().parents[1] / "canaries" / "scans"


class ScanCanary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    scan: Literal["superlative_collisions", "order_cycles", "same_attribute"]
    text: str
    people: tuple[str, ...]
    attribute: str | None = None
    plant_people: tuple[str, ...] = ()
    planted: tuple[str, ...] = ()
    defect: str
    pattern: str | None = None
    source: str = "synthetic"


class ScanTrust(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    scan: str
    trusted: bool
    caught: tuple[str, ...] = ()
    missed: tuple[str, ...] = ()


def load(folder: str | Path | None = None) -> list[ScanCanary]:
    folder = Path(folder) if folder is not None else FOLDER
    canaries = []
    for p in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        body = json.loads(p.read_text(encoding="utf-8"))
        canaries += [ScanCanary.model_validate(c) for c in (body if isinstance(body, list) else [body])]
    ids = [c.id for c in canaries]
    if len(set(ids)) != len(ids):
        raise ValueError("each scan canary has an id of its own")
    return canaries


def caught(canary: ScanCanary) -> bool:
    return bool(scans.run(canary.scan, canary.text, canary.people, attribute=canary.attribute,
                          plant_people=canary.plant_people, planted=canary.planted))


def trust(canaries: list[ScanCanary]) -> dict[str, ScanTrust]:
    """Per scan, whether its clean results are trusted, and which of its canaries it caught and missed."""
    out = {}
    for name in scans.SCANS:
        mine = [c for c in canaries if c.scan == name]
        hit = tuple(c.id for c in mine if caught(c))
        missed = tuple(c.id for c in mine if c.id not in hit)
        out[name] = ScanTrust(scan=name, trusted=bool(mine) and not missed, caught=hit, missed=missed)
    return out
