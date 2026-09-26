"""Render one variant, retrying with the failed checks quoted back (XONFORGE_SPEC.md §6).

A base is rendered twin first (the user's item 2 of 2026-09-25, xonforge/docs/decisions.md): ``render`` writes the
consistent twin from its skeleton, and ``derive`` makes each planted variant from the twin's document, and each trap
variant from its planted variant's, by re-rendering only the sentences of the facts that differ and putting them in
place of the old ones, every other byte of the text kept. The checks run on every text.

Up to the retry cap (5, §5.4) attempts are made. Each attempt is its own cached request (xon_common's attempt number),
so a resumed run replays the same attempts from the cache. A reply that is not a JSON object of the schema, is cut off,
or is declined counts as a failed attempt, quoted back like a failed check; transport retries never count (A1's
policy, CHANGELOG_EXPERIMENTS.md). A document that needed every attempt is flagged for human review, and one whose
last attempt still fails its checks is kept as failed, for a human to regenerate or discard (§7.4).
"""
from __future__ import annotations

from collections import Counter
from typing import Callable, Sequence

from xon_common.caller import Caller
from xon_common.providers.base import OutputInvalid, Refusal, Truncated
from xonforge import modes
from xonforge.skeleton.schema import Skeleton

from . import prompt
from .inferred import inferred_map
from .schema import Attempt, Document, Renderer, Rendering, RenderRules, ReviewProblem, Revisions, SpanEntry

Check = Callable[[Skeleton, Rendering, RenderRules], list[str]]

REPLY_PROBLEMS = {OutputInvalid: "the reply was not a JSON object with the document's text and one span per fact",
                  Truncated: "the reply was cut off before it ended",
                  Refusal: "the reply declined to write the document"}
DERIVE_PROBLEMS = {OutputInvalid: "the reply was not a JSON object with one new sentence per listed fact",
                   Truncated: "the reply was cut off before it ended",
                   Refusal: "the reply declined to write the sentences"}
DERIVED_FROM = {"planted": "consistent", "trap_only": "planted"}   # each derived variant, and what it derives from


def doc_id(skeleton: Skeleton) -> str:
    return f"{skeleton.base_id}-{skeleton.variant}"


def _listed(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _flags(attempts: list[Attempt], problems: list[str], cap: int) -> list[str]:
    flags = [f"needed all {cap} rendering attempts"] if len(attempts) == cap else []
    if problems:
        flags.append(f"still failed after {len(attempts)} attempts: " + "; ".join(problems))
    return flags


def render(skeleton: Skeleton, rules: RenderRules, caller: Caller, *, check: Check, max_tokens: int, mode: str,
           params: dict | None = None, thinking: bool = False, review_problems: Sequence[ReviewProblem] = (),
           previous_text: str | None = None) -> Document:
    """The document of a consistent twin, rendered by ``caller``'s provider entry and checked by ``check``, which
    returns the problems it finds (empty when the rendering passes). ``mode``: the run's mode, which labels the
    document."""
    modes.check(mode)
    did = doc_id(skeleton)
    entry = caller.adapter.entry
    attempts: list[Attempt] = []
    problems: list[str] = []
    last: Rendering | None = None
    for number in range(1, rules.retry_cap + 1):
        system, user = prompt.build(skeleton, rules, problems=problems, review_problems=review_problems,
                                    previous_text=previous_text)
        try:
            result = caller.complete(system=system, user=user, max_tokens=max_tokens, schema=Rendering,
                                     params=params, thinking=thinking, tag=f"render:{did}", attempt=number)
        except (OutputInvalid, Truncated, Refusal) as exc:
            problems = [REPLY_PROBLEMS[type(exc)]]
            attempts.append(Attempt(number=number, failed=tuple(problems), error=type(exc).__name__))
            continue
        last = result.parsed
        problems = check(skeleton, last, rules)
        attempts.append(Attempt(number=number, request=result.key[:16], source=result.source,
                                failed=tuple(problems)))
        if not problems:
            break
    return Document(doc_id=did, base_id=skeleton.base_id, variant=skeleton.variant, skeleton_digest=skeleton.digest(),
                    mode=mode, renderer=Renderer(entry=entry.name, provider=entry.provider, model=entry.model,
                                                 params=dict(params or {}), thinking=thinking,
                                                 prompt_version=prompt.PROMPT_VERSION,
                                                 prompt_sha256=prompt.RENDER.sha256),
                    rules=rules, status="failed" if problems else "rendered",
                    text=None if last is None else last.text, spans={} if last is None else last.span_map(),
                    inferred={} if last is None else inferred_map(skeleton, last.span_map()),
                    attempts=tuple(attempts), flags=tuple(_flags(attempts, problems, rules.retry_cap)),
                    review_problems=tuple(review_problems))


# ------------------------------------------------------------------------------------------ derived variants
def changed_facts(source: Skeleton, skeleton: Skeleton) -> list[str]:
    """The facts that differ between a variant and the variant it is derived from, in the variant's order."""
    theirs = {f.id: f for f in source.facts}
    if source.base_id != skeleton.base_id or set(theirs) != {f.id for f in skeleton.facts}:
        raise ValueError("a variant is derived from another variant of its base, which has the same facts")
    return [f.id for f in skeleton.facts if theirs[f.id] != f]


def splice(text: str, replacements: dict[str, tuple[str, str]]) -> str:
    """The text with each (old, new) sentence of ``replacements`` put in place of the old one, which it holds once;
    every other byte is kept."""
    found = []
    for fid, (old, new) in replacements.items():
        if not old or text.count(old) != 1:
            raise ValueError(f"the sentence for fact {fid} is not in the text exactly once")
        found.append((text.index(old), old, new))
    pieces, end = [], 0
    for at, old, new in sorted(found):
        pieces += [text[end:at], new]
        end = at + len(old)
    return "".join(pieces + [text[end:]])


def revise(document: Document, revisions: Revisions, changed: Sequence[str]) -> tuple[Rendering | None, list[str]]:
    """The document with the changed facts' sentences replaced by the new ones, or the problems with the reply."""
    counts = Counter(r.fact for r in revisions.sentences)
    new = {r.fact: r.sentence.strip() for r in revisions.sentences}
    problems = []
    extra = sorted(set(counts) - set(changed))
    if extra:
        problems.append(f"new sentences were given for {_listed(extra)}, which "
                        + ("is not a fact to restate" if len(extra) == 1 else "are not facts to restate"))
    for fid in changed:
        if counts[fid] != 1:
            problems.append(f"no new sentence was given for fact {fid}" if not counts[fid]
                            else f"fact {fid} was given {counts[fid]} new sentences; give each fact one")
        elif new[fid] == document.spans[fid].strip():
            problems.append(f"the new sentence for fact {fid} is the sentence it replaces; state the fact given")
    if problems:
        return None, problems
    text = splice(document.text, {f: (document.spans[f], new[f]) for f in changed})
    spans = {**document.spans, **{f: new[f] for f in changed}}
    return Rendering(text=text, spans=[SpanEntry(fact=f, span=s) for f, s in spans.items()]), []


def derive(skeleton: Skeleton, source: Skeleton, document: Document, caller: Caller, *, check: Check,
           max_tokens: int, mode: str, params: dict | None = None, thinking: bool = False) -> Document:
    """The document of a planted variant, derived from its consistent twin's ``document``, or of a trap variant,
    derived from its planted variant's: the sentences of the facts that differ from ``source`` are re-rendered by
    ``caller``'s provider entry and put in place, and the result is checked by ``check`` under the source document's
    rules."""
    modes.check(mode)
    if DERIVED_FROM.get(skeleton.variant) != source.variant:
        raise ValueError(f"a {skeleton.variant} variant is not derived from a {source.variant} variant")
    if document.doc_id != doc_id(source) or document.skeleton_digest != source.digest():
        raise ValueError("the document does not render the variant it would be derived from")
    if document.status != "rendered" or document.text is None:
        raise ValueError("a variant is derived from a rendered document that passed its checks")
    if document.mode != mode:
        raise ValueError(f"a {mode} run derives from its own documents, not from a {document.mode} one")
    changed = changed_facts(source, skeleton)
    did, entry, rules = doc_id(skeleton), caller.adapter.entry, document.rules
    attempts: list[Attempt] = []
    problems: list[str] = []
    last: Rendering | None = None
    for number in range(1, rules.retry_cap + 1):
        system, user = prompt.build_derive(skeleton, {f: document.spans[f] for f in changed}, rules,
                                           problems=problems)
        try:
            result = caller.complete(system=system, user=user, max_tokens=max_tokens, schema=Revisions,
                                     params=params, thinking=thinking, tag=f"derive:{did}", attempt=number)
        except (OutputInvalid, Truncated, Refusal) as exc:
            problems = [DERIVE_PROBLEMS[type(exc)]]
            attempts.append(Attempt(number=number, failed=tuple(problems), error=type(exc).__name__))
            continue
        rendering, problems = revise(document, result.parsed, changed)
        if rendering is not None:
            last = rendering
            problems = check(skeleton, rendering, rules)
        attempts.append(Attempt(number=number, request=result.key[:16], source=result.source,
                                failed=tuple(problems)))
        if not problems:
            break
    return Document(doc_id=did, base_id=skeleton.base_id, variant=skeleton.variant, skeleton_digest=skeleton.digest(),
                    mode=mode, renderer=Renderer(entry=entry.name, provider=entry.provider, model=entry.model,
                                                 params=dict(params or {}), thinking=thinking,
                                                 prompt_version=prompt.DERIVE_VERSION,
                                                 prompt_sha256=prompt.DERIVE.sha256),
                    rules=rules, status="failed" if problems else "rendered",
                    text=None if last is None else last.text, spans={} if last is None else last.span_map(),
                    inferred={} if last is None else inferred_map(skeleton, last.span_map()),
                    attempts=tuple(attempts), flags=tuple(_flags(attempts, problems, rules.retry_cap)),
                    derived_from=document.doc_id, changed=tuple(changed))


def derivation_problems(skeleton: Skeleton, document: Document, source: Document | None) -> list[str]:
    """What is wrong with how a derived document was made; empty if nothing is. It names the document it was derived
    from, which is given; it re-rendered the facts that differ (a planted variant's ``differs_from_twin``, a trap
    variant's arity fact); and its text is that document's with those sentences replaced, every other byte kept."""
    if skeleton.variant not in DERIVED_FROM:
        return [] if document.derived_from is None else ["a consistent twin is rendered from its skeleton, not derived"]
    if document.derived_from is None:
        return [f"a {skeleton.variant} variant is derived from its {DERIVED_FROM[skeleton.variant]} variant's text, "
                "and this document was not"]
    if source is None or source.doc_id != document.derived_from:
        return [f"the document it was derived from, {document.derived_from}, is needed to check it"]
    expected = (list(skeleton.plant.params.get("differs_from_twin", ())) if skeleton.plant is not None
                else [skeleton.arity_fact])
    problems = []
    if list(document.changed) != expected:
        problems.append(f"it re-rendered the sentences for facts {_listed(list(document.changed)) or 'none'}, and "
                        f"the facts that differ are {_listed(expected)}")
    if document.text is None or source.text is None:
        return problems + ["it or the document it was derived from has no text"]
    try:
        kept = splice(source.text, {f: (source.spans.get(f, ""), document.spans.get(f, "")) for f in document.changed})
    except ValueError as exc:
        return problems + [f"in the document it was derived from, {exc}"]
    if kept != document.text:
        problems.append("its text differs from the document it was derived from outside the re-rendered sentences")
    moved = sorted(f for f in document.spans.keys() | source.spans.keys()
                   if f not in document.changed and document.spans.get(f) != source.spans.get(f))
    if moved:
        problems.append(f"its spans for facts {_listed(moved)} differ from the document it was derived from")
    return problems
