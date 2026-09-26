"""One run, from skeletons to the queue (XONFORGE_SPEC.md §14). ``python -m xonforge run NAME`` calls ``execute``.

It refuses unless the run's check passes (the caller builds the session, and a session with a failing check is
refused). A dry run replays the response cache and sends no call. A document already in the store, for the same
skeleton, is kept, so a resumed run does not render it again. Pipeline-test documents are labelled with the run's
mode. This command does not split or seal them.
"""
from __future__ import annotations

from xon_common.providers.base import DryRunMissing

from . import registry
from .corpus.acceptance import accept
from .levels import draw
from .render.renderer import derive, doc_id, render
from .render.store import DocumentStore
from .review.decisions import DecisionLog
from .review.queue import queue as build_queue
from .skeleton.generators import generate
from .skeleton.schema import Skeleton
from .solver import check_base
from .verify.audit import audit, disagreements
from .verify.canaries import load as load_canaries
from .verify.canaries import trust as scan_trust
from .verify.checks import check, finalize


def execute(session: registry.Session, specs, *, genre: str, seed: int, premise_share: float,
            audit_facts: bool = False) -> dict:
    """Render each base in ``specs`` (estimate.BaseSpec), then queue what was stored and say whether each document
    would be accepted. The fact audit runs only when ``audit_facts`` is set, and the sample leaves it off."""
    config = session.config
    if config is None:
        raise ValueError("a run names its configuration")
    renderer_name = config.renderers[0]
    caller = session.caller(renderer_name)
    rules_cap = int(session.defaults["render"]["retry_cap"])
    max_tokens = int(session.defaults["render"]["max_tokens"])
    store, log = DocumentStore(), DecisionLog()
    if log.seed(config.name) is None:
        log.log_seed(config.name, seed)
    trust = scan_trust(load_canaries())
    misses: list[str] = []
    documents = []
    skeletons: dict[str, Skeleton] = {}
    for spec in specs:
        knobs, rules = draw(spec.level, spec.plant_type, spec.seed)
        rules = rules.model_copy(update={"retry_cap": rules_cap})
        traps = ("arity_control",) if spec.trap and spec.plant_type == "binary_parity" else ()
        base = generate(spec.plant_type, seed=spec.seed, genre=genre, knobs=knobs, level=spec.level, traps=traps,
                        premise_share=premise_share if spec.plant_type == "direct_negation" else None)
        problems = check_base(base)
        if problems:
            raise ValueError(f"{base.base_id} does not pass the solver: {'; '.join(problems)}")
        made = _variants(config.name, base, store, caller, rules, max_tokens, config.mode, trust, misses)
        for skeleton, document in made:
            skeletons[document.doc_id] = skeleton
            documents.append(document)
    audits = (audit_documents(session, documents, skeletons, renderer=renderer_name, max_tokens=max_tokens)
              if audit_facts else {})
    items = build_queue(config.name, documents, {}, log, sample=(config.mode == "pipeline_test"), audit_flags=audits)
    verdicts = [accept(skeletons[d.doc_id], d, mode=config.mode, trust=trust, queued=d.doc_id in {i.doc_id for i in items})
                for d in documents]
    return {"documents": documents, "queue": items, "verdicts": verdicts, "misses": misses,
            "run": config.name, "mode": config.mode}


def _variants(run, base, store, caller, rules, max_tokens, mode, trust, misses):
    """(skeleton, document) for the twin and, when the twin rendered, each planted and trap variant."""
    twin_doc = _one(run, base.consistent, store, lambda: render(
        base.consistent, rules, caller, check=check, max_tokens=max_tokens, mode=mode), trust, misses)
    out = [(base.consistent, twin_doc)]
    if twin_doc.status != "rendered":
        return out
    for skeleton in (*base.planted, *base.trap_only):
        source = base.consistent if skeleton.variant == "planted" else base.planted[0]
        document = next(d for s, d in out if s.variant == source.variant and d.status == "rendered")
        made = _one(run, skeleton, store, lambda s=skeleton, src=source, d=document: derive(
            s, src, d, caller, check=check, max_tokens=max_tokens, mode=mode), trust, misses)
        out.append((skeleton, made))
        if made.status != "rendered" and skeleton.variant == "planted":
            break
    return out


def _one(run, skeleton, store, build, trust, misses):
    stored = store.load(run, doc_id(skeleton))
    if stored is not None and stored.skeleton_digest == skeleton.digest():
        return stored
    try:
        document = build()
    except DryRunMissing as exc:
        misses.append(str(exc))
        raise
    document = finalize(skeleton, document, trust)
    store.save(run, document)
    return document


def audit_documents(session, documents, skeletons: dict, *, renderer: str, max_tokens: int) -> dict[str, tuple[str, ...]]:
    """Disagreements between the fact auditor and each document's fact-to-span map. The auditor is the run's first
    reviewer, who is not the renderer."""
    if session.config is None or not session.config.reviewers:
        return {}
    caller = session.caller(session.config.reviewers[0])
    out = {}
    for document in documents:
        skeleton = skeletons.get(document.doc_id)
        if skeleton is None or document.text is None:
            continue
        found = audit(skeleton, document, caller, renderer=renderer, max_tokens=max_tokens)
        flags = disagreements(skeleton, document, found)
        if flags:
            out[document.doc_id] = tuple(flags)
    return out
