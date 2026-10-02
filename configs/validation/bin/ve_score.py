"""Bot filter, scorecard and the pre-registered verdict (docs/validation_engine.md).

Everything here is deterministic and reads only the idea's state folder, so the same data always
gives the same scorecard and the same verdict:

- `build_sessions` turns raw page events (and form posts) into one record per visit: attribution
  (UTM, ad, framing), dwell, scroll depth, whether "how it works" was reached, and what the visitor did.
- `classify` is the bot / junk filter: under 2 s, data-centre address, bot user agent, automated
  browser. Raw "visits" mean nothing; every dropped visit keeps its reasons.
- `build_scorecard` rolls the ad report, real visits, signups, deposits and the concierge log into the
  spec's scorecard schema (plus per-framing and per-channel numbers, the filter's own numbers and
  the quality flags).
- `decide` applies the pre-registered rules in order against the hash-locked bars and returns
  advance / pivot / kill with the rule that fired and every rule it checked.
- `size_confirm` sizes the confirm-tier spend for a survivor.
"""

from __future__ import annotations

import ipaddress
import math
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ve_common import (
    DEFAULT_WINDOW_DAYS,
    dump_yaml,
    iso,
    read_json,
    read_jsonl,
    today_utc,
    verify_preregistration,
    write_json,
    write_text,
)
from ve_traffic import CHANNELS

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------------------------------
# Bot / junk filter
# ---------------------------------------------------------------------------------------------------

BOT_UA = re.compile(
    r"(bot\b|bot/|crawl|spider|slurp|headless|phantomjs|selenium|puppeteer|playwright|lighthouse|"
    r"pagespeed|python-requests|python-urllib|curl/|wget|go-http-client|okhttp|java/|axios|node-fetch|"
    r"scrapy|facebookexternalhit|adsbot|mediapartners|bingpreview|uptime|pingdom|statuscake)",
    re.IGNORECASE,
)

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def load_cidrs(extra: Iterable[str] = ()) -> list[_Network]:
    """The data-centre blocks shipped next to this file, plus any extra blocks given."""
    nets: list[_Network] = []
    lines = (HERE / "datacenter_cidrs.txt").read_text().splitlines() + list(extra)
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if line:
            nets.append(ipaddress.ip_network(line, strict=False))
    return nets


def in_cidrs(ip: str, nets: list[_Network]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr.version == n.version and addr in n for n in nets)


def _channel_of(ad_id: str | None, utm_source: str | None) -> str | None:
    short = (ad_id or "").split("-", 1)[0]
    for name, meta in CHANNELS.items():
        if short and meta["short"] == short:
            return name
    for name, meta in CHANNELS.items():
        if utm_source and meta["utm_source"] == utm_source:
            return name
    return None


def build_sessions(events: list[dict[str, Any]], forms: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """One record per visit (the page's session id), from the page events and the form posts."""
    sessions: dict[str, dict[str, Any]] = {}
    for ev in sorted(events, key=lambda e: (str(e.get("ts") or ""), float(e.get("seconds") or 0.0))):
        sid = str(ev.get("session_id") or "")
        if not sid:
            continue
        s = sessions.get(sid)
        if s is None:
            s = sessions[sid] = {
                "session_id": sid,
                "first_ts": ev.get("ts"),
                "ip": ev.get("ip") or "",
                "ua": ev.get("ua") or "",
                "country": ev.get("country"),
                "variant": None,
                "utm": {},
                "ad_id": None,
                "sim": False,
                "seconds": 0.0,
                "max_scroll": 0,
                "reached_how": False,
                "webdriver": False,
                "pages": [],
                "events": Counter(),
                "email": "",
                "followup_answer": "",
            }
        name = str(ev.get("event") or "")
        s["events"][name] += 1
        page = str(ev.get("page") or "")
        if page and page not in s["pages"]:
            s["pages"].append(page)
        if s["variant"] is None and page == "landing" and ev.get("variant"):
            s["variant"] = str(ev["variant"])
        for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"):
            if ev.get(k) and k not in s["utm"]:
                s["utm"][k] = str(ev[k])
        if ev.get("ve_ad") and not s["ad_id"]:
            s["ad_id"] = str(ev["ve_ad"])
        if str(ev.get("sim") or "") == "1":
            s["sim"] = True
        try:
            s["seconds"] = max(s["seconds"], float(ev.get("seconds") or 0.0))
        except (TypeError, ValueError):
            pass
        props = ev.get("props") if isinstance(ev.get("props"), dict) else {}
        scroll = props.get("pct") if name == "scroll" else None
        for value in (ev.get("max_scroll"), scroll):
            try:
                s["max_scroll"] = max(s["max_scroll"], int(value or 0))
            except (TypeError, ValueError):
                pass
        if name == "section_view" and props.get("section") == "how":
            s["reached_how"] = True
        if ev.get("webdriver") is True or str(ev.get("webdriver")).lower() == "true":
            s["webdriver"] = True
    for row in forms:
        sid = str(row.get("session_id") or "")
        s = sessions.get(sid)
        if s is None:
            continue
        form = row.get("form")
        if form == "signup":
            s["events"]["form_signup"] += 1
            s["email"] = str(row.get("email") or s["email"]).strip().lower()
        elif form == "followup":
            s["events"]["form_followup"] += 1
            s["followup_answer"] = str(row.get("answer") or "")[:500]
        elif form == "call":
            s["events"]["form_call"] += 1
            s["email"] = s["email"] or str(row.get("email") or "").strip().lower()
    for s in sessions.values():
        ev = s["events"]
        s["signup"] = bool(ev["signup"] or ev["form_signup"])
        s["followup"] = bool(ev["followup_answer"] or ev["form_followup"])
        s["call"] = bool(ev["call_request"] or ev["form_call"])
        s["deposit_click"] = bool(ev["deposit_click"])
        s["channel"] = _channel_of(s["ad_id"], s["utm"].get("utm_source"))
        if s["variant"] is None and s["utm"].get("utm_content"):
            s["variant"] = s["utm"]["utm_content"]
        s["events"] = dict(ev)
    return sessions


def classify(
    s: dict[str, Any],
    *,
    campaign: str,
    countries: list[str],
    bot_filter: dict[str, Any],
    nets: list[_Network],
    live: bool,
) -> tuple[str, list[str]]:
    """(bucket, reasons). bucket: real | bot | internal_test | other_campaign | direct."""
    reasons: list[str] = []
    if float(s["seconds"]) < float(bot_filter.get("min_session_seconds", 2.0)):
        reasons.append("under_2s")
    if bot_filter.get("datacenter_ips", True) and in_cidrs(str(s["ip"]), nets):
        reasons.append("datacenter_ip")
    if bot_filter.get("ua_bots", True) and (not s["ua"] or BOT_UA.search(str(s["ua"]))):
        reasons.append("bot_user_agent")
    if bot_filter.get("webdriver", True) and s["webdriver"]:
        reasons.append("automated_browser")
    if reasons:
        return "bot", reasons
    if live and s["sim"]:
        return "internal_test", ["sim=1 on a live page (someone testing)"]
    got = s["utm"].get("utm_campaign")
    if not got:
        return "direct", ["no UTM campaign (not from an ad)"]
    if got != campaign:
        return "other_campaign", [f"utm_campaign={got}"]
    return "real", []


# ---------------------------------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------------------------------


def _log_comb(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_greater(a: int, n_a: int, b: int, n_b: int) -> float:
    """One-sided Fisher exact p-value that rate a/n_a is higher than b/n_b."""
    a, n_a, b, n_b = int(a), int(n_a), int(b), int(n_b)
    if n_a <= 0 or n_b <= 0:
        return 1.0
    total, hits = n_a + n_b, a + b
    lo, hi = a, min(n_a, hits)
    if lo > hi:
        return 1.0
    log_den = _log_comb(total, n_a)
    p = 0.0
    for x in range(lo, hi + 1):
        if hits - x > n_b or hits - x < 0:
            continue
        p += math.exp(_log_comb(hits, x) + _log_comb(total - hits, n_a - x) - log_den)
    return min(1.0, p)


def _rate(num: float, den: float) -> float:
    return round(num / den, 4) if den else 0.0


# ---------------------------------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------------------------------


def _deposits(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[str]]:
    """(paid deposits, ids refunded at the customer's request). Engine refunds (on kill) are not a no."""
    paid: dict[str, dict[str, Any]] = {}
    customer_refunds: set[str] = set()
    for r in rows:
        rid = str(r.get("id") or "")
        if r.get("status") == "paid" and rid:
            paid.setdefault(rid, r)
        elif r.get("status") == "refunded" and rid:
            if str(r.get("refund_reason") or "").startswith("requested_by_customer"):
                customer_refunds.add(rid)
    return list(paid.values()), customer_refunds


def build_scorecard(
    idea_dir: Path,
    prereg: dict[str, Any],
    copy: dict[str, Any],
    *,
    live: bool,
    evidence: list[dict[str, str]] | None = None,
    extra_cidrs: Iterable[str] = (),
) -> dict[str, Any]:
    """The scorecard for one idea, from everything in its state folder."""
    t = prereg["thresholds"]
    tier = prereg["tier"]
    campaign = f"ve-{prereg['idea_id']}-{tier}"
    countries = [c.upper() for c in prereg.get("countries") or ["US"]]
    nets = load_cidrs(extra_cidrs)
    events = read_jsonl(idea_dir / "events.jsonl")
    forms = read_jsonl(idea_dir / "forms.jsonl")
    sessions = build_sessions(events, forms)

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    reasons: Counter[str] = Counter()
    for s in sessions.values():
        bucket, why = classify(s, campaign=campaign, countries=countries, bot_filter=prereg["bot_filter"], nets=nets, live=live)
        s["bucket"] = bucket
        s["why"] = why
        buckets[bucket].append(s)
        if bucket == "bot":
            reasons.update(why)
    real = buckets["real"]
    in_seg = [s for s in real if not s["country"] or str(s["country"]).upper() in countries]
    out_seg = [s for s in real if s["country"] and str(s["country"]).upper() not in countries]
    unknown_country = sum(1 for s in real if not s["country"])

    # ad platform numbers (this tier only)
    ads = [r for r in read_jsonl(idea_dir / "ad_report.jsonl") if r.get("tier", tier) == tier]
    impressions = sum(int(r.get("impressions") or 0) for r in ads)
    clicks = sum(int(r.get("clicks") or 0) for r in ads)
    spend = round(sum(float(r.get("spend_usd") or 0.0) for r in ads), 2)

    # depth (bot-filtered, in segment)
    eng = prereg["engaged_definition"]

    def engaged(s: dict[str, Any]) -> bool:
        deep = int(s["max_scroll"]) >= int(eng["min_scroll_pct"]) or bool(s["reached_how"])
        return float(s["seconds"]) >= float(eng["min_seconds"]) and deep

    n_seg = len(in_seg)
    engaged_n = sum(1 for s in in_seg if engaged(s))
    scroll90 = sum(1 for s in in_seg if int(s["max_scroll"]) >= 90)
    median_s = round(statistics.median([float(s["seconds"]) for s in in_seg]), 1) if in_seg else 0

    # signups: distinct people (email when known), real + in segment
    signup_keys = {s["email"] or s["session_id"] for s in in_seg if s["signup"]}
    replies = sum(1 for s in in_seg if s["signup"] and s["followup"])
    calls = {s["email"] or s["session_id"] for s in in_seg if s["call"]}

    # deposits: money traced to a real, in-segment visit; refunds the customer asked for are a "no"
    deposit_rows = read_jsonl(idea_dir / "deposits.jsonl")
    paid, refunded = _deposits(deposit_rows)
    refunded_any = {str(r.get("id")) for r in deposit_rows if r.get("status") == "refunded"}
    seg_ids = {s["session_id"] for s in in_seg}
    all_ids = set(sessions)
    dep_counted = [d for d in paid if str(d.get("session_id") or "") in seg_ids and str(d["id"]) not in refunded]
    dep_refunded = [d for d in paid if str(d["id"]) in refunded]
    dep_unattributed = [d for d in paid if str(d.get("session_id") or "") not in all_ids]
    dep_other = [d for d in paid if d not in dep_counted and d not in dep_refunded and d not in dep_unattributed]

    # concierge: activation and repeat use among the people who paid
    payers = {str(d.get("email") or d.get("session_id") or "") for d in dep_counted}
    uses: Counter[str] = Counter(
        str(r.get("customer") or "") for r in read_jsonl(idea_dir / "concierge.jsonl") if r.get("event") == "used"
    )
    activated = sum(1 for p in payers if uses[p] >= 1)
    repeat = sum(1 for p in payers if uses[p] >= 2)

    ctr = _rate(clicks, impressions)
    signup_rate = _rate(len(signup_keys), n_seg)
    ctr_pass = (ctr >= float(t["ctr"])) if impressions >= int(t["min_impressions_for_ctr_call"]) else None
    rate_pass = (signup_rate >= float(t["signup_rate"])) if n_seg >= int(t["min_sessions_for_rate_call"]) else None
    enough_for_commitment = len(dep_counted) >= int(t["deposit_n"]) or len(signup_keys) >= int(t["min_signups_for_commitment_call"])
    commit_pass = (len(dep_counted) >= int(t["deposit_n"])) if enough_for_commitment else None

    # per framing and per channel
    copy_variants = [v for v in copy.get("variants") or [] if isinstance(v, dict)]

    def slice_stats(pred_ad: Any, pred_s: Any) -> dict[str, Any]:
        rows = [r for r in ads if pred_ad(r)]
        imp = sum(int(r.get("impressions") or 0) for r in rows)
        clk = sum(int(r.get("clicks") or 0) for r in rows)
        seg = [s for s in in_seg if pred_s(s)]
        sig = {s["email"] or s["session_id"] for s in seg if s["signup"]}
        ids = {s["session_id"] for s in seg}
        return {
            "impressions": imp,
            "clicks": clk,
            "ctr": _rate(clk, imp),
            "sessions": len(seg),
            "engaged_rate": _rate(sum(1 for s in seg if engaged(s)), len(seg)),
            "signups": len(sig),
            "signup_rate": _rate(len(sig), len(seg)),
            "deposits": sum(1 for d in dep_counted if str(d.get("session_id")) in ids),
            "spend_usd": round(sum(float(r.get("spend_usd") or 0.0) for r in rows), 2),
        }

    variants = []
    for v in copy_variants:
        vid = str(v["id"])
        st = slice_stats(lambda r, vid=vid: str(r.get("variant")) == vid, lambda s, vid=vid: s["variant"] == vid)
        variants.append({"id": vid, "headline": v.get("headline", ""), "framing": v.get("framing", ""), **st})
    by_channel = {}
    for ch in prereg.get("channels") or []:
        by_channel[ch] = {
            "kind": CHANNELS.get(ch, {}).get("kind", "?"),
            **slice_stats(lambda r, ch=ch: r.get("channel") == ch, lambda s, ch=ch: s["channel"] == ch),
        }

    total_sessions = len(sessions)
    bots = len(buckets["bot"])
    flags: list[str] = []
    if not live:
        flags.append("synthetic")
    if total_sessions and bots / total_sessions > float(t["bot_share_flag"]):
        flags.append("bot_spike")
    if real and len(out_seg) / len(real) > float(t["segment_leak_flag"]):
        flags.append("segment_leak")
    small = []
    if impressions < int(t["min_impressions_for_ctr_call"]):
        small.append(f"impressions {impressions} < {t['min_impressions_for_ctr_call']}")
    if n_seg < int(t["min_sessions_for_rate_call"]):
        small.append(f"real visits {n_seg} < {t['min_sessions_for_rate_call']}")
    thin = [v["id"] for v in variants if v["clicks"] < int(t["min_clicks_per_variant_ab"])]
    if thin:
        small.append(f"framing(s) {', '.join(thin)} under {t['min_clicks_per_variant_ab']} clicks: enough to drop a flop, "
                     "too few to name a winner (the confirm tier does that)")
    if small:
        flags.append("sample_too_small")
    if live and clicks and len(buckets["real"]) + bots < 0.5 * clicks:
        flags.append("tracking_gap")
    if len(signup_keys) >= int(t["min_signups_for_silence_flag"]) and replies == 0:
        flags.append("silent_list")
    if dep_unattributed:
        flags.append("unattributed_deposit")
    budget = float(prereg.get("budget_usd") or 0.0)
    if spend > budget + 0.01:
        flags.append("over_budget")

    card: dict[str, Any] = {
        # --- the spec's schema (docs/validation_engine.md, "Scorecard schema") ---
        "idea_id": prereg["idea_id"],
        "run_window": prereg["run_window"],
        "segment": prereg.get("segment") or "",
        "channels": list(prereg.get("channels") or []),
        "funnel": {
            "impressions": {"n": impressions},
            "clicks": {"n": clicks, "ctr": ctr, "threshold": float(t["ctr"]), "pass": ctr_pass},
            "engaged": {"rate": _rate(engaged_n, n_seg), "scroll90": _rate(scroll90, n_seg), "median_seconds": median_s,
                        "n": engaged_n, "threshold": float(t["engaged_rate"])},
            "signups": {"n": len(signup_keys), "rate": signup_rate, "threshold": float(t["signup_rate"]), "pass": rate_pass},
            "commitment": {"deposits": len(dep_counted), "booked_calls": len(calls), "threshold_n": int(t["deposit_n"]),
                           "pass": commit_pass},
            "activation": {"used_concierge": activated},
            "retention": {"repeat_users": repeat},
        },
        "variants": variants,
        "quality_flags": flags,
        "spend_usd": spend,
        "decision": None,
        "evidence": list(evidence or []),
        # --- the engine's own detail ---
        "tier": tier,
        "mode": "live" if live else "dry_run",
        "synthetic": not live,
        "by_channel": by_channel,
        "followup": {"replies": replies, "reply_rate": _rate(replies, len(signup_keys)),
                     "sample": list(dict.fromkeys(s["followup_answer"] for s in in_seg if s["followup_answer"]))[:5]},
        "deposits_detail": {
            "counted": len(dep_counted),
            "refunded_on_request": len(dep_refunded),
            "out_of_segment_or_filtered": len(dep_other),
            "unattributed": len(dep_unattributed),
            "deposit_usd": prereg.get("deposit_usd"),
            # money we still hold: every paid deposit not refunded yet, whoever asked for the refund
            "held": sum(1 for d in paid if str(d["id"]) not in refunded_any),
            "refunded_by_engine": len(refunded_any - refunded),
            "refund_by": prereg.get("refund_by"),
        },
        "filter": {
            "sessions_total": total_sessions,
            "bots_dropped": bots,
            "bot_reasons": dict(reasons),
            "internal_test": len(buckets["internal_test"]),
            "direct": len(buckets["direct"]),
            "other_campaign": len(buckets["other_campaign"]),
            "real": len(real),
            "in_segment": n_seg,
            "out_of_segment": len(out_seg),
            "unknown_country": unknown_country,
            "click_to_session": _rate(len(real) + bots, clicks),
        },
        "budget": {"budget_usd": budget, "spent_usd": spend, "remaining_usd": round(budget - spend, 2)},
        "sample_notes": small,
        "preregistration": {"sha256": prereg.get("sha256"), "verified": verify_preregistration(prereg),
                            "registered_at": prereg.get("registered_at")},
        "updated_at": iso(),
    }
    if live:
        card["window_complete"] = today_utc().isoformat() >= str(prereg["run_window"]["end"])
    else:
        card["window_complete"] = True  # a dry run plays the whole window at once
    truth = read_json(idea_dir / "simulation.json")
    if not live and isinstance(truth, dict) and truth.get("truth"):
        card["filter"]["check"] = filter_check(list(sessions.values()), truth)
    return card


def filter_check(sessions: list[dict[str, Any]], truth: dict[str, Any]) -> dict[str, Any]:
    """Dry run only: the bot filter against the simulator's ground truth, visit by visit (by address)."""
    by_ip = {str(r["ip"]): r for r in truth.get("truth") or []}
    bots_caught = bots_missed = humans_kept = humans_dropped = unmatched = 0
    for s in sessions:
        r = by_ip.get(str(s["ip"]))
        if r is None:
            unmatched += 1
            continue
        dropped = s["bucket"] == "bot"
        if r["bot"]:
            bots_caught += dropped
            bots_missed += not dropped
        else:
            humans_dropped += dropped
            humans_kept += not dropped
    planted_bots = sum(1 for r in by_ip.values() if r["bot"])
    planted_humans = len(by_ip) - planted_bots
    return {
        "planted_bots": planted_bots,
        "planted_humans": planted_humans,
        "bots_caught": bots_caught,
        "bots_missed": bots_missed,
        "humans_kept": humans_kept,
        "humans_dropped": humans_dropped,
        "visits_recorded": len(sessions) - unmatched,
        "visits_unmatched": unmatched,
        "engine": truth.get("engine"),
        "ok": bots_missed == 0 and humans_dropped == 0 and bots_caught == planted_bots and humans_kept == planted_humans,
    }


# ---------------------------------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------------------------------


def _flops(v: dict[str, Any], t: dict[str, Any]) -> bool:
    return (v["sessions"] > 0 and v["signup_rate"] < float(t["signup_rate_weak"])) or (
        v["impressions"] > 0 and v["ctr"] < float(t["ctr_kill"])
    )


def pivot_check(variants: list[dict[str, Any]], t: dict[str, Any]) -> dict[str, Any] | None:
    """A framing that clearly works next to one that flops, by a big and significant margin."""
    vs = [v for v in variants if v["sessions"] > 0 or v["impressions"] > 0]
    if len(vs) < 2:
        return None
    checks = (
        ("signup_rate", "signups", "sessions", float(t["signup_rate"]), float(t["signup_rate_weak"])),
        ("ctr", "clicks", "impressions", float(t["ctr"]), float(t["ctr_kill"])),
    )
    for metric, num, den, works_bar, flop_bar in checks:
        best = max(vs, key=lambda v, m=metric: (v[m], v["signups"], v["clicks"]))
        worst = min(vs, key=lambda v, m=metric: (v[m], v["signups"], v["clicks"]))
        if best is worst or not best[den] or not worst[den]:
            continue
        ratio = math.inf if worst[metric] == 0 else best[metric] / worst[metric]
        p = fisher_greater(best[num], best[den], worst[num], worst[den])
        ok = best[metric] >= works_bar and worst[metric] < flop_bar and ratio >= float(t["pivot_ratio"]) and p < float(t["pivot_alpha"])
        if ok:
            return {
                "metric": metric,
                "best": best["id"],
                "worst": worst["id"],
                "best_value": best[metric],
                "worst_value": worst[metric],
                "ratio": "inf" if ratio == math.inf else round(ratio, 2),
                "p_value": round(p, 4),
                "keep": [v["id"] for v in variants if not _flops(v, t)],
            }
    return None


def decide(card: dict[str, Any], prereg: dict[str, Any]) -> dict[str, Any]:
    """Apply the pre-registered rules, in order. Returns {decision, rule, reason, trace, next_step}."""
    if not verify_preregistration(prereg):
        return {
            "decision": None,
            "rule": "preregistration_changed",
            "reason": "the pre-registered bars no longer match their hash: no verdict until a new test is registered",
            "trace": [],
            "next_step": "register a fresh test; never move a bar after the data is in",
        }
    t = prereg["thresholds"]
    tier = prereg["tier"]
    f = card["funnel"]
    variants = card["variants"]
    impressions = f["impressions"]["n"]
    ctr = f["clicks"]["ctr"]
    sessions = card["filter"]["in_segment"]
    signups = f["signups"]["n"]
    rate = f["signups"]["rate"]
    deposits = f["commitment"]["deposits"]
    calls = f["commitment"]["booked_calls"]
    engaged = f["engaged"]["rate"]
    silent = "silent_list" in card["quality_flags"]
    trace: list[dict[str, Any]] = []

    def check(rule: str, fired: bool, why: str) -> bool:
        trace.append({"rule": rule, "fired": bool(fired), "why": why})
        return bool(fired)

    any_ctr = any(v["ctr"] >= float(t["ctr"]) for v in variants)
    any_rate = any(v["signup_rate"] >= float(t["signup_rate"]) for v in variants)
    if check(
        "kill_ctr",
        impressions >= int(t["min_impressions_for_ctr_call"]) and ctr < float(t["ctr_kill"]) and not any_ctr,
        f"CTR {ctr:.2%} over {impressions} impressions (kill under {float(t['ctr_kill']):.2%}; a framing at "
        f"{float(t['ctr']):.2%}+ rescues it: {'yes' if any_ctr else 'no'})",
    ):
        return _verdict("kill", "kill_ctr", "the pain headline does not land: near-zero CTR", trace, card, prereg)
    if check(
        "kill_no_commitment",
        signups >= int(t["min_signups_for_commitment_call"]) and deposits == 0 and calls == 0,
        f"{signups} signups, {deposits} deposits, {calls} booked calls (judged from {t['min_signups_for_commitment_call']} signups)",
    ):
        return _verdict("kill", "kill_no_commitment", "signups but no commitment: a nice-to-have, not a must-have", trace, card, prereg)
    if check(
        "kill_signup_rate",
        sessions >= int(t["min_sessions_for_rate_call"]) and rate < float(t["signup_rate_weak"]) and not any_rate,
        f"signup rate {rate:.1%} over {sessions} real visits (kill under {float(t['signup_rate_weak']):.0%}; a framing at "
        f"{float(t['signup_rate']):.0%}+ rescues it: {'yes' if any_rate else 'no'})",
    ):
        return _verdict("kill", "kill_signup_rate", "visitors read it and do not raise a hand", trace, card, prereg)

    pivot = pivot_check(variants, t)
    pivot_why = (
        f"{pivot['best']} {pivot['metric']} {pivot['best_value']} vs {pivot['worst']} {pivot['worst_value']} "
        f"(x{pivot['ratio']}, p={pivot['p_value']})"
        if pivot
        else "no framing both clearly works and beats a flopping one by a significant margin"
    )
    if tier == "screen":
        if check("pivot", pivot is not None, pivot_why):
            assert pivot is not None
            return _verdict("pivot", "pivot", f"framing {pivot['best']} works and {pivot['worst']} flops", trace, card, prereg,
                            pivot=pivot)
        check("advance", True, "no kill rule fired: the screen only kills duds")
        return _verdict("advance", "advance", "survived the screen: earns the confirm-tier spend", trace, card, prereg)

    cleared = deposits >= int(t["deposit_n"]) and engaged >= float(t["engaged_rate"]) and not silent
    if check(
        "advance",
        cleared,
        f"{deposits} deposits (bar {t['deposit_n']}), engaged {engaged:.0%} (bar {float(t['engaged_rate']):.0%}), "
        f"follow-up {'silent' if silent else 'answered'}",
    ):
        return _verdict("advance", "advance", "cleared the commitment bar with real depth and replies", trace, card, prereg)
    if check("pivot", pivot is not None, pivot_why):
        assert pivot is not None
        return _verdict("pivot", "pivot", f"framing {pivot['best']} works and {pivot['worst']} flops", trace, card, prereg,
                        pivot=pivot)
    check("kill_default", True, "did not clear the commitment bar")
    return _verdict("kill", "kill_default", "did not clear the commitment bar: a clean no", trace, card, prereg)


def _verdict(
    decision: str,
    rule: str,
    reason: str,
    trace: list[dict[str, Any]],
    card: dict[str, Any],
    prereg: dict[str, Any],
    pivot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tier = prereg["tier"]
    out: dict[str, Any] = {"decision": decision, "rule": rule, "reason": reason, "trace": trace, "pivot": pivot}
    if decision == "kill":
        out["next_step"] = "stop spending on this idea; refund every deposit in full (the engine does it in live mode)"
        out["confirm_sizing"] = None
    elif tier == "screen":
        keep = pivot["keep"] if pivot else [v["id"] for v in card["variants"]]
        out["confirm_sizing"] = size_confirm(card, prereg, keep)
        out["next_step"] = (
            f"run the confirm tier on framing(s) {', '.join(keep)}"
            + (" (drop the flop)" if pivot else "")
            + f": {out['confirm_sizing']['summary']}"
        )
    else:
        out["confirm_sizing"] = None
        out["next_step"] = (
            "run the concierge for the people who paid and watch for repeat use (activation, retention)"
            if decision == "advance"
            else f"re-test with framing {pivot['best'] if pivot else '?'} only"
        )
    out["provisional"] = not card.get("window_complete", True)
    if out["provisional"]:
        out["next_step"] += " (provisional: the pre-registered window is still running)"
    return out


def size_confirm(card: dict[str, Any], prereg: dict[str, Any], keep: list[str]) -> dict[str, Any]:
    """Confirm-tier spend for a survivor: enough clicks per kept framing to call a winner, capped."""
    t = prereg["thresholds"]
    limits = prereg.get("confirm_clicks") or {"min": 150, "max": 300}
    n = max(1, len(keep))
    target = int(min(max(int(t["min_clicks_per_variant_ab"]) * n, int(limits["min"])), int(limits["max"])))
    clicks = int(card["funnel"]["clicks"]["n"])
    spend = float(card.get("spend_usd") or 0.0)
    if clicks > 0 and spend > 0:
        cpc, basis = round(spend / clicks, 2), f"observed CPC from the screen (${spend:.2f} / {clicks} clicks)"
    else:
        cpc, basis = float(prereg.get("assumed_cpc_usd") or 2.0), "assumed CPC (the spec's ~$2/click; no paid clicks yet)"
    needed = float(math.ceil(target * cpc / 10.0) * 10)
    budget = prereg.get("confirm_budget_usd")
    if budget is None:
        recommended, owner_ok = needed, True
        note = "no confirm-tier budget is set: the owner sets one before any confirm spend"
    elif needed <= float(budget):
        recommended, owner_ok = needed, False
        note = f"within the owner's confirm budget (${float(budget):.0f})"
    else:
        recommended, owner_ok = float(budget), True
        note = (
            f"needs ${needed:.0f}, above the owner's confirm budget ${float(budget):.0f}: the budget buys "
            f"~{int(float(budget) / cpc)} clicks; ask the owner before going above it"
        )
    return {
        "framings": keep,
        "target_clicks": target,
        "cpc_usd": cpc,
        "cpc_basis": basis,
        "needed_usd": needed,
        "recommended_usd": recommended,
        "window_days": DEFAULT_WINDOW_DAYS["confirm"],
        "needs_owner_ok": owner_ok,
        "note": note,
        "summary": f"~{target} clicks x ${cpc:.2f} = ${needed:.0f} over {DEFAULT_WINDOW_DAYS['confirm']} days ({note})",
    }


# ---------------------------------------------------------------------------------------------------
# Report + the whole step
# ---------------------------------------------------------------------------------------------------


def _diagnostics(card: dict[str, Any], t: dict[str, Any]) -> list[str]:
    f = card["funnel"]
    out = []
    if f["clicks"]["ctr"] >= float(t["ctr"]) and f["signups"]["rate"] < float(t["signup_rate_weak"]) and card["filter"]["in_segment"]:
        out.append("great CTR + no signups: the headline oversells what the page delivers")
    if f["signups"]["n"] >= int(t["min_signups_for_commitment_call"]) and f["commitment"]["deposits"] == 0:
        out.append("many signups + no deposits: nice-to-have, not must-have")
    # Repeat use takes time: the concierge serves survivors, so it is read on a finished confirm test only.
    finished_confirm = card.get("tier") == "confirm" and card.get("window_complete", True)
    if finished_confirm and f["commitment"]["deposits"] and f["activation"]["used_concierge"] and not f["retention"]["repeat_users"]:
        out.append("deposits + no repeat use: one-off novelty, not a business")
    chans = card.get("by_channel") or {}
    search = [c for c in chans.values() if c.get("kind") == "search" and c["sessions"]]
    cold = [c for c in chans.values() if c.get("kind") == "cold" and c["sessions"]]
    if search and cold:
        s_ok = any(c["signup_rate"] >= float(t["signup_rate"]) for c in search)
        c_ok = any(c["signup_rate"] >= float(t["signup_rate"]) for c in cold)
        if s_ok and not c_ok:
            out.append("search works, cold does not: the market exists but may be small")
        elif c_ok:
            out.append("cold traffic converts: demand can be created, room to grow")
    return out


def _yes(passed: bool | None) -> str:
    return "not judged yet" if passed is None else ("yes" if passed else "no")


def render_report(card: dict[str, Any], verdict: dict[str, Any], prereg: dict[str, Any]) -> str:
    f = card["funnel"]
    t = prereg["thresholds"]
    lines = [f"# Validation Engine scorecard: {card['idea_id']} ({card['tier']} tier)", ""]
    if card["synthetic"]:
        lines += [
            "> **DRY RUN — SYNTHETIC DATA.** Zero spend, a local test URL and a simulated crowd (with planted bots). "
            "These numbers test the engine, not the idea; the verdict below is the engine's rules applied to fake "
            "visitors and is not evidence about the market.",
            "",
        ]
    verdict_word = (verdict.get("decision") or "none").upper()
    lines += [
        f"**Verdict: {verdict_word}** (rule `{verdict.get('rule')}`): {verdict.get('reason')}.",
        f"Next: {verdict.get('next_step')}",
        "",
        f"Window {card['run_window']['start']} to {card['run_window']['end']} | segment `{card['segment'] or '-'}` | "
        f"channels {', '.join(card['channels'])} | spend ${card['spend_usd']:.2f} of ${card['budget']['budget_usd']:.2f}",
        "",
        "## Funnel (bot-filtered, in segment)",
        "",
        "| step | value | bar | pass |",
        "|---|---|---|---|",
        f"| impressions | {f['impressions']['n']} | | |",
        f"| clicks (CTR) | {f['clicks']['n']} ({f['clicks']['ctr']:.2%}) | {f['clicks']['threshold']:.2%} | {_yes(f['clicks']['pass'])} |",
        f"| real visits | {card['filter']['in_segment']} | | |",
        f"| engaged | {f['engaged']['rate']:.0%} (scroll 90%: {f['engaged']['scroll90']:.0%}, median {f['engaged']['median_seconds']} s) "
        f"| {f['engaged']['threshold']:.0%} | |",
        f"| signups | {f['signups']['n']} ({f['signups']['rate']:.1%}) | {f['signups']['threshold']:.0%} | {_yes(f['signups']['pass'])} |",
        f"| follow-up replies | {card['followup']['replies']} ({card['followup']['reply_rate']:.0%} of signups) | | |",
        f"| deposits / booked calls | {f['commitment']['deposits']} / {f['commitment']['booked_calls']} | "
        f"{f['commitment']['threshold_n']} deposits | {_yes(f['commitment']['pass'])} |",
        f"| used the concierge | {f['activation']['used_concierge']} | | |",
        f"| repeat users | {f['retention']['repeat_users']} | | |",
        "",
        "## Framings (A/B on the value proposition)",
        "",
        "| id | headline | impr | clicks | CTR | visits | signups | rate | deposits |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for v in card["variants"]:
        lines.append(
            f"| {v['id']} | {v['headline']} | {v['impressions']} | {v['clicks']} | {v['ctr']:.2%} | {v['sessions']} | "
            f"{v['signups']} | {v['signup_rate']:.0%} | {v['deposits']} |"
        )
    lines += ["", "## Channels", "", "| channel | kind | clicks | CTR | visits | signups | rate | spend |", "|---|---|---|---|---|---|---|---|"]
    for ch, c in (card.get("by_channel") or {}).items():
        lines.append(
            f"| {ch} | {c['kind']} | {c['clicks']} | {c['ctr']:.2%} | {c['sessions']} | {c['signups']} | {c['signup_rate']:.0%} | ${c['spend_usd']:.2f} |"
        )
    fl = card["filter"]
    lines += [
        "",
        "## Bot / junk filter",
        "",
        f"{fl['sessions_total']} visits recorded; {fl['bots_dropped']} dropped as bots/junk ({', '.join(f'{k} {v}' for k, v in fl['bot_reasons'].items()) or 'none'}); "
        f"{fl['direct']} direct, {fl['other_campaign']} other campaign, {fl['internal_test']} internal test; "
        f"{fl['real']} real ({fl['in_segment']} in segment, {fl['out_of_segment']} outside). Ad clicks -> recorded visits: {fl['click_to_session']:.0%}.",
    ]
    chk = fl.get("check")
    if chk:
        lines += [
            "",
            f"Filter vs the simulator's ground truth ({chk['engine']}): bots caught {chk['bots_caught']}/{chk['planted_bots']}, "
            f"humans kept {chk['humans_kept']}/{chk['planted_humans']}, bots missed {chk['bots_missed']}, humans wrongly dropped "
            f"{chk['humans_dropped']} -> {'OK' if chk['ok'] else 'NOT OK'}.",
        ]
    lines += ["", "## Quality flags", ""]
    lines += [f"- {q}" for q in card["quality_flags"]] or ["- none"]
    lines += [f"  - {n}" for n in card.get("sample_notes") or []]
    diags = _diagnostics(card, t)
    if diags:
        lines += ["", "## Diagnostics", ""] + [f"- {d}" for d in diags]
    lines += ["", "## Pre-registered rules, in order", ""]
    for step in verdict.get("trace") or []:
        lines.append(f"- {'**FIRED**' if step['fired'] else 'no'} `{step['rule']}`: {step['why']}")
    dd = card.get("deposits_detail") or {}
    lines += [
        "",
        "## Deposits (fully refundable)",
        "",
        f"{dd.get('held', 0)} held, {dd.get('refunded_on_request', 0)} refunded on request, {dd.get('refunded_by_engine', 0)} "
        f"refunded by the engine; ${dd.get('deposit_usd')} each. The page promises a full refund if nothing launches within "
        f"90 days: refund every deposit still held by **{dd.get('refund_by') or '-'}** unless it has launched "
        f"(`ve.py refund --dir <idea folder> --why no-launch`).",
    ]
    cs = verdict.get("confirm_sizing")
    if cs:
        lines += ["", "## Confirm-tier sizing", "", f"- {cs['summary']}", f"- CPC basis: {cs['cpc_basis']}",
                  f"- needs the owner's OK: {cs['needs_owner_ok']}"]
    lines += ["", "## Evidence", ""]
    lines += [f"- {e.get('what')}: {e.get('link')}" for e in card.get("evidence") or []] or ["- none yet"]
    pr = card["preregistration"]
    lines += ["", f"Pre-registration sha256 `{pr['sha256']}` ({'verified' if pr['verified'] else 'CHANGED'}), registered {pr['registered_at']}.", ""]
    return "\n".join(lines)


def score(
    idea_dir: Path,
    *,
    live: bool,
    evidence: list[dict[str, str]] | None = None,
    extra_cidrs: Iterable[str] = (),
) -> dict[str, Any]:
    """Build the scorecard, decide, and write scorecard.{yaml,json}, decision.json and report.md."""
    prereg = read_json(idea_dir / "preregistration.json")
    if not isinstance(prereg, dict):
        raise FileNotFoundError(f"{idea_dir / 'preregistration.json'} is missing: ve_setup writes it")
    copy = read_json(idea_dir / "page" / "copy.json") or {}
    card = build_scorecard(idea_dir, prereg, copy, live=live, evidence=evidence, extra_cidrs=extra_cidrs)
    verdict = decide(card, prereg)
    card["decision"] = verdict["decision"]
    card["decision_rule"] = verdict["rule"]
    card["decision_reason"] = verdict["reason"]
    card["next_step"] = verdict["next_step"]
    card["diagnostics"] = _diagnostics(card, prereg["thresholds"])
    if verdict.get("confirm_sizing"):
        card["confirm_sizing"] = verdict["confirm_sizing"]
    write_json(idea_dir / "scorecard.json", card)
    write_text(idea_dir / "scorecard.yaml", dump_yaml(card))
    write_json(idea_dir / "decision.json", verdict)
    write_text(idea_dir / "report.md", render_report(card, verdict, prereg))
    return {"card": card, "verdict": verdict}
