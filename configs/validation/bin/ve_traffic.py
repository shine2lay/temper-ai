"""The campaign plan (budgets, UTM scheme, targeting) and the no-spend dry-run traffic simulator.

`build_plan` is used by both modes: it splits the tier's budget evenly over every channel x variant
(one variable at a time: same budget, same audience, only the framing changes), tags every ad URL
with the UTM scheme, and writes the targeting. In live mode ve_campaign launches exactly this plan;
in a dry run the plan's budget is $0 and `simulate` plays synthetic visitors through it instead.

The simulator drives a real headless browser through the real page, so the page's own
instrumentation produces every event (when no browser is available it posts the same events over
HTTP and says so). It plants known bots among the visitors -- too fast, data-centre address, bot
user agent, webdriver -- so the dry run also measures the bot filter against ground truth.
Everything it writes is marked synthetic; none of it is evidence about the idea.
"""

from __future__ import annotations

import json
import random
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from ve_common import append_jsonl, iso, read_jsonl, write_json

# ---------------------------------------------------------------------------------------------------
# Campaign plan + UTM scheme
# ---------------------------------------------------------------------------------------------------

CHANNELS: dict[str, dict[str, str]] = {
    # search captures existing intent; cold social tests whether demand can be created
    "google-search": {"utm_source": "google", "utm_medium": "cpc", "kind": "search", "short": "gs"},
    "reddit-ads": {"utm_source": "reddit", "utm_medium": "paid-social", "kind": "cold", "short": "rd"},
    "meta-ads": {"utm_source": "meta", "utm_medium": "paid-social", "kind": "cold", "short": "mt"},
}


def utm_url(base_url: str, *, idea_id: str, tier: str, channel: str, variant: str, ad_id: str) -> str:
    """The landing URL of one ad. Every signup/deposit traces back to source, framing and ad."""
    meta = CHANNELS[channel]
    params = {
        "utm_source": meta["utm_source"],
        "utm_medium": meta["utm_medium"],
        "utm_campaign": f"ve-{idea_id}-{tier}",
        "utm_content": variant,
        "ve_ad": ad_id,
    }
    query = urlencode(params)
    if meta["kind"] == "search":
        query += "&utm_term={keyword}"  # Google fills in the matched keyword (ValueTrack)
    return f"{base_url.rstrip('/')}/{variant.lower()}/?{query}"


def build_plan(prereg: dict[str, Any], copy: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Every ad of the test, with a lifetime budget cap each; the caps never add up past the budget."""
    channels = [c for c in prereg.get("channels") or [] if c in CHANNELS]
    if not channels:
        raise ValueError(f"no known channel in {prereg.get('channels')}; known: {', '.join(CHANNELS)}")
    variants = [v for v in copy.get("variants") or [] if isinstance(v, dict)]
    budget = float(prereg.get("budget_usd") or 0.0)
    n_ads = len(channels) * len(variants)
    per_ad = int(budget * 100 / n_ads) / 100 if n_ads else 0.0  # floor to the cent
    keywords = list(copy.get("keywords") or [])
    ads: list[dict[str, Any]] = []
    for channel in channels:
        meta = CHANNELS[channel]
        for v in variants:
            vid = str(v["id"])
            ad_id = f"{meta['short']}-{vid}"
            ad = v.get("ad") or {}
            url = utm_url(base_url, idea_id=prereg["idea_id"], tier=prereg["tier"], channel=channel, variant=vid, ad_id=ad_id)
            targeting: dict[str, Any] = {"countries": prereg.get("countries") or ["US"]}
            if meta["kind"] == "search":
                targeting["keywords"] = keywords or list(ad.get("keywords") or [])
                targeting["match"] = "phrase"
            else:
                targeting["audience"] = copy.get("audience", "")
                targeting["interests"] = list(copy.get("interests") or [])
            ads.append(
                {
                    "ad_id": ad_id,
                    "channel": channel,
                    "kind": meta["kind"],
                    "variant": vid,
                    "framing": v.get("framing", ""),
                    "creative": {"headline": ad.get("headline", ""), "body": ad.get("body", "")},
                    "url": url,
                    "path": url[len(base_url.rstrip("/")) :],
                    "lifetime_budget_usd": per_ad,
                    "targeting": targeting,
                }
            )
    total = round(sum(a["lifetime_budget_usd"] for a in ads), 2)
    if total > budget + 1e-9:  # pragma: no cover - the floor above makes this impossible
        raise ValueError(f"plan total ${total} exceeds budget ${budget}")
    return {
        "idea_id": prereg["idea_id"],
        "tier": prereg["tier"],
        "mode": prereg["mode"],
        "base_url": base_url,
        "window": prereg["run_window"],
        "budget_usd": budget,
        "planned_total_usd": total,
        "tier_budget_usd": prereg.get("tier_budget_usd"),
        "rules": [
            "one variable at a time: same budget and audience for every framing within a channel",
            "lifetime budget caps per ad (never a daily budget with no end date)",
            f"run the full window ({prereg['run_window']['start']} to {prereg['run_window']['end']}), >= 5-7 days",
            "no organic posting, no DMs, no cold outreach: paid placements only",
        ],
        "utm_scheme": {
            "utm_source": "google | reddit | meta",
            "utm_medium": "cpc (search) | paid-social (cold)",
            "utm_campaign": f"ve-{prereg['idea_id']}-{prereg['tier']}",
            "utm_content": "variant id (A/B/C)",
            "utm_term": "matched keyword (search only)",
            "ve_ad": "ad id (<channel short>-<variant>)",
        },
        "ads": ads,
        "planned_at": iso(),
    }


# ---------------------------------------------------------------------------------------------------
# Dry-run simulator
# ---------------------------------------------------------------------------------------------------

HUMAN_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36",
]
HEADLESS_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/129.0.0.0 Safari/537.36"
CRAWLER_UA = "AdsBot-Google (+http://www.google.com/adsbot.html)"
# Residential-looking addresses (documentation-safe would be 192.0.2.x, but the filter must see
# realistic public space): US cable/fibre blocks, plus a few non-target countries for segment checks.
HUMAN_NETS = {"US": ["73.{}.{}.{}", "98.{}.{}.{}", "24.{}.{}.{}", "71.{}.{}.{}"], "IN": ["117.{}.{}.{}"], "PH": ["112.{}.{}.{}"]}
DC_NETS = ["3.{}.{}.{}", "34.{}.{}.{}", "167.99.{}.{}", "52.{}.{}.{}"]


@dataclass
class Visitor:
    """One synthetic click on an ad, with the behaviour it will play on the page."""

    persona: str
    ad: dict[str, Any]
    ua: str
    ip: str
    country: str
    dwell_s: float
    scroll_to: int  # percent of the page
    signup: bool = False
    followup: bool = False
    deposit: bool = False
    call: bool = False
    bot: bool = False
    hide_webdriver: bool = True
    email: str = ""
    keyword: str = ""


# persona -> (dwell range s, scroll %, actions, bot?)
PERSONAS: dict[str, dict[str, Any]] = {
    "bounce": {"dwell": (3.0, 6.0), "scroll": 15},
    "skim": {"dwell": (8.0, 14.0), "scroll": 60},
    "reader": {"dwell": (20.0, 45.0), "scroll": 100},
    "signup": {"dwell": (25.0, 50.0), "scroll": 100, "signup": True},
    "signup_reply": {"dwell": (30.0, 60.0), "scroll": 100, "signup": True, "followup": True},
    "depositor": {"dwell": (35.0, 70.0), "scroll": 100, "signup": True, "followup": True, "deposit": True},
    "caller": {"dwell": (30.0, 55.0), "scroll": 100, "signup": True, "call": True},
    "bot_fast": {"dwell": (0.3, 1.2), "scroll": 0, "bot": True, "ua": "headless", "hide_webdriver": False},
    "bot_crawler": {"dwell": (1.0, 1.8), "scroll": 0, "bot": True, "ua": "crawler", "hide_webdriver": False},
    "bot_datacenter": {"dwell": (6.0, 9.0), "scroll": 60, "bot": True, "dc": True},
}

# A synthetic market: framing A lands, B flops, C is in between. Counts are per channel.
DEFAULT_MIX: dict[str, dict[str, int]] = {
    "A": {"bounce": 3, "skim": 2, "reader": 2, "signup": 1, "signup_reply": 1, "depositor": 1, "caller": 1,
          "bot_fast": 1, "bot_crawler": 0, "bot_datacenter": 1},
    "B": {"bounce": 6, "skim": 2, "reader": 1, "signup": 0, "signup_reply": 0, "depositor": 0, "caller": 0,
          "bot_fast": 1, "bot_crawler": 1, "bot_datacenter": 0},
    "C": {"bounce": 4, "skim": 2, "reader": 2, "signup": 1, "signup_reply": 0, "depositor": 0, "caller": 0,
          "bot_fast": 0, "bot_crawler": 1, "bot_datacenter": 1},
}
SYNTHETIC_CTR = {"A": 0.012, "B": 0.004, "C": 0.008}


def _ip(rng: random.Random, pattern: str) -> str:
    parts = [rng.randint(1, 254) for _ in range(pattern.count("{}"))]
    return pattern.format(*parts)


def make_visitors(plan: dict[str, Any], seed: int = 7, mix: dict[str, dict[str, int]] | None = None) -> list[Visitor]:
    """The synthetic visitors for every ad of the plan (seeded: the same plan gives the same crowd)."""
    rng = random.Random(seed)
    mix = mix or DEFAULT_MIX
    visitors: list[Visitor] = []
    n = 0
    for ad in plan["ads"]:
        counts = mix.get(ad["variant"], mix["C"])
        for persona, count in counts.items():
            spec = PERSONAS[persona]
            for _ in range(count):
                n += 1
                bot = bool(spec.get("bot"))
                if spec.get("ua") == "headless":
                    ua = HEADLESS_UA
                elif spec.get("ua") == "crawler":
                    ua = CRAWLER_UA
                else:
                    ua = rng.choice(HUMAN_UAS)
                if spec.get("dc"):
                    ip, country = _ip(rng, rng.choice(DC_NETS)), "US"
                else:
                    country = "US" if rng.random() < 0.9 else rng.choice(["IN", "PH"])
                    ip = _ip(rng, rng.choice(HUMAN_NETS[country]))
                keywords = ad["targeting"].get("keywords") or []
                visitors.append(
                    Visitor(
                        persona=persona,
                        ad=ad,
                        ua=ua,
                        ip=ip,
                        country=country,
                        dwell_s=round(rng.uniform(*spec["dwell"]), 1),
                        scroll_to=int(spec["scroll"]),
                        signup=bool(spec.get("signup")),
                        followup=bool(spec.get("followup")),
                        deposit=bool(spec.get("deposit")),
                        call=bool(spec.get("call")),
                        bot=bot,
                        hide_webdriver=bool(spec.get("hide_webdriver", True)),
                        email=f"sim{n:03d}@example.test",
                        keyword=rng.choice(keywords) if keywords else "",
                    )
                )
    rng.shuffle(visitors)
    return visitors


FOLLOWUP_ANSWERS = [
    "Right now it's a spreadsheet and a lot of phone tag; it eats most of Monday.",
    "We post on two job boards and I screen every applicant by hand at night.",
    "Honestly we just hire whoever shows up first and it costs us in no-shows.",
]


def _landing_path(v: Visitor) -> str:
    """The ad's own UTM-tagged path, as the platform would fill it in, marked synthetic (`sim=1`)."""
    return v.ad["path"].replace("{keyword}", v.keyword.replace(" ", "+") or "none") + "&sim=1"


def _answer_for(v: Visitor) -> str:
    digits = "".join(ch for ch in v.email if ch.isdigit()) or "0"
    return FOLLOWUP_ANSWERS[int(digits) % len(FOLLOWUP_ANSWERS)]


def _play_browser(v: Visitor, base_url: str, browser: Any) -> None:
    """One visit in a real browser: the page's own ve.js sends every event."""
    headers = {"X-Forwarded-For": v.ip, "X-VE-Country": v.country}
    mobile = "Mobile" in v.ua or "iPhone" in v.ua
    ctx = browser.new_context(
        user_agent=v.ua,
        extra_http_headers=headers,
        viewport={"width": 390, "height": 800} if mobile else {"width": 1280, "height": 800},
    )
    try:
        if v.hide_webdriver:
            # a synthetic *human*: real browsers do not announce automation
            ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => false});")
        page = ctx.new_page()
        page.clock.install()
        page.goto(base_url.rstrip("/") + _landing_path(v), wait_until="load")
        spent = 0.0
        if v.scroll_to > 0:
            steps = max(1, v.scroll_to // 20)
            for i in range(1, steps + 1):
                frac = min(1.0, (v.scroll_to / 100.0) * i / steps)
                page.evaluate(
                    "f => window.scrollTo(0, Math.max(0, f * document.documentElement.scrollHeight - window.innerHeight))",
                    frac,
                )
                page.wait_for_timeout(60)
                page.clock.run_for(1500)
                spent += 1.5
        rest = max(0.0, v.dwell_s - spent)
        if v.signup:
            page.clock.run_for(int(rest * 1000 * 0.7))
            page.evaluate("() => window.scrollTo(0, 0)")
            page.fill("#signup input[type=email]", v.email)
            with page.expect_navigation(url="**/thanks/**"):
                page.click("#signup button[type=submit]")
            rest *= 0.3
            if v.followup:
                page.fill("#followup textarea", _answer_for(v))
                page.click("#followup button[type=submit]")
                page.wait_for_timeout(150)
            if v.deposit:
                with page.expect_navigation(url="**/reserve/**"):
                    page.click("#deposit")
                page.fill("#mockemail", v.email)
                with page.expect_navigation(url="**/deposit-done/**"):
                    page.click("#mockpay")
                page.wait_for_timeout(150)
            elif v.call:
                with page.expect_navigation(url="**/call/**"):
                    page.click("#call")
                page.fill("#callreq input[type=email]", v.email)
                page.click("#callreq button[type=submit]")
                page.wait_for_timeout(150)
        page.clock.run_for(max(100, int(rest * 1000)))
        page.wait_for_timeout(80)
        page.goto("about:blank")  # pagehide: ve.js sends page_leave with the dwell
        page.wait_for_timeout(80)
        page.close()
    finally:
        ctx.close()


class _HttpPlayer:
    """Fallback when no browser can start: post the events ve.js would send. Flagged as unverified."""

    def __init__(self, base_url: str, idea_id: str, tier: str) -> None:
        self.base = base_url.rstrip("/")
        self.idea = idea_id
        self.tier = tier

    def _post(self, path: str, body: dict[str, Any], v: Visitor) -> None:
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "text/plain", "User-Agent": v.ua, "X-Forwarded-For": v.ip, "X-VE-Country": v.country},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10).read()  # noqa: S310 - local test host only

    def play(self, v: Visitor, n: int) -> None:
        sid = f"http{n:04d}"
        ad = v.ad
        attr = {
            "utm_source": CHANNELS[ad["channel"]]["utm_source"],
            "utm_medium": CHANNELS[ad["channel"]]["utm_medium"],
            "utm_campaign": f"ve-{self.idea}-{self.tier}",
            "utm_content": ad["variant"],
            "ve_ad": ad["ad_id"],
            "sim": "1",
        }
        if v.keyword:
            attr["utm_term"] = v.keyword

        def ev(event: str, seconds: float, page: str = "landing", **props: Any) -> None:
            body = {"event": event, "idea_id": self.idea, "variant": ad["variant"], "page": page, "session_id": sid,
                    "visitor_id": sid, "seconds": seconds, "webdriver": not v.hide_webdriver,
                    "max_scroll": v.scroll_to, "props": props, **attr}
            self._post("/e", body, v)

        ev("page_view", 0.0)
        for m in (25, 50, 75, 90):
            if v.scroll_to >= m:
                ev("scroll", min(v.dwell_s, 1.5 * (m // 25)), pct=m)
        if v.scroll_to >= 60:
            ev("section_view", min(v.dwell_s, 3.0), section="how")
        t = 5.0
        while t <= v.dwell_s:
            ev("heartbeat", t)
            t += 5.0
        if v.signup:
            ev("signup", v.dwell_s * 0.7, email_domain="example.test")
            self._post("/f", {"form": "signup", "email": v.email, "session_id": sid, "variant": ad["variant"], **attr}, v)
            ev("page_view", v.dwell_s * 0.7, page="thanks")
            if v.followup:
                answer = _answer_for(v)
                ev("followup_answer", v.dwell_s * 0.8, page="thanks", chars=len(answer))
                self._post("/f", {"form": "followup", "answer": answer, "session_id": sid, "variant": ad["variant"], **attr}, v)
            if v.deposit:
                ev("deposit_click", v.dwell_s * 0.85, page="thanks")
                self._post("/mock-pay", {"session_id": sid, "variant": ad["variant"], "idea_id": self.idea, "amount_usd": 49,
                                         "email": v.email}, v)
                ev("deposit_paid", v.dwell_s * 0.9, page="deposit_done")
            elif v.call:
                ev("call_request", v.dwell_s * 0.9, page="call")
                self._post("/f", {"form": "call", "email": v.email, "when": "", "session_id": sid, "variant": ad["variant"], **attr}, v)
        ev("page_leave", v.dwell_s)


def simulate(
    plan: dict[str, Any],
    base_url: str,
    state_dir: Path,
    *,
    seed: int = 7,
    engine: str = "auto",
    concierge: bool = True,
) -> dict[str, Any]:
    """Play the synthetic crowd through the live local page. Returns the ground truth for the filter check."""
    visitors = make_visitors(plan, seed=seed)
    used_engine = engine
    errors: list[str] = []
    if engine in {"auto", "browser"}:
        try:
            from playwright.sync_api import (
                sync_playwright,  # type: ignore[import-not-found]
            )

            with sync_playwright() as pw:
                try:
                    browser = pw.chromium.launch(headless=True)
                except Exception:  # noqa: BLE001 - fall back to the system chromium
                    browser = pw.chromium.launch(headless=True, executable_path="/usr/bin/chromium-browser")
                for v in visitors:
                    try:
                        _play_browser(v, base_url, browser)
                    except Exception as exc:  # noqa: BLE001 - one bad visit must not end the run
                        errors.append(f"{v.persona}/{v.ad['ad_id']}: {type(exc).__name__}: {str(exc)[:160]}")
                browser.close()
            used_engine = "browser"
        except ImportError:
            if engine == "browser":
                raise
            used_engine = "http"
    if used_engine == "http":
        player = _HttpPlayer(base_url, plan["idea_id"], plan["tier"])
        for i, v in enumerate(visitors, 1):
            player.play(v, i)

    # Ad-platform report for the plan, in the canonical shape the live pull also writes. $0 spend.
    report = []
    for ad in plan["ads"]:
        clicks = sum(1 for v in visitors if v.ad["ad_id"] == ad["ad_id"])
        ctr = SYNTHETIC_CTR.get(ad["variant"], 0.006)
        report.append(
            {
                "date": plan["window"]["start"],
                "channel": ad["channel"],
                "ad_id": ad["ad_id"],
                "variant": ad["variant"],
                "impressions": int(round(clicks / ctr)) if clicks else 0,
                "clicks": clicks,
                "spend_usd": 0.0,
                "simulated": True,
            }
        )
    append_jsonl(state_dir / "ad_report.jsonl", report)

    # One synthetic refund request, and the concierge log for whoever reserved.
    paid = [r for r in read_jsonl(state_dir / "deposits.jsonl") if r.get("status") == "paid"]
    if paid:
        first = paid[0]
        append_jsonl(state_dir / "deposits.jsonl", [{**first, "status": "refunded", "ts": iso(), "refund_reason": "requested_by_customer (synthetic)"}])
    if concierge and paid:
        rows = []
        for i, r in enumerate(paid):
            ref = r.get("email") or r.get("session_id")
            rows.append({"ts": iso(), "customer": ref, "event": "used", "synthetic": True})
            if i % 2 == 0:
                rows.append({"ts": iso(), "customer": ref, "event": "used", "synthetic": True})
        append_jsonl(state_dir / "concierge.jsonl", rows)

    truth = {
        "seed": seed,
        "engine": used_engine,
        "visitors": len(visitors),
        "bots_planted": sum(1 for v in visitors if v.bot),
        "humans_planted": sum(1 for v in visitors if not v.bot),
        "by_persona": {p: sum(1 for v in visitors if v.persona == p) for p in PERSONAS},
        # per visitor, keyed by the address it came from, so ve_score can check the bot filter visit by visit
        "truth": [{"ip": v.ip, "persona": v.persona, "bot": v.bot, "ad_id": v.ad["ad_id"], "country": v.country} for v in visitors],
        "errors": errors,
        "simulated_at": iso(),
    }
    write_json(state_dir / "simulation.json", truth)
    return truth
