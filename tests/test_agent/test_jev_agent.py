"""The jev agent type: typed questions answered by TypeSafe AI's Jev model.

Jev is not an LLM. It is given some content and named questions of a declared type (noul, choice,
score) and returns every answer at once with its probabilities, so the answers are the node's
structured output as they arrive. These tests run the agent against a stand-in for the TypeSafe
API (httpx.MockTransport); nothing here reaches the network.
"""

from __future__ import annotations

import functools
import json
from unittest.mock import MagicMock

import httpx
import pytest

from temper_ai.agent import AGENT_TYPES, create_agent, jev_agent
from temper_ai.agent.jev_agent import USD_PER_INPUT_TOKEN, JevAgent, jev_config_errors
from temper_ai.observability import EventType
from temper_ai.shared.types import ExecutionContext, Status
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.conditions import evaluate_condition
from temper_ai.stage.loader import GraphLoader
from temper_ai.stage.models import NodeConfig

KEY = "ts-test-key-7f3a"

QUESTIONS = {
    "severity": {
        "type": "choice",
        "instructions": "How serious is this review finding?",
        "criteria": {"blocking": "Breaks behaviour or loses data", "minor": "Style, naming or a nit"},
    },
    "is_flaky": {"type": "noul", "instructions": "Is this about a flaky test?"},
}

ANSWERS = {
    "severity": {
        "type": "choice", "choice": "blocking", "confidence": 0.91,
        "probabilities": {"blocking": 0.93, "minor": 0.07},
    },
    "is_flaky": {"type": "noul", "noul": 0.04},
}

FINDING = "save() swallows the IntegrityError, so a duplicate order is silently dropped"


def _config(**overrides) -> dict:
    return {
        "name": "triage", "type": "jev", "model": "jev-1.13.0",
        "state_template": "{{ finding }}", "questions": QUESTIONS, **overrides,
    }


class _TypeSafe:
    """Stands in for api.typesafe.ai: plays back scripted responses and keeps every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


def _ok(answers=ANSWERS, model="jev-1.13.0", input_tokens=120, request_id="req-1"):
    return httpx.Response(
        200,
        json={"model": model, "answers": answers,
              "usage": {"input_tokens": input_tokens, "output_tokens": 12}},
        headers={"x-typesafe-request-id": request_id},
    )


def _agent(api: _TypeSafe, **overrides) -> JevAgent:
    return JevAgent(_config(**overrides), transport=httpx.MockTransport(api))


def _context():
    ctx = MagicMock()
    ctx.run_id = "run-1"
    ctx.node_path = "triage"
    ctx.parent_event_id = "node-event"
    ctx.event_recorder.record.return_value = "agent-event"
    return ctx


def _events(ctx) -> list[tuple]:
    return [(c.args[0], c.kwargs) for c in ctx.event_recorder.record.call_args_list]


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)


@pytest.fixture(autouse=True)
def sleeps(monkeypatch) -> list[float]:
    waited: list[float] = []
    monkeypatch.setattr(jev_agent, "_sleep", waited.append)
    return waited


class TestTheAnswersAreTheStructuredOutput:
    def test_a_node_gets_the_answers_keyed_by_question(self):
        api = _TypeSafe(_ok())
        result = _agent(api).run({"finding": FINDING}, _context())

        assert result.status == Status.COMPLETED, result.error
        assert result.structured_output == ANSWERS
        assert result.structured_output["severity"]["choice"] == "blocking"
        # AgentNode re-runs an agent with empty output, so the answers are the text output too.
        assert json.loads(result.output) == ANSWERS
        assert result.metadata == {"model": "jev-1.13.0", "request_id": "req-1"}

    def test_a_reply_as_typesafe_sent_it(self):
        """The whole body api.typesafe.ai sent on 2026-09-23, asked a choice, a noul and a score."""
        questions = {
            "severity": QUESTIONS["severity"],
            "user_visible": {"type": "noul", "instructions": "Would a user notice the problem?"},
            "real_defect": {
                "type": "score", "instructions": "How likely is this finding to be a real defect?",
                "criteria": ["Almost certainly a misreading", "Could go either way", "Almost certainly real"],
            },
        }
        answers = {
            "severity": {"type": "choice", "choice": "blocking", "confidence": 1.0,
                         "probabilities": {"blocking": 1.0, "minor": 0.0}},
            "user_visible": {"type": "noul", "noul": 0.81},
            "real_defect": {
                "type": "score", "score": 1.81, "confidence": 0.71,
                "legend": {"0": "Almost certainly a misreading", "1": "Could go either way",
                           "2": "Almost certainly real"},
                "probabilities": {"0": 0.02, "1": 0.15, "2": 0.83},
            },
        }
        api = _TypeSafe(httpx.Response(
            200,
            json={"model": "jev-1.13.0", "answers": answers,
                  "usage": {"input_tokens": 468, "output_tokens": 64}},
            headers={"x-typesafe-request-id": "req_01a0cea256a173b59f46575c704abd55",
                     "content-type": "application/json"},
        ))
        result = _agent(api, questions=questions).run({"finding": FINDING}, _context())

        assert result.status == Status.COMPLETED, result.error
        assert result.structured_output == answers
        assert (result.tokens.prompt_tokens, result.tokens.completion_tokens) == (468, 64)
        assert result.cost_usd == pytest.approx(468 * 0.042 / 1_000_000)
        assert result.metadata["request_id"] == "req_01a0cea256a173b59f46575c704abd55"

    def test_the_request_is_the_one_typesafe_documents(self):
        api = _TypeSafe(_ok())
        _agent(api).run({"finding": FINDING}, _context())

        (request,) = api.requests
        assert request.method == "POST"
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert api.bodies == [{"model": "jev-1.13.0", "state": FINDING, "questions": QUESTIONS}]

    def test_a_mapping_state_is_sent_as_an_object(self):
        api = _TypeSafe(_ok())
        agent = _agent(api, state_template={"finding": "{{ finding }}", "file": "{{ path }}", "lines": [3, 9]})
        agent.run({"finding": FINDING, "path": "orders/save.py"}, _context())

        assert api.bodies[0]["state"] == {"finding": FINDING, "file": "orders/save.py", "lines": [3, 9]}

    def test_input_tokens_are_priced_and_output_tokens_are_free(self):
        api = _TypeSafe(_ok(input_tokens=2_000_000))
        result = _agent(api).run({"finding": FINDING}, _context())

        assert result.cost_usd == pytest.approx(0.084)
        assert result.cost_usd == pytest.approx(2_000_000 * USD_PER_INPUT_TOKEN)
        assert (result.tokens.prompt_tokens, result.tokens.completion_tokens) == (2_000_000, 12)
        assert result.tokens.total_tokens == 2_000_012

    def test_the_model_defaults_to_the_latest_alias_and_reports_the_one_that_answered(self):
        api = _TypeSafe(_ok(model="jev-1.13.0"))
        config = _config()
        del config["model"]
        result = JevAgent(config, transport=httpx.MockTransport(api)).run({"finding": FINDING}, _context())

        assert api.bodies[0]["model"] == "jev-latest"
        assert result.metadata["model"] == "jev-1.13.0"

    def test_the_base_url_can_be_overridden(self, monkeypatch):
        monkeypatch.setenv("TYPESAFE_BASE_URL", "http://typesafe-proxy.local/")
        api = _TypeSafe(_ok())
        _agent(api).run({"finding": FINDING}, _context())

        assert str(api.requests[0].url) == "http://typesafe-proxy.local/v1/systemone"


class TestNothingToJudgeIsNotAJudgement:
    """Asked about an empty state, Jev still answers, with a probability that looks like a
    judgement. A node that routes on it must fail instead, before anything is sent."""

    def test_an_input_that_was_never_supplied_fails_the_node(self):
        api = _TypeSafe()
        result = _agent(api).run({}, _context())

        assert result.status == Status.FAILED
        assert "'finding' is undefined" in result.error
        assert "input_map" in result.error
        assert api.requests == []

    def test_a_state_that_renders_blank_fails_the_node(self):
        api = _TypeSafe()
        result = _agent(api).run({"finding": "  \n "}, _context())

        assert result.status == Status.FAILED
        assert "rendered empty" in result.error
        assert api.requests == []

    def test_a_mapping_of_blanks_is_blank(self):
        api = _TypeSafe()
        agent = _agent(api, state_template={"finding": "{{ finding }}", "file": "{{ path }}"})
        result = agent.run({"finding": "", "path": " "}, _context())

        assert result.status == Status.FAILED
        assert api.requests == []

    def test_a_default_is_the_way_to_allow_a_missing_input(self):
        api = _TypeSafe(_ok())
        agent = _agent(api, state_template="{{ finding }} (in {{ path | default('an unknown file') }})")
        result = agent.run({"finding": FINDING}, _context())

        assert result.status == Status.COMPLETED
        assert api.bodies[0]["state"] == f"{FINDING} (in an unknown file)"


class TestTheConfigIsCheckedBeforeAnythingIsSent:
    def test_a_complete_config_has_no_errors(self):
        assert jev_config_errors(_config()) == []
        assert jev_config_errors(_config(questions={"urgency": {
            "type": "score", "criteria": ["Can wait", "This week", "Today"]}})) == []
        assert jev_config_errors(_config(questions={"spam": {
            "type": "noul", "criteria": {"true": "Advertising", "false": "A real conversation"}}})) == []

    def test_every_size_typesafe_takes_is_taken(self):
        # The edges api.typesafe.ai answered on 2026-09-23.
        taken = {
            "most_options": {"type": "choice", "criteria": {f"o{i}": "" for i in range(255)}},
            "two_levels": {"type": "score", "criteria": ["calm", "upset"]},
            "most_levels": {"type": "score", "criteria": [f"L{i}" for i in range(10)]},
            "no_instructions": {"type": "choice", "criteria": {"billing": "money", "bug": "a defect"}},
            "empty_criteria": {"type": "noul", "instructions": "Is it billing?", "criteria": {}},
        }
        assert jev_config_errors(_config(questions=taken)) == []

    @pytest.mark.parametrize("change, complaint", [
        ({"questions": None}, "must have 'questions'"),
        ({"questions": {}}, "must have 'questions'"),
        ({"state_template": ""}, "must have 'state_template'"),
        ({"questions": {"q": {"type": "boolean"}}}, "one of noul, choice, score"),
        ({"questions": {"q": "Is it bad?"}}, "must be a mapping"),
        ({"questions": {"q": {"type": "choice"}}}, "Choice question 'q' needs 'criteria'"),
        ({"questions": {"q": {"type": "choice", "criteria": ["a", "b"]}}}, "Choice question 'q' needs 'criteria'"),
        ({"questions": {"q": {"type": "score", "criteria": {"low": "x"}}}}, "Score question 'q' needs 'criteria'"),
        ({"questions": {"q": {"type": "noul", "criteria": "yes if bad"}}}, "Noul question 'q'"),
        # TypeSafe answers these, always the same way, with confidence 1.0: routing on nothing.
        ({"questions": {"q": {"type": "choice", "criteria": {"only": "x"}}}},
         "Choice question 'q' has a single option, so Jev can only answer it one way"),
        ({"questions": {"q": {"type": "score", "criteria": ["only"]}}},
         "Score question 'q' has a single level"),
        # TypeSafe refuses these with a 400 when the node runs; the studio should refuse them first.
        ({"questions": {"q": {"type": "choice", "criteria": {f"o{i}": "" for i in range(256)}}}},
         "Choice question 'q' has 256 options; TypeSafe takes at most 255"),
        ({"questions": {"q": {"type": "score", "criteria": [f"L{i}" for i in range(11)]}}},
         "Score question 'q' has 11 levels; TypeSafe takes at most 10"),
        ({"questions": {"q": {"type": "noul"}}}, "Noul question 'q' needs 'instructions'"),
        ({"questions": {"q": {"type": "noul", "instructions": "", "criteria": {}}}},
         "Noul question 'q' needs 'instructions'"),
        ({"model": 1.13}, "'model' must be a model name"),
    ])
    def test_an_incomplete_config_is_named_and_nothing_is_sent(self, change, complaint):
        assert any(complaint in e for e in jev_config_errors(_config(**change)))

        api = _TypeSafe()
        result = _agent(api, **change).run({"finding": FINDING}, _context())
        assert result.status == Status.FAILED
        assert complaint in result.error
        assert api.requests == []


class TestTheKeyStaysInTemper:
    def test_no_key_fails_the_node_by_name(self, monkeypatch):
        monkeypatch.delenv("TYPESAFE_API_KEY")
        api = _TypeSafe()
        result = _agent(api).run({"finding": FINDING}, _context())

        assert result.status == Status.FAILED
        assert "TYPESAFE_API_KEY is not set" in result.error
        assert api.requests == []

    def test_the_key_is_in_no_event_and_no_error(self):
        # The body api.typesafe.ai sends for a bad key (seen 2026-09-23).
        api = _TypeSafe(httpx.Response(401, json={"detail": {
            "error_type": "authentication_error",
            "message": "Cannot authenticate with the server. Please check your API key and try again.",
        }}, headers={"x-typesafe-request-id": "req-4"}))
        ctx = _context()
        result = _agent(api).run({"finding": FINDING}, ctx)

        assert result.error == (
            "TypeSafe refused the request: 401 authentication_error: Cannot authenticate with the "
            "server. Please check your API key and try again.; check TYPESAFE_API_KEY (request_id=req-4)"
        )
        assert KEY not in result.error
        assert KEY not in json.dumps([kwargs for _, kwargs in _events(ctx)], default=str)

    def test_scripts_never_see_it(self, monkeypatch):
        """A script agent's Bash gets the environment minus every *_API_KEY."""
        from temper_ai.tools.bash import _safe_env

        assert "TYPESAFE_API_KEY" not in _safe_env()


class TestWhatAskingAgainCanFix:
    def test_a_rate_limit_waits_as_long_as_typesafe_says(self, sleeps):
        api = _TypeSafe(httpx.Response(429, headers={"retry-after-ms": "250"}), _ok())
        result = _agent(api).run({"finding": FINDING}, _context())

        assert result.status == Status.COMPLETED
        assert len(api.requests) == 2
        assert sleeps == [0.25]

    def test_server_errors_back_off_and_retry_twice(self, sleeps):
        api = _TypeSafe(httpx.Response(503), httpx.Response(502), _ok())
        result = _agent(api).run({"finding": FINDING}, _context())

        assert result.status == Status.COMPLETED
        assert sleeps == [0.5, 1.0]

    def test_it_gives_up_after_three_attempts(self):
        api = _TypeSafe(httpx.Response(500), httpx.Response(500),
                        httpx.Response(500, json={"message": "overloaded"}, headers={"x-typesafe-request-id": "req-3"}))
        result = _agent(api).run({"finding": FINDING}, _context())

        assert result.status == Status.FAILED
        assert len(api.requests) == 3
        assert result.error == "TypeSafe refused the request after 3 attempts: 500 overloaded (request_id=req-3)"

    def test_a_long_retry_after_is_capped(self, sleeps):
        api = _TypeSafe(httpx.Response(429, headers={"retry-after": "600"}), _ok())
        _agent(api).run({"finding": FINDING}, _context())

        assert sleeps == [jev_agent.RETRY_AFTER_MAX_SECONDS]

    def test_a_dropped_connection_is_retried(self, sleeps):
        api = _TypeSafe(httpx.ConnectError("connection refused"), _ok())
        result = _agent(api).run({"finding": FINDING}, _context())

        assert result.status == Status.COMPLETED
        assert sleeps == [0.5]

    def test_an_unreachable_api_fails_the_node(self):
        api = _TypeSafe(*[httpx.ConnectError("connection refused")] * 3)
        result = _agent(api).run({"finding": FINDING}, _context())

        assert result.status == Status.FAILED
        assert "could not reach TypeSafe" in result.error
        assert len(api.requests) == 3

    def test_a_refused_request_is_not_retried_and_says_why(self, sleeps):
        refusal = httpx.Response(
            422,
            json={"detail": [{"loc": ["body", "questions", "severity", "criteria"], "msg": "Field required",
                              "type": "missing"}]},
            headers={"x-typesafe-request-id": "req-9"},
        )
        api = _TypeSafe(refusal)
        result = _agent(api).run({"finding": FINDING}, _context())

        assert result.status == Status.FAILED
        assert len(api.requests) == 1 and sleeps == []
        assert result.error == (
            "TypeSafe refused the request: 422 body.questions.severity.criteria: Field required (request_id=req-9)"
        )

    def test_a_state_over_the_token_limit_says_so(self, sleeps):
        # The body api.typesafe.ai sent for a state of ~40k tokens (2026-09-23): no message in it.
        api = _TypeSafe(httpx.Response(
            400, json={"detail": {"error_type": "max_tokens_exceeded"}},
            headers={"x-typesafe-request-id": "req-5"},
        ))
        result = _agent(api).run({"finding": FINDING}, _context())

        assert len(api.requests) == 1 and sleeps == []
        assert result.error == (
            "TypeSafe refused the request: 400 max_tokens_exceeded; the state and the longest "
            "question are over Jev's token limit: give it less state (request_id=req-5)"
        )

    def test_an_unknown_model_is_named(self, sleeps):
        api = _TypeSafe(httpx.Response(
            400, json={"detail": {"error_type": "api_usage_error", "message": "Unknown model: jev-0.0.0"}},
            headers={"x-typesafe-request-id": "req-6"},
        ))
        result = _agent(api, model="jev-0.0.0").run({"finding": FINDING}, _context())

        assert len(api.requests) == 1 and sleeps == []
        assert result.error == (
            "TypeSafe refused the request: 400 api_usage_error: Unknown model: jev-0.0.0 (request_id=req-6)"
        )


class TestTheAnswersAreChecked:
    """A condition on `severity.choice` reads None from a missing or mistyped answer, and None
    routes somewhere. So the reply is checked against the questions."""

    def test_a_question_left_unanswered_fails_the_node(self):
        api = _TypeSafe(_ok(answers={"severity": ANSWERS["severity"]}))
        result = _agent(api).run({"finding": FINDING}, _context())

        assert result.status == Status.FAILED
        assert "did not answer ['is_flaky']" in result.error

    def test_an_answer_of_another_type_fails_the_node(self):
        api = _TypeSafe(_ok(answers={**ANSWERS, "severity": {"type": "noul", "noul": 0.9}}))
        result = _agent(api).run({"finding": FINDING}, _context())

        assert result.status == Status.FAILED
        assert "answered 'severity' as 'noul', but it was asked as 'choice'" in result.error

    def test_an_answer_nobody_asked_for_is_dropped(self):
        api = _TypeSafe(_ok(answers={**ANSWERS, "extra": {"type": "noul", "noul": 0.5}}))
        result = _agent(api).run({"finding": FINDING}, _context())

        assert result.structured_output == ANSWERS


class TestTheRunRecordsIt:
    def test_started_and_completed_events(self):
        ctx = _context()
        _agent(_TypeSafe(_ok())).run({"finding": FINDING}, ctx)

        (started_type, started), (done_type, done) = _events(ctx)
        assert started_type == EventType.AGENT_STARTED
        assert started["parent_id"] == "node-event"
        # Flat, the way LLMAgent records it: the run view labels the agent from `type` and `model`.
        assert started["data"]["agent_config"]["type"] == "jev"
        assert started["data"]["agent_config"]["model"] == "jev-1.13.0"
        assert started["data"]["agent_config"]["questions"] == QUESTIONS
        assert started["data"]["input_data"] == {"finding": FINDING}

        assert done_type == EventType.AGENT_COMPLETED
        assert done["parent_id"] == "agent-event"
        assert done["data"]["structured_output"] == ANSWERS
        assert done["data"]["cost_usd"] == pytest.approx(120 * USD_PER_INPUT_TOKEN)
        assert done["data"]["tokens"] == 132
        assert done["data"]["request_id"] == "req-1"

    def test_a_failure_is_recorded_as_one(self):
        ctx = _context()
        _agent(_TypeSafe()).run({}, ctx)

        done_type, done = _events(ctx)[-1]
        assert done_type == EventType.AGENT_FAILED
        assert done["status"] == "failed"
        assert "'finding' is undefined" in done["data"]["error"]
        assert done["data"]["error_type"] == "JevError"


class TestInAWorkflow:
    def test_jev_is_a_registered_agent_type(self):
        assert AGENT_TYPES["jev"] is JevAgent
        assert isinstance(create_agent(_config()), JevAgent)

    def test_a_condition_routes_on_an_answer(self, monkeypatch):
        """The whole point: the answers reach the graph as they are, and a condition reads them."""
        api = _TypeSafe(_ok())
        monkeypatch.setitem(
            AGENT_TYPES, "jev", functools.partial(JevAgent, transport=httpx.MockTransport(api)),
        )
        node = AgentNode(NodeConfig(name="triage"), _config())
        ctx = ExecutionContext(
            run_id="run-1", workflow_name="review", node_path="", agent_name="",
            event_recorder=MagicMock(), tool_executor=None,
        )
        result = node.run({"finding": FINDING}, ctx)

        assert result.status == Status.COMPLETED, result.error
        assert result.structured_output == ANSWERS
        assert result.cost_usd == pytest.approx(120 * USD_PER_INPUT_TOKEN)
        outputs = {"triage": result}
        assert evaluate_condition(
            {"source": "triage.structured.severity.choice", "operator": "equals", "value": "blocking"}, outputs,
        )
        assert not evaluate_condition(
            {"source": "triage.structured.severity.choice", "operator": "equals", "value": "minor"}, outputs,
        )


def _store(configs: dict):
    store = MagicMock()

    def get(name, config_type):
        return configs[f"{config_type}:{name}"]

    store.get = MagicMock(side_effect=get)
    return store


class TestWorkflowLLMSettingsStayWithLLMAgents:
    """A workflow's `defaults: {provider, model}` and a run-wide `--model` name the LLM. Merged
    into a jev agent they would be sent to TypeSafe as the Jev model."""

    JEV = {"name": "triage", "type": "jev", "state_template": "{{ finding }}", "questions": QUESTIONS}
    LLM = {"name": "planner", "type": "llm", "system_prompt": "You plan."}

    def _load(self, nodes: list, jev: dict | None = None, overrides: dict | None = None) -> list:
        loader = GraphLoader(_store({
            "workflow:wf": {"name": "wf", "defaults": {"provider": "vllm", "model": "qwen3", "temperature": 0.2},
                            "nodes": nodes},
            "agent:triage": jev or self.JEV,
            "agent:planner": self.LLM,
        }))
        loader._overrides = overrides or {}
        nodes, _ = loader.load_workflow("wf")
        return nodes

    def test_the_default_model_does_not_reach_a_jev_agent(self):
        jev, llm = self._load([
            {"name": "triage", "type": "agent", "agent": "agents/triage"},
            {"name": "planner", "type": "agent", "agent": "agents/planner"},
        ])
        assert not {"provider", "model", "temperature"} & set(jev.agent_config)
        assert JevAgent(jev.agent_config).model == "jev-latest"
        # An LLM agent in the same workflow still gets them.
        assert (llm.agent_config["provider"], llm.agent_config["model"]) == ("vllm", "qwen3")

    def test_a_run_wide_model_override_does_not_replace_the_jev_model(self):
        jev, llm = self._load(
            [{"name": "triage", "type": "agent", "agent": "agents/triage"},
             {"name": "planner", "type": "agent", "agent": "agents/planner"}],
            jev={**self.JEV, "model": "jev-1.13.0"},
            overrides={"provider": "openai", "model": "gpt-4o"},
        )
        assert jev.agent_config["model"] == "jev-1.13.0"
        assert "provider" not in jev.agent_config
        assert llm.agent_config["model"] == "gpt-4o"

    def test_the_node_can_still_choose_its_jev_model(self):
        (jev,) = self._load([{"name": "triage", "type": "agent", "agent": "agents/triage", "model": "jev-1.12.0"}])
        assert jev.agent_config["model"] == "jev-1.12.0"

    def test_a_jev_agent_in_a_strategy_stage_is_kept_apart_too(self):
        (stage,) = self._load([{
            "name": "review", "type": "stage", "strategy": "parallel",
            "agents": ["agents/triage", "agents/planner"],
        }])
        jev, llm = stage.child_nodes
        assert "model" not in jev.agent_config
        assert llm.agent_config["model"] == "qwen3"
