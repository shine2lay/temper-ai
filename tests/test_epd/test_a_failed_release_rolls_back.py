"""A production release migrates the database, checks it is healthy, and puts itself back when it fails.

Until 2026-10-29 deploy_prod() backed up, ran `standee up` and waited for the URL, and stopped there:
- the database was never migrated: each release that brought a migration needed someone to run
  `alembic upgrade head` in the container by hand, and until then the Health page flagged it;
- nothing after `standee up` was checked or undone: on 2026-10-26 one Docker Hub `TLS handshake
  timeout` failed a release, and putting prod right took a hand.

Now: backup, up (tried again on a registry or network error only), mount check, URL, migration,
health; a failure after the first change restores the database (only when a migration ran), puts
the previous images back and says what state prod is in. standee, docker, alembic and /api/health
are a fake prod kept in memory here; what is under test is the order of the steps and what is undone.
"""

import io
import json
import subprocess
import urllib.error

import pytest

from tests.test_epd import test_epd_loop

# The driver, loaded with its state in a temporary directory: test_epd_loop's fixture, by name.
L = test_epd_loop.L

REF = "c0ffee1234567890c0ffee1234567890c0ffee12"
OLD_SHA = "a1" * 20                     # the commit live before the release, an ancestor of REF
OLD, NEW = "sha256:" + "a" * 64, "sha256:" + "b" * 64
REVISION = "org.opencontainers.image.revision"
LOCK_BUSY = ("Error: another standee command holds the lock (/home/shinelay/.standee/standee.lock); "
             "waited 60s for up")
DOCKER_HUB = ('ERROR: failed to solve: node:22-alpine: failed to resolve source metadata for '
              'docker.io/library/node:22-alpine: failed to do request: Head "https://registry-1.docker.io/v2/'
              'library/node/manifests/22-alpine": net/http: TLS handshake timeout')
BUILD_BROKE = 'ERROR: failed to solve: process "/bin/sh -c npm ci" did not complete successfully: exit code: 1'
ALEMBIC_LOG = ("INFO  [alembic.runtime.migration] Context impl SQLiteImpl.\n"
               "INFO  [alembic.runtime.migration] Will assume non-transactional DDL.\n")


class Prod:
    """The live product as deploy_prod sees it, in memory: what runs, what the database holds, the copies."""

    def __init__(self, L, tmp_path):
        self.L = L
        self.image = OLD                         # the image the live container runs
        self.db = "r1"                           # the live database's alembic revision
        self.head_of = {OLD: "r1", NEW: "r2"}    # each image's migrations head
        self.right_mount = f"{(L.PROD_HOME / 'var').resolve()}->/data"
        self.mount, self.mount_after_up = self.right_mount, self.right_mount
        self.up_fails: list[str] = []            # what the next `standee up`s fail with, in turn
        self.upgrade = "ok"                      # ok | fails | fails-halfway | does-nothing
        self.unhealthy: set[str] = set()         # images whose /api/health says ok=false
        self.url_dead = False
        self.restore_ok = True
        self.backups: list[tuple[str, str]] = []  # (path, revision it holds)
        self.dir = tmp_path / "backups" / "rollcall-prod"
        self.ran: list[str] = []                 # the steps that matter, in order
        self.slept: list[float] = []
        # which commit runs: each image's labels (standee's and the Dockerfile's) and /api/health's commit
        self.labels_of = {OLD: {"standee.commit": OLD_SHA[:12], REVISION: OLD_SHA},
                          NEW: {"standee.commit": REF[:12], REVISION: REF}}
        self.commit_of: dict[str, str | None] = {OLD: OLD_SHA, NEW: REF}
        self.ancestor_rc = 0                     # `git merge-base --is-ancestor`: 0 yes, 1 no, 128 unknown
        self.asked_ancestor: list[tuple[str, str]] = []
        self.up_env: list[dict] = []             # the environment each `standee up` got
        # standee's lock: how many more tries of each command find it taken; each such try waits 60 s
        self.lock_busy = {"backup": 0, "up": 0}
        self.clock = 1000.0
        # the release tags: on origin and in the checkout, name -> commit; what each tag says
        self.remote_tags: dict[str, str] = {}
        self.local_tags: dict[str, str] = {}
        self.tag_message: dict[str, str] = {}
        self.tag_fails = self.push_fails = False
        self.pushed: list[str] = []
        self.told: list[str] = []                # what RollCall was told

    def steps(self) -> list[str]:
        return self.ran

    # -- the commands deploy_prod runs ------------------------------------------------------------
    def sh(self, cmd, cwd=None, check=True, env=None):
        def done(out="", rc=0, err=""):
            if rc and check:
                self.L.die(f"command failed ({rc}): {' '.join(cmd)}")
            return subprocess.CompletedProcess(cmd, rc, out, err)

        def lock_taken(what):
            if self.lock_busy[what] <= 0:
                return False
            self.lock_busy[what] -= 1
            self.clock += 60  # standee waits 60 s for its lock before it gives up
            return True

        match cmd:
            case ["git", "rev-parse", "HEAD"]:
                return done(REF + "\n")
            case ["git", "status", "--porcelain"]:
                return done("")
            case ["git", "rev-parse", "--verify", "--quiet", short]:
                full = next((s for s in (OLD_SHA, REF) if s.startswith(short.removesuffix("^{commit}"))), "")
                return done(full + "\n" if full else "", 0 if full else 1)
            case ["git", "merge-base", "--is-ancestor", running, ref]:
                self.asked_ancestor.append((running, ref))
                return done("", self.ancestor_rc, "fatal: Not a valid commit name" if self.ancestor_rc > 1 else "")
            case ["git", "ls-remote", "--tags", "origin", "prod/*"]:
                rows = [f"{'f' * 40}\trefs/tags/{n}\n{sha}\trefs/tags/{n}^{{}}" for n, sha in self.remote_tags.items()]
                return done("\n".join(rows) + "\n" if rows else "")
            case ["git", "for-each-ref", fmt, "refs/tags/prod/*"]:
                return done("".join(f"{n} {sha} {'e' * 40}\n" for n, sha in self.local_tags.items()))
            case ["git", "tag", "-a", name, sha, "-m", message]:
                if self.tag_fails:
                    return done("", 128, "fatal: unable to auto-detect email address")
                self.local_tags[name], self.tag_message[name] = sha, message
                return done("")
            case ["git", "push", "origin", tag_ref]:
                if self.push_fails:
                    return done("", 128, "ERROR: Repository not found.\nfatal: Could not read from remote repository.")
                name = tag_ref.removeprefix("refs/tags/")
                self.remote_tags[name] = self.local_tags[name]
                self.pushed.append(name)
                return done("", err=f" * [new tag]         {name} -> {name}\n")
            case ["docker", "inspect", _, "--format", "{{.Image}}"]:
                return done(self.image + "\n") if self.image else done("", 1, "Error: No such object")
            case ["docker", "inspect", _, "--format", "{{json .Config.Labels}}"]:
                if not self.image:
                    return done("", 1, "Error: No such object")
                return done(json.dumps({"com.docker.compose.project": "rollcall-prod",
                                        **self.labels_of[self.image]}) + "\n")
            case ["docker", "inspect", _, "--format", fmt] if "Mounts" in fmt:
                self.ran.append("mounts")
                return done(self.mount + " \n")
            case ["standee", "backup", _, "--label", "deploy"]:  # an unlabelled backup matches nothing here
                self.ran.append("backup")
                if lock_taken("backup"):
                    return done("", 1, LOCK_BUSY.replace("for up", "for backup"))
                when = f"2026-10-29-1030{len(self.backups):02d}"
                self.backups.append((str(self.dir / "rollcall" / f"{when}.deploy.db.gz"), self.db))
                return done(f"rollcall  sqlite  1.2M  {self.backups[-1][0]}\n")
            case ["standee", "backup", _, "--list"]:
                rows = []
                for path, _rev in self.backups:
                    when = path.rsplit("/", 1)[1].split(".")[0]
                    rows.append(f"{when:<20}{'files':<12}{'667B':>9}  {self.dir}/files/{when}.deploy")
                    rows.append(f"{when:<20}{'rollcall':<12}{'1.2M':>9}  {path}")
                return done("\n".join(sorted(rows)) + "\n")
            case ["standee", "backup", _, "--restore", path, "--yes"]:
                n = [p for p, _ in self.backups].index(path) + 1
                self.ran.append(f"restore {n}")
                if not self.restore_ok:
                    return done("", 1, "restore into rollcall failed (exit 1)")
                self.db = self.backups[n - 1][1]
                return done("restored /data/rollcall.db\n")
            case ["standee", "up", *_]:
                self.ran.append("up")
                self.up_env.append(env)
                if lock_taken("up"):
                    return done("", 1, LOCK_BUSY)
                if self.up_fails:  # standee puts the images that ran before back itself
                    return done("", 1, self.up_fails.pop(0) + "\n✗ up failed: rolled back to the previous images")
                self.image, self.mount = NEW, self.mount_after_up
                return done("env  rollcall-prod\nurl  https://rollcall.wai2shine.com\n")
            case ["standee", "rollback", _]:
                self.ran.append("rollback")
                self.image, self.mount = OLD, self.right_mount
                return done("rolled back rollcall-prod\n")
            case ["standee", "restart", _]:
                self.ran.append("restart")
                return done("")
            case ["docker", "exec", _, "sh", "-c", script]:
                return self.alembic(script.removeprefix("cd /app && alembic "), done)
        raise AssertionError(f"unexpected command: {cmd}")

    def alembic(self, args, done):
        head = self.head_of[self.image]
        if args == "current":
            return done(f"{self.db} (head)\n" if self.db == head else f"{self.db}\n", err=ALEMBIC_LOG)
        if args == "heads":
            return done(f"{head} (head)\n", err=ALEMBIC_LOG)
        assert args == "upgrade head", args
        self.ran.append("upgrade")
        if self.upgrade == "ok":
            self.db = head
        elif self.upgrade == "fails-halfway":
            self.db = "r1b"
        if self.upgrade.startswith("fails"):
            return done("", 1, ALEMBIC_LOG + "sqlite3.OperationalError: duplicate column name: roll_window")
        return done("", err=ALEMBIC_LOG + "INFO  [alembic.runtime.migration] Running upgrade r1 -> r2\n")

    # -- the URL ------------------------------------------------------------------------------------
    def wait_for_url(self, url, timeout=240.0):
        self.ran.append("url")
        if self.url_dead:
            self.L.die(f"{url} did not come up in {timeout:.0f}s (last: HTTP 502)")

    def api_health(self):
        self.ran.append("health")
        return "/api/health says ok=False, db_ok=False" if self.image in self.unhealthy else None

    def health_commit(self):
        return self.commit_of[self.image]

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.clock += seconds


@pytest.fixture
def prod(L, tmp_path, monkeypatch):
    p = Prod(L, tmp_path)
    monkeypatch.setattr(L, "sh", p.sh)
    monkeypatch.setattr(L, "wait_for_url", p.wait_for_url)
    monkeypatch.setattr(L, "prod_api_health", p.api_health)
    monkeypatch.setattr(L, "ensure_qa_password", lambda: "not-a-password")
    monkeypatch.setattr(L, "planned_mount_problem", lambda: None)  # its own tests: test_one_deploy_at_a_time
    monkeypatch.setattr(L, "prod_health_commit", p.health_commit)
    monkeypatch.setattr(L, "tell_rollcall", p.told.append)
    monkeypatch.setattr(L, "clock_seconds", lambda: p.clock)
    monkeypatch.setattr(L, "release_time", lambda: L.dt.datetime(2026, 11, 5, 20, 31, 7, tzinfo=L.dt.UTC))
    monkeypatch.setattr(L.time, "sleep", p.sleep)
    monkeypatch.setattr(L, "HEALTH_TRIES", 3)
    return p


def release(L, capsys, **kw) -> tuple[bool, str]:
    """deploy_prod(REF, **kw): (whether it died, everything it said)."""
    died, said = release_code(L, capsys, **kw)
    return died is not None, said


def release_code(L, capsys, ref=REF, **kw) -> tuple[int | str | None, str]:
    """deploy_prod(ref, **kw): (its exit code, None when it returned; everything it said)."""
    try:
        L.deploy_prod(ref, **kw)
        code = None
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr()
    return code, out.out + out.err


# ---- the release goes through ---------------------------------------------------------------------


def test_a_release_migrates_the_database_and_checks_it_is_healthy(L, prod, capsys):
    died, said = release(L, capsys)
    assert not died, said
    assert (prod.image, prod.db) == (NEW, "r2")
    # the second backup is the copy a failed migration would be restored from
    assert prod.steps() == ["backup", "up", "mounts", "url", "backup", "upgrade", "health"]
    assert "migrated the live database: r1 -> r2" in said
    assert f"release of {REF[:12]} is live and healthy" in said


def test_a_release_with_nothing_to_migrate_takes_no_second_copy(L, prod, capsys):
    prod.head_of[NEW] = "r1"
    died, said = release(L, capsys)
    assert not died, said
    assert prod.steps() == ["backup", "up", "mounts", "url", "health"]
    assert "database already at head (r1): no migration to run" in said


def test_a_registry_hiccup_is_tried_again_and_the_release_goes_on(L, prod, capsys):
    prod.up_fails = [DOCKER_HUB, DOCKER_HUB]
    died, said = release(L, capsys)
    assert not died, said
    assert prod.steps() == ["backup", "up", "up", "up", "mounts", "url", "backup", "upgrade", "health"]
    assert prod.slept == [20, 40]
    assert "registry or network error (TLS handshake timeout); trying again in 20s (try 2 of 4)" in said
    assert (prod.image, prod.db) == (NEW, "r2")


# ---- a failure puts the release before back -------------------------------------------------------


@pytest.mark.parametrize("upgrade", ["fails", "fails-halfway"])
def test_a_failed_migration_puts_the_database_and_the_images_back(L, prod, capsys, upgrade):
    prod.upgrade = upgrade
    died, said = release(L, capsys)
    assert died
    assert (prod.image, prod.db) == (OLD, "r1")
    # the database first, from the copy taken just before the migration, while a container runs to
    # take it; then the old images, which start fresh on it; then the result is checked
    assert prod.steps() == ["backup", "up", "mounts", "url", "backup", "upgrade",
                            "restore 2", "rollback", "mounts", "health"]
    assert "failed while migrating the database from r1 to r2: `alembic upgrade head` exited 1" in said
    assert "duplicate column name: roll_window" in said
    assert "Undone: rolled back to the previous images (aaaaaaaaaaaa); database restored from" in said
    assert "Prod now: healthy" in said


def test_a_release_that_is_not_healthy_is_put_back(L, prod, capsys):
    prod.unhealthy.add(NEW)
    died, said = release(L, capsys)
    assert died
    assert (prod.image, prod.db) == (OLD, "r1")
    assert prod.steps() == ["backup", "up", "mounts", "url", "backup", "upgrade", "health", "health", "health",
                            "restore 2", "rollback", "mounts", "health"]
    assert "failed while checking the release is healthy: /api/health says ok=False, db_ok=False (3 tries)" in said
    assert "Prod now: healthy" in said


def test_a_migration_that_leaves_the_database_short_of_head_is_put_back(L, prod, capsys):
    prod.upgrade = "does-nothing"
    died, said = release(L, capsys)
    assert died
    assert prod.steps()[-4:] == ["restore 2", "rollback", "mounts", "health"]
    assert "the database is at r1 but the code's head is r2" in said
    assert (prod.image, prod.db) == (OLD, "r1")


def test_a_build_that_breaks_is_not_tried_again_and_nothing_is_migrated(L, prod, capsys):
    prod.up_fails = [BUILD_BROKE]
    died, said = release(L, capsys)
    assert died
    # standee already put the images that ran before back: nothing to roll back, nothing to restore
    assert prod.steps() == ["backup", "up", "mounts", "health"]
    assert prod.slept == []
    assert "failed while starting the new images (`standee up`): `standee up` exited 1" in said
    assert "database left as it was (no migration had run)" in said
    assert (prod.image, prod.db) == (OLD, "r1")


def test_the_tries_stop_after_three_and_the_release_is_called_off(L, prod, capsys):
    prod.up_fails = [DOCKER_HUB] * 9
    died, said = release(L, capsys)
    assert died
    assert prod.steps().count("up") == 4
    assert prod.slept == [20, 40, 80]
    assert "on try 4 of 4 (registry or network: TLS handshake timeout)" in said


def test_a_release_that_lost_the_database_mount_is_rolled_back_without_touching_the_database(L, prod, capsys):
    prod.mount_after_up = "/tmp/elsewhere/var->/data"
    died, said = release(L, capsys)
    assert died
    assert prod.steps() == ["backup", "up", "mounts", "rollback", "mounts", "health"]
    assert "is not mounting" in said and "Prod now: healthy" in said
    assert prod.mount == prod.right_mount


def test_a_url_that_never_answers_is_rolled_back(L, prod, capsys):
    prod.url_dead = True
    died, said = release(L, capsys)
    assert died
    assert prod.steps() == ["backup", "up", "mounts", "url", "rollback", "mounts", "health"]
    assert "failed while waiting for https://rollcall.wai2shine.com to answer" in said
    assert prod.image == OLD


def test_an_undo_that_cannot_restore_the_database_says_so_and_how(L, prod, capsys):
    prod.upgrade, prod.restore_ok = "fails-halfway", False
    died, said = release(L, capsys)
    assert died
    assert prod.steps() == ["backup", "up", "mounts", "url", "backup", "upgrade",
                            "restore 2", "rollback", "restore 2", "mounts", "health"]
    assert "UNDO INCOMPLETE" in said
    assert f"the database is NOT restored: run `standee backup rollcall-prod --restore {prod.backups[1][0]} --yes`" in said
    assert "Prod now: NOT HEALTHY: the database is at r1b but the code's head is r1" in said


# ---- one deploy at a time, and only onto the live data ---------------------------------------------


def hold(path):
    """Hold `path`'s flock the way another deploy's deploy_prod would; returns the open fd."""
    import fcntl
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def test_one_deploy_at_a_time(L, prod, capsys):
    """While another deploy holds the lock, deploy_prod changes nothing and exits DEPLOY_BUSY (75)."""
    import os

    fd = hold(L.DEPLOY_LOCK)
    try:
        with pytest.raises(SystemExit) as e:
            L.deploy_prod(REF)
    finally:
        os.close(fd)
    assert e.value.code == L.DEPLOY_BUSY == 75
    assert prod.steps() == []  # not even a backup
    assert "another production deploy is running" in capsys.readouterr().out
    # Once it lets go, the next deploy goes through.
    died, said = release(L, capsys)
    assert not died, said
    assert prod.image == NEW


def test_a_release_that_dies_lets_go_of_the_lock(L, prod, capsys):
    import os

    prod.url_dead = True
    died, _ = release(L, capsys)
    assert died
    fd = hold(L.DEPLOY_LOCK)  # would raise BlockingIOError if the dead release still held it
    os.close(fd)


def test_the_lock_is_the_one_the_continuous_deployer_names(L):
    """wt deploy's release hook passes the same exit code on; the lock lives in its state directory by default."""
    from pathlib import Path

    bin_dir = Path(L.__file__).parent
    assert f"DEPLOY_BUSY = {L.DEPLOY_BUSY}" in (bin_dir / "rollcall_cd_deploy.py").read_text()
    assert '".local" / "state" / "rollcall-cd" / "deploy.lock"' in (bin_dir / "epd_loop.py").read_text()


class Compose:
    """`docker compose ... config --format json` as planned_mount_problem asks it."""

    def __init__(self, source):
        self.source, self.cmds = source, []

    def run(self, cmd, **kw):
        self.cmds.append(cmd)
        assert cmd[:2] == ["docker", "compose"] and cmd[-3:] == ["config", "--format", "json"], cmd
        vols = [{"type": "bind", "source": self.source, "target": "/data"}] if self.source else []
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"services": {"rollcall": {"volumes": vols}}}), "")


def tree(L, prod_files):
    L.REPO_CHECKOUT.mkdir(parents=True, exist_ok=True)
    tiers = f"tiers:\n  prod:\n    compose: {json.dumps(prod_files)}\n" if prod_files else "tiers:\n  prod: {}\n"
    (L.REPO_CHECKOUT / "standee.yaml").write_text(f"name: rollcall\ncompose: [deploy/compose.yaml]\n{tiers}")


def test_a_tree_that_mounts_the_live_data_by_its_own_path_may_be_released(L, monkeypatch):
    tree(L, ["deploy/compose.yaml", "deploy/compose.live.yaml"])
    c = Compose(str((L.PROD_HOME / "var").resolve()))
    monkeypatch.setattr(L.subprocess, "run", c.run)
    assert L.planned_mount_problem() is None
    cmd = c.cmds[0]
    assert cmd[cmd.index("--project-directory") + 1] == str(L.REPO_CHECKOUT)
    assert [cmd[i + 1] for i, a in enumerate(cmd) if a == "-f"] == [
        str(L.REPO_CHECKOUT / "deploy/compose.yaml"), str(L.REPO_CHECKOUT / "deploy/compose.live.yaml")]


def test_a_tree_from_before_the_live_paths_is_refused_before_anything_changes(L, monkeypatch, capsys, request):
    """An older commit mounts ./var of the checkout it runs from: an empty database. Refused first."""
    tree(L, None)
    c = Compose(str(L.REPO_CHECKOUT / "var"))
    with monkeypatch.context() as m:
        m.setattr(L.subprocess, "run", c.run)
        problem = L.planned_mount_problem()
    prod = request.getfixturevalue("prod")  # the fake prod, whose own stub answers None
    assert problem and "would mount" in problem and "predates deploy/compose.live.yaml" in problem
    assert [cmd[i + 1] for cmd in c.cmds for i, a in enumerate(cmd) if a == "-f"] == [
        str(L.REPO_CHECKOUT / "deploy/compose.yaml")]  # the top-level compose, tier prod naming none
    monkeypatch.setattr(L, "planned_mount_problem", lambda: problem)
    died, said = release(L, capsys)
    assert died and prod.steps() == []
    assert f"refusing to release {REF[:12]}" in said and "nothing was changed" in said


def test_a_tree_without_a_standee_file_is_refused(L):
    L.REPO_CHECKOUT.mkdir(parents=True, exist_ok=True)
    assert "could not read" in L.planned_mount_problem()


def test_every_standee_call_sees_the_live_data_home(L):
    """`standee rollback` re-reads compose.live.yaml's ROLLCALL_HOME when it recreates the container."""
    import os

    assert os.environ["ROLLCALL_HOME"] == str(L.PROD_HOME)


# ---- the pieces -----------------------------------------------------------------------------------


def test_only_a_registry_or_network_error_counts_as_passing(L):
    assert L.transient_up_error(DOCKER_HUB) == "TLS handshake timeout"
    assert L.transient_up_error("toomanyrequests: You have reached your pull rate limit") == "toomanyrequests"
    assert L.transient_up_error(BUILD_BROKE) == ""


def test_alembic_revisions_reads_current_and_heads(L):
    assert L.alembic_revisions("d2e4f6a8b1c3 (head)\n") == ("d2e4f6a8b1c3",)
    assert L.alembic_revisions("b2 (head)\na1 (head)\n") == ("a1", "b2")
    assert L.alembic_revisions("") == ()  # a database with no version yet
    assert L.alembic_revisions(ALEMBIC_LOG) == ()  # its log lines, should they ever reach stdout


def test_api_health_wants_ok_true(L, monkeypatch):
    def answer(body=None, code=None):
        def urlopen(url, timeout=0):
            assert url == "https://rollcall.wai2shine.com/api/health"
            if code:
                raise urllib.error.HTTPError(url, code, "Bad Gateway", {}, io.BytesIO(b"bad gateway"))
            return io.BytesIO(json.dumps(body).encode())
        monkeypatch.setattr(L.urllib.request, "urlopen", urlopen)

    answer({"ok": True, "db_ok": True, "scheduler_running": True})
    assert L.prod_api_health() is None
    answer({"ok": False, "db_ok": False})
    assert L.prod_api_health() == "/api/health says ok=False, db_ok=False"
    answer(code=502)
    assert L.prod_api_health() == "/api/health answered HTTP 502"


def test_ensure_qa_on_prod_runs_after_deploy_and_reports_failure_without_reverting(L, prod, monkeypatch, capsys):
    monkeypatch.setattr(L, "_previous_release_info", lambda ref, kind: (OLD_SHA, 120.0, ["feat: alpha"], set()))
    monkeypatch.setattr(L, "check_prod_scheduler_lock", lambda: ("acquired", 0.0))
    monkeypatch.setattr(L, "_announce_release", lambda **kw: None)

    def failing_qa():
        msg = "ensure_qa_on_prod: QA seed check failed (seed script exited 1) — not a revert reason"
        L.log(f"WARNING: {msg}")
        L.tell_rollcall(msg)
        return False

    monkeypatch.setattr(L, "ensure_qa_on_prod", failing_qa)
    out = L.release_prod(REF, kind="forward", reason="master c0ffee12")
    said = capsys.readouterr().out
    assert out["prod_qa"] is False
    assert prod.image == NEW
    assert "seed script exited 1" in said
    assert any("seed script exited 1" in t for t in prod.told)


def test_scheduler_lock_held_elsewhere_waits_and_flags_loudly_without_undoing(L, prod, monkeypatch, capsys):
    monkeypatch.setattr(L, "prod_health_scheduler_lock", lambda: "held_elsewhere")
    state, waited = L.check_prod_scheduler_lock(wait_s=90.0, poll_s=30.0)
    said = capsys.readouterr().out
    assert state == "held_elsewhere" and waited == 90.0
    assert prod.slept == [30.0, 30.0, 30.0]
    assert "scheduler_lock=held_elsewhere after 90s" in said
    assert any("scheduler_lock=held_elsewhere after 90s" in t for t in prod.told)


def test_release_prod_announces_every_real_deploy_and_skips_pre_change_refusals(L, prod, monkeypatch, capsys):
    announced = []
    monkeypatch.setattr(L, "_announce_release", lambda **kw: announced.append(kw))
    monkeypatch.setattr(L, "_previous_release_info", lambda ref, kind: (OLD_SHA, 270.0, ["feat: alpha", "fix: beta"], set()))
    monkeypatch.setattr(L, "check_prod_scheduler_lock", lambda: ("acquired", 0.0))
    monkeypatch.setattr(L, "ensure_qa_on_prod", lambda: True)

    # 1. Forward success announces deployed
    L.release_prod(REF, kind="forward", reason="master c0ffee12")
    assert len(announced) == 1
    assert announced[-1]["outcome"] == "deployed"
    assert announced[-1]["kind"] == "deploy"
    assert announced[-1]["sha"] == REF
    assert announced[-1]["previous_sha"] == OLD_SHA
    assert announced[-1]["subjects"] == ["feat: alpha", "fix: beta"]
    assert announced[-1]["tag"] and announced[-1]["tag"].startswith("prod/")

    # 2. Pre-change refusal (already-live / order guard) does NOT announce a deploy
    announced.clear()
    with pytest.raises(SystemExit) as e:
        L.release_prod(REF, kind="forward", reason="already live")
    assert e.value.code == L.DEPLOY_ALREADY_LIVE
    assert announced == []

    prod.image = OLD
    prod.ancestor_rc = 1
    with pytest.raises(SystemExit) as e:
        L.release_prod(REF, kind="forward", reason="out of order")
    assert e.value.code == L.DEPLOY_REFUSED
    assert announced == []

    # 3. Undo success announces undo deployed
    prod.ancestor_rc = 1
    prod.image = OLD
    L.release_prod(REF, kind="undo", reason="money test red")
    assert len(announced) == 1
    assert announced[-1]["outcome"] == "deployed" and announced[-1]["kind"] == "undo"
    prod.ancestor_rc = 0

    # 4. Self-undone failure announces failed_self_undone and re-raises SystemExit
    announced.clear()
    prod.image = OLD
    prod.db = "r1"
    prod.unhealthy.add(NEW)
    with pytest.raises(SystemExit):
        L.release_prod(REF, kind="forward", reason="bad release")
    assert len(announced) == 1
    assert announced[-1]["outcome"] == "failed_self_undone"
    assert announced[-1]["health"] == "ok"

    # 5. UNDO INCOMPLETE announces undo_incomplete and re-raises SystemExit
    announced.clear()
    prod.unhealthy.clear()
    prod.image = OLD
    prod.db = "r1"
    prod.upgrade = "fails-halfway"
    prod.restore_ok = False
    with pytest.raises(SystemExit):
        L.release_prod(REF, kind="forward", reason="worse release")
    assert len(announced) == 1
    assert announced[-1]["outcome"] == "undo_incomplete"


