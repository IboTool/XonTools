"""XonForge scaffold (XONFORGE_SPEC.md): the packages load from this repository and the CLI prints its help. Never
calls an API."""
import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_packages_load_from_this_repository():
    """pyproject.toml puts the repository root first on pytest's path: the editable xon-sim install maps xon to the
    folder it was installed from, and tests/xonforge/ would otherwise pass for the xonforge package."""
    for name in ("xon", "xonforge", "xon_common"):
        module = importlib.import_module(name)
        assert module.__file__ is not None and Path(module.__file__).resolve() == ROOT / name / "__init__.py", name


def test_main_prints_the_help(capsys):
    from xonforge.cli import main

    assert main([]) == 0
    assert capsys.readouterr().out.startswith("usage: python -m xonforge")


def test_python_dash_m_xonforge_prints_the_help():
    for args in ([], ["--help"]):
        out = subprocess.run([sys.executable, "-m", "xonforge", *args], cwd=ROOT, capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        assert out.stdout.startswith("usage: python -m xonforge") and "XonForge" in out.stdout
