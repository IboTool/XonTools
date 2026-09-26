"""The baselines of L1 (XON_A1_CONSISTENCY.md §4.8)."""
from __future__ import annotations

from dataclasses import dataclass

from . import prompts
from .claims import SignedClaimGraph
from .client import LLM
from .consistency import CONFIDENCE_MIN
from .schemas import Contradiction, ContradictionList


def pairwise_only(sg: SignedClaimGraph, threshold: float = CONFIDENCE_MIN) -> tuple[bool, list[tuple[int, int]]]:
    """Inconsistent if any contradicts edge with confidence >= threshold (rev. 2.1: 0.5) joins two claims, of any kind
    (approximates pairwise self-consistency checkers such as SelfCheckGPT; Manakul et al. 2023). No entity graph, no
    balance; a rev. 2.2 "tension" relation makes no edge, so it is ignored."""
    pairs = [(int(a), int(b)) for (a, b), s, w in zip(sg.edges.tolist(), sg.sign, sg.weight)
             if s < 0 and w >= threshold]
    return bool(pairs), pairs


@dataclass
class DirectResult:
    inconsistent: bool
    contradictions: list[Contradiction]
    thinking: bool


def llm_direct(llm: LLM, text: str, *, tag: str, thinking: bool = True, bypass_cache: bool = False) -> DirectResult:
    """One call on the full text; inconsistent if any contradiction is listed. The run of record uses adaptive
    thinking (thinking=True); thinking disabled is the secondary number."""
    cfg = llm.cfg
    out = llm.parse(system=prompts.DIRECT_SYSTEM, user=prompts.direct_user(text), schema=ContradictionList,
                    max_tokens=cfg.llm_max_tokens_direct if thinking else cfg.llm_max_tokens_direct_no_thinking,
                    thinking=thinking, tag=f"{tag}-direct-{'thinking' if thinking else 'no-thinking'}",
                    bypass_cache=bypass_cache)
    return DirectResult(bool(out.contradictions), list(out.contradictions), thinking)
