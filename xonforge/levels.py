"""Difficulty levels (the user's item 4 of 2026-09-25, xonforge/docs/decisions.md): bundles of §5.4's knobs, whose
actual values each document records.

- Level 1 (L1-like): 150-300 words; cycle 3-4; stated; 0-1 distractors per planted fact, on other attributes only; low
  lexical variety; 3-5 entities, 2-3 attributes; any plant distance.
- Level 2: 400-800 words; cycle 3-5; stated or paraphrased; 1-2 distractors, same-attribute distractors on; medium
  variety; 5-8 entities, 3-5 attributes; the planted sentences spread over at least half the document.
- Level 3: 1,000-3,000 words; cycle 4-6; paraphrased; 2-3 distractors, same-attribute distractors on; high variety;
  8-12 entities, 5-8 attributes; the first and last planted sentences in the first and last quarters.

A draw (the implementing agent's method): the skeleton's knobs uniformly among the level's combinations that the
generator can build for the plant type (generators.feasible), the target length uniformly among the level's multiples
of 10 words, and the explicitness uniformly among the level's; all from a seed. direct_negation's plant is two facts
about one entity, so the cycle length does not apply to it, and its knobs take the level's lowest.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass

from .render.schema import RenderRules
from .skeleton.generators import Knobs, _spec, feasible


@dataclass(frozen=True)
class Level:
    words: tuple[int, int]
    cycle_length: tuple[int, int]
    explicitness: tuple[str, ...]
    distractors: tuple[int, int]
    same_attribute_distractors: bool
    lexical_variety: str
    entities: tuple[int, int]
    attributes: tuple[int, int]
    spread: str


LEVELS = {
    1: Level((150, 300), (3, 4), ("stated",), (0, 1), False, "low", (3, 5), (2, 3), "any"),
    2: Level((400, 800), (3, 5), ("stated", "paraphrased"), (1, 2), True, "medium", (5, 8), (3, 5), "half"),
    3: Level((1000, 3000), (4, 6), ("paraphrased",), (2, 3), True, "high", (8, 12), (5, 8), "quarters"),
}


def _span(bounds: tuple[int, int]) -> range:
    return range(bounds[0], bounds[1] + 1)


def combinations(level: int, plant_type: str) -> list[Knobs]:
    """The level's skeleton knobs that the generator can build for the plant type."""
    if level not in LEVELS:
        raise ValueError(f"the difficulty levels are {', '.join(map(str, LEVELS))}, not {level!r}")
    try:
        size = _spec(plant_type)[1]
    except ValueError:
        raise ValueError(f"not a plant type: {plant_type!r}") from None
    lv = LEVELS[level]
    cycles = _span(lv.cycle_length) if size is None else (lv.cycle_length[0],)
    out = []
    for k, n, a, d in itertools.product(cycles, _span(lv.entities), _span(lv.attributes), _span(lv.distractors)):
        try:
            knobs = Knobs(cycle_length=k, entities=n, attributes=a, distractors=d,
                          same_attribute_distractors=lv.same_attribute_distractors)
        except ValueError:
            continue
        if feasible(plant_type, knobs):
            out.append(knobs)
    return out


def draw(level: int, plant_type: str, seed: int) -> tuple[Knobs, RenderRules]:
    """The skeleton knobs and the rendering rules of one document of the level, the same for the same arguments."""
    options = combinations(level, plant_type)
    if not options:
        raise ValueError(f"no combination of level {level}'s knobs can build a {plant_type} base")
    lv = LEVELS[level]
    rng = random.Random(f"xonforge:level:{level}:{plant_type}:{seed}")
    knobs = rng.choice(options)
    rules = RenderRules(words=rng.randrange(lv.words[0], lv.words[1] + 1, 10),
                        explicitness=rng.choice(lv.explicitness), lexical_variety=lv.lexical_variety,
                        spread=lv.spread, level=level)
    return knobs, rules
