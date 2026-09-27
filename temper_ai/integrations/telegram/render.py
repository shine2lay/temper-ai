"""The Telegram messages temper sends, as HTML text plus inline buttons.

Telegram's HTML allows only a few tags (b, i, u, s, code, pre, a,
blockquote, tg-spoiler); everything else must have <, > and & escaped.
A message is at most 4096 characters, a button's data at most 64 bytes.
Times are shown in the zone from configs/telegram (Telegram cannot show a
moment in each reader's own zone the way Slack does).
"""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from temper_ai.integrations.notify.notice import Decision, Notice
from temper_ai.integrations.slack.blocks import (
    clip,
    cost,
    duration,
    gist,
    output_gist,
    short,
)

TEXT_MAX = 4000        # a little under Telegram's 4096, for the parts added later
LABEL_MAX = 40         # a button's label, before Telegram cuts it itself

STATUS_EMOJI = {
    "running": "▶️", "waiting": "⏸", "completed": "✅", "failed": "❌", "cancelled": "⏹",
    "interrupted": "⚠️", "queued": "⏳",
}


def esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""), quote=False)


def when(moment: Any, zone: str) -> str:
    """"3:45 PM PDT, Sep 26" in the configured zone."""
    text = str(moment or "")
    if not text:
        return ""
    try:
        at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return esc(text[:16].replace("T", " "))
    at = (at if at.tzinfo else at.replace(tzinfo=UTC)).astimezone(ZoneInfo(zone))
    return at.strftime("%-I:%M %p %Z, %b %-d")


def run_header(workflow: str, execution_id: str, url: str = "") -> str:
    ref = f'<a href="{esc(url)}">{short(execution_id)}</a>' if url else f"<code>{short(execution_id)}</code>"
    return f"<b>{esc(workflow)}</b> ({ref})"


def button(text: str, data: str) -> dict[str, Any]:
    assert len(data.encode()) <= 64, data
    return {"text": clip(text, LABEL_MAX), "callback_data": data}


def link_button(text: str, url: str) -> dict[str, Any]:
    return {"text": text, "url": url}


def _fit(text: str) -> str:
    """Cut a finished HTML message that is too long at a line break (never
    inside a tag: every tag temper writes opens and closes on one line)."""
    if len(text) <= TEXT_MAX:
        return text
    cut = text.rfind("\n", 0, TEXT_MAX - 40)
    return text[: cut if cut > 0 else TEXT_MAX - 40] + "\n<i>(cut short; the rest is in temper)</i>"


# -- questions ---------------------------------------------------------------------


def _options(q: dict[str, Any]) -> list[dict[str, Any]]:
    return [o for o in (q.get("options") or []) if isinstance(o, dict) and o.get("label")][:20]


def _upstream(upstream: list[Any]) -> list[str]:
    lines = []
    for up in upstream[:3]:
        name = (up.get("name") or up.get("node") or "previous step") if isinstance(up, dict) else "previous step"
        body = up.get("output") if isinstance(up, dict) else up
        words = output_gist(body, 700) if isinstance(body, (dict, str)) else ""
        if not words and isinstance(body, str):
            words = clip(body, 700)
        if words:
            lines.append(f"<blockquote expandable><b>{esc(name)}</b> said: {esc(words)}</blockquote>")
    return lines


def answer_text(a: dict[str, Any] | None) -> str:
    if not a:
        return ""
    return ", ".join(x for x in (", ".join(a.get("selected") or []), str(a.get("custom") or "").strip()) if x)


def question_text(notice: Notice, zone: str, state: dict[str, Any] | None = None,
                  decision: Decision | None = None) -> str:
    """A waiting gate: what it is about, its questions and the answers so far;
    once answered, who answered and how."""
    state = state or {}
    answers = state.get("answers") or {}
    current = int(state.get("i") or 0)
    if decision is None:
        head = f"{STATUS_EMOJI['waiting']} {run_header(notice.workflow, notice.execution_id, notice.url)} " \
               f"is waiting for your OK before <b>{esc(notice.node)}</b>."
    else:
        emoji = {"approved": "✅", "rejected": "⛔", "resumed": "🔄"}.get(decision.verdict, "☑️")
        head = f"{emoji} {run_header(notice.workflow, notice.execution_id, notice.url)} " \
               f"was waiting for an OK before <b>{esc(notice.node)}</b>."
    lines = [head]
    if notice.nudged_after_min and decision is None:
        lines.insert(0, f"🔔 Nobody has answered this for {notice.nudged_after_min} min.")
    lines += _upstream(notice.upstream)
    for i, q in enumerate(notice.questions):
        qid = str(q.get("id") or f"q{i + 1}")
        marker = "👉" if decision is None and i == current and len(notice.questions) > 1 else "❓"
        header = f"<b>{esc(q.get('header'))}:</b> " if q.get("header") else ""
        kind = " <i>(pick any)</i>" if q.get("multiSelect") and _options(q) else ""
        lines.append(f"\n{marker} {i + 1}/{len(notice.questions)} {header}{esc(clip(q.get('question'), 600))}{kind}")
        if q.get("detail"):
            lines.append(f"<i>{esc(clip(q.get('detail'), 400))}</i>")
        opts = _options(q)
        if opts and decision is None and i == current:
            for o in opts:
                if o.get("description"):
                    lines.append(f"• <b>{esc(clip(o['label'], 80))}</b>: {esc(clip(o['description'], 160))}")
        given = answer_text(answers.get(qid))
        if decision is not None and decision.answers:
            given = next((a for qq, a in decision.answers if qq == str(q.get("question") or qid)), given)
        if given:
            lines.append(f"   ✏️ <b>{esc(clip(given, 500))}</b>")
    if decision is not None:
        lines.append(f"\n{esc(decision.line())}" + (f": {esc(clip(decision.reason, 300))}" if decision.reason
                                                   and decision.verdict in ("approved", "rejected") else ""))
    elif state.get("confirm_reject"):
        lines.append("\n⛔ Reject stops the run. Sure?")
    elif notice.questions:
        lines.append("\n<i>Tap the choices below, or reply to this message to type an answer; "
                     "then Approve.</i>")
    return _fit("\n".join(lines))


def question_keyboard(copy_id: int, notice: Notice, state: dict[str, Any] | None = None) -> list[list[dict]]:
    state = state or {}
    rows: list[list[dict]] = []
    p = f"q:{copy_id}"
    if state.get("confirm_reject"):
        return [[button("⛔ Yes, reject and stop it", f"{p}:rr"), button("Back", f"{p}:rx")]]
    questions = notice.questions
    if questions:
        i = min(int(state.get("i") or 0), len(questions) - 1)
        q = questions[i]
        qid = str(q.get("id") or f"q{i + 1}")
        chosen = set((state.get("answers") or {}).get(qid, {}).get("selected") or [])
        multi = bool(q.get("multiSelect"))
        for n, o in enumerate(_options(q)):
            label = str(o["label"])
            mark = ("☑️ " if label in chosen else "⬜ ") if multi else ("🔘 " if label in chosen else "")
            rows.append([button(mark + label, f"{p}:{'t' if multi else 'o'}:{i}:{n}")])
        nav = [button("✏️ Type an answer", f"{p}:y:{i}")]
        if i > 0:
            nav.insert(0, button("◀ Back", f"{p}:b:{i}"))
        if i < len(questions) - 1:
            nav.append(button("Next ▶", f"{p}:n:{i}"))
        rows.append(nav)
    rows.append([button("✅ Approve", f"{p}:a"), button("⛔ Reject", f"{p}:r")])
    if notice.url:
        rows.append([link_button("Open in temper", notice.url)])
    return rows


# -- other notices -------------------------------------------------------------------


def stuck_text(notice: Notice, zone: str, ended: str = "") -> str:
    head = run_header(notice.workflow, notice.execution_id, notice.url)
    if ended:
        return f"{STATUS_EMOJI.get(ended, '☑️')} {head} went quiet for a while; it has since ended " \
               f"(<b>{esc(ended)}</b>)."
    at = f" in <b>{esc(', '.join(notice.active_nodes))}</b>" if notice.active_nodes else ""
    return f"⚠️ {head} has had no new event for <b>{notice.idle_min} min</b>{at} " \
           f"(last event {esc(when(notice.last_at, zone))})."


def stuck_keyboard(copy_id: int, notice: Notice, confirm: bool = False) -> list[list[dict]]:
    if confirm:
        return [[button("⏹ Yes, stop it", f"s:{copy_id}:y"), button("No", f"s:{copy_id}:n")]]
    rows = [[button("⏹ Stop run", f"s:{copy_id}")]]
    if notice.url:
        rows[0].append(link_button("Open in temper", notice.url))
    return rows


def ended_text(notice: Notice, zone: str) -> str:
    s = notice.summary
    status = str(s.get("status") or notice.status or "?")
    bits = [b for b in (duration(s.get("duration_seconds")), cost(s.get("total_cost_usd"))) if b]
    took = f" after {', '.join(bits)}" if bits else ""
    lines = [f"{STATUS_EMOJI.get(status, '❔')} {run_header(notice.workflow, notice.execution_id, notice.url)} "
             f"<b>{esc(status)}</b>{took}"]
    stopped = notice.stopped_by or s.get("stopped_by")
    if stopped:
        lines.append(f"✋ {esc(stopped)}")
    elif s.get("failure_summary"):
        lines.append(f"<blockquote>{esc(clip(s['failure_summary'], 1500))}</blockquote>")
    shown = output_gist(s.get("output")) if status == "completed" else ""
    if shown:
        lines.append(esc(shown))
    return _fit("\n".join(lines))


def render(notice: Notice, zone: str) -> str:
    if notice.kind == "question":
        return question_text(notice, zone)
    if notice.kind == "stuck":
        return stuck_text(notice, zone)
    return ended_text(notice, zone)


# -- answers to commands ---------------------------------------------------------------


HELP = (
    "<b>Temper</b>: talk to temper without opening it\n"
    "• /ask &lt;question&gt;: what rollcall, roamee or temper-ai can do, and where in the code, or what the Notion pages say\n"
    "• /search &lt;words&gt;: find a workflow by what it does\n"
    "• /list: every workflow, with its inputs\n"
    "• /run &lt;workflow&gt; key=value …: start a run; its notices reply to its first message\n"
    "• /status [run id]: one run, or the runs going now\n"
    "• /stop &lt;run id&gt;: cancel a run\n"
    "Or just say what you want (in a group: mention me or reply to me). I pick a workflow and ask "
    "before starting it. Values with spaces go in quotes: <code>topic=\"weekly summary\"</code>. "
    "A run id can be its first 8 characters."
)


def started_text(workflow: str, execution_id: str, inputs: dict[str, Any], by: str, url: str = "") -> str:
    shown = inputs_text(inputs, 1200)
    return _fit(f"▶️ {run_header(workflow, execution_id, url)} started by {esc(by)}.\n"
                f"{shown}\nIts questions and notices come here, as replies to this message.")


def inputs_text(inputs: dict[str, Any], limit: int = 1500) -> str:
    if not inputs:
        return "<i>no inputs</i>"
    lines = []
    for k, v in inputs.items():
        value = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        lines.append(f"• <code>{esc(k)}</code> = {esc(clip(value, 300))}")
    return clip("\n".join(lines), limit)


def proposal_text(workflow: str, inputs: dict[str, Any], reason: str, entry: dict[str, Any] | None) -> str:
    lines = [f"🔎 I'd run <b>{esc(workflow)}</b>" + (f": {esc(clip(reason, 300))}" if reason else "")]
    if entry and entry.get("description"):
        lines.append(f"<i>{esc(gist(entry['description'], 200))}</i>")
    lines.append("<b>Inputs</b>\n" + inputs_text(inputs))
    return _fit("\n".join(lines))


def status_text(summary: dict[str, Any], url: str = "") -> str:
    workflow = str(summary.get("workflow") or "?")
    eid = str(summary.get("execution_id") or "")
    st = str(summary.get("status") or "?")
    bits = [b for b in (duration(summary.get("duration_seconds")), cost(summary.get("total_cost_usd"))) if b]
    lines = [f"{STATUS_EMOJI.get(st, '❔')} {run_header(workflow, eid, url)} <b>{esc(st)}</b>"
             + (f" · {', '.join(bits)}" if bits else "")]
    nodes = list(_walk(summary.get("nodes") or []))
    active = [str(n.get("name")) for n in nodes if n.get("status") in ("running", "waiting")]
    if active:
        lines.append(f"now at: {esc(', '.join(active[:6]))}")
    if nodes:
        lines.append(f"{sum(1 for n in nodes if n.get('status') == 'completed')} of {len(nodes)} steps done")
    if summary.get("failure_summary"):
        lines.append(f"<blockquote>{esc(clip(summary['failure_summary'], 800))}</blockquote>")
    return "\n".join(lines)


def _walk(nodes: list[dict[str, Any]]):
    for n in nodes or []:
        yield n
        yield from _walk(n.get("children") or n.get("child_nodes") or [])


def recent_text(runs: list[dict[str, Any]], zone: str, url_of: Any = None) -> str:
    if not runs:
        return "No runs are going right now."
    lines = []
    for r in runs[:15]:
        st = str(r.get("status") or "?")
        url = url_of(r["id"]) if url_of else ""
        lines.append(f"{STATUS_EMOJI.get(st, '')} {run_header(str(r.get('workflow_name') or '?'), r['id'], url)} "
                     f"{esc(st)} · started {esc(when(r.get('start_time'), zone))}")
    return "\n".join(lines)


def workflows_text(result: dict[str, Any], title: str) -> list[str]:
    """One or more messages listing workflows."""
    results = result.get("results") or []
    total = result.get("total", len(results))
    if not results:
        return [f"<b>{esc(title)}</b>\nNothing matched."]
    head = f"<b>{esc(title)}</b>" + (f" (showing {len(results)} of {total})" if total > len(results) else "")
    messages, current = [], head
    for entry in results:
        desc = gist(entry.get("description"))
        inputs = entry.get("inputs") or {}
        req = [k for k, v in inputs.items() if (v or {}).get("required")]
        opt = [k for k in inputs if k not in req]
        shape = (" · inputs: " + ", ".join([f"<code>{esc(k)}</code>" for k in req]
                                          + [f"<code>{esc(k)}</code>?" for k in opt])) if inputs else ""
        line = f"• <b>{esc(entry.get('name'))}</b>: {esc(desc) if desc else '<i>no description</i>'}{shape}"
        if len(current) + len(line) + 1 > TEXT_MAX:
            messages.append(current)
            current = line
        else:
            current += "\n" + line
    messages.append(current)
    return messages[:5]


_FENCE = re.compile(r"```\n?(.*?)```", re.S)
_CODE = re.compile(r"`([^`\n]+)`")
_STAR = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")


def mrkdwn(text: str) -> str:
    """Slack-style text (what temper's answers and messages are written
    in) as Telegram HTML: ```blocks```, `code` and *bold*."""
    parts = []
    last = 0
    for m in _FENCE.finditer(text):
        parts.append(_inline(text[last:m.start()]))
        parts.append(f"<pre>{esc(m.group(1).rstrip())}</pre>")
        last = m.end()
    parts.append(_inline(text[last:]))
    return "".join(parts)


def _inline(text: str) -> str:
    out = []
    last = 0
    for m in _CODE.finditer(text):
        out.append(_STAR.sub(r"<b>\1</b>", esc(text[last:m.start()])))
        out.append(f"<code>{esc(m.group(1))}</code>")
        last = m.end()
    out.append(_STAR.sub(r"<b>\1</b>", esc(text[last:])))
    return "".join(out)


def note(text: Any) -> str:
    """A message written for Slack (an error, a hint) as Telegram HTML:
    ``/temper run`` is ``/run`` here."""
    return mrkdwn(str(text).replace("/temper ", "/"))


def _pieces(text: str, limit: int) -> list[str]:
    """Raw text cut at line breaks into pieces of at most ``limit``; a
    ```block``` cut in two is closed and reopened, so each piece stands alone."""
    pieces: list[str] = []
    while text:
        if len(text) <= limit:
            pieces.append(text)
            break
        cut = text.rfind("\n", limit // 2, limit)
        cut = cut if cut > 0 else limit
        pieces.append(text[:cut])
        text = text[cut:].lstrip("\n")
    for i in range(len(pieces) - 1):
        if pieces[i].count("```") % 2:
            pieces[i] += "\n```"
            pieces[i + 1] = "```\n" + pieces[i + 1]
    return pieces


def answer_texts(text: str, execution_id: str, url: str = "", seconds: Any = None, usd: Any = None,
                 question: str = "") -> list[str]:
    """An answer about the code, in as many messages as it takes (at most 4)."""
    # Escaping and tags make a piece longer: cut the raw text well short.
    pieces = [mrkdwn(p) for p in _pieces(str(text or ""), 3000)]
    if len(pieces) > 4:
        pieces = pieces[:4]
        pieces[-1] += "\n<i>(cut short here; the whole answer is on the run's page)</i>"
    bits = [b for b in (duration(seconds), cost(usd)) if b]
    ref = f'<a href="{esc(url)}">{short(execution_id)}</a>' if url else f"<code>{short(execution_id)}</code>"
    foot = f"\n\n<i>Read the code in {ref}" + (f" · {' · '.join(bits)}" if bits else "") + "</i>"
    if question:
        pieces[0] = f"🔎 <i>{esc(clip(question, 300))}</i>\n\n" + pieces[0]
    if len(pieces[-1]) + len(foot) <= 4096:
        pieces[-1] += foot
    else:
        pieces.append(foot.strip())
    return pieces or [foot.strip()]
