"""Google (Gemini) through generate_content, with the google-genai SDK. The SDK is not a dependency: without it the
provider shows as unavailable.

The client gets its key explicitly and is told it is not Vertex AI, so that the SDK takes neither a key nor Google
Cloud credentials from its environment. The request body is plain data (the SDK accepts a dict as the config), so it
can be hashed as sent.
"""
from __future__ import annotations

import copy
import os

from ..retry import TransportError, retry_after, sdk_error
from ..schema import strict_schema, with_instruction
from .base import Adapter, Reply, Usage, count, field_of

FINISH = {"STOP": "end", "MAX_TOKENS": "max_tokens", "SAFETY": "refusal", "RECITATION": "refusal",
          "BLOCKLIST": "refusal", "PROHIBITED_CONTENT": "refusal", "SPII": "refusal"}


def _name(value) -> str:
    """An SDK enum's name ("STOP"), or the string a fake gives."""
    return str(getattr(value, "name", value) or "")


class GoogleAdapter(Adapter):
    kind = "google"
    sdk = "google.genai"
    sampling_params = ("temperature", "top_p", "top_k")

    def _read_key(self) -> str | None:
        return (os.environ.get(self.entry.key_env) or None) if self.entry.key_env else None

    def _make_client(self, key):
        from google import genai
        options = {"timeout": int(self.timeout_s * 1000)}
        if self.entry.base_url:
            options["base_url"] = self.entry.base_url
        return genai.Client(api_key=key, vertexai=False, http_options=options)

    def request(self, *, system, user, max_tokens, schema=None, thinking=False, params=None) -> dict:
        caps = self.entry.capabilities
        if schema is not None and caps.structured_output != "json_schema":
            system = with_instruction(system, schema)
        config = {"system_instruction": system, "max_output_tokens": int(max_tokens), **self.sampling(params)}
        if not thinking and caps.reasoning_off:
            config.update(copy.deepcopy(dict(caps.reasoning_off)))
        if schema is not None and caps.structured_output in ("json_schema", "json_object"):
            config["response_mime_type"] = "application/json"
        if schema is not None and caps.structured_output == "json_schema":
            config["response_json_schema"] = strict_schema(schema)
        return {"model": self.entry.model, "contents": user, "config": config}

    def send(self, body: dict):
        return self.client().models.generate_content(model=body["model"], contents=body["contents"],
                                                     config=body["config"])

    def reply(self, raw) -> Reply:
        u = field_of(raw, "usage_metadata")
        thoughts = count(u, "thoughts_token_count")
        usage = Usage(input_tokens=count(u, "prompt_token_count"),
                      output_tokens=count(u, "candidates_token_count") + thoughts, thinking_tokens=thoughts,
                      cache_read_tokens=count(u, "cached_content_token_count"))
        candidates = field_of(raw, "candidates", [])
        finish = _name(field_of(candidates[0], "finish_reason")) if candidates else ""
        blocked = _name(field_of(field_of(raw, "prompt_feedback"), "block_reason"))
        stop = "refusal" if blocked or not candidates else FINISH.get(finish, finish)
        text = (field_of(raw, "text", "") or "") if candidates else ""
        return Reply(text, usage, stop, field_of(raw, "response_id"))

    def transport_error(self, exc: BaseException) -> TransportError | None:
        """google-genai's APIError carries the HTTP status as ``code``; failures with no response come from httpx."""
        code = getattr(exc, "code", None)
        if isinstance(code, int) and any(c.__name__ == "APIError" for c in type(exc).__mro__):
            return TransportError(code, False, retry_after(exc))
        return sdk_error(exc)
