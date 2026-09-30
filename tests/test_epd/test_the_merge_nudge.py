"""The owner hears about a PR at his merge gate that bets wait on (queue task 12, 2026-09-27).

Since epd_loop v12 a bet that changes a file an earlier live bet changes waits in its `turn` node
until that bet's PR is merged or closed. On past bets most of the waiting would have been on the
owner's merge gate: one PR waited two days, and four builds would have hit the 24-hour stop behind
it. So once a bet has waited 2 hours on a PR at the gate, the owner gets a Slack message naming the
PR and the bets behind it: once per PR, then once a day while bets still wait on it. `nudge` runs on
the host, on a timer, with no model; it reads what each waiting bet's turn node wrote (turn.json).

Since 2026-09-29 the autopilot merges ready PRs itself, so the message says the PR is not merged yet
and why that can be, instead of asking the owner to merge it at his gate (task 12's study,
~/epd-autopilot/collide/waits.md).
"""

import datetime as dt
import io
import json

from tests.test_epd import test_epd_loop

# The driver, loaded with its state in a temporary directory: test_epd_loop's fixture, by name.
L = test_epd_loop.L

NOW = dt.datetime(2026, 9, 28, 18, 0, tzinfo=dt.UTC)


def ago(hours: float, now: dt.datetime = NOW) -> str:
    return (now - dt.timedelta(hours=hours)).isoformat(timespec="seconds")


def at_gate(bet: str = "b064", pr: int = 40, opened_h: float = 30, now: dt.datetime = NOW, **ship) -> dict:
    return {"status": "pr_opened", "title": "Covered calls", "state": {"stages": {"ship": {
        "pr": f"https://github.com/shine2lay/rollcall/pull/{pr}", "pr_number": pr,
        "title": f"{bet}: Covered calls", "at": ago(opened_h, now), **ship}}}}


def waiting(since_h: float, *on: str, now: dt.datetime = NOW, files=("backend/rollcall/roll.py",)) -> dict:
    return {"since": ago(since_h, now), "checked": ago(0.05, now),
            "blockers": [{"bet_id": b, "status": "pr_opened", "files": list(files)} for b in on]}


# ---- when: 2 hours, one per PR, then daily ------------------------------------------------------


def test_nothing_before_two_hours(L):
    due, keep = L.nudges_due({"b120": waiting(1.9, "b064")}, {"b064": at_gate()}, {}, NOW)
    assert due == [] and keep == {}


def test_one_message_per_pr_naming_every_bet_behind_it(L):
    waits = {"b120": waiting(3, "b064"), "b121": waiting(26, "b064", files=("frontend/src/pages/Roll.tsx",))}
    due, keep = L.nudges_due(waits, {"b064": at_gate()}, {}, NOW)
    assert len(due) == 1
    assert [w["bet_id"] for w in due[0]["waiting"]] == ["b120", "b121"]
    assert keep == {"40": {"first": NOW.isoformat(timespec="seconds"), "last": NOW.isoformat(timespec="seconds"),
                           "bet": "b064"}}
    text = L.nudge_text(due[0])
    assert text.startswith("2 bets wait on PR #40, not merged yet: b064: Covered calls")
    assert "The autopilot merges it once CI passes and it merges cleanly" in text
    assert "at your merge gate" not in text, "he no longer merges them himself (09-29)"
    assert "b120, for 3 h (both change backend/rollcall/roll.py)" in text
    assert "b121, for 26 h (both change frontend/src/pages/Roll.tsx)" in text
    assert text.endswith("https://github.com/shine2lay/rollcall/pull/40")


def test_then_nothing_until_a_day_has_passed(L):
    bets = {"b064": at_gate()}
    due, sent = L.nudges_due({"b120": waiting(2, "b064")}, bets, {}, NOW)
    assert len(due) == 1
    first = sent["40"]["first"]
    for later_h in (0.1, 1, 12, 23.9):
        now = NOW + dt.timedelta(hours=later_h)
        due, sent = L.nudges_due({"b120": waiting(2 + later_h, "b064", now=now)}, bets, sent, now)
        assert due == [], f"{later_h} h after the first message"
    now = NOW + dt.timedelta(hours=24)
    due, sent = L.nudges_due({"b120": waiting(26, "b064", now=now)}, bets, sent, now)
    assert len(due) == 1 and sent["40"]["first"] == first and sent["40"]["last"] == now.isoformat(timespec="seconds")


def test_each_pr_gets_its_own_message(L):
    waits = {"b120": waiting(3, "b064", "b070")}
    due, keep = L.nudges_due(waits, {"b064": at_gate(), "b070": at_gate("b070", pr=44)}, {}, NOW)
    assert sorted(g["pr_number"] for g in due) == [40, 44] and sorted(keep) == ["40", "44"]


def test_the_wait_counts_from_when_the_pr_reached_the_gate(L):
    # b120 waited 10 h, but b064 was still being built until an hour ago: the owner had nothing to do
    due, _ = L.nudges_due({"b120": waiting(10, "b064")}, {"b064": at_gate(opened_h=1)}, {}, NOW)
    assert due == []
    due, _ = L.nudges_due({"b120": waiting(11, "b064")}, {"b064": at_gate(opened_h=2)}, {}, NOW)
    assert len(due) == 1 and round(due[0]["waiting"][0]["hours"]) == 2


def test_a_build_still_running_or_a_merged_pr_is_not_the_owners_to_move(L):
    running = {"status": "running", "title": "Still building", "state": {"stages": {}}}
    merged = at_gate(merged=True)
    for blocker in (running, merged):
        due, keep = L.nudges_due({"b120": waiting(30, "b064")}, {"b064": blocker}, {}, NOW)
        assert due == [] and keep == {}


def test_a_pr_that_stops_holding_anyone_is_forgotten(L):
    sent = {"40": {"first": ago(30), "last": ago(6), "bet": "b064"}}
    due, keep = L.nudges_due({}, {"b064": at_gate()}, sent, NOW)
    assert due == [] and keep == {}
    # a bet that waits on it again later is told about after its own 2 hours, not after a day
    due, _ = L.nudges_due({"b125": waiting(2, "b064")}, {"b064": at_gate()}, keep, NOW)
    assert len(due) == 1


# ---- the command: reads the turn records, sends, remembers ---------------------------------------


def write_turn(L, bet: str, rec: dict) -> None:
    (L.BETS_DIR / bet).mkdir(exist_ok=True)
    (L.BETS_DIR / bet / "turn.json").write_text(json.dumps(rec))


def test_nudge_reads_the_waiting_bets_and_tells_the_owner_once(L, monkeypatch):
    now = dt.datetime.now(dt.UTC)
    write_turn(L, "b120", waiting(3, "b064", now=now))
    stale = waiting(30, "b064", now=now)
    stale["checked"] = ago(2, now)  # its run stopped two hours ago
    write_turn(L, "b121", stale)
    write_turn(L, "b122", {"since": ago(30, now), "cleared": ago(1, now), "waited_for": ["b064"]})
    monkeypatch.setattr(L, "bets_in_line", lambda with_branches=False: {"b064": at_gate(now=now)})
    told: list[str] = []
    monkeypatch.setattr(L, "tell_owner", lambda text: told.append(text) or True)

    L.cmd_nudge()
    assert len(told) == 1 and "PR #40" in told[0] and "b120" in told[0]
    assert "b121" not in told[0] and "b122" not in told[0], "a stopped run's or a cleared wait is left out"
    assert set(json.loads(L.NUDGES.read_text())) == {"40"}

    L.cmd_nudge()
    assert len(told) == 1, "not again the same day"


def test_a_message_that_was_not_sent_is_tried_again(L, monkeypatch):
    now = dt.datetime.now(dt.UTC)
    write_turn(L, "b120", waiting(3, "b064", now=now))
    monkeypatch.setattr(L, "bets_in_line", lambda with_branches=False: {"b064": at_gate(now=now)})
    tries: list[str] = []
    monkeypatch.setattr(L, "tell_owner", lambda text: tries.append(text) and False)
    L.cmd_nudge()
    assert len(tries) == 1 and json.loads(L.read(L.NUDGES) or "{}") == {}
    monkeypatch.setattr(L, "tell_owner", lambda text: tries.append(text) or True)
    L.cmd_nudge()
    assert len(tries) == 2 and "40" in json.loads(L.NUDGES.read_text())


def test_nothing_waiting_sends_nothing_and_reads_no_ledger(L, monkeypatch):
    monkeypatch.setattr(L, "bets_in_line", lambda with_branches=False: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(L, "tell_owner", lambda text: (_ for _ in ()).throw(AssertionError))
    L.cmd_nudge()
    assert not L.NUDGES.exists()


def test_the_test_message_is_sent_and_nothing_is_recorded(L, monkeypatch):
    told: list[str] = []
    monkeypatch.setattr(L, "tell_owner", lambda text: told.append(text) or True)
    monkeypatch.setattr("sys.argv", ["epd_loop.py", "nudge", "--test"])
    L.main()
    assert len(told) == 1 and told[0].startswith("Test of the merge nudge")
    assert not L.NUDGES.exists()


# ---- the Slack message: temper's bot, the owner's DM, as temper-deploy sends -----------------------


def test_the_message_goes_to_the_owners_dm_from_temper_bot(L, monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nSLACK_BOT_TOKEN='xoxb-test'\n")
    monkeypatch.setattr(L, "TEMPER_ENV", env)
    calls = []

    def urlopen(req, timeout):
        calls.append((req.full_url, req.headers.get("Authorization"), json.loads(req.data)))
        reply = {"ok": True, "channel": {"id": "D123"}} if req.full_url.endswith("conversations.open") else {"ok": True}
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(L.urllib.request, "urlopen", urlopen)
    assert L.tell_owner("hello") is True
    assert calls[0] == ("https://slack.com/api/conversations.open", "Bearer xoxb-test", {"users": L.OWNER_SLACK_DM})
    assert calls[1][0].endswith("chat.postMessage") and calls[1][2]["channel"] == "D123"
    assert calls[1][2]["text"] == "hello"


def test_no_token_means_no_message_and_no_error(L, monkeypatch, tmp_path):
    monkeypatch.setattr(L, "TEMPER_ENV", tmp_path / "missing.env")
    monkeypatch.setattr(L.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert L.tell_owner("hello") is False
