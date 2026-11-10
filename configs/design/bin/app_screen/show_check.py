"""Deterministic 4-rule checker for Stage 7 (07-show/) of design_app_screen_v1.

Rules:
1. review_done: 06-checks/round-<ws.round>/review.json exists, has verdict == "done", and has 0 open Must findings.
2. bundle_self_contained: 07-show/bundle.html exists, has data-st-interactive="true" on <html>, has no external stylesheet/script links, has no forbidden data-state/data-st-state attributes below html/body (note n131), and when round > 1 with a prior round bundle, records non-blank line retention (bp-bc056d81).
3. showtell_and_comments_match: 07-show/showtell.json and 07-show/comments.json exist, have matching doc_id (^d_[a-z0-9]{6,20}$), valid version == ws.round, valid /showtell/#/d/<doc_id> url, and valid comment schemas.
4. targeted_comments_answered: when ws.round > 1 and 07-show/gate_final.json requested changes for specific comment numbers/IDs, all targeted comments are marked state == "answered" with a reply for version == ws.round.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .contracts import ContractError
from .workspace import Workspace

RULE_NAMES: tuple[str, ...] = (
    "review_done",
    "bundle_self_contained",
    "showtell_and_comments_match",
    "targeted_comments_answered",
)

DOC_ID_RE = re.compile(r"^d_[a-z0-9]{6,20}$")
VALID_COMMENT_STATES = {"open", "answered"}
VALID_OUTCOMES = {"done", "changed_differently", "wont_do", "question"}


class _BundleHTMLInspector(HTMLParser):
    """Inspect 07-show/bundle.html for self-containment and n131 compliance."""

    def __init__(self) -> None:
        super().__init__()
        self.html_attrs: dict[str, str | None] = {}
        self.external_refs: list[str] = []
        self.forbidden_state_attrs: list[str] = []
        self.has_inline_style = False
        self.has_inline_script = False
        self.has_fixture_script = False
        self._in_style = False
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k.lower(): v for k, v in attrs}
        tag_l = tag.lower()
        if tag_l == "html":
            self.html_attrs = attr_map
        elif tag_l not in ("html", "body"):
            for forbidden in ("data-state", "data-st-state"):
                if forbidden in attr_map:
                    self.forbidden_state_attrs.append(f"<{tag_l} {forbidden}={attr_map[forbidden]!r}>")

        if tag_l == "link":
            rel = (attr_map.get("rel") or "").lower()
            href = (attr_map.get("href") or "").strip()
            if "stylesheet" in rel and href:
                self.external_refs.append(f"<link rel='stylesheet' href={href!r}>")
        elif tag_l == "script":
            src = (attr_map.get("src") or "").strip()
            if src:
                self.external_refs.append(f"<script src={src!r}>")
            else:
                self._in_script = True
                if attr_map.get("id") == "rc-fixture-data":
                    self.has_fixture_script = True
        elif tag_l == "style":
            self._in_style = True

    def handle_data(self, data: str) -> None:
        if self._in_style and data.strip():
            self.has_inline_style = True
        if self._in_script and data.strip():
            self.has_inline_script = True

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if tag_l == "style":
            self._in_style = False
        elif tag_l == "script":
            self._in_script = False


def _read_json(
    ws: Workspace,
    path: Path,
    problems: list[str],
    label: str,
    *,
    custom_error: str | None = None,
) -> dict[str, Any] | None:
    if not path.is_file():
        problems.append(custom_error or f"{label}: {path.name}: file is missing")
        return None
    ws_step = ws if ws.step else ws.for_step("show")
    try:
        doc = json.loads(ws_step.read_text(path))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(custom_error or f"{label}: {path.name}: invalid JSON ({exc})")
        return None
    if not isinstance(doc, dict):
        problems.append(custom_error or f"{label}: must be a JSON object")
        return None
    return doc


def _check_review_done(ws: Workspace, round_num: int) -> list[str]:
    problems: list[str] = []
    review_path = ws.round_folder(round_num) / "review.json"
    review_doc = _read_json(ws, review_path, problems, f"06-checks/round-{round_num}/review.json")
    if review_doc is None:
        return problems

    verdict = review_doc.get("verdict")
    if verdict != "done":
        problems.append(
            f"06-checks/round-{round_num}/review.json: verdict must be 'done' before Stage 7 show (got {verdict!r})"
        )

    findings = review_doc.get("findings")
    if isinstance(findings, list):
        open_must = [
            f.get("id", "?")
            for f in findings
            if isinstance(f, dict)
            and f.get("priority") == "must"
            and f.get("status") not in ("fixed", "resolved")
        ]
        if open_must:
            problems.append(
                f"06-checks/round-{round_num}/review.json: has {len(open_must)} open Must finding(s): {', '.join(str(x) for x in open_must)}"
            )
    return problems


def _check_bundle_self_contained(ws: Workspace, round_num: int) -> list[str]:
    ws_step = ws if ws.step else ws.for_step("show")
    problems: list[str] = []
    show_dir = ws_step.folder("show")
    bundle_path = show_dir / "bundle.html"
    if not bundle_path.is_file():
        problems.append("07-show/bundle.html: file is missing")
        return problems

    text = ws_step.read_text(bundle_path)
    if not text.strip():
        problems.append("07-show/bundle.html: file is empty")
        return problems

    inspector = _BundleHTMLInspector()
    try:
        inspector.feed(text)
    except Exception as exc:  # pragma: no cover
        problems.append(f"07-show/bundle.html: HTML parse error ({exc})")
        return problems

    if inspector.html_attrs.get("data-st-interactive") != "true":
        problems.append(
            '07-show/bundle.html: <html> tag is missing required data-st-interactive="true" attribute (note n131)'
        )

    if inspector.external_refs:
        problems.append(
            f"07-show/bundle.html: bundle is not self-contained; found external ref(s): {', '.join(inspector.external_refs)}"
        )

    if inspector.forbidden_state_attrs:
        problems.append(
            "07-show/bundle.html: found forbidden data-state/data-st-state attribute(s) below html/body (note n131): "
            + ", ".join(inspector.forbidden_state_attrs[:5])
        )

    if not inspector.has_inline_style:
        problems.append("07-show/bundle.html: missing inlined <style> block")
    if not inspector.has_inline_script:
        problems.append("07-show/bundle.html: missing inlined <script> block")
    if not inspector.has_fixture_script:
        problems.append('07-show/bundle.html: missing inlined <script id="rc-fixture-data"> block')

    if round_num > 1 and (show_dir / f"bundle-round-{round_num - 1}.html").is_file():
        showtell_doc = _read_json(
            ws_step,
            show_dir / "showtell.json",
            problems,
            "07-show/showtell.json",
            custom_error="07-show/showtell.json: missing or invalid for round > 1 retention check",
        )
        if showtell_doc is not None:
            change_note = str(showtell_doc.get("change_note") or "").strip()
            kept = showtell_doc.get("kept_lines")
            prev_total = showtell_doc.get("prev_non_blank_lines")
            if not change_note or "non-blank lines kept" not in change_note:
                problems.append(
                    "07-show/showtell.json: round > 1 change_note must state non-blank lines kept vs previous version (bp-bc056d81)"
                )
            if not isinstance(kept, int) or not isinstance(prev_total, int) or prev_total <= 0 or kept <= 0:
                problems.append(
                    f"07-show/showtell.json: round > 1 must record positive kept_lines and prev_non_blank_lines (got kept={kept!r}, prev={prev_total!r})"
                )

    return problems


def _check_showtell_and_comments_match(ws: Workspace, round_num: int) -> list[str]:
    problems: list[str] = []
    show_dir = ws.folder("show")
    showtell_doc = _read_json(ws, show_dir / "showtell.json", problems, "07-show/showtell.json")
    comments_doc = _read_json(ws, show_dir / "comments.json", problems, "07-show/comments.json")

    if problems or showtell_doc is None or comments_doc is None:
        return problems

    doc_id = str(showtell_doc.get("doc_id") or "")
    if not DOC_ID_RE.match(doc_id):
        problems.append(f"07-show/showtell.json: doc_id={doc_id!r} does not match ^d_[a-z0-9]{{6,20}}$")

    version = showtell_doc.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != round_num:
        problems.append(
            f"07-show/showtell.json: version={version!r} must be integer equal to current round {round_num}"
        )

    url = str(showtell_doc.get("url") or "")
    expected_url = f"/showtell/#/d/{doc_id}"
    if not doc_id or url != expected_url:
        problems.append(f"07-show/showtell.json: url={url!r} must equal {expected_url!r}")

    title = str(showtell_doc.get("title") or "").strip()
    if not title:
        problems.append("07-show/showtell.json: title must be non-empty")

    cm_doc_id = str(comments_doc.get("doc_id") or "")
    if cm_doc_id != doc_id:
        problems.append(
            f"07-show/comments.json: doc_id={cm_doc_id!r} does not match showtell.json doc_id={doc_id!r}"
        )

    comments_list = comments_doc.get("comments")
    if not isinstance(comments_list, list):
        problems.append("07-show/comments.json: comments must be a list")
        return problems

    for idx, c in enumerate(comments_list):
        if not isinstance(c, dict):
            problems.append(f"07-show/comments.json: comments[{idx}] must be an object")
            continue
        num = c.get("number")
        if not isinstance(num, int) or isinstance(num, bool) or num < 1:
            problems.append(f"07-show/comments.json: comments[{idx}].number={num!r} must be int >= 1")
        cver = c.get("version")
        if not isinstance(cver, int) or isinstance(cver, bool) or cver < 1:
            problems.append(f"07-show/comments.json: comments[{idx}].version={cver!r} must be int >= 1")
        state = c.get("state")
        if state not in VALID_COMMENT_STATES:
            problems.append(
                f"07-show/comments.json: comments[{idx}] state={state!r} must be in {sorted(VALID_COMMENT_STATES)}"
            )
        body = str(c.get("body") or "").strip()
        if not body:
            problems.append(f"07-show/comments.json: comments[{idx}] body must be non-empty")
        if not isinstance(c.get("element"), str):
            problems.append(f"07-show/comments.json: comments[{idx}] element must be a string")

        if state == "answered":
            replies = c.get("replies")
            if not isinstance(replies, list) or not replies:
                problems.append(
                    f"07-show/comments.json: comments[{idx}] (number={num}) state='answered' requires non-empty replies[]"
                )
            else:
                last_reply = replies[-1]
                if not isinstance(last_reply, dict):
                    problems.append(f"07-show/comments.json: comments[{idx}] reply must be an object")
                else:
                    outcome = last_reply.get("outcome")
                    if outcome not in VALID_OUTCOMES:
                        problems.append(
                            f"07-show/comments.json: comments[{idx}] reply outcome={outcome!r} must be in {sorted(VALID_OUTCOMES)}"
                        )
                    if not str(last_reply.get("body") or "").strip():
                        problems.append(f"07-show/comments.json: comments[{idx}] reply body must be non-empty")
                    rver = last_reply.get("version")
                    if not isinstance(rver, int) or isinstance(rver, bool) or rver < 1:
                        problems.append(f"07-show/comments.json: comments[{idx}] reply version={rver!r} must be int >= 1")

    return problems


def _target_number(raw: Any) -> int | None:
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    s = str(raw).strip()
    if s.isdigit():
        return int(s)
    m = re.search(r"(\d+)$", s)
    if m:
        return int(m.group(1))
    return None


def _check_targeted_comments_answered(ws: Workspace, round_num: int) -> list[str]:
    problems: list[str] = []
    if round_num <= 1:
        return problems

    show_dir = ws.folder("show")
    prev_gate_archive = show_dir / f"gate_final-round-{round_num - 1}.json"
    gate_path = prev_gate_archive if prev_gate_archive.is_file() else (show_dir / "gate_final.json")
    if not gate_path.is_file():
        return problems

    gate_doc = _read_json(ws, gate_path, problems, "07-show/gate_final.json")
    if gate_doc is None:
        return problems

    if gate_doc.get("choice") != "changes":
        return problems

    raw_targets = gate_doc.get("comments") or []
    if not isinstance(raw_targets, list) or not raw_targets:
        return problems

    comments_doc = _read_json(ws, show_dir / "comments.json", problems, "07-show/comments.json")
    if comments_doc is None:
        return problems

    comments_list = [c for c in (comments_doc.get("comments") or []) if isinstance(c, dict)]
    by_number: dict[int, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for idx, c in enumerate(comments_list, start=1):
        num = c.get("number") if isinstance(c.get("number"), int) else idx
        by_number[num] = c
        if isinstance(c.get("id"), str):
            by_id[c["id"]] = c

    for raw_t in raw_targets:
        num = _target_number(raw_t)
        c = by_number.get(num) if num is not None else by_id.get(str(raw_t))
        if c is None and isinstance(raw_t, str):
            c = by_id.get(raw_t)
        label = f"comment #{num}" if num is not None else f"comment {raw_t!r}"
        if c is None:
            problems.append(f"07-show/comments.json: targeted {label} from gate_final.json is missing")
            continue
        if c.get("state") != "answered":
            problems.append(
                f"07-show/comments.json: targeted {label} must have state='answered' in round {round_num} (got {c.get('state')!r})"
            )
        replies = c.get("replies")
        if not isinstance(replies, list) or not replies:
            problems.append(f"07-show/comments.json: targeted {label} is missing replies[] in round {round_num}")
        else:
            has_round_reply = any(
                isinstance(r, dict)
                and r.get("version") == round_num
                and str(r.get("body") or "").strip()
                and r.get("outcome") in VALID_OUTCOMES
                for r in replies
            )
            if not has_round_reply:
                problems.append(
                    f"07-show/comments.json: targeted {label} must have a valid reply with version={round_num}"
                )

    return problems


def check_show(ws: Workspace, *, write_report: bool = True) -> dict[str, Any]:
    """Run all 4 deterministic Stage 7 show rules and optionally write 07-show/check.json."""
    round_num = max(1, ws.round) if ws.run_file.is_file() else 1

    rule_checks = {
        "review_done": _check_review_done(ws, round_num),
        "bundle_self_contained": _check_bundle_self_contained(ws, round_num),
        "showtell_and_comments_match": _check_showtell_and_comments_match(ws, round_num),
        "targeted_comments_answered": _check_targeted_comments_answered(ws, round_num),
    }

    rules_report: dict[str, dict[str, Any]] = {}
    all_problems: list[str] = []
    for rule_name in RULE_NAMES:
        probs = rule_checks[rule_name]
        rules_report[rule_name] = {
            "passed": len(probs) == 0,
            "problems": probs,
        }
        for p in probs:
            all_problems.append(f"[{rule_name}] {p}")

    report = {
        "stage": "show",
        "round": round_num,
        "passed": len(all_problems) == 0,
        "rules": rules_report,
        "problems": all_problems,
    }

    if write_report:
        show_dir = ws.folder("show")
        show_dir.mkdir(parents=True, exist_ok=True)
        (show_dir / "check.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return report


def assert_show_clean(ws: Workspace) -> dict[str, Any]:
    """Run check_show(ws) and raise ContractError if any rule failed."""
    report = check_show(ws, write_report=True)
    if not report["passed"]:
        raise ContractError(f"show: {len(report['problems'])} problem(s): " + "; ".join(report["problems"]))
    return report
