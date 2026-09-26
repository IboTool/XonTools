"""Which split each base goes to (XONFORGE_SPEC.md §9; the user's item 15 of 2026-09-25, xonforge/docs/decisions.md).

Bases, each with all its variants, are stratified by plant type × difficulty level. Within each stratum they are
sorted by id, shuffled with the seed, and divided by the proportions (50 / 15 / 35 for development, calibration and
test by default, configurable) with largest-remainder rounding, ties broken by the same seed, which is logged before
generation (the decision log's split seed, decisions.py). A judged plant (causal, commonsense, implicature) goes only
to the judged split, and only in a corpus of record. A pipeline test's bases go only to development and calibration,
in proportions its run gives (xonforge/modes.py).
"""
from __future__ import annotations

import random
from fractions import Fraction
from typing import Mapping, Sequence

from xonforge import modes
from xonforge.skeleton.schema import Base
from xonforge.solver.solver import JUDGED

from .export import OUT_OF_BOUNDS, SPLITS
from .quotas import largest_remainder

PROPORTIONS = {"development": Fraction(50, 100), "calibration": Fraction(15, 100), "test": Fraction(35, 100)}


def stratum(base: Base) -> tuple[str, int | None]:
    """A base's plant type and difficulty level."""
    return base.planted[0].plant.type, base.consistent.difficulty.get("level")


def assign(strata: Mapping[str, tuple], seed: int, *, mode: str,
           proportions: Mapping[str, Fraction] | None = None) -> dict[str, str]:
    """Each base's split. ``strata``: each base id's stratum (``stratum``)."""
    modes.check(mode)
    if proportions is None:
        if mode == modes.PIPELINE_TEST:
            raise ValueError("a pipeline test's run gives its proportions, for development and calibration only")
        proportions = PROPORTIONS
    unknown = sorted(set(proportions) - set(SPLITS))
    if unknown:
        raise ValueError(f"the splits are {', '.join(SPLITS)}, not {', '.join(unknown)}")
    barred = [s for s in OUT_OF_BOUNDS[mode] if proportions.get(s)]
    if barred:
        raise ValueError(f"a pipeline-test document never enters a sealed or judged split, and a proportion is given "
                         f"for {', '.join(barred)}")
    out: dict[str, str] = {}
    for key in sorted({s for s in strata.values()}, key=repr):
        ids = sorted(b for b, s in strata.items() if s == key)
        random.Random(f"xonforge:splits:{seed}:{key!r}").shuffle(ids)
        counts = largest_remainder(len(ids), dict(proportions), seed)
        start = 0
        for split in SPLITS:
            for b in ids[start:start + counts.get(split, 0)]:
                out[b] = split
            start += counts.get(split, 0)
    return out


def assign_bases(bases: Sequence[Base], seed: int, *, mode: str,
                 proportions: Mapping[str, Fraction] | None = None) -> dict[str, str]:
    """Each base's split. A judged plant is the judged split in a corpus of record, and is refused in a pipeline test."""
    judged = [b.base_id for b in bases if b.planted[0].plant.type in JUDGED]
    if judged and mode != modes.RECORD:
        raise ValueError("a judged plant goes only to the judged split, and a pipeline test has none")
    ordinary = [b for b in bases if b.base_id not in set(judged)]
    out = assign({b.base_id: stratum(b) for b in ordinary}, seed, mode=mode, proportions=proportions)
    for base_id in judged:
        out[base_id] = "judged"
    return out
