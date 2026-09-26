"""XonForge's prompts (the user's item 7 of 2026-09-25, xonforge/docs/decisions.md), each stored verbatim in this
folder and recorded in versions.json with its version and the SHA-256 of its file. A prompt whose file no longer
matches its recorded hash is refused, so a changed prompt is recorded under a new version before it is used.

- render.txt: the system prompt that renders a consistent twin (a draft, for the 20-document sample);
- derive.txt: the system prompt that re-renders the sentences of a derived variant (a draft);
- render_wording.json: the explicitness, lexical-variety and spread instructions of the rendering prompt, the
  lexical-variety wording a draft for the user's review;
- review_contradiction.txt and review_inventory.txt: the user's two review prompts, verbatim.
- fact_audit.txt: the fact auditor's prompt (stated, implied, absent or contradicted), a model other than the renderer.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

FOLDER = Path(__file__).resolve().parent


class PromptChanged(RuntimeError):
    """A prompt's file does not match the hash recorded for its version."""


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    sha256: str
    text: str                  # the file's text, without its final line break


def recorded(folder: Path = FOLDER) -> dict[str, dict]:
    return json.loads((folder / "versions.json").read_text(encoding="utf-8"))


def load(name: str, folder: Path = FOLDER) -> Prompt:
    versions = recorded(folder)
    if name not in versions:
        raise KeyError(f"no prompt named {name!r} is recorded in versions.json")
    raw = (folder / name).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != versions[name]["sha256"]:
        raise PromptChanged(f"{name} does not match the hash recorded for {versions[name]['version']}; a changed "
                            "prompt is recorded under a new version in versions.json")
    text = raw.decode("utf-8")
    return Prompt(name=name, version=versions[name]["version"], sha256=digest,
                  text=text[:-1] if text.endswith("\n") else text)


def data(name: str, folder: Path = FOLDER) -> dict:
    """A JSON prompt file's content."""
    return json.loads(load(name, folder).text)
