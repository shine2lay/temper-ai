"""The scripted members of the Pi rehearsal: what the local stand-in answers, turn by turn.

The stand-in (standin.py) plays the model for real member boxes. It is stateless: every
request carries the whole conversation, so the member, its batch of messages and how far its
turn has got are read from the request itself. Only the framing Temper writes is parsed (the
``[Temper] You are`` line, the ``[temper:<tag>]`` headers and Temper's own message texts);
a member's message body is never acted on.

A scenario is an ordered list of rules. The first rule whose ``when`` matches the turn gives
the turn's steps: one tool call per model call, then a closing text. #54 adds its scenarios
to ``SCENARIOS``; the bundled normal run is ``normal``.

What it logs is metadata only (rule, step, tool name, model, thinking settings, the names of
the tools the request offered), never a prompt, a message body or a token.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

FRAMING = re.compile(r"\[Temper\] You are (?P<name>[^,\n]+), a member of a team working "
                     r"through Temper: (?P<roster>[^\n]+?)\. (?P<leader>[^ \n]+) leads\.")
INTRO = re.compile(r"(?P<mark>\[temper:[0-9a-f]{8}\]) \d+ messages? for you, oldest first\.")
HEADER = re.compile(r"message (?P<i>\d+) of (?P<n>\d+) · id (?P<id>[^ ]+) · from "
                    r"(?P<sender>Temper|the owner|member \"[^\"]*\") · kind (?P<kind>[a-z_]+)"
                    r"(?: · in reply to (?P<reply_to>[^ ]+))?")
REVIEW_REQUEST = re.compile(r"Review (?P<rid>[^ ]+) \(round (?P<round>\d+)\) from ")
VIEWS_IN = re.compile(r"Review (?P<rid>[^ ]+) \(round (?P<round>\d+)\): the views are in "
                      r"\((?P<satisfied>\d+) satisfied, (?P<changes>\d+) changes\)")
DONE_REFUSED = re.compile(r"Done on review (?P<rid>[^ ]+) was refused: ")
REFUSED_RESULT = ("Not sent (", "Not recorded (")
BODY_PREFIX = "| "


@dataclass(frozen=True)
class Message:
    id: str
    sender: str          # "temper", "owner" or the member's name
    kind: str
    reply_to: str | None
    body: str


@dataclass(frozen=True)
class Turn:
    """What one model request says about the member's turn."""
    member: str
    leader: str
    roster: tuple[str, ...]
    batch: tuple[Message, ...]
    step: int                         # model calls already answered in this turn
    last_result_refused: bool         # the previous tool call's result was a refusal
    tools: frozenset[str]
    model: str
    thinking: dict[str, Any]

    @property
    def leads(self) -> bool:
        return self.member == self.leader

    @property
    def others(self) -> list[str]:
        return [m for m in self.roster if m != self.member]

    def kinds(self) -> set[str]:
        return {m.kind for m in self.batch}

    def first(self, kind: str, sender: str | None = None) -> Message | None:
        return next((m for m in self.batch if m.kind == kind
                     and (sender is None or m.sender == sender)), None)

    def review_request(self) -> re.Match[str] | None:
        msg = self.first("review_request", "temper")
        return REVIEW_REQUEST.match(msg.body) if msg else None

    def views_in(self) -> re.Match[str] | None:
        for msg in self.batch:
            if msg.kind == "notice" and msg.sender == "temper":
                hit = VIEWS_IN.match(msg.body)
                if hit:
                    return hit
        return None

    def done_refused(self) -> bool:
        return any(m.sender == "temper" and DONE_REFUSED.match(m.body) for m in self.batch)


@dataclass(frozen=True)
class Step:
    """One model call's answer: a tool call (``tool`` and ``input``) or a closing ``text``.
    ``hold`` names a gate file the stand-in waits for before it answers (the answer's stream
    starts at once and stays alive meanwhile)."""
    tool: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    hold: str = ""


@dataclass(frozen=True)
class Rule:
    name: str
    when: Callable[[Turn], bool]
    steps: Callable[[Turn], list[Step]]


@dataclass(frozen=True)
class Answer:
    rule: str
    step: int
    action: Step
    flag: str = ""           # set when the scenario went off its script (a finding)


class NotATurn(ValueError):
    """The request isn't a member turn the scenario can read."""


# --- reading a request -------------------------------------------------------------------------

def _texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    out = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            out.append(str(block.get("text") or ""))
    return out


def _result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    return "\n".join(_texts(content))


def parse_batch(text: str) -> tuple[Message, ...]:
    hit = INTRO.search(text)
    if hit is None:
        return ()
    mark = hit.group("mark")
    messages: list[Message] = []
    current: dict[str, Any] | None = None
    body: list[str] = []
    for line in text[hit.end():].splitlines():
        if line.startswith(mark + " "):
            if current is not None:
                messages.append(Message(body="\n".join(body), **current))
                current, body = None, []
            head = HEADER.match(line[len(mark) + 1:])
            if head:
                sender = head.group("sender")
                sender = ("temper" if sender == "Temper" else "owner" if sender == "the owner"
                          else sender[len('member "'):-1])
                current = {"id": head.group("id"), "sender": sender, "kind": head.group("kind"),
                           "reply_to": head.group("reply_to")}
        elif current is not None and line.startswith(BODY_PREFIX):
            body.append(line[len(BODY_PREFIX):])
    if current is not None:
        messages.append(Message(body="\n".join(body), **current))
    return tuple(messages)


def turn_effort(request: dict[str, Any]) -> tuple[str, str]:
    """The thinking effort the request asks for this turn, and where it says so.

    For a model with mid-conversation effort (Claude Opus 5.5 in Pi's runtime), pi-ai sends a
    fixed "high" at the top of the request and the member's own effort in a system message
    that closes the conversation (pi-ai's insertThinkingLevelMessages); the closing one is the
    turn's. Other models carry it only at the top."""
    for msg in reversed(request.get("messages") or []):
        if not isinstance(msg, dict) or msg.get("role") != "system":
            break
        effort = (msg.get("output_config") or {}).get("effort") if isinstance(
            msg.get("output_config"), dict) else None
        if effort:
            return str(effort), "closing system message"
    top = request.get("output_config")
    if isinstance(top, dict) and top.get("effort"):
        return str(top["effort"]), "request"
    return "", ""


def read_turn(request: dict[str, Any]) -> Turn:
    """The member's turn from an Anthropic messages request (the whole conversation).

    System messages (pi-ai's effort markers and setting updates) carry no member text, so the
    batch, the step count and the last tool result are read from the others."""
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        raise NotATurn("no messages")
    messages = [m for m in messages if isinstance(m, dict) and m.get("role") != "system"]
    if not messages:
        raise NotATurn("no messages")
    start = None
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") == "user" and any(INTRO.search(t) for t in _texts(msg.get("content"))):
            start = i
            break
    if start is None:
        raise NotATurn("no batch from Temper")
    text = "\n".join(_texts(messages[start].get("content")))
    framing = FRAMING.search(text)
    if framing is None:
        raise NotATurn("no team framing")
    roster = tuple(name.strip() for name in framing.group("roster").split(","))
    step = sum(1 for m in messages[start + 1:] if m.get("role") == "assistant")
    refused = False
    last = messages[-1]
    if step and last.get("role") == "user" and isinstance(last.get("content"), list):
        for block in last["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                refused = refused or bool(block.get("is_error")) or _result_text(block).startswith(
                    REFUSED_RESULT)
    tools = frozenset(str(t.get("name")) for t in request.get("tools") or []
                      if isinstance(t, dict) and t.get("name"))
    thinking = request.get("thinking") if isinstance(request.get("thinking"), dict) else {}
    settings = {k: v for k, v in thinking.items() if k in ("type", "budget_tokens")}
    effort, said_in = turn_effort(request)
    if effort:
        settings["effort"] = effort
        top = request.get("output_config")
        top_effort = top.get("effort") if isinstance(top, dict) else None
        if said_in != "request":
            settings["effort_in"] = said_in
            if top_effort and top_effort != effort:
                settings["request_effort"] = top_effort
    return Turn(member=framing.group("name").strip(), leader=framing.group("leader"),
                roster=roster, batch=parse_batch(text), step=step, last_result_refused=refused,
                tools=tools, model=str(request.get("model") or ""), thinking=settings)


# --- the bundled normal run (#74) ---------------------------------------------------------------
#
# The first trial's team (ADR-M4-22): a leader and four reviewers, pause after round 1.
# Round 1: the leader writes version 1, tells the first reviewer, asks for a review; the first
# reviewer replies and asks for a change, the others are satisfied; the leader keeps going with
# version 2 and the team pauses for the owner. Round 2, after the owner's answer: every
# reviewer is satisfied (the first view waits until the owner's message has reached the team,
# so the run can't end before the page has sent it), and the leader decides done.

OWNER_MESSAGE_GATE = "owner-message"


def first_reviewer(t: Turn) -> str:
    """The first member on the roster who isn't the leader: the one the leader talks to."""
    return next((m for m in t.roster if m != t.leader), "")


def _lead_first(t: Turn) -> list[Step]:
    return [Step("write", {"path": "NOTES.md", "content": "Rehearsal notes, version 1.\n"}),
            Step("send_message", {"to": first_reviewer(t), "kind": "info",
                                  "body": "Version 1 of NOTES.md is ready for your review."}),
            Step("request_review", {"note": "First version of NOTES.md."}),
            Step(text="Version 1 is written and up for review.")]


def _review_round_one(t: Turn) -> list[Step]:
    rr = t.review_request()
    review_id = rr.group("rid") if rr else ""
    if t.member != first_reviewer(t):
        return [Step("give_view", {"review_id": review_id, "verdict": "satisfied",
                                   "note": "Version 1 reads fine to me."}),
                Step(text="My view is in: satisfied.")]
    steps = []
    info = t.first("info", t.leader)
    if info is not None:
        steps.append(Step("send_message", {"kind": "reply", "in_reply_to": info.id,
                                           "body": "Thanks, I'm looking at it now."}))
    steps.append(Step("give_view", {"review_id": review_id, "verdict": "changes",
                                    "note": "Please add a second line saying what it is for."}))
    steps.append(Step(text="My view is in: one change asked."))
    return steps


def _lead_keep_going(t: Turn) -> list[Step]:
    hit = t.views_in()
    return [Step("decide", {"review_id": hit.group("rid") if hit else "",
                            "decision": "keep_going",
                            "summary": "Adding the second line the review asked for."}),
            Step("write", {"path": "NOTES.md", "content": "Rehearsal notes, version 2.\n"
                                                          "It records the bundled normal run.\n"}),
            Step("request_review", {"note": "Second version: the line the review asked for."}),
            Step(text="Version 2 is written and up for review.")]


def _review_later_round(t: Turn) -> list[Step]:
    rr = t.review_request()
    steps = [Step("give_view", {"review_id": rr.group("rid") if rr else "",
                                "verdict": "satisfied", "note": "The second line is there."},
                  hold=OWNER_MESSAGE_GATE)]
    if t.member == first_reviewer(t):
        steps.append(Step("send_message", {"to": t.leader, "kind": "info",
                                           "body": "I'm satisfied with version 2."}))
    steps.append(Step(text="Satisfied with version 2."))
    return steps


def _lead_done(t: Turn) -> list[Step]:
    hit = t.views_in()
    return [Step("decide", {"review_id": hit.group("rid") if hit else "", "decision": "done",
                            "summary": "The reviewed version 2 is the result."}),
            Step(text="Done: version 2 is the result.")]


def _noted(t: Turn) -> list[Step]:
    return [Step(text="Noted.")]


def _views(t: Turn, *, satisfied: bool) -> bool:
    hit = t.views_in()
    if hit is None:
        return False
    all_satisfied = int(hit.group("changes")) == 0 and int(hit.group("satisfied")) > 0
    return all_satisfied if satisfied else not all_satisfied


NORMAL = [
    Rule("lead_first_version", lambda t: t.leads and "goal" in t.kinds(), _lead_first),
    Rule("lead_done", lambda t: t.leads and _views(t, satisfied=True), _lead_done),
    Rule("lead_keep_going", lambda t: t.leads and _views(t, satisfied=False), _lead_keep_going),
    Rule("review_round_one", lambda t: not t.leads and t.review_request() is not None
         and t.review_request().group("round") == "1", _review_round_one),
    Rule("review_later_round", lambda t: not t.leads and t.review_request() is not None,
         _review_later_round),
    Rule("noted", lambda t: True, _noted),
]

SCENARIOS: dict[str, list[Rule]] = {"normal": NORMAL}


def offered_name(turn: Turn, tool: str) -> str:
    """The request's own name for a scenario tool, or "" when the request doesn't offer it.

    Pi's Anthropic client sends its built-in tools under Claude Code's names when it uses an
    OAuth token, as a member box does ("write" goes out as "Write"; pi-ai's toClaudeCodeName),
    and maps a call to that name back to its own tool. So the scenario's names match without
    case, and the call uses the name the request gave."""
    if tool in turn.tools:
        return tool
    return next((t for t in sorted(turn.tools) if t.lower() == tool.lower()), "")


def answer(turn: Turn, rules: list[Rule]) -> Answer:
    """This model call's answer: the matching rule's step for the turn's progress."""
    if turn.done_refused():
        return Answer("done_refused", turn.step, Step(text="Stopping: done was refused."),
                      flag="done_refused")
    if turn.last_result_refused:
        return Answer("tool_refused", turn.step, Step(text="Stopping: a tool call was refused."),
                      flag="tool_refused")
    for rule in rules:
        if rule.when(turn):
            steps = rule.steps(turn)
            if turn.step >= len(steps):
                return Answer(rule.name, turn.step, Step(text="Finished."), flag="extra_call")
            step = steps[turn.step]
            if step.tool:
                name = offered_name(turn, step.tool)
                if not name:
                    return Answer(rule.name, turn.step, Step(text=f"Missing tool {step.tool}."),
                                  flag="tool_missing")
                step = Step(name, step.input, step.text, step.hold)
            return Answer(rule.name, turn.step, step)
    return Answer("no_rule", turn.step, Step(text="No rule."), flag="no_rule")
