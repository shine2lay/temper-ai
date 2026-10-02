"""The pre-registered rules decide, in their written order (docs/validation_engine.md, "Pre-registered
thresholds" and "Decision rules"): kill on a dead headline, on signups without commitment or on a page
nobody answers; the screen passes everything else on (pivoting on a clear framing split); the confirm
tier advances only on real deposits, depth and replies."""

import pytest
from ve_common import build_preregistration
from ve_score import decide, fisher_greater

from .conftest import IDEA


def prereg(tier="screen"):
    return build_preregistration(idea_id="hourly-screening", idea=IDEA, tier=tier, mode="live", budget_usd=50.0,
                                 confirm_budget_usd=300.0, channels=["google-search"])


def variant(vid, impressions, clicks, sessions, signups):
    return {"id": vid, "impressions": impressions, "clicks": clicks, "sessions": sessions, "signups": signups,
            "ctr": round(clicks / impressions, 4) if impressions else 0.0,
            "signup_rate": round(signups / sessions, 4) if sessions else 0.0}


def card(*variants, deposits=0, calls=0, engaged=0.5, flags=(), spend=50.0, window_complete=True):
    imp = sum(v["impressions"] for v in variants)
    clicks = sum(v["clicks"] for v in variants)
    sessions = sum(v["sessions"] for v in variants)
    signups = sum(v["signups"] for v in variants)
    return {
        "funnel": {
            "impressions": {"n": imp},
            "clicks": {"n": clicks, "ctr": round(clicks / imp, 4) if imp else 0.0},
            "engaged": {"rate": engaged},
            "signups": {"n": signups, "rate": round(signups / sessions, 4) if sessions else 0.0},
            "commitment": {"deposits": deposits, "booked_calls": calls},
            "activation": {"used_concierge": 0},
            "retention": {"repeat_users": 0},
        },
        "filter": {"in_segment": sessions},
        "variants": list(variants),
        "quality_flags": list(flags),
        "spend_usd": spend,
        "window_complete": window_complete,
    }


@pytest.mark.parametrize(
    "the_card,rule",
    [
        (card(variant("A", 1000, 2, 2, 0), variant("B", 1000, 3, 3, 0)), "kill_ctr"),
        (card(variant("A", 1000, 20, 20, 6), variant("B", 1000, 20, 20, 6)), "kill_no_commitment"),
        (card(variant("A", 1000, 15, 15, 0), variant("B", 1000, 15, 15, 0)), "kill_signup_rate"),
    ],
    ids=["dead headline", "signups without commitment", "nobody raises a hand"],
)
def test_the_kill_rules(the_card, rule):
    out = decide(the_card, prereg())
    assert (out["decision"], out["rule"]) == ("kill", rule)
    assert out["confirm_sizing"] is None and "refund every deposit" in out["next_step"]
    assert [t["rule"] for t in out["trace"] if t["fired"]] == [rule]


def test_a_framing_that_rescues_the_ctr_is_not_killed():
    out = decide(card(variant("A", 1000, 5, 5, 1), variant("B", 3000, 0, 0, 0)), prereg())
    assert out["rule"] != "kill_ctr", "overall CTR 0.125%, but framing A reaches the 0.5% bar"
    assert out["decision"] == "pivot" and out["pivot"]["metric"] == "ctr" and out["pivot"]["keep"] == ["A"]


def test_the_screen_passes_a_survivor_on_with_confirm_sizing():
    out = decide(card(variant("A", 1000, 20, 20, 4), variant("B", 1000, 20, 20, 3), deposits=1), prereg())
    assert (out["decision"], out["rule"]) == ("advance", "advance")
    s = out["confirm_sizing"]
    assert s["framings"] == ["A", "B"] and s["target_clicks"] == 200
    assert s["cpc_usd"] == 1.25 and "observed CPC" in s["cpc_basis"]
    assert s["needed_usd"] == 250.0 and s["needs_owner_ok"] is False, "within the owner's $300 confirm budget"


def test_a_clear_framing_split_is_a_pivot_that_drops_the_flop():
    out = decide(card(variant("A", 1000, 30, 30, 9), variant("B", 1000, 30, 30, 0)), prereg())
    assert (out["decision"], out["rule"]) == ("pivot", "pivot")
    assert out["pivot"]["best"] == "A" and out["pivot"]["keep"] == ["A"] and out["pivot"]["p_value"] < 0.05
    assert out["confirm_sizing"]["framings"] == ["A"]


def test_a_split_that_could_be_noise_is_no_pivot():
    out = decide(card(variant("A", 1000, 12, 12, 2), variant("B", 1000, 12, 12, 0)), prereg())
    assert out["decision"] == "advance", "2/12 vs 0/12 is not significant: no framing is dropped on noise"
    assert fisher_greater(2, 12, 0, 12) > 0.05


def test_the_confirm_tier_advances_only_on_deposits_depth_and_replies():
    good = (variant("A", 1500, 40, 40, 8), variant("B", 1500, 40, 40, 7))
    assert decide(card(*good, deposits=3, engaged=0.4), prereg("confirm"))["decision"] == "advance"
    silent = decide(card(*good, deposits=3, engaged=0.4, flags=["silent_list"]), prereg("confirm"))
    assert (silent["decision"], silent["rule"]) == ("kill", "kill_default")
    shallow = decide(card(*good, deposits=3, engaged=0.2), prereg("confirm"))
    assert shallow["decision"] == "kill"
    few = decide(card(*good, deposits=2, engaged=0.6), prereg("confirm"))
    assert (few["decision"], few["rule"]) == ("kill", "kill_default")


def test_a_verdict_before_the_window_ends_is_provisional():
    out = decide(card(variant("A", 1000, 20, 20, 4), variant("B", 1000, 20, 20, 3), window_complete=False), prereg())
    assert out["provisional"] is True and out["next_step"].endswith("(provisional: the pre-registered window is still running)")
