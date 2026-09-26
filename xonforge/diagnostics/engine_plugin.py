"""The engine diagnostic (XONFORGE_SPEC.md §7.5): the one module allowed to import the consistency engine, and one
that nothing imports (tests/xonforge/test_xonforge_boundary.py).

Until the tag a1-rev2.2-frozen exists it is an inert stub that imports no engine module. Its refusal is already in
force: it screens no document under the sealed test split or the judged split, so that the engine never screens its
own test corpus, and while either location is unset it screens nothing, since no path can then be shown to be
outside it.
"""
from __future__ import annotations

from pathlib import Path

from ..locations import LocationRefused, judged_dir, sealed_dir


class SealedPathRefused(RuntimeError):
    """A document the diagnostic must not screen."""


def _within(path: Path, root: Path) -> bool:
    """Whether ``path`` is the root or inside it. Compared again with case folded, so a sealed path is still sealed
    when only its letter case differs."""
    if path == root or root in path.parents:
        return True
    folded, base = path.as_posix().casefold(), root.as_posix().casefold().rstrip("/")
    return folded == base or folded.startswith(base + "/")


def check_path(path: str | Path) -> Path:
    """The document's resolved path, if it is outside the sealed and judged splits; otherwise SealedPathRefused."""
    p = Path(path).resolve()
    for what, location in (("sealed test split", sealed_dir), ("judged split", judged_dir)):
        try:
            root = location()
        except LocationRefused as exc:
            raise SealedPathRefused(f"{p} cannot be checked against the {what}: {exc}") from None
        if _within(p, root):
            raise SealedPathRefused(f"{p} is in the {what} ({root}); the engine never screens its own test corpus.")
    return p


def screen(path: str | Path):
    check_path(path)
    raise NotImplementedError("The engine diagnostic is an inert stub until the tag a1-rev2.2-frozen exists.")
