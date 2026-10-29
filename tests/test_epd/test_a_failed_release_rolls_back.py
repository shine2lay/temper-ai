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
OLD, NEW = "sha256:" + "a" * 64, "sha256:" + "b" * 64
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
        self.right_mount = f"{(L.REPO_CHECKOUT / 'var').resolve()}->/data"
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

    def steps(self) -> list[str]:
        return self.ran

    # -- the commands deploy_prod runs ------------------------------------------------------------
    def sh(self, cmd, cwd=None, check=True):
        def done(out="", rc=0, err=""):
            if rc and check:
                self.L.die(f"command failed ({rc}): {' '.join(cmd)}")
            return subprocess.CompletedProcess(cmd, rc, out, err)

        match cmd:
            case ["git", "rev-parse", "HEAD"]:
                return done(REF + "\n")
            case ["git", "status", "--porcelain"]:
                return done("")
            case ["docker", "inspect", _, "--format", "{{.Image}}"]:
                return done(self.image + "\n") if self.image else done("", 1, "Error: No such object")
            case ["docker", "inspect", _, "--format", fmt] if "Mounts" in fmt:
                self.ran.append("mounts")
                return done(self.mount + " \n")
            case ["standee", "backup", _]:
                self.ran.append("backup")
                when = f"2026-10-29-1030{len(self.backups):02d}"
                self.backups.append((str(self.dir / "rollcall" / f"{when}.db.gz"), self.db))
                return done(f"rollcall  sqlite  1.2M  {self.backups[-1][0]}\n")
            case ["standee", "backup", _, "--list"]:
                rows = []
                for path, _rev in self.backups:
                    when = path.rsplit("/", 1)[1].split(".")[0]
                    rows.append(f"{when:<20}{'files':<12}{'667B':>9}  {self.dir}/files/{when}")
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


@pytest.fixture
def prod(L, tmp_path, monkeypatch):
    p = Prod(L, tmp_path)
    monkeypatch.setattr(L, "sh", p.sh)
    monkeypatch.setattr(L, "wait_for_url", p.wait_for_url)
    monkeypatch.setattr(L, "prod_api_health", p.api_health)
    monkeypatch.setattr(L, "ensure_qa_password", lambda: "not-a-password")
    monkeypatch.setattr(L.time, "sleep", p.slept.append)
    monkeypatch.setattr(L, "HEALTH_TRIES", 3)
    return p


def release(L, capsys) -> tuple[bool, str]:
    """deploy_prod(REF): (whether it died, everything it said)."""
    try:
        L.deploy_prod(REF)
        died = False
    except SystemExit:
        died = True
    out = capsys.readouterr()
    return died, out.out + out.err


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
