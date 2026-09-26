"""Fakes for XonForge's offline tests: clients shaped as the three SDKs, their errors, their responses, and registry
entries. No test calls an API."""
from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from xon_common.budget import Budget, Caps
from xon_common.cache import ResponseCache
from xon_common.caller import Caller
from xon_common.calllog import CallLog
from xon_common.providers import adapter_for
from xon_common.providers.base import Capabilities, Price, ProviderEntry
from xon_common.retry import RetryPolicy

KEY_ENV = {"anthropic": "XONFORGE_ANTHROPIC_KEY", "openai": "XONFORGE_OPENAI_KEY", "google": "XONFORGE_GEMINI_KEY",
           "xai": "XONFORGE_XAI_KEY", "openai_compatible": None}
SYSTEM, USER = "SYSTEM-PROMPT-MARKER plant nothing", "USER-PROMPT-MARKER Ana is older than Ben."
RESPONSE = "RESPONSE-TEXT-MARKER Ana is older than Ben."


class Verdict(BaseModel):
    consistent: bool
    reason: str


class StatusError(Exception):
    """Shaped as the Anthropic and OpenAI SDKs' HTTP errors."""

    def __init__(self, status: int, retry_after: str | None = None):
        super().__init__(f"HTTP {status}")
        self.status_code = status
        self.response = SimpleNamespace(headers={} if retry_after is None else {"retry-after": retry_after})


class APIConnectionError(Exception):
    """Named as the Anthropic and OpenAI SDKs' failure with no response."""


class APITimeoutError(APIConnectionError):
    pass


class APIError(Exception):
    """Shaped as google-genai's errors: the HTTP status as ``code``."""

    def __init__(self, code: int, retry_after: str | None = None):
        super().__init__(f"HTTP {code}")
        self.code = code
        self.response = SimpleNamespace(headers={} if retry_after is None else {"retry-after": retry_after})


def anthropic_response(text=RESPONSE, stop="end_turn", input_tokens=40, output_tokens=12, **usage):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop, id="msg_fake",
                           usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, **usage))


def openai_response(text=RESPONSE, finish="stop", refusal=None, prompt_tokens=40, completion_tokens=12, reasoning=0,
                    cached=0):
    return SimpleNamespace(
        id="chatcmpl-fake",
        choices=[SimpleNamespace(message=SimpleNamespace(content=text, refusal=refusal), finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                              completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning),
                              prompt_tokens_details=SimpleNamespace(cached_tokens=cached)))


def google_response(text=RESPONSE, finish="STOP", prompt=40, candidates=12, thoughts=0, block_reason=None,
                    no_candidates=False):
    return SimpleNamespace(
        text=text, response_id="resp-fake",
        candidates=[] if no_candidates else [SimpleNamespace(finish_reason=SimpleNamespace(name=finish))],
        prompt_feedback=SimpleNamespace(block_reason=block_reason),
        usage_metadata=SimpleNamespace(prompt_token_count=prompt, candidates_token_count=candidates,
                                       thoughts_token_count=thoughts))


RESPONSES = {"anthropic": anthropic_response, "openai": openai_response, "xai": openai_response,
             "openai_compatible": openai_response, "google": google_response}


class FakeClient:
    """Answers each call with the next reply (the last one repeats); a reply that is an exception is raised. Records
    each request as sent. Shaped as all three SDKs: messages.create, chat.completions.create and
    models.generate_content."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.bodies: list[dict] = []
        self.messages = SimpleNamespace(create=self._call)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._call))
        self.models = SimpleNamespace(generate_content=self._call)

    def _call(self, **body):
        self.bodies.append(body)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, BaseException):
            raise reply
        return reply


def entry(provider="anthropic", name=None, model="model-x", price=(2.0, 10.0), base_url=None, key_env="default",
          **caps) -> ProviderEntry:
    return ProviderEntry(name=name or provider.replace("_", "-"), provider=provider, model=model,
                         key_env=KEY_ENV[provider] if key_env == "default" else key_env,
                         base_url=base_url or ("http://localhost:11434/v1" if provider == "openai_compatible" else None),
                         capabilities=Capabilities(**caps), price=None if price is None else Price(*price))


def open_caps(*names: str) -> Caps:
    """Caps high enough never to stop a test's calls."""
    return Caps(run_tokens=10**7, run_usd=100.0, provider_tokens={n: 10**7 for n in names},
                provider_usd={n: 100.0 for n in names})


def caller(tmp_path, e: ProviderEntry, client, caps: Caps | None = None, *, dry_run=False, run="run-1", sleeps=None,
           retries=3, cache=True) -> Caller:
    adapter = adapter_for(e, client=client)
    return Caller(adapter, cache=ResponseCache(tmp_path / "cache") if cache else None,
                  budget=Budget(caps if caps is not None else open_caps(e.name)), log=CallLog(tmp_path / "log.jsonl"),
                  retry=RetryPolicy(retries, 2.0), run=run, dry_run=dry_run,
                  sleep=(sleeps.append if sleeps is not None else (lambda s: None)))
