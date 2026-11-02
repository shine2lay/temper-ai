"""Closed decoder for the private variant of the existing normal-start route.

The private APIs authenticate before reading any bytes. The shared /api/runs
route has to inspect its discriminator to distinguish ordinary requests; it
never passes a private request to FastAPI's reflective body-error machinery.
"""
from __future__ import annotations

import json

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from temper_ai.api.private_contexts import read_private_json
from temper_ai.api.private_responses import private_failure, private_headers
from temper_ai.llm.single_send import metadata_only_logs
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.runtime import caller_boundary, get_private_boundary
from temper_ai.private_context.wire import PrivateRunStart, decode_wire
from temper_ai.runner.private_context_binding import (
    private_run_requested,
    private_start_requested,
)


async def _ordinary_without_reflection(handler, request: Request):
    # Invalid/escaped discriminators cannot safely identify private input.
    # Preserve ordinary validation status, never reflected request values.
    try:
        return await handler(request)
    except (RequestValidationError, RecursionError):
        return JSONResponse({"detail": "Invalid request"}, status_code=422, headers=private_headers())


class PrivateStartRoute(APIRoute):
    def get_route_handler(self):
        ordinary = super().get_route_handler()

        async def handle(request: Request):
            raw = await request.body()
            try:
                envelope = json.loads(raw)
            except (ValueError, UnicodeError, RecursionError):
                # This only selects the fixed failure path, not power.
                if b"private_context" in raw:
                    return private_failure(Code.CONTEXT_INVALID)
                return await _ordinary_without_reflection(ordinary, request)
            if not isinstance(envelope, dict) or not private_start_requested(
                envelope.get("workflow", envelope.get("workflow_name")), envelope.get("inputs"),
            ):
                return await _ordinary_without_reflection(ordinary, request)
            with metadata_only_logs():
                try:
                    caller_boundary(get_private_boundary())
                    await read_private_json(request)
                    wanted = decode_wire(raw, PrivateRunStart)
                    from temper_ai.api.routes import RunRequest, start_run

                    response = await run_in_threadpool(start_run, RunRequest(
                        workflow=wanted.workflow, inputs=wanted.inputs.model_dump(mode="json")))
                    return JSONResponse(response.model_dump(mode="json"), headers=private_headers())
                except PrivateDraftFailure as exc:
                    return private_failure(exc.code)
                except Exception:
                    return private_failure(Code.CONTEXT_UNAVAILABLE)

        return handle


class PrivateLifecycleRoute(APIRoute):
    """Private resume/cancel have no body overrides; fork has no private variant."""
    def get_route_handler(self):
        ordinary = super().get_route_handler()

        async def handle(request: Request):
            execution_id = request.path_params.get("execution_id")
            if not execution_id or not await run_in_threadpool(private_run_requested, execution_id):
                return await _ordinary_without_reflection(ordinary, request)
            with metadata_only_logs():
                try:
                    caller_boundary(get_private_boundary())
                    raw = await request.body()
                    if raw:
                        from temper_ai.private_context.private_json import decode_object

                        await read_private_json(request)
                        if decode_object(raw) != {}:
                            raise PrivateDraftFailure(Code.SCOPE_DENIED)
                    from temper_ai.api.routes import cancel_run, resume_run

                    action = cancel_run if request.url.path.endswith("/cancel") else resume_run
                    result = await run_in_threadpool(action, execution_id, None)
                    body = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
                    return JSONResponse(body, headers=private_headers())
                except PrivateDraftFailure as exc:
                    return private_failure(exc.code)
                except Exception:
                    return private_failure(Code.CONTEXT_UNAVAILABLE)

        return handle


class PrivateForkRoute(APIRoute):
    def get_route_handler(self):
        ordinary = super().get_route_handler()

        async def handle(request: Request):
            raw = await request.body()
            try:
                envelope = json.loads(raw)
            except (ValueError, UnicodeError, RecursionError):
                if b"private_context" in raw:
                    return private_failure(Code.CONTEXT_INVALID)
                return await _ordinary_without_reflection(ordinary, request)
            if isinstance(envelope, dict):
                source = envelope.get("source_execution_id")
                marked = private_start_requested(envelope.get("workflow"), envelope.get("inputs"))
                private_source = type(source) is str and await run_in_threadpool(private_run_requested, source)
                if marked or private_source:
                    # Existing private bindings never fork, even before reservation.
                    return private_failure(Code.SCOPE_DENIED)
            return await _ordinary_without_reflection(ordinary, request)

        return handle
