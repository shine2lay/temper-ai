"""Independent-process controls for E's real composition, not a second server.

Unlike B's fixed operation pool, these children pause at named commit/effect
boundaries until the parent explicitly releases or kills them. Only closed
outcomes cross stdout; synthetic input and the isolated DB address use stdin.
"""

from __future__ import annotations

import json
import select
import subprocess
import sys

import pytest

from temper_ai.clarifications import contracts as c
from temper_ai.clarifications.store import ClarificationStore
from temper_ai.integrations.telegram import poller
from temper_ai.integrations.telegram import store as telegram_store
from tests.test_clarifications import composition_scenarios as s
from tests.test_clarifications import composition_vectors as v
from tests.test_clarifications.test_caller_integration import Composition
from tests.test_clarifications.test_store import Db


class ExistingDatabase(Db):
    """Reuse Db's engine/restart/read methods without creating or clearing rows."""

    def __init__(self, url):
        self.url, self.engines = url, []
        self.engine = self.new_engine()
        self.store = ClarificationStore(self.engine)


class Child:
    """Parent-owned child; every boundary has an explicit receive/release pair."""

    def __init__(self, db, operation, *, boundary=None, **inputs):
        self.process = subprocess.Popen(
            [sys.executable, "-m", "tests.test_clarifications.composition_process"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1,
        )
        self.send(dict(url=db.url, operation=operation, boundary=boundary, **inputs))

    def send(self, value):
        self.process.stdin.write(json.dumps(value) + "\n")
        self.process.stdin.flush()

    def receive(self):
        assert select.select([self.process.stdout], [], [], 90)[0], "composition child missed named boundary"
        line = self.process.stdout.readline()
        assert line, "composition child exited before closed outcome"
        result = json.loads(line)
        assert result[0] != "error", f"composition child refused: {result[1:]}"
        return result

    def at(self, name):
        assert self.receive() == ["boundary", name]

    def release(self):
        self.send("continue")

    def finish(self):
        outcome = self.receive()
        assert self.process.wait(timeout=90) == 0, "composition child failed"
        return outcome

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=90)
        self.process.stdin.close()
        self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _emit(value):
    print(json.dumps(value), flush=True)


def _run(config):
    db = ExistingDatabase(config["url"])
    with pytest.MonkeyPatch.context() as patch:
        rig = Composition(db, patch, initialize=False)
        target, signalled = config.get("boundary"), False

        def pause(name):
            nonlocal signalled
            if name == target and not signalled:
                signalled = True
                _emit(["boundary", name])
                assert json.loads(sys.stdin.readline()) == "continue"

        for method, name in (("_cas", "cas"), ("_create", "create")):
            original = getattr(db.store, method)

            def gated(*args, _original=original, _name=name, **kwargs):
                pause(_name)
                return _original(*args, **kwargs)

            patch.setattr(db.store, method, gated)
        commit = db.store._commit
        commits = 0

        def commit_boundary(session, explained):
            nonlocal commits
            commits += 1
            selected = commits == config.get("commit_index", 1)
            # Flushing before the cut proves rollback of written, uncommitted rows.
            if selected and target == "before_commit" and not signalled:
                session.flush()
                pause("before_commit")
            commit(session, explained)
            if selected:
                pause("after_commit")

        patch.setattr(db.store, "_commit", commit_boundary)
        set_state = telegram_store.set_state

        def offset_boundary(key, value):
            if key == poller.OFFSET_KEY:
                pause("before_offset")
            return set_state(key, value)

        patch.setattr(telegram_store, "set_state", offset_boundary)
        rig.before_send = lambda: pause("before_send")
        rig.before_ack = lambda: pause("before_ack")
        send = rig.provider.send

        def returned(*args, **kwargs):
            answer = send(*args, **kwargs)
            pause("after_send")
            return answer

        rig.provider.send = returned
        rig.provider._ids = iter(config.get("message_ids", [501]))
        operation = config["operation"]
        try:
            if operation == "prepare":
                context = s.inputs(config["profile"]) if "profile" in config else rig.initial
                result = rig.coordinator.prepare(context)
                outcome = ["prepare", result.record.revision]
            elif operation == "present":
                result, = rig.present()
                outcome = ["present", result.state, result.message_id]
            elif operation == "attempt":
                send_id = config["send_id"]
                seen = rig.ledger.send(send_id, stream=rig.initial.stream)
                pause("read_attempt")
                result, won = rig.ledger.start_attempt(
                    send_id, expected_attempts=seen.attempts, resend=config.get("resend", False),
                    stream=rig.initial.stream,
                )
                if won:
                    rig.provider.send(int(v.CHAT), result.intent.text)
                outcome = ["attempt", won, result.attempts, len(rig.provider.sent)]
            elif operation == "send":
                intent = rig.ledger.send(config["send_id"], stream=rig.initial.stream).intent
                result = rig.edge._send(intent, rig.ledger.send(intent.send_id, stream=rig.initial.stream),
                                        resend=config.get("resend", False))
                outcome = ["send", result.state, result.message_id, len(rig.provider.sent)]
            elif operation == "append":
                result = rig.append(c.receipt_from_json(config["receipt"]))
                outcome = ["append", result.result.status, result.result.revision,
                           None if result.result.code is None else result.result.code.value]
            elif operation == "pull":
                rig.pull(config["update"])
                outcome = ["pull", rig.offset(), len(rig.provider.sent), len(rig.provider.callbacks)]
            elif operation == "ack":
                checked = rig.check()
                pause("consumer_effect")  # external consumer marker, not an application invocation
                result = rig.coordinator.acknowledge_consumption(rig.context(), checked=checked)
                outcome = ["ack", result]
            else:
                raise ValueError("unknown synthetic operation")
            _emit(outcome)
        except Exception as error:
            _emit(["error", type(error).__name__, getattr(error, "guard", None)])
        finally:
            for engine in db.engines:
                engine.dispose()


if __name__ == "__main__":
    _run(json.loads(sys.stdin.readline()))
