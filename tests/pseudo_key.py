"""The keyed pseudo-element pages' answer key, checked against a conversion (queue #103, hypothesis H9).

configs/design/testpages/pseudo-v1/expected.json says, for each ::before/::after on its pages, whether the
converter must draw it (and as what), must leave it alone (no visible paint), or can't draw it (and must
say so, failing the pseudo check). check() compares one page's key with a conversion report
(html_to_penpot.convert's conversion.json) and returns the mismatches; [] means the key holds.
Used by tests/test_converter_pseudo.py and by Design's live W13b runs.
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[1] / "configs/design/testpages/pseudo-v1"
PIXEL_BAR_PCT = 0.01


def key() -> dict:
    return json.loads((FIXTURE / "expected.json").read_text())


def words(text: str | None) -> str:
    return " ".join((text or "").split())


def check(page: dict, report: dict, widths=None) -> list[str]:
    """Mismatches between one page's key (key()["pages"][name]) and a conversion report."""
    problems: list[str] = []
    pseudo = report.get("pseudo") or {}
    verdict = (report.get("verify") or {}).get("pseudo") or {}
    widths = widths or key()["widths"]
    if verdict.get("passed") is not page["pseudo_check_passes"]:
        problems.append(f"pseudo check passed={verdict.get('passed')}, key says {page['pseudo_check_passes']}")
    for w in widths:
        records = [r for r in pseudo.get("records", []) if r.get("width") == w]
        named = {(i["host"], i["pseudo"]) for i in page["items"]}
        for r in records:
            if (r.get("id"), r.get("pseudo")) not in named:
                problems.append(f"{w}: {r.get('where')} {r.get('pseudo')} recorded but not in the key")
        for item in page["items"]:
            label = f"{w}: {item['host']} {item['pseudo']}"
            found = [r for r in records if r.get("id") == item["host"] and r.get("pseudo") == item["pseudo"]]
            if item["outcome"] == "none":
                if found:
                    problems.append(f"{label}: has no visible paint but was recorded ({found[0].get('kind')})")
                continue
            if len(found) != 1:
                problems.append(f"{label}: recorded {len(found)} times, expected once")
                continue
            r = found[0]
            if r.get("kind") != item["kind"]:
                problems.append(f"{label}: kind {r.get('kind')}, key says {item['kind']}")
            if item["outcome"] == "drawn":
                if not r.get("drawn") or r.get("not_drawn"):
                    problems.append(f"{label}: not drawn ({r.get('not_drawn')})")
                if "text" in item and words(r.get("text")) != words(item["text"]):
                    problems.append(f"{label}: text {r.get('text')!r}, key says {item['text']!r}")
            elif item["outcome"] == "not-drawn":
                if r.get("drawn") or r.get("not_drawn") != item["why"]:
                    problems.append(f"{label}: drawn={r.get('drawn')} not_drawn={r.get('not_drawn')}, key says not drawn ({item['why']})")
        counts = (verdict.get("per_width") or {}).get(str(w), {})
        for k, v in page["counts"].items():
            if counts.get(k) != v:
                problems.append(f"{w}: count {k} = {counts.get(k)}, key says {v}")
        if any(r.get("drawn") for r in records):
            guard = (pseudo.get("guards") or {}).get(str(w))
            if not isinstance(guard, dict) or not guard.get("same_size") or float(guard.get("pct", 100)) > PIXEL_BAR_PCT:
                problems.append(f"{w}: page pixels changed with the pseudo-elements drawn as elements: {guard}")
    return problems
