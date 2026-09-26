"""OpenAI through the Chat Completions API, with the openai SDK. The SDK is not a dependency: without it the provider
shows as unavailable. xai.py and openai_compatible.py send the same requests to other endpoints.

The client gets its key, base URL, organization and project explicitly, with the SDK's own retries off, so that the
SDK fills none of them from its own environment variables.
"""
from __future__ import annotations

import copy
import os

from ..schema import strict_schema, with_instruction
from .base import Adapter, Reply, Usage, count, field_of

BASE_URL = "https://api.openai.com/v1"
FINISH = {"stop": "end", "length": "max_tokens", "content_filter": "refusal"}


class OpenAIAdapter(Adapter):
    kind = "openai"
    sdk = "openai"
    sampling_params = ("temperature", "top_p")
    default_base_url: str | None = BASE_URL
    max_tokens_field = "max_completion_tokens"
    no_key: str | None = None       # the placeholder sent to an endpoint that takes no key

    def _read_key(self) -> str | None:
        return (os.environ.get(self.entry.key_env) or None) if self.entry.key_env else None

    def _make_client(self, key):
        import openai
        client = openai.OpenAI(api_key=key or self.no_key, base_url=self.entry.base_url or self.default_base_url,
                               organization="", project="", max_retries=0, timeout=self.timeout_s)
        client.organization = None  # passed as "" only so that the SDK does not read them; None sends no header
        client.project = None
        return client

    def request(self, *, system, user, max_tokens, schema=None, thinking=False, params=None) -> dict:
        caps = self.entry.capabilities
        if schema is not None and caps.structured_output != "json_schema":
            system = with_instruction(system, schema)
        body = {"model": self.entry.model, self.max_tokens_field: int(max_tokens),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        body.update(self.sampling(params))
        if not thinking and caps.reasoning_off:
            body.update(copy.deepcopy(dict(caps.reasoning_off)))
        if schema is not None and caps.structured_output == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "strict": True, "schema": strict_schema(schema, all_required=True)}}
        elif schema is not None and caps.structured_output == "json_object":
            body["response_format"] = {"type": "json_object"}
        return body

    def send(self, body: dict):
        return self.client().chat.completions.create(**body)

    def reply(self, raw) -> Reply:
        choices = field_of(raw, "choices", [])
        choice = choices[0] if choices else None
        message = field_of(choice, "message")
        u = field_of(raw, "usage")
        usage = Usage(input_tokens=count(u, "prompt_tokens"), output_tokens=count(u, "completion_tokens"),
                      thinking_tokens=count(field_of(u, "completion_tokens_details"), "reasoning_tokens"),
                      cache_read_tokens=count(field_of(u, "prompt_tokens_details"), "cached_tokens"))
        finish = field_of(choice, "finish_reason", "")
        stop = "refusal" if field_of(message, "refusal") else FINISH.get(finish, finish)
        return Reply(field_of(message, "content", ""), usage, stop, field_of(raw, "id"))
