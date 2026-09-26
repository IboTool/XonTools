"""The provider interface (XONFORGE_SPEC.md §4.2): a registry entry with its model's capability flags and price, and
the adapter each provider module implements. The caller (xon_common/caller.py) caches, budgets, retries and logs; an
adapter only builds its provider's request, sends it and reads the response.

Each provider module reads its key itself (``_read_key``), only from the variable named by the entry's key_env, and
keeps it only inside its SDK client. No SDK is left to fill a key, base URL or credential from its own environment
variables.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from ..retry import TransportError, sdk_error

STRUCTURED_OUTPUT = ("json_schema", "json_object", "prompt")
REASONING_DEFAULT = ("off", "on", "adaptive")
SAMPLING_PARAMS = ("temperature", "top_p", "top_k")


@dataclass(frozen=True)
class Capabilities:
    """A model's capability flags, configured in the registry.

    structured_output: json_schema (the API enforces the schema), json_object (the API returns JSON; the schema is
    in the prompt) or prompt (the schema is only in the prompt). sampling: whether temperature and the like are
    accepted; they are sent only then. context_tokens: the context limit, None if unknown. reasoning_default: what
    the model does when the request says nothing about reasoning. reasoning_off: the request fields that turn
    reasoning off, None if it cannot be turned off."""
    structured_output: str = "prompt"
    sampling: bool = False
    context_tokens: int | None = None
    reasoning_default: str = "off"
    reasoning_off: Mapping[str, Any] | None = None

    def __post_init__(self):
        if self.structured_output not in STRUCTURED_OUTPUT:
            raise ValueError(f"structured_output must be one of {STRUCTURED_OUTPUT}, not {self.structured_output!r}")
        if self.reasoning_default not in REASONING_DEFAULT:
            raise ValueError(f"reasoning_default must be one of {REASONING_DEFAULT}, not {self.reasoning_default!r}")


@dataclass(frozen=True)
class Price:
    """USD per million input and output tokens; reasoning is billed as output. cache_read and cache_write: what an
    input token read from or written to the provider's prompt cache costs, as a multiple of the input price."""
    input_per_mtok: float
    output_per_mtok: float
    verified: bool = False
    source: str = ""
    cache_read: float = 1.0
    cache_write: float = 1.0

    def usd(self, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0,
            cache_write_tokens: int = 0) -> float:
        """``input_tokens`` counts every input token, the cached ones among them."""
        plain = input_tokens - cache_read_tokens - cache_write_tokens
        cached = cache_read_tokens * self.cache_read + cache_write_tokens * self.cache_write
        return ((plain + cached) * self.input_per_mtok + output_tokens * self.output_per_mtok) / 1e6


@dataclass(frozen=True)
class ProviderEntry:
    """One registry entry. verified: whether the model id and capabilities were checked against the provider's
    documentation; source: where they come from."""
    name: str
    provider: str
    model: str
    key_env: str | None
    base_url: str | None = None
    roles: tuple[str, ...] = ()
    capabilities: Capabilities = field(default_factory=Capabilities)
    price: Price | None = None
    verified: bool = False
    source: str = ""


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0       # every input token, cached ones included
    output_tokens: int = 0      # every output token, reasoning included
    thinking_tokens: int = 0    # the reasoning tokens among them, where the provider reports them
    cache_read_tokens: int = 0  # the cached tokens among the input, where the provider reports them
    cache_write_tokens: int = 0  # the input tokens written to the cache, where the provider reports them

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class Reply:
    """A response as an adapter reads it. stop: "end", "max_tokens", "refusal", or the provider's own reason."""
    text: str
    usage: Usage
    stop: str
    request_id: str | None = None


class ProviderError(RuntimeError):
    """A call that did not produce a usable response."""


class ProviderUnavailable(ProviderError):
    """No key, no SDK or no endpoint: the provider is skipped, never replaced by another."""


class Refusal(ProviderError):
    """The model declined, or the provider blocked the request or the response."""


class Truncated(ProviderError):
    """The response hit max_tokens, which covers reasoning plus output."""


class OutputInvalid(ProviderError):
    """The response does not match the requested schema."""


class DryRunMissing(ProviderError):
    """A dry run, and the request is not in the cache."""


def field_of(obj, name: str, default=None):
    """An attribute of an SDK object, or a key of the dict a fake or a raw response gives instead."""
    if obj is None:
        return default
    value = obj.get(name, default) if isinstance(obj, Mapping) else getattr(obj, name, default)
    return default if value is None else value


def count(obj, name: str) -> int:
    return int(field_of(obj, name, 0) or 0)


class Adapter:
    kind: ClassVar[str] = ""
    sdk: ClassVar[str] = ""                          # the SDK's import name
    sampling_params: ClassVar[tuple[str, ...]] = ()  # the sampling parameters this API has

    def __init__(self, entry: ProviderEntry, client=None, timeout_s: float = 600.0):
        """``client`` replaces the SDK client (tests pass a fake)."""
        if entry.provider != self.kind:
            raise ValueError(f"{type(self).__name__} is for {self.kind!r} entries, not {entry.provider!r}")
        self.entry = entry
        self.timeout_s = float(timeout_s)
        self._client = client

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.entry.name!r}, model={self.entry.model!r})"

    # ------------------------------------------------------------------ implemented by each provider module
    def _read_key(self) -> str | None:
        raise NotImplementedError

    def _make_client(self, key: str | None):
        raise NotImplementedError

    def request(self, *, system: str, user: str, max_tokens: int, schema=None, thinking: bool = False,
                params: Mapping[str, float] | None = None) -> dict:
        """The request body to send; its hash is the cache key. thinking False turns reasoning off where the model
        allows it."""
        raise NotImplementedError

    def send(self, body: dict):
        raise NotImplementedError

    def reply(self, raw) -> Reply:
        raise NotImplementedError

    def transport_error(self, exc: BaseException) -> TransportError | None:
        return sdk_error(exc)

    # ------------------------------------------------------------------ shared
    def sdk_installed(self) -> bool:
        try:
            return importlib.util.find_spec(self.sdk) is not None
        except (ImportError, ValueError):
            return False

    def key_state(self) -> str:
        """"present", "missing" or "not needed"; never the key."""
        if self.entry.key_env is None:
            return "not needed"
        return "present" if self._read_key() else "missing"

    def status(self) -> tuple[bool, str]:
        """Whether calls can be sent, and if not, why. A client passed in (a test's fake) is always available."""
        if self._client is not None:
            return True, "a client was passed in"
        if self.key_state() == "missing":
            return False, f"{self.entry.key_env} is not set"
        if not self.sdk_installed():
            return False, f"the {self.sdk} SDK is not installed"
        return True, "ready"

    def client(self):
        if self._client is None:
            ok, why = self.status()
            if not ok:
                raise ProviderUnavailable(f"{self.entry.name}: {why}")
            self._client = self._make_client(self._read_key())
        return self._client

    def sampling(self, params: Mapping[str, float] | None) -> dict:
        """The sampling parameters to send: none if the model does not accept them, otherwise those given."""
        params = dict(params or {})
        unknown = sorted(set(params) - set(SAMPLING_PARAMS))
        if unknown:
            raise ValueError(f"unknown parameters: {', '.join(unknown)}")
        if not self.entry.capabilities.sampling:
            return {}
        missing = sorted(set(params) - set(self.sampling_params))
        if missing:
            raise ValueError(f"the {self.kind} API has no {', '.join(missing)}")
        return {k: (int(v) if k == "top_k" else float(v)) for k, v in params.items()}

    def reasoning_label(self, thinking: bool) -> str:
        """What the request asks of the model's reasoning, for the call log."""
        caps = self.entry.capabilities
        if thinking or caps.reasoning_default == "off":
            return caps.reasoning_default
        return "off" if caps.reasoning_off else f"{caps.reasoning_default} (cannot be turned off)"
