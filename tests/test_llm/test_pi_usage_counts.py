"""Fixed, content-free Pi wire shapes; never a Pi process or a provider call."""

from __future__ import annotations

import inspect
import json
from copy import deepcopy
from pathlib import Path

import pytest

from temper_ai.llm import pi_stream
from temper_ai.llm.pi_stream import (
    MAX_SAFE_USAGE_COUNT,
    PiEventMapper,
    _usage,
    record_outcome,
)
from temper_ai.observability.event_types import EventType
from temper_ai.observability.run_totals import _agents_by_run
from tests.test_llm.test_pi_stream import COMPLETED, FAILED, Spy

FIELDS = {
    "prompt_tokens": "input",
    "completion_tokens": "output",
    "cached_prompt_tokens": "cacheRead",
    "cache_write_tokens": "cacheWrite",
    "total_tokens": "totalTokens",
}
COMPONENTS = tuple(FIELDS)[:-1]
NORMAL = {"input": 100, "output": 20, "cacheRead": 80, "cacheWrite": 0,
          "totalTokens": 200, "cost": {"total": 0.125}}
POSITIVE = {**NORMAL, "cacheWrite": 10, "totalTokens": 210}
FIXTURES = Path(__file__).parents[1] / "fixtures"
BASELINE = json.loads((FIXTURES / "pi_usage_legacy_totals.json").read_text())
OBSERVATIONS = json.loads((FIXTURES / "pi_usage_observations.json").read_text())


def mapper(spy):
    return PiEventMapper(spy, execution_id="usage-fixed", agent_event_id="agent",
                         agent_name="fixed", session_id="session-fixed")


def call(usage, *, stop="stop", api="anthropic-messages", provider="anthropic"):
    message = {"role": "assistant", "api": api, "provider": provider, "model": "fixed",
               "content": [], "stopReason": stop, "usage": usage}
    return [{"type": "message_start", "message": message},
            {"type": "message_end", "message": message}]


def test_combined_report_failed_before_usage_and_compaction_preserve_totals():
    """Happy path first; Data confirmed no zero class, not even normal cacheWrite 0."""
    spy = Spy()
    mapped = mapper(spy)
    mapped.handle_all(call(deepcopy(NORMAL)))
    expected = {"prompt_tokens": 100, "completion_tokens": 20, "cached_prompt_tokens": 80,
                "cache_write_tokens": 0, "total_tokens": 200, "cost_usd": 0.125}
    assert mapped.finish().tokens == expected
    assert mapped.usage_snapshot() == {"cost_usd": 0.125, "total_tokens": 200, "llm_calls": 1}

    no_report = {**dict.fromkeys(FIELDS.values(), 0), "cost": {"total": 0}}
    mapped.handle_all(call(no_report, stop="error"))
    mapped.handle_all([{"type": "auto_compaction_start", "reason": "fixed"},
                       {"type": "auto_compaction_end", "result": {"tokensBefore": 999}},
                       {"type": "agent_settled"}])
    ends = [e["data"] for e in spy.of(COMPLETED, FAILED)]
    assert len(ends) == 3
    assert {key: ends[0][key] for key in FIELDS} == BASELINE["cases"][0]["observations"]
    assert all(ends[index][key] is None for index in (1, 2) for key in FIELDS)
    assert [e["call_kind"] for e in ends] == ["model", "model", "compaction"]
    assert [e["cost_usd"] for e in ends] == [0.125, 0.0, 0.0]
    assert all(e["cost_basis"] == "pi_estimate" for e in ends)
    outcome = mapped.finish()
    assert outcome.tokens == expected
    assert mapped.usage_snapshot() == {"cost_usd": 0.125, "total_tokens": 200, "llm_calls": 3}
    record_outcome(spy, mapped, outcome)
    agent = spy.events[-1]["data"]
    assert (agent["tokens"], agent["prompt_tokens"], agent["completion_tokens"], agent["cost_usd"]) == (
        200, 100, 20, 0.125)


@pytest.mark.parametrize("key, field", FIELDS.items())
@pytest.mark.parametrize("bad", [None, True, False, 0, 7.9, 7.0, -1, float("nan"), float("inf"),
                                float("-inf"), 2**53, "7", [], {}])
def test_each_invalid_or_zero_class_is_unknown_without_truncation(key, field, bad):
    raw = {**POSITIVE, field: bad}
    assert _usage(raw)[key] is None
    del raw[field]
    assert _usage(raw)[key] is None


@pytest.mark.parametrize("key", COMPONENTS)
@pytest.mark.parametrize("count", [1, MAX_SAFE_USAGE_COUNT])
def test_each_positive_safe_component_survives(key, count):
    assert _usage({**POSITIVE, FIELDS[key]: count})[key] == count


@pytest.mark.parametrize("api, provider", [
    ("anthropic-messages", "anthropic"), ("future-api", "future-provider"),
    (None, None), ([], {}),
])
def test_zeros_are_unknown_and_positives_observed_regardless_of_api(api, provider):
    spy = Spy()
    mapped = mapper(spy)
    mapped.handle_all(call(NORMAL, api=api, provider=provider))
    ended = spy.of(COMPLETED)[0]["data"]
    assert {key: ended[key] for key in FIELDS} == BASELINE["cases"][0]["observations"]
    for key, field in FIELDS.items():
        assert _usage({**POSITIVE, field: 0})[key] is None
    assert _usage(POSITIVE)["total_tokens"] == 210


@pytest.mark.parametrize("raw", [None, {}, [], False, "usage", dict.fromkeys(FIELDS.values(), 0),
                                 {**dict.fromkeys(FIELDS.values(), 0), "totalTokens": 91,
                                  "cost": {"total": 0.25}}])
def test_no_object_or_all_four_zero_means_no_usable_report(raw):
    result = _usage(raw)
    assert all(result[key] is None for key in FIELDS)
    assert result["cost_usd"] == (0.25 if isinstance(raw, dict) and raw.get("cost") else 0.0)


@pytest.mark.parametrize("long_write", [1, 10, 11, MAX_SAFE_USAGE_COUNT, 2**53])
def test_one_hour_writes_are_not_classified_as_ordinary_cache_writes(long_write):
    result = _usage({**POSITIVE, "cacheWrite1h": long_write})
    assert result["cache_write_tokens"] is None and result["total_tokens"] is None
    assert result["cost_usd"] == 0.125


@pytest.mark.parametrize("long_write", [0, None, False, True, -1, 1.5, "1"])
def test_only_a_positive_integer_one_hour_count_triggers_the_guard(long_write):
    # A positive ordinary write remains a count, NOT evidence of its pricing tier.
    assert _usage({**POSITIVE, "cacheWrite1h": long_write})["cache_write_tokens"] == 10


@pytest.mark.parametrize("raw", [
    {**POSITIVE, "totalTokens": None}, {**POSITIVE, "totalTokens": 211},
    {**POSITIVE, "totalTokens": 2**53}, {**POSITIVE, "input": None},
    {**POSITIVE, "input": "100"}, {**POSITIVE, "input": 7.9}, NORMAL,
    {**POSITIVE, "input": MAX_SAFE_USAGE_COUNT},
])
def test_total_is_neither_an_unchecked_number_nor_a_partial_sum(raw):
    assert _usage(raw)["total_tokens"] is None
    assert _usage(POSITIVE)["total_tokens"] == 210
    without_total = {k: v for k, v in POSITIVE.items() if k != "totalTokens"}
    assert _usage(without_total)["total_tokens"] is None  # never synthesize it


def test_safe_integer_upper_bound_total_with_all_components_known():
    raw = {"input": MAX_SAFE_USAGE_COUNT - 3, "output": 1, "cacheRead": 1,
           "cacheWrite": 1, "totalTokens": MAX_SAFE_USAGE_COUNT}
    assert _usage(raw)["total_tokens"] == MAX_SAFE_USAGE_COUNT


@pytest.mark.parametrize("case", BASELINE["cases"], ids=lambda case: case["name"])
def test_current_master_numeric_baseline_and_independent_observations(case):
    assert BASELINE["master_commit"] == "296711b41065f1b2ebf94d4ad54b18ccfbc5c918"
    spy = Spy()
    mapped = mapper(spy)
    raw = deepcopy(case["raw"])
    events = ([{"type": "compaction_start"}, {"type": "compaction_end", "result": {"usage": raw}}]
              if case["compaction"] else call(raw))
    mapped.handle_all([*events, {"type": "agent_settled"}])
    ended = spy.of(COMPLETED)[0]["data"]
    assert {key: ended[key] for key in FIELDS} == case["observations"]
    assert ended["cost_usd"] == case["tokens"]["cost_usd"]
    assert mapped.finish().tokens == case["tokens"]
    assert mapped.usage_snapshot() == case["snapshot"]


@pytest.mark.parametrize("case", OBSERVATIONS["cases"], ids=lambda case: case["name"])
def test_data_fixed_catch_and_clean_cases(case):
    spy = Spy()
    mapped = mapper(spy)
    if case.get("compaction"):
        events = [{"type": "compaction_start"},
                  {"type": "compaction_end", "result": {"usage": case["raw"]}}]
    else:
        events = call(case["raw"], stop=case.get("stop", "stop"),
                      api=case.get("api", "anthropic-messages"), provider=case.get("provider", "anthropic"))
        if case.get("start_usage"):
            events[0] = {"type": "message_start", "message": {**events[0]["message"],
                                                               "usage": case["start_usage"]}}
        if case.get("response_model"):
            events[1]["message"] = {**events[1]["message"], "responseModel": case["response_model"]}
    mapped.handle_all([*events, {"type": "agent_settled"}])
    ended = spy.of(COMPLETED, FAILED)[0]["data"]
    assert {key: ended[key] for key in FIELDS} == case["expected"]
    assert ended["call_kind"] == ("compaction" if case.get("compaction") else "model")
    if case.get("compaction"):
        assert ended.get("provider") is None and ended.get("model") is None
    else:
        assert ended["model"] == case.get("response_model", "fixed")
    if case.get("start_usage"):
        # Only the final snapshot, not both start and final; nullable observations
        # do not subtract raw final counts from the independent legacy aggregate.
        assert mapped.finish().tokens["total_tokens"] == case["raw"]["totalTokens"]


def test_run_spend_reader_null_fallback_and_numeric_agent_end():
    # Actual fixed 100/20/80/0/200 mapper events -> pure row reducer, no database.
    # An unfinished/lost agent's unknown call total is a floor, not raw legacy usage.
    spy = Spy()
    mapped = mapper(spy)
    mapped.handle_all([*call(NORMAL), {"type": "agent_settled"}])
    ended = spy.of(COMPLETED)[0]
    data = ended["data"]
    assert data["total_tokens"] is None
    rows = [("fixed", ended["type"], ended["parent_id"], data["cost_usd"], data["total_tokens"], None)]
    before_end = _agents_by_run(rows)["fixed"]["agent"].spent()
    assert (before_end.cost_usd, before_end.total_tokens) == (0.125, 0)
    outcome = mapped.finish()
    record_outcome(spy, mapped, outcome)
    agent_end = spy.events[-1]
    data = agent_end["data"]
    assert agent_end["type"] == str(EventType.AGENT_COMPLETED)
    assert data["tokens"] == 200
    rows.append(("fixed", agent_end["type"], agent_end["parent_id"], data["cost_usd"], None, data["tokens"]))
    after_end = _agents_by_run(rows)["fixed"]["agent"].spent()
    assert (after_end.cost_usd, after_end.total_tokens) == (0.125, 200)


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_unreachable_nonfinite_legacy_token_crash_becomes_ignore(nonfinite):
    spy = Spy()
    mapped = mapper(spy)
    mapped.handle_all(call({**NORMAL, "input": nonfinite}))
    assert mapped.finish().tokens == {**BASELINE["cases"][0]["tokens"], "prompt_tokens": 0}
    assert spy.of(COMPLETED)[0]["data"]["prompt_tokens"] is None


@pytest.mark.parametrize("old, new, value", [
    ("type(value) is int", "isinstance(value, int)", True),
    ("0 < value <= MAX_SAFE_USAGE_COUNT", "0 <= value <= MAX_SAFE_USAGE_COUNT", 0),
    ("0 < value <= MAX_SAFE_USAGE_COUNT", "value <= MAX_SAFE_USAGE_COUNT", -1),
    ("0 < value <= MAX_SAFE_USAGE_COUNT", "0 < value", 2**53),
    ("return value if type(value) is int", "return int(value) if isinstance(value, (int, float))", 7.9),
])
def test_numeric_guard_removals_are_caught(old, new, value):
    source = inspect.getsource(pi_stream._positive_usage_count)
    assert source.count(old) == 1
    scope = dict(vars(pi_stream))
    exec(compile(source.replace(old, new), "<count-guard-mutant>", "exec"), scope)
    with pytest.raises(AssertionError):
        assert scope["_positive_usage_count"](value) is None


@pytest.mark.parametrize("old, new, raw, field, expected", [
    ("tokens[\"cache_write_tokens\"] = None", "pass", {**POSITIVE, "cacheWrite1h": 2},
     "cache_write_tokens", None),
    ("type(long_write) is int", "isinstance(long_write, int)", {**POSITIVE, "cacheWrite1h": True},
     "cache_write_tokens", 10),
    (" and long_write > 0", "", {**POSITIVE, "cacheWrite1h": 0}, "cache_write_tokens", 10),
    ("any(count is None for count in components)", "False", NORMAL, "total_tokens", None),
    ("tokens[\"total_tokens\"] != sum(count for count in components if count is not None)",
     "False", {**POSITIVE, "totalTokens": 211}, "total_tokens", None),
])
def test_usage_guard_removals_are_caught(old, new, raw, field, expected):
    source = inspect.getsource(_usage)
    assert source.count(old) == 1
    scope = dict(vars(pi_stream))
    exec(compile(source.replace(old, new), "<usage-guard-mutant>", "exec"), scope)
    with pytest.raises(AssertionError):
        assert scope["_usage"](raw)[field] == expected
