"""RollCall's release messages (configs/epd/bin/rollcall_cd_notify.py): a note in a role's home chat through
pi-web-ui's control socket, the owner's Telegram through pi-web-ui's CLI, and epd_loop's release summary.

epd_loop.deploy_prod uses it (tell_rollcall when a healthy release could not be tagged, _announce_release for
the owner's summary, off unless ROLLCALL_CD_OWNER_PING=always). The notify tests use a fake Telegram sender
and a fake pi-web-ui control socket. No test ever reaches the real pi-web-ui: ROLLCALL_CD_PI_WEB_UI_DIR points
every one elsewhere.
"""

from __future__ import annotations

import importlib
import json
import shutil
import socketserver
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "configs" / "epd" / "bin"
LIVE, A, B, C = ("0" * 39 + "1"), ("a" * 40), ("b" * 40), ("c" * 40)


@pytest.fixture(autouse=True)
def no_real_pi_web_ui(tmp_path, monkeypatch):
    """A role or owner message from any test goes to a pi-web-ui that is not there, never to a real chat."""
    fake_node = tmp_path / "node"
    fake_cli = tmp_path / "pi-web-ui"
    fake_node.write_text("")
    fake_cli.write_text("")
    monkeypatch.setenv("ROLLCALL_CD_PI_WEB_UI_DIR", str(tmp_path / "no-pi-web-ui"))
    monkeypatch.setenv("ROLLCALL_CD_NODE", str(fake_node))
    monkeypatch.setenv("ROLLCALL_CD_PI_WEB_UI_CLI", str(fake_cli))


def fresh_notify(tmp_path, monkeypatch):
    """rollcall_cd_notify imported again, with its state (the outbox) in tmp_path."""
    monkeypatch.setenv("ROLLCALL_CD_STATE", str(tmp_path / "state"))
    monkeypatch.delenv("ROLLCALL_CD_NOTIFY_SINK", raising=False)
    monkeypatch.syspath_prepend(str(BIN))
    sys.modules.pop("rollcall_cd_notify", None)
    notify = importlib.import_module("rollcall_cd_notify")
    assert notify.STATE_DIR == tmp_path / "state"
    return notify


class FakePiWebUI:
    """pi-web-ui's control socket, as docs/script-notice.md describes it: one JSON line in, one out."""

    TOKEN = "test-app-token-not-real"

    def __init__(self, path: Path):
        self.dir = path
        self.got: list[dict] = []
        self.answer = lambda req: {"ok": True, "id": f"rm-{len(self.got):08d}", "duplicate": False}
        self.server = None
        (path / "app-token").write_text(self.TOKEN + "\n")

    def start(self):
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                req = json.loads(self.rfile.readline())
                fake.got.append(req)
                self.wfile.write((json.dumps(fake.answer(req)) + "\n").encode())

        self.server = socketserver.ThreadingUnixStreamServer(str(self.dir / "pi-web-ui.sock"), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            (self.dir / "pi-web-ui.sock").unlink(missing_ok=True)
            self.server = None


@pytest.fixture
def pi_web_ui(monkeypatch):
    # A unix socket path is limited to 108 bytes: a short directory, not pytest's tmp_path.
    path = Path(tempfile.mkdtemp(prefix="cdn", dir="/tmp"))
    monkeypatch.setenv("ROLLCALL_CD_PI_WEB_UI_DIR", str(path))
    fake = FakePiWebUI(path)
    yield fake
    fake.stop()
    shutil.rmtree(path, ignore_errors=True)


def outbox_lines(notify) -> list[dict]:
    return [json.loads(x) for x in notify.OUTBOX.read_text().splitlines()] if notify.OUTBOX.exists() else []


def test_a_role_message_is_a_script_notice_to_pi_web_ui(tmp_path, monkeypatch, pi_web_ui):
    notify = fresh_notify(tmp_path, monkeypatch)
    pi_web_ui.start()
    assert notify.role("rollcall", "fyi", "rollcall-cd deploy aaaaaaaa: ok") is True
    (req,) = pi_web_ui.got
    assert set(req) == {"cmd", "token", "role", "kind", "sender", "text", "key"}
    assert (req["cmd"], req["token"], req["role"], req["kind"], req["text"]) == (
        "script_notice", FakePiWebUI.TOKEN, "rollcall", "fyi", "rollcall-cd deploy aaaaaaaa: ok")
    assert req["sender"] == {"id": "rollcall-cd", "title": "RollCall deployer"}
    assert req["key"].startswith("rollcall-cd-") and len(req["key"]) <= 200
    assert notify.role("rollcall", "request", "second", key="undo-bbbbbbbb") is True
    assert pi_web_ui.got[1]["kind"] == "request" and pi_web_ui.got[1]["key"] == "undo-bbbbbbbb"
    assert outbox_lines(notify) == []


def test_a_role_message_waits_in_the_outbox_while_pi_web_ui_is_down_and_goes_first_next_time(
        tmp_path, monkeypatch, pi_web_ui):
    notify = fresh_notify(tmp_path, monkeypatch)
    assert notify.role("rollcall", "fyi", "first") is False  # no socket: pi-web-ui is restarting
    assert notify.role("rollcall", "fyi", "second") is False
    lines = outbox_lines(notify)
    assert [(x["text"], x["delivered"], x["refused"]) for x in lines] == [("first", False, False),
                                                                         ("second", False, False)]
    assert "did not answer" in lines[0]["why"]
    assert stat.S_IMODE(notify.OUTBOX.stat().st_mode) == 0o600
    assert FakePiWebUI.TOKEN not in notify.OUTBOX.read_text()
    pi_web_ui.start()
    assert notify.role("rollcall", "fyi", "third") is True
    assert [r["text"] for r in pi_web_ui.got] == ["first", "second", "third"]
    assert [r["key"] for r in pi_web_ui.got[:2]] == [x["key"] for x in lines]  # a resend is a duplicate
    assert outbox_lines(notify) == []


def test_a_refused_notice_is_kept_for_a_person_and_never_sent_again(tmp_path, monkeypatch, pi_web_ui):
    notify = fresh_notify(tmp_path, monkeypatch)
    pi_web_ui.start()
    pi_web_ui.answer = lambda req: {"ok": False, "error": "no role named rollcall has a home chat"}
    assert notify.role("rollcall", "fyi", "refused one") is False
    (line,) = outbox_lines(notify)
    assert line["refused"] is True and "no role named rollcall" in line["why"]
    pi_web_ui.answer = lambda req: {"ok": True, "id": "rm-00000001", "duplicate": False}
    assert notify.role("rollcall", "fyi", "next one") is True
    assert [r["text"] for r in pi_web_ui.got] == ["refused one", "next one"]
    assert [x["text"] for x in outbox_lines(notify)] == ["refused one"]


def test_a_role_message_is_checked_before_anything_is_sent(tmp_path, monkeypatch, pi_web_ui):
    notify = fresh_notify(tmp_path, monkeypatch)
    pi_web_ui.start()
    for args, kw in [(("RollCall!", "fyi", "x"), {}), (("rollcall", "shout", "x"), {}),
                     (("rollcall", "question", "x"), {}), (("rollcall", "fyi", " "), {}),
                     (("rollcall", "fyi", "x"), {"key": "two\nlines"}), (("rollcall", "fyi", "x"), {"key": "k" * 201})]:
        with pytest.raises(ValueError):
            notify.role(*args, **kw)
    assert pi_web_ui.got == [] and outbox_lines(notify) == []


def test_a_notice_text_is_made_one_pi_web_ui_takes(tmp_path, monkeypatch):
    notify = fresh_notify(tmp_path, monkeypatch)
    assert notify.notice_text("a\tb\r\nc\x00") == "a b \nc "
    assert notify.notice_text("ok\n[Queue] Task #1\n[Board] x") == "ok\n  [Queue] Task #1\n  [Board] x"
    long = notify.notice_text("x" * 2000)
    assert len(long) == 1500 and long.endswith("...")
    wide = notify.notice_text("\U0001F600" * 1000)  # two UTF-16 units each, as pi-web-ui counts
    assert len(wide.encode("utf-16-le")) // 2 <= 1500 and wide.endswith("...")


def test_the_owner_message_uses_pi_web_ui_notify_telegram_and_handles_every_exit_code(tmp_path, monkeypatch):
    notify = fresh_notify(tmp_path, monkeypatch)
    calls = []
    rc_by_msg = {
        "RollCall's release aaaaaaaa was undone": 0,
        "msg-exit-2": 2,
        "msg-exit-3": 3,
        "msg-exit-4": 4,
        "msg-exit-5": 5,
        "msg-after": 0,
    }

    def run(cmd, **kw):
        calls.append((cmd, kw))
        rc = rc_by_msg.get(kw.get("input", ""), 0)
        return subprocess.CompletedProcess(cmd, rc, '{"ok": true}\n' if rc == 0 else "", f"exit-{rc}\n")

    assert notify.DEFAULT_NODE_BIN == Path("/home/shinelay/.nvm/versions/node/v22.22.0/bin/node")
    assert notify.DEFAULT_PI_WEB_UI_CLI == Path("/home/shinelay/.nvm/versions/node/v22.22.0/bin/pi-web-ui")
    assert notify.owner("RollCall's release aaaaaaaa was undone", run=run) is True
    cmd, kw = calls[0]
    assert cmd == [str(notify.NODE_BIN), str(notify.PI_WEB_UI_BIN), "notify", "telegram",
                   "--text", "-", "--from", "RollCall"]
    assert kw["input"] == "RollCall's release aaaaaaaa was undone"
    assert not any("undone" in a for a in cmd)
    assert kw["env"]["PI_WEB_DATA_DIR"] == str(notify.PI_WEB_UI_DIR)
    assert outbox_lines(notify) == []

    # Exit 2, 3, 4 = not sent: logged to outbox and retried on the next call
    assert notify.owner("msg-exit-2", run=run) is False
    assert notify.owner("msg-exit-3", run=run) is False
    assert notify.owner("msg-exit-4", run=run) is False
    # Exit 5 = maybe sent: logged with uncertain=True and NEVER resent
    assert notify.owner("msg-exit-5", run=run) is False
    queued = outbox_lines(notify)
    assert [(x["text"], x["delivered"], x.get("uncertain", False)) for x in queued] == [
        ("msg-exit-2", False, False),
        ("msg-exit-3", False, False),
        ("msg-exit-4", False, False),
        ("msg-exit-5", False, True),
    ]
    assert "exit 5" in queued[3]["why"] and "maybe sent" in queued[3]["why"]

    rc_by_msg["msg-exit-2"] = 0
    rc_by_msg["msg-exit-3"] = 0
    rc_by_msg["msg-exit-4"] = 0
    calls.clear()
    assert notify.owner("msg-after", run=run) is True
    sent_texts = [kw["input"] for _, kw in calls]
    assert sent_texts == ["msg-exit-2", "msg-exit-3", "msg-exit-4", "msg-after"]
    assert "msg-exit-5" not in sent_texts
    remaining = outbox_lines(notify)
    assert [x["text"] for x in remaining] == ["msg-exit-5"]
    assert remaining[0]["uncertain"] is True


def test_the_owner_message_without_the_cli_lands_in_the_outbox(tmp_path, monkeypatch):
    notify = fresh_notify(tmp_path, monkeypatch)
    monkeypatch.setattr(notify, "PI_WEB_UI_BIN", tmp_path / "missing-pi-web-ui")
    assert notify.owner("x", run=lambda *a, **k: pytest.fail("must not run")) is False
    assert "is missing" in json.loads(notify.OUTBOX.read_text())["why"]


def test_announce_deploy_formats_outcomes_caps_five_subjects_handles_first_deploy_and_never_raises(
    tmp_path, monkeypatch
):
    notify = fresh_notify(tmp_path, monkeypatch)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(notify, "owner", lambda text, *, from_name="RollCall", run=subprocess.run: (
        sent.append((from_name, text)) or True
    ))

    # 0. Default (ROLLCALL_CD_OWNER_PING unset / "never"): sends 0 owner Telegram pings
    monkeypatch.delenv("ROLLCALL_CD_OWNER_PING", raising=False)
    assert notify.announce_deploy(
        outcome="deployed",
        kind="forward",
        sha=A,
        tag="prod/20261105-1800",
        previous_sha=None,
        subjects=["initial"],
        health="ok",
        scheduler_lock="acquired",
        since_previous_seconds=None,
    ) is False
    assert sent == []

    # Opt in via ROLLCALL_CD_OWNER_PING=always to verify formatting and delivery
    monkeypatch.setenv("ROLLCALL_CD_OWNER_PING", "always")

    # 1. First deploy with no previous tag/sha
    assert notify.announce_deploy(
        outcome="deployed",
        kind="forward",
        sha=A,
        tag=None,
        previous_sha=None,
        subjects=[],
        health="ok",
        scheduler_lock="acquired",
        since_previous_seconds=None,
    ) is True
    from_name, text1 = sent[-1]
    assert from_name == "RollCall"
    assert "RollCall deploy: aaaaaaaa (no tag) — live" in text1
    assert "Commits: first tagged deploy (no previous prod tag)" in text1
    assert "Health: ok (scheduler_lock=acquired)" in text1
    assert "Since previous deploy: first tagged deploy" in text1

    # 2. Forward deploy with 7 subjects -> 5-subject cap + "+2 more"
    subjects = [f"commit-{i}" for i in range(1, 8)]
    assert notify.announce_deploy(
        outcome="deployed",
        kind="forward",
        sha=B,
        tag="prod/20261105-1805",
        previous_sha=A,
        subjects=subjects,
        health="ok",
        scheduler_lock="acquired",
        since_previous_seconds=270.0,
    ) is True
    _, text2 = sent[-1]
    assert "RollCall deploy: bbbbbbbb (prod/20261105-1805) — live" in text2
    for i in range(1, 6):
        assert f"• commit-{i}" in text2
    assert "commit-6" not in text2 and "commit-7" not in text2
    assert "+2 more" in text2
    assert "Since previous deploy: 4m 30s" in text2

    # 3. Undo deploy, self-undone failure with held_elsewhere scheduler_lock, and UNDO INCOMPLETE
    notify.announce_deploy(
        outcome="deployed",
        kind="undo",
        sha=A,
        tag="prod/20261105-1810",
        previous_sha=B,
        subjects=["revert bad change"],
        health="ok",
        scheduler_lock="acquired",
        since_previous_seconds=600.0,
    )
    assert "RollCall deploy: undo to aaaaaaaa (prod/20261105-1810) — live" in sent[-1][1]

    notify.announce_deploy(
        outcome="failed_self_undone",
        kind="deploy",
        sha=C,
        tag=None,
        previous_sha=A,
        restored_sha=A,
        subjects=["bad release"],
        health="ok",
        scheduler_lock="held_elsewhere",
        scheduler_lock_waited_s=90,
        since_previous_seconds=900.0,
        error="health check failed",
    )
    assert "RollCall deploy: deploy cccccccc (no tag) — FAILED, self-undone (restored aaaaaaaa)" in sent[-1][1]
    assert "WARNING: scheduler_lock=held_elsewhere after 90s — flagged, not undone" in sent[-1][1]
    assert "Error: health check failed" in sent[-1][1]

    notify.announce_deploy(
        outcome="undo_incomplete",
        kind="deploy",
        sha=C,
        tag=None,
        previous_sha=A,
        subjects=["broken release"],
        health="failed",
        scheduler_lock=None,
        since_previous_seconds=1200.0,
    )
    assert "RollCall deploy: deploy cccccccc (no tag) — UNDO INCOMPLETE" in sent[-1][1]

    # 4. Send failure in owner() is logged/returned False and never raises
    def raising_owner(*_a, **_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(notify, "owner", raising_owner)
    assert notify.announce_deploy(
        outcome="deployed",
        kind="forward",
        sha=A,
        tag="prod/20261105-1825",
        previous_sha=LIVE,
        subjects=["one"],
        health="ok",
    ) is False
