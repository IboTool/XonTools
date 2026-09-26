"""The cost estimate (XONFORGE_SPEC.md §4.2; §14, step 7): what a run would cost, per registry entry and in total,
before any live call, so that the user can decide whether it goes ahead. Offline: it generates the run's skeletons
from their seeds, builds the prompts each call would send, and prices them from the price table; no model is called.

Tokens: a text's words × the tokens per word × the model's tokenizer factor (defaults.yaml, estimate). Thinking is
billed as output, so it is counted as output, at the tokens per call the configuration assumes, as none is measured
yet. No prompt caching and no batch discount are assumed.

What a call's output holds: a rendering, the text at its target length and each fact's sentence again in the span
map; a derivation, the new sentences of the facts that differ; a review, its conflicts, and with the relational
inventory prompt the relational statements quoted again, taken as half the document's words. Reviews go in batches of
up to 20 documents, each with its 7 canaries, for every reviewer with every prompt. Two cases bound the attempts:
every rendering and derivation passing on its first attempt, and every one using all 5.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from xon_common.providers.base import ProviderEntry

from .levels import draw
from .render import prompt
from .render.phrasing import statement
from .review import blind, calibration
from .skeleton.generators import TRAP_PLANTS, generate

REPLY_WORDS = 60            # a review's conflicts, its JSON included
SPAN_WORDS = 4              # a span map entry's words besides its sentence
INVENTORY_SHARE = 0.5       # the relational inventory quotes about half the document again
ID_WORDS = 2                # "Document r-...:" before each reviewed text


@dataclass(frozen=True)
class BaseSpec:
    """One base of a composition: its plant type, difficulty level and seed, and whether it has its trap variant."""
    plant_type: str
    level: int
    seed: int
    trap: bool = False


@dataclass
class Tally:
    calls: float = 0
    input_words: float = 0
    output_words: float = 0
    thinking_tokens: float = 0

    def add(self, calls: float, input_words: float, output_words: float, thinking: float) -> None:
        self.calls += calls
        self.input_words += calls * input_words
        self.output_words += calls * output_words
        self.thinking_tokens += calls * thinking


@dataclass
class Estimate:
    documents: int
    reviewed_items: int
    tallies: dict[str, Tally] = field(default_factory=dict)


def _words(*texts: str) -> int:
    return sum(len(t.split()) for t in texts)


def _span_words(skeleton, fact_ids) -> int:
    facts = {f.id: f for f in skeleton.facts}
    return sum(_words(statement(facts[f], skeleton)) + SPAN_WORDS for f in fact_ids)


def plan(bases: Sequence[BaseSpec], *, renderers: Sequence[str], reviewers: Sequence[str],
         review_prompts: Sequence[str], attempts: int, thinking: Mapping[str, int], premise_share: float,
         genre: str = "office memo") -> Estimate:
    """The calls a run over ``bases`` would make, per registry entry, with ``attempts`` attempts at each rendering and
    derivation; the bases go to the renderers in turn. ``premise_share``: direct_negation's (defaults.yaml)."""
    if not renderers:
        raise ValueError("a run's estimate needs its renderers")
    tallies = {n: Tally() for n in (*renderers, *reviewers)}
    texts: list[int] = []
    for n, b in enumerate(bases):
        renderer = renderers[n % len(renderers)]
        knobs, rules = draw(b.level, b.plant_type, b.seed)
        traps = ("arity_control",) if b.trap and b.plant_type in TRAP_PLANTS["arity_control"] else ()
        made = generate(b.plant_type, seed=b.seed, genre=genre, knobs=knobs, level=b.level, traps=traps,
                        premise_share=premise_share if b.plant_type == "direct_negation" else None)
        twin = made.consistent
        tallies[renderer].add(attempts, _words(*prompt.build(twin, rules)),
                              rules.words + _span_words(twin, [f.id for f in twin.facts]), thinking["render"])
        for sk, changed in ([(p, p.plant.params["differs_from_twin"]) for p in made.planted]
                            + [(t, (t.arity_fact,)) for t in made.trap_only]):
            now = {f.id: statement(f, twin) for f in twin.facts if f.id in changed}
            tallies[renderer].add(attempts, _words(*prompt.build_derive(sk, now, rules)), _span_words(sk, changed),
                                  thinking["derive"])
        texts += [rules.words] * (1 + len(made.planted) + len(made.trap_only))
    pool = calibration.load()
    batches = math.ceil(len(texts) / blind.MAX_DOCUMENTS)
    canaries = []
    for n, defect in ((calibration.DEFECT_CANARIES, True), (calibration.CLEAN_CANARIES, False)):
        group = [_words(c.text) for c in pool if (c.defect is not None) == defect]
        canaries.append((sum(group) / len(group), batches * n))
    items = len(texts) + sum(n for _, n in canaries)
    for name in reviewers:
        for p in review_prompts:
            head = _words(blind.load_prompt(p).text) + ID_WORDS
            share = INVENTORY_SHARE if p == "relational_inventory" else 0
            for words, n in [(w, 1) for w in texts] + canaries:
                tallies[name].add(n, head + words, REPLY_WORDS + share * words, thinking["review"])
    return Estimate(documents=len(texts), reviewed_items=items, tallies=tallies)


def tokens(words: float, entry: ProviderEntry, settings: Mapping) -> float:
    return words * settings["tokens_per_word"] * settings.get("tokenizer_factor", {}).get(entry.model, 1.0)


def usd(tally: Tally, entry: ProviderEntry, settings: Mapping, *, with_thinking: bool = True) -> float | None:
    """The cost of a tally at the entry's price, or None if it has no price."""
    if entry.price is None:
        return None
    out = tokens(tally.output_words, entry, settings) + (tally.thinking_tokens if with_thinking else 0)
    return (tokens(tally.input_words, entry, settings) * entry.price.input_per_mtok
            + out * entry.price.output_per_mtok) / 1_000_000
