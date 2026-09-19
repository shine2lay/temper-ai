"""Tests for the ``compress`` context policy — model-driven compression.

The transcript is built the way the service builds it: system, task, then
assistant tool-call / tool-result pairs. ``_anchor`` appends what the service
would append after a compress call, so tests can walk several turns.
"""

import json

import pytest

from temper_ai.llm.context import (
    GUIDANCE,
    ContextCompressor,
    ContextError,
    estimate_messages_tokens,
    ref,
)
from temper_ai.llm.models import CallContext, LLMResponse
from temper_ai.llm.service import LLMService
from temper_ai.observability import EventType, get_events

from .conftest import MockProvider


def _turn(
    messages: list[dict], call_id: str, name: str, result: str, args: dict | None = None
) -> None:
    messages.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args or {})},
                }
            ],
        }
    )
    messages.append({"role": "tool", "tool_call_id": call_id, "content": result})


def _transcript(turns: int = 6, size: int = 3000) -> list[dict]:
    messages = [
        {"role": "system", "content": "You are a coder."},
        {"role": "user", "content": "Fix the bug in parser.py"},
    ]
    for n in range(turns):
        _turn(
            messages,
            f"c{n}",
            "Read",
            f"file {n}: " + ("x" * size),
            {"path": f"f{n}.py"},
        )
    return messages


def _anchor(
    messages: list[dict], compressor: ContextCompressor, call_id: str, result: str
) -> None:
    """What the service appends after a compress call, then the next prepare()."""
    _turn(messages, call_id, "compress", result, {"ranges": "…"})
    compressor.prepare(messages)


def _compress(
    compressor: ContextCompressor,
    messages: list[dict],
    call_id: str,
    ranges: list[dict],
) -> str:
    result = compressor.compress(messages, ranges, tool_call_id=call_id)
    _anchor(messages, compressor, call_id, result)
    return result


def _tags(view: list[dict]) -> list[str]:
    """The ref each wire message is tagged with ('' for untagged system/assistant messages)."""
    return [
        m["content"].rsplit(">", 2)[-2].split("<")[0]
        if m["role"] in ("user", "tool") and "<acp" in str(m.get("content"))
        else ""
        for m in view
    ]


class TestView:
    def test_tags_user_and_tool_messages_only(self):
        messages = _transcript(turns=1)
        view = ContextCompressor(100_000).view(messages)

        assert view[1]["content"].endswith("m00002</acp>")
        assert '<acp tokens="' in view[3]["content"] and view[3]["content"].endswith(
            "m00004</acp>"
        )
        assert "<acp" not in view[2]["content"]  # assistant messages are unnumbered
        assert view[0]["content"].endswith(GUIDANCE)

    def test_transcript_is_never_mutated(self):
        messages = _transcript(turns=2)
        before = json.dumps(messages)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        _compress(
            c,
            messages,
            "k1",
            [{"start": "m00003", "end": "m00006", "summary": "read f0, f1: nothing"}],
        )
        c.prepare(messages)

        assert json.dumps(messages[:6]) == json.dumps(json.loads(before)[:6])
        assert all(not k.startswith("_") for m in messages for k in m)

    def test_refs_are_transcript_positions(self):
        assert ref(0) == "m00001"
        assert ref(41) == "m00042"

    def test_shrinking_transcript_is_a_bug(self):
        messages = _transcript(turns=2)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        del messages[-2:]
        with pytest.raises(RuntimeError, match="shrank"):
            c.prepare(messages)


class TestCompress:
    def test_hides_the_range_and_keeps_the_anchor(self):
        messages = _transcript(turns=4)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        result = _compress(
            c,
            messages,
            "k1",
            [
                {
                    "start": "m00003",
                    "end": "m00006",
                    "summary": "f0 and f1 are irrelevant",
                },
            ],
        )

        assert result.startswith("Compressed 1 range(s): m00003–m00006 → b1 (tier 1")
        view = c.view(messages)
        refs = _tags(view)
        assert "m00003" not in refs and "m00006" not in refs
        assert "m00008" in refs and "m00010" in refs  # later turns untouched
        # the model's own compress call is the anchor and stays visible
        assert any("compress" in json.dumps(m.get("tool_calls", "")) for m in view)
        assert c.blocks["b1"].anchor == len(messages) - 1
        assert estimate_messages_tokens(view) < estimate_messages_tokens(messages)

    def test_boundaries_snap_to_tool_call_pairs(self):
        messages = _transcript(turns=3)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        # m00004 is a tool result (its call is m00003); m00005 is an assistant call (its result is m00006)
        result = _compress(
            c,
            messages,
            "k1",
            [{"start": "m00004", "end": "m00005", "summary": "f0, f1 read"}],
        )

        assert "snapped to m00003–m00006" in result
        assert c.blocks["b1"].start == 2 and c.blocks["b1"].end == 5

    def test_task_and_last_user_message_are_protected(self):
        messages = _transcript(turns=2)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        with pytest.raises(
            ContextError, match="m00002 is protected \\(the task message\\)"
        ):
            c.compress(
                messages,
                [{"start": "m00002", "end": "m00004", "summary": "s"}],
                tool_call_id="k",
            )
        messages.append({"role": "user", "content": "also check the tests"})
        with pytest.raises(ContextError, match="the last user message"):
            c.compress(
                messages,
                [{"start": "m00005", "end": "m00007", "summary": "s"}],
                tool_call_id="k",
            )
        assert not c.blocks

    def test_rejects_a_summary_that_does_not_shrink(self):
        messages = _transcript(turns=2, size=20)
        c = ContextCompressor(100_000)
        with pytest.raises(ContextError, match="nothing would be gained"):
            c.compress(
                messages,
                [{"start": "m00003", "end": "m00004", "summary": "x" * 500}],
                tool_call_id="k",
            )

    def test_rejects_an_empty_summary(self):
        messages = _transcript(turns=2)
        c = ContextCompressor(100_000)
        with pytest.raises(ContextError, match="empty summary"):
            c.compress(
                messages,
                [{"start": "m00003", "end": "m00004", "summary": "  "}],
                tool_call_id="k",
            )

    def test_unknown_ref_names_the_end_of_the_transcript(self):
        messages = _transcript(turns=1)
        c = ContextCompressor(100_000)
        with pytest.raises(
            ContextError, match="m00099 does not exist; the transcript ends at m00004"
        ):
            c.compress(
                messages,
                [{"start": "m00003", "end": "m00099", "summary": "s"}],
                tool_call_id="k",
            )

    def test_all_ranges_or_none(self):
        messages = _transcript(turns=4)
        c = ContextCompressor(100_000)
        with pytest.raises(ContextError):
            c.compress(
                messages,
                [
                    {"start": "m00003", "end": "m00004", "summary": "fine"},
                    {"start": "m00007", "end": "m00002", "summary": "backwards"},
                ],
                tool_call_id="k",
            )
        assert not c.blocks

    def test_overlapping_ranges_in_one_call_are_rejected(self):
        messages = _transcript(turns=4)
        c = ContextCompressor(100_000)
        with pytest.raises(ContextError, match="ranges overlap"):
            c.compress(
                messages,
                [
                    {"start": "m00003", "end": "m00006", "summary": "a"},
                    {"start": "m00005", "end": "m00008", "summary": "b"},
                ],
                tool_call_id="k",
            )

    def test_ref_inside_a_block_points_at_the_block(self):
        messages = _transcript(turns=4)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        _compress(
            c,
            messages,
            "k1",
            [{"start": "m00003", "end": "m00006", "summary": "first two files"}],
        )
        with pytest.raises(
            ContextError,
            match="m00004 is inside b1 \\(tier 1, m00003–m00006\\); use b1",
        ):
            c.compress(
                messages,
                [{"start": "m00004", "end": "m00008", "summary": "s"}],
                tool_call_id="k2",
            )

    def test_cutting_into_a_block_is_rejected(self):
        messages = _transcript(turns=4)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        _compress(
            c,
            messages,
            "k1",
            [{"start": "m00003", "end": "m00006", "summary": "first two files"}],
        )
        # a range that swallows b1's anchor but not its content would lose the only record of m00003–m00006
        anchor = ref(c.blocks["b1"].anchor)
        with pytest.raises(
            ContextError,
            match=f"would hide {anchor}, the anchor of b1 .*start the range at b1",
        ):
            c.compress(
                messages,
                [{"start": "m00007", "end": anchor, "summary": "s"}],
                tool_call_id="k2",
            )
        assert len(c.blocks) == 1

    def test_taking_the_content_without_the_anchor_is_rejected(self):
        messages = _transcript(turns=4)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        _compress(
            c,
            messages,
            "k1",
            [{"start": "m00005", "end": "m00006", "summary": "file 1"}],
        )
        anchor = ref(c.blocks["b1"].anchor)
        with pytest.raises(
            ContextError,
            match=f"contains b1 .* but not its anchor {anchor}; end the range at b1",
        ):
            c.compress(
                messages,
                [{"start": "m00003", "end": "m00008", "summary": "s"}],
                tool_call_id="k2",
            )

    def test_the_gap_between_a_block_and_its_anchor_is_live(self):
        messages = _transcript(turns=4)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        _compress(
            c,
            messages,
            "k1",
            [{"start": "m00003", "end": "m00004", "summary": "file 0"}],
        )
        # m00005–m00010 happened after file 0 was read but before it was compressed: plain live messages
        result = _compress(
            c,
            messages,
            "k2",
            [{"start": "m00005", "end": "m00010", "summary": "files 1-3"}],
        )
        assert "→ b2 (tier 1" in result and "folds" not in result
        assert c.blocks["b1"].active and c.blocks["b2"].active


class TestTiers:
    def test_folding_blocks_makes_a_higher_tier(self):
        messages = _transcript(turns=6)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        _compress(
            c,
            messages,
            "k1",
            [
                {
                    "start": "m00003",
                    "end": "m00006",
                    "summary": "files 0-1: nothing relevant",
                }
            ],
        )
        _compress(
            c,
            messages,
            "k2",
            [
                {
                    "start": "m00007",
                    "end": "m00010",
                    "summary": "files 2-3: nothing relevant",
                }
            ],
        )
        result = _compress(
            c,
            messages,
            "k3",
            [{"start": "b1", "end": "b2", "summary": "files 0-3: nothing"}],
        )

        assert "→ b3 (tier 2" in result and "folds b1, b2" in result
        assert (
            not c.blocks["b1"].active
            and not c.blocks["b2"].active
            and c.blocks["b3"].active
        )
        view = c.view(messages)
        refs = _tags(view)
        # both child anchors are gone from the wire, the tier-2 anchor remains
        assert ref(c.blocks["b1"].anchor) not in refs
        assert ref(c.blocks["b2"].anchor) not in refs
        assert ref(c.blocks["b3"].anchor) in refs
        # files 4-5 were live between b2 and the fold; a fold spans everything from b1's start to b2's anchor
        assert "m00012" not in refs and "m00014" not in refs
        assert refs == ["", "m00002", "", ref(c.blocks["b3"].anchor)]

    def test_a_block_created_this_turn_cannot_bound_a_range_yet(self):
        messages = _transcript(turns=4)
        c = ContextCompressor(100_000)
        c.compress(
            messages,
            [{"start": "m00003", "end": "m00004", "summary": "f0"}],
            tool_call_id="k1",
        )
        with pytest.raises(ContextError, match="b1 was created this turn"):
            c.compress(
                messages,
                [{"start": "b1", "end": "m00006", "summary": "s"}],
                tool_call_id="k1",
            )


class TestDecompressSearchStatus:
    def test_decompress_returns_the_originals(self):
        messages = _transcript(turns=3)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        _compress(
            c,
            messages,
            "k1",
            [{"start": "m00003", "end": "m00006", "summary": "f0, f1"}],
        )

        text = c.decompress(messages, "b1")
        assert text.startswith("b1 (tier 1, m00003–m00006)")
        assert (
            "--- m00003 assistant → Read ---" in text
            and 'Read({"path": "f0.py"})' in text
        )
        assert "--- m00004 tool Read ---\nfile 0: xxx" in text
        assert c.blocks["b1"].active  # still compressed

    def test_decompress_is_bounded(self):
        messages = _transcript(turns=3)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        _compress(
            c,
            messages,
            "k1",
            [{"start": "m00003", "end": "m00006", "summary": "f0, f1"}],
        )
        text = c.decompress(messages, "b1", max_chars=300)
        assert len(text) < 400 and "more chars; raise max_chars" in text

    def test_decompress_tier2_is_one_tier_up(self):
        messages = _transcript(turns=5)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        _compress(
            c,
            messages,
            "k1",
            [{"start": "m00003", "end": "m00004", "summary": "f0: nothing"}],
        )
        _compress(
            c,
            messages,
            "k2",
            [{"start": "m00005", "end": "m00006", "summary": "f1: nothing"}],
        )
        _compress(
            c,
            messages,
            "k3",
            [{"start": "b1", "end": "b2", "summary": "f0-f1: nothing"}],
        )

        text = c.decompress(messages, "b3")
        assert "--- b1 (tier 1, m00003–m00004) summary ---\nf0: nothing" in text
        assert "--- b2 (tier 1, m00005–m00006) summary ---\nf1: nothing" in text
        assert (
            "--- m00008 tool Read ---\nfile 2: xxx" in text
        )  # live between the children: shown in full
        assert "file 0: xxx" not in text  # originals are two tiers down
        assert (
            "Compressed 1 range" not in text
        )  # the children's anchor pairs add nothing

    def test_unknown_block(self):
        c = ContextCompressor(100_000)
        with pytest.raises(ContextError, match="no block 'b9'; blocks: none"):
            c.decompress([], "b9")

    def test_search_finds_hidden_content(self):
        messages = _transcript(turns=3)
        messages[5]["content"] = (
            "def parse(): raise ValueError('bad token at line 12')"  # m00006, file 1
        )
        c = ContextCompressor(100_000)
        c.prepare(messages)
        _compress(
            c,
            messages,
            "k1",
            [{"start": "m00003", "end": "m00006", "summary": "parser read"}],
        )

        out = c.search(messages, "bad token")
        assert out.startswith("m00006 (tool Read, hidden in b1")
        assert "bad token at line 12" in out
        assert c.search(messages, "zebra") == "No matches for 'zebra'."

    def test_status_reports_usage_blocks_and_ranges(self):
        messages = _transcript(turns=4)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        _compress(
            c, messages, "k1", [{"start": "m00003", "end": "m00004", "summary": "f0"}]
        )

        out = c.status(messages)
        assert out.startswith("Context: ") and "/ 100,000 tokens" in out
        assert "Blocks: b1 (tier 1, m00003–m00004)" in out
        assert "Largest compressible ranges: m00005–m00010" in out


class TestNudgeAndEviction:
    def test_no_nudge_while_there_is_room(self):
        messages = _transcript(turns=4)
        view = ContextCompressor(1_000_000).prepare(messages)
        assert "[context]" not in view[-1]["content"]

    def test_nudge_names_the_largest_ranges(self):
        messages = _transcript(turns=6, size=3000)  # ~6K tokens of results
        c = ContextCompressor(8_000)
        view = c.prepare(messages)
        note = view[-1]["content"].split("[context] ")[-1]
        assert "of the 8,000-token limit used" in note
        assert "Largest compressible ranges: m00003–m00012" in note
        assert "Compress consumed ranges before continuing" in note

    def test_over_the_limit_evicts_old_results_visibly(self):
        messages = _transcript(turns=6, size=3000)
        c = ContextCompressor(4_000)
        view = c.prepare(messages)

        stubs = [
            m
            for m in view
            if "[evicted to stay under the context limit: Read result"
            in str(m.get("content"))
        ]
        assert stubs and stubs[0]["content"].endswith("m00004</acp>")  # oldest first
        assert (
            "file 5: xxx" in view[-1]["content"]
        )  # the newest result is never evicted
        assert "tool result(s) were evicted" in view[-1]["content"]
        assert messages[3]["content"].startswith("file 0: xxx")  # transcript intact
        assert estimate_messages_tokens(view) < estimate_messages_tokens(messages)

    def test_eviction_note_is_shown_once(self):
        messages = _transcript(turns=6, size=3000)
        c = ContextCompressor(4_000)
        c.prepare(messages)
        _turn(messages, "c9", "Read", "file 9: " + "y" * 100)
        view = c.prepare(messages)
        assert "were evicted" not in view[-1]["content"]


def _text(content="Done", tokens=100):
    return LLMResponse(
        content=content,
        model="mock-model",
        provider="MockProvider",
        prompt_tokens=60,
        completion_tokens=40,
        total_tokens=tokens,
        latency_ms=5,
        finish_reason="stop",
    )


def _calls(tool_calls, tokens=100):
    return LLMResponse(
        content=None,
        model="mock-model",
        provider="MockProvider",
        prompt_tokens=60,
        completion_tokens=40,
        total_tokens=tokens,
        latency_ms=5,
        finish_reason="tool_calls",
        tool_calls=tool_calls,
    )


class TestServiceWiring:
    def test_unknown_policy_is_rejected_up_front(self):
        with pytest.raises(
            ValueError,
            match="context_policy must be one of truncate, compress, not 'evict'",
        ):
            LLMService(MockProvider([]), context_policy="evict")

    def test_truncate_is_the_default_and_sends_the_transcript_itself(self):
        provider = MockProvider([_text()])
        service = LLMService(provider)
        messages = [{"role": "user", "content": "hi"}]
        service.run(messages)

        assert service.context_policy == "truncate"
        assert provider.calls[0]["messages"] is messages  # no view layer, no tags
        assert provider.calls[0]["kwargs"].get("tools") is None

    def test_compress_offers_the_context_tools(self):
        provider = MockProvider([_text()])
        service = LLMService(provider, context_policy="compress")
        service.run(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "Read"}}],
        )

        names = [t["function"]["name"] for t in provider.calls[0]["kwargs"]["tools"]]
        assert names == [
            "Read",
            "compress",
            "decompress",
            "search_context",
            "context_status",
        ]
        assert provider.calls[0]["messages"][0]["content"].endswith("m00001</acp>")

    def test_compress_call_runs_locally_and_hides_the_range(self):
        big = "x" * 3000
        provider = MockProvider(
            [
                _calls([{"id": "c1", "name": "Read", "arguments": '{"path": "a"}'}]),
                _calls([{"id": "c2", "name": "Read", "arguments": '{"path": "b"}'}]),
                _calls(
                    [
                        {
                            "id": "k1",
                            "name": "compress",
                            "arguments": json.dumps(
                                {
                                    "ranges": [
                                        {
                                            "start": "m00002",
                                            "end": "m00005",
                                            "summary": "a and b: both fine",
                                        }
                                    ]
                                }
                            ),
                        }
                    ]
                ),
                _text("Done"),
            ]
        )
        service = LLMService(provider, context_policy="compress")
        ctx = CallContext(execution_id="ctx-1", agent_name="coder")
        result = service.run(
            [{"role": "user", "content": "check a and b"}],
            tools=[],
            execute_tool=lambda name, args: big,
            context=ctx,
        )

        assert result.error is None and result.output == "Done"
        last_wire = provider.calls[-1]["messages"]
        assert "x" * 3000 not in json.dumps(last_wire)  # the reads are hidden
        assert "a and b: both fine" in json.dumps(
            last_wire
        )  # the summary is the anchor
        assert last_wire[-1]["content"].startswith(
            "Compressed 1 range(s): m00002–m00005 → b1"
        )
        # the compress call went through the same recording path as any tool
        events = [
            e
            for e in get_events(execution_id="ctx-1")
            if e["data"].get("tool_name") == "compress"
        ]
        assert [e["type"] for e in events] == [
            str(EventType.TOOL_CALL_STARTED),
            str(EventType.TOOL_CALL_COMPLETED),
        ]
        assert (
            events[0]["data"]["input_params"]["ranges"][0]["summary"]
            == "a and b: both fine"
        )
        assert events[0]["data"]["executed_by"] == "temper"

    def test_context_tools_need_no_executor(self):
        provider = MockProvider(
            [
                _calls([{"id": "k1", "name": "context_status", "arguments": "{}"}]),
                _text("Done"),
            ]
        )
        service = LLMService(provider, context_policy="compress")
        result = service.run([{"role": "user", "content": "hi"}])

        assert result.error is None
        assert provider.calls[-1]["messages"][-1]["content"].startswith("Context: ")

    def test_a_bad_range_comes_back_as_a_tool_error_and_the_run_goes_on(self):
        provider = MockProvider(
            [
                _calls(
                    [
                        {
                            "id": "k1",
                            "name": "compress",
                            "arguments": json.dumps(
                                {
                                    "ranges": [
                                        {
                                            "start": "m00001",
                                            "end": "m00001",
                                            "summary": "the task",
                                        }
                                    ]
                                }
                            ),
                        }
                    ]
                ),
                _text("Done"),
            ]
        )
        service = LLMService(provider, context_policy="compress")
        result = service.run([{"role": "user", "content": "hi"}])

        assert result.error is None
        assert provider.calls[-1]["messages"][-1]["content"].startswith(
            "Error: m00001 is protected (the task message)"
        )
        assert (
            result.tool_calls[0]["success"] is True
        )  # the tool ran; the model's input was wrong
