"""The worktrees of a git repository, read from git's own files rather than by running git: the main worktree and
every linked one. XonForge keeps its cache, its sealed and judged splits and its logs that hold text outside all of
them.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def repository_root(start: Path) -> Path | None:
    """The nearest directory at or above ``start`` that has a .git entry (a directory, or a linked worktree's file)."""
    for d in (start, *start.parents):
        if (d / ".git").exists():
            return d
    return None


def _gitdir(root: Path) -> Path:
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git
    text = dot_git.read_text(encoding="utf-8").strip()
    if not text.startswith("gitdir:"):
        raise ValueError(f"{dot_git} is neither a git directory nor a link to one")
    target = Path(text[len("gitdir:"):].strip())
    return (target if target.is_absolute() else root / target).resolve()


def worktree_roots(start: str | Path | None = None) -> list[Path]:
    """The root of every worktree of the repository that holds ``start`` (default: this package's repository), or
    an empty list if ``start`` is not in one."""
    root = repository_root(Path(start).resolve() if start is not None else HERE)
    if root is None:
        return []
    gitdir = _gitdir(root)
    link = gitdir / "commondir"
    common = (gitdir / link.read_text(encoding="utf-8").strip()).resolve() if link.exists() else gitdir
    roots = {root.resolve()}
    if common.name == ".git":
        roots.add(common.parent.resolve())
    for entry in sorted((common / "worktrees").glob("*/gitdir")):
        target = Path(entry.read_text(encoding="utf-8").strip())
        roots.add((target if target.is_absolute() else entry.parent / target).resolve().parent)
    return sorted(roots)


def inside(path: str | Path, roots) -> Path | None:
    """The root among ``roots`` that ``path`` is at or under, if any."""
    p = Path(path).resolve()
    for r in roots:
        r = Path(r).resolve()
        if p == r or r in p.parents:
            return r
    return None
