"""Where XonForge keeps what must stay out of the repository (rules.md, XonForge; CHANGELOG_EXPERIMENTS.md,
2026-09-25): the response cache, the sealed test split and the judged split, each in the directory named by its
environment variable, and, under the cache directory's parent, the review, decision and diagnostic logs that hold
text and the review-queue items and reviewer outputs of sealed or judged documents. A location is refused when its
variable is unset or the path is inside any worktree of this repository.
"""
from __future__ import annotations

import os
from pathlib import Path

from xon_common.worktrees import inside, worktree_roots

CACHE_ENV = "XONFORGE_CACHE_DIR"
SEALED_ENV = "XONFORGE_SEALED_DIR"
JUDGED_ENV = "XONFORGE_JUDGED_DIR"
ROOT = Path(__file__).resolve().parents[1]


class LocationRefused(RuntimeError):
    """A location XonForge must not use: its variable is unset, or it is inside a worktree of this repository."""


def outside_worktrees(path: str | Path, what: str) -> Path:
    p = Path(path).resolve()
    root = inside(p, {ROOT, *worktree_roots(ROOT)})
    if root is not None:
        raise LocationRefused(f"The {what} ({p}) is inside the worktree {root}; it must be outside every worktree of "
                              "this repository.")
    return p


def from_env(env: str, what: str) -> Path:
    value = os.environ.get(env, "").strip()
    if not value:
        raise LocationRefused(f"The {what} is in the directory named by {env}, which is not set.")
    return outside_worktrees(value, what)


def cache_dir() -> Path:
    return from_env(CACHE_ENV, "response cache")


def sealed_dir() -> Path:
    return from_env(SEALED_ENV, "sealed test split")


def judged_dir() -> Path:
    return from_env(JUDGED_ENV, "judged split")


def text_log_dir() -> Path:
    """The cache directory's parent: the review, decision and diagnostic logs that hold text, and the review-queue
    items and reviewer outputs of sealed or judged documents."""
    return outside_worktrees(cache_dir().parent, "directory of the logs that hold text")
