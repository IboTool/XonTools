"""The engine diagnostic's refusal (XONFORGE_SPEC.md §7.5; CHANGELOG_EXPERIMENTS.md, 2026-09-25, XonForge step 1,
item 8): it screens nothing under the sealed test split or the judged split, and nothing at all while either location
is unset or inside a worktree. The stub is otherwise inert until a1-rev2.2-frozen. Never calls an API."""
from pathlib import Path

import pytest

from xonforge import locations
from xonforge.diagnostics.engine_plugin import SealedPathRefused, check_path, screen

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def splits(tmp_path, monkeypatch):
    sealed, judged = tmp_path / "sealed", tmp_path / "judged"
    for d in (sealed / "sub", judged):
        d.mkdir(parents=True)
    monkeypatch.setenv(locations.SEALED_ENV, str(sealed))
    monkeypatch.setenv(locations.JUDGED_ENV, str(judged))
    return sealed, judged


def test_a_document_in_the_sealed_or_judged_split_is_refused(splits):
    sealed, judged = splits
    for path in (sealed / "doc-001.txt", sealed, sealed / "sub" / ".." / "doc-002.txt", judged / "doc-003.txt",
                 Path(str(sealed / "doc-004.txt").upper())):
        with pytest.raises(SealedPathRefused, match="never screens its own test corpus"):
            screen(path)


def test_nothing_is_screened_while_a_split_s_location_is_unset_or_inside_a_worktree(splits, monkeypatch, tmp_path):
    outside = tmp_path / "development" / "doc.txt"
    monkeypatch.delenv(locations.JUDGED_ENV)
    with pytest.raises(SealedPathRefused, match="cannot be checked against the judged split"):
        check_path(outside)
    monkeypatch.setenv(locations.JUDGED_ENV, str(ROOT / "judged"))
    with pytest.raises(SealedPathRefused, match="inside the worktree"):
        check_path(outside)


def test_a_document_outside_both_passes_the_check_and_the_stub_stays_inert(splits, tmp_path):
    outside = tmp_path / "development" / "doc.txt"
    assert check_path(outside) == outside.resolve()
    with pytest.raises(NotImplementedError, match="inert stub"):
        screen(outside)
