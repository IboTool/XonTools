"""Transport retries, the same for every provider: A1's policy (XON_A1_REV2_2_PRECISION.md §4.2), which the user chose
over XONFORGE_SPEC.md §4.2's rate-limit and overload errors only (a logged deviation, CHANGELOG_EXPERIMENTS.md,
2026-09-25).

A send that fails with a rate limit (429), an overload (529), another 5xx status, a timeout or a lost connection is
sent again, identically, after a wait that starts at the policy's backoff, doubles each time and is never shorter
than the server's retry-after. A transport retry is not a content retry: it never counts toward the renderer's cap on
rendering attempts (§6).
"""
from __future__ import annotations

from dataclasses import dataclass

RATE_LIMITED, OVERLOADED = 429, 529
# Failures with no response: the Anthropic and OpenAI SDKs' APIConnectionError (their APITimeoutError included), and
# httpx's and Python's own timeouts and lost connections, which other SDKs let through
NO_RESPONSE = frozenset({"APIConnectionError", "TimeoutException", "NetworkError", "RemoteProtocolError",
                         "TimeoutError", "ConnectionError"})


@dataclass(frozen=True)
class TransportError:
    """A failed send as a provider module reads it: the HTTP status if a response came back, whether the connection
    failed or timed out without one, and the server's retry-after in seconds (0 if absent)."""
    status: int | None
    no_response: bool
    retry_after_s: float = 0.0


@dataclass(frozen=True)
class RetryPolicy:
    retries: int        # sends after the first one
    backoff_s: float    # the first retry's wait; it doubles each time

    def transient(self, err: TransportError | None) -> bool:
        if err is None:
            return False
        s = err.status
        return err.no_response or s in (RATE_LIMITED, OVERLOADED) or (s is not None and 500 <= s < 600)


def retry_after(exc: BaseException) -> float:
    """The retry-after header of the failed response, in seconds; 0 if absent or unreadable."""
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        return max(float(headers.get("retry-after") or 0.0), 0.0)
    except (AttributeError, TypeError, ValueError):
        return 0.0


def sdk_error(exc: BaseException) -> TransportError | None:
    """A failed send from an SDK shaped like Anthropic's or OpenAI's: status_code on an HTTP error, and a class named
    as one of NO_RESPONSE when there was no response. None for any other exception."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return TransportError(status, False, retry_after(exc))
    if any(c.__name__ in NO_RESPONSE for c in type(exc).__mro__):
        return TransportError(None, True, 0.0)
    return None


def send_with_retries(send, classify, policy: RetryPolicy, on_retry, sleep):
    """``send()`` until it returns, retrying transient failures as the policy says; returns (response, retries).
    ``classify(exc)`` reads a failure (a TransportError, or None if it is not a transport failure);
    ``on_retry(n, err, wait_s)`` is called before the n-th retry's wait. The last failure is raised."""
    delay = float(policy.backoff_s)
    for n in range(int(policy.retries) + 1):
        try:
            return send(), n
        except Exception as exc:
            err = classify(exc)
            if not policy.transient(err) or n == policy.retries:
                raise
            wait = max(delay, err.retry_after_s)
        on_retry(n + 1, err, wait)
        sleep(wait)
        delay *= 2
    raise AssertionError("unreachable")
