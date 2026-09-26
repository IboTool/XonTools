"""XonForge step 1 (XONFORGE_SPEC.md §4.1-4.2): the registry, the startup check, `python -m xonforge providers`, and
the locations that must stay outside the repository. Offline; never calls an API."""
import dataclasses
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from xon.config import XonConfig
from xon_common.budget import BudgetPaused, Caps
from xon_common.calllog import CallLog
from xon_common.providers import adapter_for
from xon_common.providers.base import Price
from xon_common.retry import RetryPolicy
from xon_common.worktrees import worktree_roots
from xonforge import locations, registry, runs
from xonforge.cli import format_providers
from xonforge_fakes import FakeClient, RESPONSES, anthropic_response, caller, entry, open_caps

ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------------------------------ the registry
CLAUDE = ["claude-sonnet", "claude-opus", "claude-fable"]


def test_the_registry_holds_the_sample_s_verified_claude_models_and_one_unverified_candidate_per_other_provider():
    entries = registry.load_entries()
    assert [(e.name, e.provider) for e in entries] == [
        ("claude-sonnet", "anthropic"), ("claude-opus", "anthropic"), ("claude-fable", "anthropic"),
        ("gpt", "openai"), ("gemini", "google"), ("grok", "xai"), ("local", "openai_compatible")]
    assert all(e.verified and e.price.verified and "2026-09-25" in e.source + e.price.source for e in entries[:3])
    assert all(e.price is not None and not e.price.verified and not e.verified and e.source for e in entries[3:])


def test_the_sample_s_model_ids_prices_and_request_shape_are_the_ones_checked_on_2026_09_25():
    entries = {e.name: e for e in registry.load_entries()}
    shown = {n: (entries[n].model, entries[n].price.input_per_mtok, entries[n].price.output_per_mtok,
                 entries[n].price.cache_read, entries[n].price.cache_write) for n in CLAUDE}
    assert shown == {"claude-sonnet": ("claude-sonnet-5", 2.0, 10.0, 0.1, 1.25),
                     "claude-opus": ("claude-opus-5-5", 4.0, 20.0, 0.05, 1.25),
                     "claude-fable": ("claude-fable-5-1", 10.0, 50.0, 0.025, 1.25)}
    for n in CLAUDE:
        caps = entries[n].capabilities
        assert (caps.sampling, caps.reasoning_default, caps.structured_output) == (False, "adaptive", "json_schema")
    assert entries["claude-sonnet"].capabilities.reasoning_off == {"thinking": {"type": "disabled"}}
    assert entries["claude-opus"].capabilities.reasoning_off is None
    assert entries["claude-fable"].capabilities.reasoning_off is None
    table = registry.load_yaml("prices.yaml")["anthropic"]
    assert {m: table[m]["retirement_not_before"] for m in table} == {
        "claude-fable-5-1": "2027-09-01", "claude-opus-5-5": "2027-09-22", "claude-sonnet-5": "2027-06-30",
        "claude-haiku-4-5-20251001": "2026-10-15"}


def test_a_cached_input_token_is_charged_at_its_own_rate():
    fable = Price(10.0, 50.0, cache_read=0.025, cache_write=1.25)
    assert fable.usd(1000, 100, cache_read_tokens=800, cache_write_tokens=100) == pytest.approx(
        ((100 + 800 * 0.025 + 100 * 1.25) * 10.0 + 100 * 50.0) / 1e6)
    assert fable.usd(1000, 100) == pytest.approx((1000 * 10.0 + 100 * 50.0) / 1e6)
    plain = Price(2.0, 10.0)
    assert plain.usd(1000, 100, 800, 100) == plain.usd(1000, 100) == pytest.approx(0.003)


def test_the_caller_charges_the_cache_rates_for_the_cached_tokens_the_provider_reports(tmp_path):
    e = entry("anthropic", name="claude-fable", price=(10.0, 50.0, True, "", 0.025, 1.25))
    reply = anthropic_response(input_tokens=40, output_tokens=12, cache_read_input_tokens=800,
                               cache_creation_input_tokens=100)
    result = caller(tmp_path, e, FakeClient(reply)).complete(system="s", user="u", max_tokens=100, tag="t")
    assert (result.usage.input_tokens, result.usage.cache_read_tokens, result.usage.cache_write_tokens) == (940, 800,
                                                                                                             100)
    cost = ((40 + 800 * 0.025 + 100 * 1.25) * 10.0 + 12 * 50.0) / 1e6
    assert result.cost_usd == pytest.approx(cost)
    row = CallLog(tmp_path / "log.jsonl").rows()[-1]
    assert (row["cache_read_tokens"], row["cache_write_tokens"], row["cost_usd"]) == (800, 100, round(cost, 6))


def test_the_worst_case_held_back_prices_the_input_at_the_cache_write_rate_where_that_is_higher(tmp_path):
    user = "u" * 4000
    probe = caller(tmp_path, entry("anthropic"), FakeClient(anthropic_response()), cache=False)
    estimate = probe.input_estimate(probe.adapter.request(system="s", user=user, max_tokens=100, schema=None,
                                                          thinking=False, params=None))
    for price, rate in (((2.0, 10.0), 1.0), ((2.0, 10.0, True, "", 0.1, 1.25), 1.25)):
        worst = (estimate * 2.0 * rate + 100 * 10.0) / 1e6
        for cap, sent in ((worst * 0.999, False), (worst * 1.001, True)):
            caps = Caps(run_tokens=10**6, run_usd=cap, provider_tokens={"anthropic": 10**6},
                        provider_usd={"anthropic": 1.0})
            call = caller(tmp_path, entry("anthropic", price=price), FakeClient(anthropic_response()), caps,
                          cache=False)
            if sent:
                assert call.complete(system="s", user=user, max_tokens=100, tag="t").source == "api"
            else:
                with pytest.raises(BudgetPaused):
                    call.complete(system="s", user=user, max_tokens=100, tag="t")


def test_each_provider_reads_its_key_only_from_xonforge_s_own_variable():
    assert {e.provider: e.key_env for e in registry.load_entries()} == {**registry.KEY_ENV, "openai_compatible": None}
    a1_key = "ANTHROPIC" + "_API_KEY"
    assert registry.key_env_error("anthropic", a1_key) and registry.key_env_error("openai", "OPENAI_API_KEY")
    assert registry.key_env_error("openai_compatible", "XONFORGE_OPENAI_KEY")
    assert registry.key_env_error("openai_compatible", "LOCAL_KEY")
    assert registry.key_env_error("openai_compatible", None) is None
    assert registry.key_env_error("openai_compatible", "XONFORGE_LOCAL_KEY") is None


@pytest.mark.parametrize("change, message", [
    ({"extra": 1}, "unknown fields"),
    ({"name": "Claude Sonnet"}, "a name is unique"),
    ({"provider": "mistral"}, "the provider is one of"),
    ({"key_env": "XONFORGE_OPENAI_KEY"}, "reads its key from XONFORGE_ANTHROPIC_KEY"),
    ({"roles": ["judge"]}, "the roles are among"),
    ({"capabilities": {"structured_output": "xml"}}, "structured_output must be one of"),
])
def test_the_registry_refuses_a_bad_entry(tmp_path, change, message):
    for name in ("prices.yaml", "defaults.yaml"):
        shutil.copy(registry.CONFIG_DIR / name, tmp_path / name)
    entries = registry.load_yaml("providers.yaml")
    entries[0] = {**entries[0], **change}
    (tmp_path / "providers.yaml").write_text(yaml.safe_dump(entries), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        registry.load_entries(tmp_path)


def test_the_defaults_hold_a1s_retry_values_no_caps_and_the_log_in_the_repository():
    defaults = registry.load_defaults()
    cfg = XonConfig()
    assert registry.retry_policy(defaults) == RetryPolicy(cfg.llm_retries, cfg.llm_backoff_s) == RetryPolicy(3, 2.0)
    assert defaults["chars_per_token"] == cfg.llm_chars_per_token
    assert registry.caps_of(defaults, registry.load_entries()) == Caps()
    assert registry.call_log(defaults).path == ROOT / "cache" / "xonforge" / "log.jsonl"
    with pytest.raises(ValueError, match="no registry entry is named"):
        registry.caps_of({"caps": {"provider_usd": {"nobody": 1.0}}}, registry.load_entries())


# ------------------------------------------------------------------------------------------ the startup check
def with_caps(**caps) -> dict:
    defaults = registry.load_defaults()
    return {**defaults, "caps": {**defaults["caps"], **caps}}


def fake_adapters(entries):
    return {e.name: adapter_for(e, client=FakeClient(RESPONSES[e.provider]())) for e in entries}


def test_the_startup_check_reports_each_key_as_present_or_missing_never_its_value(monkeypatch):
    for env in registry.KEY_ENV.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("XONFORGE_ANTHROPIC_KEY", "sk-canary-anthropic-0123456789")
    entries = registry.load_entries()
    defaults = registry.load_defaults()
    rows = registry.startup_check(entries, registry.adapters(entries, defaults), defaults)
    assert [(r["name"], r["key"]) for r in rows] == [
        ("claude-sonnet", "present"), ("claude-opus", "present"), ("claude-fable", "present"), ("gpt", "missing"),
        ("gemini", "missing"), ("grok", "missing"), ("local", "not needed")]
    assert all(r["available"] for r in rows[:3]) and not any(r["available"] for r in rows[3:6])
    assert {r["test_call"] for r in rows} == {"not run"}
    text = format_providers(rows, registry.caps_of(defaults, entries), registry.retry_policy(defaults))
    assert "canary" not in repr(rows) + text and "XONFORGE_ANTHROPIC_KEY: present" in text


def test_the_test_call_is_sent_only_when_asked_available_and_within_set_caps(tmp_path, monkeypatch):
    for env in registry.KEY_ENV.values():
        monkeypatch.delenv(env, raising=False)
    entries = registry.load_entries()
    names = [e.name for e in entries]
    log = CallLog(tmp_path / "log.jsonl")
    unset = registry.startup_check(entries, fake_adapters(entries), registry.load_defaults(), test_call=True, log=log)
    assert {r["test_call"] for r in unset} == {"not run: the budget caps are not set"} and not log.path.exists()
    defaults = with_caps(run_tokens=10**6, run_usd=5.0, provider_tokens={n: 10**5 for n in names},
                         provider_usd={n: 1.0 for n in names})
    adapters = fake_adapters(entries)
    rows = registry.startup_check(entries, adapters, defaults, test_call=True, log=log)
    assert all(r["test_call"].startswith("ok: 52 tokens") for r in rows)
    assert all(len(a._client.bodies) == 1 for a in adapters.values())
    assert {r["run"] for r in log.rows()} == {registry.TEST_RUN} and len(log.rows()) == 7
    cloud = [e for e in entries if e.key_env is not None]     # their keys are removed, so nothing can be sent
    unavailable = registry.startup_check(cloud, registry.adapters(cloud, defaults),
                                         with_caps(run_tokens=10**6, run_usd=5.0), test_call=True, log=log)
    assert {r["test_call"] for r in unavailable} == {"not run: unavailable"} and len(log.rows()) == 7


def test_a_test_call_that_is_refused_or_truncated_still_shows_the_key_works(tmp_path):
    entries = registry.load_entries()[:1]
    defaults = with_caps(run_tokens=10**6, run_usd=5.0, provider_tokens={"claude-sonnet": 10**5},
                         provider_usd={"claude-sonnet": 1.0})
    adapters = {"claude-sonnet": adapter_for(entries[0], client=FakeClient(anthropic_response(stop="max_tokens")))}
    rows = registry.startup_check(entries, adapters, defaults, test_call=True, log=CallLog(tmp_path / "log.jsonl"))
    assert rows[0]["test_call"] == "ok: answered (Truncated)"


def test_python_dash_m_xonforge_providers_makes_no_call_and_shows_no_key():
    env = {k: v for k, v in os.environ.items() if not k.startswith("XONFORGE_") and k != "ANTHROPIC" + "_API_KEY"}
    env.update(XONFORGE_ANTHROPIC_KEY="sk-canary-anthropic-0123456789", XONFORGE_OPENAI_KEY="sk-canary-openai-0123")
    out = subprocess.run([sys.executable, "-m", "xonforge", "providers"], cwd=ROOT, env=env, capture_output=True,
                         text=True)
    assert out.returncode == 0, out.stderr
    assert "canary" not in out.stdout + out.stderr
    assert "XONFORGE_ANTHROPIC_KEY: present" in out.stdout and "XONFORGE_GEMINI_KEY: missing" in out.stdout
    assert "not run" in out.stdout and "Run caps: tokens not set, USD not set." in out.stdout
    assert not (ROOT / "cache" / "xonforge").exists()


# ------------------------------------------------------------------------------------------ a run's session
def test_a_session_keeps_its_cache_only_outside_the_worktrees(tmp_path, monkeypatch):
    monkeypatch.delenv(locations.CACHE_ENV, raising=False)
    with pytest.raises(locations.LocationRefused, match="not set"):
        registry.Session("run-1", log=CallLog(tmp_path / "log.jsonl"))
    monkeypatch.setenv(locations.CACHE_ENV, str(ROOT / "cache" / "xonforge-responses"))
    with pytest.raises(locations.LocationRefused, match="inside the worktree"):
        registry.Session("run-1", log=CallLog(tmp_path / "log.jsonl"))
    monkeypatch.setenv(locations.CACHE_ENV, str(tmp_path / "cache"))
    assert registry.Session("run-1", log=CallLog(tmp_path / "log.jsonl")).cache.root == (tmp_path / "cache").resolve()


def test_a_session_s_callers_share_one_budget_and_a_resumed_run_starts_from_its_spending(tmp_path, monkeypatch):
    monkeypatch.setenv(locations.CACHE_ENV, str(tmp_path / "cache"))
    config = tmp_path / "config"
    shutil.copytree(registry.CONFIG_DIR, config)
    defaults = with_caps(run_tokens=1500, run_usd=5.0, provider_tokens={"claude-sonnet": 10**5, "gpt": 10**5},
                         provider_usd={"claude-sonnet": 1.0, "gpt": 1.0})
    (config / "defaults.yaml").write_text(yaml.safe_dump(defaults), encoding="utf-8")
    log = CallLog(tmp_path / "log.jsonl")
    clients = {"claude-sonnet": FakeClient(RESPONSES["anthropic"](input_tokens=400, output_tokens=200)),
               "gpt": FakeClient(RESPONSES["openai"](prompt_tokens=400, completion_tokens=200))}
    session = registry.Session("run-1", config_dir=config, log=log, clients=clients)
    session.caller("claude-sonnet").complete(system="s", user="u", max_tokens=100, tag="a")
    assert session.budget.spent() == (600, pytest.approx(0.0028))
    with pytest.raises(BudgetPaused, match="run's 1,500-token cap"):
        session.caller("gpt").complete(system="s", user="u" * 2000, max_tokens=100, tag="b")
    resumed = registry.Session("run-1", config_dir=config, log=log, clients=clients)
    assert resumed.budget.spent() == session.budget.spent()
    assert resumed.caller("claude-sonnet").complete(system="s", user="u", max_tokens=100, tag="a").source == "cache"
    assert registry.Session("run-2", config_dir=config, log=log, clients=clients).budget.spent() == (0, 0.0)


# ------------------------------------------------------------------------------------------ run configurations
def with_run(name: str, **raw) -> dict:
    defaults = registry.load_defaults()
    return {**defaults, "runs": {**defaults["runs"], name: raw}}


def sample_with(**caps) -> dict:
    sample = registry.load_defaults()["runs"]["sample"]
    return with_run("sample", **{**sample, "caps": {**sample["caps"], **caps}})


def by_name(entries=None) -> dict:
    return {e.name: e for e in (entries or registry.load_entries())}


def test_the_sample_is_a_pipeline_test_run_of_the_three_claude_models_within_40_dollars():
    entries = by_name()
    config = runs.load("sample", registry.load_defaults(), entries)
    assert (config.mode, config.renderers, config.reviewers) == ("pipeline_test", ("claude-sonnet",),
                                                                 ("claude-opus", "claude-fable"))
    assert config.entries == tuple(CLAUDE)
    assert config.caps == Caps(run_tokens=20_000_000, run_usd=40,
                               provider_tokens={n: 20_000_000 for n in CLAUDE},
                               provider_usd={n: 40 for n in CLAUDE})
    assert runs.problems(config, entries, fake_adapters(entries.values()), k=2) == []


def test_a_run_needs_its_entries_available_except_for_a_dry_run(monkeypatch):
    for env in registry.KEY_ENV.values():
        monkeypatch.delenv(env, raising=False)
    entries = by_name()
    config = runs.load("sample", sample_with(run_tokens=10**6, provider_tokens_each=10**5), entries)
    adapters = registry.adapters(list(entries.values()), registry.load_defaults())
    assert runs.problems(config, entries, adapters, k=2) == [
        f"{n} is unavailable: XONFORGE_ANTHROPIC_KEY is not set" for n in CLAUDE]
    assert runs.problems(config, entries, adapters, k=2, dry_run=True) == []


def test_an_entry_s_own_cap_overrides_the_cap_for_each():
    config = runs.load("sample", sample_with(provider_usd={"claude-fable": 5}), by_name())
    assert config.caps.provider_usd == {"claude-sonnet": 40, "claude-opus": 40, "claude-fable": 5}


@pytest.mark.parametrize("change, message", [
    ({"mode": None}, "names its mode, record or pipeline_test, and not None"),
    ({"mode": "test"}, "names its mode, record or pipeline_test, and not 'test'"),
    ({"reviewers": ["claude-opus", "nobody"]}, "no registry entry is named nobody"),
    ({"extra": 1}, "unknown fields extra"),
    ({"caps": {"run_dollars": 1}}, "unknown fields caps.run_dollars"),
    ({"caps": {"provider_usd": {"gpt": 1}}}, "caps.provider_usd: gpt is not an entry the run uses"),
])
def test_a_malformed_run_configuration_is_refused(change, message):
    sample = registry.load_defaults()["runs"]["sample"]
    with pytest.raises(ValueError, match=message):
        runs.load("sample", with_run("sample", **{**sample, **change}), by_name())
    with pytest.raises(ValueError, match="no run configuration named 'nothing'"):
        runs.load("nothing", registry.load_defaults(), by_name())


def test_a_run_s_entries_need_verified_model_ids_and_prices_and_their_roles():
    entries = by_name()
    raw = {"mode": "pipeline_test", "renderers": ["gpt"], "reviewers": ["claude-opus", "claude-fable"],
           "caps": {"run_tokens": 10**6, "run_usd": 20, "provider_tokens_each": 10**5, "provider_usd_each": 20}}
    config = runs.load("r", with_run("r", **raw), entries)
    assert runs.problems(config, entries, fake_adapters(entries.values()), k=2) == [
        "gpt: its model id is not verified in the provider's documentation", "gpt: its price is not verified"]
    renderer_only = {**entries, "claude-fable": dataclasses.replace(entries["claude-fable"], roles=("render",))}
    config = runs.load("sample", sample_with(run_tokens=10**6, provider_tokens_each=10**5), renderer_only)
    assert runs.problems(config, renderer_only, fake_adapters(renderer_only.values()), k=2) == [
        "not registered for the review role: claude-fable",
        "renderer claude-sonnet: not registered for the review role: claude-fable"]


def test_a_corpus_of_record_run_refuses_to_start_with_fewer_than_three_configured_providers():
    entries = by_name()
    caps = {"run_tokens": 10**6, "run_usd": 250, "provider_tokens_each": 10**5, "provider_usd_each": 100}
    claude = runs.load("r", with_run("r", mode="record", renderers=["claude-sonnet"],
                                     reviewers=["claude-opus", "claude-fable"], caps=caps), entries)
    assert runs.problems(claude, entries, fake_adapters(entries.values()), k=2) == [
        "renderer claude-sonnet: 2 reviewers are needed from providers other than the renderer's (anthropic), and 0 "
        "of the listed ones are",
        "a corpus-of-record run needs at least 3 configured providers, and its entries have 1 (anthropic)"]
    mixed = runs.load("r", with_run("r", mode="record", renderers=["claude-sonnet"], reviewers=["gpt", "gemini"],
                                    caps=caps), entries)
    found = runs.problems(mixed, entries, fake_adapters(entries.values()), k=2)
    assert found[-1] == "a corpus-of-record run needs at least 3 configured providers, and its entries have 1 " \
                        "(anthropic)"
    checked = {**entries, **{n: dataclasses.replace(entries[n], verified=True, price=dataclasses.replace(
        entries[n].price, verified=True)) for n in ("gpt", "gemini")}}
    assert runs.problems(mixed, checked, fake_adapters(checked.values()), k=2) == []
    first = runs.load("first_corpus", registry.load_defaults(), entries)
    assert (first.mode, first.caps.run_usd, first.caps.run_tokens) == ("record", 250, None)
    assert runs.problems(first, entries, fake_adapters(entries.values()), k=2) == [
        "no renderer is chosen", "the token caps are not set (the run's), and the budget sends no call without them",
        "a corpus-of-record run needs at least 3 configured providers, and its entries have 0"]


def test_a_session_started_with_a_run_configuration_takes_its_mode_and_caps_or_refuses_to_start(tmp_path,
                                                                                                monkeypatch):
    monkeypatch.setenv(locations.CACHE_ENV, str(tmp_path / "cache"))
    config = tmp_path / "config"
    shutil.copytree(registry.CONFIG_DIR, config)
    log = CallLog(tmp_path / "log.jsonl")
    clients = {n: FakeClient(anthropic_response()) for n in CLAUDE}
    session = registry.Session("run-1", run_config="sample", config_dir=config, log=log, clients=clients)
    assert session.mode == "pipeline_test" and session.budget.caps == session.config.caps
    assert session.budget.caps.provider_usd == {n: 40 for n in CLAUDE} and session.budget.caps.run_usd == 40
    assert registry.Session("run-1", config_dir=config, log=log, clients=clients).mode is None


def test_python_dash_m_xonforge_run_check_shows_why_the_sample_may_not_start_yet():
    env = {k: v for k, v in os.environ.items() if not k.startswith("XONFORGE_") and k != "ANTHROPIC" + "_API_KEY"}
    out = subprocess.run([sys.executable, "-m", "xonforge", "run-check", "sample"], cwd=ROOT, env=env,
                         capture_output=True, text=True)
    assert out.returncode == 1, out.stderr
    assert "mode pipeline_test: its documents are labelled pipeline_test" in out.stdout
    assert "Renderers: claude-sonnet (claude-sonnet-5). Reviewers: claude-opus (claude-opus-5-5), claude-fable " \
           "(claude-fable-5-1)." in out.stdout
    assert "Run caps: tokens 20,000,000, USD $40.00." in out.stdout
    assert "- claude-sonnet is unavailable: XONFORGE_ANTHROPIC_KEY is not set" in out.stdout
    dry = subprocess.run([sys.executable, "-m", "xonforge", "run-check", "sample", "--dry-run"], cwd=ROOT, env=env,
                         capture_output=True, text=True)
    assert dry.returncode == 0 and "unavailable" not in dry.stdout and "It may start as a dry run." in dry.stdout
    missing = subprocess.run([sys.executable, "-m", "xonforge", "run-check", "nothing"], cwd=ROOT, env=env,
                             capture_output=True, text=True)
    assert missing.returncode == 2 and "no run configuration named 'nothing'" in missing.stdout
    assert not (ROOT / "cache" / "xonforge").exists()


# ------------------------------------------------------------------------------------------ locations
def test_a_location_is_refused_when_its_variable_is_unset(monkeypatch):
    for env in (locations.CACHE_ENV, locations.SEALED_ENV, locations.JUDGED_ENV):
        monkeypatch.delenv(env, raising=False)
    for where in (locations.cache_dir, locations.sealed_dir, locations.judged_dir, locations.text_log_dir):
        with pytest.raises(locations.LocationRefused, match="not set"):
            where()


def test_a_location_inside_any_worktree_is_refused(monkeypatch):
    roots = worktree_roots()
    if (ROOT / ".git").exists():
        assert ROOT in roots
    for root in sorted({ROOT, *roots}):
        for env, where in ((locations.CACHE_ENV, locations.cache_dir), (locations.SEALED_ENV, locations.sealed_dir),
                           (locations.JUDGED_ENV, locations.judged_dir)):
            monkeypatch.setenv(env, str(root / "somewhere" / "inside"))
            with pytest.raises(locations.LocationRefused, match="inside the worktree"):
                where()
    monkeypatch.setenv(locations.CACHE_ENV, str(ROOT / "cache-dir"))
    with pytest.raises(locations.LocationRefused):
        locations.text_log_dir()


def test_locations_outside_the_worktrees_are_used_and_text_logs_go_under_the_cache_s_parent(tmp_path, monkeypatch):
    monkeypatch.setenv(locations.CACHE_ENV, str(tmp_path / "xonforge" / "cache"))
    monkeypatch.setenv(locations.SEALED_ENV, str(tmp_path / "sealed"))
    monkeypatch.setenv(locations.JUDGED_ENV, str(tmp_path / "judged"))
    assert locations.cache_dir() == (tmp_path / "xonforge" / "cache").resolve()
    assert locations.text_log_dir() == (tmp_path / "xonforge").resolve()
    assert (locations.sealed_dir(), locations.judged_dir()) == ((tmp_path / "sealed").resolve(),
                                                                (tmp_path / "judged").resolve())


def test_every_worktree_is_found_from_git_s_own_files(tmp_path):
    main, linked = tmp_path / "main", tmp_path / "linked"
    link = main / ".git" / "worktrees" / "linked"
    link.mkdir(parents=True)
    linked.mkdir()
    (link / "gitdir").write_text(str(linked / ".git") + "\n", encoding="utf-8")
    (link / "commondir").write_text("../..\n", encoding="utf-8")
    (linked / ".git").write_text(f"gitdir: {link}\n", encoding="utf-8")
    assert worktree_roots(linked / "sub") == worktree_roots(main) == sorted([main.resolve(), linked.resolve()])
    assert main.resolve() not in worktree_roots(tmp_path / "elsewhere")
