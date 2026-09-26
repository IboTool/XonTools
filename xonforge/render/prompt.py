"""The renderer's prompts (XONFORGE_SPEC.md §6), drafts for the 20-document sample (§14, step 7), stored in
xonforge/prompts/ with their versions and hashes: render.txt, derive.txt and render_wording.json.

For the user's decision of 2026-09-25 (item 2, xonforge/docs/decisions.md), a base is rendered twin first. Its
consistent twin is rendered from its skeleton (``build``); each planted variant is derived from the twin's text by
re-rendering only the sentences of the facts that differ, in place (``build_derive``), and a trap variant from its
planted variant the same way. The renderer is never asked to plant a contradiction and never writes prose around one.

The twin's prompt gives the skeleton's people and facts, and asks for the document with, for each fact, the whole
sentence that states it. Its rules come from the document's knobs and the constants: length, explicitness, lexical
variety, the minimum spacing between the planted sentences (the twin's ``twin_facts``) and the level's spread of them.
It follows A1's document prompt (xon/llm/corpus.py, CORPUS_SYSTEM and corpus_user) where A1 had a rule: one sentence
per fact, the facts spread through the document, one assumption only, no quotation marks, no shared superlatives, no
other statement on the facts' attributes, no count of an attribute's values but the listed one. Two rules match
structural checks A1 did not need, having fixed its sentences word for word: each fact's sentence names its people,
and keeps the fact's sense (xonforge/verify/structural.py).
"""
from __future__ import annotations

from typing import Sequence

from xonforge import prompts
from xonforge.skeleton.schema import Skeleton

from .phrasing import is_assumption, noun, statement
from .schema import RenderRules, ReviewProblem

RENDER = prompts.load("render.txt")
DERIVE = prompts.load("derive.txt")
_WORDING = prompts.load("render_wording.json")
PROMPT_VERSION = f"{RENDER.version}+{_WORDING.version}"
DERIVE_VERSION = DERIVE.version
SYSTEM, DERIVE_SYSTEM = RENDER.text, DERIVE.text
_TEXTS = prompts.data("render_wording.json")
LEXICAL, EXPLICIT, SPREAD = _TEXTS["lexical_variety"], _TEXTS["explicitness"], _TEXTS["spread"]


def _names(ids: Sequence[str], skeleton: Skeleton) -> str:
    name = {e.id: e.name for e in skeleton.entities}
    names = [name[i] for i in ids]
    return names[0] if len(names) == 1 else "any of " + ", ".join(names[:-1]) + " and " + names[-1]


def _ids(ids: Sequence[str]) -> str:
    return ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " and " + ids[-1]


def _fact_line(f, skeleton: Skeleton) -> str:
    s = statement(f, skeleton)
    return f"(an assumption) Assume that {s}." if is_assumption(f) else f"{s}."


def _people(skeleton: Skeleton) -> str:
    return ", ".join(f"{e.name} ({e.pronoun})" for e in skeleton.entities)


def build(skeleton: Skeleton, rules: RenderRules, *, problems: Sequence[str] = (),
          review_problems: Sequence[ReviewProblem] = (), previous_text: str | None = None) -> tuple[str, str]:
    """The system and user prompts for one attempt at a consistent twin. ``problems``: the checks the previous attempt
    failed, quoted back. ``review_problems`` and ``previous_text``: a human reviewer's problems with an earlier
    version, for a targeted re-rendering."""
    if skeleton.variant != "consistent":
        raise ValueError(f"a {skeleton.variant} variant is derived from another variant's text (derive), not "
                         "rendered from its skeleton")
    spaced = list(skeleton.planted_facts())
    if not spaced:
        raise ValueError("a consistent twin records its twin_facts, whose sentences its checks treat as planted")
    facts = {f.id: f for f in skeleton.facts}
    attribute = facts[spaced[0]].attribute
    entities = list(dict.fromkeys(e for i in spaced for e in (facts[i].subject, facts[i].object) if e))
    lines = [f"Genre: {skeleton.genre}", f"Length: about {rules.words} words, in paragraphs.",
             f"Wording: {LEXICAL[rules.lexical_variety]}", f"Stating the facts: {EXPLICIT[rules.explicitness]}", "",
             f"People: {_people(skeleton)}", "", "Facts:"]
    lines += [f"{f.id}. {_fact_line(f, skeleton)}" for f in skeleton.facts]
    exempt = spaced + ([skeleton.arity_fact] if skeleton.arity_fact else [])
    other = "other sentence" if rules.min_spacing == 1 else "other sentences"
    lines += ["", f"Spacing: put at least {rules.min_spacing} {other} between any two of the sentences for facts "
                  f"{_ids(spaced)}, and {SPREAD[rules.spread]}.",
              "", "Restriction:",
              f"- Apart from the sentences for facts {_ids(exempt)}, no sentence may mention "
              f"{_names(entities, skeleton)} together with their {noun(attribute)}, or say anything that bears on it."]
    if problems:
        lines += ["", "An earlier draft had these problems, which this one must not have: " + "; ".join(problems) + "."]
    if review_problems:
        lines += ["", "A reviewer found these problems in an earlier version of this document:"]
        for p in review_problems:
            where = "; ".join(x for x in (f"fact {p.fact}" if p.fact else "",
                                          f"the sentence: {p.sentence}" if p.sentence else "") if x)
            lines.append(f"- {p.problem}" + (f" ({where})" if where else ""))
        if previous_text is not None:
            lines += ["Change only what is needed to fix them. The earlier version:", "", previous_text]
    return SYSTEM, "\n".join(lines)


def build_derive(skeleton: Skeleton, sentences: dict[str, str], rules: RenderRules, *,
                 problems: Sequence[str] = ()) -> tuple[str, str]:
    """The system and user prompts for one attempt at re-rendering sentences: ``sentences`` maps each fact to be
    restated to the sentence that stands in its place now. Only those sentences are shown, never the document."""
    facts = {f.id: f for f in skeleton.facts}
    lines = [f"Stating the facts: {EXPLICIT[rules.explicitness]}", "", f"People: {_people(skeleton)}", "",
             "Sentences:"]
    for fid, now in sentences.items():
        lines += [f"{fid}.", f"- The sentence now: {now}",
                  f"- The fact to state instead: {_fact_line(facts[fid], skeleton)}"]
    if problems:
        lines += ["", "An earlier attempt had these problems, which this one must not have: " + "; ".join(problems)
                  + "."]
    return DERIVE_SYSTEM, "\n".join(lines)
