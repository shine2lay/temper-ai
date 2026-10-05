#!/usr/bin/env python3
"""Craft-critic benchmark steps (Design, queue #10): prepare one test page, then collect the verdict.

    design_craft_bench.py prepare --workspace W --site /app/configs/design/testpages/craft-v1 --page page-03
    design_craft_bench.py collect --workspace W

prepare copies one page of a craft test site into homepage/site (with its fonts), then writes what the
homepage workflow's craft critic reads, through the SAME code the measure stage uses
(design_homepage_v2.write_review_inputs): screenshots and facts, brief.md, craft-facts.md, concept.md.
The test pages have no category references, so review/references.md says so. The live critic then runs
unchanged (workflows/design_craft_bench.yaml), and collect checks and summarises review/craft/craft.json.

Which pages carry which planted problems is not in this repository: the answer key stays on the host,
where the findings are graded. No model here.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import design_homepage_v2 as v2  # noqa: E402

PAGE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
NO_REFERENCES = ("# References\n\nNone for this review: it is a benchmark page without category references.\n"
                 "Judge craft from the page, the brief, the direction and the measured facts; list reference\n"
                 "comparisons under not_checked.\n")


def manifest_for(site: Path) -> dict:
    path = site.parent / f"{site.name}.json"
    if not path.is_file():
        raise ValueError(f"no site manifest {path.name} next to {site}")
    data = json.loads(path.read_text())
    for key in ("pages", "page_product", "products", "font_dirs", "fonts_css"):
        if key not in data:
            raise ValueError(f"site manifest {path.name} lacks {key}")
    return data


def prepare(workspace: Path, site: Path, page: str) -> dict:
    if not PAGE.match(page):
        raise ValueError("page names are short lowercase names, e.g. page-03")
    data = manifest_for(site)
    if page not in data["pages"]:
        raise ValueError(f"{page} is not a page of {site.name}")
    product = data["products"][data["page_product"][page]]
    target = workspace / "homepage" / "site"
    review = workspace / "review"
    if target.exists() or review.exists():
        raise ValueError("this workspace already holds a benchmark page; use a fresh workspace per run")
    if (site / page / "fonts").is_dir():  # a page saved from a run carries its own fonts (concept pages, queue #34)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(site / page, target)
    else:
        target.mkdir(parents=True)
        shutil.copyfile(site / page / "index.html", target / "index.html")
        fonts = target / "fonts"
        fonts.mkdir()
        shutil.copyfile(site / data["fonts_css"], fonts / "fonts.css")
        for name in data["font_dirs"]:
            shutil.copytree(site.parent / "html-fixtures" / "fonts" / name, fonts / name)
    problems = v2.html_problems(target / "index.html")
    if problems:
        raise ValueError("test page breaks the page contract: " + "; ".join(problems))
    review.mkdir()
    metrics = v2.write_review_inputs(review, target, product["brief"], 1, product["concept"], "", None)
    (review / "references.md").write_text(NO_REFERENCES)
    record = {"site": site.name, "page": page, "product": product["brief"]["product"], "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "scale_ratio": {w: m.get("scale_ratio") for w, m in metrics.items()}}
    v2.save(workspace / "homepage" / "bench.json", record)
    return {"status": "completed", **record, "facts_path": "review/facts.md", "craft_facts": "review/craft-facts.md"}


def collect(workspace: Path) -> dict:
    bench = workspace / "homepage" / "bench.json"
    path = workspace / "review" / "craft" / "craft.json"
    if not bench.is_file():
        raise ValueError("no prepared benchmark page in this workspace")
    if not path.is_file():
        raise ValueError("the craft critic wrote no review/craft/craft.json")
    try:
        craft = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"review/craft/craft.json is not valid JSON: {exc}") from None
    findings = craft.get("findings")
    if not isinstance(findings, list):
        raise ValueError("review/craft/craft.json has no findings list")
    counts = {str(s): 0 for s in (4, 3, 2, 1)}
    checks: dict[str, int] = {}
    for f in findings:
        if isinstance(f, dict):
            if str(f.get("severity")) in counts:
                counts[str(f.get("severity"))] += 1
            checks[str(f.get("check"))] = checks.get(str(f.get("check")), 0) + 1
    page = json.loads(bench.read_text())["page"]
    return {"status": "completed", "page": page, "findings": len(findings), "severity_counts": counts, "checks": checks,
            "template_verdict": (craft.get("template_test") or {}).get("verdict"), "craft_path": "review/craft/craft.json"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=("prepare", "collect"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--site", default="")
    parser.add_argument("--page", default="")
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve()
    started = time.monotonic()
    try:
        if args.stage == "prepare":
            if not args.site or not args.page:
                raise ValueError("prepare needs --site and --page")
            result = prepare(workspace, Path(args.site).resolve(), args.page)
        else:
            result = collect(workspace)
    except (ValueError, OSError, KeyError) as exc:
        raise SystemExit(f"{args.stage}: {exc}") from None
    result["seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
