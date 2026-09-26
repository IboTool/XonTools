"""How a reported conflict is matched (the user's item 7 of 2026-09-25, xonforge/docs/decisions.md). A quoted
statement and a sentence are normalized (NFKC, case folded, quotation marks stripped, whitespace collapsed), and the
statement matches the sentence if either contains the other. A conflict matches a defect, a planted variant's plant
or a defect canary's defect, if the defect's sentences that its statements match number at least min(2, the number of
the defect's sentences). Anything matching neither goes to the human queue.

Quotation marks are stripped wherever they occur, apostrophes included, from the statement and the sentence alike, so
that a straight and a curly apostrophe compare equal. A statement that normalizes to nothing matches no sentence.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Sequence

QUOTES = "\"'\u2018\u2019\u201a\u201b\u201c\u201d\u201e\u201f\u00ab\u00bb"
_STRIP = {ord(c): None for c in QUOTES}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold().translate(_STRIP)).strip()


def matches(statement: str, sentence: str) -> bool:
    s, t = normalize(statement), normalize(sentence)
    return bool(s and t) and (s in t or t in s)


def found(statements: Sequence[str], defect: Sequence[str]) -> bool:
    """Whether a conflict, by its quoted statements, matches a defect, by its sentences."""
    sentences = list(dict.fromkeys(defect))
    if not sentences:
        raise ValueError("a defect has at least one sentence")
    hit = [d for d in sentences if any(matches(s, d) for s in statements)]
    return len(hit) >= min(2, len(sentences))
