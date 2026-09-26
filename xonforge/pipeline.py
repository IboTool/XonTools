"""The sample run (XONFORGE_SPEC.md §14, step 7): render a 20-document sample, review it blind, and stop.

The run is the pipeline-test configuration ``sample``. It logs its seeds, generates the bases, renders each consistent
twin and derives its planted variant, reviews the documents that have text, and queues the result for a human. It does
not accept, export, split or seal anything, and it does not start the first corpus. A second invocation of the same
run continues from the documents, batches and response cache already stored outside the repository.

The composition, the token caps and the choice that each reviewer runs both prompts were open (xonforge/docs/decisions.md).
They are fixed for this run in ``sample_bases`` and in the ``sample`` caps of config/defaults.yaml, and logged in
CHANGELOG_EXPERIMENTS.md (2026-09-26).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from xon_common.budget import BudgetPaused

from . import estimate as estimates
from . import locations, registry
from .estimate import BaseSpec
from .levels import draw
from .render.renderer import derive, doc_id, render
from .render.rotation import Rotation
from .render.store import DocumentStore
from .review import blind, calibration, outcome, queue
from .review.blind import BatchStore
from .review.decisions import DecisionLog
from .review.outcome import plant_sentences
from .review.queue import QueueStore
from .review.reviewers import select
from .skeleton.generators import generate
from .skeleton.schema import Base, Skeleton
from .solver import check_base
from .verify.canaries import load as load_scan_canaries, trust
from .verify.checks import check, finalize
from .waiting import Waiting

GENRE = "office memo"
SAMPLE_BASES = 10
SAMPLE_LEVEL = 1
# Logged once, before generation: the spot-check seed, then the quota and split seeds (items 10, 13 and 15). The
# sample is not split; the quota and split seeds are logged because the protocol logs them before generation.
SEEDS = (("sample_seed", 1), ("quota_seed", 2), ("split_seed", 3))
CONSTRAINTS = locations.ROOT / "constraints.txt"


def sample_bases() -> list[BaseSpec]:
    """Ten level-1 bases, dealt in turn across v0's four plant types, seeds 1 through 10.

    Each base is one consistent twin and one planted variant, so the run is 20 documents. A twin counts as a document.
    No trap variant, which would make a binary-parity base a third document. The fact audit is v1 and does not run.
    """
    types = ("order_cycle", "equality_break", "binary_parity", "direct_negation")
    return [BaseSpec(types[i % len(types)], SAMPLE_LEVEL, i + 1) for i in range(SAMPLE_BASES)]


def constraints_sha256() -> str:
    return hashlib.sha256(CONSTRAINTS.read_bytes()).hexdigest()


@dataclass
class RunReport:
    run: str
    status: str
    detail: str
    documents: int = 0
    rendered: int = 0
    failed: int = 0
    not_derived: tuple[str, ...] = ()
    queued: int = 0
    spot_checks: int = 0
    spent: dict[str, tuple[int, float]] = field(default_factory=dict)
    scores: tuple[str, ...] = ()
    packet: str | None = None
    constraints: str = ""

    def text(self) -> str:
        rows = [f"{name}: {tokens:,} tokens, ${usd:,.4f}" for name, (tokens, usd) in self.spent.items()]
        total_t = sum(t for t, _ in self.spent.values())
        total_d = sum(d for _, d in self.spent.values())
        lines = [
            f"XonForge sample run {self.run}: {self.status}.",
            self.detail,
            f"Documents: {self.documents} attempted, {self.rendered} rendered, {self.failed} failed"
            + (f", {len(self.not_derived)} not derived ({', '.join(self.not_derived)})" if self.not_derived else "")
            + ".",
            f"Queue: {self.queued} documents, of which {self.spot_checks} are spot checks of unflagged documents.",
            f"Spent: {total_t:,} tokens, ${total_d:,.4f}.",
            *(f"  {row}" for row in rows),
            *(f"Review: {s}" for s in self.scores),
            f"constraints.txt SHA-256: {self.constraints}.",
        ]
        if self.packet:
            lines.append(f"Review packet (outside the repository): {self.packet}")
        lines.append("Stopped for review. Nothing was accepted, exported, split or sealed.")
        return "\n".join(lines)


class _Manifest:
    """Run state that holds no document text: the composition, the renderer assigned to each base, and the status."""

    def __init__(self, root: Path, run: str):
        self.path = root / f"{run}.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"run": run}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)


class _Bases:
    def __init__(self, root: Path):
        self.root = locations.outside_worktrees(root, "skeleton store")

    def path(self, run: str, stem: str) -> Path:
        return self.root / run / f"{stem}.json"

    def load(self, run: str, stem: str) -> Base | None:
        path = self.path(run, stem)
        return Base.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def save(self, run: str, stem: str, base: Base) -> None:
        path = self.path(run, stem)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(base.model_dump_json(indent=1), encoding="utf-8")
        os.replace(tmp, path)


def _stem(spec: BaseSpec) -> str:
    return f"{spec.plant_type}-L{spec.level}-{spec.seed}"


def _variants(base: Base) -> list[Skeleton]:
    return [base.consistent, *base.planted, *base.trap_only]


def _ensure_seeds(log: DecisionLog, run: str) -> None:
    for kind, seed in SEEDS:
        if log.seed(run, kind) is None:
            log.log_seed(run, seed, kind)


def _specs(manifest: _Manifest, bases: list[BaseSpec] | None) -> list[BaseSpec]:
    saved = manifest.data.get("composition")
    if saved:
        return [BaseSpec(**row) for row in saved]
    return list(bases) if bases is not None else sample_bases()


def _prepare(session: registry.Session, manifest: _Manifest, store: _Bases, specs: list[BaseSpec]) -> list[Base]:
    _ensure_seeds(DecisionLog(), session.run)
    defaults = session.defaults
    share = defaults["skeletons"]["negation_premise_share"]
    genre = manifest.data.get("genre", GENRE)
    made = []
    for spec in specs:
        stem = _stem(spec)
        base = store.load(session.run, stem)
        if base is None:
            knobs, _rules = draw(spec.level, spec.plant_type, spec.seed)
            traps = ("arity_control",) if spec.trap else ()
            base = generate(spec.plant_type, seed=spec.seed, genre=genre, knobs=knobs, level=spec.level,
                            traps=traps, premise_share=share if spec.plant_type == "direct_negation" else None)
            problems = check_base(base)
            if problems:
                raise RuntimeError(f"{base.base_id} fails the solver before any call: {'; '.join(problems)}")
            store.save(session.run, stem, base)
        made.append(base)
    if not manifest.data.get("composition"):
        manifest.data.update(composition=[
            {"plant_type": s.plant_type, "level": s.level, "seed": s.seed, "trap": s.trap} for s in specs],
            genre=genre, constraints_sha256=constraints_sha256(), status="rendered-not-yet")
        manifest.save()
    return made


def _rules_for(spec: BaseSpec):
    return draw(spec.level, spec.plant_type, spec.seed)[1]


def _render_all(session: registry.Session, manifest: _Manifest, bases: list[Base], specs: list[BaseSpec],
                documents: DocumentStore) -> tuple[list, list[str]]:
    config, defaults = session.config, session.defaults
    assert config is not None
    max_tokens = int(defaults["render"]["max_tokens"])
    params = defaults["render"]["params"] or None
    scan_trust = trust(load_scan_canaries())
    out, skipped = [], []
    assignments = dict(manifest.data.get("assignments") or {})
    rotation = Rotation(config.renderers)
    for spec, base in zip(specs, bases):
        stem = _stem(spec)
        if stem not in assignments:
            existing = documents.load(session.run, doc_id(base.consistent))
            if existing is None:
                assignments[stem] = rotation.next()
            else:
                assignments[stem] = existing.renderer.entry
                rotation.counts[existing.renderer.entry] += 1
        else:
            rotation.counts[assignments[stem]] += 1
    manifest.data["assignments"] = assignments
    manifest.save()
    for spec, base in zip(specs, bases):
        stem = _stem(spec)
        name = assignments[stem]
        caller = session.caller(name)
        rules = _rules_for(spec)
        twin = documents.load(session.run, doc_id(base.consistent))
        if twin is None:
            print(f"rendering {base.base_id} ({name})", flush=True)
            twin = finalize(base.consistent, render(
                base.consistent, rules, caller, check=check, max_tokens=max_tokens, mode=config.mode, params=params,
                thinking=True), scan_trust)
            documents.save(session.run, twin)
        out.append((base.consistent, twin))
        by_id = {doc_id(base.consistent): twin}
        for skeleton in base.planted + base.trap_only:
            saved = documents.load(session.run, doc_id(skeleton))
            if saved is not None:
                out.append((skeleton, saved))
                by_id[saved.doc_id] = saved
                continue
            source_id = doc_id(base.consistent if skeleton.variant == "planted" else base.planted[0])
            source = by_id.get(source_id)
            if source is None or source.status != "rendered" or source.text is None:
                skipped.append(doc_id(skeleton))
                print(f"not derived: {doc_id(skeleton)} (its source did not render)", flush=True)
                continue
            print(f"deriving {doc_id(skeleton)}", flush=True)
            made = finalize(skeleton, derive(
                skeleton, _source_skeleton(base, source), source, caller, check=check, max_tokens=max_tokens,
                mode=config.mode, params=params, thinking=True), scan_trust)
            documents.save(session.run, made)
            out.append((skeleton, made))
            by_id[made.doc_id] = made
    return out, skipped


def _source_skeleton(base: Base, document) -> Skeleton:
    for skeleton in _variants(base):
        if doc_id(skeleton) == document.doc_id:
            return skeleton
    raise RuntimeError(f"{document.doc_id} is not a variant of {base.base_id}")


def _review(session: registry.Session, pairs: list[tuple[Skeleton, object]]) -> list:
    config = session.config
    assert config is not None
    defaults = session.defaults
    max_tokens = int(defaults["render"]["max_tokens"])
    params = defaults["render"]["params"] or None
    prompts = tuple(blind.PROMPTS)
    pool = calibration.load()
    canaries = {c.id: c for c in pool}
    usable = [(sk, doc) for sk, doc in pairs if doc.text]
    if not usable:
        return []
    k = int(defaults["review"]["k"])
    seed = DecisionLog().seed(session.run) or SEEDS[0][1]
    batches, outcomes = BatchStore(), []
    by_renderer: dict[str, list] = {}
    for pair in usable:
        by_renderer.setdefault(pair[1].renderer.entry, []).append(pair)
    for renderer, group in by_renderer.items():
        reviewers = [e.name for e in select(session.entries[renderer], [session.entries[n] for n in config.reviewers],
                                            k, mode=config.mode)]
        ids = [doc.doc_id for _, doc in group]
        for reviewer in reviewers:
            for index, prompt_name in enumerate(prompts):
                for start in range(0, len(ids), blind.MAX_DOCUMENTS):
                    chunk = ids[start:start + blind.MAX_DOCUMENTS]
                    batch_id = f"{renderer}-{reviewer}-{prompt_name}-{start // blind.MAX_DOCUMENTS}"
                    batch = batches.load(session.run, batch_id)
                    if batch is None:
                        attributes = {a.key for sk, doc in group if doc.doc_id in chunk for a in sk.attributes}
                        batch = blind.batch_for(session.run, batch_id, chunk, pool, attributes,
                                                seed + index + start, reviewer=reviewer, prompt=prompt_name)
                        batches.save(batch)
                    print(f"reviewing {batch.batch_id} ({len(batch.items)} items)", flush=True)
                    texts = {doc.doc_id: doc.text for _, doc in group if doc.doc_id in chunk}
                    texts.update({c: canaries[c].text for c in canaries})
                    results = blind.review(batch, texts, prompt_name, session.caller(reviewer), max_tokens=max_tokens,
                                           params=params, thinking=True)
                    plants = {doc.doc_id: plant_sentences(sk, doc) for sk, doc in group if doc.doc_id in chunk}
                    outcomes.append(outcome.outcome(batch, results, plants=plants, canaries=canaries))
    return outcomes


def _packet(path: Path, pairs, items, scores: list[str]) -> None:
    reasons = {i.doc_id: i.reasons for i in items}
    lines = ["# XonForge 20-document sample, for review", "",
             "Pipeline test. These documents are not a corpus of record and are not sealed.", ""]
    lines += [s for s in scores]
    lines.append("")
    for skeleton, doc in pairs:
        lines += [f"## {doc.doc_id}", "",
                  f"Variant: {doc.variant}. Status: {doc.status}. Level: {doc.rules.level}. "
                  f"Words aimed at: {doc.rules.words}.",
                  f"Flags: {'; '.join(doc.flags) if doc.flags else 'none'}.",
                  f"Queue: {'; '.join(reasons.get(doc.doc_id, ())) or 'not queued'}.", ""]
        lines += ["```", doc.text or "(no text)", "```", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _spent(session: registry.Session) -> dict[str, tuple[int, float]]:
    assert session.config is not None
    return {name: session.budget.spent(name) for name in session.config.entries}


def _scores(outcomes) -> list[str]:
    return [f"{o.reviewer} / {o.prompt}: recall {o.score.caught}/{o.score.defects}, "
            f"false alarms {o.score.false_alarms}/{o.score.clean}, "
            f"{'certifiable' if o.certifiable else 'not certifiable'}"
            for o in outcomes]


def execute(session: registry.Session, bases: list[BaseSpec] | None = None) -> RunReport:
    """Run the sample, or continue it, and stop for review. ``bases`` replaces the sample composition (tests)."""
    if session.config is None or session.config.name != "sample":
        raise Waiting("This gate runs only the 20-document sample. The first corpus waits until that sample has been "
                      "reviewed.")
    root = locations.text_log_dir() / "runs"
    manifest, store = _Manifest(locations.outside_worktrees(root, "run record"), session.run), _Bases(
        locations.text_log_dir() / "skeletons")
    documents = DocumentStore()
    specs = _specs(manifest, bases)
    if bases is None and not manifest.data.get("composition") and len(specs) != SAMPLE_BASES:
        raise RuntimeError(f"the sample is {SAMPLE_BASES} bases, not {len(specs)}")
    prepared = _prepare(session, manifest, store, specs)
    variants = sum(len(_variants(b)) for b in prepared)
    if bases is None and variants != 20:
        raise RuntimeError(f"the sample is 20 documents, and these bases have {variants}")
    settings = session.defaults["estimate"]
    assert session.config is not None
    planned = estimates.plan(specs, renderers=session.config.renderers, reviewers=session.config.reviewers,
                             review_prompts=tuple(blind.PROMPTS), attempts=1,
                             thinking=settings["thinking_per_call"],
                             premise_share=session.defaults["skeletons"]["negation_premise_share"], genre=GENRE)
    priced = [estimates.usd(t, session.entries[name], settings) for name, t in planned.tallies.items()]
    total = sum(p or 0 for p in priced)
    print(f"Estimate at first attempts, with the assumed thinking: ${total:,.2f}. "
          f"Run cap: ${session.config.caps.run_usd:,.2f}.", flush=True)
    report = RunReport(run=session.run, status="paused", detail="", constraints=constraints_sha256())
    skipped: list[str] = []
    try:
        pairs, skipped = _render_all(session, manifest, prepared, specs, documents)
    except BudgetPaused as exc:
        report.detail = f"Paused while rendering: {exc}"
        report.spent = _spent(session)
        report.not_derived = tuple(skipped)
        manifest.data["status"] = "paused-rendering"
        manifest.save()
        return report
    try:
        outcomes = _review(session, pairs)
    except BudgetPaused as exc:
        report.detail = f"Paused while reviewing: {exc}"
        report.documents = len(pairs) + len(skipped)
        report.rendered = sum(doc.status == "rendered" for _, doc in pairs)
        report.failed = sum(doc.status != "rendered" for _, doc in pairs)
        report.not_derived = tuple(skipped)
        report.spent = _spent(session)
        manifest.data["status"] = "paused-reviewing"
        manifest.save()
        return report
    flags = outcome.reviewer_flags([doc.doc_id for _, doc in pairs], outcomes, session.config.reviewers,
                                   tuple(blind.PROMPTS))
    items = queue.queue(session.run, [doc for _, doc in pairs], flags, DecisionLog(), sample=True)
    QueueStore().save(session.run, items)
    scores = _scores(outcomes)
    packet = locations.text_log_dir() / "runs" / f"{session.run}-review.md"
    _packet(packet, pairs, items, scores)
    spot = sum(all(r.startswith("drawn for a spot check") for r in i.reasons) for i in items)
    manifest.data["status"] = "stopped-for-review"
    manifest.save()
    return RunReport(run=session.run, status="stopped for review",
                     detail="The 20-document sample is queued for a human. It is a pipeline test.",
                     documents=len(pairs) + len(skipped),
                     rendered=sum(doc.status == "rendered" for _, doc in pairs),
                     failed=sum(doc.status != "rendered" for _, doc in pairs),
                     not_derived=tuple(skipped), queued=len(items), spot_checks=spot, spent=_spent(session),
                     scores=tuple(scores), packet=str(packet), constraints=constraints_sha256())
