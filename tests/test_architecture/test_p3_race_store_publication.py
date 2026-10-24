"""P3 fixture store: two concurrent HTTP adds both publish, one save at a time, under the store's own lock.

#124's SIM-5 RaceStore (variant race_add) and its frozen pre-lock counterexample were removed in #125:
SIM-5 is not one of QA #32's rows, so the fixture server keeps only the common first_app_shared.Store.
Real Store._save, both handlers entered before either publication. No browser/model/service.
"""

import importlib.util
import json
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

BIN = Path(__file__).resolve().parents[2] / "configs/architecture/bin"
if "first_app_p3" not in sys.modules:
    spec = importlib.util.spec_from_file_location("first_app_p3", BIN / "first_app_p3.py")
    p3 = importlib.util.module_from_spec(spec)
    sys.modules["first_app_p3"] = p3
    spec.loader.exec_module(p3)
p3 = sys.modules["first_app_p3"]

WAIT = 5


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


def test_no_race_store_is_left():
    assert not hasattr(p3, "RaceStore")
    assert "race_add" not in (p3.FIXTURE / "app.js").read_text(encoding="utf-8")


def test_two_http_201s_with_serial_saves(tmp_path, monkeypatch):
    site = p3.materialize("clean", tmp_path / "fixture")
    data = tmp_path / "data"
    data.mkdir()
    server = p3.P3Server(site, data, "clean", bind_address="127.0.0.1")
    server.start()
    try:
        assert server.srv.server_address[0] == "127.0.0.1"
        store = server.srv.store
        lock = PublicationLock(store.lock)
        monkeypatch.setattr(store, "lock", lock)
        load, save, add = store._load, store._save, store.add
        entries = threading.Barrier(2, timeout=WAIT)
        entered, reads, snapshots, publications, waits = [], [], [], [], []
        state = threading.Lock()
        active = peak = 0

        def wait_only(delay):
            waits.append(delay)

        monkeypatch.setattr(p3, "time", SimpleNamespace(sleep=wait_only))

        def observed_load():
            assert lock.owned_here(), "read moved outside the store lock"
            d = load()
            with state:
                reads.append(threading.get_ident())
                snapshots.append((id(d), json.loads(json.dumps(d))))
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
            entries.wait()  # concurrent request entry
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
        assert waits == []
        assert [len(d["items"]) for _, d in snapshots] == [0, 1]
        assert [len(d["items"]) for d in publications] == [1, 2]
        assert sorted(body["item"]["id"] for _, body in outcomes) == [1, 2]

        monkeypatch.setattr(store, "_load", load)  # GET is not a third add/snapshot
        with opener.open(url, timeout=WAIT) as response:
            assert response.status == 200
            items = json.loads(response.read())["items"]
        disk = json.loads((data / "items.json").read_text())
        assert disk == {"next_id": 3, "items": items}
        assert len(items) == 2
        assert {item["text"] for item in items} == {"a", "b"}
        assert not (data / "items.tmp").exists()
        assert sum(hit == "POST /api/items 201" for hit in server.hits) == 2
    finally:
        server.shutdown()
