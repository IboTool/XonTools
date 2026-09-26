"""The provider modules (XONFORGE_SPEC.md §4): Anthropic, OpenAI, Google, xAI and any OpenAI-compatible endpoint. Each
imports its SDK only when it first sends, so that a missing SDK makes only its own provider unavailable.
"""
from .anthropic import AnthropicAdapter
from .base import Adapter, ProviderEntry
from .google import GoogleAdapter
from .openai import OpenAIAdapter
from .openai_compatible import OpenAICompatibleAdapter
from .xai import XAIAdapter

ADAPTERS = {cls.kind: cls for cls in (AnthropicAdapter, OpenAIAdapter, GoogleAdapter, XAIAdapter,
                                      OpenAICompatibleAdapter)}


def adapter_for(entry: ProviderEntry, client=None, timeout_s: float = 600.0) -> Adapter:
    try:
        cls = ADAPTERS[entry.provider]
    except KeyError:
        raise ValueError(f"unknown provider {entry.provider!r}; the provider modules are {', '.join(ADAPTERS)}")
    return cls(entry, client=client, timeout_s=timeout_s)
