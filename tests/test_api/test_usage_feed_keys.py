"""Inert feed-auth stage: combined custody happy path first, then fixed catches.

All credentials, registries, mounts and script operations are fixtures. No HTTP
server, Docker daemon, provider, epoch operation or live credential is used.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import api_key as script
from temper_ai.api import api_keys, auth, caller, run_tokens
from temper_ai.api import usage_feed_keys as feed

RAW = "tk_fixture-feed-canary-000000000000000000000000000"
HASH = api_keys.hash_key(RAW)
PRINCIPAL = "usage-collector"
REAL_MOUNT_SOURCES = script._feed_mount_sources


def write_store(path: Path, entries: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"keys": entries if entries is not None else {PRINCIPAL: HASH}}))


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    feed_file = tmp_path / "path-canary" / "feed.json"
    monkeypatch.setenv(feed.KEYS_FILE_ENV_VAR, str(feed_file))
    monkeypatch.setenv(api_keys.KEYS_FILE_ENV_VAR, str(tmp_path / "general.json"))
    for name in ("TEMPER_API_TOKEN", "TEMPER_API_TOKENS_FILE", "TEMPER_USAGE_FEED_KEYS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(auth, "_file_cache", None)
    monkeypatch.setattr(feed, "_last_count", None)
    api_keys._reset_for_tests()
    yield feed_file
    api_keys._reset_for_tests()


@pytest.fixture
def custody(isolated, tmp_path, monkeypatch):
    monkeypatch.setattr(script.sys, "path", list(script.sys.path))
    monkeypatch.setattr(script, "_feed_mount_sources", lambda: [script.REPO, Path.home() / "temper-ai"])
    monkeypatch.setattr(script.secrets, "token_urlsafe", lambda size: RAW.removeprefix("tk_"))
    return SimpleNamespace(registry=isolated, raw_dir=tmp_path / "private")


def command(custody, action: str, name: str | None = PRINCIPAL) -> int:
    args = [action]
    if name is not None:
        args.append(name)
    return script.main([*args, "--feed", "--keys-file", str(custody.registry),
                        "--key-dir", str(custody.raw_dir)])


def test_opening_combined_add_load_feed_only_identification_and_revoke(custody, capsys, caplog):
    """One feature journey; raw fixture bytes never leave protected storage."""
    caplog.set_level(logging.INFO)
    unrelated_progress = custody.raw_dir.parent / "unrelated-reader-evidence"
    unrelated_progress.write_bytes(b"settled-cursor-and-evidence-remain")
    assert command(custody, "add") == 0
    raw_file = custody.raw_dir / f"{PRINCIPAL}.key"
    assert raw_file.read_text() == RAW + "\n"
    assert stat.S_IMODE(custody.raw_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(raw_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(custody.registry.stat().st_mode) == 0o644
    assert json.loads(custody.registry.read_text()) == {"keys": {PRINCIPAL: HASH}}
    assert feed.feed_keys() == {PRINCIPAL: HASH}
    assert feed.identify_feed_key(RAW) == PRINCIPAL
    assert feed.identify_feed_headers([(b"Authorization", f"Bearer {RAW}".encode())]) == PRINCIPAL
    assert api_keys.identify_key(RAW) is None
    assert auth.identify(RAW) is None
    assert auth.identify_caller_name(RAW, "fixture-not-loopback") is None
    assert command(custody, "list", None) == 0
    assert command(custody, "remove") == 0
    assert not raw_file.exists()
    assert feed.identify_feed_key(RAW) is None
    assert feed.feed_keys() == {}
    assert unrelated_progress.read_bytes() == b"settled-cursor-and-evidence-remain"
    out = capsys.readouterr()
    assert PRINCIPAL in out.out  # list prints validated names, never keys/hashes
    for canary in (RAW, HASH, str(custody.registry), str(raw_file)):
        assert canary not in out.out + out.err + caplog.text
    assert not list(custody.registry.parent.glob(".usage-feed-*"))


BAD_STORES = [
    "", "   ", "{not-json:" + RAW, "null", "[]", "true", '"keys"', "{}",
    '{"keys":null}', '{"keys":[]}', '{"keys":true}',
    json.dumps({"keys": {PRINCIPAL: HASH}, "extra": RAW}),
    '{"keys":{},"keys":{"usage-collector":"' + HASH + '"}}',
    '{"keys":{"usage-collector":"' + HASH + '","usage-collector":"' + HASH + '"}}',
    json.dumps({"keys": {f"reader-{n}": HASH for n in range(17)}}),
    *[json.dumps({"keys": {PRINCIPAL: HASH, name: HASH}}) for name in (
        "", "Uppercase", "has space", "../escape", "a" * 64, "ends-in-newline\n",
        "server", "pickup", "carry-on", "unknown", "shared", "box", "slack", "telegram",
        "box:r", "slack:u", "telegram:u", "hook:s", "trigger:s",
    )],
    *[json.dumps({"keys": {PRINCIPAL: HASH, "other": value}}) for value in (
        RAW, HASH.removeprefix("sha256:"), "sha256:" + "A" * 64,
        "sha256:" + "0" * 63, "sha256:" + "0" * 65, " " + HASH, HASH + "\n",
        None, 12, True, {}, [],
    )],
]


@pytest.mark.parametrize("text", BAD_STORES, ids=lambda text: f"invalid-{BAD_STORES.index(text)}")
def test_every_invalid_class_discards_whole_store_not_just_bad_entry(isolated, text, caplog):
    write_store(isolated)  # start authorized, then prove no stale/partial admission
    assert feed.identify_feed_key(RAW) == PRINCIPAL
    isolated.write_text(text)
    keys, problems = feed.parse_keys(text)
    assert keys == {} and problems == ["invalid feed key store"]
    assert feed.feed_keys() == {}
    assert feed.identify_feed_key(RAW) is None
    assert RAW not in caplog.text and HASH not in caplog.text
    assert str(isolated) not in caplog.text


@pytest.mark.parametrize("kind", ["missing", "unreadable", "directory", "non-utf8", "empty-keys"])
def test_store_off_for_missing_unreadable_directory_encoding_and_empty(isolated, monkeypatch, kind, caplog):
    write_store(isolated)
    assert feed.identify_feed_key(RAW) == PRINCIPAL
    if kind == "missing":
        isolated.unlink()
    elif kind == "directory":
        isolated.unlink()
        isolated.mkdir()
    elif kind == "non-utf8":
        isolated.write_bytes(b"\xff\xfe")
    elif kind == "empty-keys":
        write_store(isolated, {})
    else:
        original = Path.read_text

        def unreadable(path, *args, **kwargs):
            if path == isolated:
                raise PermissionError(RAW)
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", unreadable)
    assert feed.feed_keys() == {}
    assert feed.identify_feed_key(RAW) is None
    assert RAW not in caplog.text and str(isolated) not in caplog.text


def test_clean_limits_and_no_mutable_cache_escape(isolated):
    entries = {f"reader-{n}": api_keys.hash_key(f"fixture-{n}") for n in range(14)}
    entries.update({"a": HASH, "b" * 63: HASH})
    write_store(isolated, entries)
    assert len(feed.feed_keys()) == 16
    returned = feed.feed_keys()
    returned.clear()
    assert feed.feed_keys() == entries
    assert feed.parse_keys('{"keys":{}}') == ({}, [])


def test_reload_same_size_mtime_atomic_replace_and_rotation_preserve_progress(isolated, tmp_path):
    next_raw = RAW.replace("0000", "1111")
    next_hash = api_keys.hash_key(next_raw)
    write_store(isolated)
    old_stat = isolated.stat()
    assert feed.identify_feed_key(RAW) == PRINCIPAL
    write_store(isolated, {PRINCIPAL: next_hash})
    os.utime(isolated, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert isolated.stat().st_size == old_stat.st_size
    assert feed.identify_feed_key(RAW) is None
    assert feed.identify_feed_key(next_raw) == PRINCIPAL
    replacement = tmp_path / "replacement.json"
    write_store(replacement)
    os.utime(replacement, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    replacement.replace(isolated)
    assert feed.identify_feed_key(next_raw) is None
    assert feed.identify_feed_key(RAW) == PRINCIPAL


def test_inline_env_ignored_default_existing_config_path_no_provisioning(tmp_path, isolated, monkeypatch):
    config = tmp_path / "config-fixture"
    monkeypatch.setenv("TEMPER_CONFIG_DIR", str(config))
    monkeypatch.delenv(feed.KEYS_FILE_ENV_VAR)
    monkeypatch.setenv("TEMPER_USAGE_FEED_KEYS", json.dumps({PRINCIPAL: RAW}))
    expected = config / "api" / "local" / "usage-feed-keys.json"
    assert feed.keys_path() == expected
    assert feed.identify_feed_key(RAW) is None
    assert not config.exists()  # neither lookup nor default path provisions anything
    write_store(expected)
    assert feed.identify_feed_key(RAW) == PRINCIPAL
    monkeypatch.setenv(feed.KEYS_FILE_ENV_VAR, str(isolated))
    assert feed.identify_feed_key(RAW) is None  # explicit missing file: no default fallback


@pytest.mark.parametrize("kind", ["run", "github-run", "shared", "tokens-file", "general"])
def test_other_credential_class_cannot_promote_even_with_same_feed_hash(isolated, tmp_path, monkeypatch, kind):
    raw = {"run": "trun_fixture", "github-run": "tghk_fixture"}.get(kind, RAW)
    write_store(isolated, {PRINCIPAL: api_keys.hash_key(raw)})

    def no_database(*args, **kwargs):
        pytest.fail("feed authentication must not look up a run or use the database")

    monkeypatch.setattr(run_tokens, "identify_run_key", no_database)
    from temper_ai.database import session

    monkeypatch.setattr(session, "get_session", no_database)
    if kind == "shared":
        monkeypatch.setenv("TEMPER_API_TOKEN", raw)
    elif kind == "tokens-file":
        path = tmp_path / "shared-fixture.json"
        path.write_text(json.dumps({"other-client": raw}))
        monkeypatch.setenv("TEMPER_API_TOKENS_FILE", str(path))
    elif kind == "general":
        write_store(api_keys.keys_path(), {"general-writer": api_keys.hash_key(raw)})
    assert feed.identify_feed_key(raw) is None


@pytest.mark.parametrize("raw", [None, "", "not-a-key", "\u00e9", "\ud800"])
def test_absent_unknown_or_non_ascii_credential_refused(isolated, raw):
    write_store(isolated)
    assert feed.identify_feed_key(raw) is None


def test_off_and_absent_short_circuit_before_other_credentials(isolated, monkeypatch):
    def forbidden(*args):
        pytest.fail("no credential-class lookup before store ON and nonempty header")

    monkeypatch.setattr(auth, "identify", forbidden)
    monkeypatch.setattr(api_keys, "identify_key", forbidden)
    monkeypatch.setattr(run_tokens, "is_run_key", forbidden)
    assert feed.identify_feed_key(RAW) is None
    write_store(isolated)
    assert feed.identify_feed_key(None) is None
    assert feed.identify_feed_key("") is None


@pytest.mark.parametrize("match", ["reader-0", "reader-1", "reader-2", None])
def test_all_hashes_compared_constant_time_even_after_match(isolated, monkeypatch, match):
    raw = "fixture-unknown" if match is None else match
    entries = {f"reader-{n}": api_keys.hash_key(f"reader-{n}") for n in range(3)}
    write_store(isolated, entries)
    original = feed.hmac.compare_digest
    comparisons = []

    def compared(left, right):
        comparisons.append((left, right))
        return original(left, right)

    monkeypatch.setattr(feed.hmac, "compare_digest", compared)
    assert feed.identify_feed_key(raw) == match
    assert comparisons == [(api_keys.hash_key(raw), value) for value in entries.values()]


@pytest.mark.parametrize(("headers", "accepted"), [
    ([(b"Authorization", f"Bearer {RAW}".encode())], True),
    ([(b"authorization", f"bEaReR {RAW}".encode())], True),
    ([(b"X-Temper-Token", RAW.encode())], True),
    ([(b"authorization", b"Bearer wrong"), (b"x-temper-token", RAW.encode())], False),
    ([(b"authorization", b"Bearer "), (b"x-temper-token", RAW.encode())], False),
    ([(b"authorization", b"Basic wrong"), (b"x-temper-token", RAW.encode())], True),
    ([(b"authorization", b"Bearer wrong"), (b"authorization", f"Bearer {RAW}".encode())], False),
    ([(b"cookie", f"temper_token={RAW}".encode())], False),
    ([(b"x-temper-token", b"   ")], False),
    ([], False),
])
def test_header_only_bearer_precedence(isolated, headers, accepted):
    write_store(isolated)
    assert feed.identify_feed_headers(headers) == (PRINCIPAL if accepted else None)


def test_query_and_cookie_are_not_accepted_by_header_extractor():
    assert auth._write_key({"headers": [(b"cookie", f"temper_token={RAW}".encode())],
                            "query_string": f"token={RAW}".encode()}) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("global_auth", [True, False])
async def test_feed_key_stays_unknown_to_other_http_auth_paths(isolated, monkeypatch, global_auth):
    write_store(isolated)
    if global_auth:
        monkeypatch.setenv("TEMPER_API_TOKEN", "fixture-shared-token")
    reached = []
    messages = []

    async def inner(scope, receive, send):
        reached.append(caller.current_caller().name)
        await send({"type": "http.response.start", "status": 200})

    async def send(message):
        messages.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    edge = auth.TokenAuthMiddleware(auth.CallerMiddleware(inner))
    await edge({"type": "http", "method": "POST", "path": "/api/runs",
                "client": ("fixture-source", 1), "headers": [(b"authorization", f"Bearer {RAW}".encode())]},
               receive, send)
    assert messages[0]["status"] == (401 if global_auth else 200)
    assert reached == ([] if global_auth else [None])
    assert feed.identify_feed_key(RAW) == PRINCIPAL


def test_feed_script_list_absent_is_inert_and_uses_dedicated_default(custody, monkeypatch, capsys):
    monkeypatch.setattr(script, "DEFAULT_KEYS_FILE", custody.registry.parent / "general.json")
    assert script.main(["list", "--feed", "--key-dir", str(custody.raw_dir)]) == 0
    assert not custody.registry.parent.exists() and not custody.raw_dir.exists()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("action", ["add", "remove", "list"])
def test_feed_script_refuses_invalid_existing_store_without_partial_rewrite(custody, capsys, action):
    custody.registry.parent.mkdir(parents=True)
    invalid = json.dumps({"keys": {PRINCIPAL: HASH, "bad": RAW}})
    custody.registry.write_text(invalid)
    assert command(custody, action) == 2
    assert custody.registry.read_text() == invalid
    assert not custody.raw_dir.exists()
    out = capsys.readouterr()
    assert out.out == "" and out.err == "feed key operation refused\n"


@pytest.mark.parametrize("name", ["../escape", "server", "carry-on", "box:r", "bad\n", "a" * 64])
@pytest.mark.parametrize("action", ["add", "remove"])
def test_script_name_guard_before_filesystem_change(custody, capsys, name, action):
    assert command(custody, action, name) == 2
    assert not custody.registry.exists() and not custody.raw_dir.exists()
    assert name not in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["repo", "worktree", "mount", "mount-parent", "mount-symlink"])
def test_script_refuses_every_repo_mount_overlap_before_writing(custody, tmp_path, monkeypatch, kind):
    root = tmp_path / kind
    root.mkdir()
    if kind == "repo":
        monkeypatch.setattr(script, "REPO", root)
    if kind == "mount-parent":
        custody.raw_dir = root
        mounted = root / "child"
    elif kind == "mount-symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        custody.raw_dir = alias / "raw"
        mounted = root
    else:
        custody.raw_dir = root / "raw"
        mounted = root
    monkeypatch.setattr(script, "_feed_mount_sources", lambda: [mounted])
    assert command(custody, "add") == 2
    assert not custody.registry.exists()
    assert not (custody.raw_dir / f"{PRINCIPAL}.key").exists()


@pytest.mark.parametrize("kind", ["general-default", "general-env", "tokens-file", "registry-symlink", "raw-overlap"])
def test_script_cannot_write_feed_hashes_into_other_auth_store(custody, tmp_path, monkeypatch, kind):
    original = custody.registry
    if kind == "general-default":
        monkeypatch.setattr(script, "DEFAULT_KEYS_FILE", custody.registry)
    elif kind == "general-env":
        monkeypatch.setenv(api_keys.KEYS_FILE_ENV_VAR, str(custody.registry))
    elif kind == "tokens-file":
        monkeypatch.setenv("TEMPER_API_TOKENS_FILE", str(custody.registry))
    elif kind == "registry-symlink":
        target = tmp_path / "separate-target.json"
        write_store(target)
        custody.registry.parent.mkdir(parents=True)
        custody.registry.symlink_to(target)
    else:
        custody.registry = custody.raw_dir / "feed.json"
    assert command(custody, "add") == 2
    assert not custody.raw_dir.exists()
    if kind == "registry-symlink":
        assert original.is_symlink() and target.read_text() == json.dumps({"keys": {PRINCIPAL: HASH}})
    else:
        assert not custody.registry.exists()


def test_duplicate_raw_file_and_remove_without_registration_do_not_touch_foreign_file(custody):
    custody.raw_dir.mkdir()
    raw_file = custody.raw_dir / f"{PRINCIPAL}.key"
    raw_file.write_bytes(b"foreign-key-kept")
    assert command(custody, "add") == 2
    assert raw_file.read_bytes() == b"foreign-key-kept"
    assert command(custody, "remove") == 0
    assert raw_file.read_bytes() == b"foreign-key-kept"
    assert not custody.registry.exists()


def test_existing_registered_name_and_full_store_refuse_add(custody):
    write_store(custody.registry)
    assert command(custody, "add") == 2
    assert not custody.raw_dir.exists()
    entries = {f"reader-{n}": HASH for n in range(16)}
    write_store(custody.registry, entries)
    assert command(custody, "add") == 2
    assert feed.feed_keys() == entries and not custody.raw_dir.exists()


def test_script_refuses_name_owned_by_general_auth(custody):
    write_store(api_keys.keys_path(), {PRINCIPAL: api_keys.hash_key("fixture-general")})
    assert command(custody, "add") == 2
    assert not custody.registry.exists() and not custody.raw_dir.exists()


def test_raw_exclusive_create_wins_race_and_never_overwrites(custody, monkeypatch):
    raw_file = custody.raw_dir / f"{PRINCIPAL}.key"
    original = script.os.open
    observed = []

    def raced(path, flags, mode=0o777, **kwargs):
        if Path(path) == raw_file:
            observed.append(flags)
            raw_file.write_bytes(b"racing-foreign-key-kept")
        return original(path, flags, mode, **kwargs)

    monkeypatch.setattr(script.os, "open", raced)
    assert command(custody, "add") == 2
    assert len(observed) == 1
    assert observed[0] & os.O_EXCL and observed[0] & os.O_NOFOLLOW
    assert raw_file.read_bytes() == b"racing-foreign-key-kept"
    assert not custody.registry.exists()


@pytest.mark.parametrize("mask", [0, 0o777])
def test_raw_permissions_are_exact_even_with_extreme_umask(custody, mask):
    custody.registry.parent.mkdir(parents=True)
    previous = os.umask(mask)
    try:
        assert command(custody, "add") == 0
    finally:
        os.umask(previous)
    assert stat.S_IMODE(custody.raw_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((custody.raw_dir / f"{PRINCIPAL}.key").stat().st_mode) == 0o600


def test_raw_directory_symlink_and_wrong_owner_refused(custody, tmp_path, monkeypatch):
    actual = tmp_path / "actual-private"
    actual.mkdir()
    custody.raw_dir.symlink_to(actual, target_is_directory=True)
    assert command(custody, "add") == 2
    custody.raw_dir.unlink()
    custody.raw_dir.mkdir()
    monkeypatch.setattr(script.os, "getuid", lambda: -1)
    assert command(custody, "add") == 2
    assert not custody.registry.exists() and list(actual.iterdir()) == []


def test_script_hash_save_failure_cleans_only_new_raw_and_redacts_exception(custody, monkeypatch, capsys):
    def failed(*args):
        raise OSError(RAW)

    monkeypatch.setattr(script, "_feed_save", failed)
    assert command(custody, "add") == 2
    assert not (custody.raw_dir / f"{PRINCIPAL}.key").exists()
    assert not custody.registry.exists()
    out = capsys.readouterr()
    assert out.out == "" and out.err == "feed key operation refused\n"


def test_concurrent_supported_feed_writers_keep_both_entries(custody):
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(command, custody, "add", name) for name in ("reader-a", "reader-b")]
        assert [future.result() for future in futures] == [0, 0]
    assert set(feed.feed_keys()) == {"reader-a", "reader-b"}
    assert (custody.raw_dir / "reader-a.key").is_file()
    assert (custody.raw_dir / "reader-b.key").is_file()


def test_readonly_mount_inspector_covers_worktrees_and_container_sources(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs == {"capture_output": True, "text": True, "check": True, "timeout": 10}
        outputs = ["worktree /fixture/worktree\nHEAD fixture\n\n", "fixture-container\n",
                   json.dumps([{"Source": "/fixture/mounted"}, {"Type": "tmpfs", "Source": ""}]) + "\n"]
        return SimpleNamespace(stdout=outputs[len(calls) - 1])

    monkeypatch.setattr(script.subprocess, "run", run)
    roots = REAL_MOUNT_SOURCES()
    assert Path("/fixture/worktree") in roots and Path("/fixture/mounted") in roots
    assert calls[1] == ["docker", "ps", "-aq"]
    assert calls[2] == ["docker", "inspect", "--format", "{{json .Mounts}}", "fixture-container"]


@pytest.mark.parametrize("failure", ["unavailable", "timeout", "bad-json", "bad-shape", "bad-source", "missing-mounts"])
def test_mount_inspection_unknown_refuses_custody_and_redacts(custody, monkeypatch, capsys, failure):
    def run(argv, **kwargs):
        if argv[0] == "git":
            return SimpleNamespace(stdout="worktree /fixture/worktree\n")
        if failure == "unavailable":
            raise subprocess.CalledProcessError(1, argv, output=RAW, stderr=RAW)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 10, output=RAW, stderr=RAW)
        if argv[1] == "ps":
            return SimpleNamespace(stdout="fixture-container\n")
        values = {"bad-json": RAW, "bad-shape": "{}", "bad-source": '[{"Source":null}]',
                  "missing-mounts": ""}
        return SimpleNamespace(stdout=values[failure])

    monkeypatch.setattr(script, "_feed_mount_sources", REAL_MOUNT_SOURCES)
    monkeypatch.setattr(script.subprocess, "run", run)
    assert command(custody, "add") == 2
    assert not custody.registry.exists() and not custody.raw_dir.exists()
    out = capsys.readouterr()
    assert out.out == "" and out.err == "feed key operation refused\n"


def test_existing_general_script_path_unchanged_no_mount_inspection(tmp_path, monkeypatch, capsys):
    keys = tmp_path / "general-fixture.json"
    raw_dir = tmp_path / "general-private"

    def forbidden():
        pytest.fail("the unchanged general script does not enter feed custody")

    monkeypatch.setattr(script, "_feed_mount_sources", forbidden)
    args = ["--keys-file", str(keys), "--key-dir", str(raw_dir)]
    assert script.main(["add", "fixture-client", *args]) == 0
    assert script.main(["list", *args]) == 0
    assert "fixture-client" in capsys.readouterr().out
    assert script.main(["remove", "fixture-client", *args]) == 0
    assert json.loads(keys.read_text()) == {"keys": {}}
    assert not (raw_dir / "fixture-client.key").exists()
