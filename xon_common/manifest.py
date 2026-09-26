"""Hash manifests (XONFORGE_SPEC.md §9): a SHA-256 for every file of a folder, and one hash over them all. The format
and its check live here, shared, so that a check on a sealed split needs nothing but xon_common; making a manifest
lives in xonforge/corpus/seal.py.

A manifest is a JSON object: ``version`` (1); ``files``, each file's path, relative to the folder and written with
forward slashes, mapped to its SHA-256; optionally ``canary``, the corpus's canary string, which XONFORGE_SPEC.md §9
puts in every file; and ``manifest_hash``, the SHA-256 of the canonical JSON of the rest. The manifest hash is what
SEALED.md records, and what should be published before any evaluation.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

VERSION = 1
_DIGEST = re.compile(r"[0-9a-f]{64}")


def file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_hash(files: dict[str, str], canary: str | None = None) -> str:
    body = {"version": VERSION, "files": files, **({"canary": canary} if canary is not None else {})}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check(files: dict[str, str]) -> None:
    for rel, digest in files.items():
        parts = PurePosixPath(rel).parts
        if (not rel or "\\" in rel or ":" in rel or rel.startswith("/") or ".." in parts
                or PurePosixPath(rel).as_posix() != rel):
            raise ValueError(f"a manifest path is relative, written with forward slashes, and stays in its folder: "
                             f"{rel!r}")
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise ValueError(f"the hash of {rel} is not a SHA-256 in lower-case hexadecimal")


def build(files: dict[str, str], *, canary: str | None = None) -> dict:
    """A manifest of the given files and their hashes."""
    _check(files)
    if canary is not None and (not isinstance(canary, str) or not canary.strip()):
        raise ValueError("a manifest's canary string is a non-empty string")
    files = dict(sorted(files.items()))
    return {"version": VERSION, "files": files, **({"canary": canary} if canary is not None else {}),
            "manifest_hash": manifest_hash(files, canary)}


def dumps(manifest: dict) -> str:
    return json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def load(path: str | Path) -> dict:
    """A manifest file, checked for its form; ``verify`` checks its hashes."""
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) - {"canary"} != {"version", "files", "manifest_hash"}:
        raise ValueError(f"{path}: a manifest holds version, files, manifest_hash and optionally canary, and nothing "
                         "else")
    if manifest["version"] != VERSION or not isinstance(manifest["files"], dict):
        raise ValueError(f"{path}: not a version {VERSION} manifest")
    if "canary" in manifest and not isinstance(manifest["canary"], str):
        raise ValueError(f"{path}: a manifest's canary string is a string")
    _check(manifest["files"])
    return manifest


def verify(manifest: dict, root: str | Path, *, ignore: tuple[str, ...] = ()) -> list[str]:
    """What differs between the folder and its manifest; empty when the manifest hash matches its files, and every
    file of the folder (``ignore`` aside) is listed, present and unchanged."""
    root = Path(root)
    problems = []
    if manifest_hash(manifest["files"], manifest.get("canary")) != manifest["manifest_hash"]:
        problems.append("the manifest hash does not match the files it lists")
    present = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} - set(ignore)
    listed = set(manifest["files"])
    problems += [f"missing: {p}" for p in sorted(listed - present)]
    problems += [f"not in the manifest: {p}" for p in sorted(present - listed)]
    problems += [f"changed: {p}" for p in sorted(listed & present) if file_hash(root / p) != manifest["files"][p]]
    return problems
