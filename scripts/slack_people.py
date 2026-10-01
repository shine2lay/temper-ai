"""Who is in the Slack workspace: ids and names, for configs/slack/local/access.yaml.

    uv run python scripts/slack_people.py            # everyone who is not a bot
    uv run python scripts/slack_people.py lomit      # only those whose name matches

Reads SLACK_BOT_TOKEN from .env. The bot needs users:read, which it has.
"""

from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def token() -> str:
    tok = os.environ.get("SLACK_BOT_TOKEN")
    if tok:
        return tok
    for line in (Path(__file__).resolve().parents[1] / ".env").read_text().splitlines():
        if line.startswith("SLACK_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("no SLACK_BOT_TOKEN")


def people() -> list[dict]:
    out, cursor = [], ""
    while True:
        query = urllib.parse.urlencode({"limit": 200, **({"cursor": cursor} if cursor else {})})
        req = urllib.request.Request(f"https://slack.com/api/users.list?{query}",
                                     headers={"Authorization": f"Bearer {token()}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = __import__("json").loads(resp.read())
        if not body.get("ok"):
            raise SystemExit(f"slack said: {body.get('error')}")
        out += body.get("members") or []
        cursor = (body.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            return out


def main() -> None:
    want = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    for m in people():
        if m.get("is_bot") or m.get("deleted") or m.get("id") == "USLACKBOT":
            continue
        profile = m.get("profile") or {}
        bits = [m.get("name", ""), profile.get("real_name", ""), profile.get("display_name", ""),
                profile.get("email", "")]
        if want and want not in " ".join(b.lower() for b in bits):
            continue
        print(f"{m['id']}  {m.get('name','')}  real={profile.get('real_name','')!r} "
              f"display={profile.get('display_name','')!r} email={profile.get('email','')!r}"
              f"{'  [owner]' if m.get('is_owner') else ''}")


if __name__ == "__main__":
    main()
