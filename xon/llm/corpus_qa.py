"""Deterministic corpus QA scans (A1 §5): report-only string checks, and optional plant-verify hooks.

- same-attribute filler among the planted trio on the planted attribute
- activity-synonym leaks of the claim's event (beyond the single FACT_KEYWORDS token)
- superlative / universal-extremal collisions (delegates to corpus.superlative_collisions)
- pairwise order phrases per attribute; cycles among edges that are not planted sentences
"""
from __future__ import annotations

import re
from collections import defaultdict

from .corpus import (CorpusRecord, Plan, normalize_ws, occurrences, superlative_collisions, _sentence_texts)

# Phrases that compare two people on an order attribute. "forward" means subject > object on the attribute
# as used for cycle detection (age: older; height: taller; rank: ahead; arrival: earlier = subject precedes).
_ORDER_PATTERNS: tuple[tuple[str, str, bool], ...] = (
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
_ATTRIBUTE_CUES: dict[str, tuple[str, ...]] = {
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

# Synonyms beyond FACT_KEYWORDS for the claim's event (activity-synonym check).
ACTIVITY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "first-aid": ("first-aid", "first aid", "bandage", "med kit", "first aid kit"),
    "hall": ("hall", "booking", "booked the room", "meeting space"),
    "raffle": ("raffle", "prize", "earlier luck", "earlier excitement", "ticket was drawn"),
    "minibus": ("minibus", "the drive over", "drove over", "driving over", "van ride"),
    "photograph": ("photograph", "photo", "photos", "camera", "shot", "shots", "capturing",
                   "captured", "images", "angles and lighting", "camera bag", "camera strap"),
}


def _nonplanted_sentences(text: str, exclude: list[str] | tuple[str, ...]) -> list[str]:
    """Sentences of `text` that are not an exact planted/required sentence (whitespace-normalized)."""
    planted = {normalize_ws(s) for s in exclude}
    return [s for s in _sentence_texts(text) if normalize_ws(s) not in planted]


def same_attribute_hits(text: str, p: Plan, *, exclude: list[str] | tuple[str, ...] | None = None) -> list[dict]:
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


def activity_synonym_hits(text: str, p: Plan, *, exclude: list[str] | tuple[str, ...] | None = None) -> list[dict]:
    """Claim-event synonyms outside the required/planted sentences (extends the single-keyword leak check)."""
    exclude = list(exclude if exclude is not None else p.required)
    residual = " ".join(_nonplanted_sentences(text, exclude)).lower()
    syns = ACTIVITY_SYNONYMS.get(p.claim_keyword, (p.claim_keyword,))
    return [{"keyword": s, "claim_keyword": p.claim_keyword}
            for s in syns if s.lower() in residual]


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


def qa_document(text: str, p: Plan, *, exclude: list[str] | tuple[str, ...] | None = None) -> dict:
    """Run every deterministic corpus QA scan on one document."""
    exclude = list(exclude if exclude is not None else p.required)
    order = order_cycle_scan(text, p.people, exclude_sentences=exclude)
    return {
        "same_attribute": same_attribute_hits(text, p, exclude=exclude),
        "activity_synonyms": activity_synonym_hits(text, p, exclude=exclude),
        "superlative_collisions": superlative_collisions(text, p.people),
        "order_cycles": {
            "n_phrases": order["n_phrases"],
            "cycles_unplanted": [
                {"attribute": c["attribute"], "entities": c["entities"],
                 "sentences": sorted({e["sentence"] for e in c["edges"]})}
                for c in order["cycles_unplanted"]
            ],
            "cycles_all": [
                {"attribute": c["attribute"], "entities": c["entities"]}
                for c in order["cycles_all"]
            ],
        },
    }


def qa_record(p: Plan, r: CorpusRecord) -> dict:
    """QA one corpus record; excludes that variant's required/planted sentences from filler checks."""
    arity = ([p.arity_cycle] if r.variant == "cycle" and p.arity_cycle
             else [p.arity_control] if p.arity_control else [])
    if r.variant == "cycle":
        exclude = [p.premise, p.claim] + list(p.cycle) + arity
    elif r.variant == "direct":
        exclude = [p.premise, p.claim, p.negation] + list(p.control) + arity
    else:
        exclude = list(p.required)
    report = qa_document(r.text, p, exclude=exclude)
    report["doc_id"] = r.doc_id
    report["base"] = r.base
    report["variant"] = r.variant
    return report


def qa_corpus(records: list[CorpusRecord], plans: dict[int, Plan] | None = None) -> dict:
    """Scan every record; return aggregate hits plus per-document reports that have any hit."""
    from .corpus import plan as make_plan
    plans = plans or {}
    reports, hits = [], {"same_attribute": [], "activity_synonyms": [], "superlative_collisions": [],
                        "order_cycles_unplanted": []}
    n_phrases = 0
    planted_order_bases = set()
    for r in records:
        p = plans.get(r.base) or make_plan(r.base)
        rep = qa_record(p, r)
        n_phrases += rep["order_cycles"]["n_phrases"]
        if r.cycle_type == "order_cycle" and r.variant == "cycle" and rep["order_cycles"]["cycles_all"]:
            planted_order_bases.add(r.base)
        interesting = (rep["same_attribute"] or rep["activity_synonyms"] or rep["superlative_collisions"]
                       or rep["order_cycles"]["cycles_unplanted"])
        if interesting:
            reports.append(rep)
            for key in ("same_attribute", "activity_synonyms", "superlative_collisions"):
                if rep[key]:
                    hits[key].append({"doc_id": r.doc_id, "hits": rep[key]})
            if rep["order_cycles"]["cycles_unplanted"]:
                hits["order_cycles_unplanted"].append(
                    {"doc_id": r.doc_id, "cycles": rep["order_cycles"]["cycles_unplanted"]})
    return {
        "n_documents": len(records),
        "n_order_phrases": n_phrases,
        "n_planted_order_cycle_bases_seen": len(planted_order_bases),
        "planted_order_cycle_bases_seen": sorted(planted_order_bases),
        "hits": hits,
        "documents_with_hits": reports,
    }
