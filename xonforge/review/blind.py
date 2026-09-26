"""Blind review requests (XONFORGE_SPEC.md §7.3; the user's items 7 to 9 of 2026-09-25, xonforge/docs/decisions.md).
A reviewer receives a document's review id and its text, and nothing else: no skeleton, plant, variant, base or
document id. Review ids are opaque, derived from a batch's secret salt and the document's or canary's id, so that they
show neither which items are canaries, nor a document's variant, nor which documents share a base. The salt, the seed
that draws the batch's canaries and shuffles its order, and the map back to documents and canaries are kept in the
batch record, outside the repository.

A batch is up to 20 generated documents reviewed by one reviewer with one prompt, plus its canaries (calibration.py).
Each item is its own request, which item 8 allows ("one call or several"). The two prompts are the user's, read
verbatim from xonforge/prompts/ with their versions and hashes; the reply is structured output (replies.py). A reply
that is refused, truncated or not of the reply's shape leaves its item unreviewed, which outcome.py flags; any other
failure (the budget, an unavailable provider, a dry run without the call) stops the batch, to resume from the cache.
"""
from __future__ import annotations

import hashlib
import random
import secrets
from pathlib import Path
from typing import Collection, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from xon_common.caller import Caller, Result
from xon_common.providers.base import OutputInvalid, Refusal, Truncated
from xonforge import locations, prompts

from . import calibration
from .replies import ContradictionReply, InventoryReply

PROMPTS = {"contradiction_only": "review_contradiction.txt", "relational_inventory": "review_inventory.txt"}
REPLIES = {"contradiction_only": ContradictionReply, "relational_inventory": InventoryReply}
MAX_DOCUMENTS = 20
UNUSABLE = (Refusal, Truncated, OutputInvalid)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BatchItem(_Frozen):
    review_id: str
    kind: Literal["document", "canary"]
    ref: str                          # the document's id or the canary's


class Batch(_Frozen):
    batch_id: str
    run: str
    seed: int                         # draws the canaries and shuffles the items' order
    salt: str                         # secret: with it, a review id leads back to its item
    items: tuple[BatchItem, ...]
    reviewer: str | None = None       # the registry entry that reviews the batch
    prompt: str | None = None         # the review prompt's name
    prompt_version: str | None = None

    def item(self, review_id: str) -> BatchItem:
        return next(i for i in self.items if i.review_id == review_id)


def load_prompt(name: str, folder: Path | None = None) -> prompts.Prompt:
    if name not in PROMPTS:
        raise ValueError(f"the review prompts are {' and '.join(PROMPTS)}, not {name!r}")
    return prompts.load(PROMPTS[name], folder if folder is not None else prompts.FOLDER)


def review_id(salt: str, ref: str) -> str:
    return "r" + hashlib.sha256(f"{salt}\n{ref}".encode("utf-8")).hexdigest()[:12]


def assemble(run: str, batch_id: str, documents: Sequence[str], canaries: Sequence[str], seed: int,
             salt: str | None = None, *, reviewer: str | None = None, prompt: str | None = None) -> Batch:
    """A batch of the given documents and canaries (their ids), in an order shuffled with ``seed``."""
    if not 1 <= len(documents) <= MAX_DOCUMENTS:
        raise ValueError(f"a batch holds 1 to {MAX_DOCUMENTS} generated documents, not {len(documents)}")
    refs = list(documents) + list(canaries)
    if len(set(refs)) != len(refs):
        raise ValueError("each document and canary appears once in a batch, and no canary shares a document's id")
    salt = salt if salt is not None else secrets.token_hex(16)
    items = [BatchItem(review_id=review_id(salt, d), kind="document", ref=d) for d in documents]
    items += [BatchItem(review_id=review_id(salt, c), kind="canary", ref=c) for c in canaries]
    if len({i.review_id for i in items}) != len(items):
        raise ValueError("two items drew the same review id; assemble the batch with another salt")
    random.Random(seed).shuffle(items)
    return Batch(batch_id=batch_id, run=run, seed=seed, salt=salt, items=tuple(items), reviewer=reviewer,
                 prompt=prompt, prompt_version=None if prompt is None else load_prompt(prompt).version)


def batch_for(run: str, batch_id: str, documents: Sequence[str], pool: Sequence[calibration.ReviewCanary],
              attributes: Collection[str], seed: int, *, reviewer: str, prompt: str,
              salt: str | None = None) -> Batch:
    """A batch of the documents with its canaries, drawn from the registry with the seed (calibration.draw)."""
    canaries = calibration.draw(pool, attributes, seed)
    return assemble(run, batch_id, documents, [c.id for c in canaries], seed, salt, reviewer=reviewer, prompt=prompt)


def request(prompt: str, item: BatchItem, text: str) -> tuple[str, str]:
    """The system and user prompts for one item: the review prompt, and the item's review id and text only."""
    return prompt, f"Document {item.review_id}:\n\n{text}"


def review(batch: Batch, texts: Mapping[str, str], prompt_name: str, caller: Caller, *, max_tokens: int,
           params: dict | None = None, thinking: bool = False) -> dict[str, Result | Exception]:
    """Each item reviewed by ``caller``'s entry with the named prompt, by review id: its result, or the refusal,
    truncation or invalid output that left it unreviewed. ``texts``: each item's text, by its ``ref``."""
    if batch.prompt is not None and batch.prompt != prompt_name:
        raise ValueError(f"batch {batch.batch_id} is reviewed with the {batch.prompt} prompt, not {prompt_name}")
    prompt = load_prompt(prompt_name)
    results: dict[str, Result | Exception] = {}
    for item in batch.items:
        system, user = request(prompt.text, item, texts[item.ref])
        try:
            results[item.review_id] = caller.complete(system=system, user=user, max_tokens=max_tokens,
                                                      schema=REPLIES[prompt_name], params=params, thinking=thinking,
                                                      tag=f"review:{prompt_name}:{item.review_id}")
        except UNUSABLE as exc:
            results[item.review_id] = exc
    return results


class BatchStore:
    """Batch records, under the cache directory's parent in reviews/batches/<run>/ (their salts are secret)."""

    def __init__(self, root: str | Path | None = None):
        self.root = locations.outside_worktrees(
            root if root is not None else locations.text_log_dir() / "reviews" / "batches", "batch store")

    def path(self, run: str, batch_id: str) -> Path:
        for part, what in ((run, "run"), (batch_id, "batch id")):
            if not part or any(c in part for c in '/\\:*?"<>|') or part in (".", ".."):
                raise ValueError(f"a {what} is a plain file name, not {part!r}")
        return self.root / run / f"{batch_id}.json"

    def save(self, batch: Batch) -> Path:
        path = self.path(batch.run, batch.batch_id)
        if path.exists():
            raise FileExistsError(f"batch {batch.batch_id} of run {batch.run} is already recorded")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(batch.model_dump_json(indent=1), encoding="utf-8")
        return path

    def load(self, run: str, batch_id: str) -> Batch | None:
        path = self.path(run, batch_id)
        return Batch.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None
