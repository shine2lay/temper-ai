"""Real ASGI middleware + explicit recording ports. No server or real custody."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from temper_ai.api import auth
from temper_ai.api.caller import Caller, bound
from temper_ai.api.private_contexts import create_private_router
from temper_ai.api.private_identity import (
    bound_verified_named_key,
    issue_private_caller,
    require_private_caller_provenance,
)
from temper_ai.private_context.errors import (
    HTTP_STATUS,
    PrivateDraftErrorCode,
    PrivateDraftFailure,
)
from temper_ai.private_context.private_json import encode_private
from temper_ai.private_context.wire import decode_object

from . import ipd1
from .ipd1 import require
from .transport_fakes import SYNTHETIC_KEY, RecordingPorts, fake_key_sources

ROOT = "/api/private-contexts"


def app_for(boundary):
    app = FastAPI()
    app.include_router(create_private_router(lambda request: boundary))
    app.add_middleware(auth.CallerMiddleware)
    app.add_middleware(auth.TokenAuthMiddleware)
    return app


def exchange(app, *, path=ROOT, method="POST", raw=b"{}", key=SYNTHETIC_KEY,
             headers=(), query=b""):
    """Direct in-process ASGI with a receive spy, no networking/test server."""
    received = 0
    sent = []
    async def receive():
        nonlocal received
        received += 1
        return {"type": "http.request", "body": raw, "more_body": False}
    async def send(message):
        sent.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "scheme": "http", "server": ("synthetic", 80), "client": ("127.0.0.1", 1234),
        "root_path": "", "path": path, "raw_path": path.encode(), "query_string": query,
        "method": method, "headers": [(b"host", b"synthetic"),
            (b"content-type", b"application/json"), *headers]}
    if key is not None:
        scope["headers"].append((b"authorization", b"Bearer " + key.encode()))
    asyncio.run(app(scope, receive, send))
    start = next(item for item in sent if item["type"] == "http.response.start")
    data = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), data, received


def safe_response(reply, *, status=200):
    code, headers, raw, _ = reply
    require(code == status and headers.get(b"cache-control") == b"no-store")
    require(UUID(headers[b"x-request-id"].decode()).version == 4)
    require(ipd1.scan({ipd1.Surface.ERROR: raw}).clean)


@pytest.fixture
def ports(monkeypatch):
    fake_key_sources(monkeypatch)
    return RecordingPorts()


def test_registration_new_equal_changed_and_lost_through_http_client(ports):
    """Real HTTP client success handling; recording-port semantics, not C1 custody proof."""
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(ports.boundary())),
                base_url="http://synthetic", headers={"Authorization": "Bearer " + SYNTHETIC_KEY,
                                                    "Content-Type": "application/json"}) as client:
            raw = ipd1.registration().to_private_json()
            new = await client.post(ROOT, content=raw)
            retry = await client.post(ROOT, content=raw)
            new.raise_for_status()
            retry.raise_for_status()
            require(new.status_code == retry.status_code == 200 and new.json() == retry.json())
            # Same attempt with changed valid body bytes; the recording service
            # supplies conflict rather than transport guessing via another read.
            changed = ipd1.registration().open_private()
            changed["expires_at"] = "2098-01-01T00:00:00Z"
            conflict = await client.post(ROOT, content=encode_private(changed))
            require(conflict.status_code == HTTP_STATUS[PrivateDraftErrorCode.CONTEXT_CONFLICT])
            require(conflict.json()["error"]["code"] == "context_conflict")
            ports.registration_lost = True
            lost = await client.post(ROOT, content=raw)
            require(lost.status_code == HTTP_STATUS[PrivateDraftErrorCode.CONTEXT_LOST])
            require(lost.json()["error"]["code"] == "context_lost")
            require(all(response.headers["cache-control"] == "no-store"
                        for response in (new, retry, conflict, lost)))
            require(ipd1.scan({ipd1.Surface.ERROR: conflict.content + lost.content}).clean)
    asyncio.run(run())


def test_combined_authenticated_application_flow_and_revocation(ports):
    app = app_for(ports.boundary())
    responses = [exchange(app, raw=ipd1.registration().to_private_json()),
        exchange(app, path=ROOT + "/status", raw=encode_private(
            {"context_ref": ipd1.REF, "context_version": 1}))]
    wanted = encode_private({"context_ref": ipd1.REF, "execution_id": ipd1.RUN, "draft_ref": ipd1.DRAFT})
    private_result = exchange(app, path=ROOT + "/result", raw=wanted)
    require(private_result[0] == 200 and private_result[1][b"cache-control"] == b"no-store")
    require(decode_object(private_result[2])["draft"] == ipd1.draft().open_private())
    responses += [exchange(app, path=ROOT + "/ack", raw=wanted),
                  exchange(app, path=ROOT + "/" + ipd1.REF, method="DELETE")]
    for reply in responses:
        safe_response(reply)
    require(len({reply[1][b"x-request-id"] for reply in responses}) == len(responses))
    require(ports.calls == ["register", "status", "result", "ack", "delete"])
    ports.allowed = False
    refused = exchange(app, raw=ipd1.registration().to_private_json())
    safe_response(refused, status=403)
    require(refused[3] == 0 and len(ports.calls) == 5)


@pytest.mark.parametrize("guard", ["off", "record", "enforce"])
@pytest.mark.parametrize("key,headers,query", [
    (None, (), b""), ("synthetic-shared-credential", (), b""),
    ("synthetic-other-credential", (), b""), ("trun_synthetic", (), b""),
    ("tgh_synthetic", (), b""), ("tpriv_synthetic", (), b""),
    (None, ((b"cookie", b"temper_token=synthetic-owner-credential"),), b""),
    (None, (), b"token=synthetic-owner-credential"),
    (None, ((b"origin", b"http://synthetic"),), b""),
    (SYNTHETIC_KEY, ((b"authorization", b"Bearer synthetic-owner-credential"),), b""),
    (SYNTHETIC_KEY, ((b"x-temper-token", b"synthetic-owner-credential"),), b""),
    (" synthetic-owner-credential", (), b""),
])
def test_unsupported_identity_refuses_before_receive(ports, monkeypatch, guard, key, headers, query):
    monkeypatch.setenv("TEMPER_API_GUARD", guard)
    reply = exchange(app_for(ports.boundary()), raw=ipd1.registration().to_private_json(),
                     key=key, headers=headers, query=query)
    require(reply[0] in {401, 403} and reply[3] == 0 and not ports.calls)
    safe_response(reply, status=reply[0])


@pytest.mark.parametrize("missing", ["boundary", "service", "composition", "profile"])
def test_missing_components_refuse_before_receive(ports, missing):
    boundary = ports.boundary()
    if missing == "boundary":
        boundary = None
    elif missing == "profile":
        ports.available = False
    else:
        boundary = replace(boundary, **{missing: None})
    reply = exchange(app_for(boundary), raw=ipd1.registration().to_private_json())
    safe_response(reply, status=503)
    require(reply[3] == 0 and not ports.calls)


@pytest.mark.parametrize("raw", [b"{", b'{"namespace":"scope-1","namespace":"other"}',
    b'{"namespace":"scope-1","profile":"synthetic-reply-v1","context":NaN}',
    b"[]", b"null", b"\xff"])
def test_malformed_wire_has_fixed_nonreflecting_errors(ports, raw):
    reply = exchange(app_for(ports.boundary()), raw=raw)
    require(reply[0] == 400 and not ports.calls)
    safe_response(reply, status=400)


@pytest.mark.parametrize("namespace,profile", [("scope-1-canary", "synthetic-reply-v1"),
    ("scope-1", "synthetic-reply-v1-canary"), ("foreign", "foreign")])
def test_scope_equality_not_prefix_or_contains(ports, namespace, profile):
    payload = ipd1.registration().open_private()
    payload.update(namespace=namespace, profile=profile)
    reply = exchange(app_for(ports.boundary()), raw=encode_private(payload))
    safe_response(reply, status=403)
    require(not ports.calls)


@pytest.mark.parametrize("path,method", [(ROOT + "/status-canary", "POST"),
    (ROOT + "/result/extra", "POST"), (ROOT, "GET"), (ROOT, "PUT"),
    (ROOT + "/not-a-reference", "DELETE")])
def test_closed_methods_paths_and_no_reflection(ports, path, method):
    reply = exchange(app_for(ports.boundary()), path=path, method=method,
                     raw=ipd1.registration().to_private_json())
    safe_response(reply, status=400)
    require(reply[3] == 0 and not ports.calls)


def test_metadata_cannot_smuggle_extra_response_values(ports, monkeypatch):
    class FaultyReceipt:
        def model_dump(self, **kwargs):
            return {"context_ref": ipd1.REF, "private": ipd1.draft().open_private()}
    monkeypatch.setattr(ports, "register", lambda *args: FaultyReceipt())
    reply = exchange(app_for(ports.boundary()), raw=ipd1.registration().to_private_json())
    safe_response(reply, status=400)


def test_named_key_equal_to_shared_token_never_has_private_authority(ports, monkeypatch):
    from temper_ai.api import api_keys

    monkeypatch.setattr(auth, "configured_token", lambda: SYNTHETIC_KEY)
    # Real identify_caller_name gives hashed named keys precedence over the
    # shared-token fallback. Exercise that collision, not only named_tokens.
    monkeypatch.setattr(api_keys, "identify_key", lambda raw: "owner-1" if raw == SYNTHETIC_KEY else None)
    # Bite the verifier independently as well as through the real middleware.
    require(auth.identify_verified_named_key(SYNTHETIC_KEY) is None)
    reply = exchange(app_for(ports.boundary()), raw=ipd1.registration().to_private_json())
    safe_response(reply, status=401)
    require(reply[3] == 0 and not ports.calls)


def test_caller_rebinding_and_key_revocation_invalidate_issued_principal(ports, monkeypatch):
    caller = Caller(name="owner-1", source="synthetic", request_id="synthetic", via="synthetic")
    with bound(caller), bound_verified_named_key(caller, SYNTHETIC_KEY):
        principal = issue_private_caller("owner-1", "scope-1", "synthetic-reply-v1", ports.may)
        with bound(replace(caller)), pytest.raises(PrivateDraftFailure):
            require_private_caller_provenance(principal)
        monkeypatch.setattr(auth, "identify_verified_named_key", lambda key: None)
        with pytest.raises(PrivateDraftFailure):
            require_private_caller_provenance(principal)


def test_constructed_caller_and_value_equal_principal_are_not_authority(ports):
    from temper_ai.private_context.contracts import CallerPrincipal

    caller = Caller(name="owner-1", source="synthetic", request_id="synthetic", via="synthetic")
    with bound(caller):
        with pytest.raises(PrivateDraftFailure):
            issue_private_caller("owner-1", "scope-1", "synthetic-reply-v1", ports.may)
        with bound_verified_named_key(caller, SYNTHETIC_KEY):
            principal = issue_private_caller("owner-1", "scope-1", "synthetic-reply-v1", ports.may)
            require(require_private_caller_provenance(principal) == "owner-1")
            forged = CallerPrincipal.model_validate(principal.model_dump())
            with pytest.raises(PrivateDraftFailure):
                require_private_caller_provenance(forged)
        with pytest.raises(PrivateDraftFailure):
            require_private_caller_provenance(principal)
