"""Export and placement (XONFORGE_SPEC.md §9). Each split is one JSONL file, a line per document: its text and fact→span
map, variant, plant, traps, arity fact and premise status, difficulty (set and measured), renderer, reviewers, flags,
scan results, human decisions and hashes, with its split's canary string. The skeletons go in a file of their own,
and each folder gets a README and a LICENSE.txt, both with the "not for training" notice, the license and the canary
strings of the folder's splits (the user's items 16 and 19 of 2026-09-25, xonforge/docs/decisions.md): CC BY 4.0, the
notice a request and not a term of the license, and one canary string per split, so that the sealed split's canary is
never in a file of another split. Nothing is exported with a document whose renderer's provider has no logged check of
its terms on publishing its outputs as a dataset (terms.py).

Where each split goes (rules.md): development and calibration into the repository, under data/xonforge/<version>/;
the sealed test split under XONFORGE_SEALED_DIR/<version>/ and the judged split under XONFORGE_JUDGED_DIR/<version>/,
both outside the repository. Which base goes to which split is splits.py's assignment: placement takes it, keeps each
base's variants together, and places only accepted documents.

Every corpus has one mode (xonforge/modes.py), and so does every record in it. A pipeline test's documents never enter
a sealed or judged split and are excluded from any corpus of record: its development and calibration splits go under
data/xonforge/pipeline_test/<version>/ (the implementing agent's choice), apart from every corpus of record, and its
README says it is a pipeline test.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from xonforge import locations, modes
from xonforge.render.schema import Document, Renderer, ScanRecord
from xonforge.review.decisions import Entry
from xonforge.skeleton.schema import Skeleton
from xonforge.waiting import Waiting

from . import terms
from .acceptance import Verdict

SPLITS = ("development", "calibration", "test", "judged")
OUT_OF_BOUNDS = {modes.RECORD: (), modes.PIPELINE_TEST: ("test", "judged")}    # splits a mode's documents never enter
DATA_DIR = locations.ROOT / "data" / "xonforge"
NOTICE = ("Not for training, a request: this corpus is test data for contradiction detection. Please do not train or "
          "tune models on it, and keep its sealed test split out of any training data. This request is not a term of "
          "the license.")
LICENSE = ("This corpus is licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0). "
           "The license: https://creativecommons.org/licenses/by/4.0/. Its legal code: "
           "https://creativecommons.org/licenses/by/4.0/legalcode.")
PIPELINE_TEST_NOTICE = ("Pipeline test. Every document here was made in XonForge's pipeline-test mode, in which the "
                        "renderer and the reviewers may be different models of one provider. This is not a corpus of "
                        "record: its documents are excluded from any corpus of record, and none enters a sealed or "
                        "judged split.")


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    decision: str
    reason: str
    reviewer: str | None = None
    time: str


class ExportRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    doc_id: str
    base_id: str
    variant: Literal["consistent", "planted", "trap_only"]
    mode: Literal["record", "pipeline_test"]
    genre: str
    text: str
    spans: dict[str, str]
    plant: dict | None
    traps: list[dict]
    arity_fact: str | None
    premise_status: str | None
    difficulty: dict                  # "set": the knobs and rules; "measured": after rendering (§5.4)
    renderer: Renderer
    reviewers: list[str]
    flags: list[str]
    scans: list[ScanRecord]
    decisions: list[Decision]
    hashes: dict[str, str]            # "skeleton": the skeleton's digest; "text": the text's SHA-256
    canary: str


def _license(license: str | None) -> str:
    if not license or not license.strip():
        raise ValueError("an export carries its license's text")
    return license


def _canaries(splits: Sequence[str], canaries: Mapping[str, str]) -> dict[str, str]:
    """The canary strings of the given splits: one per split, each its own."""
    missing = [s for s in splits if not (canaries.get(s) or "").strip()]
    if missing:
        raise ValueError(f"each split has a canary string of its own, and {', '.join(missing)} has none")
    if len(set(canaries.values())) != len(canaries):
        raise ValueError("each split has a canary string of its own, and two splits share one")
    return {s: canaries[s] for s in splits}


def _canary_lines(canaries: Mapping[str, str]) -> str:
    return "\n".join(f"Canary string of the {s} split: {c}" for s, c in canaries.items())


def record(skeleton: Skeleton, document: Document, *, canary: str, reviewers: Sequence[str] = (),
           decisions: Sequence[Entry] = ()) -> ExportRecord:
    if document.text is None or document.skeleton_digest != skeleton.digest():
        raise ValueError(f"{document.doc_id}: only a rendered document of this skeleton is exported")
    rules = document.rules
    plain = skeleton.model_dump(mode="json")
    return ExportRecord(
        doc_id=document.doc_id, base_id=document.base_id, variant=document.variant, mode=document.mode,
        genre=skeleton.genre,
        text=document.text, spans=dict(document.spans), plant=plain["plant"], traps=plain["traps"],
        arity_fact=skeleton.arity_fact, premise_status=skeleton.premise_status,
        difficulty={"set": {**plain["difficulty"], "words": rules.words, "explicitness": rules.explicitness,
                            "lexical_variety": rules.lexical_variety},
                    "measured": dict(document.measured)},
        renderer=document.renderer, reviewers=list(reviewers), flags=list(document.flags), scans=list(document.scans),
        decisions=[Decision(decision=e.decision, reason=e.reason, reviewer=e.reviewer, time=e.time)
                   for e in decisions if e.kind == "decision" and e.doc_id == document.doc_id],
        hashes={"skeleton": skeleton.digest(), "text": hashlib.sha256(document.text.encode("utf-8")).hexdigest()},
        canary=canary)


def _jsonl(path: Path, rows: Sequence[str]) -> Path:
    if path.exists():
        raise FileExistsError(f"{path} is already written")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(r + "\n" for r in rows), encoding="utf-8", newline="\n")
    return path


def _enters(mode: str, split: str) -> None:
    if split not in SPLITS:
        raise ValueError(f"the splits are {', '.join(SPLITS)}, not {split!r}")
    if split in OUT_OF_BOUNDS[modes.check(mode)]:
        raise ValueError(f"a pipeline-test document never enters a sealed or judged split, and this is the {split} "
                         "split")


def write_split(folder: str | Path, split: str, records: Sequence[ExportRecord], *, license: str | None = LICENSE,
                canary: str) -> Path:
    """``canary``: the split's canary string."""
    _license(license)
    if split not in SPLITS:
        raise ValueError(f"the splits are {', '.join(SPLITS)}, not {split!r}")
    if len({r.mode for r in records}) > 1:
        raise ValueError("a split's records are of one mode: a pipeline-test document is excluded from any corpus of "
                         "record")
    if records:
        _enters(records[0].mode, split)
    if any(r.canary != canary for r in records):
        raise ValueError("every record carries its split's canary string")
    return _jsonl(Path(folder) / f"{split}.jsonl", [r.model_dump_json() for r in records])


def write_skeletons(folder: str | Path, split: str, skeletons: Sequence[Skeleton], *, canary: str) -> Path:
    return _jsonl(Path(folder) / f"{split}.skeletons.jsonl",
                  [json.dumps({**s.model_dump(mode="json"), "canary": canary}, ensure_ascii=False) for s in skeletons])


def write_readme(folder: str | Path, *, corpus_version: str, splits: Sequence[str], mode: str,
                 license: str | None = LICENSE, canaries: Mapping[str, str]) -> Path:
    """``canaries``: each split's canary string; the README carries those of its folder's splits only."""
    license = _license(license)
    for split in splits:
        _enters(mode, split)
    mine = _canaries(splits, canaries)
    path = Path(folder) / "README.md"
    if path.exists():
        raise FileExistsError(f"{path} is already written")
    path.parent.mkdir(parents=True, exist_ok=True)
    test = f"{PIPELINE_TEST_NOTICE}\n\n" if mode == modes.PIPELINE_TEST else ""
    path.write_text(f"# XonForge corpus {corpus_version}\n\n{test}{NOTICE}\n\n"
                    f"Splits here: {', '.join(splits)}. Each split's documents are in <split>.jsonl and its skeletons "
                    f"in <split>.skeletons.jsonl, one JSON object per line.\n\nLicense: {license}\n\n"
                    f"{_canary_lines(mine)}\n", encoding="utf-8", newline="\n")
    return path


def write_license(folder: str | Path, *, splits: Sequence[str], license: str | None = LICENSE,
                  canaries: Mapping[str, str]) -> Path:
    license = _license(license)
    mine = _canaries(splits, canaries)
    path = Path(folder) / "LICENSE.txt"
    if path.exists():
        raise FileExistsError(f"{path} is already written")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{license}\n\n{NOTICE}\n\n{_canary_lines(mine)}\n", encoding="utf-8", newline="\n")
    return path


def destination(split: str, version: str, *, mode: str, data_dir: str | Path | None = None,
                sealed: str | Path | None = None, judged: str | Path | None = None) -> Path:
    """Where a split's files go: development and calibration into the repository, the test and judged splits
    outside it; a pipeline test's apart from every corpus of record."""
    _enters(mode, split)
    if split in ("development", "calibration"):
        root = Path(data_dir if data_dir is not None else DATA_DIR)
        return (root / "pipeline_test" if mode == modes.PIPELINE_TEST else root) / version
    if split == "test":
        root = locations.outside_worktrees(sealed, "sealed split") if sealed is not None else locations.sealed_dir()
        return root / version
    if split == "judged":
        root = locations.outside_worktrees(judged, "judged split") if judged is not None else locations.judged_dir()
        return root / version
    raise ValueError(f"the splits are {', '.join(SPLITS)}, not {split!r}")


def place(assignment: Mapping[str, str], entries: Sequence[tuple[Skeleton, Document]],
          verdicts: Mapping[str, Verdict], *, mode: str, version: str, canaries: Mapping[str, str],
          license: str | None = LICENSE, checks: Mapping[str, terms.TermsCheck] | None = None,
          reviewers: Mapping[str, Sequence[str]] | None = None, decisions: Sequence[Entry] = (),
          data_dir: str | Path | None = None, sealed: str | Path | None = None,
          judged: str | Path | None = None) -> dict[str, Path]:
    """Writes each split's documents, skeletons, README and license to its destination. ``assignment``: each base's
    split (splits.py); ``entries``: every variant of every base, with its document; ``mode``: the corpus's mode, which
    every document must have; ``canaries``: each placed split's canary string; ``checks``: the logged checks of the
    providers' terms (terms.yaml by default)."""
    _license(license)
    modes.check(mode)
    refused = terms.problems({d.renderer.provider for _, d in entries},
                             terms.load() if checks is None else checks)
    if refused:
        raise Waiting("nothing is exported before each renderer's terms are checked (the user's item 16): "
                      + "; ".join(refused))
    other = sorted(d.doc_id for _, d in entries if d.mode != mode)
    if other:
        raise ValueError(("a pipeline-test document is excluded from any corpus of record" if mode == modes.RECORD else
                          "a pipeline test places only its own documents") + f", and {', '.join(other)} is not one")
    for base_id, split in sorted(assignment.items()):
        if split in OUT_OF_BOUNDS[mode]:
            raise ValueError(f"a pipeline-test document never enters a sealed or judged split, and base {base_id} is "
                             f"assigned the {split} split")
    bases: dict[str, list[tuple[Skeleton, Document]]] = {}
    for skeleton, document in entries:
        bases.setdefault(skeleton.base_id, []).append((skeleton, document))
    if set(bases) != set(assignment):
        raise ValueError("every base with documents is assigned a split, and every assigned base has documents")
    for base_id, members in bases.items():
        variants = sorted(d.variant for _, d in members)
        if variants.count("consistent") != 1 or "planted" not in variants:
            raise ValueError(f"base {base_id}: a consistent twin and its planted variants are placed together")
        refused = [d.doc_id for _, d in members if not (verdicts.get(d.doc_id) and verdicts[d.doc_id].accepted)]
        if refused:
            raise ValueError(f"base {base_id}: only accepted documents are placed, and {', '.join(refused)} is not")
    plans, folders = [], {}
    for split in SPLITS:
        members = [m for b, ms in sorted(bases.items()) if assignment[b] == split for m in ms]
        if members:
            folder = destination(split, version, mode=mode, data_dir=data_dir, sealed=sealed, judged=judged)
            plans.append((split, folder, members))
            folders.setdefault(folder, []).append(split)
    mine = _canaries([split for split, _, _ in plans], canaries)
    for split, folder, members in plans:
        records = [record(s, d, canary=mine[split], reviewers=(reviewers or {}).get(d.doc_id, ()),
                          decisions=decisions) for s, d in members]
        write_split(folder, split, records, license=license, canary=mine[split])
        write_skeletons(folder, split, [s for s, _ in members], canary=mine[split])
    for folder, splits in folders.items():
        write_readme(folder, corpus_version=version, splits=splits, mode=mode, license=license, canaries=mine)
        write_license(folder, splits=splits, license=license, canaries=mine)
    return {split: folder for split, folder, _ in plans}
