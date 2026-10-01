"""What temper does with what Telegram sends: commands, plain messages,
button presses, typed answers, and being added to (or removed from) chats.

Who may use the bot (configs/telegram): its owners' private chats, and
groups an owner added it to (or that the config names, or an owner is in).
Everyone else gets no answer; a group someone else added it to is left at
once. Both are recorded, so ``temper telegram check`` can show them.

In a group the bot only reads commands, messages that mention it and
replies to its own messages (it is told everything, but ignores the rest).
Anyone in an allowed group may act; every action is recorded with who did
it (``store.log_action``).

Every update is saved in the event inbox before the poller moves on
(poller.py), and handled from there (``handle_saved``): if handling fails or
a restart cuts it off, the inbox tries again.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from temper_ai.integrations.inbox import service as inbox
from temper_ai.integrations.inbox.store import Event
from temper_ai.integrations.notify import service as notify
from temper_ai.integrations.notify import store as notify_store
from temper_ai.integrations.notify.config import ConfigWatcher as NotifyWatcher
from temper_ai.integrations.notify.loop import question_notice
from temper_ai.integrations.notify.notice import Copy, Decision, Notice
from temper_ai.integrations.slack.answer import (
    ANSWER_WORKFLOW,
    ROAMEE_WORKFLOW,
    Answerer,
)
from temper_ai.integrations.slack.commands import Command, coerce_inputs, parse
from temper_ai.integrations.slack.ops import OpsError, TemperOps
from temper_ai.integrations.slack.picker import Picker
from temper_ai.integrations.telegram import render, store
from temper_ai.integrations.telegram.client import TelegramClient, TelegramError
from temper_ai.integrations.telegram.config import ConfigWatcher
from temper_ai.integrations.telegram.render import clip, esc
from temper_ai.integrations.telegram.sender import TelegramSender, split_ref

logger = logging.getLogger(__name__)

GOING = ("running", "waiting", "queued")
MEMBER = ("creator", "administrator", "member", "restricted")
GROUPS = ("group", "supergroup")
SEEN_MAX = 500
SOURCE = "telegram"
HI = ("help", "hi", "hello", "hey", "?", "start")

# What the bot's command menu shows (setMyCommands).
COMMANDS = [
    ("ask", "What rollcall, roamee or temper-ai can do"),
    ("search", "Find a workflow by what it does"),
    ("list", "Every workflow"),
    ("run", "Start a run: /run <workflow> key=value"),
    ("status", "One run, or the runs going now"),
    ("stop", "Cancel a run: /stop <run id>"),
    ("help", "What I can do"),
]


def describe(update: dict[str, Any]) -> tuple[str, str]:
    """(kind, chat) of an update, for the inbox: ("message /run", "-100123")."""
    for kind in ("message", "callback_query", "my_chat_member"):
        part = update.get(kind)
        if isinstance(part, dict):
            msg = part.get("message") if kind == "callback_query" else part
            chat = str(((msg or {}).get("chat") or {}).get("id") or "")
            text = str(part.get("text") or "") if kind == "message" else ""
            word = text.split(maxsplit=1)[0] if text.startswith("/") else ""
            return (f"{kind} {word}".strip(), chat)
    return ("update", "")


def display_name(user: dict[str, Any] | None) -> str:
    user = user or {}
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x).strip()
    return name or (f"@{user['username']}" if user.get("username") else str(user.get("id") or "someone"))


def mention(user: dict[str, Any]) -> str:
    """The person's name as a link to them: in a group, a reply prompt then
    goes to them alone."""
    return f'<a href="tg://user?id={int(user.get("id") or 0)}">{esc(display_name(user))}</a>'


class Handler:
    def __init__(self, client: TelegramClient, config: ConfigWatcher, ops: TemperOps | None = None,
                 picker: Picker | None = None, answerer: Answerer | None = None,
                 bot: dict[str, Any] | None = None, notify_config: NotifyWatcher | None = None,
                 sender: TelegramSender | None = None, workers: int = 8) -> None:
        self.client = client
        self.config = config
        self.ops = ops or TemperOps()
        self.picker = picker or Picker(self.ops)
        self.answerer = answerer or Answerer(self.ops)
        self.bot = bot or {}
        self.bot_id = int(self.bot.get("id") or 0)
        self.username = str(self.bot.get("username") or "")
        self.notify_config = notify_config or NotifyWatcher()
        self.sender = sender or TelegramSender(client, config)
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="telegram-handler")
        self._seen: OrderedDict[str, int | None] = OrderedDict()
        self._lock = threading.Lock()
        self._copy_locks: dict[int, threading.Lock] = {}
        self.handled = 0
        self.last_error: str | None = None

    # -- entry points ---------------------------------------------------------------

    def submit(self, item: dict[str, Any] | int) -> None:
        """Handle an update: its inbox event id once saved, or the update itself."""
        if isinstance(item, int):
            self._pool.submit(self._process_saved, item)
        else:
            self._pool.submit(self._safe, item)

    def _process_saved(self, event_id: int) -> None:
        try:
            inbox.process(event_id)
        except Exception:  # noqa: BLE001 - e.g. the database blinked; the inbox's sweeper tries again
            logger.exception("Telegram: event %s could not be handled", event_id)

    def handle_saved(self, event: Event) -> str:
        """The inbox's handler for Telegram; raises if it failed, to be tried again."""
        try:
            self.handle(event.payload)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise
        self.handled += 1
        return f"handled {describe(event.payload)[0]}"

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _safe(self, update: dict[str, Any]) -> None:
        try:
            self.handle(update)
            self.handled += 1
        except Exception as exc:  # noqa: BLE001 - one bad update must not kill the pool thread
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Telegram: handling update %s failed", update.get("update_id"))

    def handle(self, update: dict[str, Any]) -> None:
        if not self._first_time(str(update.get("update_id", ""))):
            return
        if "my_chat_member" in update:
            self.membership(update["my_chat_member"])
        elif "message" in update:
            self.message(update["message"])
        elif "callback_query" in update:
            self.press(update["callback_query"])

    def _first_time(self, key: str) -> bool:
        """False for something seen before, but True again for the inbox
        retrying the same event."""
        if not key:
            return True
        me = inbox.current_event_id()
        with self._lock:
            if key in self._seen:
                return me is not None and self._seen[key] == me
            self._seen[key] = me
            while len(self._seen) > SEEN_MAX:
                self._seen.popitem(last=False)
            return True

    def _copy_lock(self, copy_id: int) -> threading.Lock:
        with self._lock:
            return self._copy_locks.setdefault(copy_id, threading.Lock())

    # -- who may use the bot -------------------------------------------------------------

    def allowed(self, chat: dict[str, Any], user: dict[str, Any] | None) -> bool:
        cfg = self.config.get()
        chat_id = int(chat.get("id") or 0)
        kind = str(chat.get("type") or "")
        title = str(chat.get("title") or display_name(user))
        if kind == "private":
            if chat_id in cfg.owners:
                return True
            store.save_chat(chat_id, type=kind, title=title, status="refused", tried=True,
                            detail=f"{display_name(user)} wrote to the bot; not an owner")
            logger.info("Telegram: ignored a private chat with %s (%s): not an owner", display_name(user), chat_id)
            return False
        if kind not in GROUPS:
            return False
        if chat_id in cfg.groups:
            return True
        known = store.chat(chat_id)
        if known and known["status"] == "allowed":
            return True
        owner = self._owner_in(chat_id)
        if owner:
            store.save_chat(chat_id, type=kind, title=title, status="allowed", added_by=None,
                            detail=f"an owner ({owner}) is in it")
            return True
        self._leave(chat, "no owner added the bot or is in the group")
        return False

    def _owner_in(self, chat_id: int) -> str:
        for owner in sorted(self.config.get().owners):
            try:
                member = self.client.get_chat_member(chat_id, owner)
            except TelegramError as exc:
                logger.info("Telegram: could not check %s in %s: %s", owner, chat_id, exc)
                continue
            if member.get("status") in MEMBER:
                return display_name(member.get("user")) or str(owner)
        return ""

    def _leave(self, chat: dict[str, Any], why: str) -> None:
        chat_id = int(chat.get("id") or 0)
        try:
            self.client.leave_chat(chat_id)
        except TelegramError as exc:
            logger.info("Telegram: could not leave %s: %s", chat_id, exc)
        store.save_chat(chat_id, type=str(chat.get("type") or ""), title=str(chat.get("title") or ""),
                        status="left", tried=True, detail=why)
        store.log_action("", "", "leave", None, why, chat_id=chat_id)
        logger.warning("Telegram: left %s (%s): %s", chat.get("title") or chat_id, chat_id, why)

    def membership(self, m: dict[str, Any]) -> None:
        """The bot was added to, removed from, or changed in a chat."""
        chat = m.get("chat") or {}
        chat_id = int(chat.get("id") or 0)
        by = m.get("from") or {}
        old = str((m.get("old_chat_member") or {}).get("status") or "")
        new = str((m.get("new_chat_member") or {}).get("status") or "")
        cfg = self.config.get()
        if chat.get("type") == "private":
            status = ("allowed" if chat_id in cfg.owners else "refused") if new in MEMBER else "left"
            store.save_chat(chat_id, type="private", title=display_name(by), status=status)
            return
        if chat.get("type") not in GROUPS:
            return
        if new in ("left", "kicked"):
            store.save_chat(chat_id, type=str(chat.get("type")), title=str(chat.get("title") or ""),
                            status="left", detail=f"removed by {display_name(by)}")
            store.log_action(by.get("id", ""), display_name(by), "removed", None, str(chat.get("title") or ""),
                             chat_id=chat_id)
            return
        if new not in MEMBER or old in MEMBER:
            return  # a change while it stays in (made admin, ...)
        if int(by.get("id") or 0) in cfg.owners or chat_id in cfg.groups:
            store.save_chat(chat_id, type=str(chat.get("type")), title=str(chat.get("title") or ""),
                            status="allowed", added_by=display_name(by), detail="added by an owner")
            store.log_action(by.get("id", ""), display_name(by), "added", None, str(chat.get("title") or ""),
                             chat_id=chat_id)
            try:
                self.client.send(chat_id, "👋 Hi, I'm temper. Send /help to see what I can do; mention me "
                                          "or reply to me to ask in plain words.", quiet=True)
            except TelegramError as exc:
                logger.info("Telegram: could not say hello in %s: %s", chat_id, exc)
            return
        self._leave(chat, f"added by {display_name(by)} ({by.get('id')}), who is not an owner")

    # -- messages ----------------------------------------------------------------------

    def message(self, msg: dict[str, Any]) -> None:
        chat = msg.get("chat") or {}
        chat_id = int(chat.get("id") or 0)
        if msg.get("migrate_to_chat_id"):
            store.move_chat(chat_id, int(msg["migrate_to_chat_id"]))
            return
        user = msg.get("from") or {}
        if not user or user.get("is_bot"):
            return
        text = str(msg.get("text") or "").strip()
        if not text:
            return
        group = chat.get("type") in GROUPS
        earlier = msg.get("reply_to_message") or {}
        to_me = bool(self.bot_id) and int((earlier.get("from") or {}).get("id") or 0) == self.bot_id
        command = text.startswith("/")
        if command:
            head = text.split(None, 1)[0]
            if "@" in head and head.split("@", 1)[1].lower() != self.username.lower():
                return  # another bot's command
        mentioned = bool(self.username) and f"@{self.username.lower()}" in text.lower()
        if group and not (command or mentioned or to_me):
            return
        if not self.allowed(chat, user):
            return
        if to_me and not command:
            found = self._question_for_reply(chat_id, int(earlier.get("message_id") or 0))
            if found is not None:
                self.typed(found, text, msg, user)
                return
        try:
            if command:
                self.command(text, msg, user)
            else:
                plain = re.sub(rf"@{re.escape(self.username)}\b", "", text, flags=re.I).strip() if self.username \
                    else text
                self.plain(plain, msg, user, earlier if to_me else None)
        except OpsError as exc:
            self.reply(msg, f"⚠️ {render.note(exc)}")

    def reply(self, msg: dict[str, Any], text: str, keyboard: list[list[dict[str, Any]]] | None = None,
              quiet: bool = False) -> dict[str, Any]:
        return self.client.send(int(msg["chat"]["id"]), text, reply_to=int(msg.get("message_id") or 0) or None,
                                keyboard=keyboard, quiet=quiet)

    def _edit(self, chat_id: int, message_id: int, text: str,
              keyboard: list[list[dict[str, Any]]] | None = None) -> None:
        try:
            self.client.edit_text(chat_id, message_id, text, keyboard)
        except TelegramError as exc:
            logger.warning("Telegram: could not update %s/%s: %s", chat_id, message_id, exc)

    # -- commands ----------------------------------------------------------------------

    def command(self, text: str, msg: dict[str, Any], user: dict[str, Any]) -> None:
        head, _, rest = text.partition(" ") if " " in text.split("\n", 1)[0] else text.partition("\n")
        verb = head[1:].split("@", 1)[0].lower()
        if verb in ("start", ""):
            verb = "help"
        cmd = parse(f"{verb} {rest}".strip())
        cfg = self.notify_config.get()
        if cmd.error:
            hint = render.note(cmd.error)
            self.reply(msg, f"⚠️ {hint}\n\n{render.HELP}")
            return
        if cmd.verb == "help":
            self.reply(msg, render.HELP)
        elif cmd.verb in ("list", "search"):
            limit, title = (500, "Workflows") if cmd.verb == "list" else (10, f"Workflows for “{cmd.query}”")
            for piece in render.workflows_text(self.ops.search(cmd.query, limit=limit), title):
                self.reply(msg, piece, quiet=True)
        elif cmd.verb == "status":
            if cmd.run_id:
                eid = self.ops.resolve(cmd.run_id)
                summary = self.ops.summary(eid)
                if summary.get("error"):
                    raise OpsError(str(summary["error"]))
                self.reply(msg, render.status_text(summary, cfg.run_url(eid)))
            else:
                going = [r for r in self.ops.recent() if r.get("status") in GOING]
                self.reply(msg, render.recent_text(going, self.config.get().zone, cfg.run_url))
        elif cmd.verb == "stop":
            self.reply(msg, esc(self.stop(self.ops.resolve(cmd.run_id), user, (msg.get("chat") or {}).get("id", ""))))
        elif cmd.verb == "run":
            self.run(cmd, msg, user)
        elif cmd.verb == "ask":
            self.ask(cmd.query, msg, user)

    def run(self, cmd: Command, msg: dict[str, Any], user: dict[str, Any]) -> None:
        entry = next((e for e in self.ops.catalog() if e["name"] == cmd.workflow), None)
        if entry is None:
            hits = self.ops.search(cmd.workflow, limit=5).get("results") or []
            like = ", ".join(f"`{h['name']}`" for h in hits)
            raise OpsError(f"There is no workflow `{cmd.workflow}`." + (f" Did you mean {like}?" if like else ""))
        inputs, problems = coerce_inputs(cmd.inputs, entry.get("inputs") or {})
        if problems:
            self.reply(msg, f"⚠️ Not started: {render.note('; '.join(problems))}")
            return
        if cmd.workflow in (ANSWER_WORKFLOW, ROAMEE_WORKFLOW):
            self.ask(str(inputs.get("question") or ""), msg, user)
            return
        who = display_name(user)
        eid = self.ops.start(cmd.workflow, inputs)
        chat_id = int(msg["chat"]["id"])
        store.log_action(user.get("id", ""), who, "run", eid, f"{cmd.workflow} {json.dumps(inputs)[:500]}",
                         chat_id=chat_id)
        sent = self.reply(msg, render.started_text(cmd.workflow, eid, inputs, who,
                                                   self.notify_config.get().run_url(eid)))
        if sent.get("message_id"):
            store.save_thread(eid, chat_id, int(sent["message_id"]), origin=True)

    def ask(self, question: str, msg: dict[str, Any], user: dict[str, Any], conversation: str = "",
            placeholder: dict[str, Any] | None = None) -> None:
        """A question about the code: answered in the chat."""
        chat_id = int(msg["chat"]["id"])
        text = f"🔎 Reading the code to answer <i>{esc(clip(question, 300))}</i>, about a minute."
        if placeholder:
            self._edit(chat_id, int(placeholder["message_id"]), text)
        else:
            placeholder = self.reply(msg, text, quiet=True)
        store.log_action(user.get("id", ""), display_name(user), "ask", None, question[:500], chat_id=chat_id)
        try:
            got = self.answerer.answer(question, conversation)
        except OpsError as exc:
            self._edit(chat_id, int(placeholder["message_id"]), f"⚠️ {render.note(exc)}")
            return
        pieces = render.answer_texts(got.text, got.execution_id, self.notify_config.get().run_url(got.execution_id),
                                     got.seconds, got.cost_usd, question=question)
        self._edit(chat_id, int(placeholder["message_id"]), pieces[0])
        for piece in pieces[1:]:
            self.client.send(chat_id, piece, reply_to=int(placeholder["message_id"]))

    def stop(self, eid: str, user: dict[str, Any], chat_id: Any = "") -> str:
        summary = self.ops.summary(eid)
        if summary.get("error"):
            raise OpsError(str(summary["error"]))
        status = summary.get("status")
        if status not in GOING:
            return f"{summary.get('workflow')} {eid[:8]} is already {status}."
        who = display_name(user)
        self.ops.cancel(eid, f"Stopped in Telegram by {who}", by=f"{who} (Telegram)")
        store.log_action(user.get("id", ""), who, "stop", eid, str(summary.get("workflow") or ""), chat_id=chat_id)
        return f"Stopping {summary.get('workflow')} {eid[:8]}."

    # -- plain words ---------------------------------------------------------------------

    def plain(self, text: str, msg: dict[str, Any], user: dict[str, Any], earlier: dict[str, Any] | None) -> None:
        """Plain words: suggest a workflow (with a Start button), or answer a
        question about the code. Nothing starts without the press."""
        if not text or text.lower().strip("!./ ") in HI:
            self.reply(msg, "Tell me what you want run, in plain words, and I'll suggest a workflow. "
                            "Or ask what rollcall, roamee or temper-ai can do.\n\n" + render.HELP)
            return
        chat_id = int(msg["chat"]["id"])
        placeholder = self.reply(msg, "🔎 Looking for the right workflow…", quiet=True)
        pid_message = int(placeholder.get("message_id") or 0)
        conversation = f"temper: {earlier.get('text')}" if earlier and earlier.get("text") else ""
        who = display_name(user)
        store.log_action(user.get("id", ""), who, "pick", None, text[:500], chat_id=chat_id)
        try:
            pick = self.picker.pick(text, conversation)
        except OpsError as exc:
            self._edit(chat_id, pid_message, f"⚠️ {render.note(exc)}")
            return
        if pick.workflow in (ANSWER_WORKFLOW, ROAMEE_WORKFLOW):
            self.ask(str(pick.inputs.get("question") or text), msg, user, conversation, placeholder)
            return
        if not pick.workflow or pick.question and pick.problems:
            answer = render.note(pick.question or "I couldn't find a workflow that does that.")
            if pick.workflow:
                answer = f"I'd use <b>{esc(pick.workflow)}</b>, but: {answer}"
            self._edit(chat_id, pid_message, f"{answer}\n<i>Reply to this message with more.</i>")
            return
        entry = next((e for e in self.ops.catalog() if e["name"] == pick.workflow), None)
        pid = store.add_pending(chat_id, {"workflow": pick.workflow, "inputs": pick.inputs, "by": who,
                                          "by_id": user.get("id"), "reason": pick.reason,
                                          "pick": pick.execution_id})
        store.set_pending_message(pid, pid_message)
        self._edit(chat_id, pid_message, render.proposal_text(pick.workflow, pick.inputs, pick.reason, entry),
                   [[render.button("▶️ Start", f"p:{pid}:s"), render.button("Cancel", f"p:{pid}:c")]])

    # -- button presses --------------------------------------------------------------------

    def press(self, cq: dict[str, Any]) -> None:
        msg = cq.get("message") or {}
        chat = msg.get("chat") or {}
        user = cq.get("from") or {}
        data = str(cq.get("data") or "")
        if not chat or not self.allowed(chat, user):
            self.client.answer_callback(str(cq.get("id") or ""), "Not allowed here.")
            return
        parts = data.split(":")
        note, alert = "", False
        try:
            if parts[0] == "p" and len(parts) == 3:
                note = self.proposal_press(int(parts[1]), parts[2], msg, user)
            elif parts[0] == "q" and len(parts) >= 3:
                note = self.question_press(int(parts[1]), parts[2:], msg, user)
            elif parts[0] == "s" and len(parts) >= 2:
                note = self.stuck_press(int(parts[1]), parts[2:], msg, user)
        except OpsError as exc:
            note, alert = f"⚠️ {exc}", True
        except (ValueError, IndexError):
            note = "That button is out of date."
        self.client.answer_callback(str(cq.get("id") or ""), note, alert)

    def proposal_press(self, pid: int, action: str, msg: dict[str, Any], user: dict[str, Any]) -> str:
        chat_id, message_id = int(msg["chat"]["id"]), int(msg.get("message_id") or 0)
        p = store.pending(pid)
        if p is None or p["chat_id"] != chat_id:
            return "This suggestion is gone."
        data = p["data"]
        workflow = str(data.get("workflow") or "")
        raw = data.get("inputs")
        inputs: dict[str, Any] = raw if isinstance(raw, dict) else {}
        who = display_name(user)
        if action == "c":
            if not store.settle_pending(pid, "cancelled"):
                return "Already handled."
            store.log_action(user.get("id", ""), who, "cancel_pick", None, workflow, chat_id=chat_id)
            self._edit(chat_id, message_id, render.proposal_text(workflow, inputs, str(data.get("reason") or ""), None)
                       + f"\n\n✖️ Cancelled by {esc(who)}; nothing was started.")
            return "Cancelled"
        if action != "s":
            return ""
        if not any(e["name"] == workflow for e in self.ops.catalog()):
            raise OpsError(f"There is no workflow {workflow} any more.")
        if not store.settle_pending(pid, "started"):
            return "Already started."
        eid = self.ops.start(workflow, inputs)
        store.log_action(user.get("id", ""), who, "confirm", eid, f"{workflow} {json.dumps(inputs)[:500]}",
                         chat_id=chat_id)
        self._edit(chat_id, message_id, render.started_text(workflow, eid, inputs, who,
                                                             self.notify_config.get().run_url(eid)))
        store.save_thread(eid, chat_id, message_id, origin=True)
        return "Started"

    def stuck_press(self, copy_id: int, parts: list[str], msg: dict[str, Any], user: dict[str, Any]) -> str:
        chat_id, message_id = int(msg["chat"]["id"]), int(msg.get("message_id") or 0)
        copy = notify_store.get(copy_id)
        if copy is None or split_ref(copy.ref) != (chat_id, message_id):
            return "That button is out of date."
        notice = Notice(kind="stuck", execution_id=copy.execution_id,
                        url=self.notify_config.get().run_url(copy.execution_id))
        if not parts:
            self.client.edit_markup(chat_id, message_id, render.stuck_keyboard(copy.id, notice, confirm=True))
            return "Stop this run?"
        if parts[0] == "n":
            self.client.edit_markup(chat_id, message_id, render.stuck_keyboard(copy.id, notice))
            return ""
        text = self.stop(copy.execution_id, user, chat_id)
        notify_store.mark(copy.id, "closed", only_from=notify_store.OPEN, detail=f"stopped by {display_name(user)}")
        body = str(msg.get("text") or "")
        self._edit(chat_id, message_id, f"{esc(body)}\n\n⏹ {esc(text)} ({esc(display_name(user))})",
                   [[render.link_button("Open in temper", notice.url)]] if notice.url else [])
        return "Stopping"

    # -- questions ---------------------------------------------------------------------------

    def _question(self, copy: Copy) -> tuple[Notice | None, bool, dict[str, Any] | None]:
        """The question as it stands now: (notice, still waiting, gate event)."""
        raw = self.ops.gate_decision(copy.event_id) if copy.event_id else None
        if raw is None:
            return None, False, None
        workflow = ""
        try:
            workflow = str(self.ops.summary(copy.execution_id).get("workflow") or "")
        except Exception:  # noqa: BLE001 - only the header's name is lost
            pass
        notice = question_notice(self.notify_config.get(), copy.execution_id, workflow,
                                 {"id": copy.event_id, "data": raw.get("data") or {}})
        return notice, raw.get("status") == "waiting", raw

    def _question_for_reply(self, chat_id: int, message_id: int) -> Copy | None:
        """The question a reply is for: the question message itself, or a
        "type your answer" prompt it sent."""
        if not message_id:
            return None
        found = notify_store.by_ref("telegram", f"{chat_id}:{message_id}")
        if found is not None and found.kind == "question":
            return found
        for c in notify_store.copies(kind="question", via="telegram"):
            where = split_ref(c.ref)
            if where and where[0] == chat_id and str(message_id) in ((c.state or {}).get("prompts") or {}):
                return c
        return None

    def question_press(self, copy_id: int, parts: list[str], msg: dict[str, Any], user: dict[str, Any]) -> str:
        chat_id, message_id = int(msg["chat"]["id"]), int(msg.get("message_id") or 0)
        with self._copy_lock(copy_id):
            copy = notify_store.get(copy_id)
            if copy is None or split_ref(copy.ref) != (chat_id, message_id):
                return "That button is out of date."
            if copy.status not in notify_store.OPEN:
                return "This was already answered."
            notice, waiting, raw = self._question(copy)
            if notice is None or not waiting:
                decision = Decision.from_event(raw)
                self.close(copy, notice, decision)
                return "This was already answered."
            state = dict(copy.state or {})
            op = parts[0]
            n_questions = len(notice.questions)
            if op in ("o", "t"):
                qi, oi = int(parts[1]), int(parts[2])
                q = notice.questions[qi]
                options = [o for o in (q.get("options") or []) if isinstance(o, dict) and o.get("label")]
                label = str(options[oi]["label"])
                qid = str(q.get("id") or f"q{qi + 1}")
                answers = dict(state.get("answers") or {})
                a = dict(answers.get(qid) or {"selected": [], "custom": ""})
                chosen = list(a.get("selected") or [])
                if op == "t":
                    chosen = [c for c in chosen if c != label] if label in chosen else chosen + [label]
                else:
                    chosen = [] if chosen == [label] else [label]
                    if chosen and qi < n_questions - 1:
                        state["i"] = qi + 1
                a["selected"] = chosen
                answers[qid] = a
                state["answers"] = answers
            elif op in ("n", "b"):
                qi = int(parts[1])
                state["i"] = max(0, min(n_questions - 1, qi + (1 if op == "n" else -1)))
            elif op == "y":
                return self.prompt(copy, notice, state, int(parts[1]), msg, user)
            elif op == "a":
                return self.approve(copy, notice, state, user)
            elif op == "r":
                state["confirm_reject"] = True
            elif op == "rx":
                state.pop("confirm_reject", None)
            elif op == "rr":
                return self.reject(copy, notice, user)
            else:
                return ""
            notify_store.mark(copy.id, state=state)
        self._edit(chat_id, message_id, render.question_text(notice, self.config.get().zone, state),
                   render.question_keyboard(copy.id, notice, state))
        return "Sure? Press again to reject." if op == "r" else ""

    def prompt(self, copy: Copy, notice: Notice, state: dict[str, Any], qi: int, msg: dict[str, Any],
               user: dict[str, Any]) -> str:
        """Ask for a typed answer: a message the person replies to."""
        chat_id, message_id = int(msg["chat"]["id"]), int(msg.get("message_id") or 0)
        q = notice.questions[qi] if 0 <= qi < len(notice.questions) else {}
        about = f" to <b>{esc(clip(q.get('question'), 200))}</b>" if q else ""
        who = f"{mention(user)}, your" if msg["chat"].get("type") in GROUPS else "Your"
        sent = self.client.send(chat_id, f"✏️ {who} answer{about}: reply to this message.", reply_to=message_id,
                                force_reply="Type your answer")
        prompts = dict(state.get("prompts") or {})
        prompts[str(sent.get("message_id"))] = qi
        state["prompts"] = prompts
        state["i"] = max(qi, 0)
        notify_store.mark(copy.id, state=state)
        return "Reply to my message with your answer."

    def typed(self, copy: Copy, text: str, msg: dict[str, Any], user: dict[str, Any]) -> None:
        """A typed answer: a reply to the question or to its prompt."""
        with self._copy_lock(copy.id):
            fresh = notify_store.get(copy.id) or copy
            notice, waiting, _ = self._question(fresh)
            if notice is None or not waiting or fresh.status not in notify_store.OPEN:
                self.reply(msg, "That question was already answered, so your reply changed nothing.", quiet=True)
                return
            state = dict(fresh.state or {})
            earlier = str((msg.get("reply_to_message") or {}).get("message_id") or "")
            prompts = state.get("prompts") or {}
            if not notice.questions:
                state["response"] = text
                noted = "Noted as your reply to the gate"
            else:
                qi = int(prompts.get(earlier, state.get("i") or 0))
                qi = max(0, min(qi, len(notice.questions) - 1))
                q = notice.questions[qi]
                qid = str(q.get("id") or f"q{qi + 1}")
                answers = dict(state.get("answers") or {})
                a = dict(answers.get(qid) or {"selected": [], "custom": ""})
                a["custom"] = text
                answers[qid] = a
                state["answers"] = answers
                if qi < len(notice.questions) - 1:
                    state["i"] = qi + 1
                noted = f"Noted as your answer to question {qi + 1}"
            notify_store.mark(fresh.id, state=state)
        where = split_ref(fresh.ref)
        if where:
            self._edit(where[0], where[1], render.question_text(notice, self.config.get().zone, state),
                       render.question_keyboard(fresh.id, notice, state))
        self.reply(msg, f"✏️ {noted}. Press Approve on the question when you're ready.", quiet=True)

    @staticmethod
    def answers(notice: Notice, state: dict[str, Any]) -> list[dict[str, Any]]:
        """The answers so far, in the gate's shape, in question order."""
        given = state.get("answers") or {}
        out = []
        for i, q in enumerate(notice.questions):
            qid = str(q.get("id") or f"q{i + 1}")
            a = given.get(qid) or {}
            selected = [str(s) for s in a.get("selected") or []]
            custom = str(a.get("custom") or "").strip()
            if selected or custom:
                out.append({"id": qid, "question": str(q.get("question") or ""), "selected": selected,
                            "custom": custom})
        return out

    def approve(self, copy: Copy, notice: Notice, state: dict[str, Any], user: dict[str, Any]) -> str:
        who = display_name(user)
        answers = self.answers(notice, state)
        response = str(state.get("response") or "")
        eid, node = copy.execution_id, copy.node or notice.node
        if self.ops.run_is_alive(eid):
            self.ops.approve(eid, node, answers, response, by=f"{who} (Telegram)")
            verdict = "approved"
        else:
            # After a restart nothing waits on this gate: resuming the run
            # brings it back to the gate, which asks again.
            self.ops.approve(eid, node, answers, response, by=f"{who} (Telegram)")
            self.ops.resume(eid)
            verdict = "resumed"
        store.log_action(user.get("id", ""), who, "approve", eid,
                         f"{node} {copy.event_id} {verdict} {json.dumps(answers)[:400]}", chat_id=copy.target)
        pairs = tuple((a["question"] or a["id"], render.answer_text(a)) for a in answers)
        self.close(copy, notice, Decision(verdict, who, "Telegram", response, pairs), state)
        return "Approved" + (f" with {len(answers)} answer(s)" if answers else "")

    def reject(self, copy: Copy, notice: Notice, user: dict[str, Any]) -> str:
        who = display_name(user)
        self.ops.cancel(copy.execution_id, f"Rejected in Telegram by {who}", by=f"{who} (Telegram)")
        store.log_action(user.get("id", ""), who, "reject", copy.execution_id, f"{copy.node} {copy.event_id}",
                         chat_id=copy.target)
        self.close(copy, notice, Decision("rejected", who, "Telegram"))
        return "Rejected; the run is stopped"

    def close(self, copy: Copy, notice: Notice | None, decision: Decision,
              state: dict[str, Any] | None = None) -> None:
        """This copy says how the question was answered (at once), then every
        other copy does too."""
        if notice is not None and notify_store.mark(copy.id, "closed", only_from=notify_store.OPEN,
                                                    detail=f"{decision.verdict} {decision.who} {decision.where}"):
            shown = Copy(**{**copy.__dict__, "state": state if state is not None else copy.state})
            try:
                self.sender.close_question(shown, notice, decision)
            except TelegramError as exc:
                logger.warning("Telegram: could not close the question %s: %s", copy.ref, exc)
        notify.close_question(copy.key, decision, skip=copy.id)
