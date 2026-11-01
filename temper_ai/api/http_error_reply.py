"""The API's reply to an HTTPException, with database values withheld from its detail.

Routes turn a caught error into ``HTTPException(detail=str(exc))`` or
``detail=f"...: {exc}"``, raised from that error or inside its except block.
When the error is a database error, or quotes one, its text would carry row
values back to the caller (shared/database_error_text.py). This handler gives
every string in the detail the safe text of each database error in the
HTTPException's chain, then answers as FastAPI's own handler does. A detail
with no database error behind it is answered unchanged. See
docs/database-error-text.md.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from temper_ai.shared.database_error_text import (
    carries_database_error,
    withhold_database_values_in_body,
)


async def http_error_without_database_values(request: Request, exc: Exception) -> Response:
    """The server's handler for every HTTPException (a more specific handler wins)."""
    assert isinstance(exc, StarletteHTTPException)
    if carries_database_error(exc):
        detail = withhold_database_values_in_body(exc.detail, exc)
        exc = HTTPException(exc.status_code, detail=detail, headers=exc.headers)
    return await http_exception_handler(request, exc)
