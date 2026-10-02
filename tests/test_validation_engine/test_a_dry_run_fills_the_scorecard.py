"""A dry run instruments the whole funnel and fills the spec's scorecard with zero spend.

It is the engine's proof before any money moves: a seeded synthetic crowd (with planted bots) goes
through the real rendered page and the real collector, the same bot filter and rules as a live run
judge it, and every number is labelled synthetic (docs/validation_engine.md, "Scorecard schema")."""

import copy
import html
import json
import re
import shutil
from urllib.parse import parse_qs, urlsplit

import yaml
from ve_common import build_preregistration, read_json, read_jsonl, write_json
from ve_score import decide
from ve_site import (
    REFUND_FAQ_Q,
    REQUIRED_PHRASES,
    guard_site,
    refund_terms,
    validate_copy,
)

from .conftest import run_ve


def card_of(dry_run):
    return yaml.safe_load((dry_run["dir"] / "scorecard.yaml").read_text())


def copy_of(dry_run, tmp_path):
    """The dry run's idea folder, copied, for a test that changes it."""
    d = tmp_path / "idea"
    shutil.copytree(dry_run["dir"], d)
    return d


def test_the_scorecard_has_the_spec_schema(dry_run):
    card = card_of(dry_run)
    for key in ("idea_id", "run_window", "segment", "channels", "funnel", "variants", "quality_flags", "spend_usd",
                "decision", "evidence"):
        assert key in card, f"scorecard is missing `{key}`"
    f = card["funnel"]
    assert set(f) >= {"impressions", "clicks", "engaged", "signups", "commitment", "activation", "retention"}
    assert set(f["clicks"]) >= {"n", "ctr", "threshold", "pass"}
    assert set(f["engaged"]) >= {"rate", "scroll90", "median_seconds"}
    assert set(f["signups"]) >= {"n", "rate", "threshold", "pass"}
    assert set(f["commitment"]) >= {"deposits", "booked_calls", "threshold_n", "pass"}
    assert set(card["run_window"]) == {"start", "end"}
    assert {v["id"] for v in card["variants"]} == {"A", "B", "C"}
    assert all({"id", "headline", "clicks", "signups"} <= set(v) for v in card["variants"])


def test_every_funnel_step_is_instrumented_with_zero_spend(dry_run):
    card = card_of(dry_run)
    f = card["funnel"]
    assert f["impressions"]["n"] > 0 and f["clicks"]["n"] > 0
    assert f["engaged"]["rate"] > 0 and f["engaged"]["median_seconds"] > 0
    assert f["signups"]["n"] > 0
    assert f["commitment"]["deposits"] + f["commitment"]["booked_calls"] > 0
    assert f["activation"]["used_concierge"] > 0
    assert card["followup"]["replies"] > 0
    assert card["spend_usd"] == 0.0
    assert card["synthetic"] is True and "synthetic" in card["quality_flags"]
    assert card["decision"] in {"advance", "pivot", "kill"}
    assert len(card["evidence"]) >= 4


def test_the_bot_filter_catches_every_planted_bot(dry_run):
    fl = card_of(dry_run)["filter"]
    truth = read_json(dry_run["dir"] / "simulation.json")
    assert fl["check"]["ok"] is True
    assert fl["bots_dropped"] == fl["check"]["planted_bots"] == truth["bots_planted"] > 0
    assert fl["check"]["humans_dropped"] == 0
    assert set(fl["bot_reasons"]) >= {"under_2s", "datacenter_ip", "bot_user_agent", "automated_browser"}


def test_every_ad_carries_the_utm_scheme(dry_run):
    plan = read_json(dry_run["dir"] / "campaign_plan.json")
    assert plan["planned_total_usd"] == 0.0, "a dry run plans no spend"
    assert {a["channel"] for a in plan["ads"]} == {"google-search", "reddit-ads"}
    for ad in plan["ads"]:
        q = parse_qs(urlsplit(ad["url"]).query)
        assert q["utm_campaign"] == ["ve-hourly-screening-screen"]
        assert q["utm_content"] == [ad["variant"]] and q["ve_ad"] == [ad["ad_id"]]
        assert q["utm_source"] and q["utm_medium"]
        assert ("utm_term" in q) == (ad["kind"] == "search")


def test_every_page_says_early_access_and_fully_refundable(dry_run):
    site = dry_run["dir"] / "site"
    assert guard_site(site, ["A", "B", "C"]) == []
    pages = {p.parent.name: " ".join(p.read_text().split()) for p in site.rglob("index.html")}
    for name in ("a", "b", "c"):
        assert REQUIRED_PHRASES["early_access"] in pages[name], f"{name}: no not-available-yet banner"
    for name in ("a", "b", "c", "reserve", "deposit-done", "thanks", "privacy"):
        assert REQUIRED_PHRASES["refundable"] in pages[name], f"{name}: no refund terms"
    for text in pages.values():
        assert not re.search(r"refund[^.]*automatically|automatically[^.]*refund", text, re.I), (
            "nothing refunds on its own: the 90-day promise is a dated duty in the report")


def test_the_refund_terms_are_the_engines_alone(dry_run, copy_hourly):
    # A second dry run's copy narrowed the promise ("refundable any time before we launch"):
    # the copy may not restate refunds, and every landing page carries the one wording.
    narrowed = copy.deepcopy(copy_hourly)
    narrowed["faq"].append({"q": "Is the deposit refundable?", "a": "Yes, any time before we launch."})
    assert any(p.startswith("faq[2]: leave refunds out") for p in validate_copy(narrowed))
    pain = copy.deepcopy(copy_hourly)  # a buyer's own refund pain is not our promise
    pain["variants"][0]["subhead"] = "Then you chase down payment or give a refund."
    assert not [p for p in validate_copy(pain) if "leave refunds out" in p]
    for name in ("a", "b", "c"):
        text = (dry_run["dir"] / "site" / name / "index.html").read_text()
        plain = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())
        assert REFUND_FAQ_Q in plain and refund_terms(49) in plain, f"{name}: no engine refund FAQ"


def test_a_page_that_claims_it_ships_fails_the_guard(dry_run, tmp_path):
    site = copy_of(dry_run, tmp_path) / "site"
    page = site / "a" / "index.html"
    page.write_text(page.read_text().replace("</h1>", " Available now.</h1>", 1))
    assert guard_site(site, ["A", "B", "C"]), "a page claiming it ships must not pass"


def test_the_verdict_follows_the_preregistered_rules(dry_run):
    verdict = read_json(dry_run["dir"] / "decision.json")
    prereg = read_json(dry_run["dir"] / "preregistration.json")
    assert verdict["rule"] in {step["rule"] for step in verdict["trace"] if step["fired"]}
    assert dry_run["decide"]["decision"] == verdict["decision"]
    assert prereg["decision_rules"] and prereg["sha256"]
    report = (dry_run["dir"] / "report.md").read_text()
    assert report.startswith("# Validation Engine scorecard") and "DRY RUN" in report and "SYNTHETIC" in report
    assert prereg["refund_by"] in report
    assert "one-off novelty" not in report, "repeat use is read on a finished confirm test, not a screen"


def test_a_moved_bar_gets_no_verdict(dry_run):
    card = json.loads((dry_run["dir"] / "scorecard.json").read_text())
    prereg = read_json(dry_run["dir"] / "preregistration.json")
    moved = copy.deepcopy(prereg)
    moved["thresholds"]["signup_rate"] = 0.01
    out = decide(card, moved)
    assert out["decision"] is None and out["rule"] == "preregistration_changed"


def test_survivors_get_confirm_sizing_and_rung4_is_prepared_not_run(dry_run):
    out = dry_run["decide"]
    assert out["decision"] in {"advance", "pivot"}
    assert "clicks" in out["confirm_sizing"] and "$" in out["confirm_sizing"]
    assert "owner" in out["confirm_sizing"], "no confirm budget is set: the owner is asked first"
    assert out["run_interview"] is True and out["interview_mode"] == "prepare"


def test_interviews_are_skipped_unless_asked_for(dry_run, tmp_path):
    d = copy_of(dry_run, tmp_path)
    rails = read_json(d / "rails.json")
    write_json(d / "rails.json", {**rails, "interviews_requested": False})
    out = run_ve("decide", "--dir", str(d))
    assert out["run_interview"] is False and out["interview_mode"] == "skip"


def test_the_refund_promise_outlasts_the_test():
    prereg = build_preregistration(idea_id="t", idea="t", tier="screen", mode="dry_run", budget_usd=0.0,
                                   confirm_budget_usd=None, channels=["google-search"])
    assert prereg["refund_by"] > prereg["run_window"]["end"]


def test_refund_returns_every_deposit_still_held(dry_run, tmp_path):
    d = copy_of(dry_run, tmp_path)
    out = run_ve("refund", "--dir", str(d), "--why", "test")
    assert out["held_before"] > 0, "the dry run leaves a deposit to refund"
    assert out["ok"] is True and out["still_held"] == 0 and out["refunded_now"] == out["held_before"]
    rows = read_jsonl(d / "deposits.jsonl")
    assert all(r["refund_reason"] == "engine:test" for r in rows[-out["refunded_now"]:])
    again = run_ve("refund", "--dir", str(d), "--why", "test")
    assert again["refunded_now"] == 0, "refunding twice refunds nothing"
