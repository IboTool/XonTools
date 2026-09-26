"""A1 client (XON_A1_CONSISTENCY.md §2): cache, budget, dry-run, fixtures, retries, logging. Never calls the API."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from xon.config import LLM_CAPABILITIES, LLM_MODELS, XonConfig
from xon.llm import client as client_module
from xon.llm.client import (API_KEY_ENV, LLM, RECORD_ENV, BudgetExceeded, DryRunMissingFixture, LLMError,
                            LLMOutputInvalid, LLMRefusal, LLMTruncated, fixture_path, output_schema)
from xon.llm.schemas import ClaimList, EntityGraphSpec, PairList, RelationList

ROOT = Path(__file__).resolve().parents[1]
SYSTEM, USER = "SYSTEM-PROMPT-MARKER extract claims", "USER-PROMPT-MARKER Ana is older than Ben."
FAKE_KEY = "sk-ant-fake-key-for-tests-0123456789"
CLAIMS = {"claims": [{"id": 0, "text": "Ana is older than Ben.", "span": "Ana is older than Ben.", "kind": "Asserted"}]}


class StatusError(Exception):
    def __init__(self, status: int, retry_after: str | None = None):
        super().__init__(f"HTTP {status}")
        self.status_code = status
        self.response = SimpleNamespace(headers={} if retry_after is None else {"retry-after": retry_after})


class APIConnectionError(Exception):
    """Named as the SDK's: no response (a lost connection)."""


class APITimeoutError(APIConnectionError):
    """Named as the SDK's timeout, which is a connection error."""


class FakeMessages:
    """Answers messages.create from a queue: a JSON-able object, a (text, stop_reason) pair, or an exception."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def create(self, **body):
        self.calls.append(body)
        item = self.outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        text, stop = item if isinstance(item, tuple) else (item if isinstance(item, str) else json.dumps(item),
                                                          "end_turn")
        return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking="..."),
                                        SimpleNamespace(type="text", text=text)], stop_reason=stop,
                               usage=SimpleNamespace(input_tokens=120, output_tokens=80,
                                                     output_tokens_details={"thinking_tokens": 30}))


def fake(*outputs):
    return SimpleNamespace(messages=FakeMessages(outputs))


@pytest.fixture(autouse=True)
def _no_key_no_recording(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.delenv(RECORD_ENV, raising=False)


def llm(tmp_path, client=None, **kw):
    return LLM(cache_dir=tmp_path / "cache", client=client, fixture_dir=tmp_path / "fixtures",
               sleep=kw.pop("sleep", lambda s: None), **kw)


def call(m, tag="doc-extract", **kw):
    return m.parse(system=SYSTEM, user=USER, schema=ClaimList, max_tokens=kw.pop("max_tokens", 1000), tag=tag, **kw)


def log_rows(tmp_path):
    return [json.loads(line) for line in (tmp_path / "cache" / "log.jsonl").read_text("utf-8").splitlines()]


def test_dry_run_without_key_and_missing_fixture_is_a_clear_error(tmp_path):
    m = llm(tmp_path)
    assert m.dry_run
    with pytest.raises(DryRunMissingFixture, match="doc-extract") as err:
        call(m)
    assert API_KEY_ENV in str(err.value) and RECORD_ENV in str(err.value)


def test_dry_run_replays_fixtures_by_tag(tmp_path):
    path = fixture_path("doc-extract", tmp_path / "fixtures")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"kind": "parse", "request": "stale", "output": CLAIMS}), "utf-8")
    m = llm(tmp_path)
    out = call(m)
    assert isinstance(out, ClaimList) and out.claims[0].kind == "asserted"   # enum casing normalized
    assert m.usage["fixture_hits"] == 1 and m.usage["api_calls"] == 0 and m.usage["stale_fixtures"] == 1
    assert log_rows(tmp_path)[-1]["source"] == "fixture"
    with pytest.raises(DryRunMissingFixture, match="parse response, not a text response"):
        m.text(system=SYSTEM, user=USER, tag="doc-extract")


def test_cache_log_and_no_secrets_on_disk(tmp_path, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    f = fake(CLAIMS)
    m = llm(tmp_path, client=f)
    assert not m.dry_run
    first, second = call(m), call(m)
    assert first == second and len(f.messages.calls) == 1
    u = m.usage
    assert (u["api_calls"], u["cache_hits"], u["input_tokens"], u["output_tokens"], u["thinking_tokens"]) == \
        (1, 1, 120, 80, 30)
    assert u["estimated_cost_usd"] == pytest.approx((120 * 2.0 + 80 * 10.0) / 1e6)
    rows = log_rows(tmp_path)
    assert [r["source"] for r in rows] == ["api", "cache"] and [r["cache_hit"] for r in rows] == [False, True]
    assert {"timestamp", "tag", "model", "input_tokens", "output_tokens", "cache_hit", "duration_s"} <= set(rows[0])
    for p in (tmp_path / "cache").iterdir():
        text = p.read_text("utf-8")
        assert "SYSTEM-PROMPT-MARKER" not in text and "USER-PROMPT-MARKER" not in text and FAKE_KEY not in text


def test_request_parameters_follow_the_model(tmp_path):
    body = {name: {t: llm(tmp_path, client=fake(), model=name).request(system="s", user="u", max_tokens=10,
                                                                       thinking=t) for t in (False, True)}
            for name in LLM_MODELS}
    sonnet, haiku, opus = body["claude-sonnet-5"], body["claude-haiku-4-5-20251001"], body["claude-opus-5-5"]
    assert "temperature" not in sonnet[False] and sonnet[False]["thinking"] == {"type": "disabled"}
    assert "thinking" not in sonnet[True]                       # adaptive, the model's default
    assert haiku[False]["temperature"] == 0.0 and haiku[False]["thinking"] == {"type": "disabled"}
    assert "thinking" not in opus[False] and "temperature" not in opus[False]   # cannot be disabled
    assert all("temperature" not in body[n][t] for n in LLM_MODELS if not LLM_CAPABILITIES[n]["sampling"]
               for t in (False, True))
    m = llm(tmp_path, client=fake(), model="claude-opus-5-5")
    assert m.thinking_mode(False) == "adaptive (cannot be disabled)" and m.thinking_mode(True) == "adaptive"
    with pytest.raises(ValueError, match="unknown model"):
        llm(tmp_path, client=fake(), model="claude-2")


def test_cache_key_records_the_parameters_sent(tmp_path):
    f = fake(CLAIMS, CLAIMS, CLAIMS)
    m = llm(tmp_path, client=f)
    call(m, thinking=False)
    call(m, thinking=True)
    call(m, thinking=False, max_tokens=999)
    assert len(f.messages.calls) == 3 and len(list((tmp_path / "cache").glob("*.json"))) == 3


def test_budget_is_checked_before_calling(tmp_path):
    f = fake(CLAIMS)
    m = llm(tmp_path, client=f, budget_tokens=500)
    with pytest.raises(BudgetExceeded, match="500-token budget"):
        call(m, max_tokens=1000)
    assert f.messages.calls == [] and log_rows(tmp_path)[-1]["error"] == "BudgetExceeded"
    m.budget_tokens = 100_000
    call(m)
    assert m.spent_tokens == 200


def test_retries_only_on_transport_failures(tmp_path):
    waits = []
    f = fake(StatusError(429), StatusError(529), CLAIMS)
    call(llm(tmp_path / "a", client=f, sleep=waits.append))
    assert len(f.messages.calls) == 3 and waits == [2.0, 4.0]
    f = fake(StatusError(400), CLAIMS)
    with pytest.raises(StatusError):
        call(llm(tmp_path / "b", client=f))
    assert len(f.messages.calls) == 1
    f = fake(*[StatusError(529)] * 4)
    with pytest.raises(StatusError):
        call(llm(tmp_path / "c", client=f, cfg=XonConfig(llm_retries=3)))
    assert len(f.messages.calls) == 4
    # any 5xx, a timeout and a lost connection are transport failures too; the server's retry-after is honored
    waits = []
    f = fake(StatusError(500, retry_after="7"), APITimeoutError(), StatusError(503), CLAIMS)
    m = llm(tmp_path / "d", client=f, sleep=waits.append)
    call(m)
    assert len(f.messages.calls) == 4 and waits == [7.0, 4.0, 8.0]
    retries = [r for r in log_rows(tmp_path / "d") if r["source"] == "retry"]
    assert [(r["status"], r["retry"], r["wait_s"]) for r in retries] == [(500, 1, 7.0), ("APITimeoutError", 2, 4.0),
                                                                        (503, 3, 8.0)]
    assert m.usage["transport_retries"] == 3 and m.usage["api_calls"] == 1
    for err in (StatusError(401), StatusError(404), ValueError("not transport"), LLMOutputInvalid("schema")):
        assert not client_module.transient(err)
    assert client_module.transient(APIConnectionError()) and client_module.transient(StatusError(502))


def test_real_sdk_errors_carry_the_status_the_retry_checks():
    anthropic = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx")
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    for status in (429, 529, 500, 503):
        err = anthropic.Anthropic._make_status_error(
            anthropic.Anthropic.__new__(anthropic.Anthropic), "x", body=None,
            response=httpx.Response(status, request=req))
        assert client_module.transient(err)
    err = anthropic.Anthropic._make_status_error(anthropic.Anthropic.__new__(anthropic.Anthropic), "x", body=None,
                                                 response=httpx.Response(400, request=req))
    assert not client_module.transient(err)
    assert client_module.transient(anthropic.APIConnectionError(request=req))
    assert client_module.transient(anthropic.APITimeoutError(request=req))


def test_refusal_truncation_and_invalid_output_raise_and_are_not_cached_or_retried(tmp_path):
    for output, error in (((json.dumps(CLAIMS), "refusal"), LLMRefusal), (('{"claims": [', "max_tokens"), LLMTruncated),
                          ('{"claims": "nope"}', LLMOutputInvalid)):
        f = fake(output)
        m = llm(tmp_path, client=f)
        with pytest.raises(error):
            call(m, tag=error.__name__)
        assert len(f.messages.calls) == 1 and not list((tmp_path / "cache").glob("*.json"))
        assert log_rows(tmp_path)[-1]["error"] == error.__name__


def test_bypass_cache_neither_reads_nor_writes(tmp_path):
    f = fake(CLAIMS, CLAIMS)
    m = llm(tmp_path, client=f)
    call(m, bypass_cache=True)
    assert not list((tmp_path / "cache").glob("*.json"))
    call(m)
    call(m, bypass_cache=False)
    assert len(f.messages.calls) == 2


def test_recorder_writes_fixtures_that_dry_run_replays(tmp_path, monkeypatch):
    monkeypatch.setenv(RECORD_ENV, "1")
    m = llm(tmp_path, client=fake(CLAIMS, {"pairs": []}))
    recorded = call(m, tag="doc/7:extract")
    saved = json.loads(fixture_path("doc/7:extract", tmp_path / "fixtures").read_text("utf-8"))
    assert saved["kind"] == "parse" and "SYSTEM-PROMPT-MARKER" not in json.dumps(saved)
    with pytest.raises(LLMError, match="already recorded"):
        m.parse(system=SYSTEM, user="another request", schema=PairList, tag="doc/7:extract")
    monkeypatch.delenv(RECORD_ENV)
    replay = LLM(cache_dir=tmp_path / "elsewhere", fixture_dir=tmp_path / "fixtures")
    assert replay.dry_run and call(replay, tag="doc/7:extract") == recorded
    assert replay.usage["stale_fixtures"] == 0


def test_text_calls_and_clear_cache(tmp_path):
    f = fake("plain answer")
    m = llm(tmp_path, client=f)
    assert m.text(system="s", user="u", tag="t") == "plain answer"
    assert m.text(system="s", user="u", tag="t") == "plain answer" and len(f.messages.calls) == 1
    assert m.clear_cache() == 1 and (tmp_path / "cache" / "log.jsonl").exists()


def test_output_schema_is_strict_and_keeps_enums():
    for schema in (ClaimList, RelationList, PairList, EntityGraphSpec):
        s = output_schema(schema)
        objects = [node for node in _walk(s) if isinstance(node, dict) and node.get("type") == "object"]
        assert objects and all(node["additionalProperties"] is False for node in objects)
    kinds = output_schema(ClaimList)["$defs"]["Claim"]["properties"]["kind"]
    assert kinds["enum"] == ["asserted", "premise", "quoted"]

    from pydantic import BaseModel, Field

    class Bounded(BaseModel):
        confidence: float = Field(ge=0, le=1)
    with pytest.raises(ValueError, match="maximum, minimum"):
        output_schema(Bounded)


def test_a_relation_is_written_rationale_first():
    relation = output_schema(RelationList)["$defs"]["Relation"]
    assert list(relation["properties"]) == relation["required"] == ["a", "b", "rationale", "relation", "confidence"]


def _walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


# ------------------------------------------------------------------------------------------ repository-wide rules
SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", "cache", "results", "SPECS", ".venv", "venv", "node_modules"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".toml", ".json", ".jsonl", ".cfg", ".ini", ".yaml", ".yml", ".html", ".mdc"}


def _repo_files():
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix in TEXT_SUFFIXES and not SKIP_DIRS.intersection(p.relative_to(ROOT).parts):
            yield p


def test_the_key_variable_is_named_only_by_the_environment_read_and_the_readme():
    literal = "ANTHROPIC" + "_API_KEY"
    hits = {str(p.relative_to(ROOT)).replace("\\", "/"): p.read_text("utf-8", errors="ignore").count(literal)
            for p in _repo_files()}
    hits = {k: v for k, v in hits.items() if v}
    assert hits.pop("xon/llm/client.py") == 1
    hits.pop("README.md", None)
    assert hits == {}


def test_nothing_but_the_client_imports_anthropic():
    pattern = re.compile(r"^\s*(import anthropic|from anthropic)", re.M)
    offenders = [str(p.relative_to(ROOT)) for p in _repo_files() if p.suffix == ".py"
                 and "tests" not in p.relative_to(ROOT).parts and pattern.search(p.read_text("utf-8", errors="ignore"))]
    assert sorted(offenders) == sorted([str(Path("xon/llm/client.py")),
                                        str(Path("xon_common/providers/anthropic.py"))])
