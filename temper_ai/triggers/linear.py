"""Linear: is a delivery really Linear's, is it temper's own doing, and which rules match.

Genuine. Linear signs each delivery: ``Linear-Signature`` is the hex
HMAC-SHA256 of the raw body under the webhook's signing secret, and the
body's ``webhookTimestamp`` (milliseconds) is when it was sent. A delivery
counts only if the signature matches, compared in constant time, and it was
sent within the last minute, so a captured request cannot be replayed later.
The raw bytes are what is signed; re-serialising parsed JSON would not match.

Temper's own. Temper writes to Linear as an app (a client-credentials
token, see tools.oauth_client_credentials), so its changes carry the app
user as their actor, and its comments carry it as their author (``userId``;
seen live: the app user is a user, 98b67e5f... "Temper- Roamee"). Asking
Linear who that is (``viewer``) with the same token tells them apart from a
person's. Without that check, a rule on comments would fire on the comment
its own workflow just wrote, forever.

A comment's issue. A Comment delivery names its issue (``issueId``) but not
the issue's labels or team, so ``has_label`` and ``team`` could never hold
for one. ``enrich`` asks Linear for them and puts them at ``data.issue``,
where those keys look when the event itself is not an issue.

Matching. A rule's ``on:`` for Linear takes these keys, all optional,
each a value or a list (any of):

    type:         Issue, Comment, IssueLabel, Project, Cycle, ...  (Linear-Event)
    action:       create, update, remove
    team:         team key, e.g. ENG (the issue's team, or the comment's issue's)
    has_label:    the issue carries one of these labels now (for a comment:
                  the issue it is on)
    label_added:  one of these labels was just put on the issue (on create:
                  it was created with it). Fires once, not on every later edit.
    actor_type:   who did it: user (a person), or Linear's name for an
                  integration or app. ``user`` keeps a bot's comments out.

Label and team names compare case-insensitively. An unknown key is an
error in the rule rather than a filter that silently never applies.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time
from typing import Any

import httpx

from temper_ai.tools.oauth_client_credentials import (
    ClientCredentials,
    ClientCredentialsAuth,
)

logger = logging.getLogger(__name__)

SOURCE = "linear"
SIGNING_SECRET_ENV = "LINEAR_WEBHOOK_SECRET"  # noqa: S105 - a variable name, not a secret
CLIENT_ID_ENV = "LINEAR_CLIENT_ID"
CLIENT_SECRET_ENV = "LINEAR_CLIENT_SECRET"  # noqa: S105 - a variable name, not a secret
SCOPE_ENV = "LINEAR_SCOPE"
# The MCP config (configs/mcp_servers/linear.yaml) must ask for the same
# scope: Linear revokes all of an app's tokens when one is requested with a
# different scope.
DEFAULT_SCOPE = "read,write"
TOKEN_URL = "https://api.linear.app/oauth/token"  # noqa: S105 - a URL, not a secret
GRAPHQL_URL = "https://api.linear.app/graphql"
MAX_AGE_S = 60.0

ON_KEYS = frozenset({"type", "action", "team", "has_label", "label_added", "actor_type"})


def signing_secret() -> str | None:
    return os.environ.get(SIGNING_SECRET_ENV, "").strip() or None


def verify_signature(raw: bytes, signature: str | None, secret: str) -> bool:
    if not signature:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def is_fresh(event: dict[str, Any], now: float | None = None) -> bool:
    """Sent within the last minute (either way, for clock skew)."""
    sent_ms = event.get("webhookTimestamp")
    if not isinstance(sent_ms, (int, float)) or isinstance(sent_ms, bool):
        return False
    now_ms = (time.time() if now is None else now) * 1000
    return abs(now_ms - sent_ms) <= MAX_AGE_S * 1000


# --- temper's own identity ------------------------------------------------------------------


def app_credentials() -> ClientCredentials | None:
    client_id = os.environ.get(CLIENT_ID_ENV, "").strip()
    client_secret = os.environ.get(CLIENT_SECRET_ENV, "").strip()
    if not (client_id and client_secret):
        return None
    scope = os.environ.get(SCOPE_ENV, "").strip() or DEFAULT_SCOPE
    return ClientCredentials(TOKEN_URL, client_id, client_secret, scope)


_self_lock = threading.Lock()
_self_ids: dict[str, str] = {}


def graphql(query: str, variables: dict | None = None, creds: ClientCredentials | None = None) -> dict:
    """One GraphQL call as temper's app; raises on transport, HTTP or GraphQL errors."""
    creds = creds or app_credentials()
    if creds is None:
        raise RuntimeError(f"{CLIENT_ID_ENV} and {CLIENT_SECRET_ENV} are not set")
    with httpx.Client(timeout=15.0, auth=ClientCredentialsAuth(creds)) as client:
        response = client.post(GRAPHQL_URL, json={"query": query, "variables": variables or {}})
    response.raise_for_status()
    body = response.json()
    if body.get("errors"):
        raise RuntimeError(f"Linear GraphQL error: {body['errors']}")
    return body.get("data") or {}


def app_user_id() -> str | None:
    """Linear's id for temper's app user; None when no app is configured. Cached."""
    creds = app_credentials()
    if creds is None:
        return None
    with _self_lock:
        known = _self_ids.get(creds.client_id)
        if known:
            return known
    viewer = graphql("query { viewer { id name } }", creds=creds).get("viewer") or {}
    user_id = str(viewer.get("id") or "")
    if not user_id:
        raise RuntimeError("Linear did not say who the app user is (viewer.id missing)")
    logger.info("Linear app user is %s (%s)", viewer.get("name"), user_id)
    with _self_lock:
        _self_ids[creds.client_id] = user_id
    return user_id


def clear_identity_cache() -> None:
    with _self_lock:
        _self_ids.clear()


def actor_id(event: dict[str, Any]) -> str | None:
    actor = event.get("actor")
    if isinstance(actor, dict) and actor.get("id"):
        return str(actor["id"])
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def actor_type(event: dict[str, Any]) -> str | None:
    actor = event.get("actor")
    if isinstance(actor, dict) and actor.get("type"):
        return str(actor["type"])
    return None


def is_own(event: dict[str, Any], me: str) -> bool:
    """Whether temper's app user made this change: its actor, or the comment's author."""
    if actor_id(event) == me:
        return True
    if str(event.get("type", "")).lower() != "comment":
        return False
    data = _as_dict(event.get("data"))
    user = _as_dict(data.get("user"))
    return me in {str(data.get("userId") or ""), str(user.get("id") or "")}


_ISSUE_QUERY = """
query($id: String!) {
  issue(id: $id) { id identifier title url labels { nodes { id name } } team { key } }
}
"""


def needs_issue(event: dict[str, Any]) -> bool:
    """A Comment delivery whose issue's labels and team are not in it."""
    if str(event.get("type", "")).lower() != "comment":
        return False
    data = _as_dict(event.get("data"))
    issue = _as_dict(data.get("issue"))
    return bool(data.get("issueId") or issue.get("id")) and not isinstance(issue.get("labels"), list)


def enrich(event: dict[str, Any], creds: ClientCredentials | None = None) -> dict[str, Any]:
    """Put a comment's issue (identifier, labels, team) at ``data.issue``. Raises if Linear can't say."""
    if not needs_issue(event):
        return event
    data = event["data"]
    known = data.get("issue") if isinstance(data.get("issue"), dict) else {}
    issue_id = str(data.get("issueId") or known.get("id"))
    found = graphql(_ISSUE_QUERY, {"id": issue_id}, creds=creds).get("issue")
    if not isinstance(found, dict):
        raise RuntimeError(f"Linear has no issue {issue_id}")
    labels = (found.get("labels") or {}).get("nodes") or []
    data["issue"] = {**known, **{k: v for k, v in found.items() if k != "labels"}, "labels": labels}
    return event


# --- matching ---------------------------------------------------------------------------------


def check_on(on: dict[str, Any]) -> None:
    unknown = sorted(str(k) for k in on if k not in ON_KEYS)
    if unknown:
        raise ValueError(
            f"unknown key(s) under 'on': {', '.join(unknown)} (Linear takes {', '.join(sorted(ON_KEYS))})"
        )


def _wanted(value: Any) -> set[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return {str(v).strip().lower() for v in values if str(v).strip()}


def _labels(data: dict[str, Any]) -> list[dict[str, Any]]:
    labels = data.get("labels")
    if not isinstance(labels, list) and isinstance(data.get("issue"), dict):
        labels = data["issue"].get("labels")  # a comment: its issue's labels (see enrich)
    return [label for label in labels if isinstance(label, dict)] if isinstance(labels, list) else []


def label_names(data: dict[str, Any]) -> set[str]:
    return {str(label.get("name", "")).strip().lower() for label in _labels(data)}


def added_label_names(event: dict[str, Any]) -> set[str]:
    """Labels this event put on the issue: all of them on create, the new ones on update."""
    data = event.get("data") or {}
    action = event.get("action")
    if action == "create":
        return label_names(data)
    if action != "update":
        return set()
    before = (event.get("updatedFrom") or {}).get("labelIds")
    if not isinstance(before, list):
        return set()  # this update did not touch the labels
    previous = {str(i) for i in before}
    return {
        str(label.get("name", "")).strip().lower()
        for label in _labels(data)
        if str(label.get("id")) not in previous
    }


def _team_key(data: dict[str, Any]) -> str | None:
    for holder in (data, data.get("issue") if isinstance(data.get("issue"), dict) else None):
        if not holder:
            continue
        team = holder.get("team")
        if isinstance(team, dict) and team.get("key"):
            return str(team["key"]).strip().lower()
    return None


def matches(on: dict[str, Any], event: dict[str, Any]) -> bool:
    """Whether one rule's ``on:`` accepts this event. Every key given must hold."""
    check_on(on)
    raw_data = event.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    if "type" in on and str(event.get("type", "")).lower() not in _wanted(on["type"]):
        return False
    if "action" in on and str(event.get("action", "")).lower() not in _wanted(on["action"]):
        return False
    if "team" in on and (_team_key(data) or "") not in _wanted(on["team"]):
        return False
    if "has_label" in on and not (label_names(data) & _wanted(on["has_label"])):
        return False
    if "actor_type" in on and (actor_type(event) or "").lower() not in _wanted(on["actor_type"]):
        return False
    return not ("label_added" in on and not (added_label_names(event) & _wanted(on["label_added"])))
