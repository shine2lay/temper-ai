#!/usr/bin/env python3
"""Photograph one page of the live temper, and say what was on it.

    python3 shot.py <url> <file.png> [--expect TEXT]...

A separate little program on purpose: Playwright's browser is heavy and
occasionally wedges, and a wedged browser must cost the check one screenshot,
not the whole machine.

It prints one line of JSON about what it saw. That matters more than the
picture: a screenshot on its own is a happy-looking green tick over whatever
the server felt like serving — the first version of this photographed
`{"detail":"Not Found"}` twice and called the dashboard fine. So the caller
says what the page must contain, and anything else is a failure with the
picture kept as the evidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    expect: list[str] = []
    while "--expect" in args:
        i = args.index("--expect")
        expect.append(args[i + 1])
        del args[i:i + 2]
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    url, out = args[0], Path(args[1])
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed on this machine", file=sys.stderr)
        return 3

    seen: dict[str, object] = {"url": url}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            # Console errors are worth having: a dashboard that renders its shell and then
            # dies on a bad API call looks perfectly fine in a picture.
            problems: list[str] = []
            page.on("pageerror", lambda e: problems.append(str(e)[:200]))
            response = page.goto(url, wait_until="networkidle", timeout=60_000)
            seen["status"] = response.status if response else 0
            # The run page fills in over the websocket; give it a moment to settle so the
            # picture shows the finished run rather than a spinner.
            page.wait_for_timeout(2_500)
            page.screenshot(path=str(out), full_page=True)
            body = page.inner_text("body", timeout=10_000) or ""
            seen["title"] = page.title()
            seen["chars"] = len(body)
            seen["errors"] = problems[:3]
            # Title as well as body: to a person looking at the tab, "Temper AI \u2014 smoke_test"
            # is the page telling them which run this is, and the dashboard puts some of what
            # it knows there rather than in the page.
            shown = f"{seen['title']}\n{body}"
            missing = [t for t in expect if t.lower() not in shown.lower()]
            seen["missing"] = missing
            # A page that is mostly empty is not a dashboard, whatever it says.
            if int(seen["status"]) >= 400:
                seen["why"] = f"the server answered {seen['status']}"
            elif missing:
                seen["why"] = f"the page never showed {missing}"
            elif len(body) < 40:
                seen["why"] = f"the page was all but empty ({len(body)} characters)"
            else:
                seen["why"] = ""
        finally:
            browser.close()

    print(json.dumps(seen))
    if not out.exists():
        return 4
    return 0 if not seen.get("why") else 5


if __name__ == "__main__":
    raise SystemExit(main())
