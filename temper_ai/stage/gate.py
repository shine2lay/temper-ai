"""Human gates: what the human is shown, and what they answered.

A node with ``gate: true`` pauses before it runs. The pause is only useful
if the human can see what they are approving and can say something back,
so a gate carries two things:

- ``gate_context`` — recorded on the waiting event when the gate opens: the
  outputs of the nodes the gated node depends on, plus any *questions* those
  outputs asked (a ``questions`` / ``questions_for_owner`` list in the
  structured output, or in the output text when it is a JSON object). The
  dashboard's gate modal renders these, in the shape of pi's
  ``ask_user_question`` tool: a question, optional options with descriptions
  and previews, single or multi select, and a free-text custom answer.
- ``gate_response`` — what the human sent with the approval: per-question
  answers and a free-text response. The gated node gets it as the ``gate``
  input (``{{ gate.text }}`` in a task template is the whole thing rendered
  as ``Q:``/``A:`` lines followed by the free text).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from temper_ai.shared.types import NodeResult

QUESTION_KEYS = ("questions", "questions_for_owner", "questions_for_human")

EMPTY_RESPONSE: dict[str, Any] = {"response": "", "answers": [], "text": ""}


class GateSignal(threading.Event):
    """The in-process handle for one waiting gate.

    ``set()`` releases the node; ``response`` carries what the human said,
    so an in-process approval does not have to round-trip through the
    database to deliver its payload. It is registered under
    :func:`signal_key` -- the run and the wait's event id -- and carries
    which wait it is, for a run that keeps no events.
    """

    def __init__(self, event_id: str = "", node_name: str = "", path: str = "",
                 round_: int | None = None) -> None:
        super().__init__()
        self.response: dict[str, Any] | None = None
        self.event_id = event_id
        self.node_name = node_name
        self.path = path or node_name
        self.round = round_


def signal_key(execution_id: str, event_id: str) -> str:
    """Where a wait's :class:`GateSignal` is registered: one per wait, never one per name."""
    return f"{execution_id}:{event_id}"


# --- which wait is which -----------------------------------------------------
#
# A gate's wait is one ``stage.started`` event with ``gate: true``. Which wait it is: the run,
# the step's path (``stage.step``; the bare name at the top level), the round -- the how-manieth
# time this step asks, counting the asks that were answered -- and the event's own id. An
# approval names the event it answers, and lands only while that wait is still open; one that
# names only the step reaches it when it is the only wait open there.

WAITING = "waiting"
APPROVED = "approved"
REJECTED = "rejected"  # the run was stopped there (reject, cancel)
REPLACED = "replaced"  # the run was picked up again, and a later wait took this one's place


def gate_path(data: dict[str, Any]) -> str:
    """The step a wait is at: its path, or -- for a wait recorded before paths were -- its name."""
    return str(data.get("gate_path") or data.get("name") or "")


def names_gate(data: dict[str, Any], node: str) -> bool:
    """Whether ``node`` -- what a caller put in the URL -- names this wait's step, by name or path."""
    return bool(node) and node in (data.get("name"), data.get("gate_path"))


def describe_gate(ev: dict[str, Any]) -> dict[str, Any]:
    """One wait, as an approval's answer and a refusal show it."""
    data = ev.get("data") or {}
    return {
        "event_id": ev.get("id"),
        "node_name": data.get("name", ""),
        "path": gate_path(data),
        "round": data.get("gate_round"),
        "status": data.get("gate_status") or ev.get("status") or WAITING,
        "answered_by": data.get("gate_decided_by"),
        "answered_at": data.get("gate_decided_at"),
        "request_id": data.get("gate_request_id"),
        "replaced_by": data.get("gate_replaced_by"),
        "opened_at": ev.get("timestamp"),
    }


def _which(g: dict[str, Any]) -> str:
    rnd = f", round {g['round']}" if g.get("round") else ""
    return f"'{g.get('path') or g.get('node_name')}'{rnd}"


def refusal(g: dict[str, Any]) -> dict[str, Any]:
    """What an approval is told when the wait it named is no longer open (HTTP 409)."""
    who = f" by {g['answered_by']}" if g.get("answered_by") else ""
    when = f" at {g['answered_at']}" if g.get("answered_at") else ""
    status = g.get("status")
    if status == APPROVED:
        reason, message = "already_answered", (
            f"Already answered{who}{when}: the approval at {_which(g)} is closed, so this one "
            "changed nothing.")
    elif status == REJECTED:
        reason, message = "already_rejected", (
            f"Already turned down{who}{when} (the run was stopped at {_which(g)}), so this "
            "approval changed nothing.")
    elif status == REPLACED:
        reason, message = "replaced", (
            f"This approval at {_which(g)} was replaced: the run was picked up again and asks "
            "again in a new one. Nothing was changed; answer the open one.")
    else:
        reason, message = "closed", f"The approval at {_which(g)} is not open ({status}); nothing was changed."
    return {"message": message, "reason": reason, **g}


def several_waiting(node: str, waits: list[dict[str, Any]]) -> dict[str, Any]:
    """What an approval by name alone is told when more than one wait answers to it (HTTP 409)."""
    listed = "; ".join(f"{_which(g)} (event_id {g['event_id']})" for g in waits)
    return {
        "message": (f"{len(waits)} approvals named '{node}' are waiting: {listed}. Nothing was "
                    "approved; say which one with its event_id."),
        "reason": "several_waiting",
        "waiting": waits,
    }


@dataclass
class EarlierWaits:
    """What a step's earlier waits mean when the run reaches its gate again (see :func:`earlier_waits`)."""

    answer: dict[str, Any] | None = None  # approved while nothing waited on it: use it, ask nothing
    adopt: dict[str, Any] | None = None  # still open from before: wait on it again
    retire: list[dict[str, Any]] = dataclass_field(default_factory=list)  # open, but no longer anyone's
    round: int = 1  # the round a new wait would be


def earlier_waits(history: list[dict[str, Any]], path: str, name: str) -> EarlierWaits:
    """Sort out a step's earlier waits as it reaches its gate.

    ``history`` is the run's gate waits at steps called ``name``, oldest first. A wait
    recorded with a path belongs to this step when the path is its own; one recorded
    before waits had paths, by its name.

    * an approval nobody used yet -- given while the run was down, or just before it
      stopped -- is this step's answer: the run goes on with it and asks nothing;
    * else a wait still open from an earlier attempt is adopted: the run waits on it again,
      so the messages and buttons already out keep working;
    * every other open wait at the step (one from before waits had paths, a duplicate) is
      retired as replaced, so the step never has two open at once.
    """
    mine: list[dict[str, Any]] = []
    for ev in history:
        data = ev.get("data") or {}
        at = data.get("gate_path")
        if (at == path) if at else (data.get("name") == name):
            mine.append(ev)

    def has_path(ev: dict[str, Any]) -> bool:
        return bool((ev.get("data") or {}).get("gate_path"))

    def unused_answer(ev: dict[str, Any]) -> bool:
        data = ev.get("data") or {}
        # One from before waits had paths counts only when it says it was kept for a resume:
        # otherwise the step went on with it back then.
        return (ev.get("status") == APPROVED and not data.get("gate_used_at")
                and (has_path(ev) or bool(data.get("gate_kept_for_resume"))))

    decided = [ev for ev in mine if has_path(ev) and ev.get("status") in (APPROVED, REJECTED)]
    open_ = [ev for ev in mine if ev.get("status") == WAITING]
    answers = [ev for ev in mine if unused_answer(ev)]
    if answers:
        answer = answers[0]
        return EarlierWaits(answer=answer, retire=open_,
                            round=(answer.get("data") or {}).get("gate_round") or len(decided))
    adoptable = [ev for ev in open_ if has_path(ev)]
    adopt = adoptable[-1] if adoptable else None
    return EarlierWaits(
        adopt=adopt,
        retire=[ev for ev in open_ if ev is not adopt],
        round=((adopt.get("data") or {}).get("gate_round") if adopt else None) or len(decided) + 1,
    )


# --- what the human is shown -------------------------------------------------


def build_gate_context(depends_on: list[str], node_outputs: dict[str, NodeResult]) -> dict[str, Any]:
    """The upstream outputs a gate is about, and the questions they asked."""
    upstream: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    for dep in depends_on:
        result = node_outputs.get(dep)
        if result is None:
            continue
        structured = result.structured_output if isinstance(result.structured_output, dict) else None
        asked = questions_from(structured, result.output)
        full = result.output or ""
        entry: dict[str, Any] = {
            "node": dep,
            "output": summarise_output(full, asked),
            "structured_output": structured,
        }
        # Keep the whole thing for whoever wants it, but only when it is not
        # already what is being shown.
        if full != entry["output"]:
            entry["full_output"] = full
        upstream.append(entry)
        for q in asked:
            q = dict(q)
            q["node"] = dep
            questions.append(q)
    return {"upstream": upstream, "questions": questions}


#: Fields worth reading aloud when an output is a JSON document of questions.
PROSE_KEYS = ("summary", "pitch", "description", "context", "notes", "output", "text")


def summarise_output(text: str, asked: list[dict[str, Any]]) -> str:
    """What to show a human for an upstream output.

    Normally the output itself. But when the output is the JSON document the
    questions were parsed out of, showing it raw puts every question on
    screen twice — once as unreadable JSON, once as the form below it. In
    that case show only its prose fields (a ``summary`` and the like); the
    full text stays available as ``full_output``.
    """
    if not asked:
        return text
    document = _as_json_object(text)
    if document is None:
        return text
    prose = [
        value.strip()
        for key in PROSE_KEYS
        if isinstance(value := document.get(key), str) and value.strip()
    ]
    return "\n\n".join(prose)


def questions_from(structured: dict[str, Any] | None, text: str | None) -> list[dict[str, Any]]:
    """Questions an upstream node asked, normalised to the ask_user_question shape.

    Structured output is asked first, then an output text that is one JSON
    object — and the text is still tried when the structured output carries
    no questions, because an agent's structured output is not always the
    document it printed (a script's extractor may hand back a nested object
    from it). Anything else asked no questions.
    """
    for source in (structured, _as_json_object(text)):
        if not isinstance(source, dict):
            continue
        for key in QUESTION_KEYS:
            raw = source.get(key)
            if isinstance(raw, list):
                out = [q for q in (normalise_question(item, i + 1) for i, item in enumerate(raw)) if q]
                if out:
                    return out
    return []


def _as_json_object(text: str | None) -> dict[str, Any] | None:
    """``text`` when the whole of it is one JSON object, else None.

    Parsed with ``strict=False`` so a literal newline or tab inside a string
    still reads. Writing one is routine -- a model composing prose in a
    ``summary`` field, a script interpolating an earlier answer -- and it is
    the one failure a human pays for directly: the questions are dropped, and
    the gate shows a wall of raw JSON above a bare Approve button, which is
    to say it asks someone to approve something it declined to explain.
    """
    stripped = (text or "").strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped, strict=False)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def normalise_question(raw: Any, index: int) -> dict[str, Any] | None:
    """One question as the model wrote it → the shape the modal renders.

    A bare string is a free-text question. A dict keeps ``id``, ``question``
    (also accepted as ``text`` / ``prompt``), ``header`` (also ``key``),
    ``detail`` (also ``context``), ``options`` (strings or ``{label,
    description, preview}``) and ``multiSelect`` (also ``multi_select``).

    The aliases are not decoration: whoever writes these is an agent filling
    in a JSON object from memory, and a field under the wrong-but-obvious
    name used to be dropped in silence — the question still rendered, just
    stripped of the heading and the line of context that made it answerable.
    """
    if isinstance(raw, str):
        text = raw.strip()
        return {"id": f"q{index}", "question": text} if text else None
    if not isinstance(raw, dict):
        return None
    asked = raw.get("question") or raw.get("text") or raw.get("prompt")
    if not isinstance(asked, str) or not asked.strip():
        return None
    q: dict[str, Any] = {"id": str(raw.get("id") or f"q{index}"), "question": asked.strip()}
    for field, *aliases in (("header", "key"), ("detail", "context")):
        for name in (field, *aliases):
            value = raw.get(name)
            if isinstance(value, str) and value.strip():
                q[field] = value.strip()
                break
    options = []
    for opt in raw.get("options") or []:
        if isinstance(opt, str) and opt.strip():
            options.append({"label": opt.strip()})
        elif isinstance(opt, dict) and isinstance(opt.get("label"), str) and opt["label"].strip():
            o: dict[str, Any] = {"label": opt["label"].strip()}
            for key in ("description", "preview"):
                if isinstance(opt.get(key), str) and opt[key].strip():
                    o[key] = opt[key].strip()
            options.append(o)
    if options:
        q["options"] = options
    multi = raw.get("multiSelect", raw.get("multi_select"))
    if multi is not None:
        q["multiSelect"] = bool(multi)
    return q


# --- what the human said -----------------------------------------------------


def normalise_response(body: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the API accepted → what the gated node receives; None when nothing was said.

    ``body`` is ``{"response": str, "answers": [{"id", "question", "selected": [...], "custom": str}]}``
    with every field optional. Answers with neither a selection nor custom
    text are dropped, so an approval with the form left blank is a plain
    approval (``None``), exactly as before.
    """
    if not body:
        return None
    response = body.get("response")
    response = response.strip() if isinstance(response, str) else ""
    answers: list[dict[str, Any]] = []
    for raw in body.get("answers") or []:
        if not isinstance(raw, dict):
            continue
        selected = [s for s in (raw.get("selected") or []) if isinstance(s, str) and s.strip()]
        custom = raw.get("custom")
        custom = custom.strip() if isinstance(custom, str) else ""
        if not selected and not custom:
            continue
        answers.append({
            "id": str(raw.get("id") or f"q{len(answers) + 1}"),
            "question": str(raw.get("question") or "").strip(),
            "selected": selected,
            "custom": custom,
        })
    if not response and not answers:
        return None
    return {"response": response, "answers": answers, "text": render_response_text(answers, response)}


def render_response_text(answers: list[dict[str, Any]], response: str) -> str:
    """The response as prose a task template can paste: Q/A pairs, then the free text."""
    parts: list[str] = []
    for a in answers:
        answer = ", ".join(a["selected"])
        if a["custom"]:
            answer = f"{answer} — {a['custom']}" if answer else a["custom"]
        question = a["question"] or a["id"]
        parts.append(f"Q: {question}\nA: {answer}")
    if response:
        parts.append(response)
    return "\n\n".join(parts)
