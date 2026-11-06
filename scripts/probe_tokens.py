"""Ask each of pi's Claude slots temper uses, one cheap call each, what its own quota looks like.

Run inside the server container so it reaches temper-pi-host the way the agents do (the
pools door, TEMPER_PI_LOGINS_SOCKET) and sends the same Claude Code identity shaper:

    docker exec -i temper-ai-server-1 /app/.venv/bin/python - < scripts/probe_tokens.py

The slots are the ones configs/pools/pools.yaml lists (pools.logins.slots). Prints, per slot:
the login's fingerprint (sha256, 16 hex; never the login), HTTP status, the organization
Anthropic attributes the call to, and every anthropic-ratelimit-* header. A slot is only
"spent" if its own headers say so -- two slots signed in to the same account share one
window, which looks exactly like "all our accounts are limited" from the outside.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import httpx

sys.path.insert(0, "/app")
from local.providers.anthropic_oauth import ClaudeCodeIdentityShaper  # noqa: E402

from temper_ai.llm import pi_logins  # noqa: E402

MODEL = os.environ.get("PROBE_MODEL", "claude-opus-5")


def probe(slot: str, login: str, fingerprint: str) -> None:
    shaper = ClaudeCodeIdentityShaper()
    body = shaper.shape({
        "model": MODEL,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
        "system": [],
    })
    headers = {
        "Authorization": f"Bearer {login}",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        **shaper.client_headers(),
    }
    try:
        r = httpx.post("https://api.anthropic.com/v1/messages",
                       headers=headers, json=body, timeout=45.0)
    except Exception as exc:  # noqa: BLE001
        print(f"\n{slot} ({fingerprint}): transport error {type(exc).__name__}")
        return

    print(f"\n{slot} ({fingerprint}): HTTP {r.status_code}")
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
    slots = pi_logins.configured_slots()
    seen: dict[str, str] = {}
    for slot in slots:
        try:
            login = pi_logins.fetch(slot)
        except (pi_logins.PiLoginsUnreachable, pi_logins.PiLoginRefused) as exc:
            print(f"\n{slot}: no login from pi: {exc}")
            continue
        fingerprint = hashlib.sha256(login.encode()).hexdigest()[:16]
        if fingerprint in seen:
            print(f"\n{slot}: the same login as {seen[fingerprint]} -- one window, not two")
            continue
        seen[fingerprint] = slot
        probe(slot, login, fingerprint)
    print(f"\n{len(slots)} slot(s) configured, {len(seen)} distinct login(s).")


main()
