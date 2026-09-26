"""Budgets (XONFORGE_SPEC.md §4.2): per-provider and per-run caps on tokens and on dollars.

Before a call is sent it reserves its worst case, its estimated input plus max_tokens priced at the model's rates
(the input at its cache-write rate where that is higher), counting the calls still in flight. If that could take the
run or the provider past a cap, if a cap is not set, or if the model has no price, the call is not sent:
BudgetPaused reports which cap and by how much, and the run pauses.
After the call its reservation is replaced by what it used. A cap that is not set allows nothing, so no call is sent
before the user sets the caps.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class Caps:
    run_tokens: int | None = None
    run_usd: float | None = None
    provider_tokens: Mapping[str, int | None] = field(default_factory=dict)   # by provider entry name
    provider_usd: Mapping[str, float | None] = field(default_factory=dict)


class BudgetPaused(RuntimeError):
    """A call held back by a cap; ``report`` says which cap, what is spent and in flight, and what the call needed."""

    def __init__(self, report: dict):
        self.report = report
        super().__init__(report["reason"])


@dataclass(frozen=True)
class Reservation:
    provider: str
    tokens: int
    usd: float


class Budget:
    def __init__(self, caps: Caps, spent: Mapping[str, tuple[int, float]] | None = None):
        """``spent``: what each provider entry already used in this run (CallLog.spent), for a resumed run."""
        self.caps = caps
        self._lock = threading.Lock()
        self._spent = {p: [int(t), float(d)] for p, (t, d) in (spent or {}).items()}
        self._held: dict[str, list] = {}

    @staticmethod
    def _total(table: dict, provider: str | None) -> tuple[int, float]:
        rows = [v for p, v in table.items() if provider is None or p == provider]
        return sum(r[0] for r in rows), sum(r[1] for r in rows)

    def spent(self, provider: str | None = None) -> tuple[int, float]:
        """Tokens and dollars used, by the whole run or by one provider entry."""
        with self._lock:
            return self._total(self._spent, provider)

    def reserve(self, provider: str, tokens: int, usd: float | None) -> Reservation:
        """Holds the call's worst case (``usd`` None: the model has no price), or raises BudgetPaused."""
        with self._lock:
            for scope, who, cap_tokens, cap_usd in (
                    ("run", None, self.caps.run_tokens, self.caps.run_usd),
                    (f"provider {provider}", provider, self.caps.provider_tokens.get(provider),
                     self.caps.provider_usd.get(provider))):
                spent_t, spent_d = self._total(self._spent, who)
                held_t, held_d = self._total(self._held, who)
                base = {"scope": scope, "provider": provider, "call_tokens": int(tokens), "call_usd": usd}
                if cap_tokens is None:
                    raise BudgetPaused({**base, "cap": "tokens", "limit": None,
                                        "reason": f"The {scope} token cap is not set."})
                if spent_t + held_t + tokens > cap_tokens:
                    raise BudgetPaused({**base, "cap": "tokens", "limit": cap_tokens, "spent": spent_t,
                                        "in_flight": held_t,
                                        "reason": f"This call could use up to {tokens:,} tokens; {spent_t:,} of the "
                                                  f"{scope}'s {cap_tokens:,}-token cap are spent and {held_t:,} are "
                                                  "held by calls in flight."})
                if cap_usd is None:
                    raise BudgetPaused({**base, "cap": "usd", "limit": None,
                                        "reason": f"The {scope} dollar cap is not set."})
                if usd is None:
                    raise BudgetPaused({**base, "cap": "usd", "limit": cap_usd,
                                        "reason": f"{provider}'s model has no price, so the {scope} dollar cap "
                                                  "cannot be checked."})
                if spent_d + held_d + usd > cap_usd:
                    raise BudgetPaused({**base, "cap": "usd", "limit": cap_usd, "spent": spent_d,
                                        "in_flight": held_d,
                                        "reason": f"This call could cost up to ${usd:.4f}; ${spent_d:.4f} of the "
                                                  f"{scope}'s ${cap_usd:.2f} cap are spent and ${held_d:.4f} are held "
                                                  "by calls in flight."})
            held = self._held.setdefault(provider, [0, 0.0])
            held[0] += int(tokens)
            held[1] += float(usd)
            return Reservation(provider, int(tokens), float(usd))

    def release(self, hold: Reservation) -> None:
        with self._lock:
            held = self._held[hold.provider]
            held[0] -= hold.tokens
            held[1] -= hold.usd

    def charge(self, hold: Reservation, tokens: int, usd: float) -> None:
        """Replaces the call's reservation by what it used."""
        with self._lock:
            held = self._held[hold.provider]
            held[0] -= hold.tokens
            held[1] -= hold.usd
            spent = self._spent.setdefault(hold.provider, [0, 0.0])
            spent[0] += int(tokens)
            spent[1] += float(usd)
