"""Any OpenAI-compatible endpoint (a local Ollama, llama.cpp server or vLLM, or another service), with the openai SDK:
the requests of openai.py, sent to the entry's base_url, which is required. An endpoint that takes no key (key_env
null) gets a fixed placeholder, so that the SDK never reads a key from its own environment variables and never sends
a cloud provider's key to it.
"""
from __future__ import annotations

import os

from .openai import OpenAIAdapter


class OpenAICompatibleAdapter(OpenAIAdapter):
    kind = "openai_compatible"
    default_base_url = None
    max_tokens_field = "max_tokens"     # the older name, which every compatible server accepts
    no_key = "no-key"

    def _read_key(self) -> str | None:
        return (os.environ.get(self.entry.key_env) or None) if self.entry.key_env else None

    def status(self) -> tuple[bool, str]:
        if self._client is None and not self.entry.base_url:
            return False, "the entry has no base_url"
        return super().status()
