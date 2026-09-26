"""The driver says so when a start, a resume or a merge cannot go on, before it changes anything.

- gap 5 (b023, 2026-09-22): GitHub refused to squash a PR that conflicted with master, and the
  deploy went on as if it had merged it.
- gap 17 (b009, 2026-09-24): nothing asked the token pool before a start; every opus slot was
  rate limited, and the plan died on "token pool exhausted".
- gap 19 (b061, 2026-09-25): the preflight met one 502 during b044's prod deploy, after pick_bet
  had already taken the bet's line off the Queue.
"""

import io
import json
import urllib.error

import pytest

from tests.test_epd import test_epd_loop
from tests.test_epd.test_epd_loop import propose

# The driver, loaded with its state in a temporary directory: test_epd_loop's fixture, by name.
L = test_epd_loop.L


class _Answer:
    """What urlopen hands back: a context manager with a status and a body."""

    def __init__(self, status=200, body=b"{}"):
        self.status, self._body = status, body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *args):
        return self._body


def _http_error(url, code):
    return urllib.error.HTTPError(url, code, "Bad Gateway", {}, io.BytesIO(b"<html>bad gateway</html>"))


# ------------------------------------------------------------------ the preflight waits out a restart --


def test_the_preflight_waits_out_a_restart(L, monkeypatch):
    answers = [502, 503, 200]
    slept: list[float] = []
    monkeypatch.setattr(L.time, "sleep", slept.append)

    def urlopen(req, timeout=30):
        code = answers.pop(0)
        if code >= 400:
            raise _http_error(req.full_url, code)
        return _Answer(code)

    monkeypatch.setattr(L.urllib.request, "urlopen", urlopen)
    L.preflight_login("https://rollcall.example", emails=("qa@example.com",))
    assert answers == []
    assert slept == [L.PREFLIGHT_RESTART_WAIT] * 2


def test_the_preflight_gives_up_after_about_a_minute(L, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(L.time, "sleep", slept.append)

    def urlopen(req, timeout=30):
        raise _http_error(req.full_url, 502)

    monkeypatch.setattr(L.urllib.request, "urlopen", urlopen)
    with pytest.raises(SystemExit):
        L.preflight_login("https://rollcall.example", emails=("qa@example.com",))
    assert 50 <= sum(slept) <= 90


def test_the_preflight_still_stops_at_a_login_that_fails(L, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(L.time, "sleep", slept.append)

    def urlopen(req, timeout=30):
        raise _http_error(req.full_url, 401)

    monkeypatch.setattr(L.urllib.request, "urlopen", urlopen)
    with pytest.raises(SystemExit):
        L.preflight_login("https://rollcall.example", emails=("qa@example.com",))
    assert slept == []


# ------------------------------------------------------------------ a refused start keeps its place --


def test_a_start_its_checks_refuse_keeps_its_place_in_the_queue(L, monkeypatch):
    propose(L)
    L.approve("b002", None)
    monkeypatch.setattr(L, "require_prod_paper_login", lambda bet_id: L.die("prod answered HTTP 502"))

    with pytest.raises(SystemExit):
        L.cmd_run(keep=False, wait=False, propose=False, retry=False)
    assert L._calls["start"] == []
    assert L.load_state("b002")["status"] != "approved", "pick_bet took it anyway"
    assert L.next_waiting() == "b002"


# ------------------------------------------------------------------ the token pool --

COOLED = {"pools": [{"provider": "anthropic", "name": "anthropic-oauth", "size": 2, "families": {
    "opus": {"size": 2, "available": 0, "soonest_reset": "2026-09-26T05:00:30+00:00",
             "slots": [{"label": "aungshine", "cooling_until": "2026-09-26T05:00:30+00:00"},
                       {"label": "wai2shine", "cooling_until": "2026-09-26T19:00:30+00:00"}]},
    "sonnet": {"size": 2, "available": 2, "soonest_reset": None,
               "slots": [{"label": "aungshine", "cooling_until": None},
                         {"label": "wai2shine", "cooling_until": None}]}}}]}


def _pools(monkeypatch, L, answer):
    asked: list[str] = []

    def urlopen(url, timeout=30):
        asked.append(url)
        if isinstance(answer, int):
            raise _http_error(url, answer)
        return _Answer(body=json.dumps(answer).encode())

    monkeypatch.setattr(L.urllib.request, "urlopen", urlopen)
    return asked


def test_a_start_is_refused_while_every_opus_slot_is_rate_limited(L, monkeypatch):
    asked = _pools(monkeypatch, L, COOLED)
    with pytest.raises(SystemExit):
        L._real_require_models("b002's run")
    assert asked == [f"{L.API}/api/pools"]


def test_the_refusal_names_each_slot_and_when_the_first_is_back(L, monkeypatch, capsys):
    _pools(monkeypatch, L, COOLED)
    with pytest.raises(SystemExit):
        L._real_require_models("b002's run")
    said = capsys.readouterr()
    text = said.out + said.err
    assert "every opus slot of anthropic is rate limited (aungshine until " in text
    assert "; wai2shine until " in text
    assert "so b002's run would stop at its first model call; nothing was started" in text
    assert "The first slot is back at " in text


def test_one_free_opus_slot_is_enough(L, monkeypatch):
    free = json.loads(json.dumps(COOLED))
    opus = free["pools"][0]["families"]["opus"]
    opus["available"], opus["slots"][1]["cooling_until"] = 1, None
    _pools(monkeypatch, L, free)
    L._real_require_models("b002's run")


def test_a_server_that_cannot_say_does_not_hold_a_start_back(L, monkeypatch):
    _pools(monkeypatch, L, 404)
    L._real_require_models("b002's run")


def test_start_bet_asks_the_pool_before_it_changes_anything(L, monkeypatch):
    propose(L)
    L.approve("b002", None)
    assert L.pick_bet() == "b002"
    monkeypatch.setattr(L, "require_models", lambda what: L.die(f"cooled: {what}"))
    monkeypatch.setattr(L, "post_run", lambda *a, **k: pytest.fail("a run was submitted"))

    with pytest.raises(SystemExit):
        L._real_start_bet("b002", keep=False, wait=False)
    assert L.load_state("b002")["status"] == "approved"
    assert L._calls["plan_snapshot"] == []


def test_a_resume_asks_the_pool_before_it_forks(L, monkeypatch):
    propose(L)
    L.approve("b002", None)
    assert L.pick_bet() == "b002"
    st = L.load_state("b002")
    st["status"] = "running"
    st["stages"]["loop"] = {"_run_id": "run-failed-1"}
    L.save_state(st)
    monkeypatch.setattr(L, "get_run", lambda rid: {
        "status": "failed", "error_message": "1 node(s) failed: build/implement",
        "nodes": [{"name": "tasks", "status": "completed"}, {"name": "build", "status": "failed"}]})
    monkeypatch.setattr(L, "require_models", lambda what: L.die(f"cooled: {what}"))
    monkeypatch.setattr(L, "checkpoints", lambda rid: pytest.fail("it went on to fork"))

    with pytest.raises(SystemExit):
        L.cmd_resume(bet="b002")


# ------------------------------------------------------------------ a PR GitHub will not merge --


def test_a_pr_that_conflicts_is_named_and_nothing_is_deployed(L, monkeypatch, capsys):
    bdir = L.BETS_DIR / "b002"
    bdir.mkdir(parents=True)
    merge = next(label for label, decision in L.PR_DECISIONS.items() if decision == "merge")
    (bdir / "pr-decision.json").write_text(json.dumps({"answers": [{"selected": [merge]}]}))
    st = L.load_state("b002")
    st["bet_id"] = "b002"
    st["stages"]["ship"] = {"pr_number": 28, "title": "Say the roll window", "pr": "https://github.com/x/28"}
    calls: list[tuple] = []

    def fake_github(method, path, body=None, allow=()):
        calls.append((method, path))
        if method == "PUT" and path.endswith("/pulls/28/merge"):
            assert 405 in allow, "the refusal must come back to the driver, not kill it unexplained"
            return {"_status": 405, "_error": '{"message":"Pull Request is not mergeable"}'}
        if method == "GET" and path.endswith("/pulls/28"):
            first = not any(m == "PUT" for m, _ in calls)
            return {"state": "open", "merged": False,
                    **({} if first else {"mergeable": False, "mergeable_state": "dirty"})}
        raise AssertionError((method, path))

    monkeypatch.setattr(L, "github", fake_github)
    with pytest.raises(SystemExit):
        L.stage_deploy(st)
    out = capsys.readouterr()
    text = out.out + out.err
    assert "PR #28 conflicts with master, so it was not merged" in text
    assert "GitHub said 405" in text
    assert L.load_state("b002")["status"] != L.AFTER["deploy"]
