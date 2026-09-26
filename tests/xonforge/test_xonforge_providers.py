"""XonForge step 1 (XONFORGE_SPEC.md §4.2): the five provider modules, offline with fake clients and fake SDK modules.
Never calls an API."""
import importlib.machinery
import inspect
import sys
import types

import httpx
import pytest
from pydantic import BaseModel

from xon.config import LLM_CAPABILITIES
from xon.llm import client as a1_client
from xon.llm import schemas as a1_schemas
from xon_common.hashing import request_key
from xon_common.providers import ADAPTERS, adapter_for
from xon_common.providers.base import ProviderEntry, ProviderUnavailable
from xon_common.retry import TransportError
from xon_common.schema import ANTHROPIC_UNSUPPORTED, json_instruction, strict_schema
from xonforge_fakes import (SYSTEM, USER, APIConnectionError, APIError, FakeClient, StatusError, Verdict,
                            anthropic_response, entry, google_response, openai_response)

OPENAI_STYLE = ("openai", "xai", "openai_compatible")


def body(provider, **kw):
    caps = {k: kw.pop(k) for k in ("sampling", "structured_output", "reasoning_off", "reasoning_default") if k in kw}
    return adapter_for(entry(provider, **caps)).request(**{"system": SYSTEM, "user": USER, "max_tokens": 500, **kw})


# ------------------------------------------------------------------------------------------ parity with A1
A1_SCHEMAS = [cls for _, cls in inspect.getmembers(a1_schemas, inspect.isclass)
              if issubclass(cls, BaseModel) and cls.__module__ == a1_schemas.__name__ and not cls.__name__.startswith("_")]


@pytest.mark.parametrize("model", sorted(LLM_CAPABILITIES))
@pytest.mark.parametrize("thinking", [False, True])
@pytest.mark.parametrize("schema", [None, a1_schemas.ClaimList, a1_schemas.RelationListV22])
def test_the_anthropic_request_is_the_one_a1_sends(tmp_path, model, thinking, schema):
    """Same model, prompt, schema and settings: the same body, so the same request key (A1 sends its configured
    temperature to models that accept sampling parameters; XonForge sends one when the caller passes it)."""
    caps = LLM_CAPABILITIES[model]
    a1 = a1_client.LLM(model=model, cache_dir=tmp_path, client=FakeClient(None))
    ours = adapter_for(entry("anthropic", model=model, sampling=caps["sampling"], structured_output="json_schema",
                             reasoning_default=caps["thinking_default"],
                             reasoning_off={"thinking": {"type": "disabled"}} if caps["thinking_can_disable"] else None))
    theirs = a1.request(system=SYSTEM, user=USER, max_tokens=700, thinking=thinking, schema=schema)
    mine = ours.request(system=SYSTEM, user=USER, max_tokens=700, thinking=thinking, schema=schema,
                        params={"temperature": a1.cfg.llm_temperature} if caps["sampling"] else None)
    assert mine == theirs and request_key(mine) == a1_client.request_key(theirs)


@pytest.mark.parametrize("schema", A1_SCHEMAS, ids=lambda s: s.__name__)
def test_the_strict_anthropic_schema_is_a1s_for_every_a1_schema(schema):
    try:
        expected = a1_client.output_schema(schema)
    except ValueError:
        with pytest.raises(ValueError):
            strict_schema(schema, unsupported=ANTHROPIC_UNSUPPORTED, max_min_items=1)
        return
    assert strict_schema(schema, unsupported=ANTHROPIC_UNSUPPORTED, max_min_items=1) == expected


# ------------------------------------------------------------------------------------------ requests
def sent_params(provider, b):
    return b["config"] if provider == "google" else b


@pytest.mark.parametrize("provider", sorted(ADAPTERS))
def test_sampling_parameters_are_sent_only_where_accepted(provider):
    assert "temperature" not in sent_params(provider, body(provider, sampling=False, params={"temperature": 0.3}))
    assert sent_params(provider, body(provider, sampling=True, params={"temperature": 0.3}))["temperature"] == 0.3
    with pytest.raises(ValueError, match="unknown parameters"):
        body(provider, sampling=True, params={"frequency_penalty": 0.1})
    if provider in OPENAI_STYLE:
        with pytest.raises(ValueError, match="has no top_k"):
            body(provider, sampling=True, params={"top_k": 5})
    else:
        assert sent_params(provider, body(provider, sampling=True, params={"top_k": 5}))["top_k"] == 5


@pytest.mark.parametrize("provider, off", [("anthropic", {"thinking": {"type": "disabled"}}),
                                           ("openai", {"reasoning_effort": "minimal"}),
                                           ("google", {"thinking_config": {"thinking_budget": 0}})])
def test_reasoning_is_turned_off_only_where_the_model_allows_it(provider, off):
    field = next(iter(off))
    assert sent_params(provider, body(provider, reasoning_off=off))[field] == off[field]
    assert field not in sent_params(provider, body(provider, reasoning_off=off, thinking=True))
    assert field not in sent_params(provider, body(provider, reasoning_off=None))


def test_structured_output_follows_each_model_s_capability():
    strict = strict_schema(Verdict, unsupported=ANTHROPIC_UNSUPPORTED, max_min_items=1)
    b = body("anthropic", structured_output="json_schema", schema=Verdict)
    assert b["output_config"] == {"format": {"type": "json_schema", "schema": strict}} and b["system"] == SYSTEM
    b = body("anthropic", structured_output="prompt", schema=Verdict)
    assert "output_config" not in b and b["system"].endswith(json_instruction(Verdict))
    for provider in OPENAI_STYLE:
        b = body(provider, structured_output="json_schema", schema=Verdict)
        schema = b["response_format"]["json_schema"]
        assert schema["strict"] is True and schema["schema"]["required"] == ["consistent", "reason"]
        assert schema["schema"]["additionalProperties"] is False and b["messages"][0]["content"] == SYSTEM
        b = body(provider, structured_output="json_object", schema=Verdict)
        assert b["response_format"] == {"type": "json_object"}
        assert b["messages"][0]["content"].endswith(json_instruction(Verdict))
        b = body(provider, structured_output="prompt", schema=Verdict)
        assert "response_format" not in b and b["messages"][0]["content"].endswith(json_instruction(Verdict))
    config = body("google", structured_output="json_schema", schema=Verdict)["config"]
    assert config["response_mime_type"] == "application/json" and config["response_json_schema"] == strict_schema(
        Verdict) and config["system_instruction"] == SYSTEM
    config = body("google", structured_output="json_object", schema=Verdict)["config"]
    assert "response_json_schema" not in config and config["system_instruction"].endswith(json_instruction(Verdict))


def test_each_api_gets_its_own_request_shape():
    assert body("openai")["max_completion_tokens"] == body("xai")["max_completion_tokens"] == 500
    assert body("openai_compatible")["max_tokens"] == 500 and "max_completion_tokens" not in body("openai_compatible")
    assert body("openai")["messages"] == [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}]
    g = body("google")
    assert g == {"model": "model-x", "contents": USER, "config": {"system_instruction": SYSTEM,
                                                                  "max_output_tokens": 500}}


@pytest.mark.parametrize("provider", sorted(ADAPTERS))
def test_each_adapter_sends_through_its_sdk_s_method(provider):
    responses = {"anthropic": anthropic_response(), "google": google_response()}
    fake = FakeClient(responses.get(provider, openai_response()))
    a = adapter_for(entry(provider), client=fake)
    b = a.request(system=SYSTEM, user=USER, max_tokens=500)
    a.send(b)
    assert fake.bodies == [b]


# ------------------------------------------------------------------------------------------ responses
def test_the_anthropic_reply_is_read_as_a1_reads_it():
    a = adapter_for(entry("anthropic"))
    r = a.reply(anthropic_response(input_tokens=30, output_tokens=12, cache_creation_input_tokens=5,
                                   cache_read_input_tokens=7))
    assert (r.text, r.stop, r.request_id) == ("RESPONSE-TEXT-MARKER Ana is older than Ben.", "end", "msg_fake")
    assert (r.usage.input_tokens, r.usage.output_tokens, r.usage.cache_read_tokens) == (42, 12, 7)
    assert [a.reply(anthropic_response(stop=s)).stop for s in ("stop_sequence", "max_tokens", "refusal", "pause_turn")
            ] == ["end", "max_tokens", "refusal", "pause_turn"]


@pytest.mark.parametrize("provider", OPENAI_STYLE)
def test_an_openai_style_reply_is_read(provider):
    a = adapter_for(entry(provider))
    r = a.reply(openai_response(prompt_tokens=30, completion_tokens=20, reasoning=8, cached=10))
    assert (r.stop, r.request_id, r.usage.input_tokens, r.usage.output_tokens) == ("end", "chatcmpl-fake", 30, 20)
    assert (r.usage.thinking_tokens, r.usage.cache_read_tokens) == (8, 10)
    assert a.reply(openai_response(finish="length")).stop == "max_tokens"
    assert a.reply(openai_response(finish="content_filter")).stop == "refusal"
    assert a.reply(openai_response(text=None, refusal="I can't help with that.")).stop == "refusal"


def test_a_gemini_reply_is_read():
    a = adapter_for(entry("google"))
    r = a.reply(google_response(prompt=30, candidates=20, thoughts=9))
    assert (r.stop, r.request_id, r.usage.input_tokens, r.usage.output_tokens, r.usage.thinking_tokens) == (
        "end", "resp-fake", 30, 29, 9)
    assert a.reply(google_response(finish="MAX_TOKENS")).stop == "max_tokens"
    assert a.reply(google_response(finish="SAFETY")).stop == "refusal"
    assert a.reply(google_response(block_reason=types.SimpleNamespace(name="SAFETY"))).stop == "refusal"
    assert a.reply(google_response(no_candidates=True)).stop == "refusal"


@pytest.mark.parametrize("provider", sorted(ADAPTERS))
def test_each_adapter_reads_a_failed_send(provider):
    a = adapter_for(entry(provider))
    http = APIError(429, retry_after="3") if provider == "google" else StatusError(429, retry_after="3")
    assert a.transport_error(http) == TransportError(429, False, 3.0)
    assert a.transport_error(APIConnectionError("lost")) == TransportError(None, True, 0.0)
    assert a.transport_error(httpx.ConnectError("lost")) == TransportError(None, True, 0.0)
    assert a.transport_error(httpx.ReadTimeout("slow")) == TransportError(None, True, 0.0)
    assert a.transport_error(ValueError("a bug")) is None


# ------------------------------------------------------------------------------------------ availability and clients
def test_a_provider_without_its_key_its_sdk_or_its_endpoint_is_unavailable(monkeypatch):
    monkeypatch.delenv("XONFORGE_OPENAI_KEY", raising=False)
    a = adapter_for(entry("openai"))
    assert (a.key_state(), a.status()) == ("missing", (False, "XONFORGE_OPENAI_KEY is not set"))
    with pytest.raises(ProviderUnavailable):
        a.client()
    monkeypatch.setenv("XONFORGE_OPENAI_KEY", "")
    assert adapter_for(entry("openai")).key_state() == "missing"
    monkeypatch.setenv("XONFORGE_OPENAI_KEY", "sk-xonforge-test")
    monkeypatch.setattr(type(a), "sdk", "xonforge_no_such_sdk")
    assert adapter_for(entry("openai")).status() == (False, "the xonforge_no_such_sdk SDK is not installed")
    assert adapter_for(entry("openai_compatible")).key_state() == "not needed"
    no_url = ProviderEntry(name="local", provider="openai_compatible", model="m", key_env=None)
    assert adapter_for(no_url).status() == (False, "the entry has no base_url")


def test_the_anthropic_client_takes_nothing_from_the_sdk_s_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC" + "_API_KEY", "a1-key-canary")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-canary")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://base-canary.invalid")
    monkeypatch.setenv("XONFORGE_ANTHROPIC_KEY", "xonforge-key-canary")
    client = adapter_for(entry("anthropic"), timeout_s=30).client()
    assert client.api_key == "xonforge-key-canary" and client.auth_token is None
    assert client.auth_headers == {"X-Api-Key": "xonforge-key-canary"}
    assert str(client.base_url).rstrip("/") == "https://api.anthropic.com" and client.max_retries == 0
    monkeypatch.setenv("XONFORGE_ANTHROPIC_KEY", "")
    with pytest.raises(ProviderUnavailable, match="XONFORGE_ANTHROPIC_KEY is not set"):
        adapter_for(entry("anthropic")).client()


def fake_sdk(monkeypatch, name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(name, None)
    for k, v in attrs.items():
        setattr(module, k, v)
    monkeypatch.setitem(sys.modules, name, module)
    return module


class Recorder:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.organization, self.project = kwargs.get("organization"), kwargs.get("project")


@pytest.mark.parametrize("provider, key_env, url", [
    ("openai", "XONFORGE_OPENAI_KEY", "https://api.openai.com/v1"),
    ("xai", "XONFORGE_XAI_KEY", "https://api.x.ai/v1"),
    ("openai_compatible", None, "http://localhost:11434/v1"),
])
def test_the_openai_sdk_gets_every_setting_explicitly(monkeypatch, provider, key_env, url):
    fake_sdk(monkeypatch, "openai", OpenAI=Recorder)
    if key_env:
        monkeypatch.setenv(key_env, f"{provider}-key-canary")
    client = adapter_for(entry(provider), timeout_s=30).client()
    assert client.kwargs == {"api_key": f"{provider}-key-canary" if key_env else "no-key", "base_url": url,
                             "organization": "", "project": "", "max_retries": 0, "timeout": 30.0}
    assert client.organization is None and client.project is None


def test_the_google_sdk_gets_its_key_explicitly_and_is_not_vertex(monkeypatch):
    genai = fake_sdk(monkeypatch, "google.genai", Client=Recorder)
    fake_sdk(monkeypatch, "google", genai=genai)
    monkeypatch.setenv("XONFORGE_GEMINI_KEY", "gemini-key-canary")
    client = adapter_for(entry("google"), timeout_s=30).client()
    assert client.kwargs == {"api_key": "gemini-key-canary", "vertexai": False, "http_options": {"timeout": 30000}}
