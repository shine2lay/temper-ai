"""``temper slack e2e`` and ``temper slack fake``: Slack's flows, checked
without the browser.

Every step is a fake Slack event sent to temper's test entry (door.py),
handled by the same code as a real one. What temper does about it is read
back from Slack's API (conversations.history / conversations.replies) in
the test channel, and from temper's API (the run, its cost). Checks:

  ask      ``/temper ask …`` gets an answer in the channel
  mention  ``@temper …`` gets an answer in its thread
  form     ``/temper run notify_probe``; Answer builds a form Slack accepts;
           sending it answers the question; the run finishes with the answers
  approve  a second notify_probe: Approve moves it on
  reject   a third: Reject stops it, and the notice says who rejected it
  stop     a fourth, waiting at its question: the Stop button on a stuck
           notice stops it

What it can't show: that a form really pops up in Slack. Only a real
click's trigger opens one (for 3 seconds); a fake click's form is sent to
Slack, which checks its blocks and then refuses the trigger.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from temper_ai.integrations.slack import blocks, fakes
from temper_ai.integrations.slack.client import SlackClient

PROBE = "notify_probe"
CHECKS = ("ask", "mention", "form", "approve", "reject", "stop")
ASK = "what does the notify_probe workflow do, in two sentences?"
MENTION = "what does the gate_smoke workflow do, in two sentences?"
TYPED = "slack e2e: typed in the fake form"
ANSWERED = "Read the code in"  # the last line of every answer about the code
PLACEHOLDERS = ("Looking for the right workflow…", "Reading the code…")
ACTIONS = {"answer": blocks.ANSWER, "approve": blocks.APPROVE, "reject": blocks.REJECT, "stop": blocks.STOP,
           "confirm": blocks.CONFIRM, "cancel": blocks.CANCEL}
ASK_WAIT_S = 480.0      # the answer's own limit is 7 minutes
STEP_WAIT_S = 180.0     # a run to start in its box, reach its question, end
POLL_S = 2.0


class E2EError(Exception):
    pass


class Door:
    """temper's Slack test entry, and the run API, over HTTP."""

    def __init__(self, server: str, http: Any = None, test_token: str | None = None,
                 api_token: str | None = None) -> None:
        self.server = server.rstrip("/")
        self.http = http or httpx.Client(timeout=30)
        self.test_token = (test_token if test_token is not None else os.environ.get("TEMPER_SLACK_TEST_TOKEN", "")).strip()
        self.api_token = (api_token if api_token is not None else os.environ.get("TEMPER_API_TOKEN", "")).strip()

    def _headers(self) -> dict[str, str]:
        out = {}
        if self.test_token:
            out["X-Temper-Test-Token"] = self.test_token
        if self.api_token:
            out["Authorization"] = f"Bearer {self.api_token}"
        return out

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        response = self.http.request(method, f"{self.server}{path}", headers=self._headers(), json=body)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text[:300]
            raise E2EError(f"{method} {path}: {response.status_code} {detail}")
        return response.json()

    def info(self) -> dict[str, Any]:
        return self._call("GET", "/api/test/slack")

    def send(self, envelope: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/api/test/slack", envelope)

    def fake(self, fake_id: str) -> dict[str, Any]:
        return self._call("GET", f"/api/test/slack/fakes/{fake_id}")

    def run(self, execution_id: str) -> dict[str, Any]:
        return self._call("GET", f"/api/workflows/{execution_id}")


@dataclass
class Result:
    name: str
    ok: bool
    seconds: float
    detail: str
    runs: list[str] = field(default_factory=list)
    cost_usd: float = 0.0


def slack_ts(stamp: float) -> str:
    return f"{stamp:.6f}"


def has_buttons(message: dict[str, Any], *action_ids: str) -> bool:
    have = {b.get("action_id") for _, b in fakes.buttons(message)}
    return all(a in have for a in action_ids)


def words(message: dict[str, Any]) -> str:
    """A message's text and every text in its blocks, as one string."""
    out = [str(message.get("text") or "")]

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "text" and isinstance(item, str):
                    out.append(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(message.get("blocks") or [])
    return "\n".join(out)


def is_answer(message: dict[str, Any]) -> bool:
    return ANSWERED in words(message)


def notice(thread: list[dict[str, Any]], execution_id: str, status: str) -> dict[str, Any] | None:
    """The run's "<workflow> (<id>) <status> …" notice in a thread."""
    start = f"({blocks.short(execution_id)}) {status}"
    return next((m for m in thread if start in str(m.get("text") or "")), None)


def picks_for(view: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """What the e2e fills in a form, and the words the run must then show:
    the last choice of a pick-one, the first and last of a pick-any, and
    ``TYPED`` for a question without choices."""
    input_blocks = [b for b in view.get("blocks") or [] if b.get("type") == "input"]
    ids = {b.get("block_id") for b in input_blocks}
    picks: dict[str, Any] = {}
    expect: list[str] = []
    for block in input_blocks:
        bid, el = str(block.get("block_id") or ""), block.get("element") or {}
        options = el.get("options") or []
        if options:
            multi = el.get("type") in ("checkboxes", "multi_static_select")
            chosen = sorted({0, len(options) - 1}) if multi else [len(options) - 1]
            picks[bid] = chosen
            expect.extend(str((options[n].get("text") or {}).get("text") or "") for n in chosen)
        elif bid.endswith("c") and bid[:-1] not in ids:
            picks[bid] = TYPED
            expect.append(TYPED)
    return picks, expect


class Tester:
    """Runs the checks: fakes in through the door, results read from Slack."""

    def __init__(self, door: Door, slack: SlackClient, *, say: Callable[[str], None] = print,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], float] = time.time, poll_s: float = POLL_S,
                 ask_wait_s: float = ASK_WAIT_S, step_wait_s: float = STEP_WAIT_S) -> None:
        self.door, self.slack, self.say = door, slack, say
        self.sleep, self.clock, self.now, self.poll_s = sleep, clock, now, poll_s
        self.ask_wait_s, self.step_wait_s = ask_wait_s, step_wait_s
        info = door.info()
        if not info.get("on"):
            raise E2EError(f"the Slack test entry is off: {info.get('reason') or 'test_door: false in the Slack config'}")
        if info.get("channel_error"):
            raise E2EError(f"can't find the test channel {info.get('channel')}: {info['channel_error']}")
        self.where = fakes.Where.from_info(info)
        if not (self.where.channel and self.where.user and self.where.bot_user):
            raise E2EError(f"the test entry did not say its channel, user and bot user: {info}")

    # -- plumbing ----------------------------------------------------------------------

    def wait(self, what: str, find: Callable[[], Any], timeout_s: float) -> Any:
        start = self.clock()
        while True:
            got = find()
            if got:
                return got
            if self.clock() - start > timeout_s:
                raise E2EError(f"no {what} after {int(timeout_s)} s")
            self.sleep(self.poll_s)

    def send(self, envelope: dict[str, Any]) -> str:
        return str(self.door.send(envelope)["fake"])

    def started(self, fake_id: str) -> list[str]:
        event = self.door.fake(fake_id).get("event") or {}
        return [str(s.get("execution_id")) for s in event.get("started") or [] if s.get("execution_id")]

    def cost(self, run_ids: list[str]) -> float:
        total = 0.0
        for eid in run_ids:
            try:
                total += float(self.door.run(eid).get("total_cost_usd") or 0)
            except (E2EError, TypeError, ValueError):
                continue
        return total

    def thread(self, ts: str) -> list[dict[str, Any]]:
        return self.slack.replies(self.where.channel, ts, limit=200)

    def message(self, ts: str, thread_ts: str = "") -> dict[str, Any] | None:
        """One message as Slack has it now (``thread_ts``: it is a reply in that thread)."""
        pool = (self.thread(thread_ts) if thread_ts
                else self.slack.history(self.where.channel, latest=ts, inclusive=True, limit=1))
        return next((m for m in pool if m.get("ts") == ts), None)

    def status(self, execution_id: str) -> str:
        try:
            return str(self.door.run(execution_id).get("status") or "")
        except E2EError:
            return ""

    # -- the parts of a run check ------------------------------------------------------------

    def start_probe(self, since: str) -> tuple[str, str, str]:
        """``/temper run notify_probe``: its run id, the header's ts, the fake."""
        fid = self.send(fakes.command(self.where, f"run {PROBE}"))
        runs = self.wait("run started by /temper run", lambda: self.started(fid), self.step_wait_s)
        eid = runs[0]
        head = f"Started {PROBE} ({blocks.short(eid)})"

        def header() -> str:
            for m in self.slack.history(self.where.channel, oldest=since, limit=100):
                if str(m.get("text") or "").startswith(head):
                    return str(m["ts"])
            return ""

        ts = self.wait(f"“{head}” in {self.where.channel_name}", header, self.step_wait_s)
        return eid, ts, fid

    def question(self, header_ts: str) -> dict[str, Any]:
        def find() -> dict[str, Any] | None:
            return next((m for m in self.thread(header_ts) if has_buttons(m, blocks.APPROVE, blocks.REJECT)), None)

        return self.wait("question with Approve and Reject in the run's thread", find, self.step_wait_s)

    def ended(self, eid: str, header_ts: str, status: str) -> dict[str, Any]:
        return self.wait(f"“{status}” notice in the run's thread",
                         lambda: notice(self.thread(header_ts), eid, status), self.step_wait_s)

    def click(self, message: dict[str, Any], action: str) -> str:
        return self.send(fakes.click(self.where, message, ACTIONS.get(action, action)))

    # -- the checks ----------------------------------------------------------------------

    def check_ask(self) -> tuple[str, list[str]]:
        fid = self.send(fakes.command(self.where, f"ask {ASK}"))

        def answered() -> dict[str, Any] | None:
            got = self.door.fake(fid)
            return next((r for r in got.get("replies") or []
                         if (r.get("payload") or {}).get("response_type") == "in_channel"), None)

        reply = self.wait("answer for everyone", answered, self.ask_wait_s)
        posted = str(reply.get("posted") or "")
        if not posted or posted.startswith("error"):
            raise E2EError(f"the answer could not be posted in the channel: {posted or 'no ts'}")
        message = self.message(posted)
        if message is None or not is_answer(message):
            raise E2EError(f"no answer at {posted} in {self.where.channel_name}")
        return f"answer in {self.where.channel_name}: “{blocks.clip(str(message.get('text') or ''), 90)}”", \
            self.started(fid)

    def check_mention(self) -> tuple[str, list[str]]:
        anchor = self.slack.post(self.where.channel, f":test_tube: slack e2e, a fake @temper message: {MENTION}")
        ts = str(anchor["ts"])
        fid = self.send(fakes.mention(self.where, MENTION, ts))

        def answered() -> dict[str, Any] | None:
            replies = [m for m in self.thread(ts) if m.get("ts") != ts]
            done = next((m for m in replies if is_answer(m)), None)
            if done:
                return done
            # The placeholder turns into the answer; anything else it turns into is final.
            other = next((m for m in replies if str(m.get("text") or "") not in PLACEHOLDERS), None)
            if other is not None:
                raise E2EError(f"the thread got something else: “{blocks.clip(str(other.get('text')), 200)}”")
            return None

        message = self.wait("answer in the thread", answered, self.ask_wait_s)
        return f"answer in its thread: “{blocks.clip(str(message.get('text') or ''), 90)}”", self.started(fid)

    def check_form(self, since: str) -> tuple[str, list[str]]:
        eid, header, _ = self.start_probe(since)
        question = self.question(header)
        if not has_buttons(question, blocks.ANSWER):
            raise E2EError("the question has no Answer button")
        fid = self.click(question, "answer")

        def form() -> dict[str, Any] | None:
            got = self.door.fake(fid)
            if got.get("forms"):
                return got["forms"][-1]
            said = [str((r.get("payload") or {}).get("text") or "") for r in got.get("replies") or []]
            if said:
                raise E2EError(f"Answer said: {said[-1]}")
            return None

        kept = self.wait("form from the Answer click", form, self.step_wait_s)
        if kept.get("verdict") not in ("ok", "opened"):
            raise E2EError(f"Slack refused the form: {kept.get('verdict')} {'; '.join(kept.get('problems') or [])}")
        picks, expect = picks_for(kept["view"])
        self.send(fakes.submit(self.where, kept["view"], picks))
        self.ended(eid, header, "completed")
        run = self.door.run(eid)
        output = str(run.get("workflow_output") or run.get("output_data") or "")
        missing = [w for w in expect if w not in output]
        if missing:
            raise E2EError(f"the run finished without the form's answers: {', '.join(missing)}")
        after = self.message(str(question["ts"]), header)
        if after is None or has_buttons(after, blocks.APPROVE) or "Approved by" not in words(after):
            raise E2EError("the question still has its buttons, or does not say who approved it")
        return (f"{blocks.short(eid)}: Slack took the form's {len(kept['view'].get('blocks') or [])} blocks; "
                f"answers {', '.join(expect)} reached the run; finished notice in the thread"), [eid]

    def check_approve(self, since: str) -> tuple[str, list[str]]:
        eid, header, _ = self.start_probe(since)
        self.click(self.question(header), "approve")
        self.ended(eid, header, "completed")
        return f"{blocks.short(eid)}: Approve moved it on; finished notice in the thread", [eid]

    def check_reject(self, since: str) -> tuple[str, list[str]]:
        eid, header, _ = self.start_probe(since)
        self.click(self.question(header), "reject")
        end = self.ended(eid, header, "cancelled")
        if "Rejected in Slack by" not in words(end):
            raise E2EError(f"the cancelled notice does not say who rejected it: {words(end)[:200]}")
        return f"{blocks.short(eid)}: Reject stopped it; the notice says “Rejected in Slack by …”", [eid]

    def check_stop(self, since: str) -> tuple[str, list[str]]:
        from temper_ai.integrations.notify.notice import Notice
        from temper_ai.integrations.slack.sender import render

        eid, header, _ = self.start_probe(since)
        self.question(header)
        if self.status(eid) not in ("running", "waiting", "queued"):
            raise E2EError(f"the run is {self.status(eid) or 'gone'}, not going, before Stop")
        stuck = render(Notice(kind="stuck", execution_id=eid, workflow=PROBE, status=self.status(eid),
                              idle_min=0, last_at=datetime.now(UTC).isoformat(timespec="seconds"),
                              active_nodes=["decide"]))
        stuck["blocks"].append(blocks.context(":test_tube: slack e2e: a stuck notice posted now, for its Stop button"))
        posted = self.slack.post(self.where.channel, stuck["text"], stuck["blocks"], thread_ts=header)
        message = self.message(str(posted["ts"]), header)
        if message is None:
            raise E2EError("the stuck notice could not be read back")
        self.click(message, "stop")
        end = self.ended(eid, header, "cancelled")
        said = [m for m in self.thread(header) if str(m.get("text") or "").startswith("Stop requested by")]
        if not said or "Stopped in Slack by" not in words(end):
            raise E2EError("no “Stop requested by” in the thread, or the notice does not say who stopped it")
        return f"{blocks.short(eid)}: Stop stopped it; “Stop requested by …” and the cancelled notice in the thread", [eid]

    # -- the whole set ---------------------------------------------------------------------

    def run(self, only: list[str] | None = None) -> list[Result]:
        since = slack_ts(self.now() - 5)
        checks: list[tuple[str, Callable[[], tuple[str, list[str]]]]] = [
            ("ask", self.check_ask),
            ("mention", self.check_mention),
            ("form", lambda: self.check_form(since)),
            ("approve", lambda: self.check_approve(since)),
            ("reject", lambda: self.check_reject(since)),
            ("stop", lambda: self.check_stop(since)),
        ]
        unknown = sorted(set(only or []) - set(CHECKS))
        if unknown:
            raise E2EError(f"no check {', '.join(unknown)} (they are: {', '.join(CHECKS)})")
        results = []
        for name, check in checks:
            if only and name not in only:
                continue
            self.say(f"… {name}")
            start = self.clock()
            try:
                detail, runs = check()
                result = Result(name, True, self.clock() - start, detail, runs)
            except (E2EError, ValueError, httpx.HTTPError) as exc:
                result = Result(name, False, self.clock() - start, str(exc))
            except Exception as exc:  # noqa: BLE001 - one broken check must not hide the others
                result = Result(name, False, self.clock() - start, f"{type(exc).__name__}: {exc}")
            result.cost_usd = self.cost(result.runs)
            self.say(line(result))
            results.append(result)
        return results


def line(result: Result) -> str:
    return (f"{'PASS' if result.ok else 'FAIL'}  {result.name:<8} {result.seconds:6.1f} s  "
            f"${result.cost_usd:.3f}  {result.detail}")


def summary(results: list[Result]) -> str:
    passed = sum(r.ok for r in results)
    return (f"{passed}/{len(results)} passed in {sum(r.seconds for r in results):.0f} s, "
            f"${sum(r.cost_usd for r in results):.3f}")


# -- temper slack fake --wait ------------------------------------------------------------------

ENDED = ("done", "skipped", "expired", "gave_up", "failed")


def reply_line(reply: dict[str, Any], channel_name: str) -> str:
    payload = reply.get("payload") or {}
    kind = str(payload.get("response_type") or "ephemeral") if isinstance(payload, dict) else "?"
    text = words(payload) if isinstance(payload, dict) else str(payload)
    posted = str(reply.get("posted") or "")
    where = (f" (posted in {channel_name} at {posted})" if posted and not posted.startswith("error")
             else f" ({posted})" if posted else "")
    return f"  reply, {kind}{where}: {blocks.clip(' '.join(text.split()), 400)}"


def form_line(form: dict[str, Any]) -> str:
    view = form.get("view") or {}
    inputs = [b for b in view.get("blocks") or [] if b.get("type") == "input"]
    verdict = str(form.get("verdict") or "?")
    said = "Slack took its blocks" if verdict in ("ok", "opened") else f"Slack refused it ({verdict})"
    out = f"  form “{(view.get('title') or {}).get('text', '')}”, {len(inputs)} fields: {said}"
    problems = form.get("problems") or []
    return out + ("".join(f"\n    {p}" for p in problems) if problems else "")


def message_line(message: dict[str, Any], where: fakes.Where) -> str:
    who = "temper" if message.get("user") == where.bot_user or message.get("bot_id") else str(message.get("user") or "?")
    buttons = [str(b.get("action_id")) for _, b in fakes.buttons(message)]
    extra = f" [buttons: {', '.join(buttons)}]" if buttons else ""
    return f"  {message.get('ts')} {who}: {blocks.clip(' '.join(words(message).split()), 400)}{extra}"


def follow(tester: Tester, fake_id: str, seconds: float, thread_ts: str = "", since: str = "") -> None:
    """Print what comes of a fake, for up to ``seconds``: what temper said
    on its reply link, the forms it opened, its event in the inbox, then
    the thread's messages since ``since``."""
    seen_replies = seen_forms = 0
    start = tester.clock()
    event: dict[str, Any] = {}
    while True:
        got = tester.door.fake(fake_id)
        for reply in (got.get("replies") or [])[seen_replies:]:
            tester.say(reply_line(reply, tester.where.channel_name))
        seen_replies = len(got.get("replies") or [])
        for form in (got.get("forms") or [])[seen_forms:]:
            tester.say(form_line(form))
        seen_forms = len(got.get("forms") or [])
        event = got.get("event") or {}
        if str(event.get("status") or "") in ENDED or tester.clock() - start > seconds:
            break
        tester.sleep(tester.poll_s)
    if event.get("id") is not None:
        runs = ", ".join(f"{s.get('workflow')} {s.get('execution_id')}" for s in event.get("started") or [])
        tester.say(f"  inbox event {event['id']}: {event.get('status')}"
                   + (f", {event['outcome']}" if event.get("outcome") else "")
                   + (f"; error: {event['error']}" if event.get("error") else "")
                   + (f"; started {runs}" if runs else ""))
    else:
        tester.say("  (it is not in the event inbox, so there is no telling when temper is done with it)")
    if thread_ts:
        newer = [m for m in tester.thread(thread_ts) if not since or float(m.get("ts") or 0) >= float(since)]
        for message in newer:
            tester.say(message_line(message, tester.where))
