"""XonForge's provider registry (XONFORGE_SPEC.md §4.1) and startup check (§4.2), from config/providers.yaml,
config/prices.yaml and config/defaults.yaml.

Keys come only from XonForge's own variables, one per provider (CHANGELOG_EXPERIMENTS.md, XonForge step 0, item 7):
the registry refuses an entry whose key_env is any other. The check says whether each key is present, never what it
is, and sends its one tiny test call only when asked and only within the budget caps.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import yaml

from xon_common.budget import Budget, BudgetPaused, Caps
from xon_common.cache import ResponseCache
from xon_common.caller import Caller
from xon_common.calllog import CallLog
from xon_common.providers import ADAPTERS, adapter_for
from xon_common.providers.base import (Adapter, Capabilities, OutputInvalid, Price, ProviderEntry, Refusal,
                                       Truncated)
from xon_common.retry import RetryPolicy

from . import locations, runs

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(__file__).resolve().parent / "config"
KEY_ENV = {"anthropic": "XONFORGE_ANTHROPIC_KEY", "openai": "XONFORGE_OPENAI_KEY", "google": "XONFORGE_GEMINI_KEY",
           "xai": "XONFORGE_XAI_KEY"}
OWN_KEY = re.compile(r"XONFORGE_[A-Z0-9]+_KEY")
NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
ROLES = frozenset({"render", "review", "audit"})
FIELDS = frozenset({"name", "provider", "model", "key_env", "base_url", "roles", "capabilities", "verified", "source"})
TEST_RUN = "startup-check"
TEST_CALL = {"system": "Reply with the single word: ok", "user": "ok?", "max_tokens": 256}


def load_yaml(name: str, config_dir: str | Path = CONFIG_DIR):
    with open(Path(config_dir) / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_defaults(config_dir: str | Path = CONFIG_DIR) -> dict:
    return load_yaml("defaults.yaml", config_dir)


def key_env_error(provider: str, key_env: str | None) -> str | None:
    """Why an entry may not read its key from ``key_env``, or None if it may."""
    if provider in KEY_ENV:
        own = KEY_ENV[provider]
        return None if key_env == own else f"an entry for {provider} reads its key from {own}"
    if key_env is None or (OWN_KEY.fullmatch(key_env) and key_env not in KEY_ENV.values()):
        return None
    return "an openai_compatible entry reads no key, or its own XONFORGE_<NAME>_KEY, never a cloud provider's"


def load_entries(config_dir: str | Path = CONFIG_DIR) -> list[ProviderEntry]:
    prices = load_yaml("prices.yaml", config_dir) or {}
    entries, seen = [], set()
    for raw in load_yaml("providers.yaml", config_dir) or []:
        name, provider = raw.get("name"), raw.get("provider")
        where = f"providers.yaml, entry {name!r}"
        unknown = sorted(set(raw) - FIELDS)
        if unknown:
            raise ValueError(f"{where}: unknown fields {', '.join(unknown)}")
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in seen:
            raise ValueError(f"{where}: a name is unique and made of lower-case letters, digits, '.', '_' and '-'")
        seen.add(name)
        if provider not in ADAPTERS:
            raise ValueError(f"{where}: the provider is one of {', '.join(ADAPTERS)}")
        why = key_env_error(provider, raw.get("key_env"))
        if why:
            raise ValueError(f"{where}: {why}")
        roles = tuple(raw.get("roles") or ())
        if not set(roles) <= ROLES:
            raise ValueError(f"{where}: the roles are among {', '.join(sorted(ROLES))}")
        p = (prices.get(provider) or {}).get(str(raw["model"]))
        price = None if p is None else Price(float(p["input"]), float(p["output"]), bool(p.get("verified", False)),
                                             str(p.get("source", "")), float(p.get("cache_read", 1.0)),
                                             float(p.get("cache_write", 1.0)))
        entries.append(ProviderEntry(name=name, provider=provider, model=str(raw["model"]), key_env=raw.get("key_env"),
                                     base_url=raw.get("base_url"), roles=roles,
                                     capabilities=Capabilities(**(raw.get("capabilities") or {})), price=price,
                                     verified=bool(raw.get("verified", False)), source=str(raw.get("source", ""))))
    return entries


def retry_policy(defaults: dict) -> RetryPolicy:
    return RetryPolicy(int(defaults["transport_retries"]), float(defaults["transport_backoff_s"]))


def caps_of(defaults: dict, entries: list[ProviderEntry]) -> Caps:
    raw = defaults.get("caps") or {}
    names = {e.name for e in entries}
    for table in ("provider_tokens", "provider_usd"):
        unknown = sorted(set(raw.get(table) or {}) - names)
        if unknown:
            raise ValueError(f"defaults.yaml, caps.{table}: no registry entry is named {', '.join(unknown)}")
    return Caps(run_tokens=raw.get("run_tokens"), run_usd=raw.get("run_usd"),
                provider_tokens=dict(raw.get("provider_tokens") or {}),
                provider_usd=dict(raw.get("provider_usd") or {}))


def caps_set(caps: Caps, name: str) -> bool:
    return None not in (caps.run_tokens, caps.run_usd, caps.provider_tokens.get(name), caps.provider_usd.get(name))


def call_log(defaults: dict) -> CallLog:
    return CallLog(ROOT / defaults["call_log"])


def adapters(entries: list[ProviderEntry], defaults: dict) -> dict[str, Adapter]:
    return {e.name: adapter_for(e, timeout_s=float(defaults["request_timeout_s"])) for e in entries}


def response_cache() -> ResponseCache:
    """XonForge's response cache, in the directory XONFORGE_CACHE_DIR names; refused if that is unset or inside a
    worktree of this repository."""
    return ResponseCache(locations.cache_dir())


class Session:
    """What the calls of one run share (XONFORGE_SPEC.md §4.2, §11): the registry, the response cache outside the
    repository, one budget with the run's caps, starting from what the call log says the run has spent (so a resumed
    run pays for nothing twice), the call log, and the retry policy. ``run_config``: the run's configuration in
    defaults.yaml (runs.py), which sets its mode and caps, and which must pass its check (RunRefused otherwise);
    without one, the caps are defaults.yaml's own and the session has no mode. ``clients`` replaces SDK clients by
    entry name (tests pass fakes); ``log`` replaces the call log in the repository."""

    def __init__(self, run: str, *, run_config: str | None = None, dry_run: bool = False,
                 config_dir: str | Path = CONFIG_DIR, log: CallLog | None = None, clients: dict | None = None,
                 sleep=time.sleep):
        self.run, self.dry_run, self.sleep = run, dry_run, sleep
        self.defaults = load_defaults(config_dir)
        self.entries = {e.name: e for e in load_entries(config_dir)}
        self.cache = response_cache()
        self.log = log if log is not None else call_log(self.defaults)
        self.adapters = {name: adapter_for(e, client=(clients or {}).get(name),
                                           timeout_s=float(self.defaults["request_timeout_s"]))
                         for name, e in self.entries.items()}
        self.config = None if run_config is None else runs.load(run_config, self.defaults, self.entries)
        if self.config is not None:
            found = runs.problems(self.config, self.entries, self.adapters, k=int(self.defaults["review"]["k"]),
                                  dry_run=dry_run)
            if found:
                raise runs.RunRefused(run_config, found)
        caps = self.config.caps if self.config is not None else caps_of(self.defaults, list(self.entries.values()))
        self.budget = Budget(caps, spent=self.log.spent(run))

    @property
    def mode(self) -> str | None:
        return None if self.config is None else self.config.mode

    def caller(self, name: str) -> Caller:
        return Caller(self.adapters[name], cache=self.cache, budget=self.budget, log=self.log,
                      retry=retry_policy(self.defaults), run=self.run, dry_run=self.dry_run,
                      chars_per_token=float(self.defaults["chars_per_token"]), sleep=self.sleep)


def startup_check(entries: list[ProviderEntry], adapters_by_name: dict[str, Adapter], defaults: dict, *,
                  test_call: bool = False, log: CallLog | None = None, sleep=time.sleep) -> list[dict]:
    """One row per entry: key present or missing, SDK, availability, capabilities, price, caps and the test call.
    The test call is sent only if asked, if the provider is available and if every cap it needs is set."""
    caps = caps_of(defaults, entries)
    log = log if log is not None else call_log(defaults)
    budget = Budget(caps, spent=log.spent(TEST_RUN) if test_call else None)
    rows = []
    for e in entries:
        a = adapters_by_name[e.name]
        ok, why = a.status()
        c = e.capabilities
        row = {"name": e.name, "provider": e.provider, "model": e.model, "model_verified": e.verified,
               "key_env": e.key_env, "key": a.key_state(), "sdk": a.sdk, "sdk_installed": a.sdk_installed(),
               "available": ok, "why": why, "structured_output": c.structured_output, "sampling": c.sampling,
               "context_tokens": c.context_tokens, "reasoning_default": c.reasoning_default,
               "reasoning_can_be_off": c.reasoning_off is not None,
               "price_in": None if e.price is None else e.price.input_per_mtok,
               "price_out": None if e.price is None else e.price.output_per_mtok,
               "price_verified": e.price is not None and e.price.verified,
               "cap_tokens": caps.provider_tokens.get(e.name), "cap_usd": caps.provider_usd.get(e.name)}
        if not test_call:
            row["test_call"] = "not run"
        elif not ok:
            row["test_call"] = "not run: unavailable"
        elif not caps_set(caps, e.name):
            row["test_call"] = "not run: the budget caps are not set"
        else:
            caller = Caller(a, cache=None, budget=budget, log=log, retry=retry_policy(defaults), run=TEST_RUN,
                            chars_per_token=float(defaults["chars_per_token"]), sleep=sleep)
            try:
                r = caller.complete(**TEST_CALL, tag=f"startup-check-{e.name}")
                row["test_call"] = f"ok: {r.usage.total} tokens, ${r.cost_usd:.4f}"
            except BudgetPaused as exc:
                row["test_call"] = f"not run: {exc}"
            except (Refusal, Truncated, OutputInvalid) as exc:
                row["test_call"] = f"ok: answered ({type(exc).__name__})"
            except Exception as exc:
                row["test_call"] = f"failed: {type(exc).__name__}"
        rows.append(row)
    return rows
