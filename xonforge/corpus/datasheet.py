"""The datasheet (XONFORGE_SPEC.md §12), after "Datasheets for Datasets" (Gebru et al., 2018): motivation, composition,
generation process, providers used, review and calibration results, known issues, splits and sealing, recommended and
discouraged uses, and the license. Generated from the export records, without any document text or the sealed and
judged splits' canary strings (only their SHA-256), so that it can be committed. The fixed wording paraphrases the
spec (§1, §5 to §9, §15); everything else is counted from the records. A pipeline test's datasheet (xonforge/modes.py)
opens with a section saying that it is not a corpus of record.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

from xonforge import modes
from xonforge.review.calibration import CanaryScore

from .export import LICENSE, NOTICE, OUT_OF_BOUNDS, PIPELINE_TEST_NOTICE, SPLITS, ExportRecord
from .seal import canary_sha256

IN_REPOSITORY = ("development", "calibration")


def _counts(counter: Counter) -> str:
    return ", ".join(f"{k}: {v}" for k, v in sorted(counter.items())) if counter else "none"


def _canary_line(split: str, canary: str) -> str:
    if split in IN_REPOSITORY:
        return f"- Canary string of the {split} split, in each of its files and its README: `{canary}`."
    return (f"- Canary string of the {split} split: its SHA-256 is `{canary_sha256(canary)}`; the string itself is "
            "only in the split's own files.")


def datasheet(*, corpus_version: str, date: str, mode: str, records: Mapping[str, Sequence[ExportRecord]],
              canaries: Mapping[str, str], license: str = LICENSE, manifest_hash: str | None = None,
              reviewers: Sequence[str] = (), scores: Sequence[CanaryScore] = (),
              known_issues: Sequence[str] = ()) -> str:
    """``mode``: the corpus's mode, which every record must have; ``records``: each split's export records;
    ``canaries``: each of those splits' canary string."""
    modes.check(mode)
    unknown = sorted(set(records) - set(SPLITS))
    if unknown:
        raise ValueError(f"the splits are {', '.join(SPLITS)}, not {', '.join(unknown)}")
    placed = [s for s in SPLITS if records.get(s)]
    if [s for s in placed if not canaries.get(s)] or len(set(canaries.values())) != len(canaries):
        raise ValueError("each split has a canary string of its own")
    if any(r.canary != canaries[s] for s in placed for r in records[s]):
        raise ValueError("every record carries its split's canary string")
    every = [r for split in SPLITS for r in records.get(split, ())]
    if any(r.mode != mode for r in every):
        raise ValueError("a datasheet covers one corpus, whose records are all of its mode: a pipeline-test document "
                         "is excluded from any corpus of record")
    barred = [s for s in OUT_OF_BOUNDS[mode] if records.get(s)]
    if barred:
        raise ValueError(f"a pipeline-test document never enters a sealed or judged split, and records are given for "
                         f"{', '.join(barred)}")
    test = mode == modes.PIPELINE_TEST
    if test and manifest_hash:
        raise ValueError("a pipeline test has no sealed split, so no manifest hash")
    words = [r.difficulty.get("measured", {}).get("words") for r in every]
    words = [w for w in words if w is not None]
    decisions = Counter(d.decision for r in every for d in r.decisions)
    uncovered: Counter = Counter()
    untrusted: Counter = Counter()
    for r in every:
        for s in r.scans:
            if s.uncovered:
                uncovered[f"the {s.scan} scan has no pattern for {', '.join(s.uncovered)}"] += 1
            if s.result == "clean" and not s.trusted:
                untrusted[s.scan] += 1
    issues = list(known_issues)
    issues += [f"{what}, in {n} document{'s' if n != 1 else ''}" for what, n in sorted(uncovered.items())]
    issues += [f"the {scan} scan's clean results are not trusted (it has not caught every canary registered for "
               f"it), in {n} document{'s' if n != 1 else ''}" for scan, n in sorted(untrusted.items())]
    head = [f"# Datasheet: XonForge corpus {corpus_version}", "", f"Generated {date}. {NOTICE}", ""]
    head += ["## Pipeline test", "", PIPELINE_TEST_NOTICE, ""] if test else []
    lines = ["## Motivation", "",
             "The corpus tests contradiction detection in documents: whether a method finds the contradiction planted "
             "in a document, and leaves alone a document whose facts fit together. Its ground truth comes from a "
             "solver over each document's skeleton rather than from any model; its documents are written by several "
             "model families and reviewed blind by others, and its test split is sealed before use.", "",
             "## Composition", "",
             f"- Documents: {len(every)}, from {len({r.base_id for r in every})} base skeletons.",
             f"- By split: {_counts(Counter({s: len(records[s]) for s in records if records[s]}))}.",
             f"- By variant: {_counts(Counter(r.variant for r in every))}.",
             f"- By plant type: {_counts(Counter(r.plant['type'] for r in every if r.plant))}.",
             f"- By genre: {_counts(Counter(r.genre for r in every))}.",
             f"- Words per document: {min(words)} to {max(words)}, {sum(words) / len(words):.0f} on average."
             if words else "- Words per document: not measured.",
             "", "Each base has a consistent twin, whose facts can all be true, and planted variants, which differ "
             "from it only in their planted facts; each document's fact→span map gives the sentence of every fact.",
             "", "## Generation process", "",
             "Skeletons are generated and checked by the solver, and discarded unless the consistent twin's facts can "
             "all be true and each planted variant's required facts are its only minimal contradiction. A model "
             "renders each skeleton into prose with a fact→span map, in up to five attempts, each failed check "
             "quoted back. Deterministic structural checks and scans verify each rendering; models from other "
             "providers review it blind; flagged documents go to a human, whose decisions are logged in a hash "
             "chain; and only accepted documents enter the corpus."
             + (" In this pipeline test the reviewers were not required to be of other providers than the renderer, "
                "only other models." if test else ""), "",
             "## Providers used", "",
             f"- Renderers: {_counts(Counter(f'{r.renderer.provider} {r.renderer.model}' for r in every))}.",
             f"- Reviewers: {', '.join(reviewers) if reviewers else 'none recorded'}.", "",
             "## Review and calibration results", ""]
    lines += [f"- {s.reviewer}, batch {s.batch_id}: recall "
              f"{f'{s.caught}/{s.defects}' if s.defects else 'not measured (no defect canary)'}, false alarms "
              f"{f'{s.false_alarms}/{s.clean}' if s.clean else 'not measured (no clean canary)'}." for s in scores]
    lines += [] if scores else ["- No canary scores are recorded."]
    lines += [f"- Human decisions: {_counts(decisions)}.",
              f"- Documents with flags: {sum(1 for r in every if r.flags)}.", "",
              "## Known issues", ""]
    lines += [f"- {i}" for i in issues] or ["- None recorded."]
    bases = Counter({s: len({r.base_id for r in records[s]}) for s in records if records[s]})
    sealing = ("none: a pipeline test has no sealed or judged split" if test else
               f"`{manifest_hash}`" if manifest_hash else "not sealed yet")
    lines += ["", "## Splits and sealing", "",
              f"- Bases by split: {_counts(bases)}.",
              f"- Test split manifest hash: {sealing}."]
    lines += [_canary_line(s, canaries[s]) for s in placed]
    lines += ["", "## Recommended and discouraged uses", "",
              "- Recommended: testing XonForge's pipeline; this is not a corpus of record." if test else
              "- Recommended: evaluating and comparing contradiction-detection methods, building them on the "
              "development split, setting their thresholds on the calibration split, and reporting final results on "
              "the sealed test split.",
              "- Discouraged: training or tuning models on any split; tuning on the test split; mixing the judged "
              "split into test results; drawing conclusions beyond the plant types, genres and providers the corpus "
              "covers.", "",
              "## License", "",
              license, ""]
    return "\n".join(head + lines)


def write(folder: str | Path, sheet: str) -> Path:
    """Writes the corpus's DATASHEET.md, once."""
    path = Path(folder) / "DATASHEET.md"
    if path.exists():
        raise FileExistsError(f"{path} is already written")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sheet, encoding="utf-8", newline="\n")
    return path
