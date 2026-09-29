"""One folder per commit, with a page anybody can read.

The commit status on GitHub carries a link, and the link has to lead
somewhere that still makes sense in a week: what was checked, what each
check proved, how long it took, what the screenshots looked like, and —
when it failed — the reason, in the first screenful.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from . import paths
from .paths import REPORTS, stamp

STYLE = """
body{font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#1b1f24}
.wrap{max-width:900px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:21px;margin:0 0 4px}
.sub{color:#57606a;font-size:13px;margin-bottom:22px}
.verdict{padding:12px 16px;border-radius:8px;font-weight:600;margin-bottom:22px}
.pass{background:#dafbe1;color:#0a5227}.fail{background:#ffebe9;color:#82071e}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;
 box-shadow:0 1px 3px rgba(0,0,0,.08)}
th,td{text-align:left;padding:10px 14px;border-bottom:1px solid #eaeef2;vertical-align:top}
th{background:#f6f8fa;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#57606a}
tr:last-child td{border-bottom:none}
.ok{color:#1a7f37;font-weight:600}.no{color:#cf222e;font-weight:600}
.what{color:#57606a;font-size:13px}
.detail{font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:#24292f;white-space:pre-wrap;
 margin-top:4px}
img{max-width:100%;border:1px solid #d0d7de;border-radius:6px;margin:10px 0}
h2{font-size:16px;margin:30px 0 10px}
code{background:#eff1f3;padding:1px 5px;border-radius:4px;font-size:12.5px}
"""


def folder(sha: str) -> Path:
    d = REPORTS / sha[:12]
    d.mkdir(parents=True, exist_ok=True)
    return d


def url(sha: str) -> str:
    return f"{paths.REPORT_BASE}/{sha[:12]}/"


def write(sha: str, verdict: dict) -> Path:
    """Write ``report.json`` and ``index.html`` for one commit's check."""
    d = folder(sha)
    (d / "report.json").write_text(json.dumps(verdict, indent=2, sort_keys=True), encoding="utf-8")

    ok = bool(verdict.get("ok"))
    checks = verdict.get("checks") or []
    rows = []
    for c in checks:
        mark = '<span class="ok">passed</span>' if c.get("ok") else '<span class="no">failed</span>'
        detail = html.escape(str(c.get("detail") or ""))
        rows.append(
            f"<tr><td>{mark}</td><td><b>{html.escape(str(c.get('name')))}</b>"
            f"<div class='what'>{html.escape(str(c.get('what') or ''))}</div>"
            f"{f'<div class=detail>{detail}</div>' if detail else ''}</td>"
            f"<td>{c.get('seconds', 0):.0f}s</td></tr>"
        )

    shots = sorted(p.name for p in d.glob("*.png"))
    shot_html = "".join(
        f"<h3 style='font-size:13px;color:#57606a;margin:16px 0 2px'>{html.escape(s)}</h3>"
        f"<img src='{html.escape(s)}' alt='{html.escape(s)}'>" for s in shots
    )

    skipped = verdict.get("skipped") or ""
    body = f"""<!doctype html><meta charset=utf-8>
<title>temper/boxes — {sha[:12]}</title><style>{STYLE}</style>
<div class=wrap>
<h1>temper/boxes — <code>{sha[:12]}</code></h1>
<div class=sub>{html.escape(str(verdict.get('subject') or ''))}<br>
{html.escape(str(verdict.get('branch') or ''))} · checked {html.escape(str(verdict.get('finished_at') or stamp()))}
 · {verdict.get('seconds', 0):.0f}s total</div>
<div class="verdict {'pass' if ok else 'fail'}">
{'Everything the machine check runs passed.' if ok else html.escape(str(verdict.get('reason') or 'Something failed.'))}
</div>
{f"<p>{html.escape(skipped)}</p>" if skipped else ""}
{f"<table><tr><th></th><th>check</th><th>took</th></tr>{''.join(rows)}</table>" if rows else ""}
{f"<h2>What the page looked like</h2>{shot_html}" if shots else ""}
<h2>The stack it ran in</h2>
<table>
<tr><td>compose project</td><td><code>{html.escape(str(verdict.get('project') or ''))}</code></td></tr>
<tr><td>its own ports</td><td><code>{html.escape(str(verdict.get('ports') or ''))}</code></td></tr>
<tr><td>images built</td><td><code>{html.escape(json.dumps(verdict.get('built') or {}))}</code></td></tr>
<tr><td>model keys</td><td>none — every agent it runs is a script, so the check costs $0</td></tr>
<tr><td>live temper</td><td>{html.escape(str(verdict.get('isolation') or 'not compared'))}</td></tr>
</table>
</div>"""
    page = d / "index.html"
    page.write_text(body, encoding="utf-8")
    return page
