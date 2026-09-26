"""Rev. 2.2's fixed comparative lexicon (XON_A1_REV2_2_PRECISION.md §5.3).

For sequence and magnitude attributes the lexicon, not the model, says which side of an order statement is the
greater one: "subject" or "object" for a comparative, "max" or "min" for a superlative. A comparative is matched
case-insensitively as a whole phrase after trimming: surrounding whitespace and punctuation, a leading "the" and a
trailing "than" do not count, so "older than" is "older" and "the oldest" is "oldest", while "no later than" or
"followed by" match nothing. Other attributes, and comparatives the lexicon does not cover, keep the model's sense.
No rank words. The table may be extended only by a logged decision.

The coverage net (§5.6) searches each claim's text for the table's words and phrases (``lexicon_words_in``).

Standard library only: the minimal engine uses it through entity_consistency.py.
"""
from __future__ import annotations

import re

ORDER_KINDS = ("sequence", "magnitude")        # the order kinds the lexicon covers; "other" never matches
SIDES = ("subject", "object", "max", "min")
LEXICON: dict[str, dict[str, tuple[str, ...]]] = {
    "sequence": {                               # greater = later
        "subject": ("after", "later than", "behind", "followed"),
        "object": ("before", "earlier than", "ahead of", "preceded", "prior to"),
        "max": ("last", "final"),
        "min": ("first", "earliest"),
    },
    "magnitude": {                              # greater = more
        "subject": ("older", "taller", "heavier", "larger", "bigger", "longer", "more", "higher"),
        "object": ("younger", "shorter", "lighter", "smaller", "less", "fewer", "lower"),
        "max": ("oldest", "tallest", "heaviest", "largest", "biggest", "longest", "most", "highest"),
        "min": ("youngest", "shortest", "lightest", "smallest", "least", "fewest", "lowest"),
    },
}


def normalize_comparative(text: str) -> str:
    """Lower case, inner whitespace collapsed, surrounding punctuation, a leading "the" and a trailing "than" off."""
    words = re.sub(r"\s+", " ", str(text).strip().lower()).strip(" \t\n\"'.,;:!?()[]").split(" ")
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    if len(words) > 1 and words[-1] == "than":
        words = words[:-1]
    return " ".join(words)


_INDEX = {kind: {normalize_comparative(w): side for side, entries in table.items() for w in entries}
          for kind, table in LEXICON.items()}


def lexicon_sense(order_kind: str | None, comparative: str) -> str | None:
    """The lexicon's greater side for a comparative on an attribute of this order kind; None if it is not covered."""
    return _INDEX.get(order_kind or "", {}).get(normalize_comparative(comparative))


WORDS = tuple(dict.fromkeys(w for table in LEXICON.values() for entries in table.values() for w in entries))
_WORDS_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in sorted(WORDS, key=len, reverse=True)) + r")\b",
                       re.IGNORECASE)


def lexicon_words_in(text: str) -> list[str]:
    """The lexicon's words and phrases in a text, in lower case: whole words, case-insensitive, inner whitespace
    collapsed."""
    return [m.group(0).lower() for m in _WORDS_RE.finditer(re.sub(r"\s+", " ", str(text)))]
