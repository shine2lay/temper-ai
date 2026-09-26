"""A question about the repos, answered by the ``repo_answer`` workflow.

Slack asks with ``/temper ask <question>``, or with plain @temper when the
pick decides the message is a question rather than a request to run
something. The workflow reads each repository's capability notes, then the
code, and answers; this module starts it, waits for it, and takes the
answer out of the agent's text.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from temper_ai.integrations.slack.ops import OpsError, TemperOps
from temper_ai.integrations.slack.picker import END, POLL_S, wait_for

ANSWER_WORKFLOW = "repo_answer"
ANSWER_NODE = "answer"
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

    def answer(self, question: str, conversation: str = "") -> Answer:
        execution_id = self.ops.start(ANSWER_WORKFLOW, {"question": question, "conversation": conversation})
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
