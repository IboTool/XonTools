"""XonForge's import boundary (the user's re-specification of XONFORGE_SPEC.md; CHANGELOG_EXPERIMENTS.md, XonForge
step 0): nothing in xonforge/ or xon_common/ imports the consistency engine, directly or transitively, except the
isolated diagnostic, xonforge/diagnostics/engine_plugin.py (§7.5). Checked statically, on every import statement and
on every string that names a module reaching the engine, and at run time, in a fresh interpreter. Never calls an
API."""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = frozenset({"xon.llm.consistency", "xon.llm.entity_consistency", "xon.llm.minimal", "xon.llm.engine"})
CHECKED = ("xonforge", "xon_common")
DIAGNOSTIC = "xonforge.diagnostics.engine_plugin"   # the one module that may import the engine; inert until the freeze
PROBE = "xonforge._scan_probe"                      # a module added in memory to check that the scan catches it


def sources() -> dict[str, tuple[str, bool]]:
    """Every module of xon/, xonforge/ and xon_common/: dotted name -> (source, whether it is a package)."""
    out = {}
    for top in ("xon",) + CHECKED:
        for p in sorted((ROOT / top).rglob("*.py")):
            parts = p.relative_to(ROOT).with_suffix("").parts
            package = parts[-1] == "__init__"
            out[".".join(parts[:-1] if package else parts)] = (p.read_text("utf-8-sig"), package)
    return out


def parents(name: str) -> list[str]:
    parts = name.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts))]


def loads(tree: ast.AST, name: str, package: bool, known) -> list[tuple[int, str]]:
    """(line, module) for every module that an import statement anywhere in the tree may load, parent packages
    included: relative imports resolved, each name of a from-import also taken as a submodule, and a star import as
    every known submodule."""
    here = name.split(".") if package else name.split(".")[:-1]
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = ".".join((here[:len(here) - node.level + 1] if node.level else [])
                            + (node.module.split(".") if node.module else []))
            names = [a.name for a in node.names]
            targets = [base] + ([m for m in known if m.rpartition(".")[0] == base] if "*" in names
                                else [f"{base}.{n}" for n in names])
        else:
            continue
        found += [(node.lineno, m) for t in targets for m in parents(t) + [t]]
    return list(dict.fromkeys(found))


def strings(tree: ast.AST) -> list[tuple[int, str]]:
    """(line, text) of every string constant except docstrings."""
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    return [(node.lineno, node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]


def naming(modules) -> re.Pattern:
    """A module's dotted name, or its file path with either slash."""
    forms = ([re.escape(m) + r"(?!\w)" for m in modules]
             + [r"[/\\]".join(map(re.escape, m.split("."))) + r"\.py" for m in modules])
    return re.compile(r"(?<![\w.])(?:" + "|".join(forms) + ")")


def reaching(graph: dict[str, set[str]]) -> set[str]:
    """The engine modules and every module that imports one, directly or through others."""
    reach = set(ENGINE)
    while True:
        more = {m for m, deps in graph.items() if m not in reach and deps & reach}
        if not more:
            return reach
        reach |= more


def violations(modules: dict[str, tuple[str, bool]]) -> list[str]:
    """Each import in xonforge/ or xon_common/, the diagnostic aside, of a module that reaches the engine, and each
    string there, docstrings aside, that names such a module of xon/ (importlib, __import__, runpy, file loaders)."""
    trees = {name: ast.parse(src) for name, (src, _) in modules.items()}
    found = {name: loads(trees[name], name, package, modules) for name, (_, package) in modules.items()}
    reach = reaching({name: {m for _, m in found[name]} | set(parents(name)) for name in modules})
    pattern = naming(sorted(m for m in reach if m.split(".")[0] == "xon"))
    out = []
    for name in sorted(modules):
        if name.split(".")[0] in CHECKED and name != DIAGNOSTIC:
            out += [f"{name}:{line} imports {m}" for line, m in found[name] if m in reach]
            out += [f"{name}:{line} names {text!r}" for line, text in strings(trees[name]) if pattern.search(text)]
    return out


def with_probe(source: str) -> dict[str, tuple[str, bool]]:
    modules = sources()
    modules[PROBE] = (source, False)
    return modules


# ------------------------------------------------------------------------------------------ static scan
def test_nothing_but_the_diagnostic_imports_the_engine():
    assert violations(sources()) == []


@pytest.mark.parametrize("source", [
    "import xon.llm.consistency",
    "import xon.llm.minimal as m",
    "from xon.llm import entity_consistency",
    "from xon.llm import client, engine",
    "from xon.llm.minimal import analyze_minimal",
    "from xon.llm import *",
    "from xon.llm.claims import extract_claims",            # claims imports entity_consistency
    "def later():\n    from xon.llm import minimal",
    "import importlib\nimportlib.import_module('xon.llm.engine')",
    "__import__('xon.llm.consistency')",
    "import runpy\nrunpy.run_path('xon/llm/minimal.py')",
])
def test_the_scan_catches_every_import_form(source):
    found = violations(with_probe(source))
    assert found and all(v.startswith(f"{PROBE}:") for v in found)


@pytest.mark.parametrize("source", [
    "from xon.llm import client",
    "from xon.llm.client import LLM, request_hash",
    "import xon.config",
    '"""A docstring may name xon.llm.minimal."""',
])
def test_the_scan_passes_what_does_not_reach_the_engine(source):
    assert violations(with_probe(source)) == []


def test_only_the_diagnostic_may_import_the_engine_and_nothing_may_import_the_diagnostic():
    modules = sources()
    modules[DIAGNOSTIC] = ("from xon.llm.minimal import analyze_minimal", False)
    assert violations(modules) == []
    modules[PROBE] = ("from xonforge.diagnostics import engine_plugin", False)
    assert violations(modules) == [f"{PROBE}:1 imports {DIAGNOSTIC}"]


def test_the_shared_module_imports_nothing_from_xonforge():
    modules = sources()
    offenders = [f"{name}:{line} imports {m}" for name, (src, package) in modules.items()
                 if name.split(".")[0] == "xon_common"
                 for line, m in loads(ast.parse(src), name, package, modules) if m.split(".")[0] == "xonforge"]
    assert offenders == []


# ------------------------------------------------------------------------------------------ run time
RUNTIME = """
import importlib
import json
import sys

sys.path.insert(0, sys.argv[1])
for name in json.loads(sys.argv[2]):
    importlib.import_module(name)
print(json.dumps({"engine": sorted(m for m in json.loads(sys.argv[3]) if m in sys.modules),
                  "files": {m: getattr(sys.modules[m], "__file__", None) for m in sys.modules
                            if m.split(".")[0] in ("xon", "xonforge", "xon_common")}}))
"""


def imported_fresh(names: list[str]) -> dict:
    """Imports the modules in a fresh interpreter with this repository first on its path; returns the engine modules
    then loaded and the file of every xon, xonforge and xon_common module loaded."""
    out = subprocess.run([sys.executable, "-c", RUNTIME, str(ROOT), json.dumps(names), json.dumps(sorted(ENGINE))],
                         cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_importing_every_module_loads_no_engine_module():
    names = sorted(m for m in sources() if m.split(".")[0] in CHECKED and m != DIAGNOSTIC)
    assert {"xonforge", "xonforge.__main__", "xonforge.cli", "xon_common"} <= set(names)
    res = imported_fresh(names)
    assert res["engine"] == []
    assert set(names) <= set(res["files"])
    assert all(f and Path(f).resolve().is_relative_to(ROOT) for f in res["files"].values())


def test_the_run_time_check_sees_an_engine_import():
    assert "xon.llm.minimal" in imported_fresh(["xon.llm.minimal"])["engine"]


def test_the_diagnostic_imports_no_engine_module_while_it_is_an_inert_stub():
    """Until the tag a1-rev2.2-frozen exists (rules.md: no edit under xon/ before it) the diagnostic is inert."""
    assert imported_fresh([DIAGNOSTIC])["engine"] == []
