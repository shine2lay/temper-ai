"""Short-lived GitHub tokens for runs, from the one place that holds the app's key.

A run acts as temper's GitHub app (its comments, reviews and pull requests
show as ``<app>[bot]``), but its box never has the app's private key: a shell
there could read it (integrations.github.secret). Instead the run asks here,
and gets a token that works on one repository, for at most an hour:

    POST /api/github/token   {"repo": "owner/name"}  -> {"repo", "token", "expires_at"}
    GET  /api/github/repos                            -> {"repos": ["owner/name", ...]}

Only repositories the app is installed on get a token. These paths are not
public (the gateway passes only /api/hooks/...), and they sit behind the API
token like the rest of the API when one is set.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from temper_ai.api.caller import require_caller_may
from temper_ai.integrations.github.app import (
    GitHubAppError,
    NotInstalled,
    check_repo,
    server_app,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/github", tags=["github"])


class TokenRequest(BaseModel):
    repo: str


@router.post("/token")
def repo_token(body: TokenRequest) -> dict[str, Any]:
    """A token for one repository the app is installed on."""
    require_caller_may("github_token")
    try:
        repo = check_repo(body.repo)
    except GitHubAppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        token = server_app().token(repo)
    except NotInstalled as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitHubAppError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    logger.info("GitHub token handed out for %s", repo)
    return {
        "repo": repo,
        "token": token.value,
        "expires_at": datetime.fromtimestamp(token.expires_at, tz=UTC).isoformat(),
    }


@router.get("/repos")
def repos() -> dict[str, Any]:
    """Every repository the app is installed on."""
    try:
        return {"repos": sorted(server_app().installed_repos())}
    except GitHubAppError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
