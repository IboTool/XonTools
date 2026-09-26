"""The fact audit (XONFORGE_SPEC.md §7.4b). A fake client only: no call leaves the machine."""
import json

import pytest

from xonforge.render.schema import Document, Renderer, RenderRules
from xonforge.review.queue import reasons
from xonforge.skeleton.generators import generate
from xonforge.verify.audit import FactAudit, audit, disagreements

from xonforge_fakes import FakeClient, anthropic_response, caller, entry


def _document(skeleton):
    rules = RenderRules(words=200, explicitness="stated", lexical_variety="low")
    return Document(doc_id="d1", base_id=skeleton.base_id, variant=skeleton.variant, skeleton_digest=skeleton.digest(),
                    mode="pipeline_test", renderer=Renderer(entry="claude-sonnet", provider="anthropic",
                                                            model="claude-sonnet-5", prompt_version="t"),
                    rules=rules, status="rendered", text="Ada left at three. She arrived at five.",
                    spans={skeleton.facts[0].id: "Ada left at three."}, attempts=())


def test_the_auditor_is_not_the_renderer_and_a_disagreement_is_a_queue_reason(tmp_path):
    skeleton = generate("order_cycle", seed=1, genre="g").consistent
    document = _document(skeleton)
    reply = FactAudit(findings=[{"fact": f.id, "status": "absent"} for f in skeleton.facts])
    client = FakeClient(anthropic_response(text=json.dumps(reply.model_dump())))
    found = audit(skeleton, document, caller(tmp_path, entry(name="claude-opus"), client),
                  renderer="claude-sonnet", max_tokens=200)
    flags = disagreements(skeleton, document, found)
    assert any("in the fact-to-span map" in f and skeleton.facts[0].id in f for f in flags)
    assert any("the fact audit disagrees" in r for r in reasons(document, audit_flags=flags))
    with pytest.raises(ValueError, match="other than the renderer"):
        audit(skeleton, document, caller(tmp_path, entry(name="claude-sonnet"), client),
              renderer="claude-sonnet", max_tokens=200)
