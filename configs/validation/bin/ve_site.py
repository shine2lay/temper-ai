"""The fake-door page: copy checks, the honesty guard, the static site and the local test host.

ve_page (a model) writes `page/copy.json`; everything after that is deterministic:

- `validate_copy` checks the copy's shape and refuses wording that implies the product already
  ships, fake social proof, unverifiable statistics, or the owner's own brands.
- `render_site` turns the copy into a static site, one page per value-proposition variant, with the
  honesty text the engine controls (early-access banner, refund terms, privacy line) and the funnel
  instrumentation (`ve.js`: page view, scroll depth, section reached, dwell, signup, follow-up answer,
  deposit, call request; UTM attribution on every event).
- `guard_site` re-reads the rendered HTML and fails if any honesty text is missing.
- `serve` is the local test host for the no-spend dry run: static files plus an event/form collector
  and a mock (test-mode) reservation checkout. Nothing it serves moves money.
"""

from __future__ import annotations

import html
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ve_common import OWNER_BRANDS, append_jsonl, iso, read_json, read_jsonl, write_text

# ---------------------------------------------------------------------------------------------------
# Copy validation (the model's output) and the honesty guard
# ---------------------------------------------------------------------------------------------------

# Wording that says or implies the product exists and ships today.
SHIPS_NOW = re.compile(
    r"\b(available now|now available|in stock|ships? (today|now|immediately)|"
    r"start (using|your free trial)|free trial|sign ?in|log ?in|download (now|the app|today)|"
    r"buy now|order now|get started (now|today)|try it (now|today|free)|instant access|"
    r"live now|launch(ed)? today|already (used|helping|trusted))\b",
    re.IGNORECASE,
)
# Social proof we cannot have yet.
FAKE_PROOF = re.compile(
    r"\b(trusted by|used by|loved by|join(ed)? (over |more than )?\d|thousands of (teams|customers|users|businesses)|"
    r"millions of|customers (love|say)|rated \d|#1\b|number one|award[- ]winning|case stud(y|ies)|testimonial)",
    re.IGNORECASE,
)
# A quote attributed to a person ("..." -- Name) is a testimonial, whatever it is called.
ATTRIBUTED_QUOTE = re.compile(r"[\"\u201c][^\"\u201d]{12,}[\"\u201d]\s*(?:-|\u2013|\u2014)\s*[A-Z]")
# Percent claims about a product that does not exist cannot be verified.
PERCENT_CLAIM = re.compile(r"\b\d{1,3}(\.\d+)?\s?%")

MAX_HEADLINE = 90
MAX_AD_HEADLINE = 30  # Google responsive search ad headline limit (the strictest channel)
MAX_AD_BODY = 90  # Google responsive search ad description limit


def _texts(copy: dict[str, Any]) -> list[tuple[str, str]]:
    """(where, text) for every visitor-facing string in the copy."""
    out: list[tuple[str, str]] = []
    for key in ("brand", "product_name", "cta_signup", "followup_question", "call_offer", "audience"):
        if isinstance(copy.get(key), str):
            out.append((key, copy[key]))
    for i, step in enumerate(copy.get("how_it_works") or []):
        out.append((f"how_it_works[{i}]", str(step)))
    for i, qa in enumerate(copy.get("faq") or []):
        if isinstance(qa, dict):
            out.append((f"faq[{i}].q", str(qa.get("q", ""))))
            out.append((f"faq[{i}].a", str(qa.get("a", ""))))
    for v in copy.get("variants") or []:
        if not isinstance(v, dict):
            continue
        vid = v.get("id", "?")
        for key in ("headline", "subhead", "framing"):
            out.append((f"variant {vid}.{key}", str(v.get(key, ""))))
        for i, b in enumerate(v.get("bullets") or []):
            out.append((f"variant {vid}.bullets[{i}]", str(b)))
        ad = v.get("ad") or {}
        for key in ("headline", "body"):
            out.append((f"variant {vid}.ad.{key}", str(ad.get(key, ""))))
    return out


def validate_copy(copy: dict[str, Any]) -> list[str]:
    """Every problem with the copy, as plain sentences; an empty list means it may be rendered."""
    errors: list[str] = []
    for key in ("brand", "product_name", "cta_signup", "followup_question", "how_it_works", "variants"):
        if not copy.get(key):
            errors.append(f"missing `{key}`")
    variants = copy.get("variants") or []
    if not 2 <= len(variants) <= 3:
        errors.append(f"need 2-3 value-proposition variants, found {len(variants)}")
    ids = [str(v.get("id", "")) for v in variants if isinstance(v, dict)]
    if ids and ids != ["A", "B", "C"][: len(ids)]:
        errors.append(f"variant ids must be A, B[, C] in order, found {ids}")
    headlines = [str(v.get("headline", "")).strip().lower() for v in variants if isinstance(v, dict)]
    if len(set(headlines)) != len(headlines):
        errors.append("variant headlines must differ: A/B the value proposition, not the button")
    for v in variants:
        if not isinstance(v, dict):
            errors.append("each variant must be an object")
            continue
        vid = v.get("id", "?")
        for key in ("framing", "headline", "subhead"):
            if not str(v.get(key, "")).strip():
                errors.append(f"variant {vid}: missing `{key}`")
        if len(str(v.get("headline", ""))) > MAX_HEADLINE:
            errors.append(f"variant {vid}: headline longer than {MAX_HEADLINE} characters")
        bullets = v.get("bullets") or []
        if not 2 <= len(bullets) <= 5:
            errors.append(f"variant {vid}: need 2-5 pain bullets")
        ad = v.get("ad") or {}
        if not str(ad.get("headline", "")).strip() or not str(ad.get("body", "")).strip():
            errors.append(f"variant {vid}: missing ad.headline or ad.body")
        if len(str(ad.get("headline", ""))) > MAX_AD_HEADLINE:
            errors.append(f"variant {vid}: ad.headline longer than {MAX_AD_HEADLINE} characters")
        if len(str(ad.get("body", ""))) > MAX_AD_BODY:
            errors.append(f"variant {vid}: ad.body longer than {MAX_AD_BODY} characters")
    steps = copy.get("how_it_works") or []
    if steps and not 2 <= len(steps) <= 5:
        errors.append("how_it_works needs 2-5 steps")
    errors.extend(honesty_problems(copy))
    return errors


def honesty_problems(copy: dict[str, Any]) -> list[str]:
    """The guardrails: honest fake-door wording, no fake proof, neutral brand."""
    problems: list[str] = []
    for where, text in _texts(copy):
        m = SHIPS_NOW.search(text)
        if m:
            problems.append(f"{where}: {m.group(0)!r} implies the product already ships (say 'early access')")
        m = FAKE_PROOF.search(text)
        if m:
            problems.append(f"{where}: {m.group(0)!r} is social proof we do not have")
        if ATTRIBUTED_QUOTE.search(text):
            problems.append(f"{where}: an attributed quote reads as a testimonial")
        m = PERCENT_CLAIM.search(text)
        if m:
            problems.append(f"{where}: {m.group(0)!r} is an unverifiable statistic about an unbuilt product")
    brand_text = f"{copy.get('brand', '')} {copy.get('product_name', '')}".lower()
    for owner in OWNER_BRANDS:
        if owner in brand_text:
            problems.append(f"brand: {owner!r} is the owner's brand; use a neutral test brand")
    return problems


# Text the renderer itself writes on every page; guard_site checks it is all there.
REQUIRED_PHRASES = {
    "early_access": "is not available yet",
    "refundable": "fully refundable",
    "privacy": "only to tell you about early access",
    "how_heading": "How it would work",
}


def guard_site(site_dir: str | Path, variants: list[str]) -> list[str]:
    """Re-read the rendered pages: honesty text present, no forbidden wording, instrumentation wired."""
    site = Path(site_dir)
    problems: list[str] = []
    pages = {f"{v.lower()}/index.html": "landing" for v in variants}
    pages.update({"index.html": "landing", "thanks/index.html": "thanks", "privacy/index.html": "privacy"})
    for rel, kind in pages.items():
        p = site / rel
        if not p.exists():
            problems.append(f"{rel}: missing")
            continue
        text = p.read_text()
        plain = html.unescape(re.sub(r"<[^>]+>", " ", text))
        if REQUIRED_PHRASES["early_access"] not in plain:
            problems.append(f"{rel}: early-access banner missing")
        if "/ve.js" not in text:
            problems.append(f"{rel}: instrumentation (ve.js) not loaded")
        m = SHIPS_NOW.search(plain) or FAKE_PROOF.search(plain)
        if m:
            problems.append(f"{rel}: forbidden wording {m.group(0)!r}")
        if kind == "landing":
            for key in ("privacy", "how_heading"):
                if REQUIRED_PHRASES[key] not in plain:
                    problems.append(f"{rel}: {key} text missing")
            if 'id="how"' not in text:
                problems.append(f"{rel}: the how-it-works section has no id=how (section reach is not measured)")
        if kind in {"thanks", "privacy"} and REQUIRED_PHRASES["refundable"] not in plain:
            problems.append(f"{rel}: refund terms missing")
    if not (site / "ve.js").exists():
        problems.append("ve.js: missing")
    return problems


# ---------------------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------------------

CSS = """
*{box-sizing:border-box}body{margin:0;font:17px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#1d2330;background:#fbfbfd}
.banner{background:#fff4d6;border-bottom:1px solid #f0d58a;padding:.6rem 1rem;text-align:center;font-size:.92rem}
header,footer{max-width:760px;margin:0 auto;padding:1rem}.brand{font-weight:700;letter-spacing:.02em}
main{max-width:760px;margin:0 auto;padding:0 1rem 3rem}section{padding:2.2rem 0;border-bottom:1px solid #eceef3}
h1{font-size:2.1rem;line-height:1.2;margin:.4rem 0 1rem}h2{font-size:1.35rem;margin:0 0 .8rem}
.sub{font-size:1.15rem;color:#444b5a}form{display:flex;gap:.5rem;flex-wrap:wrap;margin:1.2rem 0 .4rem}
input,textarea{font:inherit;padding:.7rem .8rem;border:1px solid #c9ceda;border-radius:8px;flex:1 1 260px}
textarea{width:100%;min-height:6rem}button,.btn{font:inherit;font-weight:600;padding:.7rem 1.2rem;border:0;border-radius:8px;
background:#2f5bea;color:#fff;cursor:pointer;text-decoration:none;display:inline-block}.btn.alt{background:#eef1fb;color:#2f5bea}
.fine{font-size:.85rem;color:#6a7080}ul,ol{padding-left:1.2rem}li{margin:.35rem 0}.faq dt{font-weight:600;margin-top:1rem}
.faq dd{margin:.2rem 0 0}.box{background:#fff;border:1px solid #e3e6ee;border-radius:12px;padding:1.2rem;margin:1rem 0}
footer{font-size:.85rem;color:#6a7080}.test{background:#ffe9e9;border:1px dashed #d55;padding:.8rem;border-radius:8px}
"""

JS = r"""
(function () {
  "use strict";
  var C = window.VE || {};
  var KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "ve_ad", "sim"];
  function sget(k) { try { return window.sessionStorage.getItem(k); } catch (e) { return null; } }
  function sput(k, v) { try { window.sessionStorage.setItem(k, v); } catch (e) {} }
  function rid() { return Math.random().toString(36).slice(2, 10) + Date.now().toString(36); }
  var sid = sget("ve_sid");
  if (!sid) { sid = rid(); sput("ve_sid", sid); sput("ve_t0", String(Date.now())); }
  var vid = null;
  try { vid = window.localStorage.getItem("ve_vid"); if (!vid) { vid = rid(); window.localStorage.setItem("ve_vid", vid); } }
  catch (e) { vid = sid; }
  if (!sget("ve_attr")) {
    var q = new URLSearchParams(window.location.search), a = {};
    KEYS.forEach(function (k) { if (q.get(k)) { a[k] = q.get(k).slice(0, 120); } });
    a.v = C.variant || q.get("v") || "A";
    a.ref = (document.referrer || "").slice(0, 200);
    sput("ve_attr", JSON.stringify(a));
  }
  var attr = {};
  try { attr = JSON.parse(sget("ve_attr") || "{}"); } catch (e) { attr = {}; }
  var variant = attr.v || C.variant || "A";
  var t0 = Number(sget("ve_t0")) || Date.now();
  function secs() { return Math.round((Date.now() - t0) / 100) / 10; }
  var maxPct = 0;

  function send(event, props) {
    var body = {
      event: event, idea_id: C.idea, variant: variant, page: C.page, session_id: sid, visitor_id: vid,
      ts_client: new Date().toISOString(), seconds: secs(), webdriver: !!navigator.webdriver,
      max_scroll: maxPct, props: props || {}
    };
    KEYS.forEach(function (k) { if (attr[k]) { body[k] = attr[k]; } });
    if (C.analytics === "posthog" && window.posthog) {
      var p = { ve_idea: C.idea, ve_variant: variant, ve_page: C.page, ve_sid: sid, ve_seconds: body.seconds,
                ve_webdriver: body.webdriver, ve_max_scroll: maxPct };
      KEYS.forEach(function (k) { if (attr[k]) { p[k] = attr[k]; } });
      Object.keys(body.props).forEach(function (k) { p["ve_" + k] = body.props[k]; });
      window.posthog.capture(event, p);
      return;
    }
    var data = JSON.stringify(body), url = C.endpoint || "/e";
    try {
      if (navigator.sendBeacon && navigator.sendBeacon(url, new Blob([data], { type: "text/plain" }))) { return; }
    } catch (e) {}
    try { fetch(url, { method: "POST", headers: { "Content-Type": "text/plain" }, body: data, keepalive: true }); } catch (e) {}
  }
  window.veSend = send;

  function postForm(name, fields) {
    var all = { session_id: sid, variant: variant };
    KEYS.forEach(function (k) { if (attr[k]) { all[k] = attr[k]; } });
    Object.keys(fields).forEach(function (k) { all[k] = fields[k]; });
    if (C.forms === "netlify") {
      var b = new URLSearchParams(); b.append("form-name", name);
      Object.keys(all).forEach(function (k) { b.append(k, all[k]); });
      return fetch("/", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: b.toString() });
    }
    all.form = name; all.idea_id = C.idea;
    return fetch(C.forms_endpoint || "/f", { method: "POST", headers: { "Content-Type": "text/plain" }, body: JSON.stringify(all) });
  }
  function go(path) { window.location.href = path; }

  send("page_view", { ref: attr.ref || "" });
  var marks = [25, 50, 75, 90], hit = {};
  window.addEventListener("scroll", function () {
    var h = document.documentElement;
    var pct = Math.min(100, Math.round(100 * (window.scrollY + window.innerHeight) / Math.max(1, h.scrollHeight)));
    if (pct > maxPct) { maxPct = pct; }
    marks.forEach(function (m) { if (pct >= m && !hit[m]) { hit[m] = 1; send("scroll", { pct: m }); } });
  }, { passive: true });
  var how = document.getElementById("how");
  if (how && "IntersectionObserver" in window) {
    var seen = false;
    new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting && !seen) { seen = true; send("section_view", { section: "how" }); } });
    }, { threshold: 0.4 }).observe(how);
  }
  window.setInterval(function () { if (document.visibilityState === "visible") { send("heartbeat", {}); } }, 5000);
  window.addEventListener("pagehide", function () { send("page_leave", {}); });

  var signup = document.getElementById("signup");
  if (signup) {
    signup.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var email = (signup.querySelector("input[type=email]") || {}).value || "";
      send("signup", { email_domain: email.split("@")[1] || "" });
      postForm("signup", { email: email }).then(function () { go(C.root + "thanks/"); }, function () { go(C.root + "thanks/"); });
    });
  }
  var follow = document.getElementById("followup");
  if (follow) {
    follow.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var answer = (follow.querySelector("textarea") || {}).value || "";
      send("followup_answer", { chars: answer.length });
      postForm("followup", { answer: answer.slice(0, 2000) });
      follow.innerHTML = "<p><strong>Thank you.</strong> That helps us decide what to build.</p>";
    });
  }
  var dep = document.getElementById("deposit");
  if (dep) {
    dep.addEventListener("click", function (ev) {
      ev.preventDefault();
      send("deposit_click", {});
      var live = C.deposit_url || (C.deposit_urls ? C.deposit_urls[variant] : null);
      var url = live || (C.root + "reserve/");
      if (live) { url += (url.indexOf("?") < 0 ? "?" : "&") + "client_reference_id=" + encodeURIComponent(sid); }
      go(url);
    });
  }
  var call = document.getElementById("call");
  if (call) { call.addEventListener("click", function () { send("call_click", {}); }); }
  var callreq = document.getElementById("callreq");
  if (callreq) {
    callreq.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var email = (callreq.querySelector("input[type=email]") || {}).value || "";
      var when = (callreq.querySelector("input[name=when]") || {}).value || "";
      send("call_request", {});
      postForm("call", { email: email, when: when });
      callreq.innerHTML = "<p><strong>Thanks.</strong> We'll email you to pick a time.</p>";
    });
  }
  var mock = document.getElementById("mockpay");
  if (mock) {
    mock.addEventListener("click", function (ev) {
      ev.preventDefault();
      fetch(C.root + "mock-pay", { method: "POST", headers: { "Content-Type": "text/plain" },
        body: JSON.stringify({ session_id: sid, variant: variant, idea_id: C.idea, amount_usd: C.deposit_usd,
                               email: (document.getElementById("mockemail") || {}).value || "" }) })
        .then(function () { go(C.root + "deposit-done/"); });
    });
  }
  if (C.page === "deposit_done" && !sget("ve_paid")) { sput("ve_paid", "1"); send("deposit_paid", {}); }
})();
"""


def _e(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _page(
    *, title: str, brand: str, product: str, body: str, ve: dict[str, Any], contact: str, posthog: dict[str, str] | None
) -> str:
    ph = ""
    if posthog:
        # posthog-js loaded synchronously (so `window.posthog` exists before ve.js sends page_view);
        # its own pageview/autocapture are off: ve.js sends every event, with the UTM attribution.
        assets = posthog["host"].rstrip("/").replace(".i.posthog.com", "-assets.i.posthog.com")
        ph = (
            f'<script src="{_e(assets)}/static/array.js"></script>'
            f"<script>window.posthog && posthog.init({json.dumps(posthog['key'])},{{api_host:{json.dumps(posthog['host'])},"
            "capture_pageview:false,capture_pageleave:false,autocapture:false,persistence:'localStorage'});</script>"
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{_e(title)}</title><link rel="stylesheet" href="{ve['root']}ve.css">
{ph}</head><body>
<div class="banner" id="early">Early access test: {_e(product)} is not available yet. We're finding out whether to build it.</div>
<header><span class="brand">{_e(brand)}</span></header>
<main>
{body}
</main>
<footer>{_e(brand)} &middot; <a href="{ve['root']}privacy/">Privacy &amp; refunds</a> &middot; {_e(contact)}</footer>
<script>window.VE = {json.dumps(ve)};</script><script src="{ve['root']}ve.js"></script>
</body></html>
"""


def _hidden_fields(names: list[str]) -> str:
    return "".join(f'<input type="hidden" name="{n}" value="">' for n in names)


FORM_FIELDS = ["session_id", "variant", "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "ve_ad", "sim"]


def render_site(
    copy: dict[str, Any],
    prereg: dict[str, Any],
    out_dir: str | Path,
    *,
    mode: str = "dry_run",
    deposit_urls: dict[str, str] | None = None,
    posthog: dict[str, str] | None = None,
    contact: str = "hello@example.test",
) -> dict[str, Any]:
    """Write the static site. Returns {variants, pages}. `mode=live` drops the mock checkout and wires
    PostHog, Netlify Forms and the Stripe Payment Link of each variant instead of the local collector."""
    site = Path(out_dir)
    site.mkdir(parents=True, exist_ok=True)
    idea = prereg["idea_id"]
    deposit = int(prereg.get("deposit_usd", 49))
    brand = str(copy["brand"])
    product = str(copy["product_name"])
    live = mode == "live"
    base_ve: dict[str, Any] = {
        "idea": idea,
        "root": "/",
        "analytics": "posthog" if (live and posthog) else "local",
        "forms": "netlify" if live else "local",
        "deposit_usd": deposit,
    }
    write_text(site / "ve.css", CSS.strip() + "\n")
    write_text(site / "ve.js", JS.strip() + "\n")

    def netlify_attrs(name: str) -> str:
        return f' name="{name}" data-netlify="true" netlify-honeypot="company_website"' if live else f' name="{name}"'

    honeypot = '<p hidden><label>Leave empty <input name="company_website"></label></p>' if live else ""
    steps = "".join(f"<li>{_e(s)}</li>" for s in copy.get("how_it_works") or [])
    faq_items = "".join(
        f"<dt>{_e(qa.get('q', ''))}</dt><dd>{_e(qa.get('a', ''))}</dd>" for qa in copy.get("faq") or [] if isinstance(qa, dict)
    )
    faq = f'<section class="faq"><h2>Questions</h2><dl>{faq_items}</dl></section>' if faq_items else ""
    pages: list[str] = []
    variants = [v for v in copy["variants"] if isinstance(v, dict)]
    for i, v in enumerate(variants):
        vid = str(v["id"])
        bullets = "".join(f"<li>{_e(b)}</li>" for b in v.get("bullets") or [])
        body = f"""
<section class="hero">
<h1>{_e(v['headline'])}</h1>
<p class="sub">{_e(v['subhead'])}</p>
<form id="signup"{netlify_attrs('signup')} method="POST">
<input type="hidden" name="form-name" value="signup">{_hidden_fields(FORM_FIELDS)}{honeypot}
<input type="email" name="email" required placeholder="you@company.com" aria-label="Work email">
<button type="submit">{_e(copy['cta_signup'])}</button>
</form>
<p class="fine">We'll use your email only to tell you about early access. No spam; unsubscribe any time.</p>
</section>
<section class="pains"><h2>Sound familiar?</h2><ul>{bullets}</ul></section>
<section id="how"><h2>How it would work</h2><ol>{steps}</ol>
<p class="fine">{_e(product)} is being designed now. Early-access members shape what gets built first.</p></section>
<section class="offer"><h2>Founding spots</h2><p>After you sign up you can reserve a founding spot with a
<strong>fully refundable ${deposit} deposit</strong>, or book a 15-minute call to tell us how you work today.</p></section>
{faq}"""
        ve = {**base_ve, "variant": vid, "page": "landing"}
        page = _page(title=f"{product} — early access", brand=brand, product=product, body=body, ve=ve, contact=contact, posthog=posthog)
        write_text(site / vid.lower() / "index.html", page)
        pages.append(f"{vid.lower()}/index.html")
        if i == 0:
            write_text(site / "index.html", page)
            pages.append("index.html")

    thanks_dep = (
        f'<a class="btn" id="deposit" href="#">Reserve a founding spot (${deposit}, fully refundable)</a>'
    )
    thanks_body = f"""
<section><h1>You're on the early-access list.</h1>
<p>One real question while you're here — it helps us more than anything else:</p>
<form id="followup"{netlify_attrs('followup')} method="POST"><input type="hidden" name="form-name" value="followup">
{_hidden_fields(FORM_FIELDS)}{honeypot}<label for="answer"><strong>{_e(copy['followup_question'])}</strong></label>
<textarea id="answer" name="answer" placeholder="A sentence or two is plenty."></textarea>
<button type="submit">Send answer</button></form></section>
<section><h2>Want to be first?</h2>
<p>Founding members get {_e(product)} first and help shape it. The ${deposit} deposit is <strong>fully refundable</strong>:
any time, for any reason, no questions asked — and refunded in full if we don't launch within 90 days.
{_e(product)} is not available yet; this reserves a spot, it does not buy a product.</p>
<p>{thanks_dep} &nbsp; <a class="btn alt" id="call" href="/call/">{_e(copy.get('call_offer') or 'Book a 15-minute call')}</a></p>
</section>"""
    if live:
        missing = [str(v["id"]) for v in copy["variants"] if not (deposit_urls or {}).get(str(v["id"]))]
        if missing:
            raise ValueError(f"live render needs a Stripe Payment Link for variant(s) {', '.join(missing)}")
    thanks_ve = {**base_ve, "variant": None, "page": "thanks"}
    if live:
        # Each variant has its own Payment Link, so a deposit traces back to its framing in Stripe itself.
        thanks_ve["deposit_urls"] = dict(deposit_urls or {})
    write_text(
        site / "thanks" / "index.html",
        _page(title=f"{product} — thanks", brand=brand, product=product, body=thanks_body,
              ve=thanks_ve, contact=contact, posthog=posthog),
    )
    pages.append("thanks/index.html")

    call_body = f"""
<section><h1>Book a 15-minute call</h1><p>Tell us how you handle this today; we'll email you to pick a time.</p>
<form id="callreq"{netlify_attrs('call')} method="POST"><input type="hidden" name="form-name" value="call">
{_hidden_fields(FORM_FIELDS)}{honeypot}<input type="email" name="email" required placeholder="you@company.com" aria-label="Work email">
<input name="when" placeholder="Best days/times (optional)"><button type="submit">Request a call</button></form></section>"""
    write_text(
        site / "call" / "index.html",
        _page(title=f"{product} — call", brand=brand, product=product, body=call_body,
              ve={**base_ve, "variant": None, "page": "call"}, contact=contact, posthog=posthog),
    )
    pages.append("call/index.html")

    done_body = f"""
<section><h1>Your founding spot is reserved.</h1>
<p>Thank you. Your ${deposit} deposit is <strong>fully refundable</strong> — reply to the receipt or write to {_e(contact)}
any time and we'll refund it in full. If we don't launch within 90 days, we refund it in full without being asked.</p></section>"""
    write_text(
        site / "deposit-done" / "index.html",
        _page(title=f"{product} — reserved", brand=brand, product=product, body=done_body,
              ve={**base_ve, "variant": None, "page": "deposit_done"}, contact=contact, posthog=posthog),
    )
    pages.append("deposit-done/index.html")

    privacy_body = f"""
<section><h1>Privacy &amp; refunds</h1>
<p>{_e(brand)} is running an early-access test for {_e(product)}, which is not available yet.</p>
<h2>What we collect</h2><p>Your email (only if you give it), your answer to our question, and anonymous page-usage
events (which page, how far you scrolled, which ad brought you). We use them only to tell you about early access and
to decide whether to build {_e(product)}. We never sell or share them. Ask us to delete them any time: {_e(contact)}.</p>
<h2>Deposits</h2><p>A founding-spot deposit (${deposit}) is fully refundable: any time, for any reason, no questions
asked. If we don't launch within 90 days, we refund every deposit in full without being asked.</p></section>"""
    write_text(
        site / "privacy" / "index.html",
        _page(title=f"{product} — privacy", brand=brand, product=product, body=privacy_body,
              ve={**base_ve, "variant": None, "page": "privacy"}, contact=contact, posthog=posthog),
    )
    pages.append("privacy/index.html")

    if not live:
        reserve_body = f"""
<section><h1>Reserve a founding spot</h1>
<div class="test"><strong>TEST MODE — no card is charged.</strong> In a live test this step is a Stripe checkout for a
fully refundable ${deposit} reservation.</div>
<p><input id="mockemail" type="email" placeholder="you@company.com" aria-label="Email"></p>
<p><a class="btn" id="mockpay" href="#">Reserve (test mode, ${deposit})</a></p></section>"""
        write_text(
            site / "reserve" / "index.html",
            _page(title=f"{product} — reserve (test mode)", brand=brand, product=product, body=reserve_body,
                  ve={**base_ve, "variant": None, "page": "reserve"}, contact=contact, posthog=posthog),
        )
        pages.append("reserve/index.html")

    write_text(site / "robots.txt", "User-agent: *\nDisallow: /\n")
    return {"variants": [str(v["id"]) for v in variants], "pages": pages}


# ---------------------------------------------------------------------------------------------------
# Local test host (dry run): static files + event/form collector + mock checkout
# ---------------------------------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, format: str, *args: Any) -> None:  # quiet
        return

    def _client(self) -> tuple[str, str, str | None]:
        ip = self.client_address[0]
        country = None
        if self.server.trust_sim_headers:
            # The dry-run simulator plays visitors from many places; only the local test host believes it.
            ip = (self.headers.get("X-Forwarded-For") or ip).split(",")[0].strip()
            country = self.headers.get("X-VE-Country")
        return ip, self.headers.get("User-Agent", ""), country

    def _body_json(self) -> dict[str, Any] | None:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 64_000:
            return None
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8", "replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _reply(self, code: int, body: bytes = b"", ctype: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - http.server's naming
        path = urlparse(self.path).path
        data = self._body_json()
        if data is None:
            self._reply(400, b"bad body")
            return
        ip, ua, country = self._client()
        stamp = {"ts": iso(), "ip": ip, "ua": ua, "country": country}
        with self.server.lock:
            if path == "/e":
                append_jsonl(self.server.state / "events.jsonl", [{**data, **stamp, "source": "local"}])
            elif path == "/f":
                append_jsonl(self.server.state / "forms.jsonl", [{**data, **stamp}])
            elif path == "/mock-pay":
                row = {
                    "id": f"mock_{len(self.server.paid) + 1:04d}",
                    "ts": stamp["ts"],
                    "status": "paid",
                    "amount_usd": data.get("amount_usd"),
                    "session_id": data.get("session_id"),
                    "variant": data.get("variant"),
                    "email": data.get("email", ""),
                    "test_mode": True,
                    "source": "mock-checkout",
                }
                self.server.paid.append(row)
                append_jsonl(self.server.state / "deposits.jsonl", [row])
            else:
                self._reply(404, b"no such endpoint")
                return
        self._reply(204)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/healthz":
            self._reply(200, b"ok")
            return
        rel = path.lstrip("/")
        target = (self.server.site / rel).resolve()
        if not str(target).startswith(str(self.server.site.resolve())):
            self._reply(404)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self._reply(404, b"not found")
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript",
            ".css": "text/css",
            ".txt": "text/plain",
            ".png": "image/png",
        }.get(target.suffix, "application/octet-stream")
        self._reply(200, target.read_bytes(), ctype)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr: tuple[str, int], site: Path, state: Path, trust_sim_headers: bool) -> None:
        super().__init__(addr, _Handler)
        self.site = site
        self.state = state
        self.trust_sim_headers = trust_sim_headers
        self.lock = threading.Lock()
        self.paid: list[dict[str, Any]] = [r for r in read_jsonl(state / "deposits.jsonl") if r.get("status") == "paid"]


class LocalHost:
    """The dry run's test URL: `with LocalHost(site, state) as url: ...` serves on 127.0.0.1."""

    def __init__(self, site_dir: str | Path, state_dir: str | Path, *, port: int = 0, trust_sim_headers: bool = True) -> None:
        self.server = _Server(("127.0.0.1", port), Path(site_dir), Path(state_dir), trust_sim_headers)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host!s}:{port}/"

    def __enter__(self) -> str:
        self.thread.start()
        return self.url

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()


def load_copy(idea_dir: Path) -> dict[str, Any]:
    copy = read_json(idea_dir / "page" / "copy.json")
    if not isinstance(copy, dict):
        raise FileNotFoundError(f"{idea_dir / 'page' / 'copy.json'} is missing: ve_page writes it")
    return copy
