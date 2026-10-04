"""Pi's RPC stream as Temper events (A2): framing, redaction, mapping, outcome and history.

Most tests read real Pi 0.87.1 captures (fixtures/pi_a2: scripted, offline model calls; see
pi_a2_replay). The rest feed a few hand-written events, for what a capture cannot show.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pytest

from temper_ai.llm.pi_stream import (
    MAX_COUNTED_TYPES,
    PROGRESS_LIMIT,
    REDACTED,
    JsonlSplitter,
    PiEventMapper,
    PiStreamError,
    Redactor,
)
from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import get_events
from tests.test_llm import pi_a2_replay as replay

FRONTEND_FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "__tests__" / "fixtures" / "pi_a2"
SCENARIOS = replay.SCENARIOS
STARTED, COMPLETED, FAILED = (str(EventType.LLM_CALL_STARTED), str(EventType.LLM_CALL_COMPLETED),
                              str(EventType.LLM_CALL_FAILED))
TOOL_STARTED = str(EventType.TOOL_CALL_STARTED)


class Spy:
    """A recorder that keeps what it is given, in order."""

    def __init__(self):
        self.events: list[dict] = []
        self.chunks: list[dict] = []
        self.timeline: list[tuple] = []

    def record(self, event_type, data=None, parent_id=None, execution_id=None, status=None, event_id=None):
        self.events.append({"type": str(event_type), "id": event_id, "data": data or {}, "status": status,
                            "parent_id": parent_id})
        self.timeline.append(("event", str(event_type), event_id))
        return event_id

    def broadcast_stream_chunk(self, agent_id, content, chunk_type="content", done=False, call_id=None, seq=None):
        self.chunks.append({"content": content, "chunk_type": chunk_type, "done": done, "call_id": call_id,
                            "seq": seq})
        self.timeline.append(("chunk", chunk_type, call_id))

    def of(self, *types: str) -> list[dict]:
        return [e for e in self.events if e["type"] in types]


def mapper_for(spy: Spy, name: str = "x", known=()) -> PiEventMapper:
    return PiEventMapper(spy, execution_id=f"a2-{name}", agent_event_id="agent", agent_name="pi-agent",
                         session_id=f"session-{name}", redactor=Redactor([replay.SECRET]), known_event_ids=known)


def mapped(name: str, events: list[dict] | None = None, known=()) -> tuple[PiEventMapper, Spy]:
    spy = Spy()
    mapper = mapper_for(spy, name, known)
    mapper.handle_all(replay.load_events(name) if events is None else events)
    return mapper, spy


# ---- framing -------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_any_read_size_gives_the_same_events(name):
    data = replay.raw_bytes(name)
    whole = [json.loads(line) for line in data.split(b"\n") if line.strip()]
    for piece in (1, 7, 65536) if len(data) < 100_000 else (7, 65536):
        assert replay.load_events(name, piece) == whole


def test_only_a_line_feed_ends_a_record_and_a_character_may_be_cut_anywhere():
    first = {"type": "message_update", "text": "a\u2028b\u2029c — ünïcode 🔧"}
    data = json.dumps(first, ensure_ascii=False).encode() + b"\r\n\n" + b'{"type": "x"}\n'
    for cut in range(1, len(data)):
        splitter = JsonlSplitter()
        out = splitter.feed(data[:cut]) + splitter.feed(data[cut:])
        splitter.finish()
        assert out == [first, {"type": "x"}]


@pytest.mark.parametrize("data, code", [
    (b"\xff\xfe{}\n", "invalid_utf8"),
    (b"{not json}\n", "invalid_json"),
    (b"[1, 2]\n", "not_an_object"),
])
def test_a_broken_line_is_an_error(data, code):
    with pytest.raises(PiStreamError) as err:
        JsonlSplitter().feed(data)
    assert err.value.code == code


def test_a_line_too_long_or_never_ended_is_an_error():
    with pytest.raises(PiStreamError) as err:
        JsonlSplitter(max_line_bytes=10).feed(b'{"a": "0123456789"}\n')
    assert err.value.code == "line_too_long"
    with pytest.raises(PiStreamError) as err:
        JsonlSplitter(max_line_bytes=10).feed(b'{"a": "0123456789')
    assert err.value.code == "line_too_long"
    splitter = JsonlSplitter()
    assert splitter.feed(b'{"a": 1}') == []
    with pytest.raises(PiStreamError) as err:
        splitter.finish()
    assert err.value.code == "incomplete_line_at_eof"


# ---- redaction ------------------------------------------------------------------------

SECRET = "sk-test-0123456789"  # synthetic


def test_secret_values_and_secret_named_fields_are_replaced():
    r = Redactor([SECRET, "short"])
    assert r.secrets == [SECRET]  # a value this short would blank out ordinary words
    out = r.obj({"command": f"curl -H 'x: {SECRET}'", "Authorization": "Bearer abc", "api-key": "k",
                 "nested": [{"password": "p"}, SECRET], "n": 3})
    assert out == {"command": f"curl -H 'x: {REDACTED}'", "Authorization": REDACTED, "api-key": REDACTED,
                   "nested": [{"password": REDACTED}, REDACTED], "n": 3}


def test_a_secret_split_across_streamed_pieces_never_goes_out():
    r = Redactor([SECRET])
    text = f"key={SECRET}; then {SECRET[:5]} and {SECRET}."
    for i in range(len(text) + 1):
        for j in range(i, len(text) + 1):
            stream = r.stream()
            outs = [stream.feed(text[:i]), stream.feed(text[i:j]), stream.feed(text[j:]), stream.flush()]
            assert "".join(outs) == r.text(text)
            assert not any(SECRET in o for o in outs)


# ---- mapping real captures ---------------------------------------------------------------


def test_the_captures_hold_the_planted_secret():
    assert any(replay.SECRET in replay.raw_bytes(n).decode() for n in SCENARIOS)


@pytest.mark.parametrize("name", SCENARIOS)
def test_no_secret_and_nothing_of_the_system_message_is_recorded_or_sent(name):
    _, spy = mapped(name)
    sent = json.dumps([spy.events, spy.chunks], ensure_ascii=False, default=str)
    assert replay.SECRET not in sent
    assert replay.SYSTEM_MARKER not in sent


@pytest.mark.parametrize("name", SCENARIOS)
def test_a_tool_the_model_writes_is_not_a_tool_that_runs(name):
    events = replay.load_events(name)
    _, spy = mapped(name, events)
    written = sum(1 for e in events if e.get("type") == "message_update"
                  and e["assistantMessageEvent"].get("type") == "toolcall_start")
    ran = {e["toolCallId"] for e in events if e.get("type") == "tool_execution_start"}
    requests = [c for c in spy.chunks if c["chunk_type"] == "tool_call" and c["content"].startswith("\n🔧")]
    assert len(requests) == written
    assert len(spy.of(TOOL_STARTED)) == len(ran)
    calls = {e["id"] for e in spy.of(STARTED)}
    for tool in spy.of(TOOL_STARTED):
        writer = tool["data"]["llm_call_id"]
        assert writer in calls
        # The model finished writing the call before Pi ran it.
        at = spy.timeline.index(("event", TOOL_STARTED, tool["id"]))
        assert ("chunk", "tool_call", writer) in spy.timeline[:at]


@pytest.mark.parametrize("name", SCENARIOS)
def test_tool_progress_is_live_only_and_each_report_replaces_the_last(name):
    events = replay.load_events(name)
    _, spy = mapped(name, events)
    updates = [e for e in events if e.get("type") == "tool_execution_update"]
    progress = [c for c in spy.chunks if c["chunk_type"] == "tool_progress"]
    assert len(progress) == len(updates)
    by_tool: dict[str, list[dict]] = defaultdict(list)
    for c in progress:
        by_tool[c["call_id"]].append(c)
        assert len(c["content"]) <= PROGRESS_LIMIT
    for reports in by_tool.values():
        assert [c["seq"] for c in reports] == list(range(1, len(reports) + 1))
        # Each report is everything so far, so it holds the one before: adding them up would repeat it.
        for before, after in zip(reports, reports[1:], strict=False):
            assert after["content"].startswith(before["content"]) or len(after["content"]) == PROGRESS_LIMIT
    assert not [e for e in spy.events if "progress" in e["type"] or "chunk" in e["type"]]


@pytest.mark.parametrize("name", SCENARIOS)
def test_usage_is_taken_once_per_model_call(name):
    events = replay.load_events(name)
    mapper, spy = mapped(name, events)
    outcome = mapper.finish()
    finals = [(e["message"].get("usage") or {}).get("totalTokens") or 0 for e in events
              if e.get("type") == "message_end" and e["message"].get("role") == "assistant"]
    compactions = [((e.get("result") or {}).get("usage") or {}).get("totalTokens") or 0 for e in events
                   if e.get("type") in ("compaction_end", "auto_compaction_end")]
    assert outcome.tokens["total_tokens"] == sum(finals) + sum(compactions)
    ends = spy.of(COMPLETED, FAILED)
    assert sum(e["data"]["total_tokens"] for e in ends) == outcome.tokens["total_tokens"]
    # Pi repeats the running total on every update: adding those up counts it many times.
    running = sum((e.get("usage") or {}).get("totalTokens") or 0 for e in events
                  if e.get("type") == "message_update")
    if name in ("s1_stream", "s3_large_untrusted"):
        assert running > outcome.tokens["total_tokens"]


@pytest.mark.parametrize("name", SCENARIOS)
def test_streamed_words_add_up_to_the_final_message_which_has_the_last_word(name):
    _, spy = mapped(name)
    for end in spy.of(COMPLETED, FAILED):
        data = end["data"]
        assert data["authoritative_final"] is True
        if data["call_kind"] != "model":
            continue
        mine = [c for c in spy.chunks if c["call_id"] == data["llm_call_id"]]
        words = "".join(c["content"] for c in mine if c["chunk_type"] == "content")
        thinking = "".join(c["content"] for c in mine if c["chunk_type"] == "thinking")
        assert words == data["response_content"]
        assert thinking == (data["reasoning"] or "")
        assert [c["seq"] for c in mine] == list(range(1, len(mine) + 1))
        assert mine[-1]["done"] is True


@pytest.mark.parametrize("name", SCENARIOS)
def test_the_same_stream_read_again_maps_to_the_same_ids_and_records_nothing_twice(name):
    events = replay.load_events(name)
    first, spy1 = mapped(name, events)
    _, spy2 = mapped(name, events)
    assert [e["id"] for e in spy2.events] == [e["id"] for e in spy1.events]
    assert len(set(first.recorded)) == len(first.recorded)
    # A worker that restarts halfway reads the stream again from the start: what was
    # recorded is not recorded again, the chunks of calls and tools that had already
    # ended are not sent again (G3), and the rest carry the same numbers.
    half = len(events) // 2
    _, before = mapped(name, events[:half])
    again, after = mapped(name, events, known=[e["id"] for e in before.events])
    assert [e["id"] for e in before.events + after.events] == [e["id"] for e in spy1.events]
    ended = {e["data"].get("llm_call_id") for e in before.of(COMPLETED, FAILED)}
    ended |= {e["data"].get("call_id") for e in before.of(str(EventType.TOOL_CALL_COMPLETED),
                                                         str(EventType.TOOL_CALL_FAILED))}
    assert after.chunks == [c for c in spy1.chunks if c["call_id"] not in ended]
    assert again.finish().tokens == first.finish().tokens


@pytest.mark.parametrize("name", SCENARIOS)
def test_a_model_call_ending_is_not_the_agent_ending(name):
    mapper, spy = mapped(name)
    agent_events = {str(EventType.AGENT_COMPLETED), str(EventType.AGENT_FAILED)}
    assert not [e for e in spy.events if e["type"] in agent_events]
    outcome = mapper.finish(result_schema=replay.schema_for(name))
    calls = [e["status"] for e in spy.of(COMPLETED, FAILED)]
    expected = {"s1_stream": "completed", "s2_errors": "failed", "s3_large_untrusted": "completed",
                "s4_retry_recover": "completed", "s5_retry_fail": "failed", "s6_abort": "failed",
                "s7_compaction": "completed"}[name]
    assert outcome.status == expected
    if name == "s2_errors":  # every model call went fine; the agent still failed
        assert set(calls) == {"completed"}
        assert outcome.errors == ["the reply has no JSON result"]
    if name == "s4_retry_recover":  # a model call failed; the agent still succeeded
        assert "failed" in calls
        assert [e["status"] for e in spy.of(str(EventType.LLM_RETRY))] == ["running", "completed"]
    if name == "s6_abort":
        assert outcome.errors == ["the last model call was stopped: Request was aborted"]
    if name == "s1_stream":
        assert outcome.structured_output == {"status": "ok", "ticks": 4, "label": "Grüße ✓"}


# ---- outcome, from hand-written events -------------------------------------------------------

SETTLED = {"type": "agent_settled"}


def assistant(text: str = "", *, stop: str = "stop", hidden_thinking: bool = False, total: int = 10) -> dict:
    content: list[dict] = []
    if hidden_thinking:
        content.append({"type": "thinking", "thinking": "", "redacted": True})
    if text:
        content.append({"type": "text", "text": text})
    return {"role": "assistant", "content": content, "stopReason": stop, "provider": "fixture",
            "model": "fixture-1", "usage": {"input": total, "output": 0, "totalTokens": total, "cost": {"total": 0}}}


def turn(message: dict, deltas: tuple[str, ...] = ()) -> list[dict]:
    out: list[dict] = [{"type": "message_start", "message": {"role": "assistant", "content": []}}]
    if deltas:
        out.append({"type": "message_update", "assistantMessageEvent": {"type": "text_start", "contentIndex": 0}})
        out += [{"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0,
                                                                      "delta": d}} for d in deltas]
        out.append({"type": "message_update", "assistantMessageEvent": {"type": "text_end", "contentIndex": 0}})
    out.append({"type": "message_end", "message": message})
    return out


def tool_use(*ids: str) -> dict:
    """An assistant message asking for one read per id."""
    msg = assistant(stop="toolUse")
    msg["content"] = [{"type": "toolCall", "id": i, "name": "read", "arguments": {"path": "note.txt"}}
                      for i in ids]
    return msg


def ran(tool_id: str, text: str = "note") -> list[dict]:
    return [{"type": "tool_execution_start", "toolCallId": tool_id, "toolName": "read",
             "args": {"path": "note.txt"}},
            {"type": "tool_execution_end", "toolCallId": tool_id, "toolName": "read",
             "result": {"content": [{"type": "text", "text": text}]}, "isError": False}]


def retried(attempt: int, ok: bool) -> list[dict]:
    return [{"type": "auto_retry_start", "attempt": attempt, "maxAttempts": 3, "delayMs": 0,
             "errorMessage": "overloaded"},
            {"type": "auto_retry_end", "attempt": attempt, "success": ok}]


def test_g1_each_model_calls_retries_are_their_own_events():
    # Two model calls each retried once: Pi numbers both retries attempt 1.
    events = [*turn(assistant("", stop="error")), *retried(1, True), *turn(tool_use("t1")), *ran("t1"),
              *turn(assistant("", stop="error")), *retried(1, True), *turn(assistant("Done.")), SETTLED]
    _, spy = mapped("g1", events)
    retries = spy.of(str(EventType.LLM_RETRY))
    assert len(retries) == 4
    assert len({e["id"] for e in retries}) == 4
    # Read again after a restart: the same ids, nothing recorded twice.
    _, again = mapped("g1", events, known=[e["id"] for e in spy.events])
    assert again.events == []


def test_g2_a_tool_id_used_again_by_a_later_call_is_a_new_tool():
    # Some providers number tool calls per reply, so a later reply reuses "t1".
    events = [*turn(tool_use("t1")), *ran("t1", "first"), *turn(tool_use("t1")), *ran("t1", "second"),
              *turn(assistant("Done.")), SETTLED]
    mapper, spy = mapped("g2", events)
    starts = spy.of(TOOL_STARTED)
    ends = spy.of(str(EventType.TOOL_CALL_COMPLETED))
    assert len(starts) == 2 and len(ends) == 2
    assert len({e["id"] for e in starts + ends}) == 4
    assert len({e["data"]["call_id"] for e in starts}) == 2
    assert [e["data"]["output"] for e in ends] == ["first", "second"]
    # Each end belongs to its own start.
    assert [e["data"]["call_id"] for e in starts] == [e["data"]["call_id"] for e in ends]
    assert mapper.finish().status == "completed"


def test_g3_a_restart_does_not_send_finished_calls_words_again():
    first = [*turn(assistant("Hello there."), ("Hello ", "there."))]
    second = [*turn(assistant("Bye now."), ("Bye ", "now."))]
    _, before = mapped("g3", first + second[:3])  # cut while the second call is speaking
    words = lambda spy: "".join(c["content"] for c in spy.chunks)  # noqa: E731
    assert words(before).startswith("Hello there.") and words(before) != "Hello there."
    first_call = {c["call_id"] for c in before.chunks if c["content"].startswith("Hello")}
    _, after = mapped("g3", first + second + [SETTLED], known=[e["id"] for e in before.events])
    # The finished first call is not told again; the unfinished second is, in full.
    assert words(after) == "Bye now."
    assert not first_call & {c["call_id"] for c in after.chunks}
    assert {e["type"] for e in after.events} >= {COMPLETED}


def test_a_tool_that_never_ends_fails_the_turn():
    events = [*turn(tool_use("t1")), {"type": "tool_execution_start", "toolCallId": "t1", "toolName": "read",
                                       "args": {}}, *turn(assistant("Done.")), SETTLED]
    outcome, _ = outcome_of(events)
    assert outcome.status == "failed"
    assert any("never ended" in e for e in outcome.errors)


def outcome_of(events: list[dict], schema: dict | None = None):
    spy = Spy()
    mapper = mapper_for(spy)
    mapper.handle_all(events)
    return mapper.finish(result_schema=schema), spy


@pytest.mark.parametrize("reply, error", [
    ('Done.\n{"status": "ok", "ticks": 3}', None),
    ("Done, and no result.", "the reply has no JSON result"),
    ('Done.\n{"status": "ok", "ticks": "3"}', "the result does not match its schema: 'ticks' is not integer"),
    ('Done.\n{"status": "ok", "ticks": true}', "the result does not match its schema: 'ticks' is not integer"),
    ('Done.\n{"ticks": 3}', "the result does not match its schema: missing 'status'"),
])
def test_the_result_is_checked_against_its_schema(reply, error):
    outcome, _ = outcome_of([*turn(assistant(reply)), SETTLED], replay.RESULT_SCHEMA)
    assert outcome.errors == ([error] if error else [])
    assert outcome.status == ("failed" if error else "completed")


def test_only_a_settled_pi_with_an_answer_succeeds():
    answer = turn(assistant("Fine."))
    assert outcome_of([*answer, SETTLED])[0].status == "completed"
    assert outcome_of(answer)[0].errors == ["Pi stopped before it settled: the turn did not finish"]
    assert outcome_of([SETTLED])[0].errors == ["Pi gave no answer"]
    open_call = [{"type": "message_start", "message": {"role": "assistant"}}, SETTLED]
    assert "a model call never ended" in outcome_of(open_call)[0].errors
    refused = [{"type": "response", "command": "prompt", "success": False, "error": "busy"}, *answer, SETTLED]
    assert outcome_of(refused)[0].errors == ["Pi refused 'prompt': busy"]
    cut, _ = outcome_of([*turn(assistant("Cut sho", stop="length")), SETTLED])
    assert cut.status == "completed"
    assert cut.warnings == ["the answer was cut off at the model's output limit"]


def test_the_final_message_is_what_the_call_said():
    outcome, spy = outcome_of([*turn(assistant("Hello world."), deltas=("Hel", "lo wrold")), SETTLED])
    assert "".join(c["content"] for c in spy.chunks if c["chunk_type"] == "content") == "Hello wrold"
    [end] = spy.of(COMPLETED)
    assert end["data"]["response_content"] == "Hello world."
    assert end["data"]["authoritative_final"] is True
    assert outcome.output == "Hello world."


def test_thinking_the_provider_keeps_hidden_is_not_shown():
    _, spy = outcome_of([*turn(assistant("Fine.", hidden_thinking=True)), SETTLED])
    [end] = spy.of(COMPLETED)
    assert end["data"]["reasoning"] is None
    assert end["data"]["thinking_exposed"] is False
    assert end["data"]["thinking_redacted_blocks"] == 1
    assert not [c for c in spy.chunks if c["chunk_type"] == "thinking"]


def test_the_system_message_is_never_read():
    system = {"role": "system", "content": "PROMPT-AND-TOOLS", "tools": [{"name": "bash"}]}
    events = [{"type": "message_start", "message": system}, {"type": "message_end", "message": system},
              *turn(assistant("Fine.")), SETTLED]
    outcome, spy = outcome_of(events)
    assert "PROMPT-AND-TOOLS" not in json.dumps([spy.events, spy.chunks], default=str)
    assert outcome.llm_calls == 1
    assert outcome.counts["ignored"]["message:system"] == 1


def test_unknown_events_are_counted_and_reported_not_shown():
    unknown = [{"type": f"new_kind_{i}"} for i in range(MAX_COUNTED_TYPES + 10)] + [{"no": "type"}]
    outcome, spy = outcome_of([*unknown, *turn(assistant("Fine.")), SETTLED])
    assert outcome.status == "completed"
    assert len(outcome.counts["unknown"]) == MAX_COUNTED_TYPES + 1  # the rest share "<other>"
    assert outcome.warnings == [f"{MAX_COUNTED_TYPES + 11} Pi events of unknown types were not shown"]
    assert {e["type"] for e in spy.events} == {STARTED, COMPLETED}


def test_tool_results_that_are_not_text_are_described_not_stored():
    image_bytes = b"\x89PNG\r\n\x1a\n synthetic"
    image = base64.b64encode(image_bytes).decode()
    start = {"type": "tool_execution_start", "toolCallId": "t1", "toolName": "read", "args": {"path": "a.png"}}
    end = {"type": "tool_execution_end", "toolCallId": "t1", "toolName": "read", "isError": False,
           "result": {"content": [{"type": "text", "text": "see image"},
                                  {"type": "image", "mimeType": "image/png", "data": image},
                                  {"type": "audio", "data": "zzz"}],
                      "details": {"fullOutputPath": "/tmp/pi-out-1.txt",
                                  "truncation": {"truncated": True, "api_key": "x"}}}}
    _, spy = outcome_of([start, end, *turn(assistant("Fine.")), SETTLED])
    [done] = spy.of(str(EventType.TOOL_CALL_COMPLETED))
    data = done["data"]
    assert image not in json.dumps(data)
    assert data["content_parts"] == [
        {"type": "text", "chars": 9},
        {"type": "image", "mime_type": "image/png", "bytes": len(image_bytes),
         "sha256": hashlib.sha256(image_bytes).hexdigest()},
        {"type": "audio", "unsupported": True},
    ]
    assert "[audio result not shown]" in data["output"]
    assert data["artifacts"] == [{"kind": "full_output", "sandbox_path": "/tmp/pi-out-1.txt", "mapped": False}]
    assert data["truncation"] == {"truncated": True, "api_key": REDACTED}


# ---- what the page receives, and what the record keeps --------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_the_page_fixtures_are_what_temper_sends_and_the_record_keeps_the_whole_story(name):
    fixture = replay.view_fixture(name)
    # The frontend tests read these files: they must be what the backend sends today.
    saved = json.loads((FRONTEND_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    assert replay.shape(fixture) == replay.shape(saved)

    stored = get_events(execution_id=f"a2-{name}", limit=None)
    assert stored
    assert not [e for e in stored if any(w in e["type"] for w in ("stream", "chunk", "progress"))]
    # Losing every live chunk loses nothing: each call's final words are in the record.
    calls = {c["id"]: c for node in fixture["final"]["nodes"]
             for agent in ([node["agent"]] if node.get("agent") else node.get("agents") or [])
             for c in agent.get("llm_calls") or []}
    ends = [m["data"] for m in fixture["live"] if m.get("event_type") in (COMPLETED, FAILED)]
    assert ends
    for end in ends:
        call = calls[end["llm_call_id"]]
        assert call["status"] == ("failed" if end.get("error") else "completed")
        if end["call_kind"] == "model":
            assert (call.get("response") or "") == end["response_content"]
            assert call.get("thinking") == end["reasoning"]
