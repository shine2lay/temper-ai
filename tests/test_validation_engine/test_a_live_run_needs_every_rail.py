"""A live run needs every rail, a set budget and the owner's go-ahead; it never spends past the budget
and never prints a secret (docs/validation_engine.md, "Guardrails" and "Rails").

Nothing here reaches a real service: the rails are fakes in a temporary file, and the live adapters
run against a fake transport."""

import json
from pathlib import Path
from urllib.parse import parse_qs

import pytest
import ve
from ve_common import LIVE_RAILS, build_preregistration, evaluate_rails, read_json
from ve_live import Http, LiveError, stripe_payment_links, stripe_refund_all
from ve_traffic import build_plan

from .conftest import IDEA, run_ve

MARK = "NEVER_PRINT_ME"
SECRET = f"sk_test_{MARK}_0123456789"

FULL_RAILS = {
    "VE_BRAND": "Crewline",
    "VE_DOMAIN": "crewline-test.example",
    "NETLIFY_AUTH_TOKEN": f"nfp_{MARK}_netlify",
    "POSTHOG_PROJECT_API_KEY": f"phc_{MARK}_project",
    "POSTHOG_PERSONAL_API_KEY": f"phx_{MARK}_personal",
    "POSTHOG_PROJECT_ID": "12345",
    "VE_AD_CHANNELS": "google-search",
    "GOOGLE_ADS_DEVELOPER_TOKEN": f"dev_{MARK}",
    "GOOGLE_ADS_CLIENT_ID": f"client_{MARK}",
    "GOOGLE_ADS_CLIENT_SECRET": f"gcs_{MARK}",
    "GOOGLE_ADS_REFRESH_TOKEN": f"grt_{MARK}",
    "GOOGLE_ADS_CUSTOMER_ID": "123-456-7890",
    "STRIPE_SECRET_KEY": SECRET,
    "VE_SCREEN_BUDGET_USD": "50",
    "VE_CONFIRM_BUDGET_USD": "300",
    "VE_GO_AHEAD": "yes",
}


def rails_file(path: Path, **changes: str | None) -> Path:
    env = {**FULL_RAILS, **changes}
    path.write_text("".join(f"{k}={v}\n" for k, v in env.items() if v is not None))
    return path


def setup(tmp_path: Path, rails: Path, *extra: str) -> dict:
    return run_ve("setup", "--workspace", str(tmp_path / "ws"), "--idea", IDEA, "--idea-id", "hourly-screening",
                  "--mode", "live", "--rails-file", str(rails), *extra)


# --- the gate -------------------------------------------------------------------------------------


def test_with_no_rails_a_live_run_stops_before_anything(tmp_path):
    out = setup(tmp_path, tmp_path / "missing.env")
    assert out["ok"] is False and out["mode"] == "dry_run"
    assert not any(out[k] for k in ("build", "live", "simulate", "proceed", "interviews_live"))
    assert "nothing was spent" in out["stop"].lower()
    assert set(out["missing"]) == {g for g, _keys, _note in LIVE_RAILS}
    assert "- [ ] **stripe**" in out["checklist"] and "rails.example.env" in out["checklist"]
    d = Path(out["idea_dir"])
    assert not (d / "preregistration.json").exists(), "a stopped run registers no test"
    blocked = run_ve("decide", "--dir", str(d), "--stop", out["stop"], "--checklist-path", out["checklist_path"])
    assert blocked["blocked"] is True and blocked["decision"] is None and blocked["spend_usd"] == 0.0
    report = (d / "report.md").read_text()
    assert "Nothing was deployed and nothing was spent" in report and "- [ ] **go_ahead**" in report


@pytest.mark.parametrize("group,keys", [(g, k) for g, k, _note in LIVE_RAILS], ids=[g for g, _k, _n in LIVE_RAILS])
def test_each_missing_rail_blocks_a_live_run(group, keys):
    env = {k: v for k, v in FULL_RAILS.items() if k != keys[0]}
    r = evaluate_rails(env, requested_mode="live")
    assert r["live"] is False and r["mode"] == "dry_run" and group in r["missing"] and group in r["stop"]


def test_a_go_ahead_of_no_and_an_ad_channel_without_its_keys_block_it():
    r = evaluate_rails({**FULL_RAILS, "VE_GO_AHEAD": "no"}, requested_mode="live")
    assert r["live"] is False and "go_ahead" in r["missing"]
    r = evaluate_rails({**FULL_RAILS, "VE_AD_CHANNELS": "google-search,reddit-ads"}, requested_mode="live")
    assert r["live"] is False and "ads" in r["missing"]
    assert "REDDIT_ADS_CLIENT_SECRET" in r["ads_keys_missing"]


def test_every_rail_and_the_go_ahead_allow_a_live_run():
    r = evaluate_rails(dict(FULL_RAILS), requested_mode="live")
    assert r["stop"] is None and r["live"] is True and r["simulate"] is False
    assert r["budget_usd"] == 50.0 and r["stripe_mode"] == "test"


def test_a_budget_above_the_owners_is_a_stop_not_a_clamp():
    r = evaluate_rails(dict(FULL_RAILS), requested_mode="live", budget_usd=80.0)
    assert r["live"] is False and "exceeds the owner's set screen budget $50.00" in r["stop"]
    r = evaluate_rails(dict(FULL_RAILS), requested_mode="live", tier="confirm", budget_usd=250.0)
    assert r["live"] is True and r["budget_usd"] == 250.0


def test_setup_never_prints_or_stores_a_secret(tmp_path):
    out = setup(tmp_path, rails_file(tmp_path / "rails.env"))
    assert out["ok"] is True and out["live"] is True and out["budget_usd"] == 50.0
    assert MARK not in out["_stdout"] + out["_stderr"]
    d = Path(out["idea_dir"])
    for p in d.rglob("*"):
        if p.is_file():
            assert MARK not in p.read_text(), f"{p.name} holds a secret value"
    rails = read_json(d / "rails.json")
    assert "STRIPE_SECRET_KEY" in rails["present_keys"], "key names are recorded, values are not"
    assert rails["values"]["VE_BRAND"] == "Crewline"


def test_a_running_live_test_is_never_launched_twice(tmp_path):
    rails = rails_file(tmp_path / "rails.env")
    assert setup(tmp_path, rails)["ok"] is True
    again = setup(tmp_path, rails)
    assert again["ok"] is False and again["live"] is False and "phase=collect" in again["stop"]
    collect = setup(tmp_path, rails, "--phase", "collect")
    assert collect["ok"] is True and collect["build"] is False and collect["live"] is True


def test_the_confirm_tier_is_for_survivors_only(tmp_path):
    out = setup(tmp_path, rails_file(tmp_path / "rails.env"), "--tier", "confirm")
    assert out["ok"] is False and "survivors" in out["stop"]


def test_collect_needs_a_registered_test(tmp_path):
    out = setup(tmp_path, rails_file(tmp_path / "rails.env"), "--phase", "collect")
    assert out["ok"] is False and "nothing to collect" in out["stop"]


# --- the ads stay inside the plan and the budget ----------------------------------------------------


@pytest.fixture
def live_plan(copy_hourly):
    prereg = build_preregistration(idea_id="hourly-screening", idea=IDEA, tier="screen", mode="live", budget_usd=50.0,
                                   confirm_budget_usd=300.0, channels=["google-search", "reddit-ads"])
    plan = build_plan(prereg, copy_hourly, "https://crewline-test.example")
    return prereg, plan


def launched(plan, prereg, **change):
    ads = []
    for a in plan["ads"]:
        ads.append({"ad_id": a["ad_id"], "status": "active", "lifetime_cap_usd": a["lifetime_budget_usd"],
                    "final_url": a["url"].replace("{keyword}", "hourly+applicant+screening"),
                    "end_date": prereg["run_window"]["end"], **change.get(a["ad_id"], {})})
    return {"ads": ads}


def test_the_plan_caps_every_ad_inside_the_budget(live_plan):
    prereg, plan = live_plan
    assert len(plan["ads"]) == 6 and plan["planned_total_usd"] <= 50.0
    assert all(0 < a["lifetime_budget_usd"] <= 50.0 / 6 for a in plan["ads"])
    assert ve.launch_problems(plan, launched(plan, prereg), prereg) == ([], plan["planned_total_usd"])


def test_a_launch_outside_the_plan_is_caught(live_plan):
    prereg, plan = live_plan
    first, second, third = (a["ad_id"] for a in plan["ads"][:3])
    bad = launched(plan, prereg, **{
        first: {"lifetime_cap_usd": 45.0},
        second: {"final_url": "https://crewline-test.example/b/"},
        third: {"lifetime_cap_usd": None},
    })
    bad["ads"].append({"ad_id": "extra-1", "status": "active", "lifetime_cap_usd": 5.0})
    problems, _total = ve.launch_problems(plan, bad, prereg)
    text = "\n".join(problems)
    assert f"{first}: cap $45.00 is above the plan's" in text
    assert "above the test's budget $50.00" in text
    assert f"{second}: final URL does not carry the plan's page and UTM tags" in text
    assert f"{third}: no lifetime spend cap" in text
    assert "extra-1: not in the campaign plan" in text


def test_an_ad_report_over_budget_says_pause_everything(live_plan):
    prereg, plan = live_plan
    rows = [{"date": prereg["run_window"]["start"], "ad_id": a["ad_id"], "channel": a["channel"], "variant": a["variant"],
             "impressions": 900, "clicks": 12, "spend_usd": 9.5} for a in plan["ads"]]
    problems, spend = ve.ad_report_problems(rows, plan, prereg)
    assert spend == 57.0 and any(p.startswith("OVER BUDGET") and "pause every ad" in p for p in problems)
    rows[0]["simulated"] = True
    assert any("simulated row in a live report" in p for p in ve.ad_report_problems(rows, plan, prereg)[0])


# --- the live adapters, on a fake transport ---------------------------------------------------------


class FakeService:
    def __init__(self, *statuses: int) -> None:
        self.calls: list[dict] = []
        self.statuses = list(statuses)

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": dict(headers),
                           "form": parse_qs(body.decode()) if body else {}})
        status = self.statuses.pop(0) if self.statuses else 200
        if status >= 400:
            return status, json.dumps({"error": {"message": "No such thing"}}).encode()
        n = len(self.calls)
        if url.endswith("/payment_links"):
            return 200, json.dumps({"id": f"plink_{n}", "url": f"https://buy.stripe.com/test_{n}"}).encode()
        return 200, json.dumps({"id": f"obj_{n}"}).encode()


def links_with(fake):
    return stripe_payment_links(Http(fake, sleep=lambda _s: None), SECRET, idea_id="hourly-screening", lock="abc123",
                                variants=["A", "B"], deposit_usd=49, product_name="Crewline Screen",
                                done_url="https://crewline-test.example/deposit-done/")


def test_deposit_links_are_refundable_early_access_and_idempotent():
    fake = FakeService()
    links = links_with(fake)
    assert set(links) == {"A", "B"} and links["A"]["url"].startswith("https://buy.stripe.com/")
    product, price, *link_calls = fake.calls
    assert "not available yet" in product["form"]["description"][0]
    assert "fully refundable" in product["form"]["name"][0]
    assert price["form"]["unit_amount"] == ["4900"]
    for call in link_calls:
        text = call["form"]["custom_text[submit][message]"][0]
        assert text.startswith("Fully refundable reservation") and "Nothing ships today" in text
    keys = [c["headers"]["Idempotency-Key"] for c in fake.calls]
    assert len(set(keys)) == len(keys) == 4
    again = FakeService()
    links_with(again)
    assert [c["headers"]["Idempotency-Key"] for c in again.calls] == keys, "a re-run creates nothing new"


def test_refund_all_returns_each_held_deposit_once():
    rows = [
        {"id": "cs_1", "status": "paid", "payment_intent": "pi_1", "variant": "A"},
        {"id": "cs_2", "status": "paid", "payment_intent": "pi_2", "variant": "B"},
        {"id": "cs_2", "status": "refunded", "payment_intent": "pi_2", "refund_reason": "requested_by_customer"},
    ]
    fake = FakeService()
    done = stripe_refund_all(Http(fake, sleep=lambda _s: None), SECRET, rows, why="kill")
    assert [d["id"] for d in done] == ["cs_1"] and done[0]["refund_reason"] == "engine:kill"
    (call,) = fake.calls
    assert call["headers"]["Idempotency-Key"] == "ve-refund-pi_1"
    assert call["form"]["payment_intent"] == ["pi_1"] and call["form"]["metadata[ve_engine]"] == ["1"]


def test_a_busy_service_is_retried_once_and_an_error_carries_no_secret():
    slept = []
    fake = FakeService(429)
    assert Http(fake, sleep=slept.append).call("stripe", "GET", "https://api.stripe.com/v1/refunds",
                                               headers={"Authorization": f"Bearer {SECRET}"}) == {"id": "obj_2"}
    assert slept == [2.0]
    with pytest.raises(LiveError) as err:
        Http(FakeService(401), sleep=lambda _s: None).call("stripe", "POST", "https://api.stripe.com/v1/refunds",
                                                           headers={"Authorization": f"Bearer {SECRET}"})
    assert "stripe: POST /v1/refunds -> HTTP 401" in str(err.value) and MARK not in str(err.value)
