"""Sealing the test split (XONFORGE_SPEC.md §9): a manifest of every file's SHA-256 and one manifest hash (format and
check in xon_common/manifest.py); SEALED.md, recording the manifest hash, the date and the corpus version, to be
published before any evaluation so that later tampering shows; a canary string unique to the split (one per split, the
user's item 19 of 2026-09-25), for every file, the manifest included, and the README; and optional encryption at rest
with a passphrase. The sealed split lives outside the repository (XONFORGE_SEALED_DIR). SEALED.md holds no document
text and only the SHA-256 of the split's canary string, never the string, so it can be committed and a search for the
string stays clean (leak.py); a seal is appended to it once per corpus version. Only documents of a corpus of record
are sealed (xonforge/modes.py): the manifest is not written while any document line in the folder is not labelled so,
a pipeline-test document included.

Encryption (the implementing agent's choice of method): a key derived from the passphrase with scrypt (n = 2**15,
r = 8, p = 1, a random 16-byte salt per file), and AES-256-GCM with a random 12-byte nonce, from the cryptography
package (pyproject.toml's xonforge extra). Encrypted copies are written beside the plaintext's folder, which is left
as it is.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Sequence

from xon_common import manifest as manifests
from xonforge import locations, modes

MANIFEST = "MANIFEST.json"
MAGIC = b"XONFORGE-ENC1\n"
CANARY_NOTICE = ("{canary}: this string marks XonForge test data for contradiction detection. It must not appear in "
                 "training data; finding it in a model's training data or output means the corpus leaked.")


def new_canary() -> str:
    return f"XONFORGE-CANARY-{uuid.uuid4()}"


def new_canaries(splits: Sequence[str]) -> dict[str, str]:
    """A canary string of its own for each split."""
    return {s: new_canary() for s in splits}


def canary_sha256(canary: str) -> str:
    return hashlib.sha256(canary.encode("utf-8")).hexdigest()


def make_manifest(root: str | Path, *, canary: str | None = None) -> dict:
    """The manifest of every file under ``root`` but the manifest itself, with the split's canary string."""
    root = Path(root)
    files = {p.relative_to(root).as_posix(): manifests.file_hash(p) for p in sorted(root.rglob("*"))
             if p.is_file() and p.relative_to(root).as_posix() != MANIFEST}
    return manifests.build(files, canary=canary)


def not_of_record(root: str | Path) -> list[str]:
    """The document lines under ``root`` (in its .jsonl files other than skeleton files) whose mode is not
    ``record``."""
    root = Path(root)
    found = []
    for p in sorted(root.rglob("*.jsonl")):
        if p.name.endswith(".skeletons.jsonl"):
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                mode = json.loads(line).get("mode")
            except (ValueError, AttributeError):
                mode = None
            if mode != modes.RECORD:
                found.append(f"{p.relative_to(root).as_posix()}, line {n}: "
                             + ("a pipeline-test document" if mode == modes.PIPELINE_TEST else "not labelled record"))
    return found


def write_manifest(root: str | Path, *, canary: str | None = None) -> dict:
    """Writes MANIFEST.json into the sealed split's folder, which must be outside every worktree and hold only
    documents of a corpus of record."""
    root = locations.outside_worktrees(root, "sealed split")
    found = not_of_record(root)
    if found:
        raise ValueError("a sealed split holds only documents of a corpus of record, and a pipeline-test document is "
                         "excluded from any: " + "; ".join(found[:5]) + ("; and more" if len(found) > 5 else ""))
    made = make_manifest(root, canary=canary)
    (root / MANIFEST).write_text(manifests.dumps(made), encoding="utf-8", newline="\n")
    return made


def verify_sealed(root: str | Path) -> list[str]:
    root = Path(root)
    return manifests.verify(manifests.load(root / MANIFEST), root, ignore=(MANIFEST,))


def seal_section(*, corpus_version: str, date: str, manifest_hash: str, files: int, canary: str) -> str:
    """``canary``: the sealed split's canary string, of which the section records only the SHA-256."""
    return (f"## {corpus_version}\n\n"
            f"- Sealed: {date}\n"
            f"- Manifest hash (SHA-256): `{manifest_hash}`\n"
            f"- Files: {files}\n"
            f"- Canary string's SHA-256: `{canary_sha256(canary)}`\n")


def append_seal(path: str | Path, *, corpus_version: str, date: str, manifest: dict, canary: str) -> Path:
    """Appends the corpus version's seal to SEALED.md; a version is sealed once. ``canary``: the sealed split's."""
    path = Path(path)
    text = path.read_text(encoding="utf-8") if path.exists() else (
        "# Sealed XonForge test splits\n\nEach seal records a sealed test split's manifest hash. Publish it before "
        "any evaluation on the split, so that any later change to the split shows.\n")
    if f"\n## {corpus_version}\n" in text:
        raise ValueError(f"corpus version {corpus_version} is already sealed in {path}")
    text = text.rstrip("\n") + "\n\n" + seal_section(corpus_version=corpus_version, date=date,
                                                    manifest_hash=manifest["manifest_hash"],
                                                    files=len(manifest["files"]), canary=canary)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


# ------------------------------------------------------------------------------------------ encryption at rest
def _key(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    if not passphrase:
        raise ValueError("an empty passphrase encrypts nothing")
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode("utf-8"))


def encrypt(data: bytes, passphrase: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = os.urandom(16), os.urandom(12)
    return MAGIC + salt + nonce + AESGCM(_key(passphrase, salt)).encrypt(nonce, data, MAGIC)


def decrypt(blob: bytes, passphrase: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not blob.startswith(MAGIC):
        raise ValueError("not a file XonForge encrypted")
    salt, nonce, body = blob[len(MAGIC):len(MAGIC) + 16], blob[len(MAGIC) + 16:len(MAGIC) + 28], blob[len(MAGIC) + 28:]
    try:
        return AESGCM(_key(passphrase, salt)).decrypt(nonce, body, MAGIC)
    except InvalidTag:
        raise ValueError("the passphrase is wrong, or the file was altered") from None


def encrypt_folder(src: str | Path, dst: str | Path, passphrase: str) -> list[Path]:
    """An encrypted copy (``<name>.enc``) of every file under ``src``, in the same layout under ``dst``; both folders
    must be outside every worktree."""
    src = locations.outside_worktrees(src, "sealed split")
    dst = locations.outside_worktrees(dst, "encrypted copy")
    if dst.resolve().is_relative_to(src.resolve()):
        raise ValueError("the encrypted copy goes outside the sealed split's folder, whose manifest it would break")
    written = []
    for p in sorted(src.rglob("*")):
        if p.is_file():
            out = dst / (p.relative_to(src).as_posix() + ".enc")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(encrypt(p.read_bytes(), passphrase))
            written.append(out)
    return written
