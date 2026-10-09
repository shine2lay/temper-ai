"""One folder per commit, with a page anybody can read.

The commit status on GitHub carries a link, and the link has to lead
somewhere that still makes sense in a week: what was checked, what each
check proved, how long it took, what the screenshots looked like, and —
when it failed — the reason, in the first screenful. Once the commit has gone
live, the page also says what the deploy's live check found.

Since 2026-10-08 the gate builds nothing (one live temper only, no test copy
of it), so a new commit's page says it was recorded, and the deploy's live
check is what it shows. Pages of older commits keep their box checks.
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
.owed{background:#fff8c5;color:#7d4e00}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;
 box-shadow:0 1px 3px rgba(0,0,0,.08)}
th,td{text-align:left;padding:10px 14px;border-bottom:1px solid #eaeef2;vertical-align:top}
th{background:#f6f8fa;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#57606a}
tr:last-child td{border-bottom:none}
.ok{color:#1a7f37;font-weight:600}.no{color:#cf222e;font-weight:600}
.soft{color:#9a6700;font-weight:600}.info{color:#57606a;font-weight:600}
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


# Said under an information-only part of the live check, on the page.
INFO_ONLY = ("Information only: it never fails the live check, so it never reverts a deploy "
             "or holds up a landing.")


def mark(part: dict) -> str:
    """How a part of the live check reads, on the page and in ``temper-ci status``.

    A part that counts passes or fails. An information-only one (``"info": true``: the Pi
    pins) never counts, so it says so: "FAIL (doesn't block)" when it found something wrong
    or couldn't run, and a plain "info" when there is nothing to check yet (not set up).
    A part that stepped aside for someone else's run reads "owed": not tried yet, so
    neither passed nor failed; temper-ci tries it again once no run is going, and until it
    passes the commit is not recorded as good (live_checks.py, deploy.settle_owed).
    """
    if part.get("owed"):
        return "owed"
    if part.get("ok"):
        return "ok"
    if not part.get("info"):
        return "FAIL"
    return "info" if part.get("result") == "not_set_up" else "FAIL (doesn't block)"


def write(sha: str, verdict: dict) -> Path:
    """Write ``report.json`` and ``index.html`` for one commit's check."""
    d = folder(sha)
    (d / "report.json").write_text(json.dumps(verdict, indent=2, sort_keys=True), encoding="utf-8")
    return _page(sha, verdict)


def write_live(sha: str, deploy: dict) -> Path:
    """Put a deploy's live check on the commit's page, beside its machine check.

    It is kept in ``live.json``, so the page shows it again whenever it is written over.
    """
    d = folder(sha)
    (d / "live.json").write_text(json.dumps(deploy, indent=2, sort_keys=True), encoding="utf-8")
    verdict = paths.read_json(d / "report.json")
    return _page(sha, verdict if isinstance(verdict, dict) else {})


def _live_html(deploy: object) -> str:
    """The deploy's live check: what came of it, then each part with its mark."""
    if not isinstance(deploy, dict) or not isinstance(deploy.get("live"), dict):
        return ""
    live = deploy["live"]
    parts = [p for p in live.get("parts") or [] if isinstance(p, dict)]
    rows = []
    for p in parts:
        label = mark(p)
        css = {"ok": "ok", "FAIL": "no", "info": "info"}.get(label, "soft")
        detail = html.escape(str(p.get("detail") or ""))
        rows.append(
            f"<tr><td><span class={css}>{html.escape(label)}</span></td>"
            f"<td><b>{html.escape(str(p.get('name')))}</b>"
            f"{f'<div class=what>{html.escape(INFO_ONLY)}</div>' if p.get('info') else ''}"
            f"{f'<div class=detail>{detail}</div>' if detail else ''}</td></tr>"
        )
    ok = bool(deploy.get("ok"))
    owed = [str(p.get("name")) for p in parts if mark(p) == "owed"]
    bad = "; ".join(str(p.get("name")) for p in parts if mark(p) == "FAIL")
    tone = "pass" if ok else "owed" if owed and not bad else "fail"
    if ok:
        said = "Live and well: every part of the live check that counts passed."
    elif tone == "owed":
        said = (f"Live, but not yet recorded as good. Owed, because someone else's run was "
                f"going: {'; '.join(owed)}. temper-ci tries them again once no run is going; "
                "nothing has failed.")
    else:
        said = f"The live check failed: {bad or 'see below'}."
        back = deploy.get("rollback")
        if isinstance(back, dict):
            said += (f" master went back to the files of {str(back.get('good') or '')[:12]}."
                     if back.get("ok") else
                     f" The revert did not go through: {back.get('detail') or 'see the log'}.")
        elif deploy.get("rolled_back") is False:
            said += (f" Nothing was rolled back: "
                     f"{deploy.get('reason') or 'there was no earlier good commit to go back to'}.")
    table = ("<table><tr><th></th><th>live check</th></tr>" + "".join(rows) + "</table>"
             if rows else "")
    return (f"<h2>After it went live</h2>\n"
            f"<div class=sub>checked {html.escape(str(live.get('at') or ''))}"
            f" · {html.escape(str(live.get('api') or ''))}</div>\n"
            f"<div class=\"verdict {tone}\">{html.escape(said)}</div>\n"
            f"{table}")


def _page(sha: str, verdict: dict) -> Path:
    """``index.html``: the machine check, then the live check once there has been one."""
    d = folder(sha)
    live_html = _live_html(paths.read_json(d / "live.json"))
    if not verdict:
        # Gone live with no machine check on record here: say that, not "Something failed."
        page = d / "index.html"
        page.write_text(
            f"<!doctype html><meta charset=utf-8>\n<title>temper/boxes — {sha[:12]}</title>"
            f"<style>{STYLE}</style>\n<div class=wrap>\n"
            f"<h1>temper/boxes — <code>{sha[:12]}</code></h1>\n"
            "<div class=sub>This machine has no machine check on record for this commit.</div>\n"
            f"{live_html}\n</div>", encoding="utf-8")
        return page

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
    if not ok:
        said = html.escape(str(verdict.get("reason") or "Something failed."))
    elif skipped and not checks:
        said = "Recorded and passed at once: nothing was run here."
    else:
        said = "Everything the machine check runs passed."
    # Only a commit from the days of the throwaway temper has a stack to describe.
    stack_html = f"""<h2>The stack it ran in</h2>
<table>
<tr><td>compose project</td><td><code>{html.escape(str(verdict.get('project') or ''))}</code></td></tr>
<tr><td>its own ports</td><td><code>{html.escape(str(verdict.get('ports') or ''))}</code></td></tr>
<tr><td>images built</td><td><code>{html.escape(json.dumps(verdict.get('built') or {}))}</code></td></tr>
<tr><td>model keys</td><td>none — every agent it runs is a script, so the check costs $0</td></tr>
<tr><td>live temper</td><td>{html.escape(str(verdict.get('isolation') or 'not compared'))}</td></tr>
</table>""" if verdict.get("project") else ""
    body = f"""<!doctype html><meta charset=utf-8>
<title>temper/boxes — {sha[:12]}</title><style>{STYLE}</style>
<div class=wrap>
<h1>temper/boxes — <code>{sha[:12]}</code></h1>
<div class=sub>{html.escape(str(verdict.get('subject') or ''))}<br>
{html.escape(str(verdict.get('branch') or ''))} · checked {html.escape(str(verdict.get('finished_at') or stamp()))}
 · {verdict.get('seconds', 0):.0f}s total</div>
<div class="verdict {'pass' if ok else 'fail'}">
{said}
</div>
{f"<p>{html.escape(skipped)}</p>" if skipped else ""}
{f"<table><tr><th></th><th>check</th><th>took</th></tr>{''.join(rows)}</table>" if rows else ""}
{live_html}
{f"<h2>What the page looked like</h2>{shot_html}" if shots else ""}
{stack_html}
</div>"""
    page = d / "index.html"
    page.write_text(body, encoding="utf-8")
    return page
