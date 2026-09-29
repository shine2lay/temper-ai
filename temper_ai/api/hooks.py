"""Incoming webhooks: an event somewhere else starts a workflow here.

``POST /api/hooks/linear``, ``POST /api/hooks/notion`` and
``POST /api/hooks/github`` are the addresses the internet may reach (the
gateway forwards those exact paths and nothing else), so they authenticate
themselves: the API token cannot be asked of Linear, Notion or GitHub, and
instead every delivery must carry the sender's signature over its exact
bytes (Linear's must also be under a minute old). See triggers.linear,
triggers.notion and triggers.github.

Every checked delivery is saved in the event inbox (integrations.inbox)
before temper answers, and handled from there after the answer. Linear
gives up on a delivery that takes more than five seconds to answer, and
starting a run can take longer than that. If handling fails, or a restart
cuts it off, the inbox tries again, so nothing that was answered "got it"
is lost. What became of each delivery is on its row: ``temper events
list``, and ``GET /api/hooks/linear/recent`` and ``/notion/recent`` (behind
the API token, like the rest of the API).

A delivery sent again (Linear and Notion retry what they think failed) has
the same id, so it is answered without being handled twice. One that comes
before its signing key is set is kept unchecked (up to 256 KB each and 500
in all) and checked once the key is there: handled if it is genuine,
dropped if not. One with no signature at all is refused.

One issue, one run of a workflow at a time. A rule whose inputs name an
``issue_id`` does not start its workflow for an issue whose last run of
that workflow is still going: two runs working one issue would build on the
same branch at once. The skipped event is recorded; the comment it carried
is still in the thread for the next run to read.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from temper_ai.integrations.inbox import service as inbox
from temper_ai.integrations.inbox import store as inbox_store
from temper_ai.triggers import github, linear
from temper_ai.triggers.rules import Trigger, load_triggers, render_inputs

logger = logging.getLogger(__name__)

router = APIRouter()

LINEAR_PATH = "/api/hooks/linear"
LINEAR = "linear"
NOTION = "notion"
RECENT_MAX = 50
# (workflow, issue id) -> the execution id of the last run a rule started for it
_issue_runs: dict[tuple[str, str], str] = {}
_issue_lock = threading.Lock()
_ACTIVE = frozenset({"pending", "queued", "running", "waiting"})


def _save(source: str, delivery: str, kind: str, subject: str, event: dict[str, Any]) -> tuple[Any, bool]:
    try:
        return inbox.receive(source, delivery, kind=kind, subject=subject, payload=event)
    except Exception as exc:
        # Not "got it": the sender tries again later.
        logger.exception("Could not save %s delivery %s", source, delivery)
        raise HTTPException(status_code=500, detail="temper could not save the event; send it again") from exc


def _hold(source: str, delivery: str, raw: bytes, signature: str, env: str) -> JSONResponse:
    """Keep a signed event that came before the signing key was set."""
    status, message = inbox.hold(source, delivery, raw, signature)
    if status != 202:
        raise HTTPException(status_code=status, detail=f"{env} is not set, and {message}.")
    logger.warning("%s event %s kept unchecked: %s is not set yet", source.title(), delivery, env)
    return JSONResponse({"ok": True, "held": True, "detail": f"{env} is not set: {message}"}, status_code=202)


# -- Linear ------------------------------------------------------------------------------


def _linear_kind(event: dict[str, Any]) -> str:
    return ".".join(str(p) for p in (event.get("type"), event.get("action")) if p)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _linear_subject(event: dict[str, Any]) -> str:
    """The issue an event is about, for lists."""
    data = _dict(event.get("data"))
    if event.get("type") == "Issue":
        return str(data.get("identifier") or data.get("id") or "")
    issue = _dict(data.get("issue"))
    return str(issue.get("identifier") or issue.get("id") or data.get("issueId") or "")


@router.post(LINEAR_PATH)
async def linear_webhook(request: Request, background: BackgroundTasks) -> Any:
    raw = await request.body()
    signature = request.headers.get("linear-signature") or ""
    if not signature:
        raise HTTPException(status_code=401, detail="There is no Linear-Signature.")
    delivery = request.headers.get("linear-delivery", "").strip() or "sha256:" + hashlib.sha256(raw).hexdigest()[:32]
    secret = linear.signing_secret()
    if secret is None:
        return _hold(LINEAR, delivery, raw, signature, linear.SIGNING_SECRET_ENV)
    if not linear.verify_signature(raw, signature, secret):
        raise HTTPException(status_code=401, detail="Linear-Signature does not match the body.")
    event = _json_object(raw)
    if not linear.is_fresh(event):
        raise HTTPException(status_code=401, detail="webhookTimestamp is more than a minute away.")

    row, new = _save(LINEAR, delivery, _linear_kind(event), _linear_subject(event), event)
    if not new:
        logger.info("Linear delivery %s: a retry of one already received", delivery)
        return {"ok": True, "delivery": delivery, "duplicate": True}
    background.add_task(inbox.process, row.id)
    return {"ok": True, "delivery": delivery, "event": row.id}


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        event = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="The body is not JSON.") from exc
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="The body is not a JSON object.")
    return event


def _check_linear(ev: inbox_store.Event) -> tuple[dict[str, Any], str, str] | None:
    """A kept Linear event, checked now that the key may be set (judged as of when it came)."""
    secret = linear.signing_secret()
    if secret is None:
        return None
    raw = ev.raw.encode()
    if not linear.verify_signature(raw, ev.signature or None, secret):
        raise inbox.Bad("Linear-Signature does not match the body")
    try:
        event = json.loads(raw)
    except ValueError as exc:
        raise inbox.Bad("the body is not JSON") from exc
    if not isinstance(event, dict):
        raise inbox.Bad("the body is not a JSON object")
    if not linear.is_fresh(event, now=ev.received_at.timestamp()):
        raise inbox.Bad("webhookTimestamp was more than a minute from when it came")
    return event, _linear_kind(event), _linear_subject(event)


def _record_of(ev: inbox_store.Event) -> dict[str, Any]:
    """One delivery the way /recent shows it."""
    event = ev.payload
    raw_actor = event.get("actor")
    actor: dict[str, Any] = raw_actor if isinstance(raw_actor, dict) else {}
    return {
        "event": ev.id,
        "delivery": ev.delivery,
        "received_at": ev.received_at.isoformat(timespec="seconds"),
        "type": event.get("type"),
        "action": event.get("action"),
        "url": event.get("url"),
        "actor": actor.get("name") or actor.get("id"),
        "actor_id": actor.get("id"),
        "actor_type": actor.get("type"),
        "status": ev.status,
        "outcome": ev.outcome or ev.error or ev.status,
        "runs": list(ev.result.get("runs") or []),
    }


@router.get(LINEAR_PATH + "/recent")
def linear_recent() -> dict[str, Any]:
    """The last deliveries and what became of each, newest first."""
    return {"deliveries": [_record_of(ev) for ev in inbox_store.listing(source=LINEAR, limit=RECENT_MAX)]}


def _handle_linear(ev: inbox_store.Event) -> inbox.Outcome:
    record = _record_of(ev)
    record["outcome"], record["runs"] = "received", []
    dispatch(ev.payload, record)
    outcome = str(record.get("outcome") or "handled")
    if outcome.startswith("error:") or any("error" in r for r in record["runs"]):
        # Kept and tried again after a wait; what did start is noted on the event and not started twice.
        raise inbox.Retry(outcome)
    out = inbox.outcome(outcome)
    out.extra["runs"] = record["runs"]
    return out


def dispatch(
    event: dict[str, Any], record: dict[str, Any], config_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Match one verified delivery against the Linear rules and start their workflows."""
    try:
        _dispatch(event, record, config_dir)
    except Exception as exc:  # noqa: BLE001 - recorded, and the inbox tries again
        logger.exception("Linear delivery %s failed", record.get("delivery"))
        record["outcome"] = f"error: {exc}"
    logger.info(
        "Linear delivery %s (%s %s): %s",
        record.get("delivery"), record.get("type"), record.get("action"), record["outcome"],
    )
    return record


def _wants_comments(triggers: list[Trigger]) -> bool:
    for trigger in triggers:
        kind = trigger.on.get("type")
        kinds = kind if isinstance(kind, (list, tuple, set)) else [kind]
        if any(str(k).strip().lower() == "comment" for k in kinds if k is not None):
            return True
    return False


def _dispatch(event: dict[str, Any], record: dict[str, Any], config_dir: str | Path | None) -> None:
    triggers = [t for t in load_triggers(config_dir, source=linear.SOURCE) if t.enabled]
    if linear.needs_issue(event) and _wants_comments(triggers):
        # A comment names its issue but not the issue's labels: ask, or match nothing
        # (a rule on labelled issues must not fire for an issue it cannot see).
        try:
            linear.enrich(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read the issue of Linear comment %s: %s", record.get("delivery"), exc)
            record["outcome"] = f"skipped: could not read the comment's issue ({exc})"
            return

    matched: list[Trigger] = []
    for trigger in triggers:
        try:
            if linear.matches(trigger.on, event):
                matched.append(trigger)
        except ValueError as exc:
            logger.warning("Trigger %s (%s): %s", trigger.name, trigger.path, exc)
    if not matched:
        record["outcome"] = "no trigger matched"
        return

    skipped = _drop_own_changes(event, matched)
    if skipped:
        record["outcome"] = skipped
        return

    from temper_ai.api.routes import RunRequest, start_run

    # Runs this event started on an earlier try: not started again.
    earlier = {s.get("workflow"): s.get("execution_id") for s in inbox.already_started()}
    for trigger in matched:
        entry: dict[str, Any] = {"trigger": trigger.name, "workflow": trigger.workflow}
        try:
            if trigger.workflow in earlier:
                entry["execution_id"] = str(earlier[trigger.workflow])
                entry["earlier"] = True
                record["runs"].append(entry)
                continue
            inputs = render_inputs(trigger, event)
            issue = str(inputs.get("issue_id") or "").strip()
            key = (trigger.workflow, issue)
            if issue:
                entry["issue"] = issue
            with _issue_lock:
                going = _run_still_going(_issue_runs.get(key) or _last_issue_run(*key)) if issue else None
                if going:
                    entry["skipped"] = f"{trigger.workflow} run {going[:8]} for this issue is still going"
                    record["runs"].append(entry)
                    continue
                response = start_run(RunRequest(workflow=trigger.workflow, inputs=inputs))
                if issue:
                    _issue_runs[key] = response.execution_id
            entry["execution_id"] = response.execution_id
        except HTTPException as exc:
            entry["error"] = str(exc.detail)
        except Exception as exc:  # noqa: BLE001 - one rule failing must not stop the others
            entry["error"] = str(exc)
        record["runs"].append(entry)

    started = [r for r in record["runs"] if "execution_id" in r]
    failed = [r for r in record["runs"] if "error" in r]
    busy = [r for r in record["runs"] if "skipped" in r]
    parts = []
    if started:
        parts.append("started " + ", ".join(f"{r['workflow']} {r['execution_id'][:8]}" for r in started))
    if busy:
        parts.append("skipped " + "; ".join(f"{r['trigger']}: {r['skipped']}" for r in busy))
    if failed:
        parts.append("failed " + "; ".join(f"{r['trigger']}: {r['error']}" for r in failed))
    record["outcome"] = " / ".join(parts)


def _last_issue_run(workflow: str, issue: str) -> str | None:
    """The last run of ``workflow`` a Linear event started for ``issue``, from the
    inbox (the memory above is empty after a restart)."""
    try:
        for ev in inbox_store.listing(source=LINEAR, limit=200):
            for run in ev.result.get("runs") or []:
                if (isinstance(run, dict) and run.get("workflow") == workflow and run.get("issue") == issue
                        and run.get("execution_id")):
                    return str(run["execution_id"])
    except Exception as exc:  # noqa: BLE001 - no database: the memory alone decides
        logger.warning("Could not look up the last run for issue %s: %s", issue, exc)
    return None


def _drop_own_changes(event: dict[str, Any], matched: list[Trigger]) -> str | None:
    """Remove the rules that must not fire for this event; a reason if none are left.

    Fails closed: if temper cannot tell whether the change was its own (no
    app configured, or Linear did not answer), a rule that ignores its own
    changes does not fire. A loop costs more than a missed event.
    """
    guarded = [t for t in matched if t.ignore_self]
    if not guarded:
        return None
    reason = None
    try:
        me = linear.app_user_id()
        if me is None:
            reason = (
                f"skipped: {linear.CLIENT_ID_ENV}/{linear.CLIENT_SECRET_ENV} are not set, so "
                "temper cannot tell its own changes apart (set ignore_self: false to fire anyway)"
            )
        elif linear.is_own(event, me):
            reason = "ignored: temper's own change"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not ask Linear who temper's app user is: %s", exc)
        reason = f"skipped: could not ask Linear who temper's app user is ({exc})"
    if reason is None:
        return None
    matched[:] = [t for t in matched if not t.ignore_self]
    return None if matched else reason


def _run_still_going(execution_id: str | None) -> str | None:
    """The id back if that run has not finished yet; None if it has, or is unknown."""
    if not execution_id:
        return None
    from temper_ai.api.routes import _state, get_workflow

    try:
        if execution_id in _state().running:
            return execution_id
    except Exception:  # noqa: BLE001, S110 - no app state (tests, CLI): ask the database
        pass
    try:
        status = str(get_workflow(execution_id).get("status") or "").lower()
    except HTTPException:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not tell whether run %s is still going: %s", execution_id, exc)
        return None
    return execution_id if status in _ACTIVE else None


# -- Notion ------------------------------------------------------------------------------

NOTION_PATH = "/api/hooks/notion"
NOTION_TOKEN_KEY = "verification_token"  # noqa: S105 - a state key, not a secret


@router.post(NOTION_PATH)
async def notion_webhook(request: Request, background: BackgroundTasks) -> Any:
    """Notion's events (see triggers.notion). The one-time verification
    request is kept so ``temper notion check`` can show its token; every
    other delivery must be signed with ``NOTION_WEBHOOK_SECRET``."""
    from temper_ai.integrations.notion import store as notion_store
    from temper_ai.triggers import notion

    raw = await request.body()
    event = _json_object(raw)
    if set(event) == {"verification_token"}:
        notion_store.set_state(NOTION_TOKEN_KEY, str(event["verification_token"])[:200])
        logger.warning("Notion sent a webhook verification token; `temper notion check` shows it. "
                       "Paste it into Notion, and into %s in .env.", notion.SECRET_ENV)
        return {"ok": True}
    signature = request.headers.get("x-notion-signature") or ""
    if not signature:
        raise HTTPException(status_code=401, detail="There is no X-Notion-Signature.")
    event_id = str(event.get("id") or "").strip()
    if not event_id:
        raise HTTPException(status_code=400, detail="The event has no id.")
    secret = notion.signing_secret()
    if secret is None:
        return _hold(NOTION, event_id, raw, signature, notion.SECRET_ENV)
    if not notion.verify_signature(raw, signature, secret):
        raise HTTPException(status_code=401, detail="X-Notion-Signature does not match the body.")
    row, new = _save(NOTION, event_id, str(event.get("type") or ""), notion.page_of(event), event)
    if not new:
        return {"ok": True, "duplicate": True}
    background.add_task(inbox.process, row.id)
    return {"ok": True, "event": row.id}


def _check_notion(ev: inbox_store.Event) -> tuple[dict[str, Any], str, str] | None:
    from temper_ai.triggers import notion

    secret = notion.signing_secret()
    if secret is None:
        return None
    raw = ev.raw.encode()
    if not notion.verify_signature(raw, ev.signature or None, secret):
        raise inbox.Bad("X-Notion-Signature does not match the body")
    try:
        event = json.loads(raw)
    except ValueError as exc:
        raise inbox.Bad("the body is not JSON") from exc
    if not isinstance(event, dict) or str(event.get("id") or "") != ev.delivery:
        raise inbox.Bad("the body is not the event it said it was")
    return event, str(event.get("type") or ""), notion.page_of(event)


@router.get(NOTION_PATH + "/recent")
def notion_recent() -> dict[str, Any]:
    """The last Notion events and what became of each, newest first."""
    from temper_ai.triggers import notion

    out = []
    for ev in inbox_store.listing(source=NOTION, limit=RECENT_MAX):
        event = ev.payload
        authors = ",".join(f"{a['type']}:{a['id'][:8]}" for a in notion.authors(event)) if event else ""
        out.append({"id": ev.delivery, "event": ev.id, "at": ev.received_at.isoformat(timespec="seconds"),
                    "type": ev.kind, "entity": str((event.get("entity") or {}).get("id") or ""),
                    "page": ev.subject, "author": authors, "status": ev.status,
                    "outcome": ev.outcome or ev.error or ev.status})
    return {"events": out}


def notion_dispatch(event: dict[str, Any]) -> str:
    """Do what one verified Notion event asks; the outcome in a few words.
    Raises if it went wrong, and the inbox tries again."""
    from temper_ai.integrations.notion.service import service, why_off

    svc = service()
    if svc is None:
        reason = why_off()
        if reason is None:
            # Notion is on but not started yet in this server (the server is
            # starting up): the event waits for it rather than being dropped.
            raise inbox.Retry("Notion hasn't started yet in this server")
        outcome = f"skipped: Notion is off ({reason})"
    else:
        outcome = svc.handle(event)
    logger.info("Notion event %s (%s): %s", event.get("id"), event.get("type"), outcome)
    return outcome


def _handle_notion(ev: inbox_store.Event) -> inbox.Outcome:
    from temper_ai.integrations.notion.service import only_failed

    outcome = str(notion_dispatch(ev.payload) or "handled")
    if only_failed(outcome):
        raise inbox.Retry(outcome)
    return inbox.outcome(outcome)


# -- GitHub ------------------------------------------------------------------------------

GITHUB = github.SOURCE
# issue or pull request ("owner/name#12") -> the execution id of the last run started for it
_thread_runs: dict[str, str] = {}


def _github_kind(event_name: str, payload: dict[str, Any]) -> str:
    return ".".join(p for p in (event_name, str(payload.get("action") or "")) if p)


@router.post(github.PATH)
async def github_webhook(request: Request, background: BackgroundTasks) -> Any:
    """The GitHub app's events (see triggers.github), signed with its webhook secret."""
    raw = await request.body()
    signature = request.headers.get(github.SIGNATURE_HEADER) or ""
    if not signature:
        raise HTTPException(status_code=401, detail="There is no X-Hub-Signature-256.")
    event_name = request.headers.get(github.EVENT_HEADER, "").strip()
    delivery = (request.headers.get(github.DELIVERY_HEADER, "").strip()
                or "sha256:" + hashlib.sha256(raw).hexdigest()[:32])
    secret = github.signing_secret()
    if secret is not None and not github.verify_signature(raw, signature, secret):
        raise HTTPException(status_code=401, detail="X-Hub-Signature-256 does not match the body.")
    if not github.kept(event_name):
        # Nothing starts from it (a check run, a workflow run...: the app may be sent more than
        # temper uses), so it is not kept.
        logger.debug("GitHub delivery %s: a %s event, not kept", delivery, event_name or "nameless")
        return {"ok": True, "delivery": delivery, "ignored": f"{event_name or 'an unnamed'} events start nothing"}
    if secret is None:
        # The event name is not in the body: it is kept with the signature.
        return _hold(GITHUB, delivery, raw, f"{event_name} {signature}", github.SECRET_ENV)
    payload = _json_object(raw)
    row, new = _save(GITHUB, delivery, _github_kind(event_name, payload),
                     github.subject_of(event_name, payload), payload)
    if not new:
        logger.info("GitHub delivery %s: a redelivery of one already received", delivery)
        return {"ok": True, "delivery": delivery, "duplicate": True}
    background.add_task(inbox.process, row.id)
    return {"ok": True, "delivery": delivery, "event": row.id}


def _check_github(ev: inbox_store.Event) -> tuple[dict[str, Any], str, str] | None:
    """A kept GitHub event, checked now that the webhook secret may be set."""
    secret = github.signing_secret()
    if secret is None:
        return None
    event_name, _, signature = (ev.signature or "").partition(" ")
    raw = ev.raw.encode()
    if not github.verify_signature(raw, signature, secret):
        raise inbox.Bad("X-Hub-Signature-256 does not match the body")
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise inbox.Bad("the body is not JSON") from exc
    if not isinstance(payload, dict):
        raise inbox.Bad("the body is not a JSON object")
    return payload, _github_kind(event_name, payload), github.subject_of(event_name, payload)


def _event_name(ev: inbox_store.Event) -> str:
    return (ev.kind or "").split(".", 1)[0]


@router.get(github.PATH + "/recent")
def github_recent() -> dict[str, Any]:
    """The last GitHub deliveries and what became of each, newest first."""
    out = []
    for ev in inbox_store.listing(source=GITHUB, limit=RECENT_MAX):
        payload = ev.payload or {}
        out.append({
            "event": ev.id,
            "delivery": ev.delivery,
            "received_at": ev.received_at.isoformat(timespec="seconds"),
            "kind": ev.kind,
            "thread": ev.subject,
            "sender": str(_dict(payload.get("sender")).get("login") or ""),
            "status": ev.status,
            "outcome": ev.outcome or ev.error or ev.status,
            "runs": list(ev.result.get("runs") or []),
        })
    return {"deliveries": out}


def _handle_github(ev: inbox_store.Event) -> inbox.Outcome:
    record: dict[str, Any] = {"delivery": ev.delivery, "outcome": "received", "runs": []}
    github_dispatch(_event_name(ev), ev.payload, record)
    outcome = str(record.get("outcome") or "handled")
    if outcome.startswith("error:") or any("error" in r for r in record["runs"]):
        raise inbox.Retry(outcome)
    out = inbox.outcome(outcome)
    out.extra["runs"] = record["runs"]
    return out


def github_dispatch(
    event_name: str, payload: dict[str, Any], record: dict[str, Any], config_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Match one verified GitHub delivery against the GitHub rules and start their workflows."""
    record.setdefault("runs", [])
    try:
        _github_dispatch(event_name, payload, record, config_dir)
    except Exception as exc:  # noqa: BLE001 - recorded, and the inbox tries again
        logger.exception("GitHub delivery %s failed", record.get("delivery"))
        record["outcome"] = f"error: {exc}"
    logger.info("GitHub delivery %s (%s.%s %s): %s", record.get("delivery"), event_name,
                payload.get("action"), github.subject_of(event_name, payload), record["outcome"])
    return record


def _github_dispatch(
    event_name: str, payload: dict[str, Any], record: dict[str, Any], config_dir: str | Path | None,
) -> None:
    from temper_ai.integrations.github.settings import load_settings

    settings = load_settings(config_dir)
    refused = github.refusal(event_name, payload, settings)
    if refused:
        record["outcome"] = refused
        return

    matched: list[Trigger] = []
    for trigger in load_triggers(config_dir, source=GITHUB):
        if not trigger.enabled:
            continue
        try:
            if github.matches(trigger.on, event_name, payload, settings):
                matched.append(trigger)
        except ValueError as exc:
            logger.warning("Trigger %s (%s): %s", trigger.name, trigger.path, exc)
    if not matched:
        record["outcome"] = "no trigger matched"
        return

    event = github.with_context(event_name, payload)
    facts = event["github"]
    if facts["is_pull"] and not facts["head_ref"]:
        # A comment on a pull request does not say which branches it joins.
        facts.update(_pull_branches(facts["repo"], facts["number"]))
    thread = github.subject_of(event_name, payload)

    from temper_ai.api.routes import RunRequest, start_run

    # Runs this event started on an earlier try: not started again.
    earlier = {s.get("workflow"): s.get("execution_id") for s in inbox.already_started()}
    started = False
    for trigger in matched:
        entry: dict[str, Any] = {"trigger": trigger.name, "workflow": trigger.workflow, "thread": thread}
        try:
            if trigger.workflow in earlier:
                entry["execution_id"] = str(earlier[trigger.workflow])
                entry["earlier"] = True
                record["runs"].append(entry)
                started = True
                continue
            if started:
                # Two rules for one event (a reply that also calls on the app): one run.
                continue
            inputs = render_inputs(trigger, event)
            with _issue_lock:
                going = _run_still_going(_thread_runs.get(thread) or _last_thread_run(thread))
                if going:
                    entry["skipped"] = f"run {going[:8]} for {thread} is still going"
                    record["runs"].append(entry)
                    continue
                response = start_run(RunRequest(workflow=trigger.workflow, inputs=inputs))
                _thread_runs[thread] = response.execution_id
            entry["execution_id"] = response.execution_id
            started = True
        except HTTPException as exc:
            entry["error"] = str(exc.detail)
        except Exception as exc:  # noqa: BLE001 - one rule failing must not stop the others
            entry["error"] = str(exc)
        record["runs"].append(entry)
    record["outcome"] = _summary(record["runs"])


def _summary(runs: list[dict[str, Any]]) -> str:
    started = [r for r in runs if "execution_id" in r]
    failed = [r for r in runs if "error" in r]
    busy = [r for r in runs if "skipped" in r]
    parts = []
    if started:
        parts.append("started " + ", ".join(f"{r['workflow']} {r['execution_id'][:8]}" for r in started))
    if busy:
        parts.append("skipped " + "; ".join(f"{r['trigger']}: {r['skipped']}" for r in busy))
    if failed:
        parts.append("failed " + "; ".join(f"{r['trigger']}: {r['error']}" for r in failed))
    return " / ".join(parts)


def _pull_branches(repo: str, number: str) -> dict[str, Any]:
    """The branches a pull request joins, asked of GitHub as the app."""
    from temper_ai.integrations.github.app import get_app

    response = get_app().request("GET", repo, f"/pulls/{number}")
    if not response.is_success:
        raise RuntimeError(f"could not read pull request {repo}#{number} ({response.status_code})")
    pull = response.json()
    head, base = _dict(pull.get("head")), _dict(pull.get("base"))
    return {
        "head_ref": str(head.get("ref") or ""),
        "head_repo": str(_dict(head.get("repo")).get("full_name") or ""),
        "base_ref": str(base.get("ref") or ""),
        "draft": bool(pull.get("draft")),
    }


def _last_thread_run(thread: str) -> str | None:
    """The last run a GitHub event started for an issue or PR, from the inbox (after a restart)."""
    try:
        for ev in inbox_store.listing(source=GITHUB, limit=200):
            for run in ev.result.get("runs") or []:
                if isinstance(run, dict) and run.get("thread") == thread and run.get("execution_id"):
                    return str(run["execution_id"])
    except Exception as exc:  # noqa: BLE001 - no database: the memory alone decides
        logger.warning("Could not look up the last run for %s: %s", thread, exc)
    return None


inbox.register(LINEAR, _handle_linear, redo_safe=True)
inbox.register_checker(LINEAR, _check_linear)
inbox.register(NOTION, _handle_notion)
inbox.register_checker(NOTION, _check_notion)
inbox.register(GITHUB, _handle_github, redo_safe=True)
inbox.register_checker(GITHUB, _check_github)


def reset_state() -> None:
    """Forget which runs were started for which issue (tests)."""
    with _issue_lock:
        _issue_runs.clear()
        _thread_runs.clear()
