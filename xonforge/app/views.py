"""What each dashboard page shows (XONFORGE_SPEC.md §10). Pure data: no Streamlit, no API call, no key.

A draft of the configure page is a file the dashboard may write outside the repository. Runs keep loading
``defaults.yaml``. The sample's caps and the check constants are not changed here. Export and seal stay refused
while the documents are a pipeline test or a renderer's terms are unchecked, and the first corpus is not started.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from xonforge import locations, registry, runs
from xonforge.corpus import splits, terms
from xonforge.corpus.export import PIPELINE_TEST_NOTICE
from xonforge.corpus.quotas import NO_TRAP, plan as quota_plan, quotas as quota_counts
from xonforge.review.decisions import DecisionLog
from xonforge.review.queue import SAMPLE_MIN, SHARE
from xonforge.skeleton.catalog import JUDGED_PLANTS, TRAPS, V1_PLANT_TYPES
from xonforge.skeleton.generators import PLANT_TYPES

PAGES = ("Configure", "Providers", "Run", "Review queue", "Quality", "Corpus", "Logs")
TARGET_DEFAULT = 300
GENRES = ("office memo",)
DECISIONS = ("accept", "regenerate", "discard")
DATASHEET_SECTIONS = (
    "Motivation", "Composition", "Generation process", "Providers used", "Review and calibration results",
    "Known issues", "Splits and sealing", "Recommended and discouraged uses", "License",
)
# Preview of the quota table only. A corpus run logs its own quota seed before generation.
PREVIEW_SEED = 2


def flatten(value) -> str:
    """Every string a page would show, for the check that a key's value is not among them."""
    if isinstance(value, dict):
        return " ".join(flatten(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(flatten(v) for v in value)
    return "" if value is None else str(value)


def default_draft(defaults: dict | None = None) -> dict:
    """The configure form as the committed defaults and the spec's target leave it."""
    defaults = defaults if defaults is not None else registry.load_defaults()
    sample = defaults.get("runs", {}).get("sample", {})
    return {
        "target": TARGET_DEFAULT,
        "plant_types": list(PLANT_TYPES),
        "traps": [],
        "levels": [1, 2, 3],
        "genres": list(GENRES),
        "providers": list(sample.get("renderers") or []),
        "review_k": int(defaults["review"]["k"]),
        "development": 50,
        "calibration": 15,
        "test": 35,
    }


def validate_draft(draft: Mapping) -> list[str]:
    """What is wrong with a configure draft; empty when it may be saved."""
    problems = []
    target = draft.get("target")
    if isinstance(target, bool) or not isinstance(target, int) or target < 1:
        problems.append(f"the target size is a whole number of at least 1, not {target!r}")
    known = set(PLANT_TYPES) | set(V1_PLANT_TYPES)
    plants = list(draft.get("plant_types") or [])
    if not plants or any(p not in known for p in plants):
        problems.append(f"plant types are chosen from {', '.join([*PLANT_TYPES, *V1_PLANT_TYPES])}")
    unknown_traps = [t for t in draft.get("traps") or [] if t not in TRAPS]
    if unknown_traps:
        problems.append(f"traps are chosen from {', '.join(TRAPS)}")
    levels = list(draft.get("levels") or [])
    if not levels or any(level not in (1, 2, 3) for level in levels):
        problems.append("the difficulty levels are 1, 2 and 3")
    genres = list(draft.get("genres") or [])
    if not genres or any(not isinstance(g, str) or not g.strip() for g in genres):
        problems.append("a genre is a non-empty name")
    k = draft.get("review_k")
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        problems.append(f"the number of reviewers is a whole number of at least 1, not {k!r}")
    shares = [draft.get("development"), draft.get("calibration"), draft.get("test")]
    if any(isinstance(s, bool) or not isinstance(s, int) or s < 0 for s in shares) or sum(shares) != 100:
        problems.append("the development, calibration and test shares are percentages and sum to 100")
    return problems


def save_draft(path: str | Path, draft: Mapping) -> Path:
    """Write a configure draft outside every worktree. The committed defaults are not touched."""
    found = validate_draft(draft)
    if found:
        raise ValueError("; ".join(found))
    dest = locations.outside_worktrees(path, "dashboard draft")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump(dict(draft), sort_keys=False), encoding="utf-8")
    return dest


def load_draft(path: str | Path) -> dict:
    draft = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    found = validate_draft(draft)
    if found:
        raise ValueError("; ".join(found))
    return draft


def constants(defaults: dict | None = None) -> dict:
    """The constants the checks use. The dashboard shows them and does not write them."""
    defaults = defaults if defaults is not None else registry.load_defaults()
    render = defaults["render"]
    return {
        "min_spacing": render["min_spacing"],
        "retry_cap": render["retry_cap"],
        "length_tolerance": render["length_tolerance"],
        "max_tokens": render["max_tokens"],
        "canary_share": f"{SHARE.numerator}/{SHARE.denominator}",
        "sample_spot_checks_at_least": SAMPLE_MIN,
        "negation_premise_share": defaults["skeletons"]["negation_premise_share"],
        "split_proportions": {name: int(fraction * 100) for name, fraction in splits.PROPORTIONS.items()},
        "judged_plants": list(JUDGED_PLANTS),
    }


def quota_preview(draft: Mapping) -> list[dict]:
    """The draft's quota cells. A unit's meaning, a document or a base, is still open; the count is units."""
    found = validate_draft(draft)
    if found:
        raise ValueError("; ".join(found))
    plants = [p for p in draft["plant_types"] if p not in JUDGED_PLANTS]
    if not plants:
        return []
    traps = list(draft["traps"])
    units = quota_plan(
        draft["target"], plant_types=plants, levels=draft["levels"],
        providers=draft["providers"] or ["(no renderer)"], genres=draft["genres"],
        traps=([NO_TRAP, *traps] if traps else None), seed=PREVIEW_SEED)
    counts = quota_counts(units)
    return [{"plant_type": cell[0], "level": cell[1], "renderer": cell[2], "units": n}
            for cell, n in sorted(counts.items(), key=lambda kv: repr(kv[0]))]


def provider_rows(defaults: dict | None = None, entries: Sequence | None = None) -> list[dict]:
    """One row per registry entry. ``key`` is present, missing or not needed; the value is never included."""
    defaults = defaults if defaults is not None else registry.load_defaults()
    entries = list(entries) if entries is not None else registry.load_entries()
    adapters = registry.adapters(entries, defaults)
    rows = registry.startup_check(entries, adapters, defaults, test_call=False)
    shown = []
    for row in rows:
        if row["key"] not in ("present", "missing", "not needed"):
            raise RuntimeError(f"the providers page shows whether a key is set, not {row['key']!r}")
        shown.append({k: v for k, v in row.items() if k != "why"})
        shown[-1]["unavailable_because"] = None if row["available"] else row["why"]
    return shown


def terms_rows(path: str | Path | None = None) -> list[dict]:
    checks = terms.load() if path is None else terms.load(path)
    return [{"provider": name,
             "checked": None if item.checked is None else item.checked.isoformat(),
             "allows": item.allows, "sources": list(item.sources), "notes": item.notes}
            for name, item in checks.items()]


def run_status(name: str, defaults: dict | None = None) -> dict:
    """Whether a run configuration may start. No call is made. Only the sample may start at this gate."""
    defaults = defaults if defaults is not None else registry.load_defaults()
    entries = {e.name: e for e in registry.load_entries()}
    try:
        config = runs.load(name, defaults, entries)
    except ValueError as exc:
        return {"name": name, "allowed": False, "problems": [str(exc)], "renderers": [], "reviewers": [],
                "mode": None}
    found = runs.problems(config, entries, registry.adapters(list(entries.values()), defaults),
                          k=int(defaults["review"]["k"]), dry_run=False)
    allowed = name == "sample" and not found
    if name != "sample":
        found = ["This gate runs only the 20-document sample. The first corpus waits until that sample has been "
                 "reviewed.", *found]
    return {"name": name, "allowed": allowed, "problems": found, "mode": config.mode,
            "renderers": list(config.renderers), "reviewers": list(config.reviewers),
            "run_usd": config.caps.run_usd, "run_tokens": config.caps.run_tokens}


def record_decision(log: DecisionLog, run: str, doc_id: str, decision: str, reason: str,
                    reviewer: str | None = None):
    """Append one human decision. A reason is required; the chain is the decision log's."""
    if decision not in DECISIONS:
        raise ValueError(f"a decision is {', '.join(DECISIONS)}, not {decision!r}")
    if not reason or not str(reason).strip():
        raise ValueError("a decision needs a reason")
    return log.decide(run, doc_id, decision, reason.strip(), reviewer)


def queue_statistics(items: Sequence, decisions: Sequence) -> dict:
    """How many queue items are open, decided, or a spot check of an unflagged document."""
    decided = {e.doc_id for e in decisions if e.kind == "decision" and e.doc_id}
    spot = [i for i in items if any(str(r).startswith("drawn for a spot check") for r in i.reasons)]
    return {"queued": len(items), "open": sum(i.doc_id not in decided for i in items),
            "decided": sum(i.doc_id in decided for i in items), "spot_checks": len(spot)}


def fact_rows(skeleton, spans: Mapping[str, str]) -> list[dict]:
    from xonforge.render.phrasing import statement

    return [{"fact": f.id, "statement": statement(f, skeleton), "span": spans.get(f.id, "")}
            for f in skeleton.facts]


def flag_rates(documents: Sequence) -> list[dict]:
    """Flagged documents over documents, per renderer entry."""
    counts: dict[str, list[int]] = {}
    for doc in documents:
        slot = counts.setdefault(doc.renderer.entry, [0, 0])
        slot[0] += 1
        slot[1] += bool(doc.flags) or any(scan.result == "hits" for scan in doc.scans)
    return [{"renderer": name, "documents": docs, "flagged": flagged}
            for name, (docs, flagged) in sorted(counts.items())]


def difficulty_rows(documents: Sequence) -> list[dict]:
    """The difficulty that was set, beside what rendering measured."""
    rows = []
    for doc in documents:
        rows.append({"doc_id": doc.doc_id, "level": doc.rules.level, "words_set": doc.rules.words,
                     "words_measured": doc.measured.get("words"), "explicitness": doc.rules.explicitness,
                     "lexical_variety": doc.rules.lexical_variety,
                     "min_spacing_measured": doc.measured.get("min_spacing")})
    return rows


def score_lines(text: str) -> list[str]:
    """Calibration lines from a review packet. Reading stops at the first document heading, so the document text
    is not part of the result."""
    found = []
    for line in text.splitlines():
        if line.startswith("## "):
            break
        if line.startswith("Review: ") or ("recall " in line and "false alarms" in line):
            found.append(line[len("Review: "):] if line.startswith("Review: ") else line)
    return found


def solver_discard_counts(folder: str | Path) -> dict:
    """Bases in a skeleton folder that fail ``check_base``, and those that do not."""
    from xonforge.skeleton.schema import Base
    from xonforge.solver import check_base

    path = Path(folder)
    kept = discarded = 0
    problems = []
    if not path.is_dir():
        return {"present": False, "kept": 0, "discarded": 0, "problems": []}
    for file in sorted(path.glob("*.json")):
        found = check_base(Base.model_validate_json(file.read_text(encoding="utf-8")))
        if found:
            discarded += 1
            problems.append(f"{file.stem}: {found[0]}")
        else:
            kept += 1
    return {"present": True, "kept": kept, "discarded": discarded, "problems": problems}


def provenance(document, skeleton, decisions: Sequence) -> dict:
    """One document's provenance (§11): skeleton, renderer, attempts, decisions. No key."""
    plant = None
    if skeleton is not None and skeleton.plant is not None:
        plant = skeleton.plant.type
    own = [e for e in decisions if e.kind == "decision" and e.doc_id == document.doc_id]
    return {
        "doc_id": document.doc_id, "base_id": document.base_id, "variant": document.variant,
        "mode": document.mode, "genre": None if skeleton is None else skeleton.genre,
        "seed": None if skeleton is None else skeleton.seed, "plant": plant,
        "skeleton_digest": document.skeleton_digest,
        "renderer": document.renderer.entry, "provider": document.renderer.provider,
        "model": document.renderer.model, "prompt_version": document.renderer.prompt_version,
        "attempts": len(document.attempts),
        "retries": max(0, len(document.attempts) - 1),
        "status": document.status,
        "decisions": [{"decision": e.decision, "reason": e.reason, "time": e.time} for e in own],
    }


def filter_documents(documents: Sequence, *, variant: str | None = None, status: str | None = None,
                     renderer: str | None = None, doc_id: str = "") -> list:
    out = []
    for doc in documents:
        if variant and doc.variant != variant:
            continue
        if status and doc.status != status:
            continue
        if renderer and doc.renderer.entry != renderer:
            continue
        if doc_id and doc_id not in doc.doc_id:
            continue
        out.append(doc)
    return out


def export_refusal(documents: Sequence, checks: Mapping | None = None) -> list[str]:
    """Why the corpus page will not export. Empty only when every document is a corpus of record and every
    renderer's terms allow publishing."""
    if not documents:
        return ["there are no documents to export"]
    reasons = []
    if any(doc.mode == "pipeline_test" for doc in documents):
        reasons.append("a pipeline-test document is excluded from any corpus of record")
    reasons += terms.problems({doc.renderer.provider for doc in documents},
                              terms.load() if checks is None else checks)
    return reasons


def corpus_notice(documents: Sequence) -> str:
    if any(doc.mode == "pipeline_test" for doc in documents):
        return PIPELINE_TEST_NOTICE
    return "Export writes a corpus of record only after each renderer's terms are checked and logged."


def datasheet_preview(documents: Sequence, checks: Mapping | None = None) -> dict:
    """The datasheet's sections, and why nothing is exported yet. The preview holds no document text."""
    return {"sections": list(DATASHEET_SECTIONS), "notice": corpus_notice(documents),
            "refusal": export_refusal(documents, checks)}


def changelog_latest(text: str) -> str:
    """The newest changelog entry: from the first dated heading through the line before the next one."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("## ")), None)
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end]).strip()


def decision_verification(log: DecisionLog) -> dict:
    try:
        count, head = log.verify()
    except Exception as exc:
        return {"ok": False, "detail": str(exc), "entries": 0, "head": None}
    return {"ok": True, "detail": f"{count} entries, head {head}", "entries": count, "head": head}


def call_rows(path: str | Path, *, limit: int = 50) -> list[dict]:
    """The latest call-log rows. The log's own fields hold no document text and no key."""
    from xon_common.calllog import CallLog

    file = Path(path)
    if not file.exists():
        return []
    rows = CallLog(file).rows()[-limit:]
    keep = ("timestamp", "run", "provider", "model", "tag", "attempt", "source", "input_tokens", "output_tokens",
            "thinking_tokens", "cost_usd", "stop_reason", "error", "status")
    return [{k: row.get(k) for k in keep if k in row} for row in rows]


def proportions_of(draft: Mapping) -> dict[str, Fraction]:
    return {"development": Fraction(int(draft["development"]), 100),
            "calibration": Fraction(int(draft["calibration"]), 100),
            "test": Fraction(int(draft["test"]), 100)}
