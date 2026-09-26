"""XonForge's prompts (the user's item 7 of 2026-09-25, xonforge/docs/decisions.md): stored verbatim in
xonforge/prompts/, versioned and hashed. Never calls an API."""
import hashlib
import json
import shutil

import pytest

from xonforge import prompts

CONTRADICTION = ("List every set of two or more statements in this document that cannot all be true at once. Quote "
                 "each statement verbatim. Do not report statements that are merely unlikely or surprising, or that "
                 "are resolved by time, quotation, belief, hypothesis or correction. If there are none, return an "
                 "empty list.")
INVENTORY = ("First list every statement that relates people or things (order, same or different, counts, times, "
             "places, roles), quoted verbatim and grouped by attribute. Then check each group and report conflicts in "
             "the same format.")


def test_every_prompt_file_is_recorded_with_its_version_and_the_hash_of_its_file():
    files = sorted(p.name for p in prompts.FOLDER.iterdir()
                   if p.is_file() and p.name not in ("__init__.py", "versions.json"))
    recorded = prompts.recorded()
    assert files == sorted(recorded) == ["derive.txt", "fact_audit.txt", "render.txt", "render_wording.json",
                                         "review_contradiction.txt", "review_inventory.txt"]
    for name, entry in recorded.items():
        assert set(entry) == {"version", "sha256"}
        assert entry["sha256"] == hashlib.sha256((prompts.FOLDER / name).read_bytes()).hexdigest()
        assert prompts.load(name).version == entry["version"]
    assert len({e["version"] for e in recorded.values()}) == len(recorded)


def test_the_review_prompts_are_the_user_s_text_verbatim():
    assert prompts.load("review_contradiction.txt").text == CONTRADICTION
    assert prompts.load("review_inventory.txt").text == INVENTORY


def test_the_lexical_variety_wording_is_marked_as_a_draft():
    wording = prompts.data("render_wording.json")
    assert set(wording["lexical_variety"]) == {"low", "medium", "high"}
    assert set(wording["explicitness"]) == {"stated", "paraphrased"}
    assert set(wording["spread"]) == {"any", "half", "quarters"}
    assert wording["lexical_variety_status"].startswith("draft for Ian's review")
    assert "draft" in prompts.recorded()["render_wording.json"]["version"]


def test_a_changed_prompt_is_refused_until_it_is_recorded_under_a_new_version(tmp_path):
    folder = tmp_path / "prompts"
    shutil.copytree(prompts.FOLDER, folder, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    (folder / "render.txt").write_bytes((folder / "render.txt").read_bytes() + b"One more rule.\n")
    with pytest.raises(prompts.PromptChanged, match="render.txt does not match the hash recorded for render-v0"):
        prompts.load("render.txt", folder)
    versions = json.loads((folder / "versions.json").read_text(encoding="utf-8"))
    versions["render.txt"] = {"version": "render-v0-draft-4",
                              "sha256": hashlib.sha256((folder / "render.txt").read_bytes()).hexdigest()}
    (folder / "versions.json").write_text(json.dumps(versions), encoding="utf-8")
    assert prompts.load("render.txt", folder).text.endswith("One more rule.")
    with pytest.raises(KeyError, match="no prompt named"):
        prompts.load("missing.txt", folder)
