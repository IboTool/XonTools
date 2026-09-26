"""XonForge's key rules (rules.md, XonForge; XONFORGE_SPEC.md §0, §13): each XONFORGE_*_KEY is read only in its provider
module and never appears in logs, cache files or the UI. The matching XonForge test of A1's key rules. Never calls an
API."""
import ast
from pathlib import Path

import pytest

from xon_common.budget import BudgetPaused, Caps
from xon_common.calllog import CallLog
from xon_common.providers import adapter_for
from xon_common.providers.base import Refusal
from xonforge import registry
from xonforge.cli import format_providers
from xonforge_fakes import SYSTEM, USER, FakeClient, RESPONSES, StatusError, anthropic_response, caller, open_caps

ROOT = Path(__file__).resolve().parents[2]
PROVIDER_MODULES = {f"xon_common/providers/{m}.py" for m in ("anthropic", "openai", "google", "xai",
                                                              "openai_compatible")}
LOCATIONS = "xonforge/locations.py"


def environment_reads(path: Path) -> set[tuple[str, str]]:
    """(innermost function, what is read) for each use of os.environ or os.getenv in the module."""
    tree = ast.parse(path.read_text("utf-8"))
    parent = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    reads = set()
    for node in ast.walk(tree):
        what = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else None
        if what not in ("environ", "getenv"):
            continue
        arg, fn, below, up = "?", "<module>", node, parent.get(node)
        while up is not None:
            if arg == "?" and isinstance(up, ast.Call) and below is up.func and up.args:
                arg = ast.unparse(up.args[0])
            elif arg == "?" and isinstance(up, ast.Subscript) and below is up.value:
                arg = ast.unparse(up.slice)
            if isinstance(up, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = up.name
                break
            below, up = up, parent.get(up)
        reads.add((fn, arg))
    return reads


def test_only_provider_modules_read_keys_and_each_reads_only_its_entry_s_variable():
    found = {}
    for top in ("xonforge", "xon_common"):
        for p in (ROOT / top).rglob("*.py"):
            reads = environment_reads(p)
            if reads:
                found[p.relative_to(ROOT).as_posix()] = reads
    assert set(found) == PROVIDER_MODULES | {LOCATIONS}
    for module in PROVIDER_MODULES:
        assert found[module] == {("_read_key", "self.entry.key_env")}, module
        tree = ast.parse((ROOT / module).read_text("utf-8"))
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        assert len(classes) == 1 and "_read_key" in {f.name for f in classes[0].body if isinstance(f, ast.FunctionDef)}
    assert found[LOCATIONS] == {("from_env", "env")}


def test_the_scan_sees_every_way_of_reading_the_environment(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("import os\nfrom os import environ\nX = os.environ['A']\n"
                     "def f():\n    return os.getenv('B') or environ.get('C')\n", encoding="utf-8")
    assert environment_reads(probe) == {("<module>", "'A'"), ("f", "'B'"), ("f", "'C'")}


def test_the_key_values_never_reach_a_log_a_cache_file_or_the_ui(tmp_path, monkeypatch):
    canaries = {env: f"sk-canary-{env.lower()}-0123456789" for env in registry.KEY_ENV.values()}
    for env, value in canaries.items():
        monkeypatch.setenv(env, value)
    entries = registry.load_entries()
    defaults = registry.load_defaults()
    names = [e.name for e in entries]
    # the startup check and its display, with every key read
    rows = registry.startup_check(entries, registry.adapters(entries, defaults), defaults)
    shown = format_providers(rows, registry.caps_of(defaults, entries), registry.retry_policy(defaults)) + repr(rows)
    # calls of every kind: answered, cached, retried, refused and held back by the budget
    for e in entries:
        fake = FakeClient(StatusError(529), RESPONSES[e.provider]())
        c = caller(tmp_path, e, fake, open_caps(*names))
        assert c.adapter.key_state() in ("present", "not needed")
        c.complete(system=SYSTEM, user=USER, max_tokens=100, tag=f"k-{e.name}")
        c.complete(system=SYSTEM, user=USER, max_tokens=100, tag=f"k-{e.name}")
        with pytest.raises(BudgetPaused):
            caller(tmp_path, e, fake, Caps()).complete(system=SYSTEM, user=USER + "?", max_tokens=100)
    refused = caller(tmp_path, entries[0], FakeClient(anthropic_response(stop="refusal")), open_caps(*names))
    with pytest.raises(Refusal) as error:
        refused.complete(system=SYSTEM, user=USER + "!", max_tokens=100)
    # the real Anthropic client, built from the key, sends nothing here
    real = adapter_for(entries[0])
    real.client()
    shown += repr(real) + str(error.value)
    written = "".join(p.read_text("utf-8") for p in tmp_path.rglob("*") if p.is_file())
    assert CallLog(tmp_path / "log.jsonl").rows() and any((tmp_path / "cache").rglob("*.json"))
    for value in canaries.values():
        assert value not in written and value not in shown
