"""The response cache (XONFORGE_SPEC.md §4.2): one JSON file per answered request, named by the request's key
(hashing.request_key of the body sent, which holds the model, the system and user text, the schema and every
parameter sent), in a directory per provider entry. The directory makes the provider part of the key, while the key
itself stays the one A1 computes for the same request. Where the cache may live is the caller's rule: XonForge's is
outside every worktree of the repository.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

PROVIDER_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
KEY = re.compile(r"[0-9a-f]{64}")


class ResponseCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path(self, provider: str, key: str) -> Path:
        if not PROVIDER_NAME.fullmatch(provider) or not KEY.fullmatch(key):
            raise ValueError(f"not a provider entry name and a request key: {provider!r}, {key!r}")
        return self.root / provider / f"{key}.json"

    def get(self, provider: str, key: str) -> dict | None:
        path = self.path(provider, key)
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, provider: str, key: str, record: dict) -> None:
        path = self.path(provider, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{key}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
