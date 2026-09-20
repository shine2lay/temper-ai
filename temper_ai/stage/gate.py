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
from typing import Any

from temper_ai.shared.types import NodeResult

QUESTION_KEYS = ("questions", "questions_for_owner", "questions_for_human")

EMPTY_RESPONSE: dict[str, Any] = {"response": "", "answers": [], "text": ""}


class GateSignal(threading.Event):
    """The in-process handle for one waiting gate.

    ``set()`` releases the node; ``response`` carries what the human said,
    so an in-process approval does not have to round-trip through the
    database to deliver its payload.
    """

    def __init__(self) -> None:
        super().__init__()
        self.response: dict[str, Any] | None = None


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
    """``text`` when the whole of it is one JSON object, else None."""
    stripped = (text or "").strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
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
