"""What happens after master moves: it goes live, or it goes back.

The ordinary path is short. master moved, so wait until the live temper has
had no run going for two minutes, then ask ``temper-deploy restart`` for a
restart. The wait is temper-ci's own: temper-deploy restarts at once when
runs live in boxes (they carry on in their boxes), but nothing may restart
the live temper under a run that is going. Several lands that arrive while
it waits join one deploy. When it has restarted, look at the live temper for real: its
own check, its hooks, one free run, the dashboard, and then, on runs of its own, an
ordinary run's box environment and the owner's own controls: stop and resume, and a
gate answered through the API (live_checks.py). Every run it starts is quiet (notify off) and tidied away,
pass or fail. The Pi pins are looked at too, and shown, but never counted.

The look never runs beside someone else's run. A part that had to step aside for one is
owed: temper stays on the new commit, but it is not recorded as the good one to go back
to until the owed parts have passed, tried again once no run is going (settle_owed),
before any newer commit is deployed on top. A part that fails then fails the look like
any other. Owed is never a pass (Security, reply to rm-e71dc2dc): a record of what is
owed that is missing or cannot be read fails it. Step-asides never fail it, however
many; after the first, retries wait for five quiet minutes instead of two. A revert
needs quiet too, so trying an untried commit beats reverting it blind.

That look is the only look at the code once it lands. There is one temper,
the live one, and no test copy of it; GitHub's lint, types and tests are
what stands in front of master.

The unhappy path is the point of all this. If the live check fails, master
does not move backwards — a revert commit goes on top, through the same
gate as everything else. That revert's files are exactly those of the last
commit that was live and well. Then temper restarts onto it, and the owner
gets a DM saying what failed and what was taken back out. If runs are going
by then, the revert waits for them like any deploy, and the DM says so.

Whichever way a failure goes, it is said once. The commit is written down as
handled, and the watcher leaves it alone until master moves on; only a person
running ``temper-ci deploy`` tries the same commit again.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import time
from collections.abc import Collection
from pathlib import Path

from . import gate, live_checks, paths, report
from .paths import DEPLOY_STATE, MAIN_REPO, log, read_json, sh, stamp, write_json

DEPLOY_DIR = Path.home() / ".local/state/temper-deploy"
# temper-deploy's own record of the last restart it did: whose, when, and how the checks went.
# temper-ci reads it rather than keeping a second account of the same thing.
LAST_RESTART = Path.home() / ".local/state/temper-deploy/last-restart.json"
TEMPER_DEPLOY = Path.home() / ".local/bin/temper-deploy"
LIVE_PORT_DEFAULT = 8420            # what docker-compose.yml publishes
RESTART_PATIENCE = 60 * 60          # an hour: a long run may be going
# A deploy (or a revert) waits while any run on the live temper is in one of these: the
# server's own list of runs that are not over yet. "waiting" is a run parked at a gate or on a
# person's answer; it is not over, so it holds the deploy too.
LIVE_STATUSES = ("pending", "queued", "running", "waiting", "cancelling")
# A deploy goes only once the live temper has had no run going for this long: a run that ends
# and the next one that starts a moment later (a run of runs) is not a quiet temper. The same
# two minutes temper-deploy itself waited for, before runs lived in boxes.
QUIET_SECONDS = 120
LIVE_CHECK_RUNS = live_checks.FREE_RUN_WORKFLOW   # $0, script agents only; the dashboard shows it
# After a step-aside, wait longer: back-to-back runs can leave gaps of 2.5–3 minutes,
# just long enough for the ordinary wait but not for the look's own ~85 seconds of runs.
# Step-asides never fail or revert a commit: a revert needs the same quiet as a fresh look.
OWED_QUIET_SECONDS = 300
# The name temper-ci's key goes by on the live temper (GET /api/guard lists it): the caller a
# gate answered by the live look must be recorded under.
CI_CALLER = "temper-ci"
# temper-ci's own key for the live check's run start (docs/api-access.md): a file on the host,
# outside every folder mounted into temper's containers. No file, no key: fine until the
# server's write guard is set to enforce.
CI_KEY_FILE = Path.home() / ".config/temper/api-keys/temper-ci.key"
# The Pi pins (M4 ADR-M4-04, SW-50; docs/pi-lane.md, "The pins"): temper's own host command,
# model-free and read-only, run from the live checkout after every deploy.
PIN_CHECK = MAIN_REPO / "scripts" / "pi_pins_check.py"
PIN_CHECK_TIMEOUT = 120             # it stops itself at 60 s; this is the backstop
PIN_CHECK_PART = "the Pi pins"
# What its exit codes mean, when the JSON it prints says the same thing.
PIN_RESULTS = {0: "pass", 1: "mismatch", 3: "not_set_up"}


def ci_key_headers(key_file: Path = CI_KEY_FILE) -> dict[str, str]:
    """The Authorization header for temper-ci's writes, or none when it has no key."""
    try:
        key = key_file.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    return {"Authorization": f"Bearer {key}"} if key else {}


def live_api() -> str:
    """Where the live temper actually is \u2014 asked, not assumed.

    This was hard-coded to port 8000 and the live server is on 8420, so every
    part of the live check that spoke to the API failed, on every deploy,
    whatever the deploy had done. A check that always says no would have
    reverted good code for ever \u2014 the most expensive kind of wrong, because it
    looks like caution.

    So ask docker what the live server publishes, and keep the compose file's
    port only as the answer when there is nothing to ask.
    """
    r = sh("docker", "port", "temper-ai-server-1", "8420/tcp", timeout=30)
    if r.returncode == 0 and r.stdout.strip():
        # "127.0.0.1:8420" \u2014 possibly several lines, one per family.
        first = r.stdout.strip().splitlines()[0].strip()
        port = first.rsplit(":", 1)[-1]
        if port.isdigit():
            return f"http://127.0.0.1:{port}"
    return f"http://127.0.0.1:{LIVE_PORT_DEFAULT}"


def state() -> dict:
    return read_json(DEPLOY_STATE, {}) or {}


def state_unreadable() -> bool:
    """deploy.json is there, but cannot be read: which commit is good, and what a live check
    still owes, are lost with it."""
    return DEPLOY_STATE.exists() and not isinstance(read_json(DEPLOY_STATE, None), dict)


def save(data: dict) -> None:
    write_json(DEPLOY_STATE, data)


def master_sha() -> str:
    return sh("git", "-C", str(MAIN_REPO), "rev-parse", "refs/heads/master").stdout.strip()


# -- no restart under a run --------------------------------------------------

def _now() -> float:
    return time.time()


def runs_going() -> list[dict] | None:
    """The runs on the live temper that are not over yet; None when the API could not say."""
    import urllib.request
    api = live_api()
    going: list[dict] = []
    try:
        for status in LIVE_STATUSES:
            url = f"{api}/api/workflows?status={status}&limit=20"
            with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310 - loopback
                rows = json.loads(resp.read()).get("runs") or []
            going += [{"id": str(r.get("id") or ""), "workflow": str(r.get("workflow_name") or ""),
                       "status": str(r.get("status") or status)} for r in rows]
    except Exception as exc:  # noqa: BLE001 - not knowing counts as runs going
        log(f"could not ask the live temper which runs are going: {type(exc).__name__}: {exc}")
        return None
    return going


def _said(going: list[dict] | None) -> str:
    if going is None:
        return "the live temper could not say which runs are going"
    names = ", ".join(f"{r['workflow'] or '?'} {r['id'][:8]} ({r['status']})" for r in going[:5])
    more = f" and {len(going) - 5} more" if len(going) > 5 else ""
    return f"runs going on the live temper: {names}{more}"


def held_for_runs(data: dict, what: str, quiet_seconds: int | None = None) -> bool:
    """Should the deploy (or revert) of ``what`` wait? Keeps ``data["hold"]`` up to date.

    It waits while any run is going, and while the live temper cannot say; then it goes once
    the temper has been quiet for ``quiet_seconds`` in a row (QUIET_SECONDS by default).
    Owed retries use OWED_QUIET_SECONDS. A run that starts meanwhile starts the quiet over.
    A person running ``temper-ci deploy`` is not held: that is their call.
    """
    if quiet_seconds is None:
        quiet_seconds = QUIET_SECONDS
    going = runs_going()
    hold = data.get("hold") or {}
    if going is None or going:
        why = _said(going)
        if not hold or hold.get("quiet_since") is not None:
            log(f"{what}: held — {why}")
        elif hold.get("why") != why:
            log(f"{what}: still held — {why}")
        data["hold"] = {"for": what, "since": hold.get("since") or stamp(), "why": why,
                        "quiet_since": None}
        save(data)
        return True
    if quiet_seconds <= 0:
        if hold:
            data.pop("hold", None)
            save(data)
        return False
    quiet_why = f"no run going; it goes once that has lasted {quiet_seconds} seconds"
    if hold.get("quiet_since") is None:
        data["hold"] = {"for": what, "since": hold.get("since") or stamp(),
                        "why": quiet_why, "quiet_since": _now()}
        save(data)
        log(f"{what}: no run is going; it goes once that has lasted {quiet_seconds} seconds")
        return True
    if _now() - float(hold["quiet_since"]) < quiet_seconds:
        if hold.get("for") != what or hold.get("why") != quiet_why:
            data["hold"] = {**hold, "for": what, "why": quiet_why}
            save(data)
        return True
    data.pop("hold", None)
    save(data)
    log(f"{what}: no run for {quiet_seconds} seconds; going ahead (held since {hold.get('since')})")
    return False


# -- the live look -----------------------------------------------------------

def _temper_deploy(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return sh("python3", str(TEMPER_DEPLOY), *args, timeout=timeout)


def live_check(shots: Path) -> dict:
    """Seven questions of the temper that is actually serving people, and the Pi pins.

    The seven count: any one failing fails the live check (``ok``), and that reverts the
    deploy. One that stepped aside for someone else's run is owed instead (``owed``, see
    settle_owed). The pins are information only (see pin_check): shown in the report and
    ``temper-ci status``, never in ``ok``.
    """
    out: dict = {"at": stamp(), "parts": [], "ok": True, "owed": [], "shots": []}

    def part(name: str, ok: bool, detail: str) -> None:
        _count(out, {"name": name, "ok": ok, "detail": detail[:600]})

    r = _temper_deploy("check")
    part("temper-deploy check", r.returncode == 0, (r.stdout or r.stderr).strip())

    r = _temper_deploy("hooks")
    part("temper-deploy hooks", r.returncode == 0, (r.stdout or r.stderr).strip())

    api = live_api()
    out["api"] = api
    _with_runs(out, shots, api, ci_key_headers())

    # Not through _count(): whatever it says, it never touches out["ok"].
    out["parts"].append(pin_check())
    return out


def _count(out: dict, result: dict) -> None:
    """Put a part that counts on the look: one that failed fails it, one owed is owed."""
    out["parts"].append(result)
    if result.get("owed"):
        out["owed"].append(str(result["name"]))
    elif not result.get("ok"):
        out["ok"] = False


def _with_runs(out: dict, shots: Path, api: str, headers: dict[str, str],
               only: Collection[str] | None = None) -> None:
    """The parts that start runs of their own, and the dashboard: all of them, or only the
    ones named in ``only`` (the dashboard goes with the free run)."""
    if only is None or live_checks.FREE_RUN in only:
        # One free run, in a box, on the live server — the same thing a person
        # would do first: does it still run anything at all? Quiet, and tidied away if it
        # does not end (live_checks.py).
        free = live_checks.run_one(live_checks.FREE_RUN, live_checks.free_run,
                                   live_checks.Live(api, dict(headers)))
        _count(out, free)
        # The run it just made is what the list must show. With none made (someone else's
        # run was going) the page only has to come up; it is looked at again with the free run.
        _dashboard(out, shots, api, expect=not free.get("owed"))

    # Then what the owner does to his own runs, each on a $0 run of its own: the box's
    # environment, stop and resume, a gate answered through the API. After the dashboard, so
    # its picture is taken with the free run on top. Each tidies its own runs before its verdict.
    for result in live_checks.run_all(api, headers, CI_CALLER, only=only):
        _count(out, result)


def _dashboard(out: dict, shots: Path, api: str, *, expect: bool) -> None:
    """The dashboard, photographed. It lives under /app — its router's basename. The API's
    own root is a 404 by design, and photographing that was once counted as the page being
    fine."""
    shots.mkdir(parents=True, exist_ok=True)
    target = shots / "live-dashboard.png"
    # A picture left by an earlier look must not pass for this one's.
    target.unlink(missing_ok=True)
    args = ["python3", str(Path(__file__).with_name("shot.py")), f"{api}/app/", str(target)]
    if expect:
        args += ["--expect", LIVE_CHECK_RUNS]
    r = sh(*args, timeout=180)
    took = target.exists()
    if took and str(target) not in out["shots"]:
        out["shots"].append(str(target))
    _count(out, {"name": "the dashboard", "ok": r.returncode == 0 and took,
                 "detail": ("it showed the workflow list" if r.returncode == 0
                            else ((r.stdout or "").strip().splitlines()[-1:]
                                  or [(r.stderr or "").strip()])[0][:300])})


def pin_check() -> dict:
    """The Pi pin check, as a part of the live check that is shown and never counted.

    It says one of four things: the pins match; a mismatch, naming the pins; not set up (no
    private box config yet, so the Pi lane isn't configured on this host); or it couldn't run
    (no answer within PIN_CHECK_TIMEOUT, or a crash), with the reason.

    Never counted, whatever it says. A failed part of the live check reverts the deploy, and
    taking good code back out puts no pin right; the Pi lane's own preflight already refuses
    every Pi run while a pin is off (ADR-M4-04). Only what the command prints is shown: pin
    names and digests, never a path or a secret.
    """
    try:
        result, detail = _pin_check()
    except Exception as exc:  # noqa: BLE001 - this part must never break the live check
        result, detail = "couldnt_run", f"couldn't run: {type(exc).__name__}: {exc}"
    return {"name": PIN_CHECK_PART, "ok": result == "pass", "info": True,
            "result": result, "detail": detail[:600]}


def _pin_check() -> tuple[str, str]:
    if not PIN_CHECK.is_file():
        return "couldnt_run", f"couldn't run: this checkout has no scripts/{PIN_CHECK.name}"
    try:
        r = sh("python3", str(PIN_CHECK), "--json", cwd=PIN_CHECK.parent.parent,
               timeout=PIN_CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "couldnt_run", f"couldn't run: no answer within {PIN_CHECK_TIMEOUT} s"
    said = _json_object(r.stdout)
    result = str(said.get("result") or "")
    # A crash exits 1 as well, so a mismatch is only one when the JSON says so too.
    if PIN_RESULTS.get(r.returncode) != result:
        why = (str(said.get("error") or "") or _last_line(r.stderr)
               or (f"it said {result}" if result else _last_line(r.stdout))
               or "it printed nothing")
        return "couldnt_run", f"couldn't run (exit {r.returncode}): {why}"
    pins = [p for p in said.get("pins") or [] if isinstance(p, dict)]
    if result == "pass":
        return "pass", f"pass: all {len(pins)} pins match"
    if result == "not_set_up":
        return "not_set_up", ("not set up: there is no private box config yet, so the Pi lane "
                              "isn't configured on this host")
    bad = [p for p in pins if not p.get("ok")]
    lines = [f"mismatch: {len(bad)} of {len(pins)} pins: "
             + ", ".join(str(p.get("name")) for p in bad)]
    lines += [f"{p.get('name')}: want {_brief(p.get('want'))}, have {_brief(p.get('have'))}"
              for p in bad]
    return "mismatch", "\n".join(lines)


def _json_object(text: str | None) -> dict:
    """The JSON object a command printed (the whole of it, or its last line), else {}."""
    text = (text or "").strip()
    for candidate in (text, *text.splitlines()[-1:]):
        try:
            got = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(got, dict):
            return got
    return {}


def _last_line(text: str | None) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""


def _brief(value: object) -> str:
    """A pin's want or have, short enough that several fit in a part's 600 characters."""
    if value is None:
        return "nothing"
    if isinstance(value, list):
        return "[" + ", ".join(str(v) for v in value) + "]"
    text = str(value)
    return text if len(text) <= 24 else text[:19] + "…"


# -- restarting --------------------------------------------------------------

# temper-deploy's request: there while a restart is still to come, gone once it has been
# dealt with. Read, never written: like LAST_RESTART, it is temper-deploy's own account.
RESTART_REQUEST = DEPLOY_DIR / "request.json"
RESTART_POLL = 10                   # seconds between looks at those two files


def ask_restart(sha: str, why: str) -> str:
    """Ask for a restart and say which commit has to be live after it.

    `--commit` is temper-deploy's own check that the restart really carried
    this change: it refuses if the checkout is not that commit or newer.
    Returns what temper-deploy answered.
    """
    r = _temper_deploy("restart", "--reason", why, "--commit", sha, timeout=120)
    answer = (r.stdout or r.stderr).strip()
    log(f"asked temper-deploy to restart for {sha[:12]}: {answer[:200]}")
    return answer


def restart_pending() -> bool:
    """Is a restart still to come? temper-deploy holds its request until it has dealt with it."""
    row = read_json(RESTART_REQUEST)
    return isinstance(row, dict) and bool(row.get("reasons"))


def carries(head: str, sha: str) -> bool:
    """Was ``sha`` in the code temper-deploy restarted on? ``head`` is that code's commit, short."""
    head = str(head or "").strip()
    if not head or not sha:
        return False
    if sha.startswith(head) or head.startswith(sha):
        return True
    # master moved on before the restart: it carried a later commit, with this one in it.
    r = sh("git", "-C", str(MAIN_REPO), "merge-base", "--is-ancestor", sha, head, timeout=60)
    return r.returncode == 0


def _record_time(row: dict) -> dt.datetime | None:
    try:
        at = dt.datetime.fromisoformat(str(row.get("at")))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=dt.UTC)


def restart_outcome(when: dt.datetime, sha: str = "") -> tuple[str, dict | None]:
    """Where a restart asked for at ``when`` stands, from temper-deploy's own two files.

    "restarted"     a restart that began after ``when`` is on record, on ``sha``,
                    and no other restart is still to come
    "waiting"       temper-deploy still holds a request: a restart is to come.
                    The record comes with it if our own restart is already done
    "already live"  the request was let go with no new restart, and the last one
                    already carried ``sha`` -- it was under way when we asked
    "let go"        the request was let go with no restart onto ``sha``: a rebuild
                    was needed, someone cancelled, or temper-deploy refused it

    Nothing counts while a restart is still to come, because looking at temper
    then can land in the middle of it. The old record used to count whenever
    it already named ``sha``, on the idea that there was then nothing to
    restart -- but temper-deploy restarts whenever it is asked, so on
    2026-10-03 the live check went in two seconds after asking, in the middle
    of the very restart it had asked for, and failed everything. Even our own
    restart's record waits while someone else's restart is queued behind it:
    temper-deploy starts that one straight after.

    The request is read before the record, on purpose: temper-deploy writes
    the record first and only then lets the request go, so a request already
    gone means any restart that dealt with it is on record by now.
    """
    pending = restart_pending()
    row = read_json(LAST_RESTART)
    if not isinstance(row, dict):
        row = None
    at = _record_time(row) if row else None
    newer = bool(at and at > when)
    on_sha = bool(row) and (carries(str(row.get("head") or ""), sha) if sha else newer)
    if pending:
        return "waiting", (row if newer and on_sha else None)
    if newer and on_sha:
        return "restarted", row
    if on_sha:
        return "already live", row
    return "let go", None


def restart_done_after(when: dt.datetime, sha: str = "") -> dict | None:
    """The restart record once temper is back on ``sha`` -- None until then, or if it never will be."""
    outcome, row = restart_outcome(when, sha)
    return row if outcome in ("restarted", "already live") else None


def wait_for_restart(since: dt.datetime, sha: str = "",
                     patience: int = RESTART_PATIENCE) -> dict | None:
    """Look every RESTART_POLL seconds until temper is back on ``sha``; return its record.

    None once it is plain there will be no restart onto ``sha``: at once when
    temper-deploy lets the request go without one, and after ``patience`` when
    a restart is still waiting by then. Waiting out the whole hour for a
    restart that is not coming would also stop the watcher -- a single loop --
    from checking anything pushed meanwhile. For the same reason, if our own
    restart is done but another one has sat waiting behind it for the whole
    ``patience``, it looks now rather than wait on.
    """
    deadline = time.monotonic() + patience
    while True:
        outcome, row = restart_outcome(since, sha)
        if row and outcome == "restarted":
            log(f"{sha[:12]}: temper restarted at {row.get('at')} (code {row.get('head')}), "
                "after the ask")
            return row
        if row and outcome == "already live":
            log(f"{sha[:12]}: temper-deploy let the request go without a new restart; the one "
                f"at {row.get('at')} (code {row.get('head')}) already carried it")
            return row
        if outcome == "let go":
            return None
        if time.monotonic() >= deadline:
            if row:
                log(f"{sha[:12]}: temper restarted at {row.get('at')} (code {row.get('head')}), "
                    "after the ask; another restart has waited behind it all this time")
            return row
        time.sleep(RESTART_POLL)


# -- going back --------------------------------------------------------------

def revert_to(good: str, bad: str, reason: str) -> dict:
    """Put a revert commit on master, through the gate, and restart onto it.

    A revert, never a reset: master only ever moves forwards, so anyone who
    already pulled the bad commit gets the fix by pulling again, and the
    history says plainly what happened and why.
    """
    out: dict = {"at": stamp(), "good": good, "bad": bad, "reason": reason, "ok": False}
    work = paths.STATE / "revert"
    # A revert that was killed half way \u2014 the machine rebooted, the service was
    # restarted \u2014 leaves this worktree and its branch behind, and git then
    # refuses to make them again. That would mean no rollback at all on the
    # next bad deploy, which is the one moment it has to work. So clear both
    # first, every time.
    sh("rm", "-rf", str(work), timeout=60)
    sh("git", "-C", str(MAIN_REPO), "worktree", "prune", timeout=60)
    sh("git", "-C", str(MAIN_REPO), "branch", "-q", "-D", f"revert-{bad[:8]}", timeout=60)
    try:
        # commit-tree makes the last good tree a new commit on top of master, without any
        # git hook. This is not a skipped check of new files: these exact bytes already
        # passed the hook and GitHub's checks when they landed, and GitHub checks the revert
        # after the push too. A rollback must not wait minutes for tests or test Postgres.
        message = (f"Revert to {good[:12]}: the live check failed after {bad[:12]}\n\n"
                   f"{reason}\n\n"
                   "Put in by temper-ci. The files here are exactly those of "
                   f"{good[:12]}, which was live and well; the machine check "
                   "records it and passes it at once.\n\n"
                   "Made with git commit-tree, without git hooks: these exact files already "
                   "passed the hook and GitHub's checks when they landed. GitHub checks this "
                   "revert after the push too; a rollback must not wait on the full suite "
                   "or test Postgres.")
        c = sh("git", "-C", str(MAIN_REPO), "commit-tree", f"{good}^{{tree}}",
               "-p", master_sha(), "-m", message, timeout=120)
        if c.returncode:
            out["detail"] = f"could not make the revert commit: {(c.stderr or c.stdout).strip()}"
            return out
        sha = c.stdout.strip()
        out["revert"] = sha
        # The gate's mirror fetches branch heads from MAIN_REPO. Keep the new commit on a
        # temporary branch until it has been checked and master has fast-forwarded onto it.
        ref = sh("git", "-C", str(MAIN_REPO), "branch", "-q", f"revert-{bad[:8]}", sha, timeout=60)
        if ref.returncode:
            out["detail"] = f"could not name the revert for the gate: {ref.stderr.strip()}"
            return out

        # Through the same gate as everything else.
        gate.ask_for(sha, "master", f"revert of {bad[:12]}")
        verdict = gate.check(sha, "master")
        out["gate_ok"] = bool(verdict.get("ok"))
        if not verdict.get("ok"):
            out["detail"] = f"the revert itself did not pass the gate: {verdict.get('reason')}"
            return out
        ff = sh("git", "-C", str(MAIN_REPO), "merge", "-q", "--ff-only", sha, timeout=120)
        if ff.returncode:
            out["detail"] = f"could not move master onto the revert: {ff.stderr.strip()}"
            return out
        push = sh("git", "-C", str(MAIN_REPO), "push", "-q", "origin", "master", timeout=300)
        out["pushed"] = push.returncode == 0
        ask_restart(sha, f"temper-ci: reverting {bad[:12]} after its live check failed")
        out["ok"] = True
        return out
    finally:
        sh("git", "-C", str(MAIN_REPO), "branch", "-q", "-D", f"revert-{bad[:8]}", timeout=60)


def dm(text: str) -> None:
    """Reuse temper-deploy's own DM, so there is one bot and one place it comes from."""
    script = (f"import importlib.machinery, importlib.util, sys\n"
              f"loader = importlib.machinery.SourceFileLoader('td', {str(TEMPER_DEPLOY)!r})\n"
              "spec = importlib.util.spec_from_loader('td', loader)\n"
              "m = importlib.util.module_from_spec(spec)\n"
              "loader.exec_module(m)\n"
              "m.tell_owner(sys.argv[1])\n")
    r = sh("python3", "-c", script, text, timeout=60)
    if r.returncode:
        log(f"could not DM the owner: {(r.stderr or r.stdout).strip()[:300]}")


# -- the whole thing ---------------------------------------------------------

def can_be_gone_back_to(sha: str) -> bool:
    """Is this a commit the gate itself has passed?

    Going back to a commit from before the gate existed went wrong here twice:
    the revert could not pass the gate of the day, master never moved, and
    the machine tried again on the next failure, leaving a trail of revert
    commits nobody could land.

    A commit is somewhere to go back to only if the gate has recorded it and
    passed it (and, while the throwaway temper still existed, checked it).
    Anything else is a guess, and a guess is worse than saying plainly that
    there is nowhere to go and letting the owner decide.
    """
    if not sha:
        return False
    verdict = gate.result_for(sha)
    return bool(verdict and verdict.get("ok"))


def deploy(sha: str) -> dict:
    """master is at ``sha``: get it live, and make sure it is well.

    Once temper has been looked at, the commit's report gets what the live check found,
    whichever way it went.
    """
    out = _deploy(sha)
    if "live" in out:
        try:
            report.write_live(sha, out)
        except Exception as exc:  # noqa: BLE001 - the deploy is decided and saved already
            log(f"{sha[:12]}: could not put the live check on its report: "
                f"{type(exc).__name__}: {exc}")
    return out


def _deploy(sha: str) -> dict:
    data = state()
    # Whoever started this deploy (the watcher once the runs were over, or a person), any hold
    # on record is over now. Every way out of here saves ``data``.
    data.pop("hold", None)
    good = data.get("last_good") or ""
    if good and not can_be_gone_back_to(good):
        log(f"{good[:12]} was on record as the good one, but the gate never passed it; "
            "treating it as nowhere to go back to")
        good = ""
    asked_at = dt.datetime.now(dt.UTC)
    ask_restart(sha, f"temper-ci: {sha[:12]} landed on master")
    row = wait_for_restart(asked_at, sha)
    outcome = ""
    if not row:
        # One more look, to say why -- and in case it came just as the wait ran out.
        outcome, last = restart_outcome(asked_at, sha)
        if outcome in ("restarted", "already live"):
            row = last
    out: dict = {"sha": sha, "asked_at": asked_at.isoformat(), "restarted": bool(row)}
    if not row:
        if outcome == "waiting":
            out["reason"] = "temper never restarted; nothing was rolled back, because nothing went live"
        else:
            # temper-deploy let the request go: a rebuild is needed (it tells the owner
            # itself), someone cancelled, or it refused (its answer is in the log above).
            # Asked again, it would say the same -- every loop, now that the answer
            # comes in seconds rather than after the hour -- so this commit is handled,
            # like a failed live check, until master moves or `temper-ci deploy`.
            out["reason"] = ("temper-deploy let the request go without restarting onto it "
                             "(`temper-deploy status` says why); nothing was rolled back, "
                             "because nothing went live")
            data["handled"] = sha
        log(f"{sha[:12]}: {out['reason']}")
        data["last_deploy"] = out
        save(data)
        return out

    out["live"] = live_check(report.folder(sha) / "live")
    return _decide(sha, out, data, good)


def _dict(value: object) -> dict:
    """``value`` when it is a dict, else an empty one: a record read back may hold anything."""
    return value if isinstance(value, dict) else {}


def settle_owed(sha: str) -> dict:
    """Try the parts the last look at ``sha`` owes, now that no run is going; then decide.

    Their fresh results take their places in that look (with the dashboard's, when the free
    run was owed: the page is looked at again for its run). A part owed again stays owed,
    however many step-asides, and is tried after five quiet minutes; one that fails fails
    the look, as on the day.
    """
    data = state()
    owed = _dict(data.get("owed"))
    last = _dict(data.get("last_deploy"))
    # The look being finished is this commit's; anything else on record is another's.
    out = dict(last) if last.get("sha") == sha else {"sha": sha, "restarted": True}
    live = dict(out.get("live") or {})
    names = set(owed.get("parts") or live.get("owed") or [])
    good = data.get("last_good") or ""
    if good and not can_be_gone_back_to(good):
        good = ""
    log(f"{sha[:12]}: no run is going, so trying again what its live check owes (look "
        f"{_owed_tries(owed) + 1}): {'; '.join(sorted(names))}")
    fresh: dict = {"parts": [], "ok": True, "owed": [], "shots": list(live.get("shots") or [])}
    _with_runs(fresh, report.folder(sha) / "live", live_api(), ci_key_headers(), only=names)
    new = {str(p.get("name")): p for p in fresh["parts"]}
    parts = [new.pop(str(p.get("name")), p) for p in live.get("parts") or []]
    parts += list(new.values())
    live.update({"parts": parts, "owed": fresh["owed"], "shots": fresh["shots"],
                 "ok": not any(report.mark(p) == "FAIL" for p in parts), "owed_tried_at": stamp()})
    out["live"] = live
    out = _decide(sha, out, data, good)
    try:
        report.write_live(sha, out)
    except Exception as exc:  # noqa: BLE001 - the deploy is decided and saved already
        log(f"{sha[:12]}: could not put the live check on its report: {type(exc).__name__}: {exc}")
    return out


def _owed_tries(owed: dict) -> int:
    """How many looks in a row at its commit have ended owed so far (a record from before
    they were counted is its first). The record check fails an unreadable count."""
    return max(1, int(owed.get("step_asides") or 1))


def _fail_owed(live: dict, why: str) -> None:
    """Every part the look owes fails instead, saying why (with none listed, a part of its
    own says it): owed is never a pass."""
    owed = [p for p in live.get("parts") or [] if p.get("owed")]
    for p in owed:
        p.pop("owed", None)
        p["ok"] = False
        p["detail"] = f"FAILED: {why}. Before that: {p.get('detail') or ''}"[:600]
    if not owed:
        live.setdefault("parts", []).append(
            {"name": "what the live check owed", "ok": False, "detail": f"FAILED: {why}"[:600]})
    live["owed"] = []
    live["ok"] = False


def _owed_record(data: dict) -> tuple[dict | None, str]:
    """What the last look owes, as kept on disk, and what is wrong with that record, if anything.

    It is kept in deploy.json, so it outlasts a restart of temper-ci. A record that cannot be
    read, or a look that ended owed with no record of it, is not a pass (Security, reply to
    rm-e71dc2dc): the caller fails what it owed.
    """
    if "owed" in data:
        owed = data["owed"]
        parts = owed.get("parts") if isinstance(owed, dict) else None
        if (not isinstance(owed, dict) or not isinstance(owed.get("sha"), str) or not owed["sha"]
                or not isinstance(parts, list) or not parts
                or not all(isinstance(p, str) and p for p in parts)):
            return None, "the record of what its live check owes cannot be read"
        try:
            _owed_tries(owed)
        except (TypeError, ValueError):
            return None, "the record of what its live check owes cannot be read"
        return owed, ""
    last = _dict(data.get("last_deploy"))
    looked = _dict(last.get("live"))
    sha = str(last.get("sha") or "")
    if (sha and looked.get("ok") and looked.get("owed") and not last.get("ok")
            and data.get("deployed") == sha and data.get("handled") != sha
            and data.get("last_good") != sha):
        return None, "its last live check ended owed, but the record of what it owes is missing"
    return None, ""


def _owed_lost(data: dict, problem: str) -> dict | None:
    """The record of what is owed is gone or garbled: what it owed fails, like any failure."""
    owed = _dict(data.get("owed"))
    last = _dict(data.get("last_deploy"))
    sha = owed.get("sha") if isinstance(owed.get("sha"), str) and owed.get("sha") else ""
    sha = sha or str(data.get("deployed") or last.get("sha") or "")
    data.pop("owed", None)
    if not sha:
        log(f"{problem}, and no commit is on record as live; nothing to fail")
        save(data)
        return None
    log(f"{sha[:12]}: {problem}; what it owed counts as failed")
    out = dict(last) if last.get("sha") == sha else {"sha": sha, "restarted": True}
    live = dict(out.get("live") or {"at": stamp(), "parts": [], "ok": True, "owed": [], "shots": []})
    live["parts"] = [dict(p) for p in live.get("parts") or [] if isinstance(p, dict)]
    _fail_owed(live, problem)
    out["live"] = live
    good = data.get("last_good") or ""
    if good and not can_be_gone_back_to(good):
        good = ""
    out = _decide(sha, out, data, good)
    try:
        report.write_live(sha, out)
    except Exception as exc:  # noqa: BLE001 - the deploy is decided and saved already
        log(f"{sha[:12]}: could not put the live check on its report: {type(exc).__name__}: {exc}")
    return out


def _decide(sha: str, out: dict, data: dict, good: str) -> dict:
    """What the live look at ``sha`` found decides it: well, owed, or going back to ``good``."""
    live = out["live"]
    owed = [str(name) for name in live.get("owed") or []]
    earlier = _dict(data.get("owed"))
    same = earlier.get("sha") == sha
    tries = (_owed_tries(earlier) if same else 0) + 1
    out["ok"] = bool(live.get("ok")) and not owed
    data["last_deploy"] = out
    if out["ok"]:
        data.pop("owed", None)
        data.pop("state_lost_at", None)
        data["last_good"] = sha
        data["deployed"] = sha
        data["revert_outstanding"] = ""
        if data.get("handled") == sha:
            del data["handled"]
        save(data)
        log(f"{sha[:12]}: live and well")
        return out

    if live.get("ok"):
        # Nothing failed, but not everything was tried: someone else's run was going. Live,
        # and not the commit to go back to until the owed parts have passed (watch_master).
        # Nobody is told: nothing is wrong. The record says which runs it stepped aside for.
        because = sorted({str(i) for p in live.get("parts") or [] if p.get("owed")
                          for i in p.get("because") or []})
        # One line per step-aside, ids and names only (Security, reply to rm-e71dc2dc): whose
        # run it was, and which runs of its own temper-ci cancelled (they ended, no box left).
        for p in live.get("parts") or []:
            if p.get("owed"):
                log(f"{sha[:12]}: {p.get('name')} stepped aside for "
                    f"{', '.join(str(i)[:8] for i in p.get('because') or []) or 'a run not named'}; "
                    f"cancelled its own: {', '.join(str(i)[:8] for i in p.get('cancelled') or []) or 'none'}")
        data["deployed"] = sha
        data["owed"] = {"sha": sha, "parts": owed, "since": earlier.get("since") if same else stamp(),
                        "step_asides": tries, "because": because}
        save(data)
        log(f"{sha[:12]}: live, but not yet recorded as good: owed (look {tries}), "
            "because someone else's run was going "
            f"({', '.join(b[:8] for b in because) or 'not named'}): {'; '.join(owed)}. They are "
            "tried again once no run is going, before any newer deploy")
        return out

    data.pop("owed", None)
    # Only the parts that count and failed: an information-only one (the Pi pins) never
    # failed anything, and an owed one has not been tried.
    bad_parts = "; ".join(str(p["name"]) for p in live["parts"] if report.mark(p) == "FAIL")
    log(f"{sha[:12]}: the live check failed ({bad_parts})")
    # Handled, whichever way it goes from here: the owner hears about this failure
    # once, and the watcher leaves this commit alone until master moves on (or a
    # person runs `temper-ci deploy`). Without this, a failure with nothing more to
    # do came straight back on the next loop -- on 2026-10-03, six restarts and six
    # "needs a person" DMs in ten minutes, until master happened to move.
    data["handled"] = sha
    save(data)
    if not good or good == sha:
        dm(f"temper: the live check failed after {sha[:12]} ({bad_parts}), and there is no "
           "earlier commit the gate has passed to go back to. Temper is up but unwell \u2014 "
           f"`temper-deploy status`, report: {report.url(sha)}")
        out["rolled_back"] = False
        return out

    # One revert, then hands off. If the last thing this did was revert and that
    # did not put things right, a second revert is the machine arguing with
    # itself on master while the owner is not looking.
    if data.get("revert_outstanding"):
        dm(f"temper: the live check failed again after {sha[:12]} ({bad_parts}), and a revert "
           f"({str(data['revert_outstanding'])[:12]}) is already outstanding. Stopping here \u2014 "
           f"this needs a person. `temper-ci status`, report: {report.url(sha)}")
        out["rolled_back"] = False
        out["reason"] = "a revert was already outstanding"
        return out

    # A revert restarts temper too, so it waits for the runs like any deploy: watch_master
    # makes it once they are over, unless master has moved on by then.
    data = state()
    if held_for_runs(data, f"the revert of {sha[:12]}"):
        data["revert_waits"] = {"good": good, "bad": sha, "parts": bad_parts, "since": stamp()}
        save(data)
        dm(f"temper: the live check failed after {sha[:12]} ({bad_parts}). Going back to "
           f"{good[:12]} restarts temper, so it waits until no run is going "
           f"({data['hold']['why']}). Temper stays on {sha[:12]} meanwhile. "
           f"`temper-ci status`, report: {report.url(sha)}")
        out["rolled_back"] = False
        out["reason"] = "the revert waits until no run is going on the live temper"
        return out
    return _go_back(sha, good, bad_parts, out)


def _go_back(sha: str, good: str, bad_parts: str, out: dict) -> dict:
    """Revert master to ``good`` after ``sha`` failed its live check, and tell the owner."""
    try:
        back = revert_to(good, sha, f"the live check failed: {bad_parts}")
    except Exception as exc:  # noqa: BLE001 - every failed revert must be recorded and said
        back = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:600]}
    out["rollback"] = back
    data = state()
    data["last_deploy"] = out
    data["deployed"] = back.get("revert") or sha
    data["handled"] = sha
    # Cleared once a deploy is well again; until then, no second revert.
    data["revert_outstanding"] = "" if back.get("ok") else (back.get("revert") or sha)
    # Consume a waiting revert only together with its saved outcome, never before trying it.
    # A timeout used to lose the wait and escape before recording or telling the owner.
    if _dict(data.get("revert_waits")).get("bad") == sha:
        data.pop("revert_waits", None)
    save(data)
    subjects = sh("git", "-C", str(MAIN_REPO), "log", "--format=%h %s", f"{good}..{sha}").stdout.strip()
    dm("temper: the live check failed after the last land, so master has been put back.\n"
       f"• what failed: {bad_parts}\n"
       f"• taken back out:\n{subjects or f'  {sha[:12]}'}\n"
       f"• master is now the files of {good[:12]}"
       f"{' (revert ' + back['revert'][:12] + ')' if back.get('revert') else ''}\n"
       f"• temper is restarting onto it{'' if back.get('ok') else ' — THE REVERT ITSELF DID NOT GO THROUGH: ' + str(back.get('detail'))}\n"
       f"• report: {report.url(sha)}")
    return out


def _state_lost() -> None:
    """deploy.json is there but cannot be read, so which commit is good, and what a live
    check still owes, went with it. Nothing passes on that (Security, reply to rm-e71dc2dc):
    the file is kept aside, the owner is told once, and the record starts again with
    nothing to go back to until a commit passes its whole live check. Without this the
    first-look path would record master as good without a look."""
    aside = DEPLOY_STATE.with_name(f"{DEPLOY_STATE.name}.unreadable-{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%SZ}")
    try:
        DEPLOY_STATE.replace(aside)
    except OSError as exc:
        log(f"deploy.json cannot be read, nor moved aside ({type(exc).__name__}): writing a new one over it")
    sha = master_sha()
    save({"deployed": sha, "state_lost_at": stamp()})
    log(f"deploy.json could not be read (kept as {aside.name}): nothing is on record as good now, "
        "and nothing a live check owed counts as passed")
    dm(f"temper: temper-ci could not read its record of deploys (kept as {aside}), so it no longer "
       "knows which commit is good, or what a live check still owed. Nothing counts as passed: "
       f"master {sha[:12]} is taken as live, and there is nowhere to go back to until a commit "
       "passes its live check. `temper-ci status`")


def watch_master() -> dict | None:
    """Called from the watcher's loop: has master moved since we last deployed?"""
    if state_unreadable():
        _state_lost()
    data = state()
    sha = master_sha()
    waits = data.get("revert_waits")
    if waits and waits.get("bad") != sha:
        log(f"the revert of {str(waits.get('bad'))[:12]} is not needed any more: master moved on "
            f"to {sha[:12]}, whose own deploy and live check decide now")
        data.pop("revert_waits", None)
        save(data)
        waits = None
    if waits:
        if held_for_runs(data, f"the revert of {sha[:12]}"):
            return None
        return _go_back(sha, waits.get("good") or "", waits.get("parts") or "",
                        dict(data.get("last_deploy") or {"sha": sha}))
    owed, problem = _owed_record(data)
    if problem:
        return _owed_lost(data, problem)
    if owed:
        # Before anything newer goes on top, even when master has moved on (Security, reply
        # to rm-e71dc2dc): temper is still on the owed commit. After its first step-aside,
        # leave a longer quiet window: the owed parts start runs of their own, and never
        # beside someone else's. Legacy owed records without a count are the first look.
        if held_for_runs(data, f"what the live check of {owed['sha'][:12]} owes", OWED_QUIET_SECONDS):
            return None
        return settle_owed(owed["sha"])
    if not sha or data.get("deployed") == sha:
        return None
    if data.get("handled") == sha:
        # Already went wrong once, and the owner was told. Trying again would only
        # say it again, every loop; it waits for master to move, or for a person.
        return None
    if not data.get("last_good"):
        # First time: what is live now is where we would go back to \u2014 but only if
        # the gate has passed it. On the day the gate is installed master is a
        # commit from before it existed, which the gate never recorded, so
        # record nothing and let the first commit that passes become the one to
        # go back to.
        data["deployed"] = sha
        if can_be_gone_back_to(sha):
            data["last_good"] = sha
            log(f"first look: master is {sha[:12]}, and the gate has passed it, so that is "
                "where we would go back to")
        else:
            log(f"first look: master is {sha[:12]}, which the gate never checked; there is "
                "nowhere to go back to until a commit passes")
        save(data)
        return None
    if held_for_runs(data, sha[:12]):
        return None
    return deploy(sha)
