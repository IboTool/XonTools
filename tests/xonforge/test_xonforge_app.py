"""The XonForge dashboard, offline. Pages render, Start sends no call, and a key's value is never shown."""
from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

APP = str(Path(__file__).resolve().parents[2] / "xonforge" / "app" / "dashboard.py")
CANARY = "sk-canary-dashboard-do-not-show"
PAGES = ("Configure", "Providers", "Run", "Review queue", "Quality", "Corpus", "Logs")


def _ok(at):
    assert not at.exception, [e.value for e in at.exception]


def _button(at, label):
    return next(b for b in list(at.button) if b.label == label)


def _shown(at) -> str:
    chunks = [str(at.main), str(at.sidebar)]
    for name in ("markdown", "text", "info", "success", "error", "warning", "caption", "header", "subheader"):
        chunks += [getattr(el, "value", "") for el in getattr(at, name, [])]
    return "\n".join(str(c) for c in chunks)


def test_the_dashboard_renders_every_page_and_never_shows_a_key(monkeypatch):
    monkeypatch.setenv("XONFORGE_ANTHROPIC_KEY", CANARY)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("XON_LLM_RECORD", raising=False)
    source = Path(APP).read_text(encoding="utf-8")
    assert "xon.llm" not in source and "import xon." not in source and "from xon " not in source
    app = AppTest.from_file(APP, default_timeout=180)
    app.run()
    _ok(app)
    for page in PAGES:
        app.sidebar.radio(key="page").set_value(page).run()
        _ok(app)
        assert CANARY not in _shown(app)
    app.sidebar.radio(key="page").set_value("Run").run()
    _button(app, "Estimate").click().run()
    _ok(app)
    shown = _shown(app)
    assert "no call is made" in shown.lower() or "Offline" in shown
    assert CANARY not in shown
    _button(app, "Start").click().run()
    _ok(app)
    assert "does not send a call" in _shown(app)
    assert CANARY not in _shown(app)
    app.sidebar.radio(key="page").set_value("Corpus").run()
    _button(app, "Preview datasheet").click().run()
    _ok(app)
    assert "Pipeline test" in _shown(app)
    _button(app, "Try to place a sealed split").click().run()
    _ok(app)
    assert "never enters a sealed or judged split" in _shown(app)
    assert CANARY not in _shown(app)
