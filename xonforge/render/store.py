"""Where rendered documents wait for the split (rules.md, XonForge: generated documents stay outside the repository
until the split assigns them). By default under the cache directory's parent, in ``documents/<run>/``, beside the
other files that hold text; a store refuses any root inside a worktree of this repository."""
from __future__ import annotations

import json
import os
from pathlib import Path

from xonforge import locations

from .schema import Document


class DocumentStore:
    def __init__(self, root: str | Path | None = None):
        self.root = locations.outside_worktrees(root if root is not None else locations.text_log_dir() / "documents",
                                                "document store")

    def path(self, run: str, doc_id: str) -> Path:
        for part, what in ((run, "run"), (doc_id, "document id")):
            if not part or any(c in part for c in '/\\:*?"<>|') or part in (".", ".."):
                raise ValueError(f"a {what} is a plain file name, not {part!r}")
        return self.root / run / f"{doc_id}.json"

    def save(self, run: str, document: Document) -> Path:
        path = self.path(run, document.doc_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(document.model_dump_json(indent=1), encoding="utf-8")
        os.replace(tmp, path)
        return path

    def load(self, run: str, doc_id: str) -> Document | None:
        path = self.path(run, doc_id)
        return Document.model_validate(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None

    def documents(self, run: str) -> list[Document]:
        folder = self.root / run
        return [Document.model_validate(json.loads(p.read_text(encoding="utf-8")))
                for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []
