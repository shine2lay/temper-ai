"""What temper does with what Slack sends: slash commands, button clicks,
mentions and DMs.

The socket loop acks every envelope at once (Slack wants it within 3 s)
and hands it here on a small thread pool, so a slow command never delays
the next ack. Answers go back through the Web API and response_url.

Anyone in the workspace may act; every action is recorded with who did it
(``store.log_action``).
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from temper_ai.integrations.slack import blocks, store
from temper_ai.integrations.slack.answer import ANSWER_WORKFLOW, Answerer
from temper_ai.integrations.slack.client import SlackClient, SlackError
from temper_ai.integrations.slack.commands import Command, coerce_inputs, parse
from temper_ai.integrations.slack.config import ConfigWatcher
from temper_ai.integrations.slack.notifier import RunPoster, close_gate
from temper_ai.integrations.slack.ops import OpsError, TemperOps
from temper_ai.integrations.slack.picker import Picker, conversation_text

logger = logging.getLogger(__name__)

GOING = ("running", "waiting", "queued")
_MENTION = re.compile(r"<@[UW][A-Z0-9]+(?:\|[^>]*)?>")
SEEN_MAX = 500


class Handler:
    def __init__(self, client: SlackClient, config: ConfigWatcher, ops: TemperOps | None = None,
                 poster: RunPoster | None = None, picker: Picker | None = None, bot_user: str = "",
                 answerer: Answerer | None = None, workers: int = 8) -> None:
        self.client = client
        self.config = config
        self.ops = ops or TemperOps()
        self.poster = poster or RunPoster(client)
        self.picker = picker or Picker(self.ops)
        # An answer holds its thread for a minute or more; there are enough
        # threads that a few questions at once don't hold up the commands.
        self.answerer = answerer or Answerer(self.ops)
        self.bot_user = bot_user
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="slack-handler")
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()
        self.handled = 0
        self.last_error: str | None = None

    # -- entry points ---------------------------------------------------------

    def submit(self, envelope: dict[str, Any]) -> None:
        self._pool.submit(self._safe, envelope)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _safe(self, envelope: dict[str, Any]) -> None:
        try:
            self.handle(envelope)
            self.handled += 1
        except Exception as exc:  # noqa: BLE001 - one bad envelope must not kill the pool thread
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Slack: handling a %s envelope failed", envelope.get("type"))

    def handle(self, envelope: dict[str, Any]) -> None:
        kind = envelope.get("type")
        payload = envelope.get("payload") or {}
        if kind == "slash_commands":
            self.slash(payload)
        elif kind == "interactive" and payload.get("type") == "block_actions":
            self.action(payload)
        elif kind == "events_api":
            event = payload.get("event") or {}
            if self._first_time(str(payload.get("event_id") or "")) and self._first_time(
                    f"{event.get('channel')}:{event.get('ts')}"):
                self.message(event)

    def _first_time(self, key: str) -> bool:
        """False for an envelope Slack sent again (a retry) or a message seen
        twice (a mention in a DM arrives as app_mention and message.im)."""
        if not key or key.endswith(":None"):
            return True
        with self._lock:
            if key in self._seen:
                return False
            self._seen[key] = None
            while len(self._seen) > SEEN_MAX:
                self._seen.popitem(last=False)
            return True

    # -- slash commands ---------------------------------------------------------

    def slash(self, p: dict[str, Any]) -> None:
        user, name = str(p.get("user_id") or ""), str(p.get("user_name") or "")
        channel, url = str(p.get("channel_id") or ""), str(p.get("response_url") or "")

        def reply(message: dict[str, Any]) -> None:
            try:
                self.client.respond(url, {"response_type": "ephemeral", **message})
            except SlackError as exc:
                logger.warning("Slack: could not answer /temper: %s", exc)

        cmd = parse(str(p.get("text") or ""))
        try:
            self._slash(cmd, user, name, channel, reply)
        except OpsError as exc:
            reply({"text": str(exc), "blocks": [blocks.section(f":warning: {blocks.esc(exc)}")]})

    def _slash(self, cmd: Command, user: str, name: str, channel: str, reply: Any) -> None:
        cfg = self.config.get()
        if cmd.error:
            note = f":warning: {cmd.error}"
            if cmd.verb == "help" and cmd.workflow:
                hits = self.ops.search(cmd.workflow, limit=1).get("results") or []
                if hits and hits[0]["name"] == cmd.workflow:
                    note += f" To start it: `/temper run {cmd.workflow} …`"
            reply(blocks.help_message(note))
            return
        if cmd.verb == "help":
            reply(blocks.help_message())
        elif cmd.verb == "list":
            reply(blocks.workflows(self.ops.search(cmd.query, limit=500), "Workflows"))
        elif cmd.verb == "search":
            reply(blocks.workflows(self.ops.search(cmd.query, limit=10), f"Workflows for “{cmd.query}”"))
        elif cmd.verb == "status":
            if cmd.run_id:
                eid = self.ops.resolve(cmd.run_id)
                summary = self.ops.summary(eid)
                if summary.get("error"):
                    raise OpsError(str(summary["error"]))
                reply(blocks.status(summary, cfg.run_url(eid)))
            else:
                going = [r for r in self.ops.recent() if r.get("status") in GOING]
                reply(blocks.recent_runs(going, cfg.run_url))
        elif cmd.verb == "stop":
            eid = self.ops.resolve(cmd.run_id)
            reply({"text": self.stop(eid, user, name)})
        elif cmd.verb == "run":
            self.run(cmd, user, name, channel, reply)
        elif cmd.verb == "ask":
            self.ask(cmd.query, user, name, reply)

    def ask(self, question: str, user: str, name: str, reply: Any) -> None:
        """``/temper ask``: read the code, answer in the channel for everyone there."""
        reply({"text": "Reading the code…", "blocks": [blocks.context(
            f":mag: Reading the code to answer _{blocks.esc(blocks.clip(question, 300))}_ — about a minute.")]})
        store.log_action(user, name, "ask", None, question[:500])
        got = self.answerer.answer(question)
        message = blocks.answer(got.text, got.execution_id, self.config.get().run_url(got.execution_id),
                                got.seconds, got.cost_usd, question=question, by=user)
        reply({**message, "response_type": "in_channel"})

    def run(self, cmd: Command, user: str, name: str, channel: str, reply: Any) -> None:
        entry = next((e for e in self.ops.catalog() if e["name"] == cmd.workflow), None)
        if entry is None:
            hits = self.ops.search(cmd.workflow, limit=5).get("results") or []
            like = ", ".join(f"`{h['name']}`" for h in hits)
            raise OpsError(f"There is no workflow `{cmd.workflow}`." + (f" Did you mean {like}?" if like else ""))
        inputs, problems = coerce_inputs(cmd.inputs, entry.get("inputs") or {})
        if problems:
            reply({"text": "Not started", "blocks": [
                blocks.section(f":warning: Not started: {blocks.esc('; '.join(problems))}"),
                blocks.context(blocks.workflow_line(entry))]})
            return
        if cmd.workflow == ANSWER_WORKFLOW:
            # Its answer is the point, and a run thread would never show it.
            self.ask(str(inputs.get("question") or ""), user, name, reply)
            return
        eid = self.ops.start(cmd.workflow, inputs)
        store.log_action(user, name, "run", eid, f"{cmd.workflow} {json.dumps(inputs)[:500]}")
        where = self.start_thread(eid, cmd.workflow, inputs, user, channel)
        if where != channel:
            reply({"text": f"Started {cmd.workflow} ({eid[:8]}). I can't post in this channel, so its "
                           "thread is in our DM."})

    def start_thread(self, eid: str, workflow: str, inputs: dict[str, Any], user: str, channel: str,
                     ts: str | None = None) -> str:
        """The run's header message, as the thread every notice about it goes to.

        Posted where it was asked for; if temper cannot post there (a DM
        between people, a channel it is not in), in the asker's DM instead.
        ``ts`` turns an existing message (a confirmed proposal) into it.
        Returns the channel the thread is in.
        """
        message = blocks.started(workflow, eid, inputs, user, self.config.get().run_url(eid))
        if ts:
            try:
                self.client.update(channel, ts, message["text"], message["blocks"])
                store.save_thread(eid, channel, ts, origin=True)
                return channel
            except SlackError as exc:
                logger.warning("Slack: could not turn %s/%s into the run header: %s", channel, ts, exc)
        for target in (channel, user):
            try:
                where = self.client.resolve(target)
                answer = self.client.post(where, message["text"], message["blocks"])
                store.save_thread(eid, where, str(answer["ts"]), origin=True)
                return where
            except SlackError as exc:
                logger.info("Slack: can't post the header of %s in %s: %s", eid[:8], target, exc.error)
        return ""

    def stop(self, eid: str, user: str, name: str) -> str:
        summary = self.ops.summary(eid)
        status = summary.get("status")
        if summary.get("error"):
            raise OpsError(str(summary["error"]))
        if status not in GOING:
            return f"{summary.get('workflow')} {eid[:8]} is already {status}."
        self.ops.cancel(eid, f"Stopped in Slack by {name or user}")
        store.log_action(user, name, "stop", eid, str(summary.get("workflow") or ""))
        for channel, ts in store.threads_of(eid):
            try:
                self.client.post(channel, f"Stop requested by <@{user}>.", thread_ts=ts)
            except SlackError as exc:
                logger.warning("Slack: could not note the stop in %s: %s", channel, exc)
        return f"Stopping {summary.get('workflow')} {eid[:8]}."

    # -- buttons -----------------------------------------------------------------

    def action(self, p: dict[str, Any]) -> None:
        acts = p.get("actions") or []
        if not acts:
            return
        act = acts[0]
        action_id = str(act.get("action_id") or "")
        user = str((p.get("user") or {}).get("id") or "")
        name = str((p.get("user") or {}).get("username") or (p.get("user") or {}).get("name") or user)
        container = p.get("container") or {}
        channel = str((p.get("channel") or {}).get("id") or container.get("channel_id") or "")
        message = p.get("message") or {}
        ts = str(container.get("message_ts") or message.get("ts") or "")
        try:
            value = json.loads(act.get("value") or "{}")
        except ValueError:
            value = {}
        if action_id in (blocks.APPROVE, blocks.REJECT, blocks.CONFIRM, blocks.CANCEL, blocks.STOP):
            # Two quick clicks on one message: the second does nothing.
            if not self._first_time(f"click:{channel}:{ts}:{action_id}:{value.get('event', '')}"):
                return
        try:
            if action_id in (blocks.APPROVE, blocks.REJECT):
                self.gate(action_id == blocks.APPROVE, value, user, name, channel, ts, message)
            elif action_id == blocks.STOP:
                text = self.stop(str(value.get("run") or ""), user, name)
                self._decide(channel, ts, message, f":black_square_for_stop: {text} (<@{user}>)")
            elif action_id == blocks.CONFIRM:
                self.confirm(value, user, name, channel, ts, message)
            elif action_id == blocks.CANCEL:
                store.log_action(user, name, "cancel_pick", None, str(value.get("workflow") or ""))
                self._decide(channel, ts, message, f"Cancelled by <@{user}>; nothing was started.")
        except OpsError as exc:
            self._ephemeral(p, f":warning: {exc}")

    def _decide(self, channel: str, ts: str, message: dict[str, Any], line: str) -> None:
        try:
            self.client.update(channel, ts, message.get("text") or line, blocks.decided(message.get("blocks"), line))
        except SlackError as exc:
            logger.warning("Slack: could not update %s/%s: %s", channel, ts, exc)

    def _ephemeral(self, p: dict[str, Any], text: str) -> None:
        url = p.get("response_url")
        if not url:
            return
        try:
            self.client.respond(str(url), {"response_type": "ephemeral", "replace_original": False, "text": text})
        except SlackError as exc:
            logger.warning("Slack: could not answer a click: %s", exc)

    def gate(self, approve: bool, value: dict[str, Any], user: str, name: str, channel: str, ts: str,
             message: dict[str, Any]) -> None:
        eid, node, event_id = str(value.get("run") or ""), str(value.get("node") or ""), value.get("event")
        decision = self.ops.gate_decision(str(event_id)) if event_id else None
        if event_id and decision is not None:
            waiting = decision.get("status") == "waiting"
        else:
            waiting = self.ops.gate_info(eid, node) is not None
        if not waiting:
            data = (decision or {}).get("data") or {}
            verdict = str(data.get("gate_status") or (decision or {}).get("status") or "closed")
            who = data.get("gate_decided_by")
            close_gate(self.client, str(event_id or ""), None, message,
                       f":information_source: Already {verdict}" + (f" by {who}" if who else "")
                       + f"; <@{user}>'s click changed nothing.", verdict, clicked=(channel, ts))
            return
        if approve:
            if self.ops.run_is_alive(eid):
                self.ops.approve(eid, node)
                line, verdict = f":white_check_mark: Approved by <@{user}>", "approved"
            else:
                # After a restart nothing waits on this gate: resuming the
                # run brings it back to the gate, which asks again.
                self.ops.approve(eid, node)
                self.ops.resume(eid)
                line = (f":arrows_counterclockwise: <@{user}> approved, but temper had restarted since this "
                        "gate opened, so the run was resumed instead; it will ask again here.")
                verdict = "resumed"
            store.log_action(user, name, "approve", eid, f"{node} {event_id or ''} {verdict}")
        else:
            self.ops.cancel(eid, f"Rejected in Slack by {name or user}")
            line, verdict = f":no_entry: Rejected by <@{user}>; the run is stopped.", "rejected"
            store.log_action(user, name, "reject", eid, f"{node} {event_id or ''}")
        if event_id:
            self._record_who(str(event_id), f"{name or user} (Slack)")
        close_gate(self.client, str(event_id or ""), None, message, line, verdict, clicked=(channel, ts))

    def _record_who(self, event_id: str, who: str) -> None:
        try:
            from temper_ai.observability.recorder import update_event

            update_event(event_id, data={"gate_decided_by": who})
        except Exception as exc:  # noqa: BLE001 - the decision stands without the name
            logger.warning("Slack: could not record who answered gate %s: %s", event_id, exc)

    def confirm(self, value: dict[str, Any], user: str, name: str, channel: str, ts: str,
                message: dict[str, Any]) -> None:
        workflow = str(value.get("workflow") or "")
        raw = value.get("inputs")
        inputs: dict[str, Any] = raw if isinstance(raw, dict) else {}
        if not any(e["name"] == workflow for e in self.ops.catalog()):
            raise OpsError(f"There is no workflow `{workflow}` any more.")
        eid = self.ops.start(workflow, inputs)
        store.log_action(user, name, "confirm", eid, f"{workflow} {json.dumps(inputs)[:500]}")
        self.start_thread(eid, workflow, inputs, user, channel, ts=ts)

    # -- mentions and DMs -------------------------------------------------------------

    def message(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if event.get("bot_id") or event.get("subtype") or not event.get("user"):
            return
        if self.bot_user and event.get("user") == self.bot_user:
            return
        if kind == "message" and event.get("channel_type") != "im":
            return
        if kind not in ("message", "app_mention"):
            return
        channel, user = str(event.get("channel") or ""), str(event["user"])
        thread = str(event.get("thread_ts") or event.get("ts") or "")
        text = _MENTION.sub("", str(event.get("text") or "")).strip()
        if not text or text.lower() in ("help", "hi", "hello", "?"):
            message = blocks.help_message("Tell me what you want run, in plain words, and I'll suggest a workflow. "
                                          "Or ask what rollcall, roamee or temper-ai can do.")
            self.client.post(channel, message["text"], message["blocks"], thread_ts=thread)
            return
        placeholder = self.client.post(channel, "Looking for the right workflow…", thread_ts=thread)
        pts = str(placeholder.get("ts") or "")
        conversation = ""
        if event.get("thread_ts"):
            try:
                earlier = [m for m in self.client.replies(channel, str(event["thread_ts"]), limit=30)
                           if m.get("ts") not in (event.get("ts"), pts)]
                conversation = conversation_text(earlier, self.bot_user)
            except SlackError as exc:
                logger.info("Slack: could not read the thread for context: %s", exc)
        # A message event carries only the user's id; the log is read by people.
        store.log_action(user, self.client.user_name(user), "pick", None, text[:500])
        try:
            pick = self.picker.pick(text, conversation)
        except OpsError as exc:
            self.client.update(channel, pts, str(exc), [blocks.section(f":warning: {blocks.esc(exc)}")])
            return
        if pick.workflow == ANSWER_WORKFLOW:
            self.answer_in_thread(channel, pts, str(pick.inputs.get("question") or text), conversation)
            return
        if not pick.workflow or pick.question and pick.problems:
            answer = pick.question or "I couldn't find a workflow that does that."
            if pick.workflow:
                answer = f"I'd use *{blocks.esc(pick.workflow)}*, but: {blocks.esc(answer)}"
            else:
                answer = blocks.esc(answer)
            answer += "\n_Reply in this thread with more, and mention me._" if kind == "app_mention" else \
                "\n_Reply in this thread with more._"
            self.client.update(channel, pts, blocks.clip(answer, 300), [blocks.section(answer)])
            return
        entry = next((e for e in self.ops.catalog() if e["name"] == pick.workflow), None)
        proposal = blocks.proposal(pick.workflow, pick.inputs, pick.reason, entry, user, pick.execution_id[:8])
        self.client.update(channel, pts, proposal["text"], proposal["blocks"])

    def answer_in_thread(self, channel: str, ts: str, question: str, conversation: str) -> None:
        """A question in plain words: answered in place of the placeholder, no button to press."""
        self.client.update(channel, ts, "Reading the code…", [
            blocks.context(":mag: That's a question about the code; reading it to answer — about a minute.")])
        try:
            got = self.answerer.answer(question, conversation)
        except OpsError as exc:
            self.client.update(channel, ts, str(exc), [blocks.section(f":warning: {blocks.esc(exc)}")])
            return
        message = blocks.answer(got.text, got.execution_id, self.config.get().run_url(got.execution_id),
                                got.seconds, got.cost_usd)
        self.client.update(channel, ts, message["text"], message["blocks"])
