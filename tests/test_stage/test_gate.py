"""Tests for stage/gate.py and the gate path through the executor.

A ``gate: true`` node pauses; the human sees the upstream outputs and the
questions they asked, and whatever they answer reaches the gated node as
its ``gate`` input.
"""

import threading
from pathlib import Path

import yaml

from temper_ai.shared.types import NodeResult, Status
from temper_ai.stage import executor as executor_mod
from temper_ai.stage.executor import _wait_for_gate, execute_graph
from temper_ai.stage.gate import (
    EMPTY_RESPONSE,
    GateSignal,
    build_gate_context,
    normalise_question,
    normalise_response,
    questions_from,
    render_response_text,
    summarise_output,
)

from .test_executor import _make_agent_node, _make_context

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestQuestionsFrom:
    def test_bare_strings_become_free_text_questions(self):
        qs = questions_from({"questions_for_owner": ["Ship it?", " Which host? "]}, None)
        assert qs == [
            {"id": "q1", "question": "Ship it?"},
            {"id": "q2", "question": "Which host?"},
        ]

    def test_dict_questions_keep_the_ask_user_question_shape(self):
        raw = {
            "questions": [{
                "id": "host",
                "question": "Which host?",
                "header": "Deploy",
                "detail": "Prod is *busy*",
                "options": ["spark", {"label": "roamee", "description": "the laptop", "preview": "```\nssh roamee\n```"}],
                "multi_select": True,
            }],
        }
        assert questions_from(raw, None) == [{
            "id": "host",
            "question": "Which host?",
            "header": "Deploy",
            "detail": "Prod is *busy*",
            "options": [
                {"label": "spark"},
                {"label": "roamee", "description": "the laptop", "preview": "```\nssh roamee\n```"},
            ],
            "multiSelect": True,
        }]

    def test_output_text_that_is_a_json_object_is_read(self):
        text = '{"pitch": "...", "questions_for_owner": ["Keep TLS out of scope?"]}'
        assert questions_from(None, text) == [{"id": "q1", "question": "Keep TLS out of scope?"}]

    def test_structured_output_wins_over_text(self):
        qs = questions_from({"questions": ["from structured"]}, '{"questions": ["from text"]}')
        assert [q["question"] for q in qs] == ["from structured"]

    def test_text_is_still_read_when_the_structured_output_has_no_questions(self):
        # A script agent's structured output is whatever its extractor made of
        # the output. It handed back a nested object here; the questions are
        # in the document the script actually printed, so look there too.
        structured = {"label": "Per-run container", "description": "Same path as the worker."}
        text = '{"summary": "...", "questions": ["Where should a gate answer live?"]}'
        assert questions_from(structured, text) == [
            {"id": "q1", "question": "Where should a gate answer live?"}
        ]

    def test_nothing_asked(self):
        assert questions_from({"pitch": "no questions"}, "prose with a { brace") == []
        assert questions_from(None, None) == []
        assert questions_from({"questions": "not a list"}, None) == []
        assert questions_from({"questions": ["", 42, {"no": "question"}]}, None) == []

    def test_malformed_question_dict_is_dropped(self):
        assert normalise_question({"options": ["a"]}, 1) is None
        assert normalise_question(3.14, 1) is None


class TestBuildGateContext:
    def test_upstream_outputs_and_their_questions(self):
        outputs = {
            "draft": NodeResult(
                status=Status.COMPLETED,
                output="the pitch",
                structured_output={"questions_for_owner": ["Ship it?"]},
            ),
            "unrelated": NodeResult(status=Status.COMPLETED, output="not a dependency"),
        }
        ctx = build_gate_context(["draft", "missing"], outputs)
        assert ctx == {
            "upstream": [{"node": "draft", "output": "the pitch", "structured_output": {"questions_for_owner": ["Ship it?"]}}],
            "questions": [{"id": "q1", "question": "Ship it?", "node": "draft"}],
        }

    def test_no_dependencies(self):
        assert build_gate_context([], {}) == {"upstream": [], "questions": []}


class TestFieldNamesAnAgentPlausiblyWrites:
    """A field under an obvious-but-wrong name used to vanish in silence."""

    def test_key_and_context_are_taken_as_header_and_detail(self):
        q = normalise_question(
            {"question": "Ship it?", "key": "Release", "context": "Prod is busy."}, 1
        )
        assert q is not None
        assert q["header"] == "Release"
        assert q["detail"] == "Prod is busy."

    def test_the_real_names_win_over_the_aliases(self):
        q = normalise_question(
            {"question": "Ship it?", "header": "Release", "key": "ignored"}, 1
        )
        assert q is not None
        assert q["header"] == "Release"


class TestTheShippedExample:
    """`gate_smoke_ask` is what a user copies. Parse what it actually prints.

    It was committed asking its questions under field names the parser did
    not read, so every heading and every line of context was dropped — and
    nothing failed, because no test ever looked at the example itself.
    """

    def test_every_question_survives_the_parser_intact(self):
        config = yaml.safe_load(
            (REPO_ROOT / "configs" / "agents" / "gate_smoke_ask.yaml").read_text()
        )
        script = config["agent"]["script_template"]
        document = script[script.index("{") : script.rindex("}") + 1]

        questions = questions_from(None, document)

        assert [q["header"] for q in questions if "header" in q] == ["Storage", "Reach"]
        assert all(q["detail"] for q in questions if "detail" in q)
        # The heading and the context are the difference between a question
        # a human can answer and one they have to guess at.
        assert questions[0]["detail"] == "It has to survive a worker restart either way."
        assert questions[1]["multiSelect"] is True
        assert any("preview" in opt for opt in questions[0]["options"])
        assert questions[2] == {
            "id": "q3",
            "question": "Anything I should not touch while doing this?",
        }


class TestSummariseOutput:
    def test_a_json_document_of_questions_is_shown_as_its_prose(self):
        # Otherwise every question is on screen twice: once as raw JSON,
        # once as the form built from it.
        text = '{"summary": "Two ways to store answers.", "questions": ["Which one?"]}'
        asked = questions_from(None, text)
        assert summarise_output(text, asked) == "Two ways to store answers."

    def test_an_output_that_asked_nothing_is_shown_as_it_is(self):
        assert summarise_output("a plain plan", []) == "a plain plan"
        # ...including JSON, when the questions did not come out of it.
        assert summarise_output('{"key": "value"}', []) == '{"key": "value"}'

    def test_prose_free_document_shows_nothing_rather_than_json(self):
        text = '{"questions": ["Which one?"]}'
        assert summarise_output(text, questions_from(None, text)) == ""

    def test_the_whole_output_is_kept_alongside_the_prose(self):
        text = '{"summary": "Two ways.", "questions": ["Which one?"]}'
        outputs = {"plan": NodeResult(status=Status.COMPLETED, output=text)}
        entry = build_gate_context(["plan"], outputs)["upstream"][0]
        assert entry["output"] == "Two ways."
        assert entry["full_output"] == text

    def test_nothing_is_duplicated_when_the_output_is_shown_whole(self):
        outputs = {"plan": NodeResult(status=Status.COMPLETED, output="a plain plan")}
        entry = build_gate_context(["plan"], outputs)["upstream"][0]
        assert entry["output"] == "a plain plan"
        assert "full_output" not in entry


class TestNormaliseResponse:
    def test_empty_body_is_a_plain_approval(self):
        assert normalise_response(None) is None
        assert normalise_response({}) is None
        assert normalise_response({"response": "  ", "answers": [{"id": "q1", "selected": [], "custom": ""}]}) is None

    def test_answers_and_free_text_render_as_prose(self):
        body = {
            "response": "Go, but keep it small.",
            "answers": [
                {"id": "host", "question": "Which host?", "selected": ["spark"], "custom": ""},
                {"id": "q2", "question": "Anything else?", "selected": [], "custom": "no TLS work"},
                {"id": "q3", "question": "skipped", "selected": [], "custom": ""},
            ],
        }
        got = normalise_response(body)
        assert got["response"] == "Go, but keep it small."
        assert [a["id"] for a in got["answers"]] == ["host", "q2"]
        assert got["text"] == (
            "Q: Which host?\nA: spark\n\n"
            "Q: Anything else?\nA: no TLS work\n\n"
            "Go, but keep it small."
        )

    def test_selection_plus_custom_text(self):
        text = render_response_text(
            [{"id": "q1", "question": "Which?", "selected": ["a", "b"], "custom": "and c later"}], "",
        )
        assert text == "Q: Which?\nA: a, b — and c later"

    def test_answer_without_question_text_falls_back_to_its_id(self):
        got = normalise_response({"answers": [{"id": "host", "selected": ["spark"]}]})
        assert got["text"] == "Q: host\nA: spark"


class TestWaitForGate:
    def test_records_the_context_and_returns_the_in_process_response(self, monkeypatch):
        monkeypatch.setattr(executor_mod, "GATE_POLL_SECONDS", 0.05)
        registry: dict = {}
        context = _make_context(gate_registry=registry)
        context.event_recorder.event_data.return_value = None
        node = _make_agent_node("approve", depends_on=["draft"])
        outputs = {"draft": NodeResult(status=Status.COMPLETED, output="pitch", structured_output={"questions": ["Ship?"]})}

        def _approve_when_registered():
            while "run-1:approve" not in registry:
                pass
            registry["run-1:approve"].response = {"response": "yes", "answers": [], "text": "yes"}
            registry["run-1:approve"].set()
        threading.Thread(target=_approve_when_registered, daemon=True).start()

        got = _wait_for_gate(node, context, "parent", outputs)

        assert got == {"response": "yes", "answers": [], "text": "yes"}
        waiting = context.event_recorder.record.call_args.kwargs
        assert waiting["status"] == "waiting"
        assert waiting["data"]["gate"] is True
        assert waiting["data"]["gate_context"]["questions"] == [{"id": "q1", "question": "Ship?", "node": "draft"}]
        assert waiting["data"]["gate_context"]["upstream"][0]["output"] == "pitch"
        approved = context.event_recorder.update_event.call_args.kwargs
        assert approved["status"] == "approved"
        assert approved["data"]["gate_response"] == got
        assert "run-1:approve" not in registry

    def test_database_approval_carries_the_response(self, monkeypatch):
        """A worker in another process never sees the in-memory signal: the
        API flips the event to approved and writes the response into it."""
        monkeypatch.setattr(executor_mod, "GATE_POLL_SECONDS", 0.02)
        context = _make_context(gate_registry={})
        context.event_recorder.event_status.return_value = "approved"
        context.event_recorder.event_data.return_value = {
            "gate_status": "approved",
            "gate_response": {"response": "from the db", "answers": [], "text": "from the db"},
        }
        node = _make_agent_node("approve")

        got = _wait_for_gate(node, context, "parent", {})

        assert got["text"] == "from the db"

    def test_plain_approval_returns_none(self, monkeypatch):
        monkeypatch.setattr(executor_mod, "GATE_POLL_SECONDS", 0.02)
        context = _make_context(gate_registry={})
        context.event_recorder.event_status.return_value = "approved"
        context.event_recorder.event_data.return_value = {"gate_status": "approved"}
        node = _make_agent_node("approve")

        assert _wait_for_gate(node, context, "parent", {}) is None
        approved = context.event_recorder.update_event.call_args.kwargs
        assert "gate_response" not in approved["data"]

    def test_unreadable_response_still_releases_the_node(self, monkeypatch):
        monkeypatch.setattr(executor_mod, "GATE_POLL_SECONDS", 0.02)
        context = _make_context(gate_registry={})
        context.event_recorder.event_status.return_value = "approved"
        context.event_recorder.event_data.side_effect = RuntimeError("db went away")
        node = _make_agent_node("approve")

        assert _wait_for_gate(node, context, "parent", {}) is None


class TestGatedNodeInput:
    def test_the_gated_node_receives_the_response_as_gate(self, monkeypatch):
        monkeypatch.setattr(executor_mod, "GATE_POLL_SECONDS", 0.02)
        registry: dict = {}
        context = _make_context(gate_registry=registry)
        context.event_recorder.event_data.return_value = None
        draft = _make_agent_node("draft", output="the pitch")
        approve = _make_agent_node("approve", depends_on=["draft"])
        approve.config.gate = True

        def _answer():
            while "run-1:approve" not in registry:
                pass
            registry["run-1:approve"].response = {"response": "ship it", "answers": [], "text": "ship it"}
            registry["run-1:approve"].set()
        threading.Thread(target=_answer, daemon=True).start()

        result = execute_graph([draft, approve], {"task": "t"}, context)

        assert result.status == Status.COMPLETED
        given = approve.run.call_args.args[0]
        assert given["gate"] == {"response": "ship it", "answers": [], "text": "ship it"}
        assert given["other_agents"] == "[draft]:\nthe pitch"

    def test_a_plain_approval_gives_an_empty_gate(self, monkeypatch):
        monkeypatch.setattr(executor_mod, "GATE_POLL_SECONDS", 0.02)
        registry: dict = {}
        context = _make_context(gate_registry=registry)
        context.event_recorder.event_data.return_value = None
        approve = _make_agent_node("approve", input_map={"task": "workflow.task"})
        approve.config.gate = True

        def _release():
            while "run-1:approve" not in registry:
                pass
            registry["run-1:approve"].set()
        threading.Thread(target=_release, daemon=True).start()

        execute_graph([approve], {"task": "t"}, context)

        given = approve.run.call_args.args[0]
        assert given == {"task": "t", "gate": EMPTY_RESPONSE}
        assert given["gate"] is not EMPTY_RESPONSE  # a copy: nodes must not share the constant

    def test_an_ungated_node_has_no_gate_input(self):
        node = _make_agent_node("plain")
        execute_graph([node], {"task": "t"}, _make_context())
        assert "gate" not in node.run.call_args.args[0]

    def test_gate_signal_is_a_threading_event(self):
        """The registry is waited on with Event semantics; the response rides along."""
        signal = GateSignal()
        assert isinstance(signal, threading.Event)
        assert signal.response is None
