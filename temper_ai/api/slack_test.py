"""The Slack test entry (temper_ai/integrations/slack/door.py explains it).

    GET  /api/test/slack               on or off; the test channel and user
    POST /api/test/slack               a fake Slack envelope, handled like a real one
    GET  /api/test/slack/fakes/{id}    what came of one fake: inbox event, replies, forms
    POST /api/test/slack/replies/{id}  a fake's response link

Private: never on the public hook address, and every call needs the
entry's own secret (TEMPER_SLACK_TEST_TOKEN, sent as X-Temper-Test-Token)
or temper's API token, except the reply link when the server calls it
itself (from 127.0.0.1), as it calls Slack's own response_url: with no
token. It takes answers only for a fake made in the last hour, whose id is
24 random hex characters.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from temper_ai.api.auth import _presented_token
from temper_ai.integrations.slack import door
from temper_ai.integrations.slack import service as slack_service

router = APIRouter(prefix="/api/test/slack", tags=["slack test"])

LOOPBACK = ("127.0.0.1", "::1", "localhost")


def _why_not(request: Request) -> tuple[int, str] | None:
    return door.refused(request.headers.get(door.HEADER), _presented_token(dict(request.scope)))


def _allowed(request: Request) -> None:
    why = _why_not(request)
    if why is not None:
        raise HTTPException(why[0], why[1])


@router.get("")
def entry_info(request: Request) -> dict[str, Any]:
    _allowed(request)
    return door.info(slack_service.running())


@router.post("")
async def take_fake(request: Request) -> dict[str, Any]:
    _allowed(request)
    try:
        envelope = await request.json()
    except ValueError as exc:
        raise HTTPException(400, "the body is not JSON") from exc
    try:
        # Saving it and finding the channel wait on the database and Slack.
        return await run_in_threadpool(door.take, envelope, service=slack_service.running())
    except door.DoorError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/fakes/{fake_id}")
def show_fake(fake_id: str, request: Request) -> dict[str, Any]:
    _allowed(request)
    found = door.show(fake_id)
    if found is None:
        raise HTTPException(404, f"there is no fake {fake_id} (fakes are kept for an hour)")
    return found


@router.post("/replies/{fake_id}")
async def fake_reply(fake_id: str, request: Request) -> dict[str, Any]:
    caller = request.client.host if request.client else ""
    if caller not in LOOPBACK:
        _allowed(request)
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(400, "the body is not JSON") from exc
    # An answer for everyone is posted in Slack from here.
    if not await run_in_threadpool(door.reply, fake_id, payload, service=slack_service.running()):
        raise HTTPException(404, "no such fake")
    return {"ok": True}
