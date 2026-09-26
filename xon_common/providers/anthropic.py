"""Anthropic (Claude) through the Messages API. Besides xon/llm/client.py, this is the one module A1's test allows to
import anthropic (tests/test_llm_client.py).

The request has the form A1's client sends for the same model, prompt, schema and settings, so its hash is the one A1
computes. The client gets its key, base URL and authentication explicitly, with the SDK's own retries off: left as
None, the SDK would fill each from its own environment variables, A1's key among them.
"""
from __future__ import annotations

import copy
import os

from ..schema import ANTHROPIC_UNSUPPORTED, strict_schema, with_instruction
from .base import Adapter, Reply, Usage, count, field_of

BASE_URL = "https://api.anthropic.com"
STOPS = {"end_turn": "end", "stop_sequence": "end", "max_tokens": "max_tokens", "refusal": "refusal"}


class AnthropicAdapter(Adapter):
    kind = "anthropic"
    sdk = "anthropic"
    sampling_params = ("temperature", "top_p", "top_k")

    def _read_key(self) -> str | None:
        return (os.environ.get(self.entry.key_env) or None) if self.entry.key_env else None

    def _make_client(self, key):
        import anthropic
        client = anthropic.Anthropic(api_key=key, auth_token="", base_url=self.entry.base_url or BASE_URL,
                                     max_retries=0, timeout=self.timeout_s)
        client.auth_token = None    # passed as "" only so that the SDK does not read one; "" would send "Bearer "
        return client

    def request(self, *, system, user, max_tokens, schema=None, thinking=False, params=None) -> dict:
        caps = self.entry.capabilities
        body = {"model": self.entry.model, "max_tokens": int(max_tokens), "system": system,
                "messages": [{"role": "user", "content": user}]}
        body.update(self.sampling(params))
        if not thinking and caps.reasoning_off:
            body.update(copy.deepcopy(dict(caps.reasoning_off)))
        if schema is not None:
            if caps.structured_output == "json_schema":
                body["output_config"] = {"format": {"type": "json_schema", "schema": strict_schema(
                    schema, unsupported=ANTHROPIC_UNSUPPORTED, max_min_items=1)}}
            else:
                body["system"] = with_instruction(system, schema)
        return body

    def send(self, body: dict):
        return self.client().messages.create(**body)

    def reply(self, raw) -> Reply:
        u = field_of(raw, "usage")
        write, read = count(u, "cache_creation_input_tokens"), count(u, "cache_read_input_tokens")
        usage = Usage(input_tokens=count(u, "input_tokens") + write + read, output_tokens=count(u, "output_tokens"),
                      thinking_tokens=count(field_of(u, "output_tokens_details"), "thinking_tokens"),
                      cache_read_tokens=read, cache_write_tokens=write)
        text = "".join(field_of(b, "text", "") for b in field_of(raw, "content", []) if field_of(b, "type") == "text")
        stop = field_of(raw, "stop_reason", "")
        return Reply(text, usage, STOPS.get(stop, stop), field_of(raw, "id"))
