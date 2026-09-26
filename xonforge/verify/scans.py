"""The deterministic scans (XONFORGE_SPEC.md §7.2): A1's, copied into scanners.py and extended there (the user's
item 6 of 2026-09-25, xonforge/docs/decisions.md):

- superlative collisions: two people given the same superlative on one attribute;
- order cycles: pairwise comparisons, outside the planted sentences, that close a cycle on one attribute;
- same-attribute leaks: a sentence outside the planted sentences that relates two of the planted entities on the
  planted attribute. A1's scan reads three people; for more planted entities, it is run on every three of them.

A1's fourth scan, activity synonyms of a hidden claim, is not copied: its hidden-claim events have no counterpart in
v0's plants. Each scan knows only the wordings and attributes it has patterns for: ``covers`` says which of
XonForge's attributes those are, and a document records the attributes it could not scan (``uncovered``), which keep
it from being accepted (fail closed, item 6). ``patterns`` lists each scan's patterns for XonForge's attributes, each
of which has a canary of its own; a scan's clean result is trusted only once it has caught its canaries (canaries.py).
"""
from __future__ import annotations

import itertools
from types import SimpleNamespace

from xonforge.render.schema import Rendering
from xonforge.skeleton.catalog import CATEGORICAL, ORDINAL
from xonforge.skeleton.schema import Skeleton

from .scanners import (ATTRIBUTE_CUES, ORDER_PATTERNS, SUPERLATIVE_CUES, order_cycle_scan, same_attribute_hits,
                       superlative_collisions)
from .structural import exempt_ids, listed, names, scope

SCANS = ("superlative_collisions", "order_cycles", "same_attribute")
NOT_REUSED = {"activity_synonyms": "A1's hidden-claim events have no counterpart in v0's plants"}

# XonForge's attribute keys where A1's order patterns and attribute cues name them differently.
_A1 = {"arrival": "arrival_time"}
_XONFORGE = {v: k for k, v in _A1.items()}


def patterns(scan: str) -> list[str]:
    """The scan's patterns for XonForge's attributes, by key: a superlative's attribute and pole ("score:highest"),
    an order phrase ("arrived later than"), or the attribute a same-attribute scan has cues for ("club")."""
    ours = set(ORDINAL) | set(CATEGORICAL)
    # same-attribute also covers a location a plant can put three entities on. Superlatives and order stay ordinal.
    same = ours | {"containment"}
    if scan == "superlative_collisions":
        return [f"{a}:{pole}" for a, pole, _ in SUPERLATIVE_CUES if a in ours]
    if scan == "order_cycles":
        return [phrase for a, phrase, _ in ORDER_PATTERNS if _XONFORGE.get(a, a) in ours]
    if scan == "same_attribute":
        return [_XONFORGE.get(a, a) for a in ATTRIBUTE_CUES if _XONFORGE.get(a, a) in same]
    raise ValueError(f"no scan is called {scan!r}")


def covers(scan: str, attribute: str) -> bool:
    """Whether the scan has any pattern for the attribute."""
    if scan == "superlative_collisions":
        return attribute in {a for a, _, _ in SUPERLATIVE_CUES}
    if scan == "order_cycles":
        return _A1.get(attribute, attribute) in {a for a, _, _ in ORDER_PATTERNS}
    if scan == "same_attribute":
        return _A1.get(attribute, attribute) in ATTRIBUTE_CUES
    raise ValueError(f"no scan is called {scan!r}")


def applies(scan: str, skeleton: Skeleton) -> bool:
    """A same-attribute leak needs three planted entities or more; the other scans read any document."""
    found = scope(skeleton)
    return scan != "same_attribute" or (found is not None and len(found[1]) >= 3)


def relevant(scan: str, skeleton: Skeleton) -> list[str]:
    """The attributes the scan should cover on this skeleton: its ordinal attributes for superlatives and order
    cycles, the planted attribute for same-attribute leaks."""
    if scan == "same_attribute":
        return [scope(skeleton)[0]] if applies(scan, skeleton) else []
    return [a.key for a in skeleton.attributes if a.kind == "ordinal"]


def run(scan: str, text: str, people, *, attribute: str | None = None, plant_people=(), planted=()) -> list[dict]:
    """The scan's hits on a text. ``people``: every person's name; ``planted``: the planted sentences, which order
    cycles and same-attribute leaks leave out; ``attribute`` and ``plant_people``: the plant's, for same-attribute
    leaks."""
    if scan == "superlative_collisions":
        return superlative_collisions(text, list(people))
    if scan == "order_cycles":
        return [dict(c, attribute=_XONFORGE.get(c["attribute"], c["attribute"]))
                for c in order_cycle_scan(text, list(people), exclude_sentences=list(planted))["cycles_unplanted"]]
    if scan == "same_attribute":
        found: dict[str, set[str]] = {}
        for trio in itertools.combinations(plant_people, 3):
            plan = SimpleNamespace(people=trio, attribute=_A1.get(attribute, attribute))
            for hit in same_attribute_hits(text, plan, exclude=list(planted)):
                found.setdefault(hit["sentence"], set()).update(hit["people"])
        return [{"attribute": attribute, "people": sorted(p), "sentence": s} for s, p in found.items()]
    raise ValueError(f"no scan is called {scan!r}")


def scan(skeleton: Skeleton, rendering: Rendering) -> dict[str, list[dict]]:
    """Every scan's hits on a rendering; a scan that does not apply has none."""
    who = names(skeleton)
    spans = rendering.span_map()
    planted = [spans[f] for f in exempt_ids(skeleton) if f in spans]
    people = [e.name for e in skeleton.entities]
    attribute, entities = scope(skeleton) or (None, [])
    return {s: run(s, rendering.text, people, attribute=attribute, plant_people=[who[e][0] for e in entities],
                   planted=planted)
            if applies(s, skeleton) else [] for s in SCANS}


def problems(skeleton: Skeleton, hits: dict[str, list[dict]]) -> list[str]:
    """The hits, worded for the renderer's next attempt."""
    facts = f"the sentences for facts {listed(exempt_ids(skeleton))}" if exempt_ids(skeleton) else "the facts' own"
    out = [f"{listed(h['people'])} are each given the same superlative on {h['attribute']} ({h['pole']}); give it to "
           f"one person at most: {' / '.join(h['sentences'])}" for h in hits.get("superlative_collisions", ())]
    out += [f"sentences other than {facts} compare {listed(c['entities'][:-1])} in a circle on {c['attribute']}; "
            f"drop a comparison that closes it: {' / '.join(sorted({e['sentence'] for e in c['edges']}))}"
            for c in hits.get("order_cycles", ())]
    out += [f"apart from {facts}, no sentence may relate {listed(h['people'])} on their {h['attribute']}: "
            f"{h['sentence']}" for h in hits.get("same_attribute", ())]
    return out
