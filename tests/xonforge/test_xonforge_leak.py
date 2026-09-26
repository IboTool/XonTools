"""XonForge step 6 (XONFORGE_SPEC.md §9; the user's items 17 and 19 of 2026-09-25, xonforge/docs/decisions.md): the leak
test. The first test is the leak test itself: every file in every worktree, against the committed fingerprint
manifests. Nothing here opens the sealed or judged locations, writes into a worktree, or calls an API."""
import json
import subprocess
from pathlib import Path

import pytest

from xonforge import cli, locations
from xonforge.corpus import leak
from xonforge.corpus.seal import canary_sha256
from xonforge.render.phrasing import statement
from xonforge.skeleton.generators import Knobs, generate

CANARY = "XONFORGE-CANARY-00000000-0000-4000-8000-000000000002"
OTHER = "XONFORGE-CANARY-00000000-0000-4000-8000-000000000000"
TEXT = ("The quarterly planning memo went out on a grey Tuesday morning. Priya had drafted most of it the night "
        "before, while the heating in the east wing clanked and hissed. Nobody could remember who had first "
        "suggested moving the offsite to the lake house, but by noon the idea had three enthusiastic replies and "
        "one pointed question about the catering budget.")


def test_no_sealed_document_is_in_any_worktree():
    report = leak.check_worktrees()
    assert report.findings == [], "\n".join(report.lines())


# ------------------------------------------------------------------------------------------ normalizing, hashing
def test_normalizing_folds_case_and_width_and_strips_punctuation_and_quotes():
    assert leak.words("\u201cAda\u2019s\u201d  TEAM,\n\uff37on!") == ["adas", "team", "won"]
    assert leak.text_sha256("Ada won.") == leak.text_sha256(" ada   WON ")
    assert len(leak.ngrams("one two three four five six seven")) == 0
    assert len(leak.ngrams("one two three four five six seven eight nine")) == 2
    assert all(len(h) == 16 for h in leak.ngrams(TEXT))


@pytest.fixture
def skeleton():
    return generate("equality_break", seed=1, genre="office memo", knobs=Knobs(entities=5, distractors=1)).planted[0]


@pytest.fixture
def prints(tmp_path, skeleton):
    made = leak.fingerprint(version="v0.1", split="test", canary=CANARY,
                            documents=[("b0001-planted", TEXT, skeleton)])
    leak.write_fingerprint(made, tmp_path / "prints")
    return leak.load(tmp_path / "prints")


def test_a_manifest_holds_hashes_only_the_canary_s_sha256_and_is_written_once(tmp_path, skeleton, prints):
    path = tmp_path / "prints" / "v0.1-test.json"
    made = json.loads(path.read_text(encoding="utf-8"))
    assert set(made) == {"version", "split", "k", "canary_sha256", "documents"}
    assert made["canary_sha256"] == canary_sha256(CANARY) and CANARY not in path.read_text(encoding="utf-8")
    assert "Priya" not in path.read_text(encoding="utf-8") and "priya" not in path.read_text(encoding="utf-8")
    assert made["documents"][0]["doc_id"] == "b0001-planted" and len(made["documents"][0]["ngrams"]) > 20
    with pytest.raises(FileExistsError):
        leak.write_fingerprint(made, tmp_path / "prints")


def test_a_file_leaks_with_the_canary_the_whole_text_or_two_8_word_sequences(prints):
    assert leak.search(f"a note\n{CANARY}\n", prints) == ["the canary string of the test split of v0.1"]
    assert leak.search(f"a note\n{OTHER}\n", prints) == []
    found = leak.search(TEXT.upper(), prints)
    assert found[0] == "the whole text of b0001-planted of v0.1" and "8-word sequences of b0001-planted" in found[1]
    nine = "Priya had drafted most of it the night before,"
    assert leak.search(f"Quoted: {nine}", prints) == ["2 distinct 8-word sequences of b0001-planted of v0.1"]
    assert leak.search("Priya had drafted most of it the night", prints) == []


def test_a_json_file_s_string_values_are_searched_as_texts(prints):
    escaped = json.dumps({"doc": {"text": TEXT.replace("the night", "the\nnight")}}, ensure_ascii=True)
    assert "the whole text of b0001-planted of v0.1" in leak.search(escaped, prints, json_like=True)
    lines = "\n".join(json.dumps({"n": n, "text": TEXT}) for n in range(2))
    assert "the whole text of b0001-planted of v0.1" in leak.search(lines, prints, json_like=True)


def test_sequences_of_the_prompts_and_templates_are_left_out_of_the_manifest(tmp_path, skeleton):
    prompt = (leak.PROMPTS / "render.txt").read_text(encoding="utf-8")
    template = max(("Assume that " + statement(f, skeleton) for f in skeleton.facts), key=lambda s: len(s.split()))
    assert len(template.split()) >= 9
    text = f"{TEXT} {' '.join(prompt.split()[:20])} {template}."
    made = leak.fingerprint(version="v0.1", split="test", canary=CANARY, documents=[("b0001-planted", text, skeleton)])
    grams = set(made["documents"][0]["ngrams"])
    assert grams and not grams & (leak.prompt_ngrams() | leak.template_ngrams(skeleton))
    leak.write_fingerprint(made, tmp_path / "prints")
    prints = leak.load(tmp_path / "prints")
    assert leak.search(prompt, prints) == [] and leak.search(template, prints) == []


# ------------------------------------------------------------------------------------------ scanning folders
def test_every_file_but_git_s_is_searched_once_and_one_that_is_not_utf8_is_reported_skipped(tmp_path, prints):
    root = (tmp_path / "worktree").resolve()
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "leak.txt").write_text(TEXT, encoding="utf-8")
    (root / "notes").mkdir()
    (root / "notes" / "copy.md").write_text(f"{TEXT}\n", encoding="utf-8")
    prefix = " ".join(TEXT.split()[:20])
    (root / "notes" / "quote.md").write_text(f"# Notes\n\nShe wrote: {prefix}\n", encoding="utf-8")
    (root / "clean.txt").write_text("Nothing sealed here.", encoding="utf-8")
    (root / "image.bin").write_bytes(b"\xff\xfe\x00binary")
    nested = root / "nested"
    nested.mkdir()
    (nested / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    (nested / "canary.txt").write_text(CANARY, encoding="utf-8")
    assert sorted(p.relative_to(root).as_posix() for p in leak.files([root, nested])) == [
        "clean.txt", "image.bin", "nested/canary.txt", "notes/copy.md", "notes/quote.md"]
    report = leak.check_worktrees(prints=prints, roots=[root, nested])
    assert report.searched == 4 and report.skipped == [str(root / "image.bin")]
    shared = len(leak.ngrams(prefix))
    assert sorted((Path(f.where).relative_to(root).as_posix(), f.what) for f in report.findings) == [
        ("nested/canary.txt", "the canary string of the test split of v0.1"),
        ("notes/copy.md", f"{len(prints.index)} distinct 8-word sequences of b0001-planted of v0.1"),
        ("notes/copy.md", "the whole text of b0001-planted of v0.1"),
        ("notes/quote.md", f"{shared} distinct 8-word sequences of b0001-planted of v0.1")]
    assert report.lines()[0] == "Searched 4 files; 1 other was not UTF-8 text, so not searched."


def test_with_no_manifest_nothing_is_searched_and_the_check_passes(tmp_path):
    (tmp_path / "copy.txt").write_text(TEXT, encoding="utf-8")
    report = leak.check_worktrees(roots=[tmp_path], folder=tmp_path / "none")
    assert (report.findings, report.searched, report.manifests) == ([], 0, False)
    assert "nothing was searched" in report.lines()[0]
    assert leak.check_history(["--all"], folder=tmp_path / "none").manifests is False


# ------------------------------------------------------------------------------------------ git history, read only
def _git(*args):
    return subprocess.run(["git", *args], cwd=locations.ROOT, capture_output=True, encoding="utf-8",
                          check=True).stdout


def test_the_commits_being_pushed_are_searched_blob_by_blob_through_read_only_git():
    if subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=locations.ROOT,
                      capture_output=True).returncode:
        pytest.skip("no repository, or no commit yet")
    if not _git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:]:
        pytest.skip("HEAD has no parent")
    changed = _git("diff", "--name-only", "--diff-filter=AM", "HEAD~1", "HEAD").split()
    path = next(p for p in changed if p.endswith((".py", ".md", ".txt", ".yaml")))
    text = _git("show", f"HEAD:{path}")
    prints = leak.Prints(canaries={}, texts={leak.text_sha256(text): "a document of the test"}, index={})
    report = leak.check_history(["HEAD~1..HEAD"], prints=prints)
    assert report.searched >= 1
    assert any(":" in f.where and f.what == "the whole text of a document of the test" for f in report.findings)


def test_a_revision_that_looks_like_an_option_is_refused():
    for bad in ("--output=x", "-n1"):
        with pytest.raises(ValueError, match="revisions are commits or ranges, not options"):
            leak.blobs([bad])


# ------------------------------------------------------------------------------------------ the commands
def test_the_leak_commands_search_and_report_without_writing(capsys, monkeypatch, tmp_path, prints):
    assert cli.main(["leak-check"]) == 0
    out = capsys.readouterr().out
    assert "Read only: nothing is written" in out and "Every worktree:" in out
    original = leak.check_worktrees
    monkeypatch.setattr(leak, "check_worktrees", lambda: original(prints=prints, roots=[tmp_path]))
    (tmp_path / "copy.txt").write_text(TEXT, encoding="utf-8")
    assert cli.main(["leak-check"]) == 1
    assert f"- {tmp_path.resolve() / 'copy.txt'}: the whole text of b0001-planted of v0.1" in capsys.readouterr().out
    monkeypatch.setattr(leak, "load", lambda folder=None: prints)
    assert cli.main(["leak-check", "--commits=--output=x"]) == 2
    assert "not options" in capsys.readouterr().out
