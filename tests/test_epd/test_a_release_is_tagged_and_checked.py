"""A production release leaves a record of what ran when, and checks it shipped the code it meant to.

Systems #101 (RollCall rm-74d2b642; deploy audit #100 P1, P3, O1, O3, T3):
- the order guard: deploy_prod refuses, before anything changes, an older (or unrelated) commit over
  the one live (DEPLOY_REFUSED) and the commit already live (DEPLOY_ALREADY_LIVE); kind undo may go back;
- the live-code check: after `standee up` the container's standee.commit label must be ref[:12], its
  image's revision label ref (when the image has one) and /api/health's commit ref (when it says one);
  a mismatch is undone like any failed release, "not available" is logged and passes (an undo to a
  commit older than rollcall's GIT_SHA Dockerfile change, or than 5243d892);
- the tag: a healthy release is tagged prod/<UTC yyyymmdd-hhmm> (-2, -3 in the same minute) on origin,
  saying its kind, the commit before, the reason and its restore points; a failed push leaves the
  release live and tells RollCall;
- standee's lock: "another standee command holds the lock" from the pre-up backup or `standee up` is
  waited out, 30 s at a time, for up to 20 min; then the release is called off (DEPLOY_BUSY), unchanged.

The fake prod (git, docker, standee, /api/health) is test_a_failed_release_rolls_back's.
"""

from tests.test_epd import test_a_failed_release_rolls_back as fake

L, prod = fake.L, fake.prod  # its fixtures, by name: epd_loop and the fake prod

REF, OLD_SHA, OLD, NEW, REVISION = fake.REF, fake.OLD_SHA, fake.OLD, fake.NEW, fake.REVISION
TAG = "prod/20261105-2031"  # the fixture's release_time, 2026-11-05 20:31:07 UTC
release, release_code = fake.release, fake.release_code


# ---- the tag ----------------------------------------------------------------------------------------


def test_a_healthy_release_is_tagged_on_origin_with_what_ran_before_and_why(L, prod, capsys):
    died, said = release(L, capsys, reason="master c0ffee12, unchanged since 20:27")
    assert not died, said
    assert prod.pushed == [TAG] and prod.remote_tags == {TAG: REF}
    message = prod.tag_message[TAG]
    assert message.splitlines()[0] == f"RollCall prod release {REF[:12]}"
    assert "kind: forward\n" in message and f"commit: {REF}\n" in message
    assert f"previous: {OLD_SHA}\n" in message  # the image's revision label before the release
    assert "reason: master c0ffee12, unchanged since 20:27\n" in message
    # T3: its restore points, the copy before `up` and the one before the migration
    assert f"backup: {prod.backups[0][0]}\n" in message
    assert f"backup before migration: {prod.backups[1][0]}\n" in message
    assert "released: 2026-11-05T20:31:07Z by epd_loop.deploy_prod" in message
    assert f"tagged the release {TAG} on {REF[:12]} and pushed it to origin" in said
    assert prod.told == []


def test_a_second_release_in_the_same_minute_gets_the_next_number(L, prod, capsys):
    prod.remote_tags = {TAG: OLD_SHA, f"{TAG}-2": OLD_SHA}
    prod.local_tags = {f"{TAG}-3": OLD_SHA}  # made here once, never pushed: taken too
    died, said = release(L, capsys)
    assert not died, said
    assert prod.pushed == [f"{TAG}-4"]


def test_tag_names_and_their_order(L):
    at = L.dt.datetime(2026, 11, 5, 12, 31, 59, tzinfo=L.dt.timezone(L.dt.timedelta(hours=-8)))
    assert L.release_tag_name(at, set()) == TAG  # UTC, to the minute
    assert L.release_tag_name(at, {TAG}) == f"{TAG}-2"
    tags = {"prod/20261105-2031": "a" * 40, "prod/20261105-2031-2": "b" * 40, "prod/20261105-2031-10": "c" * 40,
            "prod/20261104-2359": "d" * 40, "prod/not-a-release": "e" * 40, "prod/20261106-0000": ""}
    assert L.newest_release_commit(tags) == "c" * 40  # -10 after -2; a tag whose commit is unread is skipped
    assert L.newest_release_commit({}) == ""


def test_with_no_label_the_commit_before_is_the_newest_tag_else_unknown(L, prod, capsys):
    prod.labels_of[OLD] = {"com.docker.compose.project": "rollcall-prod"}  # a container standee did not label
    prod.remote_tags = {"prod/20261104-0900": "9" * 40, "prod/20261105-0800": "8" * 40}
    died, said = release(L, capsys)
    assert not died, said
    assert "order guard: no running commit known" in said
    assert f"previous: {'8' * 40}\n" in prod.tag_message[TAG]
    assert L.release_tag_message(REF, "undo", "", "", [], L.release_time()).count("previous: unknown\n") == 1
    assert "reason: (none given)\n" in L.release_tag_message(REF, "undo", "", "", [], L.release_time())


def test_an_undo_is_tagged_as_an_undo(L, prod, capsys):
    prod.ancestor_rc = 1  # the live commit is newer: what an undo is for
    died, said = release(L, capsys, kind="undo", reason="money test failed on a1a1a1a1")
    assert not died, said
    assert prod.asked_ancestor == []  # an undo never asks the order guard
    assert "kind: undo\n" in prod.tag_message[TAG] and "reason: money test failed on a1a1a1a1\n" in prod.tag_message[TAG]
    assert f"previous: {OLD_SHA}\n" in prod.tag_message[TAG]


def test_a_failed_push_leaves_the_release_live_and_tells_rollcall(L, prod, capsys):
    prod.push_fails = True
    died, said = release(L, capsys)
    assert not died, said
    assert prod.image == NEW and "rollback" not in prod.steps()
    assert prod.remote_tags == {} and TAG in prod.local_tags  # kept here, for a push by hand
    assert "WARNING: deploy_prod: release of c0ffee123456 (forward) is live and healthy, but it is NOT TAGGED" in said
    (told,) = prod.told
    assert "NOT TAGGED" in told and "Could not read from remote repository" in told
    assert f"push origin refs/tags/{TAG}" in told


def test_a_tag_that_cannot_be_made_leaves_the_release_live_and_tells_rollcall(L, prod, capsys):
    prod.tag_fails = True
    died, said = release(L, capsys)
    assert not died, said
    assert prod.pushed == [] and prod.image == NEW
    assert len(prod.told) == 1 and "`git tag -a prod/20261105-2031` exited 128" in prod.told[0]


def test_tagging_never_raises(L, prod, capsys, monkeypatch):
    def broken():
        raise OSError("no such file: git")

    monkeypatch.setattr(L, "release_tags", broken)
    died, said = release(L, capsys)
    assert not died, said
    assert "OSError: no such file: git" in prod.told[0]


def test_a_failed_release_is_not_tagged(L, prod, capsys):
    prod.unhealthy.add(NEW)
    died, _ = release(L, capsys)
    assert died and prod.image == OLD
    assert prod.local_tags == {} and prod.remote_tags == {} and prod.told == []


# ---- the order guard ---------------------------------------------------------------------------------


def test_an_older_commit_over_a_newer_one_is_refused_before_anything_changes(L, prod, capsys):
    prod.ancestor_rc = 1
    code, said = release_code(L, capsys)
    assert code == L.DEPLOY_REFUSED == 76
    assert prod.asked_ancestor == [(OLD_SHA, REF)]
    assert prod.steps() == [] and prod.up_env == [] and prod.image == OLD  # not even a backup
    assert f"{OLD_SHA[:12]}, live now, is not an ancestor of {REF[:12]}" in said and "nothing was changed" in said


def test_a_commit_this_checkout_cannot_place_is_refused(L, prod, capsys):
    prod.ancestor_rc = 128
    code, said = release_code(L, capsys)
    assert code == L.DEPLOY_REFUSED and prod.steps() == []
    assert "could not tell whether" in said and "exited 128: fatal: Not a valid commit name" in said


def test_the_commit_already_live_is_refused_as_already_live(L, prod, capsys):
    prod.labels_of[OLD] = {"standee.commit": REF[:12], REVISION: REF}
    for kind in ("forward", "undo"):
        code, said = release_code(L, capsys, kind=kind)
        assert code == L.DEPLOY_ALREADY_LIVE == 77
        assert f"{REF[:12]} is already live" in said
    assert prod.steps() == [] and prod.asked_ancestor == []


def test_without_a_revision_label_standees_commit_label_is_the_running_commit(L, prod, capsys):
    prod.labels_of[OLD] = {"standee.commit": OLD_SHA[:12]}  # an image from before the GIT_SHA build arg
    died, said = release(L, capsys)
    assert not died, said
    assert prod.asked_ancestor == [(OLD_SHA[:12], REF)]
    assert f"previous: {OLD_SHA}\n" in prod.tag_message[TAG]  # the short sha, made full by the checkout
    prod.labels_of[NEW] = {"standee.commit": OLD_SHA[:12]}
    assert L.running_commit(prod.labels_of[NEW]) == OLD_SHA[:12]
    assert L.running_commit({"standee.commit": "", REVISION: "unknown"}) == ""


def test_with_no_live_container_the_order_is_not_checked(L, prod, capsys):
    prod.image = ""
    code, said = release_code(L, capsys)
    assert prod.asked_ancestor == [] and "order guard: no running commit known" in said
    assert prod.steps()[:2] == ["backup", "up"]


def test_a_kind_other_than_forward_or_undo_or_a_short_ref_is_refused(L, prod, capsys):
    code, said = release_code(L, capsys, kind="deploy")
    assert code == 1 and "kind must be one of forward, undo, got 'deploy'" in said
    code, said = release_code(L, capsys, ref=REF[:12])
    assert code == 1 and "full 40-character commit sha" in said
    assert prod.steps() == []


# ---- the live-code check -------------------------------------------------------------------------------


def test_the_image_is_built_with_the_commit_it_ships(L, prod, capsys):
    died, said = release(L, capsys)
    assert not died, said
    assert [env["GIT_SHA"] for env in prod.up_env] == [REF]
    assert prod.up_env[0]["ROLLCALL_HOME"] == str(L.PROD_HOME)  # the rest of the environment goes along
    assert f"live code: standee.commit {REF[:12]} and image label {REVISION} {REF[:12]}" in said
    assert f"live code: /api/health reports commit {REF[:12]}" in said


def test_a_container_whose_standee_label_is_another_commit_is_undone(L, prod, capsys):
    prod.labels_of[NEW] = {"standee.commit": "deadbeef0000", REVISION: REF}
    died, said = release(L, capsys)
    assert died and prod.image == OLD
    assert prod.steps() == ["backup", "up", "mounts", "rollback", "mounts", "health"]
    assert "failed while checking the code that started is the commit shipped" in said
    assert "standee.commit label is deadbeef0000, not c0ffee123456" in said and "Prod now: healthy" in said
    assert prod.local_tags == {}


def test_an_image_built_from_another_commit_is_undone(L, prod, capsys):
    """The shared-image hazard: a dev image (another commit) starting on prod."""
    prod.labels_of[NEW] = {"standee.commit": REF[:12], REVISION: "d" * 40}
    died, said = release(L, capsys)
    assert died and prod.image == OLD
    assert f"the live image's {REVISION} label is {'d' * 40}, not {REF}" in said


def test_an_app_reporting_another_commit_is_undone_before_any_migration(L, prod, capsys):
    prod.commit_of[NEW] = "d" * 40
    died, said = release(L, capsys)
    assert died and prod.image == OLD and prod.db == "r1"
    assert prod.steps() == ["backup", "up", "mounts", "url", "rollback", "mounts", "health"]
    assert "failed while checking the app that answers is the commit shipped" in said
    assert f"/api/health reports commit {'d' * 40}, not {REF}" in said


def test_an_older_image_without_the_label_or_the_health_field_is_logged_not_failed(L, prod, capsys):
    """An undo to a green commit from before the Dockerfile's GIT_SHA and before rollcall 5243d892."""
    prod.labels_of[NEW] = {"standee.commit": REF[:12]}
    prod.commit_of[NEW] = None
    died, said = release(L, capsys, kind="undo", reason="money test failed")
    assert not died, said
    assert f"image label {REVISION} not available (absent" in said
    assert "/api/health commit not available (absent" in said
    assert prod.pushed == [TAG]


def test_unknown_is_not_available_either(L, prod, capsys):
    """Code with the health field, image without ROLLCALL_COMMIT (or a build without GIT_SHA)."""
    prod.labels_of[NEW] = {"standee.commit": REF[:12], REVISION: "unknown"}
    prod.commit_of[NEW] = "unknown"
    died, said = release(L, capsys)
    assert not died, said
    assert f"image label {REVISION} not available (unknown" in said
    assert "/api/health commit not available ('unknown'" in said


def test_health_commit_reads_the_field(L, monkeypatch):
    import io
    import json

    slept: list[float] = []
    monkeypatch.setattr(L.time, "sleep", slept.append)

    def answer(body, blinks=0):
        left = [blinks]

        def urlopen(url, timeout=0):
            assert url == L.PROD_URL.rstrip("/") + "/api/health"
            if left[0]:
                left[0] -= 1
                raise L.urllib.error.URLError("Connection refused")
            return io.BytesIO(json.dumps(body).encode())

        monkeypatch.setattr(L.urllib.request, "urlopen", urlopen)

    answer({"ok": True, "commit": REF})
    assert L.prod_health_commit() == REF and slept == []
    answer({"ok": True, "commit": REF}, blinks=2)  # the proxy blinks: asked again
    assert L.prod_health_commit() == REF and slept == [L.HEALTH_PAUSE] * 2
    answer({"ok": True})
    assert L.prod_health_commit() is None
    answer(["not", "an", "object"])
    assert L.prod_health_commit() is None
    slept.clear()
    answer({"ok": True, "commit": REF}, blinks=999)
    assert L.prod_health_commit() is None and len(slept) == L.HEALTH_TRIES - 1


# ---- standee's lock ------------------------------------------------------------------------------------


def test_a_backup_that_finds_standees_lock_taken_waits_and_goes_on(L, prod, capsys):
    prod.lock_busy["backup"] = 3
    died, said = release(L, capsys)
    assert not died, said
    assert prod.steps()[:5] == ["backup"] * 4 + ["up"]
    assert prod.slept == [30, 30, 30]
    assert "the backup before the release: another standee command holds standee's lock; trying again in 30s" in said


def test_an_up_that_finds_standees_lock_taken_waits_without_using_its_tries(L, prod, capsys):
    prod.lock_busy["up"] = 2
    prod.up_fails = [fake.DOCKER_HUB]
    died, said = release(L, capsys)
    assert not died, said
    assert prod.steps()[:5] == ["backup", "up", "up", "up", "up"]
    assert prod.slept == [30, 30, 20]  # the registry's waits stay their own
    assert prod.image == NEW


def test_a_backup_lock_that_never_comes_free_calls_the_release_off_unchanged(L, prod, capsys):
    prod.lock_busy["backup"] = 999
    code, said = release_code(L, capsys)
    assert code == L.DEPLOY_BUSY == 75
    assert set(prod.steps()) == {"backup"} and prod.up_env == [] and prod.image == OLD
    # each try waits 60 s inside standee, then 30 s here: within 20 min in all
    assert len(prod.steps()) == 14 and prod.slept == [30] * 13
    assert "called off: the backup before the release: standee's lock stayed taken by another standee " \
           "command for 20 min" in said and "nothing was changed" in said


def test_an_up_lock_that_never_comes_free_calls_the_release_off_unchanged(L, prod, capsys):
    prod.lock_busy["up"] = 999
    code, said = release_code(L, capsys)
    assert code == L.DEPLOY_BUSY
    assert prod.steps().count("up") == 14 and "rollback" not in prod.steps() and prod.image == OLD
    assert "called off while starting the new images (`standee up`): `standee up`: standee's lock stayed taken" in said
    assert prod.local_tags == {}


def test_only_the_lock_message_counts_as_the_lock(L):
    import subprocess

    def ran(rc, err):
        return subprocess.CompletedProcess([], rc, "", err)

    assert L.standee_lock_busy(ran(1, fake.LOCK_BUSY))
    assert not L.standee_lock_busy(ran(0, fake.LOCK_BUSY))
    assert not L.standee_lock_busy(ran(1, fake.BUILD_BROKE))
    assert L.transient_up_error(fake.LOCK_BUSY) == ""  # the registry's retries are not widened
