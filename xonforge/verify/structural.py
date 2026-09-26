"""The structural checks (XONFORGE_SPEC.md §7.1), and what is measured after rendering (§5.4). Deterministic, on a
rendering and its skeleton. Each problem is worded as an instruction, since the renderer receives it on its next
attempt (§6).

- Spans: one per fact, found character for character in the text, exactly once, and each one whole sentence of its
  own, sentences being split as A1's plant verification splits them (sentences.py, copied from A1).
- What a span states: the people of its fact, by name; the value of a fact that has one (a number as a word or in
  digits, and no other number beside a stated number of values); a negation exactly where a fact about a value has
  one, none in a comparison or a shared group, and a difference in a difference; a comparison the right way round,
  where its wording is one vocabulary.py lists. Checked on every fact, distractors included, since a distractor stated
  wrongly can add a contradiction of its own.
- Forbidden content: no sentence but the planted ones and the arity fact's names a planted entity together with the
  planted attribute's words (vocabulary.py).
- No quotation marks (v0 has no quoted_speech traps); a length within the tolerance of the document's target; at least
  the minimum spacing between any two planted sentences; and the spread of the planted sentences that the document's
  level asks for.

For the user's decisions of 2026-09-25 (xonforge/docs/decisions.md): the planted sentences are a planted variant's
plant's, a consistent twin's ``twin_facts``' (item 2), and a trap variant's trap facts' other than the arity fact
(item 20); the arity sentence is never a planted sentence, so it is exempt from spacing, spread and the plant distance
but must be present, and forbidden content exempts it (item 1). The minimum spacing is one sentence (item 1). The
length tolerance is 15% of the target, and at least 25 words (item 4). The spread (item 4): at level 2 the planted
sentences, from the start of the first to the end of the last, take up at least half the document's words; at level 3
the first planted sentence begins within the first quarter of its words and the last begins within the last quarter
(the implementing agent's reading of "in the first and last quarters").
"""
from __future__ import annotations

import math
import re
from collections import Counter
from fractions import Fraction

from xonforge.render.phrasing import NUMBERS, noun
from xonforge.render.schema import Rendering, RenderRules
from xonforge.skeleton.schema import Fact, Skeleton

from . import vocabulary as vocab
from .sentences import QUOTE_CHARS, normalize_ws, occurrences, sentences

LENGTH_SHARE, LENGTH_WORDS = Fraction(15, 100), 25     # the length tolerance: 15% of the target, at least 25 words
WORDS = {1: "one", **NUMBERS}
DIGITS = {w: str(n) for n, w in WORDS.items()}
_NUMBER = re.compile(r"\b(?:" + "|".join(w for n, w in WORDS.items() if n > 1) + r")\b|\d+", re.I)


def listed(items) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def names(skeleton: Skeleton) -> dict[str, tuple[str, ...]]:
    """Each entity's name and aliases, by id."""
    return {e.id: (e.name, *e.aliases) for e in skeleton.entities}


def mentions(sentence: str, forms: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![A-Za-z]){re.escape(n)}(?![A-Za-z])", sentence) for n in forms)


def planted_ids(skeleton: Skeleton) -> list[str]:
    return list(skeleton.planted_facts())


def exempt_ids(skeleton: Skeleton) -> list[str]:
    """The sentences forbidden content leaves alone: the planted ones and the arity fact's."""
    return planted_ids(skeleton) + ([skeleton.arity_fact] if skeleton.arity_fact else [])


def scope(skeleton: Skeleton) -> tuple[str, list[str]] | None:
    """The planted attribute and entities, those of the planted facts; None when no fact is planted."""
    facts = {f.id: f for f in skeleton.facts}
    planted = [facts[i] for i in planted_ids(skeleton)]
    if not planted:
        return None
    params = skeleton.plant.params if skeleton.plant else {}
    entities = params.get("entities") or dict.fromkeys(e for f in planted for e in (f.subject, f.object) if e)
    return params.get("attribute") or planted[0].attribute, list(entities)


def positions(rendering: Rendering, ids) -> dict[str, int]:
    """The sentence index of each fact in ``ids`` whose span is one whole sentence of the text."""
    index: dict[str, int] = {}
    for i, s in enumerate(sentences(rendering.text)):
        index.setdefault(normalize_ws(s), i)
    spans = rendering.span_map()
    return {f: index[normalize_ws(spans[f])] for f in ids if f in spans and normalize_ws(spans[f]) in index}


def whole(skeleton: Skeleton, rendering: Rendering) -> bool:
    """Whether every sentence forbidden content exempts is a whole sentence of the text, found once."""
    ids = exempt_ids(skeleton)
    spans = rendering.span_map()
    return (len(positions(rendering, ids)) == len(ids)
            and all(occurrences(rendering.text, spans[f]) == 1 for f in ids))


# ------------------------------------------------------------------------------------------ spans
def span_problems(skeleton: Skeleton, rendering: Rendering) -> list[str]:
    text, ids = rendering.text, [f.id for f in skeleton.facts]
    counts = Counter(s.fact for s in rendering.spans)
    problems = []
    unknown = sorted(set(counts) - set(ids))
    if unknown:
        problems.append(f"spans were given for {listed(unknown)}, which "
                        + ("is not a listed fact" if len(unknown) == 1 else "are not listed facts"))
    spans = rendering.span_map()
    whole_sentences = {normalize_ws(s) for s in sentences(text)}
    sharing: dict[str, list[str]] = {}
    for fid in ids:
        if counts[fid] != 1:
            problems.append(f"no span was given for fact {fid}" if not counts[fid]
                            else f"fact {fid} was given {counts[fid]} spans; give each fact one")
            continue
        span = spans[fid]
        if not span.strip() or span not in text:
            problems.append(f"the span for fact {fid} is not in the text character for character: {span}")
            continue
        n = occurrences(text, span)
        if n > 1:
            problems.append(f"the sentence for fact {fid} appears {n} times; state each fact exactly once: {span}")
        if normalize_ws(span) not in whole_sentences:
            problems.append(f"the span for fact {fid} is not one whole sentence of the text: {span}")
        sharing.setdefault(normalize_ws(span), []).append(fid)
    problems += [f"facts {listed(fids)} share one sentence; state each fact in a sentence of its own"
                 for fids in sharing.values() if len(fids) > 1]
    return problems


# ------------------------------------------------------------------------------------------ what each span states
def _value(f: Fact, span: str) -> list[str]:
    if f.value is None:
        return []
    if type(f.value) is int:
        word = WORDS.get(f.value, str(f.value))
        found = {m.group(0).lower() for m in _NUMBER.finditer(span)}
        if not found & {word, str(f.value)}:
            return [f"the sentence for fact {f.id} must state the number {word}: {span}"]
        others = sorted(found - {word, str(f.value)})
        return [f"the sentence for fact {f.id} must state the number {word} and no other ({listed(others)}): {span}"
                ] if others else []
    forms = {str(f.value)} | ({DIGITS[str(f.value)]} if str(f.value) in DIGITS else set())
    if not any(re.search(rf"(?<![A-Za-z0-9]){re.escape(x)}(?![A-Za-z0-9])", span, re.I) for x in forms):
        return [f"the sentence for fact {f.id} must name the value {f.value}: {span}"]
    return []


def _sense(f: Fact, span: str, who: dict[str, tuple[str, ...]]) -> list[str]:
    if f.states_arity:
        return []
    if f.relation == "greater":
        if vocab.NEGATION.search(span):
            return [f"the sentence for fact {f.id} must state the comparison outright, without a negation: {span}"]
        if vocab.direction(span, who[f.subject], who[f.object], f.attribute) is False:
            return [f"the sentence for fact {f.id} states the comparison the wrong way round: {span}"]
        return []
    if f.relation == "same" and vocab.DIFFERENCE.search(span):
        return [f"the sentence for fact {f.id} must say that the two share their {noun(f.attribute)}, without a "
                f"negation or a difference: {span}"]
    if f.relation == "different" and not vocab.DIFFERENT.search(span):
        return [f"the sentence for fact {f.id} must say that the two differ in their {noun(f.attribute)}: {span}"]
    if f.relation is None and f.value is not None:
        if f.negated and not vocab.NEGATED.search(span):
            return [f"the sentence for fact {f.id} must say that it does not hold, with a negation: {span}"]
        if not f.negated and vocab.NEGATION.search(span):
            return [f"the sentence for fact {f.id} must state it without a negation: {span}"]
    return []


def content_problems(skeleton: Skeleton, rendering: Rendering) -> list[str]:
    spans, who = rendering.span_map(), names(skeleton)
    problems = []
    for f in skeleton.facts:
        span = spans.get(f.id)
        if span is None or not span.strip() or span not in rendering.text:
            continue
        missing = [who[x][0] for x in (f.subject, f.object) if x and not mentions(span, who[x])]
        if missing:
            problems.append(f"the sentence for fact {f.id} must name {listed(missing)}: {span}")
        problems += _value(f, span) + _sense(f, span, who)
    return problems


# ------------------------------------------------------------------------------------------ the constants
def forbidden_problems(skeleton: Skeleton, rendering: Rendering) -> list[str]:
    found = scope(skeleton)
    if found is None:
        return []
    attribute, entities = found
    words, who = vocab.attribute_words(attribute), names(skeleton)
    planted = [who[e] for e in entities]
    spans = rendering.span_map()
    exempt = [normalize_ws(spans[f]) for f in exempt_ids(skeleton) if spans.get(f, "").strip()]
    problems = []
    for s in sentences(rendering.text):
        if any(e in normalize_ws(s) for e in exempt):
            continue
        named = [forms[0] for forms in planted if mentions(s, forms)]
        if named and words.search(s):
            problems.append(f"apart from the sentences for facts {listed(exempt_ids(skeleton))}, no sentence may "
                            f"mention {listed(named)} together with their {noun(attribute)}: {s}")
    return problems


def quotation_problems(text: str) -> list[str]:
    marks = [c for c in QUOTE_CHARS if c in text]
    return [f"the text uses quotation marks ({' '.join(marks)}); use none"] if marks else []


def length_range(target: int) -> tuple[int, int]:
    """The fewest and the most words a document of the target length may have."""
    allowed = max(LENGTH_SHARE * target, LENGTH_WORDS)
    return math.ceil(target - allowed), math.floor(target + allowed)


def length_problems(text: str, rules: RenderRules) -> list[str]:
    n, (low, high) = len(text.split()), length_range(rules.words)
    return [] if low <= n <= high else [
        f"the text has {n:,} words, and must have {low:,} to {high:,}; write about {rules.words:,}"]


def spacing_problems(skeleton: Skeleton, rendering: Rendering, rules: RenderRules) -> list[str]:
    ordered = sorted(positions(rendering, planted_ids(skeleton)).items(), key=lambda kv: kv[1])
    problems = []
    for (f1, a), (f2, b) in zip(ordered, ordered[1:]):
        n = b - a - 1
        if n < rules.min_spacing:
            problems.append(f"only {n} other {'sentence separates' if n == 1 else 'sentences separate'} the sentences "
                            f"for facts {f1} and {f2}; put at least {rules.min_spacing} between them")
    return problems


def _layout(skeleton: Skeleton, rendering: Rendering) -> tuple[list[tuple[str, int]], list[int], int]:
    """The planted sentences found whole, as (fact, sentence index) in text order; the word at which each sentence of
    the text begins; and the text's words, counted over its sentences."""
    lengths = [len(s.split()) for s in sentences(rendering.text)]
    starts = [sum(lengths[:i]) for i in range(len(lengths))]
    ordered = sorted(positions(rendering, planted_ids(skeleton)).items(), key=lambda kv: kv[1])
    return ordered, starts, sum(lengths)


def spread_problems(skeleton: Skeleton, rendering: Rendering, rules: RenderRules) -> list[str]:
    ordered, starts, total = _layout(skeleton, rendering)
    if rules.spread == "any" or len(ordered) < 2:
        return []
    (first, i), (last, j) = ordered[0], ordered[-1]
    ids = listed(planted_ids(skeleton))
    if rules.spread == "half":
        covered = (starts[j + 1] if j + 1 < len(starts) else total) - starts[i]
        return [] if 2 * covered >= total else [
            f"from the sentence for fact {first} to the sentence for fact {last} is {covered:,} of the text's "
            f"{total:,} words; spread the sentences for facts {ids} over at least half of the document"]
    problems = []
    if 4 * starts[i] >= total:
        problems.append(f"the first of the sentences for facts {ids}, fact {first}'s, begins after the first quarter "
                        "of the document; put it within the first quarter")
    if 4 * starts[j] < 3 * total:
        problems.append(f"the last of the sentences for facts {ids}, fact {last}'s, begins before the last quarter "
                        "of the document; put it within the last quarter")
    return problems


def structural(skeleton: Skeleton, rendering: Rendering, rules: RenderRules) -> list[str]:
    """Every structural problem with the rendering; empty when it passes."""
    return (span_problems(skeleton, rendering) + content_problems(skeleton, rendering)
            + forbidden_problems(skeleton, rendering) + quotation_problems(rendering.text)
            + length_problems(rendering.text, rules) + spacing_problems(skeleton, rendering, rules)
            + spread_problems(skeleton, rendering, rules))


def measure(skeleton: Skeleton, rendering: Rendering) -> dict[str, int | None]:
    """What §5.4 measures after rendering: the words (whitespace-separated), the sentences, the plant distance (the
    words between the first and the last planted sentence), the fewest other sentences between two planted sentences,
    and where the planted sentences lie: the words from the start of the first to the end of the last, and the words
    before the first and before the last."""
    ordered, starts, total = _layout(skeleton, rendering)
    at = sorted({i for _, i in ordered})
    split = sentences(rendering.text)
    spread = len(at) > 1
    return {"words": len(rendering.text.split()), "sentences": len(split),
            "plant_distance": sum(len(s.split()) for s in split[at[0] + 1:at[-1]]) if spread else None,
            "min_spacing": min(b - a - 1 for a, b in zip(at, at[1:])) if spread else None,
            "planted_words": ((starts[at[-1] + 1] if at[-1] + 1 < len(starts) else total) - starts[at[0]]
                              if spread else None),
            "words_before_first_planted": starts[at[0]] if at else None,
            "words_before_last_planted": starts[at[-1]] if at else None}
