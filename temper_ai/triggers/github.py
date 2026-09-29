"""GitHub as a trigger source: temper's GitHub app sends its events here.

GitHub posts every event of the app's installations to
``POST /api/hooks/github``, signed with the app's webhook secret
(``GITHUB_APP_WEBHOOK_SECRET``): ``X-Hub-Signature-256`` is ``sha256=`` and
the HMAC-SHA256 of the exact body. A delivery without it, or with one that
does not match, is refused. ``X-GitHub-Event`` names the event and
``X-GitHub-Delivery`` is its id (the same on a redelivery, so a delivery is
handled once). Only the events a rule can start work on are kept, and
``ping`` and the installation events, which say the webhook works and where
the app is; the app may be sent more (a check run, a workflow run: several
for each CI run), which are answered and dropped (``kept``).

Who may start work, before any rule is asked: the people in
``configs/github/github.yaml`` (``allowed_authors``, by default only
shine2lay). The app's own doings (its comments, its pull requests) never
start anything, and neither does anyone else: such an event is recorded as
skipped. A rule can narrow this further with ``authors``, never widen it.

A rule's ``on:`` (every key given must hold)::

    event: issues | issue_comment | pull_request   (one or a list)
    action: labeled | created | opened | ...       (one or a list)
    label: temper          the label this event put on the issue or PR
    has_label: temper      a label the issue or PR has
    mention: true          the comment (or the new issue's or PR's text) calls
                           on the app: "@<app> ..." (false: it must not)
    pull_request: true     the thread is a pull request (false: an issue)
    draft: false           the pull request is (not) a draft
    repos: [owner/name, owner/*]   only these repositories
    authors: [login]       only these people (within allowed_authors)

Each event also gets a ``github`` mapping for the rule's input templates:
``{{ github.repo }}``, ``{{ github.number }}``, ``{{ github.kind }}`` (issue or
pull), ``{{ github.comment_id }}`` and the rest of ``thread_of`` below.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any

from temper_ai.integrations.github import secret
from temper_ai.integrations.github.settings import GitHubSettings

SOURCE = "github"
PATH = "/api/hooks/github"
EVENT_HEADER = "x-github-event"
DELIVERY_HEADER = "x-github-delivery"
SIGNATURE_HEADER = "x-hub-signature-256"
SECRET_ENV = secret.WEBHOOK_SECRET_ENV
# The events a rule can start work on.
EVENTS = frozenset({"issues", "issue_comment", "pull_request"})
# Kept though they start nothing: the webhook works, the app was installed (or on more repos).
NOTED = frozenset({"ping", "installation", "installation_repositories"})
ON_KEYS = frozenset({
    "event", "action", "label", "has_label", "mention", "pull_request", "draft", "repos", "authors",
})


def signing_secret() -> str | None:
    return secret.webhook_secret()


def kept(event_name: str) -> bool:
    """Whether a delivery of this event is kept (in the event inbox) or answered and dropped."""
    return event_name in EVENTS or event_name in NOTED


def verify_signature(raw: bytes, signature: str | None, key: str) -> bool:
    """Whether ``signature`` (``sha256=<hex>``) is the HMAC-SHA256 of ``raw`` with ``key``."""
    if not signature or not key:
        return False
    given = signature.strip()
    if not given.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, given)


# -- what an event is about ----------------------------------------------------------------------


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _login(user: Any) -> str:
    return str(_dict(user).get("login") or "")


def _labels(item: dict[str, Any]) -> list[str]:
    labels = item.get("labels")
    if not isinstance(labels, list):
        return []
    return [str(label.get("name") or "").strip() for label in labels if isinstance(label, dict)]


def thread_item(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The issue or pull request an event is about (as the payload has it)."""
    if event_name == "pull_request":
        return _dict(payload.get("pull_request"))
    return _dict(payload.get("issue"))


def is_pull(event_name: str, payload: dict[str, Any]) -> bool:
    if event_name == "pull_request":
        return True
    return bool(_dict(payload.get("issue")).get("pull_request"))


def thread_of(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The facts about one event that rules and workflow inputs use; every value a plain one."""
    repository = _dict(payload.get("repository"))
    item = thread_item(event_name, payload)
    comment = _dict(payload.get("comment")) if event_name == "issue_comment" else {}
    pull = is_pull(event_name, payload)
    head = _dict(item.get("head")) if event_name == "pull_request" else {}
    base = _dict(item.get("base")) if event_name == "pull_request" else {}
    repo = str(repository.get("full_name") or "")
    number = item.get("number")
    return {
        "event": event_name,
        "action": str(payload.get("action") or ""),
        "repo": repo,
        "owner": repo.split("/", 1)[0] if "/" in repo else "",
        "name": repo.split("/", 1)[1] if "/" in repo else "",
        "private": bool(repository.get("private")),
        "default_branch": str(repository.get("default_branch") or ""),
        "number": str(number) if number is not None else "",
        "kind": "pull" if pull else "issue",
        "is_pull": pull,
        "title": str(item.get("title") or ""),
        "url": str(item.get("html_url") or ""),
        "author": _login(item.get("user")),
        "state": str(item.get("state") or ""),
        "labels": _labels(item),
        "label": str(_dict(payload.get("label")).get("name") or ""),
        "sender": _login(payload.get("sender")),
        "sender_type": str(_dict(payload.get("sender")).get("type") or ""),
        "comment_id": str(comment.get("id") or ""),
        "comment_url": str(comment.get("html_url") or ""),
        "draft": bool(item.get("draft")),
        "head_ref": str(head.get("ref") or ""),
        "head_repo": str(_dict(head.get("repo")).get("full_name") or ""),
        "base_ref": str(base.get("ref") or ""),
        "installation": str(_dict(payload.get("installation")).get("id") or ""),
    }


def subject_of(event_name: str, payload: dict[str, Any]) -> str:
    """``owner/name#12`` for an issue or PR event; the repository (or nothing) otherwise."""
    repo = str(_dict(payload.get("repository")).get("full_name") or "")
    number = thread_item(event_name, payload).get("number")
    if repo and number is not None:
        return f"{repo}#{number}"
    return repo


def text_of(event_name: str, payload: dict[str, Any]) -> str:
    """What was written: the comment, or the new issue's or pull request's text."""
    if event_name == "issue_comment":
        return str(_dict(payload.get("comment")).get("body") or "")
    item = thread_item(event_name, payload)
    return "\n".join(str(item.get(k) or "") for k in ("title", "body"))


def mentions(text: str, app: str) -> bool:
    """Whether ``text`` calls on the app: ``@<app>`` (or ``@<app>[bot]``) as a whole word."""
    if not app:
        return False
    pattern = r"(?<![\w@/.-])@" + re.escape(app) + r"(?:\[bot\])?(?![\w-])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def with_context(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The payload plus its ``github`` facts, for matching and for input templates."""
    return {**payload, "github": thread_of(event_name, payload)}


# -- who may start work --------------------------------------------------------------------------


def is_own(payload: dict[str, Any], settings: GitHubSettings) -> bool:
    """Whether the app itself did this (its comment, its pull request, its label)."""
    return _login(payload.get("sender")).lower() == settings.bot_login.lower()


def refusal(event_name: str, payload: dict[str, Any], settings: GitHubSettings) -> str | None:
    """Why this event starts nothing whatever the rules say; None if a rule may start work."""
    if event_name not in EVENTS:
        return f"skipped: {event_name or 'an unnamed'} event starts nothing"
    sender = _login(payload.get("sender"))
    if is_own(payload, settings):
        return f"skipped: the app's own doing ({settings.bot_login})"
    if not settings.allows(sender):
        return (f"skipped: {sender or 'an unknown sender'} may not start temper "
                f"(allowed: {', '.join(settings.allowed_authors) or 'no one'})")
    return None


# -- rules ---------------------------------------------------------------------------------------


def check_on(on: dict[str, Any]) -> None:
    unknown = sorted(str(k) for k in on if k not in ON_KEYS)
    if unknown:
        raise ValueError(
            f"unknown key(s) under 'on': {', '.join(unknown)} (GitHub takes {', '.join(sorted(ON_KEYS))})"
        )
    for key in ("mention", "pull_request", "draft"):
        if key in on and not isinstance(on[key], bool):
            raise ValueError(f"'{key}' under 'on' must be true or false")


def _wanted(value: Any) -> set[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return {str(v).strip().lower() for v in values if v is not None and str(v).strip()}


def _repo_matches(repo: str, patterns: set[str]) -> bool:
    repo = repo.lower()
    for pattern in patterns:
        if pattern == repo:
            return True
        if pattern.endswith("/*") and repo.split("/", 1)[0] == pattern[:-2]:
            return True
    return False


def matches(on: dict[str, Any], event_name: str, payload: dict[str, Any], settings: GitHubSettings) -> bool:
    """Whether one rule's ``on:`` accepts this event. Every key given must hold."""
    check_on(on)
    facts = thread_of(event_name, payload)
    if "event" in on and event_name.lower() not in _wanted(on["event"]):
        return False
    if "action" in on and facts["action"].lower() not in _wanted(on["action"]):
        return False
    if "label" in on and facts["label"].lower() not in _wanted(on["label"]):
        return False
    if "has_label" in on and not ({label.lower() for label in facts["labels"]} & _wanted(on["has_label"])):
        return False
    if "mention" in on and mentions(text_of(event_name, payload), settings.app) != on["mention"]:
        return False
    if "pull_request" in on and facts["is_pull"] != on["pull_request"]:
        return False
    if "draft" in on and facts["draft"] != on["draft"]:
        return False
    if "repos" in on and not _repo_matches(facts["repo"], _wanted(on["repos"])):
        return False
    return not ("authors" in on and facts["sender"].lower() not in _wanted(on["authors"]))
