"""Linear deliveries: genuine or not, and which rules they match.

Signature and freshness are the whole of the webhook's authentication (the
path is public), so both are pinned against the exact bytes. Matching is
pinned on label_added in particular: it has to fire once when the label is
put on, not again on every later edit of an issue that carries it.
"""

import hashlib
import hmac
import json
import time

import pytest

from temper_ai.triggers import linear

SECRET = "whsec-test"  # noqa: S105


def _sign(raw: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class TestSignature:
    def test_the_signature_of_the_exact_bytes(self):
        raw = b'{"type":"Issue","action":"create"}'
        assert linear.verify_signature(raw, _sign(raw), SECRET)

    def test_re_serialised_json_does_not_match(self):
        raw = b'{"type": "Issue", "action": "create"}'
        reserialised = json.dumps(json.loads(raw), separators=(",", ":")).encode()
        assert not linear.verify_signature(raw, _sign(reserialised), SECRET)

    def test_wrong_secret_missing_or_tampered(self):
        raw = b'{"a":1}'
        assert not linear.verify_signature(raw, _sign(raw, "other"), SECRET)
        assert not linear.verify_signature(raw, None, SECRET)
        assert not linear.verify_signature(raw, "", SECRET)
        assert not linear.verify_signature(b'{"a":2}', _sign(raw), SECRET)

    def test_case_and_whitespace_of_the_header_do_not_matter(self):
        raw = b"{}"
        assert linear.verify_signature(raw, f"  {_sign(raw).upper()} ", SECRET)


class TestFreshness:
    def test_within_a_minute_either_way(self):
        now = 1_800_000_000.0
        assert linear.is_fresh({"webhookTimestamp": now * 1000 - 59_000}, now=now)
        assert linear.is_fresh({"webhookTimestamp": now * 1000 + 30_000}, now=now)

    def test_older_than_a_minute_or_missing(self):
        now = 1_800_000_000.0
        assert not linear.is_fresh({"webhookTimestamp": now * 1000 - 61_000}, now=now)
        assert not linear.is_fresh({}, now=now)
        assert not linear.is_fresh({"webhookTimestamp": "soon"}, now=now)
        assert not linear.is_fresh({"webhookTimestamp": True}, now=now)

    def test_uses_the_clock_by_default(self):
        assert linear.is_fresh({"webhookTimestamp": time.time() * 1000})


def _issue(action="create", labels=("temper",), before=None, team="ENG"):
    label_objs = [{"id": f"id-{n}", "name": n} for n in labels]
    event = {
        "type": "Issue",
        "action": action,
        "data": {"id": "iss-1", "labels": label_objs, "team": {"key": team}},
    }
    if before is not None:
        event["updatedFrom"] = {"labelIds": [f"id-{n}" for n in before]}
    return event


class TestMatch:
    def test_type_and_action_any_of(self):
        event = _issue()
        assert linear.matches({"type": "Issue"}, event)
        assert linear.matches({"type": ["Comment", "issue"], "action": ["create"]}, event)
        assert not linear.matches({"type": "Comment"}, event)
        assert not linear.matches({"action": "update"}, event)

    def test_team_on_an_issue_and_on_a_comment(self):
        assert linear.matches({"team": "eng"}, _issue())
        assert not linear.matches({"team": "OPS"}, _issue())
        comment = {"type": "Comment", "action": "create",
                   "data": {"body": "hi", "issue": {"id": "iss-1", "team": {"key": "ENG"}}}}
        assert linear.matches({"type": "Comment", "team": "ENG"}, comment)

    def test_has_label_holds_on_every_edit(self):
        event = _issue(action="update", labels=("temper", "bug"), before=("temper",))
        assert linear.matches({"has_label": "Temper"}, event)
        assert not linear.matches({"has_label": "urgent"}, event)

    def test_label_added_on_create_with_the_label(self):
        assert linear.matches({"label_added": "temper"}, _issue(action="create"))

    def test_label_added_when_it_is_put_on(self):
        event = _issue(action="update", labels=("bug", "temper"), before=("bug",))
        assert linear.matches({"label_added": "temper"}, event)

    def test_label_added_does_not_fire_again_on_later_edits(self):
        # The label was already there; the update changed the labels (bug added).
        event = _issue(action="update", labels=("temper", "bug"), before=("temper",))
        assert not linear.matches({"label_added": "temper"}, event)
        # An update that did not touch the labels at all (no labelIds in updatedFrom).
        assert not linear.matches({"label_added": "temper"}, _issue(action="update"))

    def test_label_added_never_on_remove(self):
        assert not linear.matches({"label_added": "temper"}, _issue(action="remove"))

    def test_every_key_must_hold(self):
        event = _issue(team="OPS")
        assert not linear.matches({"type": "Issue", "label_added": "temper", "team": "ENG"}, event)

    def test_an_unknown_key_is_an_error_not_a_filter_that_never_applies(self):
        with pytest.raises(ValueError, match="labels"):
            linear.matches({"type": "Issue", "labels": ["temper"]}, _issue())


class TestActor:
    def test_actor_id(self):
        assert linear.actor_id({"actor": {"id": "u1", "name": "Temper"}}) == "u1"
        assert linear.actor_id({"actor": None}) is None
        assert linear.actor_id({}) is None

    def test_no_app_configured_means_no_identity(self, monkeypatch):
        monkeypatch.delenv(linear.CLIENT_ID_ENV, raising=False)
        monkeypatch.delenv(linear.CLIENT_SECRET_ENV, raising=False)
        assert linear.app_credentials() is None
        assert linear.app_user_id() is None

    def test_the_app_user_is_asked_once_and_cached(self, monkeypatch):
        monkeypatch.setenv(linear.CLIENT_ID_ENV, "cid")
        monkeypatch.setenv(linear.CLIENT_SECRET_ENV, "csecret")
        linear.clear_identity_cache()
        calls = []

        def fake_graphql(query, variables=None, creds=None):
            calls.append(query)
            return {"viewer": {"id": "app-user", "name": "Temper"}}

        monkeypatch.setattr(linear, "graphql", fake_graphql)
        try:
            assert linear.app_user_id() == "app-user"
            assert linear.app_user_id() == "app-user"
            assert len(calls) == 1
        finally:
            linear.clear_identity_cache()

    def test_the_default_scope_matches_the_mcp_config(self, monkeypatch):
        # Linear revokes an app's tokens when one is asked for with another
        # scope, so the webhook handler and the MCP connection must agree.
        from pathlib import Path

        import yaml

        monkeypatch.setenv(linear.CLIENT_ID_ENV, "cid")
        monkeypatch.setenv(linear.CLIENT_SECRET_ENV, "csecret")
        monkeypatch.delenv(linear.SCOPE_ENV, raising=False)
        config = yaml.safe_load(
            (Path(__file__).resolve().parents[2] / "configs/mcp_servers/linear.yaml").read_text()
        )["mcp_server"]
        assert config["scope"] == "${LINEAR_SCOPE:" + linear.DEFAULT_SCOPE + "}"
        assert config["token_url"] == linear.TOKEN_URL
        assert linear.app_credentials().scope == linear.DEFAULT_SCOPE
