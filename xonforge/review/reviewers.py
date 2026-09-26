"""Who reviews a document (XONFORGE_SPEC.md §7.3): K reviewers (2 by default, configurable). The candidates are
registry entries with the review role that a run lists; the first K of them, in the listed order, that may review the
renderer's documents do. What may review them depends on the run's mode (xonforge/modes.py), which is always given:

- ``record``: never an entry of the renderer's provider (§7.3).
- ``pipeline_test``: an entry whose model is neither the renderer's nor another chosen reviewer's, of any provider.

A provider is the entry's provider, except that entries reached through the generic OpenAI-compatible adapter count
as one provider per address, since that adapter serves any vendor.
"""
from __future__ import annotations

from typing import Sequence
from urllib.parse import urlsplit

from xon_common.providers.base import ProviderEntry
from xonforge import modes

K = 2


def provider_of(entry: ProviderEntry) -> str:
    if entry.provider == "openai_compatible":
        return f"openai_compatible@{urlsplit(entry.base_url or '').netloc}"
    return entry.provider


def select(renderer: ProviderEntry, candidates: Sequence[ProviderEntry], k: int = K, *,
           mode: str) -> list[ProviderEntry]:
    modes.check(mode)
    if k < 1:
        raise ValueError("at least one reviewer reviews each document")
    names = [e.name for e in candidates]
    if len(set(names)) != len(names):
        raise ValueError("each reviewer is listed once")
    unfit = [e.name for e in candidates if "review" not in e.roles]
    if unfit:
        raise ValueError(f"not registered for the review role: {', '.join(unfit)}")
    if mode == modes.RECORD:
        eligible = [e for e in candidates if provider_of(e) != provider_of(renderer)]
        if len(eligible) < k:
            raise ValueError(f"{k} reviewers are needed from providers other than the renderer's "
                             f"({provider_of(renderer)}), and {len(eligible)} of the listed ones are")
        return eligible[:k]
    eligible = []
    for e in candidates:
        if e.model != renderer.model and e.model not in {x.model for x in eligible}:
            eligible.append(e)
    if len(eligible) < k:
        raise ValueError(f"{k} reviewers of different models are needed, none of them the renderer's "
                         f"({renderer.model}), and {len(eligible)} of the listed ones are")
    return eligible[:k]
