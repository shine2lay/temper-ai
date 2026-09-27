"""Notion: tools, upsert, webhook signatures, rule matching, self-skip, one run
per page, notices and answers as page comments, config errors.

A small in-memory Notion API (httpx.MockTransport) stands in for the real one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from typing import Any

import httpx
import pytest

from temper_ai.integrations.notion import access, replies, store
from temper_ai.integrations.notion.client import NotionClient, NotionError, normalize_id
from temper_ai.integrations.notion.config import NotionConfigError, parse_config
from temper_ai.integrations.notion.content import build_properties, upsert
from temper_ai.triggers import notion as rules

BOT = "b0000000-0000-0000-0000-000000000001"
PERSON = "p0000000-0000-0000-0000-000000000002"


def _id() -> str:
    return str(uuid.uuid4())


class FakeNotion:
    """Pages, one table (database + data source), comments."""

    def __init__(self) -> None:
        self.root = _id()
        self.db = _id()
        self.ds = _id()
        self.other = _id()
        self.pages: dict[str, dict[str, Any]] = {
            self.root: {"id": self.root, "url": "https://notion.so/root", "parent": {"type": "workspace"},
                        "properties": {"title": {"id": "title", "type": "title",
                                                 "title": [{"plain_text": "Temper QA"}]}}},
            self.other: {"id": self.other, "url": "https://notion.so/other", "parent": {"type": "workspace"},
                         "properties": {"title": {"id": "title", "type": "title",
                                                  "title": [{"plain_text": "Private"}]}}},
        }
        self.schema = {"Company": {"id": "t", "type": "title"}, "Website": {"id": "w", "type": "url"},
                       "Employees": {"id": "e", "type": "number"},
                       "Status": {"id": "s", "type": "status", "status": {"options": [{"name": "Temper"}]}}}
        self.comments: list[dict[str, Any]] = []
        self.blocks: dict[str, list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, str]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def client(self) -> NotionClient:
        return NotionClient("secret-test", http=httpx.Client(transport=self.transport()), sleep=lambda s: None)

    def row(self, company: str, **props: Any) -> str:
        rid = _id()
        p = {"Company": {"id": "t", "type": "title", "title": [{"plain_text": company}]}}
        for k, v in props.items():
            if k == "Status":
                p[k] = {"id": "s", "type": "status", "status": {"name": v}}
        self.pages[rid] = {"id": rid, "url": f"https://notion.so/{rid}",
                           "parent": {"type": "data_source_id", "data_source_id": self.ds, "database_id": self.db},
                           "properties": p}
        return rid

    def rows(self) -> list[dict[str, Any]]:
        return [p for p in self.pages.values() if (p["parent"].get("data_source_id") == self.ds)]

    def _title(self, page: dict[str, Any]) -> str:
        t = page["properties"].get("Company") or page["properties"].get("title") or {}
        return "".join(x.get("plain_text") or x.get("text", {}).get("content", "") for x in t.get("title", []))

    def _store_props(self, page: dict[str, Any], props: dict[str, Any]) -> None:
        for k, v in props.items():
            v = dict(v)
            if "title" in v:
                v["title"] = [{"plain_text": x["text"]["content"]} for x in v["title"]]
            if "rich_text" in v:
                v["rich_text"] = [{"plain_text": x["text"]["content"]} for x in v["rich_text"]]
            page["properties"][k] = {"id": k[:1].lower(), "type": next(iter(v)), **v}

    def handle(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/v1")
        body = json.loads(req.content) if req.content else {}
        self.calls.append((req.method, path))
        m = req.method

        def ok(data: Any) -> httpx.Response:
            return httpx.Response(200, json=data)

        def missing() -> httpx.Response:
            return httpx.Response(404, json={"code": "object_not_found", "message": "not found"})

        if path == "/users/me":
            return ok({"id": BOT, "name": "Temper", "type": "bot", "bot": {"workspace_name": "WS"}})
        if mm := re.fullmatch(r"/users/(.+)", path):
            return ok({"id": mm[1], "name": "Ada"})
        if mm := re.fullmatch(r"/pages/([^/]+)", path):
            page = self.pages.get(normalize_id(mm[1]))
            if page is None:
                return missing()
            if m == "PATCH":
                self._store_props(page, body.get("properties") or {})
            return ok(page)
        if path == "/pages" and m == "POST":
            pid = _id()
            page = {"id": pid, "url": f"https://notion.so/{pid}", "parent": body["parent"], "properties": {}}
            if body["parent"].get("data_source_id"):
                page["parent"]["database_id"] = self.db
            self.pages[pid] = page
            self._store_props(page, body.get("properties") or {})
            return ok(page)
        if mm := re.fullmatch(r"/databases/([^/]+)", path):
            if normalize_id(mm[1]) != self.db:
                return missing()
            return ok({"id": self.db, "data_sources": [{"id": self.ds}],
                       "parent": {"type": "page_id", "page_id": self.root}})
        if mm := re.fullmatch(r"/data_sources/([^/]+)(/query)?", path):
            if normalize_id(mm[1]) != self.ds:
                return missing()
            if mm[2]:
                want = (body.get("filter") or {})
                rows = self.rows()
                if want:
                    val = next(iter(v for k, v in want.items() if isinstance(v, dict) and k != "property"))
                    val = next(iter(val.values()))
                    rows = [r for r in rows if self._title(r) == val]
                return ok({"results": rows, "has_more": False})
            return ok({"id": self.ds, "properties": self.schema, "title": [{"plain_text": "CRM"}],
                       "parent": {"type": "database_id", "database_id": self.db}})
        if mm := re.fullmatch(r"/blocks/([^/]+)/children", path):
            bid = normalize_id(mm[1])
            if m == "PATCH":
                self.blocks.setdefault(bid, []).extend(body["children"])
                return ok({"results": body["children"]})
            return ok({"results": self.blocks.get(bid, []), "has_more": False})
        if mm := re.fullmatch(r"/blocks/([^/]+)", path):
            return missing()
        if path == "/comments" and m == "POST":
            cid = _id()
            disc = body.get("discussion_id") or _id()
            pid = (body.get("parent") or {}).get("page_id") or next(
                (c["page"] for c in self.comments if c["discussion_id"] == disc), "")
            c = {"id": cid, "discussion_id": disc, "page": normalize_id(pid), "created_by": {"id": BOT},
                 "rich_text": [{"plain_text": x["text"]["content"]} for x in body["rich_text"]],
                 "created_time": "2026-09-27T00:00:00.000Z"}
            self.comments.append(c)
            return ok(c)
        if path == "/comments":
            bid = normalize_id(req.url.params.get("block_id", ""))
            return ok({"results": [c for c in self.comments if c["page"] == bid], "has_more": False})
        if mm := re.fullmatch(r"/comments/([^/]+)", path):
            c = next((c for c in self.comments if c["id"] == normalize_id(mm[1])), None)
            return ok(c) if c else missing()
        if path == "/search":
            q = str(body.get("query") or "").lower()
            return ok({"results": [p for p in self.pages.values() if q in self._title(p).lower()],
                       "has_more": False})
        return httpx.Response(400, json={"code": "validation_error", "message": f"fake: {m} {path}"})


@pytest.fixture
def fake() -> FakeNotion:
    return FakeNotion()


@pytest.fixture
def cfg(fake):
    return parse_config({"notion": {"targets": {
        "qa": {"page": fake.root},
        "crm": {"table": fake.db, "key": "Company", "fields": {"company": "Company", "site": "Website"}},
    }}})


# -- config --------------------------------------------------------------------------

@pytest.mark.parametrize("raw, words", [
    ({"notion": {"targets": {"x": {"table": "abc"}}}}, "key"),
    ({"notion": {"targets": {"x": {"page": "a", "table": "b", "key": "k"}}}}, "exactly one"),
    ({"notion": {"targets": {"x": {"page": "a", "bogus": 1}}}}, "unknown"),
    ({"notion": {"nope": 1}}, "unknown"),
    ({"notion": {"zone": "Mars/Base"}}, "time zone"),
    ({"notion": {"answer_from": 3}}, "answer_from"),
])
def test_config_errors(raw, words):
    with pytest.raises(NotionConfigError, match=words):
        parse_config(raw)


def test_config_names_fields(cfg):
    crm = cfg.target("crm")
    assert crm.is_table and crm.prop("site") == "Website" and crm.prop("SITE") == "Website"
    assert crm.prop("Employees") == "Employees"
    assert cfg.answer_from is None


# -- upsert ---------------------------------------------------------------------------

def test_upsert_creates_then_updates_without_duplicates(fake):
    client = fake.client()
    action, row = upsert(client, fake.ds, "Company", {"Company": "Acme", "Website": "https://acme.test",
                                                      "Employees": "120"})
    assert action == "created"
    action2, row2 = upsert(client, fake.ds, "Company", {"Company": "Acme", "Employees": 130})
    assert action2 == "updated" and row2["id"] == row["id"]
    assert len(fake.rows()) == 1
    assert fake.pages[row["id"]]["properties"]["Employees"]["number"] == 130


def test_upsert_refuses_ambiguous_key_and_missing_key(fake):
    client = fake.client()
    fake.row("Twin")
    fake.row("Twin")
    with pytest.raises(Exception, match="2 rows"):
        upsert(client, fake.ds, "Company", {"Company": "Twin"})
    with pytest.raises(Exception, match="required"):
        upsert(client, fake.ds, "Company", {"Website": "https://x.test"})


def test_property_types():
    props = build_properties(
        {"T": {"type": "title"}, "N": {"type": "number"}, "S": {"type": "select"}, "C": {"type": "checkbox"},
         "U": {"type": "url"}, "M": {"type": "multi_select"}},
        {"T": "Acme", "N": "1,200", "S": "SaaS", "C": "yes", "U": "https://a.test", "M": ["a", "b"]})
    assert props["T"]["title"][0]["text"]["content"] == "Acme"
    assert props["N"]["number"] == 1200
    assert props["S"]["select"]["name"] == "SaaS"
    assert props["C"]["checkbox"] is True
    assert [x["name"] for x in props["M"]["multi_select"]] == ["a", "b"]


# -- the client -----------------------------------------------------------------------

def test_client_retries_rate_limits():
    hits = []

    def handler(req):
        hits.append(1)
        if len(hits) < 3:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={"code": "rate_limited"})
        return httpx.Response(200, json={"id": BOT})

    client = NotionClient("t", http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    assert client.me()["id"] == BOT and len(hits) == 3


def test_client_says_what_failed(fake):
    with pytest.raises(NotionError) as err:
        fake.client().page(_id())
    assert err.value.not_found


# -- where temper may write -----------------------------------------------------------

def test_access_targets_rows_and_run_pages(fake, cfg):
    client = fake.client()
    row = fake.row("Acme")
    assert access.why_not(client, cfg, fake.root) == ""
    assert access.why_not(client, cfg, row) == ""          # a row of a target table
    assert access.why_not(client, cfg, fake.other) != ""   # shared, but not a target
    assert access.why_not(client, cfg, fake.other, run_pages=[fake.other]) == ""
    with pytest.raises(access.NotAllowed):
        access.check(client, cfg, fake.other)


# -- tools ----------------------------------------------------------------------------

@pytest.fixture
def tools(fake, cfg, monkeypatch):
    from temper_ai.tools import notion as tmod

    monkeypatch.setattr(tmod._NotionTool, "_client", lambda self: fake.client())
    monkeypatch.setattr(tmod._NotionTool, "_cfg", lambda self: cfg)
    monkeypatch.setattr(tmod._NotionTool, "_run_pages", lambda self: [])
    monkeypatch.setattr(tmod._NotionTool, "_run_id", lambda self: "run-1")
    return tmod


def test_tools_write_upsert_comment_read_search(tools, fake):
    up = tools.NotionUpsert().execute(table="crm", values={"company": "Acme", "site": "https://acme.test"})
    assert up.success, up.error
    assert json.loads(up.result)["action"] == "created"
    again = tools.NotionUpsert().execute(table="crm", values={"company": "Acme", "site": "https://acme2.test"})
    assert json.loads(again.result)["action"] == "updated" and len(fake.rows()) == 1

    wrote = tools.NotionWrite().execute(where="qa", mode="new_page", title="Notes", text="hello from temper")
    assert wrote.success, wrote.error

    said = tools.NotionComment().execute(where="qa", text="hi")
    assert said.success and store.is_ours(json.loads(said.result)["comment_id"])

    read = tools.NotionRead().execute(what="crm")
    assert read.success and "Acme" in read.result

    found = tools.NotionSearch().execute(query="Temper QA")
    assert found.success and "Temper QA" in found.result


def test_tools_take_a_page_title(tools, fake):
    fake.blocks[fake.root] = [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "marigold"}]}}]
    read = tools.NotionRead().execute(what="  temper   qa ")
    assert read.success, read.error
    assert "marigold" in read.result
    said = tools.NotionComment().execute(where="Temper QA", text="by title")
    assert said.success and json.loads(said.result)["page_id"] == fake.root
    # A title that isn't a target is still only readable, not writable.
    assert tools.NotionRead().execute(what="Private").success
    assert not tools.NotionComment().execute(where="Private", text="x").success


def test_page_title_none_or_several(tools, fake):
    missing = tools.NotionRead().execute(what="No Such Page")
    assert not missing.success and "no page or table titled" in missing.error
    near = tools.NotionRead().execute(what="Temper")
    assert not near.success and "close matches" in near.error and fake.root in near.error
    twin = _id()
    fake.pages[twin] = {**fake.pages[fake.root], "id": twin}
    both = tools.NotionRead().execute(what="Temper QA")
    assert not both.success and "2 pages" in both.error and twin in both.error


def test_answer_scope_title_skips_pages_it_may_not_read(tools, fake, cfg, monkeypatch):
    twin = _id()
    fake.pages[twin] = {**fake.pages[fake.other], "id": twin,
                        "properties": fake.pages[fake.root]["properties"]}  # also "Temper QA"
    monkeypatch.setattr(type(cfg), "answer_ids", lambda self: [fake.root])
    read = tools.NotionRead({"scope": "answer"}).execute(what="Temper QA")
    assert read.success, read.error


def test_ids_from_notion_links():
    raw = "3e74cb8f6eaa801b96c5ceefb5206616"
    want = "3e74cb8f-6eaa-801b-96c5-ceefb5206616"
    for link in (f"https://www.notion.so/Temper-QA-{raw}?pvs=4", f"https://x.notion.site/Temper-QA-{raw}",
                 f"https://www.notion.com/p/Temper-QA-{raw}", raw.upper()):
        assert normalize_id(link) == want
    assert normalize_id("Temper QA") == "Temper QA"


def test_tools_refuse_pages_outside_targets(tools, fake):
    assert not tools.NotionComment().execute(where=fake.other, text="x").success
    assert not tools.NotionWrite().execute(where=fake.other, mode="append", text="x").success
    assert not tools.NotionUpsert().execute(table="qa", values={"a": 1}).success
    assert not tools.NotionUpsert().execute(table="nope", values={"a": 1}).success


def test_no_delete_tools():
    from temper_ai.tools import TOOL_CLASSES

    names = [n for n in TOOL_CLASSES if n.startswith("Notion")]
    assert sorted(names) == ["NotionComment", "NotionRead", "NotionSearch", "NotionUpsert", "NotionWrite"]


# -- signatures and matching ---------------------------------------------------------

def test_signature():
    raw = b'{"id": "e1"}'
    good = "sha256=" + hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
    assert rules.verify_signature(raw, good, "s3cret")
    assert not rules.verify_signature(raw, good, "other")
    assert not rules.verify_signature(raw + b" ", good, "s3cret")
    assert not rules.verify_signature(raw, None, "s3cret")


def _row_event(page_id: str, prop_ids=("s",), author=PERSON, author_type="person", typ="page.properties_updated"):
    return {"id": _id(), "type": typ, "entity": {"id": page_id, "type": "page"},
            "authors": [{"id": author, "type": author_type}],
            "data": {"updated_properties": list(prop_ids)}}


def test_rule_matches_status_set_once(fake, cfg):
    client = fake.client()
    row = fake.row("Task", Status="Temper")
    on = {"event": "row", "table": "crm", "property": "Status", "value": "temper"}
    ctx = rules.enrich(_row_event(row), client)
    assert rules.matches(on, ctx, cfg, client)
    other_prop = rules.enrich(_row_event(row, prop_ids=("w",)), client)
    assert not rules.matches(on, other_prop, cfg, client)
    assert not rules.matches({**on, "value": "Done"}, ctx, cfg, client)


def test_rule_unknown_key_is_an_error():
    with pytest.raises(ValueError):
        rules.check_on({"event": "row", "colour": "red"})
    with pytest.raises(ValueError):
        rules.check_on({"event": "nope"})


def test_own_events_are_temper_s():
    assert rules.is_own(_row_event(_id(), author=BOT, author_type="bot"), BOT)
    assert not rules.is_own(_row_event(_id()), BOT)


# -- the service: self-skip, one run per page, answers ------------------------------

@pytest.fixture
def service(fake, cfg, ops, tmp_path):
    from temper_ai.integrations.notion.service import NotionService

    (tmp_path / "triggers").mkdir()
    (tmp_path / "triggers" / "t.yaml").write_text(
        "trigger:\n  name: work\n  source: notion\n  on: {event: row, table: crm, property: Status, value: Temper}\n"
        "  workflow: notion_work\n  inputs:\n    page_id: '{{ page.id }}'\n")

    class Watch:
        def get(self):
            return cfg

    return NotionService(client=fake.client(), config=Watch(), ops=ops, config_dir=tmp_path)


def test_service_starts_once_per_page_and_skips_own(service, fake, ops):
    row = fake.row("Task", Status="Temper")
    out = service.handle(_row_event(row))
    assert out.startswith("started notion_work")
    assert len(ops.started) == 1
    assert service.handle(_row_event(row)).startswith("skipped")
    assert service.handle(_row_event(row, author=BOT, author_type="bot")).startswith("ignored")
    assert len(ops.started) == 1


def test_parse_replies():
    q = [{"id": "a", "question": "Which?", "options": [{"label": "Red"}, {"label": "Blue"}]}]
    assert replies.parse("reject: not now", q)[0] == "reject"
    verdict, answers, _ = replies.parse("blue", q)
    assert verdict == "approve" and answers[0]["selected"] == ["Blue"]
    two = q + [{"id": "b", "question": "Why?"}]
    _, answers, _ = replies.parse("1. Red\n2. because", two)
    assert answers[0]["selected"] == ["Red"] and answers[1]["custom"] == "because"
    assert replies.parse("ok", [])[0:2] == ("approve", [])


def test_notice_and_reply_answer_through_page_comments(service, fake, ops, notify_config):
    from datetime import UTC, datetime

    from temper_ai.integrations.notify import store as notify_store
    from temper_ai.integrations.notify.notice import Notice

    ops.add_run("run-9", "notify_probe", "running", datetime.now(UTC))
    ops.alive.add("run-9")
    ops.add_gate("ev-9", "run-9", "decide", datetime.now(UTC),
                 questions=[{"id": "q1", "question": "Colour?", "options": [{"label": "Red"}]}])
    store.save_run("run-9", fake.root, origin=True)
    page = normalize_id(fake.root)
    notice = Notice(kind="question", execution_id="run-9", workflow="notify_probe", node="decide",
                    event_id="ev-9", questions=[{"id": "q1", "question": "Colour?",
                                                 "options": [{"label": "Red"}]}])
    copy = notify_store.claim("k-run9", "question", "run-9", "notion", page, node="decide", event_id="ev-9")
    ref = service.sender.send(notice, page, copy)
    notify_store.mark(copy.id, "sent", ref=ref)
    posted = fake.comments[-1]
    assert "Colour?" in posted["rich_text"][0]["plain_text"]

    # A person replies in the question's discussion; Notion tells temper.
    reply = {"id": _id(), "discussion_id": posted["discussion_id"], "page": page,
             "created_by": {"id": PERSON}, "rich_text": [{"plain_text": "red"}]}
    fake.comments.append(reply)
    event = {"id": _id(), "type": "comment.created", "entity": {"id": reply["id"], "type": "comment"},
             "authors": [{"id": PERSON, "type": "person"}],
             "data": {"page_id": page, "discussion_id": posted["discussion_id"]}}
    out = service.handle(event)
    assert out.startswith("answered"), out
    assert ops.answers[-1]["answers"][0]["selected"] == ["Red"]
    assert ops.answers[-1]["by"] == "Ada (Notion)"

    # Temper's own comment (the question itself) never answers anything.
    own = {**event, "id": _id(), "entity": {"id": posted["id"], "type": "comment"},
           "authors": [{"id": BOT, "type": "bot"}]}
    assert service.handle(own).startswith("ignored")
