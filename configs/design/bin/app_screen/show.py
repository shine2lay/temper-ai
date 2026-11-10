"""Stage 7 (07-show/): self-contained Show&Tell bundle, showtell.json, comments.json, and deterministic check.

1. Validates upstream prerequisites loud and fast:
   - 05-build/index.html, 05-build/build.json, 05-build/fixture.json, and
     06-checks/round-<ws.round>/review.json must exist,
   - review.json must have verdict == "done" and 0 open Must findings.
2. Compiles a self-contained single-file interactive Show&Tell bundle 07-show/bundle.html
   (and 07-show/bundle-round-<ws.round>.html) by inlining 05-build/styles/tokens.css,
   05-build/fixture.json, 05-build/screens/*.js, and 05-build/shell/router.js into
   05-build/index.html with data-st-interactive="true" on <html> (note n131).
   Never shares externally or pings Telegram from inside a worker run (lead-only rule).
3. On ws.round > 1 when 07-show/bundle-round-<ws.round - 1>.html exists, computes
   non-blank line retention (kept_lines, prev_non_blank_lines, kept_ratio, change_note
   per bp-bc056d81).
4. Writes or updates 07-show/showtell.json and 07-show/comments.json. When ws.round > 1
   and 07-show/gate_final.json had choice == "changes" with comments: [1, ...], marks
   those targeted comments "answered" in 07-show/comments.json with a versioned reply
   (version = ws.round, outcome = "done").
5. Runs show_check.py (4 rules -> 07-show/check.json) and contracts.validate("show", ws).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from . import contracts
from .contracts import ContractError
from .show_check import assert_show_clean
from .workspace import Workspace

LINK_RE = re.compile(
    r'<link\b[^>]*\bhref=["\'](?P<href>[^"\']+)["\'][^>]*>',
    re.IGNORECASE,
)
SCRIPT_SRC_RE = re.compile(
    r'<script\b[^>]*\bsrc=["\'](?P<src>[^"\']+)["\'][^>]*>\s*</script>',
    re.IGNORECASE,
)
HTML_OPEN_RE = re.compile(r"<html\b(?P<attrs>[^>]*)>", re.IGNORECASE)
TITLE_RE = re.compile(r"<title>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
DOC_ID_RE = re.compile(r"^d_[a-z0-9]{6,20}$")


def default_doc_id(product: str = "app", run_id: str = "run") -> str:
    """Return a deterministic Show&Tell doc_id matching ^d_[a-z0-9]{6,20}$."""
    p_clean = re.sub(r"[^a-z0-9]+", "", str(product or "app").lower())[:6] or "app"
    digest = hashlib.sha256(f"{product}:{run_id}".encode()).hexdigest()[:8]
    return f"d_{p_clean}{digest}"


def default_comment_id(doc_id: str, number: int, version: int = 1) -> str:
    """Return a deterministic comment id c_<number>."""
    _ = (doc_id, version)
    return f"c_{number}"


def _default_doc_id(ws: Workspace) -> str:
    product = "app"
    run_id = "run"
    if ws.run_file.is_file():
        meta = ws.run()
        product = str(meta.get("product") or "app")
        run_id = str(meta.get("run_id") or ws.path.name or "run")
    return default_doc_id(product, run_id)


def _normalize_doc_id(raw: str | None, ws: Workspace) -> str:
    if not raw:
        return _default_doc_id(ws)
    s = str(raw).strip().lower()
    if DOC_ID_RE.match(s):
        return s
    body = re.sub(r"[^a-z0-9]+", "", s[2:] if s.startswith("d_") else s)
    if len(body) < 6:
        body = (body + hashlib.sha256(s.encode("utf-8")).hexdigest())[:10]
    elif len(body) > 20:
        body = body[:12] + hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]
    return f"d_{body}"


def _normalize_comment_entry(raw: dict[str, Any], idx: int, default_ver: int, doc_id: str) -> dict[str, Any]:
    num = raw.get("number")
    if not isinstance(num, int) or isinstance(num, bool) or num < 1:
        cid_raw = str(raw.get("id") or "")
        m = re.search(r"(\d+)$", cid_raw)
        num = int(m.group(1)) if m else idx

    ver = raw.get("version")
    if not isinstance(ver, int) or isinstance(ver, bool) or ver < 1:
        ver = default_ver

    body = str(raw.get("body") or raw.get("text") or f"Comment {num}").strip()
    element = str(raw.get("element") or raw.get("place") or "prototype")
    state = str(raw.get("state") or "open")
    if state not in ("open", "answered"):
        state = "open"

    cid = str(raw.get("id") or default_comment_id(doc_id, num, ver))
    replies_in = raw.get("replies")
    replies: list[dict[str, Any]] = []
    if isinstance(replies_in, list):
        for r in replies_in:
            if isinstance(r, dict):
                replies.append({
                    "outcome": str(r.get("outcome") or "done"),
                    "version": r.get("version") if isinstance(r.get("version"), int) else default_ver,
                    "body": str(r.get("body") or r.get("text") or "Addressed"),
                })
    elif state == "answered" and (raw.get("reply") or raw.get("outcome")):
        replies.append({
            "outcome": str(raw.get("outcome") or "done"),
            "version": ver,
            "body": str(raw.get("reply") or "Addressed"),
        })

    out: dict[str, Any] = {
        "id": cid,
        "number": num,
        "version": ver,
        "body": body,
        "element": element,
        "state": state,
    }
    if replies:
        out["replies"] = replies
    return out


def validate_prerequisites(ws: Workspace) -> dict[str, Any]:
    """Fail loud and fast if Stage 5 build or Stage 6b review outputs are missing or not done."""
    ws = ws if ws.step else ws.for_step("show")
    round_num = max(1, ws.round) if ws.run_file.is_file() else 1
    build_dir = ws.folder("build")
    round_dir = ws.round_folder(round_num)

    problems: list[str] = []
    index_path = build_dir / "index.html"
    build_json_path = build_dir / "build.json"
    fixture_path = build_dir / "fixture.json"
    review_path = round_dir / "review.json"

    if not index_path.is_file():
        problems.append("05-build/index.html: missing Stage 5 prototype HTML")
    if not build_json_path.is_file():
        problems.append("05-build/build.json: missing Stage 5 build manifest")
    if not fixture_path.is_file():
        problems.append("05-build/fixture.json: missing Stage 5 fixture data")
    if not review_path.is_file():
        problems.append(f"06-checks/round-{round_num}/review.json: missing Stage 6b review record")

    if problems:
        raise ContractError("show: " + "; ".join(problems))

    try:
        build_doc = json.loads(ws.read_text(build_json_path))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"show: 05-build/build.json: invalid JSON ({exc})") from exc

    try:
        fixture_doc = json.loads(ws.read_text(fixture_path))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"show: 05-build/fixture.json: invalid JSON ({exc})") from exc

    try:
        review_doc = json.loads(ws.read_text(review_path))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"show: 06-checks/round-{round_num}/review.json: invalid JSON ({exc})") from exc

    if not isinstance(review_doc, dict) or review_doc.get("verdict") != "done":
        verdict = review_doc.get("verdict") if isinstance(review_doc, dict) else None
        raise ContractError(
            f"show: 06-checks/round-{round_num}/review.json: verdict must be 'done' before Stage 7 show (got {verdict!r})"
        )

    open_must = [
        f.get("id", "?")
        for f in (review_doc.get("findings") or [])
        if isinstance(f, dict)
        and f.get("priority") == "must"
        and f.get("status") not in ("fixed", "resolved")
    ]
    if open_must:
        raise ContractError(
            f"show: 06-checks/round-{round_num}/review.json: cannot proceed to Stage 7 show with open Must finding(s): "
            + ", ".join(str(x) for x in open_must)
        )

    return {
        "round": round_num,
        "build": build_doc,
        "fixture": fixture_doc,
        "review": review_doc,
    }


def _ensure_interactive_html_tag(html_text: str) -> str:
    def _sanitize_inner_tag(m: re.Match[str]) -> str:
        tag = m.group(1).lower()
        full = m.group(0)
        if tag in ("html", "body"):
            return full
        return re.sub(r"\bdata-(?:st-)?state(\s*=)", r"data-view-state\1", full, flags=re.IGNORECASE)

    html_text = re.sub(r"<([a-zA-Z][a-zA-Z0-9_-]*)\b[^>]*>", _sanitize_inner_tag, html_text)

    def _repl(match: re.Match[str]) -> str:
        attrs = match.group("attrs") or ""
        if "data-st-interactive" in attrs.lower():
            attrs = re.sub(
                r'\bdata-st-interactive(?:\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+))?',
                'data-st-interactive="true"',
                attrs,
                flags=re.IGNORECASE,
            )
            return f"<html{attrs}>"
        return f'<html{attrs} data-st-interactive="true">'

    if HTML_OPEN_RE.search(html_text):
        return HTML_OPEN_RE.sub(_repl, html_text, count=1)
    return '<html lang="en" data-st-interactive="true">\n' + html_text


def compile_bundle(ws: Workspace, round_num: int) -> Path:
    """Compile 05-build/* into a self-contained single-file 07-show/bundle.html."""
    ws = ws if ws.step else ws.for_step("show")
    build_dir = ws.folder("build")
    show_dir = ws.folder("show")
    show_dir.mkdir(parents=True, exist_ok=True)

    raw_html = ws.read_text(build_dir / "index.html")
    html_text = _ensure_interactive_html_tag(raw_html)

    def _inline_link(match: re.Match[str]) -> str:
        tag = match.group(0)
        if "stylesheet" not in tag.lower():
            return tag
        href = match.group("href").strip()
        css_path = (build_dir / href).resolve()
        if not css_path.is_file():
            raise ContractError(f"show: 05-build/index.html: missing referenced stylesheet {href!r}")
        css_text = ws.read_text(css_path)
        return f'<style data-inlined-href="{href}">\n{css_text}\n</style>'

    html_text = LINK_RE.sub(_inline_link, html_text)

    def _inline_script(match: re.Match[str]) -> str:
        src = match.group("src").strip()
        js_path = (build_dir / src).resolve()
        if not js_path.is_file():
            raise ContractError(f"show: 05-build/index.html: missing referenced script {src!r}")
        js_text = ws.read_text(js_path)
        return f'<script data-inlined-src="{src}">\n{js_text}\n</script>'

    html_text = SCRIPT_SRC_RE.sub(_inline_script, html_text)

    if 'id="rc-fixture-data"' not in html_text and "id='rc-fixture-data'" not in html_text:
        fixture_raw = ws.read_text(build_dir / "fixture.json").strip()
        fixture_block = f'<script id="rc-fixture-data" type="application/json">\n{fixture_raw}\n</script>\n'
        if "</body>" in html_text:
            html_text = html_text.replace("</body>", fixture_block + "</body>", 1)
        else:
            html_text += "\n" + fixture_block

    bundle_path = show_dir / "bundle.html"
    round_bundle_path = show_dir / f"bundle-round-{round_num}.html"
    bundle_path.write_text(html_text, encoding="utf-8")
    round_bundle_path.write_text(html_text, encoding="utf-8")
    return bundle_path


def compute_line_retention(prev_text: str, curr_text: str) -> dict[str, Any]:
    """Compute non-blank line retention between previous and current Show&Tell bundles (bp-bc056d81)."""
    prev_lines = [line.strip() for line in prev_text.splitlines() if line.strip()]
    curr_lines = [line.strip() for line in curr_text.splitlines() if line.strip()]
    prev_total = len(prev_lines)
    curr_total = len(curr_lines)
    if prev_total == 0:
        return {
            "kept_lines": 0,
            "prev_non_blank_lines": 0,
            "curr_non_blank_lines": curr_total,
            "kept_ratio": 1.0,
        }
    prev_counts = Counter(prev_lines)
    curr_counts = Counter(curr_lines)
    kept = sum(min(count, curr_counts.get(line, 0)) for line, count in prev_counts.items())
    ratio = round(kept / prev_total, 4)
    return {
        "kept_lines": kept,
        "prev_non_blank_lines": prev_total,
        "curr_non_blank_lines": curr_total,
        "kept_ratio": ratio,
    }


def _default_title(ws: Workspace) -> str:
    ws_step = ws if ws.step else ws.for_step("show")
    req_path = ws_step.folder("intake") / "requirements.json"
    if req_path.is_file():
        try:
            req_doc = json.loads(ws_step.read_text(req_path))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"cannot read {req_path}: {exc}") from exc
        prod = str(req_doc.get("product") or "").strip()
        items = req_doc.get("items") or []
        if prod and items and isinstance(items[0], dict):
            means = str(items[0].get("means") or items[0].get("owner_words") or "").strip()
            if means:
                return f"{prod} — {means[:80]}"
        if prod:
            return f"{prod} prototype"

    index_path = ws_step.folder("build") / "index.html"
    if index_path.is_file():
        m = TITLE_RE.search(ws_step.read_text(index_path))
        if m and m.group("title").strip():
            return m.group("title").strip()

    return "App-screen interactive prototype"


def prep_show(
    ws: Workspace,
    *,
    doc_id: str | None = None,
    title: str | None = None,
    comments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Host command helper so the lead can seed 07-show/showtell.json and 07-show/comments.json."""
    ws = ws if ws.step else ws.for_step("show")
    show_dir = ws.folder("show")
    show_dir.mkdir(parents=True, exist_ok=True)
    round_num = max(1, ws.round) if ws.run_file.is_file() else 1

    st_path = show_dir / "showtell.json"
    cm_path = show_dir / "comments.json"

    existing_st: dict[str, Any] = {}
    if st_path.is_file():
        try:
            existing_st = json.loads(ws.read_text(st_path))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"cannot read {st_path}: {exc}") from exc

    existing_cm: dict[str, Any] = {}
    if cm_path.is_file():
        try:
            existing_cm = json.loads(ws.read_text(cm_path))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"cannot read {cm_path}: {exc}") from exc

    resolved_doc_id = _normalize_doc_id(doc_id or existing_st.get("doc_id"), ws)
    resolved_title = str(title or existing_st.get("title") or _default_title(ws)).strip()
    showtell_doc: dict[str, Any] = {
        **existing_st,
        "doc_id": resolved_doc_id,
        "version": int(existing_st.get("version") or round_num),
        "url": f"/showtell/#/d/{resolved_doc_id}",
        "title": resolved_title,
    }

    raw_comments: list[Any]
    if comments is not None:
        raw_comments = comments
    elif isinstance(existing_cm.get("comments"), list):
        raw_comments = existing_cm["comments"]
    else:
        raw_comments = []

    normalized_comments = [
        _normalize_comment_entry(c, idx, round_num, resolved_doc_id)
        for idx, c in enumerate(raw_comments, start=1)
        if isinstance(c, dict)
    ]

    comments_doc = {
        "doc_id": resolved_doc_id,
        "comments": normalized_comments,
    }

    st_path.write_text(
        json.dumps(showtell_doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    cm_path.write_text(
        json.dumps(comments_doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {"showtell": showtell_doc, "comments": comments_doc}


def _resolve_targeted_comments_on_rerun(
    ws: Workspace,
    round_num: int,
    doc_id: str,
    comments_list: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """When round > 1 and prior gate_final had choice == 'changes', mark targeted comments answered."""
    if round_num <= 1:
        return comments_list, []

    show_dir = ws.folder("show")
    prev_gate_archive = show_dir / f"gate_final-round-{round_num - 1}.json"
    gate_path = prev_gate_archive if prev_gate_archive.is_file() else (show_dir / "gate_final.json")
    if not gate_path.is_file():
        return comments_list, []

    ws_step = ws if ws.step else ws.for_step("show")
    try:
        gate_doc = json.loads(ws_step.read_text(gate_path))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {gate_path}: {exc}") from exc

    if isinstance(gate_doc, dict) and gate_doc.get("choice") == "changes" and not prev_gate_archive.is_file():
        prev_gate_archive.write_text(
            json.dumps(gate_doc, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    if not isinstance(gate_doc, dict) or gate_doc.get("choice") != "changes":
        return comments_list, []

    raw_targets = gate_doc.get("comments") or []
    if not isinstance(raw_targets, list) or not raw_targets:
        return comments_list, []

    gate_note = str(
        gate_doc.get("owner_words") or gate_doc.get("reason") or "Targeted revision requested at final gate"
    ).strip()

    updated = [
        _normalize_comment_entry(c, idx, max(1, round_num - 1), doc_id)
        for idx, c in enumerate(comments_list, start=1)
        if isinstance(c, dict)
    ]
    by_number: dict[int, dict[str, Any]] = {int(c["number"]): c for c in updated}
    by_id: dict[str, dict[str, Any]] = {str(c["id"]): c for c in updated}

    answered_ids: list[str] = []
    for raw_t in raw_targets:
        num: int | None = None
        if isinstance(raw_t, int) and not isinstance(raw_t, bool):
            num = raw_t
        else:
            s = str(raw_t).strip()
            if s.isdigit():
                num = int(s)
            else:
                m = re.search(r"(\d+)$", s)
                if m:
                    num = int(m.group(1))

        entry = by_number.get(num) if num is not None else by_id.get(str(raw_t))
        if entry is None:
            new_num = num if num is not None else (max(by_number.keys(), default=0) + 1)
            entry = {
                "id": default_comment_id(doc_id, new_num, max(1, round_num - 1)),
                "number": new_num,
                "version": max(1, round_num - 1),
                "body": gate_note or f"Targeted comment #{new_num}",
                "element": "prototype",
                "state": "open",
            }
            updated.append(entry)
            by_number[new_num] = entry
            by_id[str(entry["id"])] = entry

        entry["state"] = "answered"
        replies = list(entry.get("replies") or [])
        reply_body = (
            f"Addressed in Round {round_num} targeted prototype update (v{round_num}): "
            f"{entry.get('body') or gate_note}"
        )
        replies = [r for r in replies if not (isinstance(r, dict) and r.get("version") == round_num)]
        replies.append({
            "outcome": "done",
            "version": round_num,
            "body": reply_body,
        })
        entry["replies"] = replies
        answered_ids.append(str(entry["id"]))

    return updated, answered_ids


def run(ws: Workspace, _raw: str = "") -> dict[str, Any]:
    ws = ws.for_step("show")
    prereq = validate_prerequisites(ws)
    round_num: int = prereq["round"]
    show_dir = ws.folder("show")
    show_dir.mkdir(parents=True, exist_ok=True)

    bundle_path = compile_bundle(ws, round_num)
    curr_bundle_text = ws.read_text(bundle_path)

    retention: dict[str, Any] | None = None
    prev_bundle_path = show_dir / f"bundle-round-{round_num - 1}.html"
    if round_num > 1 and prev_bundle_path.is_file():
        prev_bundle_text = ws.read_text(prev_bundle_path)
        retention = compute_line_retention(prev_bundle_text, curr_bundle_text)

    seeded = prep_show(ws)
    showtell_doc = dict(seeded["showtell"])
    comments_doc = dict(seeded["comments"])
    doc_id = str(showtell_doc["doc_id"])

    updated_comments, answered_ids = _resolve_targeted_comments_on_rerun(
        ws,
        round_num,
        doc_id,
        list(comments_doc.get("comments") or []),
    )
    comments_doc["comments"] = updated_comments

    showtell_doc["version"] = round_num
    showtell_doc["url"] = f"/showtell/#/d/{doc_id}"
    showtell_doc["bundle"] = "07-show/bundle.html"
    if retention is not None:
        kept = retention["kept_lines"]
        prev_total = retention["prev_non_blank_lines"]
        ratio_pct = round(retention["kept_ratio"] * 100, 1)
        answered_suffix = (
            f"; answered targeted comment(s) {', '.join(answered_ids)}" if answered_ids else ""
        )
        showtell_doc["kept_lines"] = kept
        showtell_doc["prev_non_blank_lines"] = prev_total
        showtell_doc["kept_ratio"] = retention["kept_ratio"]
        showtell_doc["change_note"] = (
            f"Round {round_num} targeted edit: {kept}/{prev_total} ({ratio_pct}%) "
            f"non-blank lines kept vs previous version v{round_num - 1}{answered_suffix}."
        )

    (show_dir / "showtell.json").write_text(
        json.dumps(showtell_doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (show_dir / "comments.json").write_text(
        json.dumps(comments_doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    check_report = assert_show_clean(ws)
    contracts.validate("show", ws)

    return {
        "status": "ok",
        "stage": "show",
        "round": round_num,
        "doc_id": doc_id,
        "version": showtell_doc["version"],
        "bundle": "07-show/bundle.html",
        "answered_comments": answered_ids,
        "check_passed": check_report["passed"],
    }
