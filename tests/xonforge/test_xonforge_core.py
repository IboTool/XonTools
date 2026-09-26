"""XonForge step 1 (XONFORGE_SPEC.md §4.2, §11): the xon_common core, a call cached, budgeted, retried and logged.
Offline, with fake clients; never calls an API."""
import json

import pytest

from xon.llm import client as a1_client
from xon_common.budget import Budget, BudgetPaused, Caps
from xon_common.calllog import FIELDS, MAX_TEXT, CallLog
from xon_common.hashing import request_hash, request_key
from xon_common.providers import adapter_for
from xon_common.providers.base import DryRunMissing, OutputInvalid, ProviderUnavailable, Refusal, Truncated
from xonforge_fakes import (RESPONSE, SYSTEM, USER, APIConnectionError, APITimeoutError, FakeClient, StatusError,
                            Verdict, anthropic_response, caller, entry, open_caps)

ANTHROPIC = entry("anthropic", name="claude", model="claude-sonnet-5", reasoning_default="adaptive",
                  reasoning_off={"thinking": {"type": "disabled"}}, structured_output="json_schema")


def complete(c, **kw):
    return c.complete(**{"system": SYSTEM, "user": USER, "max_tokens": 1000, "tag": "t-1", **kw})


def rows(tmp_path):
    return CallLog(tmp_path / "log.jsonl").rows()


# ------------------------------------------------------------------------------------------ hashing and the cache
def test_the_hashing_functions_are_a1s_own():
    assert request_hash is a1_client.request_hash and request_key is a1_client.request_key


def test_a_call_is_sent_once_then_answered_from_the_cache(tmp_path):
    fake = FakeClient(anthropic_response())
    c = caller(tmp_path, ANTHROPIC, fake)
    first, second = complete(c), complete(c)
    assert len(fake.bodies) == 1
    assert (first.source, second.source) == ("api", "cache") and first.text == second.text == RESPONSE
    assert first.key == second.key == request_key(fake.bodies[0]) == a1_client.request_key(fake.bodies[0])
    assert (tmp_path / "cache" / "claude" / f"{first.key}.json").exists()
    assert [r["source"] for r in rows(tmp_path)] == ["api", "cache"]


def test_every_parameter_sent_is_part_of_the_key():
    def keyer(model):
        a = adapter_for(entry("anthropic", name="haiku", model=model, sampling=True,
                              reasoning_off={"thinking": {"type": "disabled"}}, structured_output="json_schema"))
        return lambda **kw: request_key(a.request(**{"system": SYSTEM, "user": USER, "max_tokens": 1000, **kw}))

    key = keyer("claude-haiku")
    keys = {key(), key(system=SYSTEM + "!"), key(user=USER + "!"), key(max_tokens=999),
            key(params={"temperature": 0.0}), key(params={"temperature": 0.5}), key(params={"top_p": 0.9}),
            key(thinking=True), key(schema=Verdict)}
    assert len(keys) == 9 and keyer("claude-other")() not in keys


def test_a_parameter_the_model_does_not_accept_is_neither_sent_nor_in_the_key(tmp_path):
    fake = FakeClient(anthropic_response())
    c = caller(tmp_path, ANTHROPIC, fake)
    assert complete(c).key == complete(c, params={"temperature": 0.7}).key
    assert len(fake.bodies) == 1 and "temperature" not in fake.bodies[0]


def test_the_provider_is_part_of_the_key(tmp_path):
    fake = FakeClient(anthropic_response())
    one = complete(caller(tmp_path, ANTHROPIC, fake))
    two = complete(caller(tmp_path, entry("anthropic", name="claude-2", model="claude-sonnet-5",
                                          reasoning_off={"thinking": {"type": "disabled"}},
                                          structured_output="json_schema"), fake))
    assert one.key == two.key and two.source == "api" and len(fake.bodies) == 2


def test_a_later_attempt_has_its_own_key_and_answer(tmp_path):
    fake = FakeClient(anthropic_response())
    c = caller(tmp_path, ANTHROPIC, fake)
    first, again = complete(c), complete(c, attempt=2)
    assert again.source == "api" and again.key == request_key(fake.bodies[1], 2) != first.key
    record = json.loads((tmp_path / "cache" / "claude" / f"{again.key}.json").read_text("utf-8"))
    assert record["attempt"] == 2 and record["sent"] == request_hash(fake.bodies[1])


def test_structured_output_is_validated_and_cached_as_data(tmp_path):
    fake = FakeClient(anthropic_response('{"consistent": false, "reason": "a cycle"}'))
    c = caller(tmp_path, ANTHROPIC, fake)
    first, second = complete(c, schema=Verdict), complete(c, schema=Verdict)
    assert first.parsed == second.parsed == Verdict(consistent=False, reason="a cycle") and len(fake.bodies) == 1
    record = json.loads((tmp_path / "cache" / "claude" / f"{first.key}.json").read_text("utf-8"))
    assert record["output"] == {"consistent": False, "reason": "a cycle"}


# ------------------------------------------------------------------------------------------ dry run and availability
def test_a_dry_run_answers_only_from_the_cache(tmp_path):
    complete(caller(tmp_path, ANTHROPIC, FakeClient(anthropic_response())))
    never = FakeClient(AssertionError("a dry run sent a request"))
    dry = caller(tmp_path, ANTHROPIC, never, dry_run=True)
    assert complete(dry).source == "cache"
    with pytest.raises(DryRunMissing):
        complete(dry, user=USER + " (not recorded)")
    assert never.bodies == [] and rows(tmp_path)[-1]["source"] == "dry-run"


def test_an_unavailable_provider_raises_and_nothing_takes_its_place(tmp_path, monkeypatch):
    monkeypatch.delenv("XONFORGE_ANTHROPIC_KEY", raising=False)
    c = caller(tmp_path, ANTHROPIC, None)
    with pytest.raises(ProviderUnavailable, match="XONFORGE_ANTHROPIC_KEY is not set"):
        complete(c)
    assert rows(tmp_path)[-1]["source"] == "unavailable"


# ------------------------------------------------------------------------------------------ budgets
def test_no_call_is_sent_while_a_cap_is_not_set(tmp_path):
    fake = FakeClient(anthropic_response())
    for caps in (Caps(), Caps(run_tokens=10**6, run_usd=10.0), Caps(10**6, None, {"claude": 10**6}, {"claude": 1.0})):
        with pytest.raises(BudgetPaused, match="not set"):
            complete(caller(tmp_path, ANTHROPIC, fake, caps))
    assert fake.bodies == [] and {r["source"] for r in rows(tmp_path)} == {"budget"}


@pytest.mark.parametrize("tight, scope, cap", [
    ({"run_tokens": 500}, "run", "tokens"),
    ({"provider_tokens": {"claude": 500}}, "provider claude", "tokens"),
    ({"run_usd": 0.001}, "run", "usd"),
    ({"provider_usd": {"claude": 0.001}}, "provider claude", "usd"),
])
def test_each_cap_pauses_before_the_call_that_could_pass_it(tmp_path, tight, scope, cap):
    base = open_caps("claude")
    caps = Caps(**{**base.__dict__, **{k: ({**getattr(base, k), **v} if isinstance(v, dict) else v)
                                       for k, v in tight.items()}})
    fake = FakeClient(anthropic_response())
    with pytest.raises(BudgetPaused) as paused:
        complete(caller(tmp_path, ANTHROPIC, fake, caps))
    assert (paused.value.report["scope"], paused.value.report["cap"]) == (scope, cap) and fake.bodies == []


def test_a_model_without_a_price_is_not_sent(tmp_path):
    fake = FakeClient(anthropic_response())
    with pytest.raises(BudgetPaused, match="no price"):
        complete(caller(tmp_path, entry("anthropic", name="claude", price=None), fake))
    assert fake.bodies == []


def test_the_budget_counts_calls_in_flight_and_charges_what_was_used():
    budget = Budget(Caps(1000, 1.0, {"p": 1000}, {"p": 1.0}))
    hold = budget.reserve("p", 600, 0.1)
    with pytest.raises(BudgetPaused, match="held by calls in flight"):
        budget.reserve("p", 600, 0.1)
    budget.charge(hold, 300, 0.05)
    assert budget.spent() == budget.spent("p") == (300, 0.05)
    budget.release(budget.reserve("p", 700, 0.1))
    assert budget.spent() == (300, 0.05)


def test_a_resumed_run_starts_from_what_its_log_says_it_spent(tmp_path):
    complete(caller(tmp_path, ANTHROPIC, FakeClient(anthropic_response(input_tokens=400, output_tokens=100))))
    spent = CallLog(tmp_path / "log.jsonl").spent("run-1")
    assert spent["claude"][0] == 500 and spent["claude"][1] == pytest.approx((400 * 2.0 + 100 * 10.0) / 1e6)
    assert CallLog(tmp_path / "log.jsonl").spent("another-run") == {}
    caps = Caps(1500, 100.0, {"claude": 1500}, {"claude": 100.0})
    resumed = caller(tmp_path, ANTHROPIC, FakeClient(anthropic_response()), caps)
    resumed.budget = Budget(caps, spent=spent)
    with pytest.raises(BudgetPaused, match="500 of the run's 1,500-token cap"):
        complete(resumed, user=USER + " (new)")


# ------------------------------------------------------------------------------------------ transport retries
@pytest.mark.parametrize("failure", [StatusError(429), StatusError(529), StatusError(500), StatusError(503),
                                     APIConnectionError("connection lost"), APITimeoutError("timed out")])
def test_a_transport_failure_is_retried_with_the_identical_request(tmp_path, failure):
    fake = FakeClient(failure, anthropic_response())
    result = complete(caller(tmp_path, ANTHROPIC, fake))
    assert len(fake.bodies) == 2 and fake.bodies[0] == fake.bodies[1]
    assert result.transport_retries == 1 and result.key == request_key(fake.bodies[0], 1)
    assert [r["source"] for r in rows(tmp_path)] == ["retry", "api"]


def test_waits_double_and_are_never_shorter_than_retry_after(tmp_path):
    sleeps = []
    fake = FakeClient(StatusError(429), StatusError(503, retry_after="7"), StatusError(500), anthropic_response())
    assert complete(caller(tmp_path, ANTHROPIC, fake, sleeps=sleeps)).transport_retries == 3
    assert sleeps == [2.0, 7.0, 8.0]
    assert [(r["retry"], r["status"], r["wait_s"]) for r in rows(tmp_path) if r["source"] == "retry"] == [
        (1, 429, 2.0), (2, 503, 7.0), (3, 500, 8.0)]


@pytest.mark.parametrize("failure", [StatusError(400), StatusError(401), StatusError(404), ValueError("a bug")])
def test_any_other_failure_is_raised_at_once_and_its_reservation_released(tmp_path, failure):
    fake = FakeClient(failure)
    c = caller(tmp_path, ANTHROPIC, fake)
    with pytest.raises(type(failure)):
        complete(c)
    assert len(fake.bodies) == 1 and c.budget.spent() == (0, 0.0)
    assert c.budget.reserve("claude", 10**7 - 1, 99.0)


def test_retries_stop_at_the_policy_s_count(tmp_path):
    fake = FakeClient(StatusError(529))
    with pytest.raises(StatusError):
        complete(caller(tmp_path, ANTHROPIC, fake, retries=3))
    assert len(fake.bodies) == 4 and [r["source"] for r in rows(tmp_path)] == ["retry"] * 3 + ["api"]


# ------------------------------------------------------------------------------------------ checks
@pytest.mark.parametrize("response, error", [
    (anthropic_response(stop="refusal"), Refusal),
    (anthropic_response(stop="max_tokens"), Truncated),
    (anthropic_response(text='{"consistent": "maybe"}'), OutputInvalid),
])
def test_a_refused_truncated_or_invalid_answer_is_charged_and_logged_but_not_cached(tmp_path, response, error):
    c = caller(tmp_path, ANTHROPIC, FakeClient(response))
    with pytest.raises(error):
        complete(c, schema=Verdict)
    assert not (tmp_path / "cache").exists() or not any((tmp_path / "cache").rglob("*.json"))
    assert c.budget.spent("claude")[0] == 52
    assert rows(tmp_path)[-1]["error"] == error.__name__ and rows(tmp_path)[-1]["input_tokens"] == 40


# ------------------------------------------------------------------------------------------ the call log
def test_the_call_log_holds_no_prompt_or_response_text(tmp_path):
    c = caller(tmp_path, ANTHROPIC, FakeClient(StatusError(429), anthropic_response()))
    complete(c)
    complete(c)
    text = (tmp_path / "log.jsonl").read_text("utf-8")
    assert "MARKER" not in text and "Ana" not in text
    assert all(set(r) <= FIELDS | {"timestamp"} for r in rows(tmp_path))


def test_the_call_log_refuses_text_and_unknown_fields(tmp_path):
    log = CallLog(tmp_path / "log.jsonl")
    with pytest.raises(ValueError, match="at most"):
        log.write(tag="x" * (MAX_TEXT + 1))
    with pytest.raises(ValueError, match="not a call-log field"):
        log.write(prompt="Ana is older than Ben.")
    with pytest.raises(ValueError):
        log.write(tag=["a", "list"])
    assert not log.path.exists()


def test_a_tag_too_long_for_the_log_is_refused_before_anything_is_sent(tmp_path):
    fake = FakeClient(anthropic_response())
    with pytest.raises(ValueError, match="tag"):
        complete(caller(tmp_path, ANTHROPIC, fake), tag="t" * (MAX_TEXT + 1))
    assert fake.bodies == []
