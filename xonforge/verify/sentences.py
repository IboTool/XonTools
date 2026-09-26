"""Sentences as A1's plant verification splits them, copied from A1 (the user's item 6 of 2026-09-25,
xonforge/docs/decisions.md): xon/llm/corpus.py at commit 1b1749b4afcea1106c439306bcc8600b44095263, where the
functions are ``_boundaries``, ``_sentence_spans``, ``_sentence_texts``, ``normalize_ws`` and ``occurrences``, with
the constants ``QUOTE_CHARS`` and ``TITLES``. A1's copy stays unchanged. The code is copied as it stands; the one
change is the name: ``_sentence_texts`` is ``sentences`` here, as XonForge imported it.
"""
from __future__ import annotations

import re

QUOTE_CHARS = "\"\u201c\u201d"   # straight and curly double quotes; these documents never need quoted speech
TITLES = ("Mr.", "Mrs.", "Ms.", "Dr.", "St.", "Prof.")


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _boundaries(text: str) -> list[int]:
    """Offsets where a sentence may be inserted: after a sentence end followed by whitespace and a capital letter
    (not after a title such as "Dr."), and the end of the text."""
    out = [m.start() for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z])", text)
           if not text[:m.start()].split()[-1] in TITLES]
    return out + [len(text.rstrip())]


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """The (start, end) offset of each sentence, split at the same boundaries used to insert the negation."""
    bounds = _boundaries(text)
    return list(zip([0] + bounds[:-1], bounds))


def sentences(text: str) -> list[str]:
    """Sentence strings using the same boundaries as plant verification."""
    return [text[s:e].strip() for s, e in _sentence_spans(text) if text[s:e].strip()]


def occurrences(text: str, sentence: str) -> int:
    """How often a sentence occurs in a text, after whitespace normalization, starting at a word boundary (so that
    "Ana is older than Ben." does not match inside "Hana is older than Ben.")."""
    return len(re.findall(r"(?<![A-Za-z])" + re.escape(normalize_ws(sentence)), normalize_ws(text)))
