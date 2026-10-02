#!/usr/bin/env python3
"""Validation Engine command line: one subcommand per deterministic workflow step.

The `validation_engine` workflow (configs/validation/workflows/validation_engine.yaml) calls these from its script
agents; the model steps (ve_page, ve_campaign, ve_interview) call `check-copy` on their own work. Every
subcommand prints one JSON object on its last line (the step's structured output) and keeps all of the
idea's state under <state root>/state/ve/<idea_id>/ (docs/validation_engine.md).

    setup      read the rails, decide the mode, lock the pre-registered bars (sha256)
    check-copy check page/copy.json against the shape and the honesty rules
    deploy     render + guard the site; dry run: a local test URL; live: Stripe links + Netlify
    simulate   dry run only: play a synthetic crowd (with planted bots) through the real page
    check-launch  live: ve_campaign's launched ads match the plan (caps, UTMs, end date, total <= budget)
    check-ad-report  live: the pulled ad report is complete, in the canonical shape and within budget
    collect    live: pull PostHog / Netlify Forms / Stripe; then build the bot-filtered scorecard
    decide     apply the pre-registered rules -> advance / pivot / kill (+ confirm sizing, refunds)
    refund     refund every deposit still held (the page's 90-day promise, or the owner's call)
    checklist  print the owner's rails checklist
    serve      show a dry run's page on a local port (nothing it records reaches the scorecard)

Exit code 0 with `"ok": false` is used for expected stops (missing rails); a non-zero exit fails the
step (bad copy, a page without its honesty text, a changed pre-registration, a service error).
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from ve_common import (  # noqa: E402 - the path above comes first
    DEFAULT_DEPOSIT_USD,
    DEFAULT_RAILS_FILE,
    _money,
    _truthy,
    build_preregistration,
    evaluate_rails,
    idea_dir,
    iso,
    parse_env_file,
    rails_checklist_markdown,
    read_json,
    read_jsonl,
    slugify,
    today_utc,
    verify_preregistration,
    write_json,
    write_text,
)
from ve_score import build_scorecard, score  # noqa: E402
from ve_site import (  # noqa: E402
    LocalHost,
    guard_site,
    load_copy,
    render_site,
    validate_copy,
)
from ve_traffic import build_plan, simulate  # noqa: E402

# Files one test produces; a new registration moves the previous test's into archive/.
RUN_FILES = (
    "preregistration.json", "deploy.json", "campaign_plan.json", "campaign_launch.json", "events.jsonl",
    "forms.jsonl", "deposits.jsonl", "ad_report.jsonl", "concierge.jsonl", "simulation.json", "scorecard.json",
    "scorecard.yaml", "decision.json", "report.md",
)
RUN_DIRS = ("site", "evidence", "interview")


class Stop(Exception):
    """A step must fail: the message says why, in plain words."""


def emit(data: dict[str, Any]) -> None:
    print(json.dumps(data, default=str))


def _dir(args: argparse.Namespace) -> Path:
    d = Path(args.dir).expanduser()
    if not (d / "rails.json").exists():
        raise Stop(f"{d} has no rails.json: run `ve.py setup` first")
    return d


def _prereg(d: Path) -> dict[str, Any]:
    prereg = read_json(d / "preregistration.json")
    if not isinstance(prereg, dict):
        raise Stop("no pre-registration: `ve.py setup` writes it before anything runs")
    if not verify_preregistration(prereg):
        raise Stop("the pre-registered bars no longer match their sha256: a bar was moved after registration")
    return prereg


def _secrets(rails: dict[str, Any]) -> dict[str, str]:
    """The rails file's values, read at the moment a live call needs them (never stored or printed)."""
    return parse_env_file(rails.get("rails_file") or DEFAULT_RAILS_FILE)


def _archive_previous(d: Path) -> str | None:
    present = [n for n in RUN_FILES if (d / n).exists()] + [n for n in RUN_DIRS if (d / n).exists()]
    if not present:
        return None
    dest = d / "archive" / iso().replace(":", "")
    dest.mkdir(parents=True, exist_ok=True)
    for n in present:
        shutil.move(str(d / n), str(dest / n))
    return str(dest)


# ---------------------------------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------------------------------


def cmd_setup(args: argparse.Namespace) -> dict[str, Any]:
    rails_file = str(Path(args.rails_file or DEFAULT_RAILS_FILE).expanduser())
    env = parse_env_file(rails_file)
    budget = _money(args.budget_usd) if args.budget_usd not in (None, "") else None
    interviews = _truthy(args.interviews)
    r = evaluate_rails(env, requested_mode=args.mode or "dry_run", phase=args.phase or "all", tier=args.tier or "screen",
                       interviews=interviews, budget_usd=budget)
    idea = (args.idea or "").strip()
    idea_id = slugify(args.idea_id or idea) if (args.idea_id or idea) else ""
    root = Path(args.state_root or args.workspace).expanduser()
    stop = r["stop"]
    if not idea_id:
        stop = stop or "no idea given: pass the idea (one paragraph) and, optionally, an idea_id"
    d = idea_dir(root, idea_id or "_none")
    prereg_sha = None
    archived = None
    existing = read_json(d / "preregistration.json")
    if stop is None and r["phase"] == "collect":
        if not isinstance(existing, dict):
            stop = "nothing to collect: no test is registered for this idea (run phase=all first)"
        elif not verify_preregistration(existing):
            stop = "the registered bars no longer match their sha256: no verdict until a new test is registered"
        elif existing.get("mode") != r["mode"] or existing.get("tier") != r["tier"]:
            stop = (f"the registered test is {existing.get('mode')}/{existing.get('tier')}, this run asked for "
                    f"{r['mode']}/{r['tier']}")
        else:
            prereg_sha = existing["sha256"]
    elif stop is None:
        running = (
            isinstance(existing, dict)
            and existing.get("mode") == "live"
            and str(existing.get("run_window", {}).get("end", "")) > today_utc().isoformat()
        )
        if running:
            stop = (f"a live {existing.get('tier')} test of this idea is running until "
                    f"{existing['run_window']['end']}: use phase=collect, never a second launch")
        elif r["mode"] == "live" and r["tier"] == "confirm":
            last = read_json(d / "decision.json") or {}
            if last.get("decision") not in {"advance", "pivot"}:
                stop = "the confirm tier is for survivors: this idea has no advance/pivot verdict from a screen yet"
        if stop is None:
            archived = _archive_previous(d)
            countries = [c.strip().upper() for c in (args.countries or r["values"].get("VE_TARGET_COUNTRIES") or "US").split(",") if c.strip()]
            channels = [c.strip() for c in (args.channels or "").split(",") if c.strip()] or r["channels"]
            prereg = build_preregistration(
                idea_id=idea_id,
                idea=idea,
                tier=r["tier"],
                mode=r["mode"],
                budget_usd=r["budget_usd"],
                confirm_budget_usd=_money(r["values"].get("VE_CONFIRM_BUDGET_USD")),
                channels=channels,
                segment=(args.segment or "").strip(),
                countries=countries,
                deposit_usd=int(_money(args.deposit_usd) or DEFAULT_DEPOSIT_USD),
            )
            write_json(d / "preregistration.json", prereg)
            write_text(d / "idea.md", f"# {idea_id}\n\n{idea}\n\nSegment: {args.segment or '-'}\n\n## Evidence so far\n\n{args.evidence or '-'}\n")
            prereg_sha = prereg["sha256"]
    rails_record = {**{k: v for k, v in r.items() if k != "checklist"}, "stop": stop, "rails_file": rails_file,
                    "idea_id": idea_id, "interviews_requested": interviews}
    if idea_id:
        write_json(d / "rails.json", rails_record)
        write_text(d / "RAILS_CHECKLIST.md", r["checklist"])
    proceed = stop is None
    out = {
        "ok": proceed,
        "idea_id": idea_id,
        "idea_dir": str(d),
        "ve_bin": str(HERE),
        "mode": r["mode"],
        "requested_mode": r["requested_mode"],
        "phase": r["phase"],
        "tier": r["tier"],
        "stop": stop or "",
        "missing": r["missing"],
        "interview_missing": r["interview_missing"],
        "ads_keys_missing": r["ads_keys_missing"],
        "build": r["build"] and proceed,
        "live": r["live"] and proceed,
        "simulate": r["simulate"] and proceed,
        "proceed": proceed,
        "interviews": interviews and proceed,
        "interviews_live": r["interviews_live"] and proceed,
        "brand": r["values"].get("VE_BRAND", "") if r["mode"] == "live" else "",
        "domain": r["values"].get("VE_DOMAIN", "") if r["mode"] == "live" else "",
        "budget_usd": r["budget_usd"],
        "channels": r["channels"],
        "rails_file": rails_file,
        "prereg_sha256": prereg_sha or "",
        "archived_previous": archived or "",
        "checklist_path": str(d / "RAILS_CHECKLIST.md") if idea_id else "",
        "checklist": r["checklist"] if (stop and r["requested_mode"] == "live") else "",
    }
    return out


# ---------------------------------------------------------------------------------------------------
# check-copy / deploy
# ---------------------------------------------------------------------------------------------------


def _copy_problems(d: Path, rails: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        copy = load_copy(d)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return None, [str(exc)]
    problems = validate_copy(copy)
    brand = (rails.get("values") or {}).get("VE_BRAND")
    if rails.get("mode") == "live" and brand and str(copy.get("brand", "")).strip() != brand:
        problems.append(f"brand: a live page uses the rails' test brand {brand!r}, not {copy.get('brand')!r}")
    return copy, problems


def cmd_check_copy(args: argparse.Namespace) -> dict[str, Any]:
    d = _dir(args)
    _copy, problems = _copy_problems(d, read_json(d / "rails.json") or {})
    return {"ok": not problems, "problems": problems, "copy_path": str(d / "page" / "copy.json")}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "validation-engine-smoke-check"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - the test's own page
        return resp.read().decode("utf-8", "replace")


def cmd_deploy(args: argparse.Namespace) -> dict[str, Any]:
    d = _dir(args)
    rails = read_json(d / "rails.json") or {}
    prereg = _prereg(d)
    copy, problems = _copy_problems(d, rails)
    if problems or copy is None:
        raise Stop("the page copy breaks the rules, nothing was deployed:\n- " + "\n- ".join(problems))
    site = d / "site"
    if site.exists():
        shutil.rmtree(site)
    live = prereg["mode"] == "live"
    if not live:
        rendered = render_site(copy, prereg, site, mode="dry_run", contact="hello@example.test")
        bad = guard_site(site, rendered["variants"])
        if bad:
            raise Stop("the rendered page failed its honesty guard:\n- " + "\n- ".join(bad))
        test_url = f"http://127.0.0.1:{_free_port()}/"
        plan = build_plan(prereg, copy, test_url)
        deploy = {
            "mode": "dry_run",
            "kind": "local test host (static site + event/form collector + test-mode checkout); no traffic, no spend",
            "url": test_url,
            "site_dir": str(site),
            "pages": rendered["pages"],
            "variants": rendered["variants"],
            "deployed_at": iso(),
        }
    else:
        from ve_live import (
            Http,
            dashboard_links,
            netlify_check_forms,
            netlify_deploy,
            netlify_ensure_site,
            stripe_payment_links,
        )

        env = _secrets(rails)
        domain = env["VE_DOMAIN"].strip().lower()
        http = Http()
        variants = [str(v["id"]) for v in copy["variants"]]
        links = stripe_payment_links(
            http, env["STRIPE_SECRET_KEY"], idea_id=prereg["idea_id"], lock=prereg["sha256"][:12], variants=variants,
            deposit_usd=int(prereg["deposit_usd"]), product_name=str(copy["product_name"]),
            done_url=f"https://{domain}/deposit-done/",
        )
        ph = {"key": env["POSTHOG_PROJECT_API_KEY"], "host": env.get("POSTHOG_HOST") or "https://us.i.posthog.com"}
        rendered = render_site(copy, prereg, site, mode="live", deposit_urls={v: links[v]["url"] for v in variants},
                               posthog=ph, contact=f"hello@{domain}")
        bad = guard_site(site, rendered["variants"])
        if bad:
            raise Stop("the rendered page failed its honesty guard:\n- " + "\n- ".join(bad))
        token = env["NETLIFY_AUTH_TOKEN"]
        site_rec = netlify_ensure_site(http, token, site_id=env.get("NETLIFY_SITE_ID", ""), domain=domain,
                                       name=slugify(f"{copy['brand']}-{prereg['idea_id']}", 60))
        dep = netlify_deploy(http, token, str(site_rec["id"]), site)
        missing_forms = netlify_check_forms(http, token, str(site_rec["id"]))
        if missing_forms:
            raise Stop(f"Netlify did not detect the form(s) {', '.join(missing_forms)}: turn on form detection for "
                       "the site (Site configuration > Forms) and deploy again; no ads were launched")
        url = f"https://{domain}/"
        try:
            page = _fetch_text(url)
        except OSError as exc:
            raise Stop(f"{url} does not answer yet ({exc}): point the domain at the site; no ads were launched") from exc
        if "is not available yet" not in page:
            raise Stop(f"{url} answers but is not this test's page: no ads were launched")
        plan = build_plan(prereg, copy, url)
        deploy = {
            "mode": "live",
            "kind": "Netlify static site + Netlify Forms + PostHog events + Stripe Payment Links",
            "url": url,
            "site_dir": str(site),
            "pages": rendered["pages"],
            "variants": rendered["variants"],
            "site_id": site_rec["id"],
            "deploy_id": dep.get("id"),
            "admin_url": site_rec.get("admin_url"),
            "payment_links": links,
            "stripe_mode": rails.get("stripe_mode"),
            "posthog_host": ph["host"],
            "posthog_project": env.get("POSTHOG_PROJECT_ID", ""),
            "evidence": dashboard_links(site={**site_rec, "ssl_url": url}, links=links,
                                        stripe_test=rails.get("stripe_mode") == "test", posthog_host=ph["host"],
                                        posthog_project=env.get("POSTHOG_PROJECT_ID", "")),
            "deployed_at": iso(),
        }
    write_json(d / "deploy.json", deploy)
    write_json(d / "campaign_plan.json", plan)
    return {
        "ok": True,
        "mode": deploy["mode"],
        "url": deploy["url"],
        "variants": deploy["variants"],
        "pages": len(deploy["pages"]),
        "ads": len(plan["ads"]),
        "planned_total_usd": plan["planned_total_usd"],
        "plan_path": str(d / "campaign_plan.json"),
    }


# ---------------------------------------------------------------------------------------------------
# simulate (dry run only)
# ---------------------------------------------------------------------------------------------------

SHOT_PAGES = ("a/", "b/", "c/", "thanks/", "reserve/", "privacy/")


def _screenshots(url: str, variants: list[str], out: Path) -> list[str]:
    """Full-page screenshots of every page a visitor sees (the page's events are blocked: not a visit)."""
    try:
        from playwright.sync_api import (
            sync_playwright,  # type: ignore[import-not-found]
        )
    except ImportError:
        return []
    wanted = [p for p in SHOT_PAGES if p[:-1].upper() in variants or len(p) > 2]
    saved: list[str] = []
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception:  # noqa: BLE001 - the system chromium
            browser = pw.chromium.launch(headless=True, executable_path="/usr/bin/chromium-browser")
        ctx = browser.new_context(viewport={"width": 1100, "height": 900})
        ctx.route("**/e", lambda route: route.abort())
        ctx.route("**/f", lambda route: route.abort())
        page = ctx.new_page()
        for rel in wanted:
            page.goto(url.rstrip("/") + "/" + rel + "?sim=1", wait_until="load")
            name = rel.strip("/") or "index"
            target = out / f"page-{name}.png"
            page.screenshot(path=str(target), full_page=True)
            saved.append(str(target))
        ctx.close()
        browser.close()
    return saved


def cmd_simulate(args: argparse.Namespace) -> dict[str, Any]:
    d = _dir(args)
    prereg = _prereg(d)
    deploy = read_json(d / "deploy.json") or {}
    if prereg["mode"] != "dry_run" or deploy.get("mode") != "dry_run":
        raise Stop("simulate is for dry runs only: a live test's traffic comes from its ads")
    plan = read_json(d / "campaign_plan.json")
    port = int(str(deploy["url"]).rstrip("/").rsplit(":", 1)[1])
    try:
        host = LocalHost(d / "site", d, port=port)
    except OSError:
        host = LocalHost(d / "site", d, port=0)
    with host as url:
        truth = simulate(plan, url, d, seed=int(args.seed), engine=args.engine)
        shots = _screenshots(url, deploy["variants"], d / "evidence") if args.screenshots and truth["engine"] == "browser" else []
    deploy["served_at"] = url
    deploy["screenshots"] = shots
    write_json(d / "deploy.json", deploy)
    return {
        "ok": not truth["errors"],
        "engine": truth["engine"],
        "instrumentation": "the page's own ve.js sent every event" if truth["engine"] == "browser"
        else "UNVERIFIED: no browser here, the events were posted directly",
        "test_url": url,
        "visitors": truth["visitors"],
        "bots_planted": truth["bots_planted"],
        "humans_planted": truth["humans_planted"],
        "errors": len(truth["errors"]),
        "first_errors": truth["errors"][:3],
        "screenshots": shots,
    }


# ---------------------------------------------------------------------------------------------------
# check-launch / check-ad-report (the deterministic guard around ve_campaign's live work)
# ---------------------------------------------------------------------------------------------------

LAUNCH_STATUSES = {"active", "scheduled", "in_review", "paused", "rejected", "not_launched"}
SPENDING = {"active", "scheduled", "in_review", "paused"}  # a paused ad can be resumed: its cap counts


def _url_matches(planned: str, actual: str) -> bool:
    """The launched final URL carries the plan's page and every UTM value ({keyword} may be filled in)."""
    p, a = urllib.parse.urlsplit(planned), urllib.parse.urlsplit(actual)
    if (p.netloc, p.path.rstrip("/")) != (a.netloc, a.path.rstrip("/")):
        return False
    pq, aq = urllib.parse.parse_qs(p.query), urllib.parse.parse_qs(a.query)
    return all(k in aq and (v == aq[k] or "{keyword}" in v[0]) for k, v in pq.items())


def launch_problems(plan: dict[str, Any], launch: dict[str, Any], prereg: dict[str, Any]) -> tuple[list[str], float]:
    planned = {a["ad_id"]: a for a in plan.get("ads") or []}
    problems: list[str] = []
    total = 0.0
    seen: set[str] = set()
    for ad in launch.get("ads") or []:
        aid = str(ad.get("ad_id") or "")
        status = str(ad.get("status") or "")
        if aid not in planned:
            problems.append(f"{aid or '?'}: not in the campaign plan (launch only planned ads)")
            continue
        if aid in seen:
            problems.append(f"{aid}: launched twice")
        seen.add(aid)
        if status not in LAUNCH_STATUSES:
            problems.append(f"{aid}: status {status!r} is not one of {sorted(LAUNCH_STATUSES)}")
        if status not in SPENDING:
            continue
        cap = ad.get("lifetime_cap_usd")
        if cap is None:
            problems.append(f"{aid}: no lifetime spend cap recorded (every ad needs a hard cap)")
            cap = float("inf")
        cap = float(cap)
        if cap > float(planned[aid]["lifetime_budget_usd"]) + 0.01:
            problems.append(f"{aid}: cap ${cap:.2f} is above the plan's ${planned[aid]['lifetime_budget_usd']:.2f}")
        total += cap
        if not _url_matches(str(planned[aid]["url"]), str(ad.get("final_url") or "")):
            problems.append(f"{aid}: final URL does not carry the plan's page and UTM tags")
        end = str(ad.get("end_date") or "")
        if not end or end > str(prereg["run_window"]["end"]):
            problems.append(f"{aid}: end date {end or 'missing'} is after the window's end {prereg['run_window']['end']}")
    if total > float(prereg["budget_usd"]) + 0.01:
        problems.append(f"caps add up to ${total:.2f}, above the test's budget ${float(prereg['budget_usd']):.2f}")
    missing = sorted(set(planned) - seen)
    if missing:
        problems.append(f"planned ads with no launch record: {', '.join(missing)} (record them as not_launched with a reason)")
    return problems, round(total, 2)


def cmd_check_launch(args: argparse.Namespace) -> dict[str, Any]:
    d = _dir(args)
    prereg = _prereg(d)
    plan = read_json(d / "campaign_plan.json") or {}
    launch = read_json(d / "campaign_launch.json")
    if not isinstance(launch, dict):
        return {"ok": False, "problems": ["no campaign_launch.json yet"], "total_cap_usd": 0.0}
    problems, total = launch_problems(plan, launch, prereg)
    return {"ok": not problems, "problems": problems, "total_cap_usd": total, "budget_usd": prereg["budget_usd"],
            "planned": len(plan.get("ads") or []), "recorded": len(launch.get("ads") or [])}


def ad_report_problems(rows: list[dict[str, Any]], plan: dict[str, Any], prereg: dict[str, Any]) -> tuple[list[str], float]:
    planned = {a["ad_id"]: a for a in plan.get("ads") or []}
    problems: list[str] = []
    spend = 0.0
    for i, r in enumerate(rows, 1):
        aid = str(r.get("ad_id") or "")
        if aid not in planned:
            problems.append(f"row {i}: ad_id {aid or '?'} is not in the plan")
            continue
        for key in ("date", "channel", "variant", "impressions", "clicks", "spend_usd"):
            if r.get(key) is None:
                problems.append(f"row {i} ({aid}): missing `{key}`")
        if r.get("simulated"):
            problems.append(f"row {i} ({aid}): a simulated row in a live report")
        if (r.get("channel"), r.get("variant")) != (planned[aid]["channel"], planned[aid]["variant"]):
            problems.append(f"row {i} ({aid}): channel/variant differ from the plan")
        spend += float(r.get("spend_usd") or 0.0)
    if spend > float(prereg["budget_usd"]) + 0.01:
        problems.append(f"OVER BUDGET: spend ${spend:.2f} > budget ${float(prereg['budget_usd']):.2f}: pause every ad now "
                        "and tell the owner")
    return problems, round(spend, 2)


def cmd_check_ad_report(args: argparse.Namespace) -> dict[str, Any]:
    d = _dir(args)
    prereg = _prereg(d)
    plan = read_json(d / "campaign_plan.json") or {}
    rows = read_jsonl(d / "ad_report.jsonl")
    if not rows:
        return {"ok": False, "problems": ["no ad_report.jsonl rows yet"], "spend_usd": 0.0}
    problems, spend = ad_report_problems(rows, plan, prereg)
    return {"ok": not problems, "problems": problems, "spend_usd": spend, "budget_usd": prereg["budget_usd"],
            "rows": len(rows)}


# ---------------------------------------------------------------------------------------------------
# collect / decide
# ---------------------------------------------------------------------------------------------------


def _rewrite_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    write_text(path, "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in rows))


def _evidence(d: Path, deploy: dict[str, Any]) -> list[dict[str, str]]:
    if deploy.get("mode") == "live":
        ev = list(deploy.get("evidence") or [])
        launch = read_json(d / "campaign_launch.json") or {}
        for ad in launch.get("ads") or []:
            if ad.get("dashboard_url"):
                ev.append({"what": f"ad {ad.get('ad_id')} ({ad.get('channel')})", "link": str(ad["dashboard_url"])})
        return ev
    ev = [
        {"what": "test URL (local test host, stopped after the run)", "link": str(deploy.get("served_at") or deploy.get("url", ""))},
        {"what": "rendered site", "link": f"file://{d / 'site'}"},
    ]
    ev += [{"what": f"screenshot {Path(s).stem}", "link": f"file://{s}"} for s in deploy.get("screenshots") or []]
    for name, what in (("events.jsonl", "raw page events"), ("forms.jsonl", "form posts"),
                       ("deposits.jsonl", "test-mode deposits + refunds"), ("ad_report.jsonl", "ad report (simulated, $0)"),
                       ("simulation.json", "simulator ground truth (planted bots)")):
        if (d / name).exists():
            ev.append({"what": what, "link": f"file://{d / name}"})
    return ev


def cmd_collect(args: argparse.Namespace) -> dict[str, Any]:
    d = _dir(args)
    rails = read_json(d / "rails.json") or {}
    prereg = _prereg(d)
    deploy = read_json(d / "deploy.json") or {}
    live = prereg["mode"] == "live"
    pulled: dict[str, int] = {}
    if live:
        from ve_live import (
            Http,
            netlify_pull_forms,
            posthog_pull_events,
            stripe_pull_deposits,
        )

        env = _secrets(rails)
        http = Http()
        since = f"{prereg['run_window']['start']}T00:00:00Z"
        events = posthog_pull_events(http, deploy["posthog_host"], env["POSTHOG_PROJECT_ID"], env["POSTHOG_PERSONAL_API_KEY"],
                                     idea_id=prereg["idea_id"], since=since)
        forms = netlify_pull_forms(http, env["NETLIFY_AUTH_TOKEN"], str(deploy["site_id"]))
        deposits = stripe_pull_deposits(http, env["STRIPE_SECRET_KEY"], deploy.get("payment_links") or {})
        _rewrite_jsonl(d / "events.jsonl", events)
        _rewrite_jsonl(d / "forms.jsonl", forms)
        _rewrite_jsonl(d / "deposits.jsonl", deposits)
        pulled = {"events": len(events), "forms": len(forms), "deposit_rows": len(deposits)}
    copy = load_copy(d)
    card = build_scorecard(d, prereg, copy, live=live, evidence=_evidence(d, deploy))
    write_json(d / "scorecard.json", card)
    f = card["funnel"]
    return {
        "ok": True,
        "mode": card["mode"],
        "pulled": pulled,
        "sessions_total": card["filter"]["sessions_total"],
        "bots_dropped": card["filter"]["bots_dropped"],
        "real_in_segment": card["filter"]["in_segment"],
        "impressions": f["impressions"]["n"],
        "clicks": f["clicks"]["n"],
        "ctr": f["clicks"]["ctr"],
        "signups": f["signups"]["n"],
        "deposits": f["commitment"]["deposits"],
        "spend_usd": card["spend_usd"],
        "quality_flags": card["quality_flags"],
        "no_ad_report": live and not (d / "ad_report.jsonl").exists(),
        "scorecard_path": str(d / "scorecard.json"),
    }


def _blocked(d: Path | None, stop: str, checklist_path: str) -> dict[str, Any]:
    checklist = Path(checklist_path).read_text() if checklist_path and Path(checklist_path).exists() else rails_checklist_markdown()
    report = f"# Validation Engine: stopped before anything ran\n\n**{stop}**\n\nNothing was deployed and nothing was spent.\n\n{checklist}"
    path = ""
    if d is not None:
        path = str(write_text(d / "report.md", report))
    # Every field a normal verdict has, so the workflow's outputs read the same either way.
    return {"ok": False, "blocked": True, "decision": None, "rule": "blocked", "reason": stop, "stop": stop,
            "next_step": "the owner sets up the rails in the checklist (and a budget + go-ahead), then run again",
            "provisional": False, "synthetic": False, "confirm_sizing": "", "spend_usd": 0.0, "quality_flags": [],
            "refunded_now": 0, "report_path": path, "scorecard_path": "", "idea_dir": str(d or ""),
            "checklist": checklist, "run_interview": False, "interview_mode": "skip"}


def cmd_decide(args: argparse.Namespace) -> dict[str, Any]:
    stop = (args.stop or "").strip()
    d = Path(args.dir).expanduser() if args.dir else None
    if stop or d is None or not (d / "rails.json").exists():
        return _blocked(d if d and d.exists() else None, stop or "setup did not finish", args.checklist_path or "")
    rails = read_json(d / "rails.json") or {}
    prereg = _prereg(d)
    deploy = read_json(d / "deploy.json") or {}
    live = prereg["mode"] == "live"
    result = score(d, live=live, evidence=_evidence(d, deploy))
    card, verdict = result["card"], result["verdict"]
    refunds: list[dict[str, Any]] = []
    if live and verdict["decision"] == "kill" and not verdict.get("provisional"):
        from ve_live import Http, stripe_refund_all

        env = _secrets(rails)
        rows = read_jsonl(d / "deposits.jsonl")
        refunds = stripe_refund_all(Http(), env["STRIPE_SECRET_KEY"], rows, why="kill")
        if refunds:
            with (d / "deposits.jsonl").open("a") as fh:
                for r in refunds:
                    fh.write(json.dumps(r, sort_keys=True, default=str) + "\n")
    requested = bool(rails.get("interviews_requested"))
    survivor = verdict["decision"] in {"advance", "pivot"}
    if not requested or not survivor:
        mode = "skip"
    elif live and prereg["tier"] == "confirm" and rails.get("interviews_live") and not verdict.get("provisional"):
        mode = "live"
    else:
        mode = "prepare"
    verdict["interview_mode"] = mode
    verdict["refunded_now"] = len(refunds)
    write_json(d / "decision.json", verdict)
    sizing = verdict.get("confirm_sizing") or {}
    return {
        "ok": True,
        "blocked": False,
        "stop": "",
        "decision": verdict["decision"],
        "rule": verdict["rule"],
        "reason": verdict["reason"],
        "next_step": verdict["next_step"],
        "provisional": verdict.get("provisional", False),
        "synthetic": card["synthetic"],
        "confirm_sizing": sizing.get("summary", ""),
        "spend_usd": card["spend_usd"],
        "quality_flags": card["quality_flags"],
        "refunded_now": len(refunds),
        "run_interview": mode != "skip",
        "interview_mode": mode,
        "scorecard_path": str(d / "scorecard.yaml"),
        "report_path": str(d / "report.md"),
        "idea_dir": str(d),
    }


def held_deposits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Paid deposits with no refund row yet (whoever asked for the refund)."""
    refunded = {str(r.get("id")) for r in rows if r.get("status") == "refunded"}
    return [r for r in rows if r.get("status") == "paid" and str(r.get("id")) not in refunded]


def cmd_refund(args: argparse.Namespace) -> dict[str, Any]:
    d = _dir(args)
    rails = read_json(d / "rails.json") or {}
    prereg = _prereg(d)
    rows = read_jsonl(d / "deposits.jsonl")
    held = held_deposits(rows)
    why = (args.why or "owner").strip() or "owner"
    if prereg["mode"] == "live":
        from ve_live import Http, stripe_refund_all

        done = stripe_refund_all(Http(), _secrets(rails)["STRIPE_SECRET_KEY"], rows, why=why)
    else:  # dry run: the deposits are the simulator's test-mode rows; mark them refunded, call nothing
        done = [{**{k: v for k, v in r.items() if k != "status"}, "status": "refunded", "refund_id": f"mock_refund_{r['id']}",
                 "ts": iso(), "refund_reason": f"engine:{why}"} for r in held]
    if done:
        with (d / "deposits.jsonl").open("a") as fh:
            for r in done:
                fh.write(json.dumps(r, sort_keys=True, default=str) + "\n")
    left = held_deposits(read_jsonl(d / "deposits.jsonl"))
    return {"ok": not left, "mode": prereg["mode"], "held_before": len(held), "refunded_now": len(done),
            "still_held": len(left), "refund_by": prereg.get("refund_by")}


# ---------------------------------------------------------------------------------------------------
# checklist / serve
# ---------------------------------------------------------------------------------------------------


def cmd_checklist(args: argparse.Namespace) -> dict[str, Any]:
    env = parse_env_file(args.rails_file or DEFAULT_RAILS_FILE)
    r = evaluate_rails(env, requested_mode="live", interviews=_truthy(args.interviews))
    sys.stderr.write(r["checklist"])
    return {"ok": not r["missing"], "missing": r["missing"], "interview_missing": r["interview_missing"]}


def cmd_serve(args: argparse.Namespace) -> dict[str, Any]:  # pragma: no cover - interactive
    d = Path(args.dir).expanduser()
    with tempfile.TemporaryDirectory() as scratch, LocalHost(d / "site", scratch, port=int(args.port)) as url:
        sys.stderr.write(f"serving {d / 'site'} at {url} (Ctrl+C to stop; visits are not recorded)\n")
        try:
            import time

            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    return {"ok": True}


# ---------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ve.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup")
    s.add_argument("--workspace", required=True)
    s.add_argument("--state-root", default="")
    s.add_argument("--idea", default="")
    s.add_argument("--idea-id", default="")
    s.add_argument("--mode", default="dry_run")
    s.add_argument("--phase", default="all")
    s.add_argument("--tier", default="screen")
    s.add_argument("--rails-file", default="")
    s.add_argument("--budget-usd", default="")
    s.add_argument("--interviews", default="")
    s.add_argument("--segment", default="")
    s.add_argument("--countries", default="")
    s.add_argument("--channels", default="")
    s.add_argument("--deposit-usd", default="")
    s.add_argument("--evidence", default="")

    for name in ("check-copy", "deploy", "collect", "check-launch", "check-ad-report"):
        x = sub.add_parser(name)
        x.add_argument("--dir", required=True)
    x = sub.add_parser("simulate")
    x.add_argument("--dir", required=True)
    x.add_argument("--seed", default="7")
    x.add_argument("--engine", default="auto", choices=["auto", "browser", "http"])
    x.add_argument("--screenshots", type=_truthy, default=True)
    x = sub.add_parser("decide")
    x.add_argument("--dir", default="")
    x.add_argument("--stop", default="")
    x.add_argument("--checklist-path", default="")
    x = sub.add_parser("refund")
    x.add_argument("--dir", required=True)
    x.add_argument("--why", default="owner")
    x = sub.add_parser("checklist")
    x.add_argument("--rails-file", default="")
    x.add_argument("--interviews", default="")
    x = sub.add_parser("serve")
    x.add_argument("--dir", required=True)
    x.add_argument("--port", default="8765")

    args = p.parse_args(argv)
    handler = {
        "setup": cmd_setup, "check-copy": cmd_check_copy, "deploy": cmd_deploy, "simulate": cmd_simulate,
        "check-launch": cmd_check_launch, "check-ad-report": cmd_check_ad_report,
        "collect": cmd_collect, "decide": cmd_decide, "refund": cmd_refund, "checklist": cmd_checklist, "serve": cmd_serve,
    }[args.cmd]
    try:
        out = handler(args)
    except Stop as exc:
        sys.stderr.write(f"{exc}\n")
        emit({"ok": False, "error": str(exc)})
        return 1
    emit(out)
    return 0 if (out.get("ok") or args.cmd in {"setup", "decide", "checklist"}) else 1


if __name__ == "__main__":
    sys.exit(main())
