"""Tests for the ``compress`` context policy — model-driven compression.

The transcript is built the way the service builds it: system, task, then
assistant tool-call / tool-result pairs. ``_reply`` appends what the service
would append after a compress call, so tests can walk several turns.
"""

import json

import pytest

from temper_ai.llm.context import (
    GUIDANCE,
    SUMMARY_STUB_CHARS,
    ContextCompressor,
    ContextError,
    _message_tokens,
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


def _reply(
    messages: list[dict],
    compressor: ContextCompressor,
    call_id: str,
    ranges: list[dict],
    result: str,
) -> None:
    """What the service appends after a compress call, then the next prepare()."""
    _turn(messages, call_id, "compress", result, {"ranges": ranges})
    compressor.prepare(messages)


def _compress(
    compressor: ContextCompressor,
    messages: list[dict],
    call_id: str,
    ranges: list[dict],
) -> str:
    result = compressor.compress(messages, ranges, tool_call_id=call_id)
    _reply(messages, compressor, call_id, ranges, result)
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
                    "summary": "read f0, f1: " + "n" * 400,
                }
            ],
        )
        before = json.dumps(messages)
        c.prepare(messages)
        c.view(messages)

        assert json.dumps(messages) == before  # the stubbed compress call is a copy
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
    def test_hides_the_range_and_renders_the_summary_in_its_place(self):
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
                    "topic": "first two files",
                    "summary": "f0 and f1 are irrelevant",
                },
            ],
        )

        assert result.startswith("Compressed 1 range(s): m00003–m00006 → b1 (tier 1")
        view = c.view(messages)
        # the summary stands where m00003–m00006 stood; the compress call (m00011) follows in order
        assert _tags(view) == [
            "",
            "m00002",
            "b1",
            "",
            "m00008",
            "",
            "m00010",
            "",
            "m00012",
        ]
        rendered = view[2]
        assert (
            rendered["role"] == "user"
        )  # never system: providers fold that into the prompt
        assert rendered["content"].startswith(
            "[Compressed b1 — first two files] m00003–m00006, tier 1, ~"
        )
        assert "\nf0 and f1 are irrelevant\n" in rendered["content"]
        assert estimate_messages_tokens(view) < estimate_messages_tokens(messages)

    def test_the_compress_call_is_stubbed_so_the_summary_is_sent_once(self):
        messages = _transcript(turns=2)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        summary = "the parser: " + "s" * 600
        _compress(
            c,
            messages,
            "k1",
            [{"start": "m00003", "end": "m00006", "summary": summary}],
        )

        view = c.view(messages)
        call = view[-2]["tool_calls"][0]["function"]["arguments"]
        stub = json.loads(call)["ranges"][0]["summary"]
        assert len(stub) == SUMMARY_STUB_CHARS and stub.endswith("…")
        assert json.dumps(view).count("s" * 600) == 1  # rendered once, in place
        assert (
            summary in messages[-2]["tool_calls"][0]["function"]["arguments"]
        )  # log intact

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

    def test_second_compress_takes_what_the_first_left_out(self):
        """The failure the anchor model had: the messages right after a block — what the
        model left live the first time — are the oldest content by the next turn."""
        messages = _transcript(turns=4)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        _compress(
            c,
            messages,
            "k1",
            [{"start": "m00003", "end": "m00004", "summary": "file 0"}],
        )
        result = _compress(
            c,
            messages,
            "k2",
            [{"start": "m00005", "end": "m00010", "summary": "files 1-3"}],
        )

        assert "→ b2 (tier 1" in result and "folds" not in result
        assert c.blocks["b1"].active and c.blocks["b2"].active
        # both summaries in order, then the two compress calls (m00011, m00013) and their results
        assert _tags(c.view(messages)) == [
            "",
            "m00002",
            "b1",
            "b2",
            "",
            "m00012",
            "",
            "m00014",
        ]

    def test_a_range_may_swallow_an_older_compress_call(self):
        messages = _transcript(turns=4)
        c = ContextCompressor(100_000)
        c.prepare(messages)
        _compress(
            c,
            messages,
            "k1",
            [{"start": "m00003", "end": "m00004", "summary": "file 0"}],
        )
        # m00011–m00012 is the k1 call and its result; b1's summary does not live there
        _compress(
            c,
            messages,
            "k2",
            [
                {
                    "start": "m00005",
                    "end": "m00012",
                    "summary": "files 1-3, then compressed",
                }
            ],
        )

        view = c.view(messages)
        assert c.blocks["b1"].active
        assert _tags(view) == ["", "m00002", "b1", "b2", "", "m00014"]
        assert "file 0" in view[2]["content"]
        assert '"k1"' not in json.dumps(view)


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
        # b3 stands where b1 began; files 4-5 (m00011–m00014) stay live in order; the
        # folded blocks' compress calls (m00015–m00018) leave the view, b3's own (m00019) stays
        assert _tags(view) == [
            "",
            "m00002",
            "b3",
            "",
            "m00012",
            "",
            "m00014",
            "",
            "m00020",
        ]
        wire = json.dumps(view)
        assert '"k1"' not in wire and '"k2"' not in wire and '"k3"' in wire
        assert "files 0-1: nothing relevant" not in wire  # two tiers down now

    def test_a_new_block_can_bound_a_range_at_once(self):
        messages = _transcript(turns=4)
        c = ContextCompressor(100_000)
        c.compress(
            messages,
            [{"start": "m00003", "end": "m00004", "summary": "f0"}],
            tool_call_id="k1",
        )
        result = c.compress(
            messages,
            [{"start": "b1", "end": "m00006", "summary": "f0-f1"}],
            tool_call_id="k2",
        )
        assert "→ b2 (tier 2" in result and "folds b1" in result


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
            [{"start": "m00007", "end": "m00008", "summary": "f2: nothing"}],
        )
        # spans both children, the live turns between and after them, and both their compress calls
        _compress(
            c,
            messages,
            "k3",
            [{"start": "b1", "end": "m00016", "summary": "f0-f4: nothing"}],
        )

        text = c.decompress(messages, "b3")
        assert "--- b1 (tier 1, m00003–m00004) summary ---\nf0: nothing" in text
        assert (
            "--- m00006 tool Read ---\nfile 1: xxx" in text
        )  # live between the children
        assert "--- b2 (tier 1, m00007–m00008) summary ---\nf2: nothing" in text
        assert "--- m00012 tool Read ---\nfile 4: xxx" in text
        assert "file 0: xxx" not in text  # originals are two tiers down
        assert (
            "compress(" not in text and "Compressed 1 range" not in text
        )  # children's calls add nothing

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

    def test_nudge_is_a_message_of_its_own_after_the_tool_result(self):
        """Not appended inside the tool result: models discount instructions found in
        tool output, and gpt-5.6-luna ignored the tail form at 97% usage, every turn."""
        messages = _transcript(turns=6, size=3000)  # ~6K tokens of results
        c = ContextCompressor(8_000)
        view = c.prepare(messages)

        assert view[-2]["role"] == "tool" and "[context]" not in view[-2]["content"]
        assert view[-1]["role"] == "user" and view[-1]["content"].startswith(
            "[context] "
        )
        assert "<acp" not in view[-1]["content"]  # not a transcript message, no ref
        assert messages[-1]["role"] == "tool"  # transcript untouched
        note = view[-1]["content"]
        assert "of the 8,000-token limit used" in note
        assert "Largest compressible ranges: m00003–m00012" in note
        assert "Compress consumed ranges before continuing" in note

    def test_no_usage_nudge_while_wrapping_up(self):
        """Once the iteration budget has told the model to answer, asking it to
        compress first would spend a turn the budget does not have."""
        messages = _transcript(turns=6, size=3000)
        view = ContextCompressor(8_000).prepare(messages, wrapping_up=True)
        assert view[-1]["role"] == "tool"  # nothing appended

    def test_prepare_describes_what_it_sent(self):
        """The event log gets the harness's side: the raw transcript in
        llm.call.started has no nudge in it and no ref tags."""
        messages = _transcript(turns=6, size=3000)
        c = ContextCompressor(1_000_000)
        assert c.sent is None
        c.prepare(messages)
        assert c.sent is not None
        assert c.sent.nudged is False and c.sent.hid == () and c.sent.blocks == 0
        assert c.sent.hidden == 0 and c.sent.wrapping_up is False
        assert c.sent.tokens == pytest.approx(estimate_messages_tokens(c.view(messages)))

        c = ContextCompressor(8_000)
        c.prepare(messages)
        assert c.sent is not None and c.sent.nudged is True
        c.prepare(messages, wrapping_up=True)
        assert c.sent is not None
        assert c.sent.nudged is False and c.sent.wrapping_up is True

    def test_sent_names_what_the_harness_hid_on_that_call_only(self):
        messages = _transcript(turns=6, size=3000)  # ~6K of results
        c = ContextCompressor(4_000)
        c.prepare(messages)
        assert c.sent is not None
        # two steps of the same block, as the room note says it to the model
        assert c.sent.hid == ("m00003–m00008 behind b1", "m00009–m00010 behind b1")
        assert c.sent.blocks == 1 and c.sent.hidden == 8
        assert c.sent.tokens <= 4_000

        c.prepare(messages)  # nothing new to hide: the block is in place
        assert c.sent is not None
        assert c.sent.hid == () and c.sent.blocks == 1

    def test_what_the_harness_hid_is_still_reported_while_wrapping_up(self):
        messages = _transcript(turns=6, size=3000)  # ~6K of results
        view = ContextCompressor(4_000).prepare(messages, wrapping_up=True)
        note = view[-1]["content"]
        assert note.startswith("[context] The harness hid ")
        assert "Compress consumed ranges before continuing" not in note

    def test_over_the_limit_the_harness_hides_the_oldest_turns_whole(self):
        messages = _transcript(turns=6, size=3000)  # ~6K of results
        c = ContextCompressor(4_000)
        view = c.prepare(messages)

        (b1,) = c.blocks.values()
        assert b1.by_harness and b1.active and b1.tier == 1
        assert b1.start == 2  # right after the task message
        assert messages[b1.end]["role"] == "tool"  # whole turns: never splits a pair
        assert b1.end < len(messages) - 2  # the current turn is never hidden
        rendered = view[2]["content"]
        assert rendered.startswith("[Compressed b1 — hidden by the harness]")
        assert "the model never summarized it" in rendered
        assert f"Read ×{(b1.end - 1) // 2}" in rendered  # a listing, not content
        assert "decompress b1 to read it" in rendered
        assert "file 5: xxx" in view[-2]["content"]  # the newest result stays
        assert view[-1]["role"] == "user"
        assert "The harness hid m00003–" in view[-1]["content"]
        assert "nothing was summarized" in view[-1]["content"]
        assert messages[3]["content"].startswith("file 0: xxx")  # transcript intact
        assert estimate_messages_tokens(view) <= 4_000
        assert "file 0: xxx" in c.decompress(messages, "b1")  # still reachable

    def test_the_harness_note_is_shown_once(self):
        messages = _transcript(turns=6, size=3000)
        c = ContextCompressor(4_000)
        c.prepare(messages)
        _turn(messages, "c9", "Read", "file 9: " + "y" * 100)
        view = c.prepare(messages)
        assert "The harness hid" not in view[-1]["content"]

    def test_the_harness_block_grows_instead_of_multiplying(self):
        """Per-message eviction left a ~48-token stub per result, forever; 400
        turns of it was ~1.6K tokens of stubs in a 10K window."""
        messages = _transcript(turns=6, size=3000)
        c = ContextCompressor(4_000)
        c.prepare(messages)
        end_before = c.blocks["b1"].end
        for n in range(6):
            _turn(messages, f"n{n}", "Read", f"file {10 + n}: " + "z" * 3000)
            view = c.prepare(messages)
            assert estimate_messages_tokens(view) <= 4_000

        assert [b.id for b in c.blocks.values()] == ["b1"]
        assert c.blocks["b1"].end > end_before
        renders = [m for m in view if str(m.get("content")).startswith("[Compressed")]
        assert len(renders) == 1

    def test_the_harness_never_puts_the_models_blocks_under_its_own(self):
        """A summary the model wrote is the point; it stays in view, and the
        harness block resumes after it."""
        messages = _transcript(turns=4, size=3000)
        c = ContextCompressor(1_000_000)
        c.prepare(messages)
        _compress(
            c,
            messages,
            "k1",
            [{"start": "m00003", "end": "m00006", "summary": "files 0-1: nothing"}],
        )
        c.max_context_tokens = 4_000
        for n in range(8):
            _turn(messages, f"n{n}", "Read", f"file {10 + n}: " + "z" * 3000)
            c.prepare(messages)

        model = c.blocks["b1"]
        harness = [b for b in c.blocks.values() if b.by_harness]
        assert model.active and not model.by_harness
        assert len(harness) == 1 and harness[0].start == model.end + 1
        assert "files 0-1: nothing" in c.view(messages)[2]["content"]

    def test_a_summary_folding_a_harness_block_says_so(self):
        """Live run (with eviction): the model compressed over content it had
        never seen, then answered with docstrings it made up for it."""
        messages = _transcript(turns=6, size=3000)
        c = ContextCompressor(4_000)
        c.prepare(messages)
        h = c.blocks["b1"]
        assert h.by_harness

        result = c.compress(
            messages,
            [
                {
                    "start": "b1",
                    "end": ref(h.end + 2),
                    "summary": "files 0-4: nothing relevant",
                }
            ],
            tool_call_id="k1",
        )
        b2 = c.blocks["b2"]
        assert b2.children == ["b1"] and b2.unread == [h.label()]
        assert (
            f"note: folds {h.label()}, which the harness had hidden unsummarized — "
            "this summary covers that content from memory only" in result
        )
        rendered = ContextCompressor.render(b2)["content"]
        assert (
            f"(folds {h.label()}, which the harness had hidden unsummarized" in rendered
        )

        # and the warning outlives the next fold
        _reply(messages, c, "k1", [], result)
        _turn(messages, "c9", "Read", "file 9: " + "y" * 100)
        c.prepare(messages)
        c.compress(
            messages,
            [{"start": "b2", "end": "m00016", "summary": "everything so far: nothing"}],
            tool_call_id="k2",
        )
        assert c.blocks["b3"].unread == [h.label()]

    def test_compress_counts_what_the_view_shows_not_the_transcript(self):
        """A compress call's summary is stubbed in the view and a folded pair is
        dropped; a range over them reclaims what the view held, not what the
        transcript holds. (Under eviction the same slip read 'Context ≈ 20,333
        → 0' for two stubs.)"""
        messages = _transcript(turns=4, size=3000)
        c = ContextCompressor(1_000_000)
        c.prepare(messages)
        long = "a summary " * 200  # 2,000 chars in the transcript, 200 in the view
        _compress(
            c, messages, "k1", [{"start": "m00003", "end": "m00004", "summary": long}]
        )
        _compress(
            c,
            messages,
            "k2",
            [{"start": "m00005", "end": "m00006", "summary": "file 1: nothing"}],
        )
        _turn(messages, "c9", "Read", "file 9: " + "y" * 100)
        view = c.prepare(messages)
        # the view of b1..m00014: b1, b2, two live turns, the k1 call (stubbed)
        # and receipt, the k2 call and receipt; then the c9 turn and the nudge
        assert [tc["id"] for tc in view[12]["tool_calls"]] == ["c9"]
        shown = estimate_messages_tokens(view[2:12])
        held = sum(_message_tokens(messages[i]) for i in range(2, 14))
        # four 1K bodies became two renders (~700, ~40), and the 2K-char summary
        # is counted once (b1's render), not again inside the stubbed k1 call
        assert 1_500 < held - shown < 2_000, (held, shown)

        result = c.compress(
            messages,
            [{"start": "b1", "end": "m00014", "summary": "files 0-1 and 9: nothing"}],
            tool_call_id="k3",
        )
        b3 = c.blocks["b3"]
        assert b3.tokens_before == shown
        before, after = (
            int(x.replace(",", ""))
            for x in result.split("Context ≈ ")[1].split(" of ")[0].split(" → ")
        )
        assert after == estimate_messages_tokens(c.view(messages))  # measured
        assert 0 < after < before


# Any tool at all: the context tools ride along with the agent's own.
_READ_TOOL = [{"type": "function", "function": {"name": "Read"}}]


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

    def test_compress_is_the_default(self):
        provider = MockProvider([_text()])
        service = LLMService(provider)
        service.run(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "Read"}}],
        )

        assert service.context_policy == "compress"
        names = [t["function"]["name"] for t in provider.calls[0]["kwargs"]["tools"]]
        assert "compress" in names
        assert provider.calls[0]["messages"][0]["content"].endswith("m00001</acp>")

    def test_truncate_sends_the_transcript_itself(self):
        provider = MockProvider([_text()])
        service = LLMService(provider, context_policy="truncate")
        messages = [{"role": "user", "content": "hi"}]
        tools = [{"type": "function", "function": {"name": "Read"}}]
        service.run(messages, tools=tools)

        assert provider.calls[0]["messages"] is messages  # no view layer, no tags
        assert provider.calls[0]["kwargs"]["tools"] is tools  # nothing added

    @pytest.mark.parametrize("tools", [None, []])
    def test_a_run_without_tools_gets_no_context_tools(self, tools):
        """One provider call, nothing to compact — and a prompt that never
        carried tools must not start carrying four."""
        provider = MockProvider([_text()])
        service = LLMService(provider)  # compress by default
        messages = [{"role": "user", "content": "hi"}]
        service.run(messages, tools=tools)

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
            tools=_READ_TOOL,
            execute_tool=lambda name, args: big,
            context=ctx,
        )

        assert result.error is None and result.output == "Done"
        last_wire = provider.calls[-1]["messages"]
        assert "x" * 3000 not in json.dumps(last_wire)  # the reads are hidden
        assert last_wire[1]["role"] == "user" and last_wire[1]["content"].startswith(
            "[Compressed b1] m00002–m00005, tier 1"
        )
        assert (
            "a and b: both fine" in last_wire[1]["content"]
        )  # rendered where the reads were
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
        result = service.run([{"role": "user", "content": "hi"}], tools=_READ_TOOL)

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
        result = service.run([{"role": "user", "content": "hi"}], tools=_READ_TOOL)

        assert result.error is None
        assert provider.calls[-1]["messages"][-1]["content"].startswith(
            "Error: m00001 is protected (the task message)"
        )
        assert (
            result.tool_calls[0]["success"] is True
        )  # the tool ran; the model's input was wrong
