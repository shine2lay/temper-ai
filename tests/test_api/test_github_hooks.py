"""POST /api/hooks/github: the GitHub app's events, and what each one starts.

Pinned: nothing unsigned or tampered gets past the handler; a redelivery
starts nothing twice; one that came before the secret was set is kept and
handled once it is, if genuine; only the allowed authors start work (never
the app, never anyone else); the shipped rules start github_work for a
label, an @mention and a reply, and nothing for a new pull request while the
automatic review is off; and one issue or pull request has one run at a time.
"""

import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from temper_ai.api import hooks
from temper_ai.api.auth import TokenAuthMiddleware
from temper_ai.integrations.github import app as github_app
from temper_ai.integrations.github import secret
from temper_ai.integrations.inbox import service as inbox
from temper_ai.integrations.inbox import store as inbox_store

SECRET = "whsec-github-test"  # noqa: S105
ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs"
REPO = "shine2lay/temper-ai"


def repository(name=REPO):
    return {"full_name": name, "private": False, "default_branch": "master"}


def labeled(sender="shine2lay", number=12, label="temper"):
    return "issues", {
        "action": "labeled",
        "issue": {"number": number, "title": "Fix the typo", "body": "In the README", "state": "open",
                  "user": {"login": "shine2lay"}, "labels": [{"name": label}]},
        "label": {"name": label},
        "repository": repository(),
        "sender": {"login": sender, "type": "User"},
    }


def commented(body="@temper-ai-bot what does this do?", sender="shine2lay", number=12, labels=(),
              on_pull=False, comment_id=555):
    issue = {"number": number, "title": "A thing", "body": "", "state": "open", "user": {"login": "shine2lay"},
             "labels": [{"name": n} for n in labels]}
    if on_pull:
        issue["pull_request"] = {"url": f"https://api.github.com/repos/{REPO}/pulls/{number}"}
    return "issue_comment", {
        "action": "created",
        "issue": issue,
        "comment": {"id": comment_id, "body": body, "user": {"login": sender}},
        "repository": repository(),
        "sender": {"login": sender, "type": "Bot" if sender.endswith("[bot]") else "User"},
    }


def pull_opened(repo=REPO, sender="shine2lay"):
    return "pull_request", {
        "action": "opened",
        "number": 3,
        "pull_request": {"number": 3, "title": "Add a page", "body": "", "draft": False, "state": "open",
                         "user": {"login": sender}, "head": {"ref": "add-page", "repo": {"full_name": repo}},
                         "base": {"ref": "master"}, "labels": []},
        "repository": repository(repo),
        "sender": {"login": sender, "type": "User"},
    }


def _post(client, event, *, key=SECRET, delivery="g-1", raw=None, signature=None):
    event_name, payload = event
    body = raw if raw is not None else json.dumps(payload).encode()
    headers = {"X-GitHub-Event": event_name, "X-GitHub-Delivery": delivery, "Content-Type": "application/json"}
    if signature is None:
        signature = "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    if signature:
        headers["X-Hub-Signature-256"] = signature
    return client.post(hooks.github.PATH, content=body, headers=headers)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    hooks.reset_state()
    secret.forget()
    github_app.set_app(None)
    monkeypatch.setenv(secret.WEBHOOK_SECRET_ENV, SECRET)
    monkeypatch.delenv("TEMPER_API_TOKEN", raising=False)
    yield
    hooks.reset_state()
    secret.forget()
    github_app.set_app(None)


@pytest.fixture
def dispatched(monkeypatch):
    seen = []

    def fake(event_name, payload, record, config_dir=None):
        seen.append((event_name, payload))
        record["outcome"] = "handled"
        return record

    monkeypatch.setattr(hooks, "github_dispatch", fake)
    return seen


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(hooks.router)
    app.add_middleware(TokenAuthMiddleware)
    return TestClient(app)


class TestTheDoor:
    def test_a_genuine_delivery_is_kept_and_handed_on(self, client, dispatched):
        response = _post(client, labeled())
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["ok"], body["delivery"]) == (True, "g-1")
        assert [(name, p["issue"]["number"]) for name, p in dispatched] == [("issues", 12)]
        row = inbox_store.get(body["event"])
        assert (row.source, row.kind, row.subject, row.status) == \
            ("github", "issues.labeled", f"{REPO}#12", "done")

    def test_no_signature_is_refused(self, client, dispatched):
        assert _post(client, labeled(), signature="").status_code == 401
        assert dispatched == []

    def test_a_wrong_signature_is_refused(self, client, dispatched):
        assert _post(client, labeled(), key="guess").status_code == 401
        assert _post(client, labeled(), signature="sha1=abc").status_code == 401
        assert dispatched == []
        assert inbox_store.listing(source="github") == []

    def test_a_body_changed_after_signing_is_refused(self, client, dispatched):
        _, payload = labeled()
        signed = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
        tampered = json.dumps({**payload, "sender": {"login": "shine2lay", "type": "User"},
                               "label": {"name": "other"}}).encode()
        response = _post(client, labeled(), raw=tampered, signature=signature)
        assert response.status_code == 401
        assert dispatched == []

    def test_a_redelivery_starts_nothing_twice(self, client, dispatched):
        assert _post(client, labeled(), delivery="same").status_code == 200
        again = _post(client, labeled(), delivery="same")
        assert again.status_code == 200 and again.json()["duplicate"] is True
        assert len(dispatched) == 1

    def test_not_json(self, client, dispatched):
        assert _post(client, labeled(), raw=b"not json").status_code == 400
        assert dispatched == []

    def test_before_the_secret_is_set_a_delivery_is_kept_not_handled(self, client, dispatched, monkeypatch):
        monkeypatch.delenv(secret.WEBHOOK_SECRET_ENV, raising=False)
        secret.forget()
        kept = _post(client, labeled(), delivery="early")
        assert kept.status_code == 202 and kept.json()["held"] is True
        assert _post(client, labeled(), key="guess", delivery="forged").status_code == 202
        assert dispatched == []

        sweeper = inbox.Sweeper(run=inbox.process)
        assert sweeper.sweep_once()["checked"] == 0  # still no secret: they wait
        monkeypatch.setenv(secret.WEBHOOK_SECRET_ENV, SECRET)
        got = sweeper.sweep_once()
        assert (got["checked"], got["dropped"]) == (1, 1)
        assert [name for name, _ in dispatched] == ["issues"]  # the event name was kept with it
        assert inbox_store.find("github", "early").status == "done"
        assert inbox_store.find("github", "forged") is None

    def test_the_hook_is_public_its_history_is_not(self, client, dispatched, monkeypatch):
        monkeypatch.setenv("TEMPER_API_TOKEN", "api-token")
        assert _post(client, labeled()).status_code == 200
        assert client.get(hooks.github.PATH + "/recent").status_code == 401
        recent = client.get(hooks.github.PATH + "/recent", headers={"Authorization": "Bearer api-token"})
        assert recent.status_code == 200
        [delivery] = recent.json()["deliveries"]
        assert (delivery["delivery"], delivery["kind"], delivery["thread"], delivery["sender"]) == \
            ("g-1", "issues.labeled", f"{REPO}#12", "shine2lay")


@pytest.fixture
def started(monkeypatch):
    from temper_ai.api import routes

    runs = []

    def fake_start_run(body):
        runs.append((body.workflow, body.inputs))
        return routes.RunResponse(execution_id=f"exec-{len(runs)}-0000", status="running")

    monkeypatch.setattr(routes, "start_run", fake_start_run)
    monkeypatch.setattr(hooks, "_run_still_going", lambda eid: None)
    return runs


def dispatch(event, config_dir=CONFIGS):
    event_name, payload = event
    return hooks.github_dispatch(event_name, payload, {"delivery": "d", "runs": []}, config_dir=config_dir)


class FakePulls:
    """The app, as far as the dispatcher asks it: a pull request's branches."""

    def __init__(self):
        self.asked = []

    def request(self, method, repo, path, **kwargs):
        self.asked.append((method, repo, path))
        return httpx.Response(200, json={"number": 7, "draft": False,
                                         "head": {"ref": "temper-issue-5", "repo": {"full_name": repo}},
                                         "base": {"ref": "master"}})


class TestWhatStartsWork:
    def test_the_temper_label_starts_github_work(self, started):
        record = dispatch(labeled())
        assert started == [("github_work", {
            "repo": REPO, "number": "12", "kind": "issue", "why": "label", "default_branch": "master",
            "private": "false", "head_ref": "", "head_repo": "", "base_ref": ""})]
        assert record["outcome"].startswith("started github_work exec-1-0")
        assert record["runs"][0]["thread"] == f"{REPO}#12"

    def test_someone_else_starts_nothing(self, started):
        record = dispatch(labeled(sender="stranger"))
        assert started == []
        assert record["outcome"].startswith("skipped: stranger may not start temper")

    def test_the_app_s_own_comment_starts_nothing(self, started):
        record = dispatch(commented("@temper-ai-bot I opened a PR", sender="temper-ai-bot[bot]", labels=("temper",)))
        assert started == []
        assert record["outcome"] == "skipped: the app's own doing (temper-ai-bot[bot])"

    def test_an_at_mention_on_an_issue_starts_github_work(self, started):
        dispatch(commented())
        [(workflow, inputs)] = started
        assert workflow == "github_work"
        assert (inputs["kind"], inputs["number"], inputs["comment_id"], inputs["why"]) == \
            ("issue", "12", "555", "mention")

    def test_an_at_mention_on_a_pull_request_names_its_branches(self, started):
        pulls = FakePulls()
        github_app.set_app(pulls)
        dispatch(commented("@temper-ai-bot review this", number=7, on_pull=True))
        [(workflow, inputs)] = started
        assert workflow == "github_work"
        assert (inputs["kind"], inputs["head_ref"], inputs["head_repo"], inputs["base_ref"]) == \
            ("pull", "temper-issue-5", REPO, "master")
        assert pulls.asked == [("GET", REPO, "/pulls/7")]

    def test_a_reply_on_a_labelled_issue_carries_the_work_on(self, started):
        dispatch(commented("Use the second option", labels=("temper",)))
        assert [(w, i["why"]) for w, i in started] == [("github_work", "reply")]

    def test_a_reply_that_also_calls_on_the_app_starts_one_run(self, started):
        record = dispatch(commented("@temper-ai-bot use the second option", labels=("temper",)))
        assert len(started) == 1
        assert record["outcome"].startswith("started github_work")

    def test_a_plain_comment_elsewhere_starts_nothing(self, started):
        assert dispatch(commented("nice"))["outcome"] == "no trigger matched"
        assert started == []

    def test_a_new_pull_request_starts_nothing_while_the_review_is_off(self, started):
        assert dispatch(pull_opened())["outcome"] == "no trigger matched"
        assert started == []

    def test_other_events_start_nothing(self, started):
        record = hooks.github_dispatch("ping", {"zen": "hi", "sender": {"login": "shine2lay"}},
                                       {"delivery": "d", "runs": []}, config_dir=CONFIGS)
        assert record["outcome"] == "skipped: ping event starts nothing"


REVIEW_ON = """
trigger:
  name: github_pr_review
  source: github
  enabled: true
  on:
    event: pull_request
    action: [opened, ready_for_review]
    draft: false
    repos: [shine2lay/temper-ai]
  workflow: github_review
  inputs:
    repo: "{{ github.repo }}"
    number: "{{ github.number }}"
"""


class TestTurningTheReviewOn:
    @pytest.fixture
    def turned_on(self, tmp_path):
        (tmp_path / "triggers").mkdir()
        (tmp_path / "triggers" / "github_pr_review.yaml").write_text(REVIEW_ON)
        (tmp_path / "github").mkdir()
        (tmp_path / "github" / "github.yaml").write_text((CONFIGS / "github" / "github.yaml").read_text())
        return tmp_path

    def test_a_new_pull_request_in_a_chosen_repo_is_reviewed(self, started, turned_on):
        dispatch(pull_opened(), config_dir=turned_on)
        assert started == [("github_review", {"repo": REPO, "number": "3"})]

    def test_not_in_another_repo(self, started, turned_on):
        assert dispatch(pull_opened(repo="shine2lay/roamee"), config_dir=turned_on)["outcome"] == \
            "no trigger matched"
        assert started == []

    def test_not_someone_else_s_pull_request(self, started, turned_on):
        dispatch(pull_opened(sender="stranger"), config_dir=turned_on)
        assert started == []


class TestOneRunPerThread:
    def test_a_second_event_while_the_run_is_going_is_skipped(self, started, monkeypatch):
        going = {"exec-1-0000"}
        monkeypatch.setattr(hooks, "_run_still_going", lambda eid: eid if eid in going else None)
        dispatch(labeled())
        record = dispatch(commented("and this too", labels=("temper",), comment_id=556))
        assert len(started) == 1
        assert record["outcome"] == f"skipped github_reply: run exec-1-0 for {REPO}#12 is still going"

        going.clear()  # the first run finished
        dispatch(commented("now?", labels=("temper",), comment_id=557))
        assert len(started) == 2

    def test_another_issue_is_not_held_up(self, started, monkeypatch):
        monkeypatch.setattr(hooks, "_run_still_going", lambda eid: eid)
        dispatch(labeled(number=12))
        dispatch(labeled(number=13))
        assert [i["number"] for _, i in started] == ["12", "13"]

    def test_after_a_restart_the_inbox_remembers_the_thread_s_run(self, client, started, monkeypatch):
        going = {"exec-1-0000"}
        monkeypatch.setattr(hooks, "_run_still_going", lambda eid: eid if eid in going else None)
        assert _post(client, labeled(), delivery="c-1").status_code == 200
        hooks.reset_state()  # a restart: the memory of which run works which thread is gone
        assert _post(client, commented("more", labels=("temper",)), delivery="c-2").status_code == 200
        assert len(started) == 1
        assert inbox_store.find("github", "c-2").outcome.startswith("skipped github_reply")


class TestTheInbox:
    def test_a_workflow_that_failed_to_start_is_tried_again(self, client, monkeypatch):
        from temper_ai.api import routes

        runs = []
        broken = {"github_work"}

        def fake_start(body):
            if body.workflow in broken:
                raise HTTPException(status_code=400, detail=f"workflow config '{body.workflow}' not found")
            runs.append(body.workflow)
            return routes.RunResponse(execution_id=f"exec-{len(runs)}-0000", status="running")

        monkeypatch.setattr(routes, "_start_run", fake_start)
        monkeypatch.setattr(hooks, "_run_still_going", lambda eid: None)
        body = _post(client, labeled(), delivery="d-9").json()
        row = inbox_store.get(body["event"])
        assert row.status == "failed" and "workflow config 'github_work' not found" in row.error
        assert runs == []

        broken.clear()
        assert inbox.process(row.id, now=row.next_try_at) == "done"
        assert runs == ["github_work"]
        assert inbox_store.get(row.id).outcome.startswith("started github_work exec-1-0")
