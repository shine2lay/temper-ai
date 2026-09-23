"""Jev agent — asks TypeSafe AI's Jev model typed questions about the node's inputs.

Jev is not an LLM, so this is not an LLMAgent with another provider behind it. It writes no text.
It is given some content (the *state*) and a set of named questions, each of a declared type, and
returns every answer at once, with its probabilities:

    noul     yes or no: the probability of yes             {"type": "noul", "noul": 0.02}
    choice   one of the options named in `criteria`        {"type": "choice", "choice": "blocking",
                                                             "confidence": 0.91, "probabilities": {...}}
    score    a level of the ordered rubric in `criteria`   {"type": "score", "score": 1.7,
                                                             "confidence": 0.8, "legend": {...}, ...}

The answers are structured already, so they become the node's structured_output as they arrive,
keyed by question name: there is no prompt to build and no reply to parse. A condition routes on
them the way it routes on any node's output (`triage.structured.severity.choice`).

    name: triage_finding
    type: jev
    model: jev-1.13.0                  # default jev-latest, which moves; pin it
    state_template: "{{ finding }}"    # Jinja over the node's inputs; a mapping renders to an object
    questions:
      severity:
        type: choice
        instructions: How serious is this review finding?
        criteria:
          blocking: Breaks behaviour or loses data
          minor: Style, naming or a nit

The API key is read from TYPESAFE_API_KEY in temper's own process. Scripts never see it: the Bash
tool strips every *_API_KEY from the environment it gives them. TYPESAFE_BASE_URL overrides the
endpoint (the same two variables TypeSafe's SDK reads).

What TypeSafe accepts (api.typesafe.ai, 2026-09-23): a choice of 2 to 255 options, a score of 2 to
10 levels, a noul with instructions or criteria. It refuses more options or levels, but it answers
a single one, always the same way with confidence 1.0, and it answers an empty state (noul 0.5):
questions that can only come out one way, or that are about nothing. This agent refuses those
before anything is sent.

Asked the same thing twice, Jev can differ in the second decimal: twelve identical requests gave
a noul of 0.80 to 0.83, and the choice did not move. A threshold that sits on the edge of an answer
can go either way on a re-run.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx
from jinja2 import BaseLoader, StrictUndefined, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

from temper_ai.agent.base import AgentABC
from temper_ai.agent.exceptions import JevError
from temper_ai.agent.llm_agent import _truncate_input_data
from temper_ai.observability import EventType
from temper_ai.observability import record as _default_record
from temper_ai.shared.types import AgentResult, ExecutionContext, Status, TokenUsage

logger = logging.getLogger(__name__)

API_KEY_ENV = "TYPESAFE_API_KEY"
BASE_URL_ENV = "TYPESAFE_BASE_URL"
DEFAULT_BASE_URL = "https://api.typesafe.ai"
ENDPOINT = "/v1/systemone"
REQUEST_ID_HEADER = "x-typesafe-request-id"
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT_SECONDS = 30.0

QUESTION_TYPES = ("noul", "choice", "score")

#: The most options and levels TypeSafe takes (it refuses more with a 400 when the node runs).
MAX_CHOICE_OPTIONS = 255
MAX_SCORE_LEVELS = 10

#: $0.042 per million input tokens (typesafe.ai pricing, September 2026). Output tokens are free.
USD_PER_INPUT_TOKEN = 0.042 / 1_000_000

#: Worth asking again: the statuses TypeSafe's own SDK retries, twice, with the same backoff.
RETRY_STATUSES = frozenset({408, 429, *range(500, 600)})
MAX_RETRIES = 2
BACKOFF_INITIAL_SECONDS = 0.5
BACKOFF_MAX_SECONDS = 5.0
#: The longest wait taken on TypeSafe's say-so (Retry-After). A run should not stall on one node.
RETRY_AFTER_MAX_SECONDS = 30.0

_sleep = time.sleep  # replaced in tests


def jev_config_errors(config: dict) -> list[str]:
    """What stops a jev agent config from running. The studio refuses to save the same things."""
    errors: list[str] = []
    state = config.get("state_template")
    if not state or not isinstance(state, (str, dict, list)):
        errors.append("A jev agent must have 'state_template': the content its questions are about")
    model = config.get("model") or DEFAULT_MODEL
    if not isinstance(model, str):
        errors.append(f"A jev agent's 'model' must be a model name such as jev-1.13.0, not {model!r}")
    questions = config.get("questions")
    if not isinstance(questions, dict) or not questions:
        errors.append(
            "A jev agent must have 'questions': each name mapped to {type, instructions, criteria}"
        )
        return errors
    for name, question in questions.items():
        errors.extend(_question_errors(str(name), question))
    return errors


def _question_errors(name: str, question: Any) -> list[str]:
    if not isinstance(question, dict):
        return [f"Question '{name}' must be a mapping with a 'type'"]
    kind = question.get("type")
    if kind not in QUESTION_TYPES:
        return [f"Question '{name}' has type {kind!r}; a jev question is one of {', '.join(QUESTION_TYPES)}"]
    criteria = question.get("criteria")
    if kind == "choice":
        if not isinstance(criteria, dict) or not criteria:
            return [f"Choice question '{name}' needs 'criteria': each option's name mapped to when it applies"]
        return _count_errors(name, "Choice", "option", len(criteria), MAX_CHOICE_OPTIONS)
    if kind == "score":
        if not isinstance(criteria, list) or not criteria:
            return [f"Score question '{name}' needs 'criteria': a list of the levels, lowest first"]
        return _count_errors(name, "Score", "level", len(criteria), MAX_SCORE_LEVELS)
    if criteria is not None and not isinstance(criteria, dict):
        return [f"Noul question '{name}': 'criteria' must be a mapping with 'true' and/or 'false'"]
    if not question.get("instructions") and not criteria:
        return [
            f"Noul question '{name}' needs 'instructions' (or 'criteria' saying when it is true): "
            f"TypeSafe refuses one with neither"
        ]
    return []


def _count_errors(name: str, kind: str, noun: str, count: int, most: int) -> list[str]:
    # TypeSafe answers a question with a single option or level the same way every time, with
    # confidence 1.0: a node routing on it routes on nothing, so it is refused here.
    if count < 2:
        return [
            f"{kind} question '{name}' has a single {noun}, so Jev can only answer it one way: "
            f"give it two or more"
        ]
    if count > most:
        return [f"{kind} question '{name}' has {count} {noun}s; TypeSafe takes at most {most}"]
    return []


class JevAgent(AgentABC):
    """Agent that answers typed questions about its inputs with TypeSafe AI's Jev model."""

    #: A workflow's default provider and model, and a run-wide `--model`, are LLM settings. Merged
    #: in, `model: claude-sonnet-4-6` would be sent to TypeSafe as the Jev model (see GraphLoader).
    uses_llm_settings = False

    def __init__(self, config: dict, *, transport: httpx.BaseTransport | None = None):
        super().__init__(config)
        self.model = config.get("model") or DEFAULT_MODEL
        self._transport = transport

    def validate_config(self) -> list[str]:
        return super().validate_config() + jev_config_errors(self.config)

    def run(self, input_data: dict, context: ExecutionContext) -> AgentResult:
        """Render the state, ask the questions, return the answers as structured output.

        Every failure (bad config, a state rendered from nothing, no key, a refused request)
        is a failed node with the reason in `error`, never an exception: AgentNode would retry an
        exception, and none of these is fixed by asking again. Transient trouble (429, 5xx, a
        dropped connection) is retried here instead, before the node gives up.
        """
        start = time.monotonic()
        _record = context.event_recorder.record if context.event_recorder else _default_record
        agent_event_id = self._record_started(_record, input_data, context)
        error_type = None
        try:
            result = self._answer(input_data, start)
        except Exception as exc:  # noqa: BLE001 — a failed node, not a crashed run
            error_type = type(exc).__name__
            result = AgentResult(
                status=Status.FAILED,
                output="",
                error=str(exc),
                duration_seconds=round(time.monotonic() - start, 3),
            )
        self._record_finished(_record, result, agent_event_id, context, error_type)
        return result

    def _answer(self, input_data: dict, start: float) -> AgentResult:
        problems = self.validate_config()
        if problems:
            raise JevError(f"jev agent '{self.name}': " + "; ".join(problems))
        questions = self.config["questions"]
        state = self._render_state(input_data)
        reply, request_id = self._ask({"model": self.model, "state": state, "questions": questions})
        answers = _answers_to(questions, reply, request_id)
        raw_usage = reply.get("usage")
        usage: dict = raw_usage if isinstance(raw_usage, dict) else {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        return AgentResult(
            status=Status.COMPLETED,
            # AgentNode re-runs an agent whose output is empty, so the answers are the output too.
            output=json.dumps(answers),
            structured_output=answers,
            tokens=TokenUsage(
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            cost_usd=input_tokens * USD_PER_INPUT_TOKEN,
            duration_seconds=round(time.monotonic() - start, 3),
            # The alias asked for and the model that answered can differ (jev-latest → jev-1.13.0).
            metadata={"model": reply.get("model") or self.model, "request_id": request_id},
        )

    def _render_state(self, input_data: dict) -> str | dict | list:
        """Render `state_template` over the node's inputs: a string to a string, a mapping or list
        to the same shape with every string in it rendered.

        An undefined reference is an error here, not a blank. Rendered blank, a missing input
        leaves Jev answering about nothing, and it answers anyway, with a probability that looks
        like a judgement. A decision node must not route on that. (ScriptAgent renders blanks
        because 82 configs relied on it before it could choose; this type has no such history.)
        """
        env = SandboxedEnvironment(loader=BaseLoader(), undefined=StrictUndefined)
        try:
            state = _render(env, self.config["state_template"], input_data)
        except UndefinedError as exc:
            raise JevError(
                f"state_template for '{self.name}' referenced an undefined value: {exc}. "
                f"Supply it via input_map, or give the template a `| default(...)`."
            ) from exc
        if _blank(state):
            raise JevError(
                f"state_template for '{self.name}' rendered empty: there is nothing for Jev to "
                f"answer about. Check the inputs it was given."
            )
        return state

    def _ask(self, body: dict) -> tuple[dict, str | None]:
        """POST the questions to TypeSafe and return its reply and request id, retrying the
        failures that asking again can fix."""
        api_key = os.environ.get(API_KEY_ENV, "").strip()
        if not api_key:
            raise JevError(
                f"{API_KEY_ENV} is not set in temper's environment, so the jev agent "
                f"'{self.name}' cannot call TypeSafe"
            )
        base = os.environ.get(BASE_URL_ENV, "").strip().rstrip("/") or DEFAULT_BASE_URL
        url = base + ENDPOINT
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        timeout = float(self.config.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        with httpx.Client(transport=self._transport, timeout=timeout) as client:
            attempt = 0
            while True:
                try:
                    response = client.post(url, json=body, headers=headers)
                except httpx.TransportError as exc:  # connect errors and timeouts
                    if attempt >= MAX_RETRIES:
                        raise JevError(
                            f"could not reach TypeSafe at {url} ({attempt + 1} attempts): {exc}"
                        ) from exc
                    _sleep(_backoff(attempt))
                    attempt += 1
                    continue
                if response.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                    logger.warning(
                        "Jev agent '%s': TypeSafe answered %s, retrying (%d/%d)",
                        self.name, response.status_code, attempt + 1, MAX_RETRIES,
                    )
                    _sleep(_retry_delay(response, attempt))
                    attempt += 1
                    continue
                return _reply(response, attempt + 1)

    def _record_started(self, _record, input_data: dict, context: ExecutionContext) -> str:
        """Emit AGENT_STARTED and return its id. `agent_config` is flat, the way LLMAgent records
        it, because the run view reads `agent_config.type` and `.model` to label the agent."""
        return _record(
            EventType.AGENT_STARTED,
            parent_id=context.parent_event_id,
            execution_id=context.run_id,
            status="running",
            data={
                "agent_name": self.name,
                "node_path": context.node_path,
                "type": "jev",
                "model": self.model,
                "input_data": _truncate_input_data(input_data),
                "agent_config": {
                    "type": "jev",
                    "name": self.name,
                    "model": self.model,
                    "state_template": self.config.get("state_template"),
                    "questions": self.config.get("questions"),
                },
            },
        )

    def _record_finished(self, _record, result: AgentResult, agent_event_id: str,
                         context: ExecutionContext, error_type: str | None) -> None:
        failed = result.status == Status.FAILED
        _record(
            EventType.AGENT_FAILED if failed else EventType.AGENT_COMPLETED,
            parent_id=agent_event_id,
            execution_id=context.run_id,
            status="failed" if failed else "completed",
            data={
                "agent_name": self.name,
                **({"error": result.error, "error_type": error_type} if failed else {}),
                "output": result.output[:5000],
                "output_length": len(result.output),
                "structured_output": result.structured_output,
                "has_structured_output": result.structured_output is not None,
                "tokens": result.tokens.total_tokens,
                "cost_usd": result.cost_usd,
                "duration_seconds": result.duration_seconds,
                **result.metadata,
            },
        )


def _render(env: SandboxedEnvironment, template: Any, values: dict) -> Any:
    if isinstance(template, str):
        return env.from_string(template).render(**values)
    if isinstance(template, dict):
        return {key: _render(env, value, values) for key, value in template.items()}
    if isinstance(template, list):
        return [_render(env, item, values) for item in template]
    return template


def _blank(state: Any) -> bool:
    if isinstance(state, str):
        return not state.strip()
    if isinstance(state, dict):
        return all(_blank(value) for value in state.values())
    if isinstance(state, list):
        return all(_blank(item) for item in state)
    return state is None


def _backoff(attempt: int) -> float:
    return min(BACKOFF_INITIAL_SECONDS * 2 ** attempt, BACKOFF_MAX_SECONDS)


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """TypeSafe's own Retry-After when it sends one (`retry-after-ms` first), else the backoff."""
    for header, seconds_per_unit in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        raw = response.headers.get(header)
        if raw:
            try:
                return min(max(float(raw) * seconds_per_unit, 0.0), RETRY_AFTER_MAX_SECONDS)
            except ValueError:
                continue  # an HTTP date: take the backoff instead
    return _backoff(attempt)


def _reply(response: httpx.Response, attempts: int) -> tuple[dict, str | None]:
    request_id = response.headers.get(REQUEST_ID_HEADER)
    if not response.is_success:
        tries = f" after {attempts} attempts" if attempts > 1 else ""
        detail = _error_detail(response)
        hint = f"; check {API_KEY_ENV}" if response.status_code in (401, 403) else ""
        if detail == "max_tokens_exceeded":
            hint = "; the state and the longest question are over Jev's token limit: give it less state"
        raise JevError(
            f"TypeSafe refused the request{tries}: {response.status_code} "
            f"{detail}{hint} (request_id={request_id or '-'})"
        )
    try:
        reply = response.json()
    except ValueError as exc:
        raise JevError(
            f"TypeSafe answered {response.status_code} with a body that is not JSON "
            f"(request_id={request_id or '-'})"
        ) from exc
    if not isinstance(reply, dict):
        raise JevError(f"TypeSafe's reply is not an object (request_id={request_id or '-'})")
    return reply, request_id


def _error_detail(response: httpx.Response) -> str:
    """TypeSafe's own words: `message`, an error under `detail` ({error_type, message}, as a 401
    is sent, or a bare {error_type}, as a state over the token limit is), or the validation errors
    under `detail` (`loc: msg`)."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:500] or response.reason_phrase
    if isinstance(body, dict):
        if isinstance(body.get("message"), str):
            return body["message"]
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, dict):
            kind = detail.get("error_type")
            message = detail.get("message")
            if isinstance(message, str):
                return f"{kind}: {message}" if isinstance(kind, str) else message
            if isinstance(kind, str):
                return kind
        if isinstance(detail, list):
            parts = [
                f"{'.'.join(str(p) for p in item.get('loc') or [])}: {item.get('msg', '')}"
                for item in detail[:5] if isinstance(item, dict)
            ]
            if parts:
                return "; ".join(parts)
    return response.text[:500] or response.reason_phrase


def _answers_to(questions: dict, reply: dict, request_id: str | None) -> dict:
    """One answer per question asked, of the type asked, in the order asked.

    Checked rather than trusted: a condition on `severity.choice` reads None from a missing or
    mistyped answer, and None routes somewhere — quietly, on nothing.
    """
    answers = reply.get("answers")
    if not isinstance(answers, dict):
        raise JevError(f"TypeSafe's reply has no answers (request_id={request_id or '-'})")
    missing = [name for name in questions if name not in answers]
    if missing:
        raise JevError(f"Jev did not answer {missing} (request_id={request_id or '-'})")
    for name, question in questions.items():
        answer = answers[name]
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            got = answer.get("type") if isinstance(answer, dict) else type(answer).__name__
            raise JevError(
                f"Jev answered '{name}' as {got!r}, but it was asked as {question['type']!r} "
                f"(request_id={request_id or '-'})"
            )
    return {name: answers[name] for name in questions}
