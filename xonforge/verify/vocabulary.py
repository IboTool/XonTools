"""Word lists for the structural checks (XONFORGE_SPEC.md §7.1), the implementing agent's choice, open to overrule.

A pattern check catches the wordings it lists and no others: what it misses is left to the blind review and the human
queue (§7.3, §7.4). The lists lean towards missing a paraphrase rather than failing a good rendering, since every
failure costs one of the five attempts.
"""
from __future__ import annotations

import re

# An attribute's words, for forbidden content (a planted entity named together with them outside the planted
# sentences): its nouns, and the comparatives and superlatives that relate people on it. Values are left out where
# they are everyday words (red, sales, north, two); club values are kept, being specific.
ATTRIBUTE_WORDS = {
    "age": r"older|oldest|younger|youngest|elder|eldest|ages?|aged|years? old|born",
    "height": r"taller|tallest|shorter|shortest|heights?|tall",
    "arrival": r"arriv\w*|showed up|turned up|came in|walked in|got (?:in|there|here)|"
               r"(?:first|last) to (?:arrive|come|show up|get)|earlier than|later than",
    "score": r"scor\w*|outscor\w*|higher than|lower than|highest|lowest",
    "speed": r"faster|fastest|slower|slowest|quicker|quickest|speed\w*|sped",
    "team": r"teams?|teammates?",
    "club": r"clubs?|chess|drama|choir|robotics",
    "department": r"departments?|dept",
    "table": r"tables?",
    "cabin": r"cabins?|cabinmates?",
    # v1's planted attributes. A pattern check still misses a paraphrase; these keep the check from refusing the
    # attribute for having no words listed.
    "schedule": r"depart\w*|arriv\w*|hours?|minutes?|schedules?",
    "jars": r"jars?",
    "containment": r"contains|inside|within|containment",
    "identity": r"same person|different person|identit\w*",
    "attendance": r"arrived|attendance|everyone",
    "presence": r"left|stayed|presence",
    "duty": r"duty|only",
    "place": r"lake|library|places?",
    "years": r"born|years?|age",
    "children": r"children|child",
    "distance": r"miles?|kilomet(?:er|re)s?|km|distance",
    "news": r"news|announced|surprised",
    "cause": r"because|rain|cause",
    "scene": r"frozen|scene",
    "wording": r"every|some",
}

_NEGATION = r"\b(?:not|never|no longer|neither|nor)\b|n['\u2019]t\b"
# A negation. A comparison, a shared group, and a fact about a value listed without "not" must not contain one.
NEGATION = re.compile(_NEGATION, re.I)
# A negated value: a negation, or wording that excludes the value.
NEGATED = re.compile(_NEGATION + r"|\b(?:other than|rather than|except|anything but|instead of)\b", re.I)
# What a shared group must not say.
DIFFERENCE = re.compile(_NEGATION + r"|\b(?:different|differ\w*|separate\w*|rival|opposing|opposite)\b", re.I)
# What a difference must say, one way or another.
DIFFERENT = re.compile(DIFFERENCE.pattern + r"|\b(?:another|other)\b", re.I)

# Comparisons whose direction the checks can read: True when the wording says the first person named is greater, as
# the skeleton's "greater" reads (older, taller, a later arrival, a higher score, faster). Longest first.
ORDER = {
    "age": (("older than", True), ("younger than", False)),
    "height": (("taller than", True), ("shorter than", False)),
    "arrival": (("arrived later than", True), ("arrived earlier than", False), ("arrived after", True),
                ("arrived before", False), ("later than", True), ("earlier than", False)),
    "score": (("scored higher than", True), ("scored lower than", False), ("scored more than", True),
              ("scored less than", False), ("outscored", True), ("higher than", True), ("lower than", False)),
    "speed": (("faster than", True), ("quicker than", True), ("slower than", False)),
}


def attribute_words(attribute: str) -> re.Pattern:
    if attribute not in ATTRIBUTE_WORDS:
        raise ValueError(f"no words are listed for the attribute {attribute!r} (xonforge/verify/vocabulary.py)")
    return re.compile(rf"\b(?:{ATTRIBUTE_WORDS[attribute]})\b", re.I)


def _any(names: tuple[str, ...]) -> str:
    return "(?<![A-Za-z])(?:" + "|".join(re.escape(n) for n in names) + ")(?![A-Za-z])"


def direction(span: str, subject: tuple[str, ...], obj: tuple[str, ...], attribute: str) -> bool | None:
    """Whether the span's comparison says the subject is greater (True) or the object is (False); None when its
    wording is not listed in ORDER or it does not name the two around it. ``subject`` and ``obj``: each person's
    name and aliases."""
    for phrase, forward in ORDER.get(attribute, ()):
        for first, second, subject_first in ((subject, obj, True), (obj, subject, False)):
            pattern = (_any(first) + r"(?:\W+\w+){0,4}?\W+" + re.escape(phrase) + r"\W+(?:\w+\W+){0,2}?"
                       + _any(second))
            if re.search(pattern, span, re.I):
                return forward if subject_first else not forward
    return None
