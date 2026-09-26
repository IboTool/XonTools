"""Quotas (XONFORGE_SPEC.md §8; the user's items 12 to 14 of 2026-09-25, xonforge/docs/decisions.md).

The target is divided over a full cross of plant type × difficulty level × renderer provider, balanced by default or
weighted per dimension; genre and trap type are separate per-dimension quotas, balanced across the cells. Every
division uses largest-remainder rounding, so that the parts sum exactly to the whole, ties broken by a seed that is
logged before generation (the decision log's quota seed, decisions.py). A cell is unfillable when its attempts reach
max(10, 3 × its quota) without filling it: it is reported, the other cells keep filling, and nothing is redistributed;
the user decides.

Genres and traps are balanced across the cells by dealing them over the plan's units, cell by cell, in an order that
interleaves each value in proportion to its quota, so that each cell's mix is close to the whole's. A trap goes only
to units whose plant type admits it (binary parity's arity control); the others have none. What a unit counts,
a document or a base, is the user's to say (still open): the plan counts units.
"""
from __future__ import annotations

import itertools
import math
import random
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from typing import Hashable, Mapping, Sequence

from xonforge.skeleton.generators import TRAP_PLANTS

NO_TRAP = "none"


def largest_remainder(total: int, weights: Mapping[Hashable, int | Fraction], seed: int) -> dict:
    """``total`` divided in proportion to ``weights``: each part the floor of its exact share, and the remaining units
    to the largest remainders, ties in an order drawn with the seed."""
    if total < 0 or not weights or any(w < 0 for w in weights.values()) or not sum(weights.values()):
        raise ValueError("a total of 0 or more is divided by weights of 0 or more, at least one of them positive")
    whole = sum(Fraction(w) for w in weights.values())
    exact = {k: Fraction(total) * Fraction(w) / whole for k, w in weights.items()}
    parts = {k: math.floor(v) for k, v in exact.items()}
    order = sorted(weights, key=repr)
    random.Random(f"xonforge:quotas:{seed}").shuffle(order)
    for k in sorted(order, key=lambda k: exact[k] - parts[k], reverse=True)[:total - sum(parts.values())]:
        parts[k] += 1
    return {k: parts[k] for k in weights}


def _weights(values: Sequence[Hashable] | Mapping[Hashable, int | Fraction], what: str) -> dict:
    out = dict(values) if isinstance(values, Mapping) else {v: 1 for v in values}
    if not out:
        raise ValueError(f"at least one {what} is given")
    return out


def _dealt(counts: Mapping[str, int], seed: int, salt: str) -> list[str]:
    """Each value as often as its count, interleaved in proportion to it: value v's i-th copy at (i + 1/2) / count."""
    order = sorted(counts)
    random.Random(f"xonforge:{salt}:{seed}").shuffle(order)
    rank = {v: n for n, v in enumerate(order)}
    slots = [(Fraction(2 * i + 1, 2 * n), rank[v], v) for v, n in counts.items() for i in range(n)]
    return [v for _, _, v in sorted(slots)]


@dataclass(frozen=True)
class Unit:
    plant_type: str
    level: int
    provider: str
    genre: str
    trap: str = NO_TRAP

    @property
    def cell(self) -> tuple[str, int, str]:
        return self.plant_type, self.level, self.provider


def plan(target: int, *, plant_types, levels, providers, genres, traps=None, seed: int) -> list[Unit]:
    """The target's units, cell by cell. Each dimension is a sequence of its values (balanced) or a mapping of each
    value to its weight; ``traps``: the trap types, with ``"none"``, over the units that may have one."""
    pt, lv, pr = _weights(plant_types, "plant type"), _weights(levels, "level"), _weights(providers, "provider")
    cells = {c: pt[c[0]] * lv[c[1]] * pr[c[2]] for c in itertools.product(pt, lv, pr)}
    quotas = largest_remainder(target, cells, seed)
    units = [c for c in sorted(cells, key=repr) for _ in range(quotas[c])]
    genre = _dealt(largest_remainder(target, _weights(genres, "genre"), seed), seed, "genres")
    out = [Unit(*c, genre=g) for c, g in zip(units, genre)]
    if traps is not None:
        tw = _weights(traps, "trap")
        admits = {t: TRAP_PLANTS.get(t, ()) for t in tw if t != NO_TRAP}
        eligible = [n for n, u in enumerate(out) if any(u.plant_type in plants for plants in admits.values())]
        if eligible:
            dealt = _dealt(largest_remainder(len(eligible), tw, seed), seed, "traps")
            for n, t in zip(eligible, dealt):
                if t == NO_TRAP or out[n].plant_type in admits[t]:
                    out[n] = Unit(*out[n].cell, genre=out[n].genre, trap=t)
    return out


def quotas(units: Sequence[Unit]) -> dict[tuple[str, int, str], int]:
    return dict(Counter(u.cell for u in units))


def give_up_after(quota: int) -> int:
    """The attempts after which a cell that is not filled is unfillable."""
    return max(10, 3 * quota)


class Progress:
    """Attempts and fills per cell, and the cells that are unfillable."""

    def __init__(self, cell_quotas: Mapping[tuple, int]):
        self.quotas = dict(cell_quotas)
        self.attempts: Counter = Counter()
        self.filled: Counter = Counter()

    def record(self, cell: tuple, filled: bool) -> None:
        if cell not in self.quotas:
            raise ValueError(f"no quota for the cell {cell}")
        if self.done(cell):
            raise ValueError(f"the cell {cell} is filled or unfillable, and takes no more attempts")
        self.attempts[cell] += 1
        self.filled[cell] += bool(filled)

    def unfillable(self) -> list[tuple]:
        return [c for c, q in self.quotas.items()
                if self.filled[c] < q and self.attempts[c] >= give_up_after(q)]

    def done(self, cell: tuple) -> bool:
        return self.filled[cell] >= self.quotas[cell] or cell in self.unfillable()

    def open(self) -> list[tuple]:
        return [c for c in self.quotas if not self.done(c)]

    def report(self) -> list[str]:
        return [f"the cell {' × '.join(map(str, c))} is unfillable: {self.filled[c]} of its {self.quotas[c]} filled "
                f"after {self.attempts[c]} attempts; nothing is redistributed, the user decides"
                for c in self.unfillable()]
