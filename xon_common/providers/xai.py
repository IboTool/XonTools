"""xAI (Grok) through its OpenAI-compatible Chat Completions API, with the openai SDK (xAI's own gRPC SDK is not
used): the requests, responses and errors of openai.py, xAI's endpoint, and xAI's key.
"""
from __future__ import annotations

import os

from .openai import OpenAIAdapter

BASE_URL = "https://api.x.ai/v1"


class XAIAdapter(OpenAIAdapter):
    kind = "xai"
    default_base_url = BASE_URL

    def _read_key(self) -> str | None:
        return (os.environ.get(self.entry.key_env) or None) if self.entry.key_env else None
