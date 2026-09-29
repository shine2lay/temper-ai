#!/usr/bin/env python3
"""Photograph one page of the throwaway temper.

    python3 shot.py <url> <file.png>

A separate little program on purpose: Playwright's browser is heavy and
occasionally wedges, and a wedged browser must cost us one screenshot, not
the whole machine check. The caller treats a non-zero exit as "no picture".
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    url, out = sys.argv[1], Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed on this machine", file=sys.stderr)
        return 3
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url, wait_until="networkidle", timeout=60_000)
            # The run page fills in over the websocket; give it a moment to
            # settle so the picture shows the finished run, not a spinner.
            page.wait_for_timeout(2_500)
            page.screenshot(path=str(out), full_page=True)
        finally:
            browser.close()
    return 0 if out.exists() else 4


if __name__ == "__main__":
    raise SystemExit(main())
