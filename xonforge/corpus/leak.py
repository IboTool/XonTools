"""The leak test (XONFORGE_SPEC.md §9; the user's items 17 and 19 of 2026-09-25, xonforge/docs/decisions.md): no sealed
document may be in any worktree or in the repository's history. The test never opens the sealed or judged
locations. When a split is sealed, a fingerprint manifest of its documents is written into the repository
(data/xonforge/fingerprints/<version>-<split>.json): the SHA-256 of the split's canary string and, for each document,
the SHA-256 of its normalized text and the hashes (8 bytes of BLAKE2b) of its word 8-grams, leaving out those that
occur in the generator's own prompts (xonforge/prompts/) and templates (the document's skeleton statements, as the
templates word them). The test reads those manifests and the files it scans, and writes nothing.

A file leaks a sealed document if it holds the split's canary string, the document's whole normalized text (as the
whole file, or as a string value in a JSON or JSONL file), or 2 or more distinct 8-grams of it. Normalized: NFKC, case
folded, punctuation and quotes stripped, whitespace collapsed. Scope: every file in every worktree, tracked or not,
excluding .git, on every test run (tests/xonforge/test_xonforge_leak.py); the commits being pushed, by
``python -m xonforge leak-check --commits <range>``; the full history, by ``python -m xonforge leak-audit``. With no
fingerprint manifest, each passes at once. A file that is not UTF-8 text is not searched, and is reported as skipped
(the implementing agent's reading).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from xon_common.worktrees import worktree_roots
from xonforge import locations
from xonforge.render.phrasing import statement
from xonforge.render.renderer import doc_id
from xonforge.skeleton.schema import Skeleton

from .export import ExportRecord
from .seal import canary_sha256

K = 8
SHARED_MIN = 2
FOLDER = locations.ROOT / "data" / "xonforge" / "fingerprints"
PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
CANARY = re.compile(r"XONFORGE-CANARY-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
JSON_SUFFIXES = (".json", ".jsonl")


@cache
def _punctuation() -> dict[int, None]:
    return {c: None for c in range(sys.maxunicode + 1) if unicodedata.category(chr(c)).startswith("P")}


def words(text: str) -> list[str]:
    return unicodedata.normalize("NFKC", text).casefold().translate(_punctuation()).split()


def text_sha256(text: str) -> str:
    return hashlib.sha256(" ".join(words(text)).encode("utf-8")).hexdigest()


def ngrams(text: str, k: int = K) -> set[str]:
    w = words(text)
    return {hashlib.blake2b(" ".join(w[i:i + k]).encode("utf-8"), digest_size=8).hexdigest()
            for i in range(len(w) - k + 1)}


def prompt_ngrams(folder: str | Path = PROMPTS) -> set[str]:
    out: set[str] = set()
    for p in sorted(Path(folder).iterdir()):
        if p.suffix in (".txt", ".json"):
            out |= ngrams(p.read_text(encoding="utf-8"))
    return out


def template_ngrams(skeleton: Skeleton) -> set[str]:
    out: set[str] = set()
    for f in skeleton.facts:
        out |= ngrams(statement(f, skeleton)) | ngrams("Assume that " + statement(f, skeleton))
    return out


# ------------------------------------------------------------------------------------------ the fingerprint manifest
def fingerprint(*, version: str, split: str, canary: str, documents: Sequence[tuple[str, str, Skeleton]],
                prompts: str | Path = PROMPTS) -> dict:
    """``documents``: each sealed document's id, text and skeleton."""
    common = prompt_ngrams(prompts)
    docs = [{"doc_id": d, "text_sha256": text_sha256(text),
             "ngrams": sorted(ngrams(text) - common - template_ngrams(skeleton))} for d, text, skeleton in documents]
    return {"version": version, "split": split, "k": K, "canary_sha256": canary_sha256(canary), "documents": docs}


def fingerprint_split(folder: str | Path, split: str, *, version: str, prompts: str | Path = PROMPTS) -> dict:
    """The fingerprint manifest of a sealed split, read from its own files when it is sealed."""
    folder = Path(folder)
    lines = (folder / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
    records = [ExportRecord.model_validate_json(line) for line in lines if line.strip()]
    skeletons = {}
    for line in (folder / f"{split}.skeletons.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw = json.loads(line)
            raw.pop("canary", None)
            sk = Skeleton.model_validate(raw)
            skeletons[doc_id(sk)] = sk
    canaries = {r.canary for r in records}
    if len(canaries) != 1:
        raise ValueError(f"the {split} split's records carry one canary string, its own, not {len(canaries)}")
    missing = [r.doc_id for r in records if r.doc_id not in skeletons]
    if missing:
        raise ValueError(f"the {split} split has no skeleton for {', '.join(missing)}")
    return fingerprint(version=version, split=split, canary=canaries.pop(), prompts=prompts,
                       documents=[(r.doc_id, r.text, skeletons[r.doc_id]) for r in records])


def write_fingerprint(made: dict, folder: str | Path | None = None) -> Path:
    path = Path(FOLDER if folder is None else folder) / f"{made['version']}-{made['split']}.json"
    if path.exists():
        raise FileExistsError(f"{path} is already written")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(made, indent=1) + "\n", encoding="utf-8", newline="\n")
    return path


@dataclass(frozen=True)
class Prints:
    canaries: dict[str, str]                 # a canary string's SHA-256 -> "the <split> split of <version>"
    texts: dict[str, str]                    # a normalized text's SHA-256 -> "<doc id> of <version>"
    index: dict[str, tuple[str, ...]]        # an 8-gram's hash -> the documents that have it


def load(folder: str | Path | None = None) -> Prints | None:
    """The committed fingerprint manifests, or None if there is none."""
    folder = Path(FOLDER if folder is None else folder)
    paths = sorted(folder.glob("*.json")) if folder.is_dir() else []
    if not paths:
        return None
    canaries, texts, index = {}, {}, {}
    for p in paths:
        made = json.loads(p.read_text(encoding="utf-8"))
        if made.get("k") != K:
            raise ValueError(f"{p}: a fingerprint manifest of {K}-word sequences, not {made.get('k')}")
        canaries[made["canary_sha256"]] = f"the {made['split']} split of {made['version']}"
        for d in made["documents"]:
            label = f"{d['doc_id']} of {made['version']}"
            texts[d["text_sha256"]] = label
            for g in d["ngrams"]:
                index.setdefault(g, []).append(label)
    return Prints(canaries, texts, {g: tuple(v) for g, v in index.items()})


# ------------------------------------------------------------------------------------------ searching
def _strings(value) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def json_strings(text: str) -> list[str]:
    """The string values in a JSON document, or in each line of a JSONL file; none if it is neither."""
    try:
        return list(_strings(json.loads(text)))
    except ValueError:
        pass
    out = []
    for line in text.splitlines():
        try:
            out += _strings(json.loads(line))
        except ValueError:
            continue
    return out


def search(text: str, prints: Prints, *, json_like: bool = False) -> list[str]:
    """What of the sealed documents ``text`` holds: each as a phrase, or none."""
    found = [f"the canary string of {prints.canaries[h]}"
             for h in sorted({canary_sha256(c) for c in CANARY.findall(text)}) if h in prints.canaries]
    strings = [text, *(json_strings(text) if json_like else ())]
    found += sorted({f"the whole text of {prints.texts[h]}" for h in map(text_sha256, strings) if h in prints.texts})
    shared = Counter(label for g in set().union(*map(ngrams, strings)) for label in prints.index.get(g, ()))
    found += [f"{n} distinct {K}-word sequences of {label}" for label, n in sorted(shared.items()) if n >= SHARED_MIN]
    return found


@dataclass(frozen=True)
class Finding:
    where: str
    what: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    searched: int = 0
    skipped: list[str] = field(default_factory=list)        # not UTF-8 text
    manifests: bool = False

    def lines(self) -> list[str]:
        if not self.manifests:
            return ["No fingerprint manifest is committed (data/xonforge/fingerprints/), so no sealed document can "
                    "have leaked: nothing was searched."]
        n = len(self.skipped)
        out = [f"Searched {self.searched} files; {n} other{' was' if n == 1 else 's were'} not UTF-8 text, so not "
               "searched."]
        out += [f"- {f.where}: {f.what}" for f in self.findings] or ["No sealed document was found."]
        return out


def _search_bytes(data: bytes, where: str, suffix: str, prints: Prints, report: Report) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        report.skipped.append(where)
        return
    report.searched += 1
    report.findings += [Finding(where, what) for what in search(text, prints, json_like=suffix in JSON_SUFFIXES)]


def files(roots: Iterable[str | Path]) -> Iterator[Path]:
    """Every file under each root, tracked or not, but .git; a root inside another is walked once."""
    roots = sorted({Path(r).resolve() for r in roots})
    for root in roots:
        others = {r for r in roots if r != root and root in r.parents}
        for here, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d != ".git" and Path(here, d) not in others)
            for n in sorted(names):
                if n != ".git":
                    yield Path(here, n)


def check_worktrees(*, prints: Prints | None = None, roots: Iterable[str | Path] | None = None,
                    folder: str | Path | None = None) -> Report:
    prints = load(folder) if prints is None else prints
    if prints is None:
        return Report()
    report = Report(manifests=True)
    for p in files(worktree_roots(locations.ROOT) if roots is None else roots):
        try:
            data = p.read_bytes()
        except OSError:
            report.skipped.append(str(p))
            continue
        _search_bytes(data, str(p), p.suffix, prints, report)
    return report


# ------------------------------------------------------------------------------------------ git history, read only
def _git(args: Sequence[str], cwd: Path, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True, **kw)


def blobs(revisions: Sequence[str], cwd: str | Path = locations.ROOT) -> dict[str, str]:
    """Each blob reachable from ``revisions`` (git rev-list's arguments), with one path it has."""
    bad = [r for r in revisions if r.startswith("-") and r != "--all"]
    if bad:
        raise ValueError(f"revisions are commits or ranges, not options: {', '.join(bad)}")
    cwd = Path(cwd)
    listed = _git(["rev-list", "--objects", *(["--all"] if "--all" in revisions else []), "--end-of-options",
                   *[r for r in revisions if r != "--all"]], cwd).stdout.decode("utf-8", "replace")
    paths = {}
    for line in listed.splitlines():
        sha, _, path = line.partition(" ")
        if path:
            paths.setdefault(sha, path)
    if not paths:
        return {}
    kinds = _git(["cat-file", "--batch-check=%(objectname) %(objecttype)"], cwd,
                 input="".join(f"{s}\n" for s in paths).encode()).stdout.decode().split()
    return {sha: paths[sha] for sha, kind in zip(kinds[::2], kinds[1::2]) if kind == "blob"}


def check_history(revisions: Sequence[str], *, prints: Prints | None = None, cwd: str | Path = locations.ROOT,
                  folder: str | Path | None = None) -> Report:
    """Searches every blob reachable from ``revisions``: the commits being pushed (a range), or ``["--all"]``."""
    prints = load(folder) if prints is None else prints
    if prints is None:
        return Report()
    report = Report(manifests=True)
    found = blobs(revisions, cwd)
    if not found:
        return report
    with tempfile.TemporaryFile() as listing:
        listing.write("".join(f"{s}\n" for s in found).encode())
        listing.seek(0)
        with subprocess.Popen(["git", "cat-file", "--batch"], cwd=Path(cwd), stdin=listing,
                              stdout=subprocess.PIPE) as proc:
            for _ in found:
                sha, _kind, size = proc.stdout.readline().decode().split()
                data = proc.stdout.read(int(size))
                proc.stdout.read(1)
                _search_bytes(data, f"{sha[:12]}:{found[sha]}", Path(found[sha]).suffix, prints, report)
    return report
