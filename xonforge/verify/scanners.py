"""A1's deterministic scans, copied (the user's item 6 of 2026-09-25, xonforge/docs/decisions.md), and extended.

Copied from A1 at commit 1b1749b4afcea1106c439306bcc8600b44095263, which A1's copy keeps unchanged:
- xon/llm/corpus.py: ``_SUPERLATIVE_CUES`` (here ``A1_SUPERLATIVE_CUES``), ``_owners_of_cue``,
  ``superlative_collisions``;
- xon/llm/corpus_qa.py: ``_ORDER_PATTERNS`` and ``_ATTRIBUTE_CUES`` (here ``A1_ORDER_PATTERNS`` and
  ``A1_ATTRIBUTE_CUES``), ``_nonplanted_sentences``, ``same_attribute_hits``, ``extract_order_edges``, ``_find_cycles``,
  ``order_cycle_scan``.
The functions are A1's as they stand, reading ``_SUPERLATIVE_CUES``, ``_ORDER_PATTERNS`` and ``_ATTRIBUTE_CUES`` as
A1's did; here those names hold A1's lists with XonForge's extensions added. ``same_attribute_hits`` takes anything
with A1's ``Plan``'s ``people`` and ``attribute``, as XonForge passed it before.

XonForge's extensions (item 6: score, speed, club, department, table, cabin, and "arrived later than") are listed
apart, below A1's lists; each has a scan canary of its own (xonforge/canaries/scans/). Attribute names follow A1's
(``arrival_time`` in the order patterns and the attribute cues, ``arrival`` in the superlatives);
xonforge/verify/scans.py maps XonForge's attribute keys onto them.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .sentences import normalize_ws
from .sentences import sentences as _sentence_texts

# ------------------------------------------------------------------------------------------ A1's lists
# Superlative / universal-extremal cues: two different people assigned the same (attribute, pole) is an accidental
# contradiction in filler (base 32: "Milo arrived first" vs "Quinn … before anyone else"). Report-only until wired
# into verify; patterns cover paraphrases of first/last, not only those words.
A1_SUPERLATIVE_CUES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("arrival", "earliest", (
        r"arrived first", r"came first", r"showed up first", r"was the first to arrive", r"first to arrive",
        r"before anyone else", r"before everyone else", r"before anyone", r"before everyone",
        r"ahead of everyone", r"ahead of anyone", r"earlier than anyone", r"earliest to arrive",
        r"the first (?:one )?to (?:arrive|show up|come in)",
    )),
    ("arrival", "latest", (
        r"arrived last", r"came last", r"showed up last", r"was the last to arrive", r"last to arrive",
        r"after everyone else", r"after everyone", r"after anyone else", r"later than anyone",
        r"the last (?:one )?to (?:arrive|show up|come in)",
    )),
    ("height", "tallest", (
        r"the tallest", r"tallest of", r"taller than (?:everyone|anyone)(?:\s+else)?",
        r"tallest among", r"tallest in",
    )),
    ("height", "shortest", (
        r"the shortest", r"shortest of", r"shorter than (?:everyone|anyone)(?:\s+else)?",
        r"shortest among", r"shortest in",
    )),
    ("age", "oldest", (
        r"the oldest", r"oldest of", r"older than (?:everyone|anyone)(?:\s+else)?",
        r"oldest among", r"oldest in",
    )),
    ("age", "youngest", (
        r"the youngest", r"youngest of", r"younger than (?:everyone|anyone)(?:\s+else)?",
        r"youngest among", r"youngest in",
    )),
    ("rank", "highest", (
        r"ranked highest", r"the highest rank", r"finished first", r"finished ahead of everyone",
        r"placed first", r"came first in",
    )),
    ("rank", "lowest", (
        r"ranked lowest", r"the lowest rank", r"finished last", r"placed last",
    )),
)

# Phrases that compare two people on an order attribute. "forward" means subject > object on the attribute
# as used for cycle detection (age: older; height: taller; rank: ahead; arrival: earlier = subject precedes).
A1_ORDER_PATTERNS: tuple[tuple[str, str, bool], ...] = (
    ("age", r"is older than", True),
    ("age", r"is younger than", False),
    ("height", r"is taller than", True),
    ("height", r"is shorter than", False),
    ("arrival_time", r"arrived before", True),   # subject earlier than object
    ("arrival_time", r"arrived after", False),
    ("rank", r"finished ahead of", True),
    ("rank", r"finished behind", False),
    ("rank", r"ranked higher than", True),
    ("rank", r"ranked lower than", False),
    ("rank", r"placed ahead of", True),
)

# Cues that a residual sentence is relating people on this attribute (same-attribute filler check).
A1_ATTRIBUTE_CUES: dict[str, tuple[str, ...]] = {
    "age": ("older", "younger", "oldest", "youngest", "years old", "year older", "year younger"),
    "arrival_time": ("arrived", "arrival", "earlier", "later", "first to arrive", "last to arrive"),
    "height": ("taller", "shorter", "tallest", "shortest", "height"),
    "rank": ("ranked", "finished ahead", "finished behind", "placed first", "placed last", "ranking"),
    "team": ("same team", "different team", "on the same team", "not on the same team"),
    "class": ("same class", "different class", "in the same class", "not in the same class"),
    "study_group": ("same study group", "different study group", "study group"),
    "house": ("same house", "different house", "in different houses", "in the same house"),
    "shift": ("same shift", "different shift", "worked different shifts"),
}

# ------------------------------------------------------------------------------------------ XonForge's extensions
SUPERLATIVE_EXTENSIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("score", "highest", (
        r"the highest score", r"scored (?:the )?highest", r"highest score", r"the top score",
        r"scored (?:more|higher) than (?:everyone|anyone)(?:\s+else)?",
    )),
    ("score", "lowest", (
        r"the lowest score", r"scored (?:the )?lowest", r"lowest score",
        r"scored (?:less|lower) than (?:everyone|anyone)(?:\s+else)?",
    )),
    ("speed", "fastest", (
        r"the fastest", r"fastest of", r"faster than (?:everyone|anyone)(?:\s+else)?",
        r"fastest among", r"fastest in",
    )),
    ("speed", "slowest", (
        r"the slowest", r"slowest of", r"slower than (?:everyone|anyone)(?:\s+else)?",
        r"slowest among", r"slowest in",
    )),
)

ORDER_EXTENSIONS: tuple[tuple[str, str, bool], ...] = (
    ("arrival_time", r"arrived later than", False),   # subject later than object
    ("arrival_time", r"arrived earlier than", True),
    ("score", r"scored higher than", True),
    ("score", r"scored lower than", False),
    ("score", r"outscored", True),
    ("speed", r"(?:is|was) faster than", True),
    ("speed", r"(?:is|was) slower than", False),
    ("speed", r"(?:is|was) quicker than", True),
)

ATTRIBUTE_CUE_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "score": ("scored", "score", "scoring", "outscored"),
    "speed": ("faster", "slower", "fastest", "slowest", "quicker", "quickest", "speed"),
    "club": ("same club", "different club", "in the same club", "not in the same club"),
    "department": ("same department", "different department", "in the same department",
                   "not in the same department"),
    "table": ("same table", "different table", "at the same table", "not at the same table"),
    "cabin": ("same cabin", "different cabin", "in the same cabin", "not in the same cabin"),
}

# What the scans read: A1's lists and XonForge's extensions.
_SUPERLATIVE_CUES = SUPERLATIVE_CUES = A1_SUPERLATIVE_CUES + SUPERLATIVE_EXTENSIONS
_ORDER_PATTERNS = ORDER_PATTERNS = A1_ORDER_PATTERNS + ORDER_EXTENSIONS
_ATTRIBUTE_CUES = ATTRIBUTE_CUES = {**A1_ATTRIBUTE_CUES, **ATTRIBUTE_CUE_EXTENSIONS}


# ------------------------------------------------------------------------------------------ A1's scans
def _owners_of_cue(sentence: str, people: tuple[str, ...] | list[str], cue: str) -> list[str]:
    """People the cue is attributed to: the nearest listed name before the cue in the sentence (so
    'Esme mentioned that Leo was the tallest' credits Leo, not Esme)."""
    match = re.search(rf"(?i)(?:{cue})", sentence)
    if not match:
        return []
    prefix = sentence[:match.start()]
    found: list[tuple[int, str]] = []
    for person in people:
        for m in re.finditer(rf"(?<![A-Za-z]){re.escape(person)}(?![A-Za-z])", prefix):
            found.append((m.end(), person))
    if not found:
        return []
    found.sort()
    return [found[-1][1]]


def superlative_collisions(text: str, people: tuple[str, ...] | list[str]) -> list[dict]:
    """Two different people given the same superlative / universal extremal on the same attribute.

    Catches 'arrived first' vs 'before anyone else' / 'ahead of everyone', not only the words first and last.
    A string check only; used as a corpus QA report and in plant verification."""
    sentences = _sentence_texts(text)
    owned: dict[tuple[str, str], dict[str, list[str]]] = {}
    for attribute, pole, cues in _SUPERLATIVE_CUES:
        for sent in sentences:
            for cue in cues:
                for person in _owners_of_cue(sent, people, cue):
                    owned.setdefault((attribute, pole), {}).setdefault(person, [])
                    if sent not in owned[(attribute, pole)][person]:
                        owned[(attribute, pole)][person].append(sent)
    hits = []
    for (attribute, pole), by_person in owned.items():
        if len(by_person) < 2:
            continue
        names = sorted(by_person)
        sents: list[str] = []
        seen: set[str] = set()
        for n in names:
            for s in by_person[n]:
                if s not in seen:
                    seen.add(s)
                    sents.append(s)
        hits.append({"attribute": attribute, "pole": pole, "people": names, "sentences": sents})
    return hits


def _nonplanted_sentences(text: str, exclude: list[str] | tuple[str, ...]) -> list[str]:
    """Sentences of `text` that are not an exact planted/required sentence (whitespace-normalized)."""
    planted = {normalize_ws(s) for s in exclude}
    return [s for s in _sentence_texts(text) if normalize_ws(s) not in planted]


def same_attribute_hits(text: str, p, *, exclude: list[str] | tuple[str, ...] | None = None) -> list[dict]:
    """Filler that relates two of the planted trio (A,B,C) on the planted attribute, outside planted sentences."""
    a, b, c = p.people[:3]
    trio = (a, b, c)
    exclude = list(exclude if exclude is not None else p.required)
    cues = _ATTRIBUTE_CUES.get(p.attribute, ())
    hits = []
    for sent in _nonplanted_sentences(text, exclude):
        low = sent.lower()
        if not any(cue in low for cue in cues):
            continue
        named = [n for n in trio if re.search(rf"(?<![A-Za-z]){re.escape(n)}(?![A-Za-z])", sent)]
        if len(named) >= 2:
            hits.append({"attribute": p.attribute, "people": named, "sentence": sent})
    return hits


def extract_order_edges(text: str, people: tuple[str, ...] | list[str]) -> list[dict]:
    """All pairwise order phrases among `people` in `text` (subject, object, attribute, directed greater)."""
    people = list(people)
    edges = []
    for attribute, phrase, forward in _ORDER_PATTERNS:
        pat = re.compile(
            rf"(?<![A-Za-z])({'|'.join(re.escape(n) for n in people)})(?![A-Za-z])\s+{phrase}\s+"
            rf"(?<![A-Za-z])({'|'.join(re.escape(n) for n in people)})(?![A-Za-z])",
            re.I)
        for m in pat.finditer(text):
            subj, obj = m.group(1), m.group(2)
            # Recover canonical casing from the people list.
            subj_c = next(n for n in people if n.lower() == subj.lower())
            obj_c = next(n for n in people if n.lower() == obj.lower())
            if subj_c == obj_c:
                continue
            greater, lesser = (subj_c, obj_c) if forward else (obj_c, subj_c)
            sent = next((s for s in _sentence_texts(text) if m.group(0) in s), m.group(0))
            edges.append({"attribute": attribute, "greater": greater, "lesser": lesser,
                          "span": m.group(0), "sentence": sent})
    return edges


def _find_cycles(edges: list[tuple[str, str]]) -> list[list[str]]:
    """Simple directed cycles (node lists) in a small digraph; each cycle reported once up to rotation."""
    adj: dict[str, set[str]] = defaultdict(set)
    for u, v in edges:
        adj[u].add(v)
    cycles: list[list[str]] = []
    seen_sig: set[tuple[str, ...]] = set()

    def dfs(start: str, node: str, path: list[str], stack: set[str]):
        for nxt in adj.get(node, ()):
            if nxt == start and len(path) >= 2:
                rot = path[path.index(min(path)):] + path[:path.index(min(path))]
                sig = tuple(rot)
                if sig not in seen_sig:
                    seen_sig.add(sig)
                    cycles.append(list(path) + [start])
            elif nxt not in stack and len(path) < 6:
                dfs(start, nxt, path + [nxt], stack | {nxt})

    for n in list(adj):
        dfs(n, n, [n], {n})
    return cycles


def order_cycle_scan(text: str, people: tuple[str, ...] | list[str],
                     *, exclude_sentences: list[str] | tuple[str, ...] = ()) -> dict:
    """Pairwise order phrases and directed cycles per attribute.

    Cycles are computed twice: on all edges, and on edges whose sentence is not in `exclude_sentences`
    (planted sentences). The latter are the unplanted accidental cycles.
    """
    excl = {normalize_ws(s) for s in exclude_sentences}
    edges = extract_order_edges(text, people)
    by_attr: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        by_attr[e["attribute"]].append(e)

    def cycles_for(edge_list: list[dict], planted_only_exclude: bool) -> list[dict]:
        out = []
        for attribute, group in by_attr.items():
            use = group
            if planted_only_exclude:
                use = [e for e in group if normalize_ws(e["sentence"]) not in excl
                       and normalize_ws(e["span"].rstrip(".") + ".") not in excl
                       and not any(normalize_ws(e["span"]) in normalize_ws(s) for s in exclude_sentences)]
            dig = [(e["greater"], e["lesser"]) for e in use]
            for cyc in _find_cycles(dig):
                out.append({"attribute": attribute, "entities": cyc,
                            "edges": [e for e in use if e["greater"] in cyc and e["lesser"] in cyc]})
        return out

    return {
        "n_phrases": len(edges),
        "phrases": edges,
        "cycles_all": cycles_for(edges, False),
        "cycles_unplanted": cycles_for(edges, True),
    }
