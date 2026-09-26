"""Which renderer writes a base (XONFORGE_SPEC.md §6, §8): rotated across the configured renderers, balanced by
default. All variants of a base get the same renderer, so a planted variant and its twin differ in their facts and not
in who wrote them. The renderers are registry entries the user chooses (``render.renderers`` in defaults.yaml); none
is chosen yet. Mixes other than balanced come with the quota scheduler (§8)."""
from __future__ import annotations

from typing import Mapping, Sequence


class Rotation:
    def __init__(self, renderers: Sequence[str], done: Mapping[str, int] | None = None):
        """``done``: bases already assigned per renderer, when a run resumes."""
        if not renderers:
            raise ValueError("no renderer is configured; the user chooses them (render.renderers in defaults.yaml)")
        if len(set(renderers)) != len(renderers):
            raise ValueError("each renderer is listed once")
        unknown = sorted(set(done or {}) - set(renderers))
        if unknown:
            raise ValueError(f"bases were assigned to renderers that are not configured: {', '.join(unknown)}")
        self.counts = {r: int((done or {}).get(r, 0)) for r in renderers}

    def next(self) -> str:
        """The renderer with the fewest bases so far; a tie goes to the one listed first."""
        name = min(self.counts, key=self.counts.__getitem__)
        self.counts[name] += 1
        return name
