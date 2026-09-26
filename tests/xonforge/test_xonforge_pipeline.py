"""The 20-document sample run (XONFORGE_SPEC.md §14, step 7). Offline: rendering and review are fakes, and no test
calls an API. The run stops for review and does not export or seal."""
from types import SimpleNamespace

from xon_common.budget import BudgetPaused
from xon_common.calllog import CallLog
from xonforge import locations, pipeline, registry
from xonforge.cli import main
from xonforge.estimate import BaseSpec
from xonforge.render.renderer import doc_id
from xonforge.render.schema import Attempt, Document, Renderer, RenderRules
from xonforge.review.decisions import DecisionLog
from xonforge.review.replies import ContradictionReply, InventoryReply
from xonforge_fakes import FakeClient, anthropic_response

CLAUDE = ["claude-sonnet", "claude-opus", "claude-fable"]


def _session(tmp_path, monkeypatch):
    monkeypatch.setenv(locations.CACHE_ENV, str(tmp_path / "cache"))
    monkeypatch.setenv(locations.SEALED_ENV, str(tmp_path / "sealed"))
    monkeypatch.setenv(locations.JUDGED_ENV, str(tmp_path / "judged"))
    return registry.Session("sample", run_config="sample", log=CallLog(tmp_path / "calls.jsonl"),
                            clients={n: FakeClient(anthropic_response()) for n in CLAUDE})


def _document(skeleton, caller):
    entry = caller.adapter.entry
    return Document(doc_id=doc_id(skeleton), base_id=skeleton.base_id, variant=skeleton.variant,
                    skeleton_digest=skeleton.digest(), mode="pipeline_test",
                    renderer=Renderer(entry=entry.name, provider=entry.provider, model=entry.model,
                                      prompt_version="test", thinking=True),
                    rules=RenderRules(words=200, explicitness="stated", lexical_variety="low", level=1),
                    status="rendered", text="A short office memo for the offline sample test.", spans={},
                    attempts=(Attempt(number=1, source="api"),))


def test_the_sample_is_ten_level_1_bases_and_twenty_documents():
    bases = pipeline.sample_bases()
    assert len(bases) == 10 and {b.level for b in bases} == {1} and [b.seed for b in bases] == list(range(1, 11))
    assert [b.plant_type for b in bases].count("order_cycle") == 3
    assert [b.plant_type for b in bases].count("equality_break") == 3
    assert [b.plant_type for b in bases].count("binary_parity") == 2
    assert [b.plant_type for b in bases].count("direct_negation") == 2
    assert not any(b.trap for b in bases)


def test_the_sample_run_renders_reviews_and_stops_for_review_without_exporting(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch)
    rendered, reviewed = [], []

    def fake_render(skeleton, rules, caller, **kwargs):
        rendered.append(skeleton.variant)
        return _document(skeleton, caller)

    def fake_derive(skeleton, source, document, caller, **kwargs):
        rendered.append(skeleton.variant)
        return _document(skeleton, caller)

    def fake_review(batch, texts, prompt_name, caller, **kwargs):
        reviewed.append((batch.batch_id, len(batch.items)))
        parsed = (InventoryReply(inventory=[], conflicts=[]) if prompt_name == "relational_inventory"
                  else ContradictionReply(conflicts=[]))
        return {item.review_id: SimpleNamespace(parsed=parsed) for item in batch.items}

    monkeypatch.setattr(pipeline, "render", fake_render)
    monkeypatch.setattr(pipeline, "derive", fake_derive)
    monkeypatch.setattr(pipeline.blind, "review", fake_review)
    report = pipeline.execute(session)
    assert report.status == "stopped for review"
    assert (report.documents, report.rendered, report.failed, report.queued) == (20, 20, 0, 20)
    assert rendered.count("consistent") == 10 and rendered.count("planted") == 10
    assert len(reviewed) == 4 and {n for _, n in reviewed} == {27}
    assert "Nothing was accepted, exported, split or sealed." in report.text()
    assert report.packet is not None and report.packet.startswith(str(tmp_path))
    log = DecisionLog()
    assert (log.seed("sample"), log.seed("sample", "quota_seed"), log.seed("sample", "split_seed")) == (1, 2, 3)
    assert not (locations.ROOT / "data" / "xonforge" / "pipeline_test").exists()
    rendered.clear()
    pipeline.execute(session)
    assert rendered == []


def test_a_run_paused_by_the_budget_keeps_what_it_saved_and_does_not_queue(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch)

    def paused(skeleton, rules, caller, **kwargs):
        raise BudgetPaused({"reason": "paused for the test"})

    monkeypatch.setattr(pipeline, "render", paused)
    report = pipeline.execute(session, bases=[BaseSpec("order_cycle", 1, 1)])
    assert report.status == "paused" and report.detail.startswith("Paused while rendering")
    assert report.queued == 0 and not (tmp_path / "reviews" / "queue" / "sample.json").exists()


def test_the_run_command_refuses_anything_but_the_sample(monkeypatch, capsys):
    assert main(["run", "first_corpus"]) == 2
    assert "only the sample" in capsys.readouterr().out
    monkeypatch.setattr(registry, "Session", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(pipeline, "execute", lambda session, bases=None: pipeline.RunReport(
        run="sample", status="stopped for review", detail="queued for review", constraints="abc"))
    assert main(["run", "sample"]) == 0
    assert "Stopped for review" in capsys.readouterr().out
