"""Ask each pool token, one cheap call each, what its own quota looks like.

Run inside the server container so it sees the same env and the same Claude
Code identity shaper the agents use:

    docker exec -i temper-ai-server-1 /app/.venv/bin/python - < scripts/probe_tokens.py

Prints, per token: HTTP status, the account/organization Anthropic attributes
the call to, and every anthropic-ratelimit-* header. A token is only "spent"
if its own headers say so -- two tokens on the same account share one window,
which looks exactly like "all our tokens are limited" from the outside.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import httpx

sys.path.insert(0, "/app")
from local.providers.anthropic_oauth import ClaudeCodeIdentityShaper  # noqa: E402

SLOTS = ["CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_BACKUP"] + [
    f"CLAUDE_CODE_OAUTH_TOKEN_{i}" for i in range(2, 10)
]
MODEL = os.environ.get("PROBE_MODEL", "claude-opus-5")


def probe(name: str, token: str) -> None:
    shaper = ClaudeCodeIdentityShaper()
    body = shaper.shape({
        "model": MODEL,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
        "system": [],
    })
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        **shaper.client_headers(),
    }
    fingerprint = hashlib.md5(token.encode()).hexdigest()[:10]
    try:
        r = httpx.post("https://api.anthropic.com/v1/messages",
                       headers=headers, json=body, timeout=45.0)
    except Exception as exc:  # noqa: BLE001
        print(f"\n{name} ({fingerprint}): transport error {exc!r}")
        return

    print(f"\n{name} ({fingerprint}): HTTP {r.status_code}")
    limits = {k: v for k, v in r.headers.items() if "ratelimit" in k.lower()}
    for k in sorted(limits):
        print(f"    {k}: {limits[k]}")
    for k in ("anthropic-organization-id", "request-id", "retry-after"):
        if k in r.headers:
            print(f"    {k}: {r.headers[k]}")
    if r.status_code != 200:
        try:
            err = r.json().get("error", {})
            print(f"    error: {err.get('type')}: {err.get('message')}")
        except (ValueError, json.JSONDecodeError):
            print(f"    body: {r.text[:200]}")


def main() -> None:
    seen: dict[str, str] = {}
    found = 0
    for name in SLOTS:
        token = (os.environ.get(name) or "").strip()
        if not token:
            continue
        found += 1
        fingerprint = hashlib.md5(token.encode()).hexdigest()[:10]
        if fingerprint in seen:
            print(f"\n{name}: the same token as {seen[fingerprint]} -- one window, not two")
            continue
        seen[fingerprint] = name
        probe(name, token)
    print(f"\n{found} token(s) configured, {len(seen)} distinct.")


main()
