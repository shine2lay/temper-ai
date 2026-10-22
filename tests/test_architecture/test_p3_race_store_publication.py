"""Finite P3 fixture schedules: save-only exclusion, not a historical syscall replay.

The negative binds the original add body to its source digest and forces the common-temp
collision. The HTTP cases use real Store._save, with both handlers entered and (for the
plant) both stale snapshots taken before either publication. No browser/model/service.
"""

import hashlib
import importlib.util
import inspect
import json
import sys
import textwrap
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

BIN = Path(__file__).resolve().parents[2] / "configs/architecture/bin"
if "first_app_p3" not in sys.modules:
    spec = importlib.util.spec_from_file_location("first_app_p3", BIN / "first_app_p3.py")
    p3 = importlib.util.module_from_spec(spec)
    sys.modules["first_app_p3"] = p3
    spec.loader.exec_module(p3)
p3 = sys.modules["first_app_p3"]

WAIT = 5
OLD_ADD_SHA256 = "d9a5bcff2e2878b53b6b299da355b824f22ae28f323561dd0dbb2615ec0baddc"
SAVE_SECTION = """    # Protect the shared temporary pathname, not the deliberately stale read.
    with self.lock:
        self._save(d)
"""


class PublicationLock:
    """Observe the store's existing lock, including a contender while save one holds it."""

    def __init__(self, lock):
        self.lock = lock
        self.state = threading.Lock()
        self.second_attempt = threading.Event()
        self.attempts = self.entries = 0
        self.owner = None

    def __enter__(self):
        with self.state:
            self.attempts += 1
            if self.attempts == 2:
                self.second_attempt.set()
        assert self.lock.acquire(timeout=WAIT), "publication lock never released"
        with self.state:
            assert self.owner is None
            self.owner = threading.get_ident()
            self.entries += 1
        return self

    def __exit__(self, *exc):
        with self.state:
            assert self.owned_here()
            self.owner = None
        self.lock.release()

    def owned_here(self):
        return self.owner == threading.get_ident() and self.lock.locked()


def _pair(call):
    """Start both before collecting either; keep every result/exception on the caller."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call, text) for text in ("a", "b")]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=WAIT * 2))
            except Exception as error:
                outcomes.append(error)
    return outcomes


@pytest.mark.parametrize(("variant", "want"), [("file", 2), ("race_add", 1)])
def test_two_http_201s_with_serial_saves_and_preserved_plant(tmp_path, monkeypatch, variant, want):
    site = p3.materialize("clean", tmp_path / "fixture")
    data = tmp_path / variant
    data.mkdir()
    server = p3.P3Server(site, data, variant, bind_address="127.0.0.1")
    server.start()
    try:
        assert server.srv.server_address[0] == "127.0.0.1"
        store = server.srv.store
        lock = PublicationLock(store.lock)
        monkeypatch.setattr(store, "lock", lock)
        load, save, add = store._load, store._save, store.add
        entries = threading.Barrier(2, timeout=WAIT)
        stale_reads = threading.Barrier(2, timeout=WAIT)
        entered, reads, snapshots, publications, waits = [], [], [], [], []
        state = threading.Lock()
        active = peak = 0

        def wait_only(delay):
            assert delay == 0.4
            waits.append(delay)

        monkeypatch.setattr(p3, "time", SimpleNamespace(sleep=wait_only))

        def observed_load():
            assert lock.owned_here() == (variant == "file"), "stale read moved under the lock"
            d = load()
            with state:
                reads.append(threading.get_ident())
                snapshots.append((id(d), json.loads(json.dumps(d))))
            if variant == "race_add":
                stale_reads.wait()  # neither add may publish until both real snapshots exist
            return d

        def observed_save(d):
            nonlocal active, peak
            assert lock.owned_here(), "final save entered without the existing store lock"
            with state:
                active += 1
                peak = max(peak, active)
                publications.append(json.loads(json.dumps(d)))
                first = len(publications) == 1
            try:
                if first:
                    assert lock.second_attempt.wait(WAIT), "second add never reached the lock"
                    assert lock.entries == 1  # contender cannot enter this publication section
                save(d)  # real write_text(items.tmp) + os.replace(items.tmp, items.json)
            finally:
                with state:
                    active -= 1

        def observed_add(text, added_by):
            with state:
                entered.append(text)
            entries.wait()  # concurrent request entry, even for clean Store.add
            return add(text, added_by)

        monkeypatch.setattr(store, "_load", observed_load)
        monkeypatch.setattr(store, "_save", observed_save)
        monkeypatch.setattr(store, "add", observed_add)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        url = f"http://127.0.0.1:{server.port}/api/items"

        def post(text):
            req = urllib.request.Request(url, data=json.dumps({"text": text, "added_by": "x"}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with opener.open(req, timeout=WAIT * 2) as response:
                return response.status, json.loads(response.read())

        outcomes = _pair(post)
        errors = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
        if errors:
            raise ExceptionGroup("concurrent POST outcomes", errors)
        assert [code for code, _ in outcomes] == [201, 201]  # before checking any final item count
        assert sorted(entered) == ["a", "b"] and not entries.broken
        assert len(set(reads)) == 2
        assert lock.attempts == lock.entries == len(publications) == 2
        assert peak == 1 and active == 0 and lock.owner is None and not lock.lock.locked()
        if variant == "race_add":
            assert not stale_reads.broken
            assert len({identity for identity, _ in snapshots}) == 2
            assert [d for _, d in snapshots] == [{"next_id": 1, "items": []}] * 2
            assert waits == [0.4, 0.4]
            assert [len(d["items"]) for d in publications] == [1, 1]
            assert [body["item"]["id"] for _, body in outcomes] == [1, 1]
        else:
            assert waits == []
            assert [len(d["items"]) for _, d in snapshots] == [0, 1]
            assert [len(d["items"]) for d in publications] == [1, 2]
            assert sorted(body["item"]["id"] for _, body in outcomes) == [1, 2]

        monkeypatch.setattr(store, "_load", load)  # GET is not a third add/snapshot barrier
        with opener.open(url, timeout=WAIT) as response:
            assert response.status == 200
            items = json.loads(response.read())["items"]
        disk = json.loads((data / "items.json").read_text())
        assert disk == {"next_id": want + 1, "items": items}
        assert len(items) == want
        assert {item["text"] for item in items} <= {"a", "b"}
        assert not (data / "items.tmp").exists()
        assert sum(hit == "POST /api/items 201" for hit in server.hits) == 2
    finally:
        server.shutdown()


def test_frozen_old_add_has_a_forced_shared_tmp_collision(tmp_path, monkeypatch):
    """Controlled counterexample; does NOT claim this was #179's syscall ordering."""
    source = textwrap.dedent(inspect.getsource(p3.RaceStore.add))
    assert source.count(SAVE_SECTION) == 1, "only the final save section may change"
    old_source = source.replace(SAVE_SECTION, "    self._save(d)\n")
    assert hashlib.sha256(old_source.encode()).hexdigest() == OLD_ADD_SHA256
    waits = []

    def wait_only(delay):
        assert delay == 0.4
        waits.append(delay)

    namespace = {"time": SimpleNamespace(sleep=wait_only)}
    exec(compile(old_source, "<frozen-pre-save-lock-RaceStore.add>", "exec"), namespace)
    old_add = namespace["add"]
    store = p3.RaceStore(tmp_path / "items.json")
    load, save, replace = store._load, store._save, p3.fs.os.replace
    snapshots = threading.Barrier(2, timeout=WAIT)
    writes_closed = threading.Barrier(2, timeout=WAIT)
    consumed = threading.Event()
    writer = threading.local()
    reads, publications = [], []
    state = threading.Lock()

    def stale_load():
        assert not store.lock.locked()
        d = load()
        with state:
            reads.append(json.loads(json.dumps(d)))
        snapshots.wait()
        return d

    def unlocked_save(d):
        assert not store.lock.locked()
        writer.text = d["items"][-1]["text"]
        with state:
            publications.append(writer.text)
        save(d)

    def forced_replace(src, dst):
        if (Path(src), Path(dst)) != (tmp_path / "items.tmp", store.path):
            return replace(src, dst)
        writes_closed.wait()  # both actual write_text calls closed before either replacement
        if writer.text == "a":
            replace(src, dst)
            consumed.set()
            return None
        assert consumed.wait(WAIT)
        return replace(src, dst)  # the common pathname was consumed by a: real FileNotFoundError

    monkeypatch.setattr(store, "_load", stale_load)
    monkeypatch.setattr(store, "_save", unlocked_save)
    monkeypatch.setattr(p3.fs.os, "replace", forced_replace)
    outcomes = _pair(lambda text: old_add(store, text, "x"))
    assert outcomes[0] == {"id": 1, "text": "a", "added_by": "x", "done": False}
    error = outcomes[1]
    assert isinstance(error, FileNotFoundError)
    assert error.filename == str(tmp_path / "items.tmp") and error.filename2 == str(store.path)
    assert reads == [{"next_id": 1, "items": []}] * 2
    assert sorted(publications) == ["a", "b"] and waits == [0.4, 0.4]
    assert not snapshots.broken and not writes_closed.broken and consumed.is_set()
