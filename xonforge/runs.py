"""Run configurations (defaults.yaml, ``runs``) and the check before a run starts (the user's decisions of 2026-09-25,
xonforge/docs/decisions.md).

A configuration names its mode (modes.py), its renderers and reviewers (registry entry names) and its caps. A run
starts only if:
- every entry it uses has its model id and its price verified in the provider's documentation, and the role it is used
  for;
- every entry is available, its key present and its SDK installed (not needed for a dry run, which only replays the
  response cache);
- each renderer has k reviewers that may review its documents in the run's mode (review/reviewers.py);
- every cap is set, since the budget sends no call that needs a cap which is not;
- in a corpus-of-record run, its entries come from at least three configured providers.

Caps: ``provider_tokens_each`` and ``provider_usd_each`` give each of the run's entries the same cap, and an entry
listed under ``provider_tokens`` or ``provider_usd`` gets its own. The budget caps each registry entry, and the run
caps bound them together.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from xon_common.budget import Caps
from xon_common.providers.base import Adapter, ProviderEntry

from . import modes
from .review.reviewers import provider_of, select

FIELDS = frozenset({"mode", "renderers", "reviewers", "caps"})
CAP_FIELDS = frozenset({"run_tokens", "run_usd", "provider_tokens", "provider_usd", "provider_tokens_each",
                        "provider_usd_each"})


class RunRefused(RuntimeError):
    """A run that may not start; ``problems`` says why."""

    def __init__(self, name: str, problems: list[str]):
        self.problems = list(problems)
        super().__init__(f"the run configuration {name} may not start: " + "; ".join(problems))


@dataclass(frozen=True)
class RunConfig:
    name: str
    mode: str
    renderers: tuple[str, ...]
    reviewers: tuple[str, ...]
    caps: Caps

    @property
    def entries(self) -> tuple[str, ...]:
        """The entries the run uses, each once."""
        return tuple(dict.fromkeys(self.renderers + self.reviewers))


def load(name: str, defaults: dict, entries: Mapping[str, ProviderEntry]) -> RunConfig:
    raw = (defaults.get("runs") or {}).get(name)
    where = f"defaults.yaml, runs.{name}"
    if raw is None:
        raise ValueError(f"defaults.yaml has no run configuration named {name!r}")
    unknown = sorted(set(raw) - FIELDS) + sorted(f"caps.{k}" for k in set(raw.get("caps") or {}) - CAP_FIELDS)
    if unknown:
        raise ValueError(f"{where}: unknown fields {', '.join(unknown)}")
    mode = modes.check(raw.get("mode"))
    renderers, reviewers = tuple(raw.get("renderers") or ()), tuple(raw.get("reviewers") or ())
    missing = sorted({n for n in renderers + reviewers if n not in entries})
    if missing:
        raise ValueError(f"{where}: no registry entry is named {', '.join(missing)}")
    caps = raw.get("caps") or {}
    names = tuple(dict.fromkeys(renderers + reviewers))

    def table(key: str) -> dict:
        own = dict(caps.get(key) or {})
        stray = sorted(set(own) - set(names))
        if stray:
            raise ValueError(f"{where}, caps.{key}: {', '.join(stray)} is not an entry the run uses")
        return {n: own.get(n, caps.get(f"{key}_each")) for n in names}

    return RunConfig(name=name, mode=mode, renderers=renderers, reviewers=reviewers,
                     caps=Caps(run_tokens=caps.get("run_tokens"), run_usd=caps.get("run_usd"),
                               provider_tokens=table("provider_tokens"), provider_usd=table("provider_usd")))


def _unset(config: RunConfig, what: str) -> list[str]:
    run = getattr(config.caps, f"run_{what}")
    table = getattr(config.caps, f"provider_{what}")
    return (["the run's"] if run is None else []) + [f"{n}'s" for n in config.entries if table.get(n) is None]


def problems(config: RunConfig, entries: Mapping[str, ProviderEntry], adapters: Mapping[str, Adapter], *, k: int,
             dry_run: bool = False) -> list[str]:
    """Why the run may not start; empty if it may."""
    out = [] if config.renderers else ["no renderer is chosen"]
    used = [entries[n] for n in config.entries]
    available = {e.name: dry_run or adapters[e.name].status()[0] for e in used}
    for e in used:
        if not e.verified:
            out.append(f"{e.name}: its model id is not verified in the provider's documentation")
        if e.price is None or not e.price.verified:
            out.append(f"{e.name}: its price is not verified")
        if not available[e.name]:
            out.append(f"{e.name} is unavailable: {adapters[e.name].status()[1]}")
    for role, names in (("render", config.renderers), ("review", config.reviewers)):
        unfit = [n for n in names if role not in entries[n].roles]
        if unfit:
            out.append(f"not registered for the {role} role: {', '.join(unfit)}")
    for name in config.renderers:
        try:
            select(entries[name], [entries[n] for n in config.reviewers], k, mode=config.mode)
        except ValueError as exc:
            out.append(f"renderer {name}: {exc}")
    for what, noun in (("tokens", "token"), ("usd", "dollar")):
        unset = _unset(config, what)
        if unset:
            out.append(f"the {noun} caps are not set ({', '.join(unset)}), and the budget sends no call without them")
    if config.mode == modes.RECORD:
        configured = sorted({provider_of(e) for e in used if e.verified and e.price is not None and e.price.verified
                             and available[e.name]})
        if len(configured) < modes.MIN_PROVIDERS:
            out.append(f"a corpus-of-record run needs at least {modes.MIN_PROVIDERS} configured providers, and its "
                       f"entries have {len(configured)}" + (f" ({', '.join(configured)})" if configured else ""))
    return out
