"""``python -m xonforge run``: it refuses unless run-check passes, and a dry run sends nothing."""
import json
import os
import shutil
from pathlib import Path

from xon_common.calllog import CallLog
from xonforge import locations, registry
from xonforge.cli import main
from xonforge.render.phrasing import statement
from xonforge.skeleton.generators import generate

from xonforge_fakes import FakeClient, anthropic_response

ROOT = Path(__file__).resolve().parents[2]


def _answers(rendering: dict) -> FakeClient:
    """A rendering for the renderer, and an empty review reply of the shape each prompt asks for."""
    client = FakeClient()

    def call(**body):
        client.bodies.append(body)
        system = body.get("system") or ""
        user = body["messages"][0]["content"]
        if isinstance(user, str) and user.startswith("Document "):
            text = '{"inventory":[],"conflicts":[]}' if system.startswith("First list") else '{"conflicts":[]}'
        else:
            text = json.dumps(rendering)
        return anthropic_response(text=text)

    client.messages = __import__("types").SimpleNamespace(create=call)
    return client


def test_run_refuses_the_sample_until_its_check_passes(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("XON_LLM_RECORD", raising=False)
    for key in list(os.environ):
        if key.startswith("XONFORGE"):
            monkeypatch.delenv(key, raising=False)
    assert main(["run", "sample", "--bases", "order_cycle:1:1"]) == 1
    out = capsys.readouterr().out
    assert "may not start" in out and "XONFORGE_ANTHROPIC_KEY is not set" in out
    assert "sk-" not in out


def test_a_dry_run_replays_the_cache_and_sends_nothing(tmp_path, monkeypatch):
    config = tmp_path / "config"
    shutil.copytree(ROOT / "xonforge" / "config", config)
    import yaml
    defaults = yaml.safe_load((config / "defaults.yaml").read_text(encoding="utf-8"))
    defaults["runs"]["sample"]["caps"]["run_tokens"] = 10**6
    defaults["runs"]["sample"]["caps"]["provider_tokens_each"] = 10**5
    (config / "defaults.yaml").write_text(yaml.safe_dump(defaults), encoding="utf-8")
    monkeypatch.setenv(locations.CACHE_ENV, str(tmp_path / "cache"))
    monkeypatch.setenv("XONFORGE_ANTHROPIC_KEY", "present-for-the-offline-test")
    for key in ("ANTHROPIC_API_KEY", "XON_LLM_RECORD"):
        monkeypatch.delenv(key, raising=False)
    skeleton = generate("direct_negation", seed=1, genre="office memo", premise=False).consistent
    body = {"text": " ".join(statement(f, skeleton) + "." for f in skeleton.facts),
            "spans": [{"fact": f.id, "span": statement(f, skeleton) + "."} for f in skeleton.facts]}
    client = _answers(body)
    names = [e.name for e in registry.load_entries(config)]
    clients = {n: client for n in names}
    log = CallLog(tmp_path / "calls.jsonl")
    first = registry.Session("sample", run_config="sample", config_dir=config, clients=clients, log=log)
    from xonforge.cli import composition
    from xonforge.pipeline import execute
    specs = composition(["direct_negation:1:1"], 1, False)
    report = execute(first, specs, genre="office memo", seed=1, premise_share=0.0)
    sent = len(client.bodies)
    assert sent >= 1 and report["documents"] and report["mode"] == "pipeline_test"
    assert any(b["messages"][0]["content"].startswith("Document ") for b in client.bodies)
    assert report["paused"] is None and report["outcomes"]
    shutil.rmtree(tmp_path / "documents")
    again = registry.Session("sample", run_config="sample", config_dir=config, clients=clients, log=log, dry_run=True)
    second = execute(again, specs, genre="office memo", seed=1, premise_share=0.0)
    assert len(client.bodies) == sent
    assert [d.doc_id for d in second["documents"]] == [d.doc_id for d in report["documents"]]
    assert "present-for-the-offline-test" not in json.dumps(client.bodies)
    assert all(d.mode == "pipeline_test" for d in second["documents"])
