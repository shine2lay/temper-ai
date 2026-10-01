"""A question about the repos, answered by the ``repo_answer`` workflow —
or, when it is about roamee, by ``roamee_answer``.

Slack asks with ``/temper ask <question>``, or with plain @temper when the
pick decides the message is a question rather than a request to run
something. The workflow reads each repository's capability notes, then the
code, and answers; this module starts it, waits for it, and takes the
answer out of the agent's text.

Roamee has its own answerer, because a question about roamee is often not
about its code at all: whether staging is up, what is in its database, what
is open on GitHub and in Linear. ``roamee_answer`` reads the same copy of
the repository and has three read-only tools besides (docs/roamee.md).
:func:`workflow_for` decides between the two, and it is the same decision
from either way in: ``/temper ask`` and plain words both come through here.
``repo_answer`` stays the name the access rules and the interpreter know —
it is the door; which answerer walks through it is this module's business.
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from temper_ai.integrations.slack.access import AccessWatcher, repos_named
from temper_ai.integrations.slack.ops import OpsError, TemperOps
from temper_ai.integrations.slack.picker import END, POLL_S, wait_for

ANSWER_WORKFLOW = "repo_answer"
ROAMEE_WORKFLOW = "roamee_answer"
ANSWER_NODE = "answer"
ROAMEE = "roamee"
# The agent may read for up to 5 minutes; the copies can take a minute more.
ANSWER_TIMEOUT_S = 420.0

_ANSWER = re.compile(r"<answer>(.*?)</answer>", re.S | re.I)
_OPEN = re.compile(r"<answer>", re.I)
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_FENCE_LANG = re.compile(r"^```[A-Za-z0-9_+.-]+[ \t]*$", re.M)


def extract(raw: str) -> str:
    """The answer, out of the agent's text, in Slack's formatting.

    The agent puts its answer between ``<answer>`` tags; what comes before
    them ("That's enough to answer.") is it thinking aloud. Markdown it
    slips in anyway becomes Slack's: ``**bold**`` -> ``*bold*``, a heading
    -> a bold line, ``[text](url)`` -> ``text (url)``.
    """
    text = str(raw or "")
    found = _ANSWER.findall(text)
    if found:
        text = found[-1]
    else:
        opened = list(_OPEN.finditer(text))
        if opened:  # cut off before the closing tag
            text = text[opened[-1].end():]
    text = _BOLD.sub(r"*\1*", text)
    text = _HEADING.sub(lambda m: "*" + m.group(1).strip("* ") + "*", text)
    text = _LINK.sub(r"\1 (\2)", text)
    text = _FENCE_LANG.sub("```", text)
    return text.strip()


def workflow_for(question: str, conversation: str = "", repos: Sequence[str] = ()) -> str:
    """Which answerer takes this question: roamee's, or the one for every repo.

    Roamee's, when the asker may only ask about roamee (their role says so,
    e.g. the roamee role), or when the words name roamee and no other
    repository. A question that names two repositories, or none, goes to
    ``repo_answer``, which can look in all of them.
    """
    wanted = tuple(str(r).strip().lower() for r in repos if str(r).strip())
    if wanted == (ROAMEE,):
        return ROAMEE_WORKFLOW
    known = wanted or tuple(known_repositories())
    named = repos_named(f"{question}\n{conversation}", known)
    return ROAMEE_WORKFLOW if named == (ROAMEE,) else ANSWER_WORKFLOW


# One watcher for the routing decision; it re-reads the file only when it changes.
_repositories = AccessWatcher()


def known_repositories() -> tuple[str, ...]:
    """Every repository temper answers about, from the access config."""
    try:
        return tuple(_repositories.get().repositories) or ("rollcall", ROAMEE, "temper-ai")
    except Exception:  # noqa: BLE001 - no access file, or it could not be read
        return ("rollcall", ROAMEE, "temper-ai")


@dataclass
class Answer:
    text: str
    execution_id: str
    seconds: Any = None
    cost_usd: Any = None


class Answerer:
    def __init__(self, ops: TemperOps | None = None, timeout_s: float = ANSWER_TIMEOUT_S,
                 poll_s: float = POLL_S, sleep: Any = time.sleep) -> None:
        self.ops = ops or TemperOps()
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self._sleep = sleep

    def answer(self, question: str, conversation: str = "", repos: Sequence[str] = ()) -> Answer:
        """Answer one question. ``repos`` narrows which repositories temper
        will even tell the answerer about (the asker's role says which);
        empty means every repository it keeps a copy of."""
        inputs: dict[str, Any] = {"question": question, "conversation": conversation}
        workflow = workflow_for(question, conversation, repos)
        if repos and workflow == ANSWER_WORKFLOW:
            # roamee_answer has no repos input: it is roamee's and only roamee's.
            inputs["repos"] = ",".join(repos)
        execution_id = self.ops.start(workflow, inputs)
        ref = execution_id[:8]
        summary = wait_for(self.ops, execution_id, self.timeout_s, self.poll_s, self._sleep)
        status = str(summary.get("status") or "running")
        if status not in END:
            try:
                self.ops.cancel(execution_id, "Answering in Slack took too long")
            except OpsError:
                pass
            raise OpsError(f"Reading the code took more than {int(self.timeout_s // 60)} minutes, "
                           f"so I stopped (run {ref}).")
        if status != "completed":
            why = str(summary.get("failure_summary") or "").strip()
            raise OpsError(f"I couldn't answer that: run {ref} {status}" + (f" ({why})" if why else "") + ".")
        text = extract(self.ops.agent_output(execution_id, ANSWER_NODE))
        if not text:
            raise OpsError(f"I read the code but came back without an answer (run {ref}).")
        return Answer(text, execution_id, summary.get("duration_seconds"), summary.get("total_cost_usd"))
