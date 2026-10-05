"""epd_leftovers (configs/epd/bin/leftovers.py): every claim, worktree, branch and dev environment the
build machinery left, whether something live still needs it, and why it stayed.

One small world in tmp_path: a git origin and its clone with worktrees, bets' state.json files,
claims, a fake `ssh` on PATH standing in for the forced-command standee key (it answers
`standee ls --json` and `standee doctor --json` from files), and a local runs API. The script runs
in-process, the way the agent runs it, and its JSON line is read back.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import http.server
import importlib.util
import json
import os
import re
import socket
import subprocess
import threading
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "configs" / "epd" / "bin" / "leftovers.py"
EPD_LOOP = ROOT / "configs" / "epd" / "bin" / "epd_loop.py"


def load():
    spec = importlib.util.spec_from_file_location("leftovers_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


leftovers = load()

NOW = dt.datetime.now(dt.UTC)
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=master",
       "-c", "commit.gpgsign=false"]

FAKE_SSH = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
d = Path(os.environ["FAKE_STANDEE"])
args = sys.argv[1:]
key = args[args.index("-i") + 1]
host = next(i for i, a in enumerate(args) if "@" in a)
cmd = args[host + 1:]
with open(d / "calls.log", "a") as f:
    f.write(json.dumps({"cmd": cmd, "key": key, "key_mode": oct(os.stat(key).st_mode & 0o777),
                        "key_is_copy": Path(key).read_bytes() == Path(os.environ["FAKE_KEY_SRC"]).read_bytes()}) + "\n")
if (d / "unreachable").exists():
    print("ssh: connect to host host.docker.internal port 22: Connection refused", file=sys.stderr)
    sys.exit(255)
if cmd == ["standee", "ls", "--json"]:
    sys.stdout.write((d / "ls.json").read_text())
    sys.exit(0)
if cmd == ["standee", "doctor", "--json"]:
    sys.stdout.write((d / "doctor.json").read_text())
    sys.exit(1)  # doctor exits 1 when any check fails; its JSON is the answer either way
print("standee-only: unexpected " + " ".join(cmd), file=sys.stderr)
sys.exit(2)
'''


def git(*args, cwd=None):
    done = subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True)
    assert done.returncode == 0, f"git {args}: {done.stderr}"
    return done.stdout


def commit(wt: Path, name: str) -> None:
    (wt / name).write_text(name + "\n")
    git("add", "-A", cwd=wt)
    git("commit", "-q", "-m", name, cwd=wt)


def iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


class RunsAPI:
    """GET /api/workflows/<id> from a dict; 404 for the rest."""

    def __init__(self, runs: dict):
        runs_ = runs

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                m = re.fullmatch(r"/api/workflows/([^/]+)", self.path)
                run = runs_.get(m.group(1)) if m else None
                body = json.dumps(run if run else {"detail": "not found"}).encode()
                self.send_response(200 if run else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def dead_url() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


@pytest.fixture
def world(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    repos = ws / "repos"
    app = repos / "app"
    (app / "claims" / "released").mkdir(parents=True)
    (app / "worktrees").mkdir()

    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", str(origin))
    seed = tmp_path / "seed"
    git("clone", "-q", str(origin), str(seed))
    commit(seed, "README")
    git("push", "-q", "origin", "master", cwd=seed)
    main = app / "main"
    git("clone", "-q", str(origin), str(main))

    def worktree(slug: str) -> Path:
        wt = app / "worktrees" / slug
        git("worktree", "add", "-q", "-b", slug, str(wt), "origin/master", cwd=main)
        return wt

    def claim(slug: str, run_id: str | None = None, days_ago: float = 2) -> None:
        (app / "claims" / f"{slug}.json").write_text(json.dumps({
            "status": "worktree_ready", "task_slug": slug, "branch": slug, "run_id": run_id,
            "claimed_at": iso(NOW - dt.timedelta(days=days_ago)), "root": str(app)}))

    def bet(bet_id: str, status: str, **state) -> None:
        d = ws / "epd" / "app" / "bets" / bet_id
        d.mkdir(parents=True)
        (d / "state.json").write_text(json.dumps({"status": status, **state}))

    # EPD bets: their items go by the bet's status.
    bet("b001", "pr_opened")                                   # a. live
    claim("epd-b001")
    wt = worktree("epd-b001")
    commit(wt, "b001")
    git("push", "-q", "origin", "epd-b001", cwd=wt)
    bet("b002", "shipped")                                     # b. merged, measure pending
    claim("epd-b002")
    bet("b003", "kept")                                        # c. finished, worktree still there
    claim("epd-b003", days_ago=9)
    wt = worktree("epd-b003")
    commit(wt, "b003")
    git("push", "-q", "origin", "epd-b003", cwd=wt)            # pushed: a sweep would lose nothing
    bet("b004", "stopped")                                     # d. + i. unpushed commits
    claim("epd-b004")
    commit(worktree("epd-b004"), "b004")
    bet("b005", "stopped", held={"since": iso(NOW - dt.timedelta(days=1)),  # n. collected with --keep
                                  "why": "collected with --keep: kept for a hand fix"})
    claim("epd-b005")
    commit(worktree("epd-b005"), "b005")                       # the hand fix goes on here, unpushed

    # Other claims: their items go by their run.
    claim("linear-roa-1", "r-linear")                          # e. finished linear_work
    worktree("linear-roa-1")
    claim("fix-thing", "r-running")                            # f. running
    claim("old-task", "r-done", days_ago=5)                    # finished epd_task: leftover, systems
    (worktree("old-task") / "notes.txt").write_text("not committed\n")  # h. uncommitted
    claim("lost-task", "r-missing")                            # the API does not know it
    worktree("orphan-wt")                                      # no claim names it
    git("branch", "stray", "origin/master", cwd=main)          # j. no worktree, no claim
    broken = app / "worktrees" / "broken-wt"                   # records that do not resolve
    broken.mkdir()
    (broken / ".git").write_text("gitdir: /nonexistent/main/.git/worktrees/broken-wt\n")
    (app / "claims" / "released" / "epd-b009.json").write_text(json.dumps({"task_slug": "epd-b009"}))  # m.

    runs = RunsAPI({
        "r-linear": {"status": "completed", "workflow_name": "linear_work", "end_time": iso(NOW)},
        "r-running": {"status": "running", "workflow_name": "epd_task", "end_time": None},
        "r-done": {"status": "completed", "workflow_name": "epd_task", "end_time": iso(NOW)},
    })

    fake = tmp_path / "standee"
    fake.mkdir()
    env = lambda name, **kw: {"name": name, "kind": "managed", "tier": "dev", "project": "app",  # noqa: E731
                              "status": "up", "created_at": iso(NOW - dt.timedelta(days=1)), **kw}
    (fake / "ls.json").write_text(json.dumps({"entries": [
        env("app-dev-epd-b001", ttl="8h", expires_at=iso(NOW + dt.timedelta(hours=4))),   # l.
        env("app-dev-epd-b003", ttl="8h", expires_at=iso(NOW + dt.timedelta(hours=4))),   # k.
        env("app-dev-epd-b005", ttl="8h", expires_at=iso(NOW + dt.timedelta(hours=4))),   # n.
        env("app-dev-scratch", ttl="3d", expires_at=iso(NOW + dt.timedelta(days=2))),
        env("app-dev-old", ttl="8h", expires_at=iso(NOW - dt.timedelta(days=2))),
        env("app-dev-forever", ttl=None, expires_at=None),
        {"name": "app-prod", "kind": "managed", "tier": "prod", "project": "app", "status": "up"},
        {"name": "temper", "kind": "route", "tier": None, "status": "up"},
    ]}))
    (fake / "doctor.json").write_text(json.dumps([
        {"area": "disk", "name": "images", "level": "ok", "detail": "1 GB", "hint": None},
        {"area": "disk", "name": "volumes", "level": "warn", "detail": "7 volume(s) attached to nothing",
         "hint": "`docker volume ls -f dangling=true`; remove what you recognise"},
    ]))
    keydir = tmp_path / "standee-ssh"
    keydir.mkdir()
    (keydir / "id_ed25519").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nZmFrZS1rZXktZm9yLXRlc3Rz\n"
                                       "-----END OPENSSH PRIVATE KEY-----\n")
    (keydir / "known_hosts").write_text("")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "ssh").write_text(FAKE_SSH)
    (bindir / "ssh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_STANDEE", str(fake))
    monkeypatch.setenv("FAKE_KEY_SRC", str(keydir / "id_ed25519"))

    w = {"tmp": tmp_path, "ws": ws, "repos": repos, "main": main, "runs": runs, "fake": fake, "keydir": keydir,
         "origin": origin}
    yield w
    runs.close()


def run(world, capsys, server_url=None, repos=None):
    code = leftovers.main(["--workspaces-root", str(repos or world["repos"]),
                           "--server-url", server_url or world["runs"].url,
                           "--standee-ssh-dir", str(world["keydir"])])
    out = capsys.readouterr().out
    result = json.loads(out.strip().splitlines()[-1])
    return code, result, out


def item(result, kind, name):
    found = [i for i in result["items"] if i["kind"] == kind and i["name"] == name]
    assert len(found) == 1, f"{kind} {name}: {len(found)} items"
    return found[0]


def test_each_item_gets_its_class_reason_and_fix_owner(world, capsys):
    code, result, _ = run(world, capsys)
    assert code == 0 and result["status"] == "ok"

    # a. a bet being built: its claim, worktree and branch are in use
    for kind in ("claim", "worktree", "branch"):
        assert item(result, kind, "epd-b001")["class"] == "in_use"
    # b. shipped, its measure still to run
    assert item(result, "claim", "epd-b002")["class"] == "in_use"
    # c. a kept bet whose worktree is still there: RollCall's leftover, safe to sweep
    for kind in ("claim", "worktree", "branch"):
        i = item(result, kind, "epd-b003")
        assert (i["class"], i["fix_owner"]) == ("leftover", "RollCall")
        assert "kept" in i["reason"] and "release_task" in i["reason"]
    assert item(result, "worktree", "epd-b003")["not_sweepable"] is False
    assert item(result, "claim", "epd-b003")["age_days"] == pytest.approx(9, abs=0.2)
    # d. a stopped bet
    i = item(result, "claim", "epd-b004")
    assert (i["class"], i["fix_owner"]) == ("leftover", "RollCall") and "stopped" in i["reason"]
    assert i["evidence"]["bet_status"] == "stopped" and i["evidence"]["state_changed"]
    assert "held" not in i["reason"] and "held_since" not in i["evidence"]
    # n. a stopped bet held for a hand fix: kept on purpose, RollCall's, with when and why
    for kind in ("claim", "worktree", "branch", "env"):
        name = "app-dev-epd-b005" if kind == "env" else "epd-b005"
        i = item(result, kind, name)
        assert (i["class"], i["fix_owner"]) == ("kept_by_design", "RollCall"), kind
        assert "held since" in i["reason"] and "kept for a hand fix" in i["reason"]
        assert i["evidence"]["bet_status"] == "stopped" and i["evidence"]["held_since"]
    assert item(result, "worktree", "epd-b005")["not_sweepable"] is True  # its commit is not pushed
    # e. a finished linear_work run keeps its task on purpose: temper's
    for kind in ("claim", "worktree", "branch"):
        i = item(result, kind, "linear-roa-1")
        assert (i["class"], i["fix_owner"]) == ("kept_by_design", "temper")
        assert i["evidence"]["run_id"] == "r-linear" and i["evidence"]["workflow"] == "linear_work"
    # f. a running run
    assert item(result, "claim", "fix-thing")["class"] == "in_use"
    # a finished run of a workflow that does not keep its task: systems' leftover
    i = item(result, "claim", "old-task")
    assert (i["class"], i["fix_owner"]) == ("leftover", "systems") and "r-done"[:8] in i["reason"]
    # a run the API does not know: unknown, with the run id, never a guess
    i = item(result, "claim", "lost-task")
    assert i["class"] == "unknown" and i["fix_owner"] is None and "r-missing" in i["reason"]
    # m. released claims are history
    assert not [x for x in result["items"] if x["name"] == "epd-b009"]


def test_worktrees_and_branches_say_whether_a_sweep_would_lose_work(world, capsys):
    _, result, _ = run(world, capsys)
    # h. uncommitted changes
    i = item(result, "worktree", "old-task")
    assert i["class"] == "leftover" and i["uncommitted"] == 1 and i["not_sweepable"] is True
    assert i["branch_safe"] is True  # nothing committed yet: everything is on origin/master
    # i. unpushed commits
    i = item(result, "worktree", "epd-b004")
    assert i["class"] == "leftover" and i["uncommitted"] == 0 and i["branch_safe"] is False
    assert i["not_sweepable"] is True and i["evidence"]["ahead_of_origin_base"] == 1
    assert item(result, "branch", "epd-b004")["not_sweepable"] is True
    # a pushed branch is safe
    assert item(result, "branch", "epd-b003")["branch_safe"] is True
    assert item(result, "branch", "epd-b003")["evidence"]["on_origin"] is True
    # a worktree no claim names
    i = item(result, "worktree", "orphan-wt")
    assert (i["class"], i["fix_owner"]) == ("leftover", "systems") and "no claim" in i["reason"]
    # j. a branch with no worktree and no claim
    i = item(result, "branch", "stray")
    assert (i["class"], i["fix_owner"]) == ("leftover", "systems") and "no worktree" in i["reason"]
    # git records that do not resolve: unknown, with the path
    i = item(result, "worktree", "broken-wt")
    assert i["class"] == "unknown" and "broken-wt" in i["evidence"]["path"] and "do not resolve" in i["reason"]
    # the base branch is not an item
    assert not [x for x in result["items"] if x["kind"] == "branch" and x["name"] == "master"]


def test_dev_environments_follow_their_bet_or_their_ttl(world, capsys):
    _, result, _ = run(world, capsys)
    envs = {i["name"]: i for i in result["items"] if i["kind"] == "env"}
    assert set(envs) == {"app-dev-epd-b001", "app-dev-epd-b003", "app-dev-epd-b005", "app-dev-scratch", "app-dev-old",
                         "app-dev-forever"}
    assert envs["app-dev-epd-b001"]["class"] == "in_use"                                # l.
    assert (envs["app-dev-epd-b003"]["class"], envs["app-dev-epd-b003"]["fix_owner"]) == ("leftover", "RollCall")  # k.
    assert envs["app-dev-epd-b003"]["expires_at"]
    assert envs["app-dev-scratch"]["class"] == "kept_by_design"                         # standee takes it down
    assert (envs["app-dev-old"]["class"], envs["app-dev-old"]["fix_owner"]) == ("leftover", "systems")
    assert envs["app-dev-forever"]["class"] == "leftover" and "no ttl" in envs["app-dev-forever"]["reason"]
    assert result["volumes_attached_to_nothing"] == 7


def test_the_counts_and_the_report_file(world, capsys):
    _, result, out = run(world, capsys)
    assert sum(result["counts"].values()) == len(result["items"])
    assert result["counts"]["leftover"] == len([i for i in result["items"] if i["class"] == "leftover"])
    assert result["leftovers_by_fix_owner"]["RollCall"] == 7  # b003 x3 + b004 x3 + env b003
    reports = list((world["ws"] / "leftovers").glob("*.json"))
    assert [str(p) for p in reports] == [result["report_path"]]
    saved = json.loads(reports[0].read_text())
    assert saved["items"] == result["items"] and saved["counts"] == result["counts"]
    assert result["leftovers_by_fix_owner"]["systems"] == 8  # old-task x3, orphan-wt x2, stray, 2 envs
    for i in result["items"]:
        assert i["class"] in leftovers.CLASSES and i["reason"]
        if i["class"] == "leftover":
            assert i["fix_owner"] in ("systems", "RollCall", "temper")
        if i["class"] in ("in_use", "unknown"):
            assert i["fix_owner"] is None
    assert "items:" in out and "leftover" in out


def test_an_unreachable_runs_api_makes_its_claims_unknown(world, capsys):
    code, result, _ = run(world, capsys, server_url=dead_url())  # g.
    assert code == 0
    for slug in ("linear-roa-1", "fix-thing", "old-task", "lost-task"):
        i = item(result, "claim", slug)
        assert i["class"] == "unknown" and "unreachable" in i["reason"]
    assert item(result, "worktree", "linear-roa-1")["class"] == "unknown"
    assert item(result, "claim", "epd-b001")["class"] == "in_use"  # the bets still answer


def test_unreachable_standee_fails_loud(world, capsys):
    (world["fake"] / "unreachable").write_text("")  # n.
    code, result, _ = run(world, capsys)
    assert code == 1 and result["status"] == "failed"
    assert "standee unreachable" in result["error"] and "Connection refused" in result["error"]
    assert not (world["ws"] / "leftovers").exists()


def test_a_source_it_cannot_read_fails_loud(world, capsys, tmp_path):
    code, result, _ = run(world, capsys, repos=tmp_path / "nowhere")
    assert code == 1 and "does not exist" in result["error"]
    (world["repos"] / "app" / "claims" / "bad.json").write_text("{not json")
    code, result, _ = run(world, capsys)
    assert code == 1 and "bad.json" in result["error"]
    (world["fake"] / "doctor.json").write_text("[]")
    (world["repos"] / "app" / "claims" / "bad.json").unlink()
    code, result, _ = run(world, capsys)
    assert code == 1 and "volumes" in result["error"]


def test_empty_workspaces_give_no_items(world, capsys, tmp_path):
    empty = tmp_path / "empty" / "repos"  # o.
    empty.mkdir(parents=True)
    (world["fake"] / "ls.json").write_text(json.dumps({"entries": []}))
    (world["fake"] / "doctor.json").write_text(json.dumps([{"area": "disk", "name": "volumes", "level": "ok",
                                                            "detail": "no orphans", "hint": None}]))
    code, result, _ = run(world, capsys, repos=empty)
    assert code == 0 and result["items"] == [] and result["volumes_attached_to_nothing"] == 0
    assert result["counts"] == {c: 0 for c in leftovers.CLASSES}


def tree(*roots: Path, skip: Path) -> dict:
    out = {}
    for root in roots:
        for p in sorted(root.rglob("*")):
            if p == skip or skip in p.parents:
                continue
            s = p.lstat()
            out[str(p)] = (s.st_mode, s.st_size, s.st_mtime_ns,
                           hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
    return out


def test_it_changes_nothing_it_audits_and_keeps_the_key_to_itself(world, capsys):
    before = tree(world["ws"], world["origin"], skip=world["ws"] / "leftovers")  # p.
    _, result, out = run(world, capsys)
    assert tree(world["ws"], world["origin"], skip=world["ws"] / "leftovers") == before
    # standee: the two read-only commands, nothing else, over a 0600 copy of the key removed on exit
    calls = [json.loads(line) for line in (world["fake"] / "calls.log").read_text().splitlines()]
    assert sorted(" ".join(c["cmd"]) for c in calls) == ["standee doctor --json", "standee ls --json"]
    for c in calls:
        assert c["key_mode"] == "0o600" and c["key_is_copy"]
        assert not Path(c["key"]).exists()
    report = Path(result["report_path"]).read_text()
    for text in (out, report):
        assert "PRIVATE KEY" not in text and "ZmFrZS1rZXktZm9yLXRlc3Rz" not in text


def test_its_statuses_match_epd_loop():
    """The bet statuses are epd_loop.py's own sets: a status added there must be placed here."""
    source = EPD_LOOP.read_text()

    def literal(name):
        m = re.search(rf"^{name} = (\{{[^}}]*\}})", source, re.M)
        assert m, f"epd_loop.py has no top-level {name}"
        return ast.literal_eval(m.group(1))

    assert literal("LIVE") == leftovers.LIVE
    assert literal("TERMINAL") == leftovers.TERMINAL


def test_it_reads_the_held_mark_epd_loop_writes():
    """collect --keep marks a stopped bet held in its state.json; the audit keys on that exact shape."""
    source = EPD_LOOP.read_text()
    assert re.search(r'st\["held"\] = \{"since": [^,]+, "why": ', source), "epd_loop.py no longer writes held"
    assert 'st.pop("held", None)' in source  # collecting it again without --keep drops it


def test_the_workflows_that_keep_their_task_are_the_ones_it_knows():
    """Every workflow that runs a node with keep: true (epd_loop's items go by their bet instead)."""
    keeping = set()
    for path in (ROOT / "configs").rglob("*.yaml"):
        if "local" in path.parts:
            continue
        doc = yaml.safe_load(path.read_text())
        wf = doc.get("workflow") if isinstance(doc, dict) else None
        if not isinstance(wf, dict):
            continue
        for node in wf.get("nodes") or []:
            if isinstance(node, dict) and (node.get("input_map") or {}).get("keep") is True:
                keeping.add(wf["name"])
    assert keeping - {"epd_loop"} == leftovers.KEEPS_TASK
