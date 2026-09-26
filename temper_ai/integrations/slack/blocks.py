"""The Slack messages temper posts, as Block Kit.

Every message also carries a plain ``text``: Slack shows it in
notifications and wherever blocks cannot be drawn.

Limits kept in mind: a section's text is at most 3000 characters, a
button's ``value`` at most 2000, a message at most 50 blocks.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

SECTION_MAX = 2900
VALUE_MAX = 1900

STATUS_EMOJI = {
    "running": ":arrow_forward:",
    "waiting": ":double_vertical_bar:",
    "completed": ":white_check_mark:",
    "failed": ":x:",
    "cancelled": ":black_square_for_stop:",
    "interrupted": ":warning:",
    "queued": ":hourglass_flowing_sand:",
}

# action_id of every button temper puts in a message.
APPROVE = "gate_approve"
REJECT = "gate_reject"
STOP = "run_stop"
CONFIRM = "pick_confirm"
CANCEL = "pick_cancel"


def esc(text: Any) -> str:
    """Text shown as-is in mrkdwn (Slack's three control characters escaped)."""
    return str(text if text is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clip(text: Any, limit: int) -> str:
    s = str(text if text is not None else "")
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def short(execution_id: str | None) -> str:
    return (execution_id or "")[:8]


def when(moment: Any) -> str:
    """A moment shown in each reader's own time zone.

    Slack's date token does the converting; the UTC text after the ``|``
    is what shows wherever Slack cannot draw it (notifications, old clients).
    temper stores times as UTC, with or without the offset.
    """
    text = str(moment or "")
    if not text:
        return ""
    try:
        at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return esc(text[:16].replace("T", " "))
    at = at if at.tzinfo else at.replace(tzinfo=UTC)
    fallback = at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"<!date^{int(at.timestamp())}^{{date_short_pretty}} {{time}}|{fallback}>"


def duration(seconds: Any) -> str:
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    if s < 1:
        return "under 1s"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def cost(usd: Any) -> str:
    try:
        v = float(usd)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""  # a run with no model calls: "$0.00" is noise
    return f"${v:.2f}" if v >= 0.01 else f"${v:.4f}"


def run_ref(execution_id: str, url: str = "") -> str:
    """``abcd1234`` as a link to the run when the dashboard is known."""
    code = f"`{short(execution_id)}`"
    return f"<{url}|{code}>" if url else code


def section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": clip(text, SECTION_MAX) or " "}}


def context(text: str) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": clip(text, SECTION_MAX) or " "}]}


def button(text: str, action_id: str, value: dict[str, Any] | str = "", style: str | None = None,
           url: str | None = None, confirm: dict[str, Any] | None = None) -> dict[str, Any]:
    b: dict[str, Any] = {"type": "button", "text": {"type": "plain_text", "text": text, "emoji": True},
                         "action_id": action_id}
    if value:
        b["value"] = clip(value if isinstance(value, str) else json.dumps(value, separators=(",", ":")), VALUE_MAX)
    if style:
        b["style"] = style
    if url:
        b["url"] = url
    if confirm:
        b["confirm"] = confirm
    return b


def confirm_dialog(title: str, text: str, yes: str) -> dict[str, Any]:
    return {"title": {"type": "plain_text", "text": clip(title, 100)},
            "text": {"type": "mrkdwn", "text": clip(text, 300)},
            "confirm": {"type": "plain_text", "text": yes},
            "deny": {"type": "plain_text", "text": "Never mind"}}


def inputs_text(inputs: dict[str, Any] | None, limit: int = 600) -> str:
    if not inputs:
        return "_no inputs_"
    parts = []
    for key, value in inputs.items():
        shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        parts.append(f"`{esc(key)}` = {esc(clip(shown, 200))}")
    return clip("\n".join(parts), limit)


def open_button(url: str) -> list[dict[str, Any]]:
    return [button("Open in temper", "open_run", url=url)] if url else []


# -- run notices ----------------------------------------------------------------


def run_header(workflow: str, execution_id: str, url: str = "") -> str:
    return f"*{esc(workflow)}* {run_ref(execution_id, url)}"


def started(workflow: str, execution_id: str, inputs: dict[str, Any] | None, by: str, url: str = "") -> dict[str, Any]:
    text = f"Started {workflow} ({short(execution_id)}) for {by}"
    blocks = [
        section(f"{STATUS_EMOJI['running']} {run_header(workflow, execution_id, url)} started by <@{by}>"),
        context(inputs_text(inputs)),
    ]
    if url:
        blocks.append({"type": "actions", "elements": open_button(url)})
    return {"text": text, "blocks": blocks}


def gate(run: dict[str, Any], gate_info: dict[str, Any], url: str = "") -> dict[str, Any]:
    """A gate is waiting: what it is about, and Approve / Reject."""
    workflow = str(run.get("workflow") or run.get("workflow_name") or "?")
    execution_id = str(run.get("id") or run.get("execution_id") or "")
    node = str(gate_info.get("node_name") or "?")
    text = f"{workflow} ({short(execution_id)}) is waiting for approval at {node}"
    blocks: list[dict[str, Any]] = [section(
        f"{STATUS_EMOJI['waiting']} {run_header(workflow, execution_id, url)} {WAITING_PHRASE} "
        f"*{esc(node)}*")]
    for up in (gate_info.get("upstream") or [])[:3]:
        name = up.get("name") or up.get("node") or "previous step"
        body = up.get("output") if isinstance(up, dict) else up
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, indent=1)
        if body:
            blocks.append(section(f"*{esc(name)}* said:\n>{esc(clip(body, 1400)).replace(chr(10), chr(10) + '>')}"))
    questions = gate_info.get("questions") or []
    if questions:
        blocks.append(context(
            f":question: It asks {len(questions)} question(s). To answer them, open the run in temper; "
            "Approve here sends no answers."))
    value = {"run": execution_id, "node": node, "event": gate_info.get("event_id")}
    elements = [
        button("Approve", APPROVE, value, style="primary"),
        button("Reject", REJECT, value, style="danger",
               confirm=confirm_dialog("Reject?", f"This stops the {esc(workflow)} run.", "Reject and stop")),
    ] + open_button(url)
    blocks.append({"type": "actions", "block_id": f"gate:{short(execution_id)}:{node}"[:255], "elements": elements})
    return {"text": text, "blocks": blocks}


WAITING_PHRASE = "is waiting for your OK before"


def decided(blocks: list[dict[str, Any]] | None, line: str, verdict: str = "") -> list[dict[str, Any]]:
    """The message's blocks with its buttons replaced by what was decided,
    and a gate's "is waiting" header turned into the past tense, so an
    answered gate never still reads as waiting."""
    kept = [b for b in (blocks or []) if b.get("type") != "actions"]
    if kept and verdict:
        first = kept[0]
        text = ((first.get("text") or {}).get("text")) or ""
        if WAITING_PHRASE in text:
            emoji = {"approved": ":white_check_mark:", "rejected": ":x:"}.get(verdict, ":ballot_box_with_check:")
            text = text.replace(STATUS_EMOJI["waiting"], emoji, 1).replace(WAITING_PHRASE, "was waiting for an OK before")
            kept[0] = {**first, "text": {**first["text"], "text": text}}
    return kept + [context(line)]


def stuck(run: dict[str, Any], idle_minutes: int, last_event_at: str, where: list[str], url: str = "") -> dict[str, Any]:
    workflow = str(run.get("workflow") or run.get("workflow_name") or "?")
    execution_id = str(run.get("id") or "")
    text = f"{workflow} ({short(execution_id)}) has been quiet for {idle_minutes} min"
    at = f" in *{esc(', '.join(where))}*" if where else ""
    blocks = [section(
        f":warning: {run_header(workflow, execution_id, url)} has had no new event for "
        f"*{idle_minutes} min*{at} (status {esc(run.get('status'))}, last event {when(last_event_at)})."),
        {"type": "actions", "elements": [
            button("Stop run", STOP, {"run": execution_id}, style="danger",
                   confirm=confirm_dialog("Stop this run?", f"{esc(workflow)} {short(execution_id)} will be cancelled.",
                                          "Stop it")),
        ] + open_button(url)},
    ]
    return {"text": text, "blocks": blocks}


def ended(summary: dict[str, Any], url: str = "") -> dict[str, Any]:
    """A run finished: completed, cancelled, interrupted or failed."""
    workflow = str(summary.get("workflow") or "?")
    execution_id = str(summary.get("execution_id") or "")
    status = str(summary.get("status") or "?")
    bits = [b for b in (duration(summary.get("duration_seconds")), cost(summary.get("total_cost_usd"))) if b]
    took = f" after {', '.join(bits)}" if bits else ""
    emoji = STATUS_EMOJI.get(status, ":grey_question:")
    text = f"{workflow} ({short(execution_id)}) {status}{took}"
    blocks = [section(f"{emoji} {run_header(workflow, execution_id, url)} *{esc(status)}*{took}")]
    stopped = summary.get("stopped_by")
    reason = summary.get("failure_summary")
    if stopped:
        # Who stopped it says why it ended; the killed step's error adds nothing.
        blocks.append(context(f":raised_hand: {stopped}"))
    elif reason:
        blocks.append(section(f">{esc(clip(reason, 1500))}"))
    shown = output_gist(summary.get("output")) if status == "completed" else ""
    if shown:
        blocks.append(context(esc(shown)))
    return {"text": text, "blocks": blocks}


# The fields of a structured output that hold a sentence written for a person.
READABLE_KEYS = ("summary", "message", "result", "answer", "reply", "text")
# A readable field inside JSON text; its value may run to the end, cut short.
_READABLE_FIELD = re.compile(r'"(' + "|".join(READABLE_KEYS) + r')"\s*:\s*"((?:[^"\\]|\\.)*)("?)')
# What temper's clipping appends to text it cut (temper_ai/mcp/tools.py _clip).
_TRUNCATED_NOTE = re.compile(r"\s*\[truncated \d+ more characters[^\]]*\]\s*$")


def output_gist(output: Any, limit: int = 600) -> str:
    """What a finished notice shows of a run's output: its words, never raw JSON.

    Plain text shows as it is. A structured output -- a dict, or a JSON
    document that arrives as text, cut short or not -- shows its summary-like
    field when it has one, and nothing otherwise: the whole output is one
    click away in temper.
    """
    if isinstance(output, str):
        text = output.strip()
        if not text.startswith(("{", "[")):
            return clip(text, limit)
        try:
            output = json.loads(text)
        except ValueError:
            # JSON cut short on the way here: its summary is usually near the top.
            found = _READABLE_FIELD.search(_TRUNCATED_NOTE.sub("", text))
            if not found:
                return ""
            words = _unescape(found.group(2)).strip()
            cut = not found.group(3)
            return clip(words + ("…" if cut and words else ""), limit)
    if isinstance(output, dict):
        for key in READABLE_KEYS:
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return clip(value.strip(), limit)
    return ""


def _unescape(raw: str) -> str:
    """A JSON string's body as text, even when it was cut mid-escape."""
    for end in (len(raw), len(raw) - 1, len(raw) - 5):
        try:
            return json.loads(f'"{raw[:max(end, 0)]}"')
        except ValueError:
            continue
    return raw


# -- answers to commands ------------------------------------------------------------


def status(summary: dict[str, Any], url: str = "") -> dict[str, Any]:
    workflow = str(summary.get("workflow") or "?")
    execution_id = str(summary.get("execution_id") or "")
    st = str(summary.get("status") or "?")
    bits = [b for b in (duration(summary.get("duration_seconds")), cost(summary.get("total_cost_usd"))) if b]
    lines = [f"{STATUS_EMOJI.get(st, ':grey_question:')} {run_header(workflow, execution_id, url)} *{esc(st)}*"
             + (f" · {', '.join(bits)}" if bits else "")]
    nodes = summary.get("nodes") or []
    active = [n.get("name") for n in _walk(nodes) if n.get("status") in ("running", "waiting")]
    if active:
        lines.append(f"now at: {esc(', '.join(str(a) for a in active[:6]))}")
    done = sum(1 for n in _walk(nodes) if n.get("status") == "completed")
    if nodes:
        lines.append(f"{done} of {len(list(_walk(nodes)))} steps done")
    if summary.get("failure_summary"):
        lines.append(f">{esc(clip(summary['failure_summary'], 800))}")
    return {"text": f"{workflow} {short(execution_id)} {st}", "blocks": [section("\n".join(lines))]}


def _walk(nodes: list[dict[str, Any]]):
    for n in nodes or []:
        yield n
        yield from _walk(n.get("children") or n.get("child_nodes") or [])


def recent_runs(runs: list[dict[str, Any]], dashboard: Any = None) -> dict[str, Any]:
    if not runs:
        return {"text": "No runs going.", "blocks": [section("No runs are going right now.")]}
    lines = []
    for r in runs[:15]:
        st = str(r.get("status") or "?")
        url = dashboard(r["id"]) if dashboard else ""
        lines.append(f"{STATUS_EMOJI.get(st, '')} {run_header(str(r.get('workflow_name') or '?'), r['id'], url)} "
                     f"{esc(st)} · started {when(r.get('start_time'))}")
    return {"text": f"{len(runs)} runs", "blocks": [section("\n".join(lines))]}


def gist(description: Any, limit: int = 160) -> str:
    """A description's opening, whole words only: YAML block descriptions
    wrap mid-sentence, so their first line alone stops at a random word."""
    flat = " ".join(str(description or "").split())
    if len(flat) <= limit:
        return flat
    end = flat.find(". ", 40, limit)
    if end > 0:
        return flat[: end + 1]
    return flat[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def workflow_line(entry: dict[str, Any]) -> str:
    desc = gist(entry.get("description"))
    first = esc(desc) if desc else "_no description_"
    inputs = entry.get("inputs") or {}
    req = [k for k, v in inputs.items() if (v or {}).get("required")]
    opt = [k for k in inputs if k not in req]
    shape = ""
    if inputs:
        shape = " · inputs: " + ", ".join([f"`{esc(k)}`" for k in req] + [f"`{esc(k)}`?" for k in opt])
    return f"*{esc(entry.get('name'))}* — {first}{shape}"


def workflows(result: dict[str, Any], title: str) -> dict[str, Any]:
    results = result.get("results") or []
    total = result.get("total", len(results))
    if not results:
        return {"text": title, "blocks": [section(f"{title}\nNothing matched.")]}
    blocks = [section(f"*{esc(title)}*" + (f" (showing {len(results)} of {total})" if total > len(results) else ""))]
    chunk: list[str] = []
    size = 0
    for entry in results:
        line = workflow_line(entry)
        if size + len(line) > SECTION_MAX - 100 and chunk:
            blocks.append(section("\n".join(chunk)))
            chunk, size = [], 0
        chunk.append(line)
        size += len(line) + 1
    if chunk:
        blocks.append(section("\n".join(chunk)))
    undescribed = result.get("undescribed") or []
    if undescribed:
        blocks.append(context(f"{len(undescribed)} workflow(s) have no description, so only their name finds them: "
                              + esc(clip(", ".join(undescribed), 800))))
    return {"text": title, "blocks": blocks[:49]}


def proposal(workflow: str, inputs: dict[str, Any], reason: str, entry: dict[str, Any] | None,
             requester: str, pick_id: str = "") -> dict[str, Any]:
    text = f"Start {workflow}?"
    lines = [f":mag: I'd run *{esc(workflow)}*" + (f" — {esc(clip(reason, 300))}" if reason else "")]
    if entry and entry.get("description"):
        lines.append(f"_{esc(gist(entry['description'], 200))}_")
    blocks = [section("\n".join(lines)), section("*Inputs*\n" + inputs_text(inputs, 1500))]
    value = {"workflow": workflow, "inputs": inputs, "by": requester, "pick": pick_id}
    raw = json.dumps(value, separators=(",", ":"))
    if len(raw) > VALUE_MAX:
        blocks.append(context(":warning: These inputs are too long to carry on a button; start it with /temper run."))
        return {"text": text, "blocks": blocks}
    blocks.append({"type": "actions", "elements": [
        button("Start it", CONFIRM, raw, style="primary"),
        button("Cancel", CANCEL, raw),
    ]})
    return {"text": text, "blocks": blocks}


# An answer longer than this many sections is cut; the run page has it all.
ANSWER_SECTIONS = 12


def chunks(text: str, size: int = SECTION_MAX) -> list[str]:
    """``text`` in pieces of at most ``size``, cut between paragraphs where it can."""
    out: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        while len(para) > size:  # one paragraph too long for a section
            cut = para.rfind("\n", 0, size)
            cut = cut if cut > size // 2 else size
            if current:
                out.append(current)
                current = ""
            out.append(para[:cut])
            para = para[cut:].lstrip("\n")
        joined = f"{current}\n\n{para}" if current else para
        if len(joined) > size:
            out.append(current)
            current = para
        else:
            current = joined
    if current.strip():
        out.append(current)
    return [c for c in out if c.strip()]


def answer(text: str, execution_id: str, url: str = "", seconds: Any = None, usd: Any = None,
           question: str = "", by: str = "") -> dict[str, Any]:
    """An answer about the repos: who asked what, the answer, what it took.

    The answer is the model's text, so it is escaped: it can't ping
    ``<!channel>`` or anyone else.
    """
    first = next((line.strip(" *_") for line in text.splitlines() if line.strip(" *_")), "")
    blocks: list[dict[str, Any]] = []
    if question:
        asker = f"<@{by}> asked" if by else "Asked"
        blocks.append(context(f":mag: {asker}: _{esc(clip(question, 500))}_"))
    pieces = chunks(esc(text))
    if len(pieces) > ANSWER_SECTIONS:
        pieces = pieces[:ANSWER_SECTIONS]
        pieces[-1] += "\n_(cut short here; the whole answer is on the run's page)_"
    blocks.extend(section(p) for p in pieces)
    bits = [b for b in (duration(seconds), cost(usd)) if b]
    blocks.append(context(f"Read the code in {run_ref(execution_id, url)}" + (f" · {' · '.join(bits)}" if bits else "")))
    return {"text": clip(esc(first) or "An answer about the code", 300), "blocks": blocks}


HELP = (
    "*/temper* — talk to temper without opening it\n"
    "• `/temper ask <question>` — what rollcall, roamee or temper-ai can do, and where in the code; "
    "I read the code and answer here\n"
    "• `/temper search <words>` — find a workflow by what it does\n"
    "• `/temper list` — every workflow, with its inputs\n"
    "• `/temper run <workflow> key=value …` — start a run; I post a thread for it\n"
    "• `/temper status [run id]` — one run, or the runs going now\n"
    "• `/temper stop <run id>` — cancel a run\n"
    "Or just say what you want: `@temper grade the plan for b022` (or DM me). "
    "I pick a workflow and ask before starting it. A question about the code gets an answer: "
    "`@temper can roamee export a trip?`\n"
    "Values with spaces go in quotes: `topic=\"weekly summary\"`. A run id can be its first 8 characters."
)


def help_message(note: str = "") -> dict[str, Any]:
    blocks = ([section(note)] if note else []) + [section(HELP)]
    return {"text": note or "How to use /temper", "blocks": blocks}
