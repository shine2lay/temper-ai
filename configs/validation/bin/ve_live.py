"""The live adapters: Netlify (page + forms), PostHog (raw events), Stripe (refundable deposits).

Only a live run (every rail present, a budget set, the owner's go-ahead) reaches this file. Each
adapter talks to the service's public HTTP API with the stdlib, through one small `Http` client a
test can replace, and turns what the service returns into the same rows the dry run's local test
host writes -- so the bot filter, the scorecard and the decision cannot tell the two apart:

- events.jsonl  one row per page event (PostHog, read back with HogQL: raw, unfiltered)
- forms.jsonl   one row per signup / follow-up answer / call request (Netlify Forms)
- deposits.jsonl one row per paid reservation, plus one per refund (Stripe)

Ads are not here: ad platforms differ too much for one clean API, so ve_campaign (a model with
the platform's API or the signed-in browser) launches the plan and writes ad_report.jsonl.

Money moves in two places only, both refundable and both idempotent: a visitor's own checkout on
a Stripe Payment Link, and `refund_all`, which gives every deposit back.
"""

from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ve_common import iso

Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, bytes]]


def _urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https API hosts
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


class LiveError(RuntimeError):
    """A service said no. The message names the service and never carries a secret."""


class Http:
    """JSON / form / raw requests with one retry on 429 and 5xx. `transport` is swapped in tests."""

    def __init__(self, transport: Transport | None = None, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.transport = transport or _urllib_transport
        self.sleep = sleep

    def call(
        self,
        service: str,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any = None,
        form: list[tuple[str, str]] | None = None,
        raw: bytes | None = None,
        content_type: str | None = None,
        timeout: float = 30.0,
    ) -> Any:
        hdrs = dict(headers or {})
        body: bytes | None = None
        if json_body is not None:
            body = json.dumps(json_body).encode()
            hdrs["Content-Type"] = "application/json"
        elif form is not None:
            body = urllib.parse.urlencode(form).encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        elif raw is not None:
            body = raw
            hdrs["Content-Type"] = content_type or "application/octet-stream"
        status, data = 0, b""
        for attempt in range(2):
            status, data = self.transport(method, url, hdrs, body, timeout)
            if status == 429 or status >= 500:
                if attempt == 0:
                    self.sleep(2.0)
                    continue
            break
        if status >= 400:
            detail = data[:300].decode("utf-8", "replace")
            raise LiveError(f"{service}: {method} {urllib.parse.urlsplit(url).path} -> HTTP {status}: {detail}")
        if not data:
            return None
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return data.decode("utf-8", "replace")


# ---------------------------------------------------------------------------------------------------
# Netlify: the page, and the forms it collects
# ---------------------------------------------------------------------------------------------------

NETLIFY = "https://api.netlify.com/api/v1"
FORM_NAMES = ("signup", "followup", "call")


def _nl(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def zip_site(site_dir: str | Path) -> bytes:
    """The rendered site as one zip (Netlify's zip deploy)."""
    root = Path(site_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(root).as_posix())
    return buf.getvalue()


def netlify_ensure_site(http: Http, token: str, *, site_id: str, domain: str, name: str) -> dict[str, Any]:
    """The test brand's site: the one named in the rails, or a new one on the brand's domain."""
    if site_id:
        site = http.call("netlify", "GET", f"{NETLIFY}/sites/{site_id}", headers=_nl(token))
    else:
        site = http.call("netlify", "POST", f"{NETLIFY}/sites", headers=_nl(token),
                         json_body={"name": name, "custom_domain": domain})
    if not isinstance(site, dict) or not site.get("id"):
        raise LiveError("netlify: no site id came back")
    return site


def netlify_deploy(http: Http, token: str, site_id: str, site_dir: str | Path, *, wait_s: float = 120.0) -> dict[str, Any]:
    """Zip-deploy the site and wait until Netlify says it is live."""
    dep = http.call("netlify", "POST", f"{NETLIFY}/sites/{site_id}/deploys", headers=_nl(token),
                    raw=zip_site(site_dir), content_type="application/zip", timeout=120)
    if not isinstance(dep, dict) or not dep.get("id"):
        raise LiveError("netlify: the deploy was not accepted")
    deadline = time.monotonic() + wait_s
    while dep.get("state") not in {"ready", "error"} and time.monotonic() < deadline:
        http.sleep(3.0)
        dep = http.call("netlify", "GET", f"{NETLIFY}/deploys/{dep['id']}", headers=_nl(token))
    if dep.get("state") != "ready":
        raise LiveError(f"netlify: deploy {dep.get('id')} ended in state {dep.get('state')!r}")
    return dep


def netlify_check_forms(http: Http, token: str, site_id: str) -> list[str]:
    """The forms Netlify detected; a missing one means signups would be lost (form detection off)."""
    forms = http.call("netlify", "GET", f"{NETLIFY}/sites/{site_id}/forms", headers=_nl(token)) or []
    found = {str(f.get("name")) for f in forms if isinstance(f, dict)}
    return [n for n in FORM_NAMES if n not in found]


def netlify_pull_forms(http: Http, token: str, site_id: str, *, max_pages: int = 50) -> list[dict[str, Any]]:
    """Every verified submission (Netlify keeps spam apart), as forms.jsonl rows."""
    rows: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        batch = http.call("netlify", "GET", f"{NETLIFY}/sites/{site_id}/submissions?per_page=100&page={page}",
                          headers=_nl(token)) or []
        for s in batch:
            data = s.get("data") or {}
            form = str(s.get("form_name") or data.get("form-name") or "")
            row = {k: data.get(k) for k in ("session_id", "variant", "utm_source", "utm_medium", "utm_campaign",
                                             "utm_content", "utm_term", "ve_ad", "sim") if data.get(k)}
            row.update({
                "form": form,
                "ts": s.get("created_at"),
                "email": str(data.get("email") or s.get("email") or "").strip().lower(),
                "answer": str(data.get("answer") or "")[:2000],
                "ip": data.get("ip") or "",
                "ua": data.get("user_agent") or "",
                "source": "netlify",
                "submission_id": s.get("id"),
            })
            rows.append(row)
        if len(batch) < 100:
            break
    return rows


# ---------------------------------------------------------------------------------------------------
# PostHog: the raw events ve.js sent (the engine applies its own bot filter to them)
# ---------------------------------------------------------------------------------------------------

_PH_KNOWN = {"ve_idea", "ve_variant", "ve_page", "ve_sid", "ve_seconds", "ve_webdriver", "ve_max_scroll"}


def posthog_row(event: str, timestamp: str, props: dict[str, Any]) -> dict[str, Any]:
    """One PostHog event as an events.jsonl row (the local collector's shape)."""
    row: dict[str, Any] = {
        "event": event,
        "ts": timestamp,
        "idea_id": props.get("ve_idea"),
        "variant": props.get("ve_variant"),
        "page": props.get("ve_page"),
        "session_id": props.get("ve_sid"),
        "seconds": props.get("ve_seconds") or 0,
        "webdriver": props.get("ve_webdriver") is True or str(props.get("ve_webdriver")).lower() == "true",
        "max_scroll": props.get("ve_max_scroll") or 0,
        "ip": props.get("$ip") or "",
        "ua": props.get("$raw_user_agent") or props.get("$user_agent") or "",
        "country": props.get("$geoip_country_code"),
        "props": {k[3:]: v for k, v in props.items() if k.startswith("ve_") and k not in _PH_KNOWN},
        "source": "posthog",
    }
    for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "ve_ad", "sim"):
        if props.get(k):
            row[k] = props[k]
    return row


def posthog_pull_events(
    http: Http, host: str, project_id: str, personal_key: str, *, idea_id: str, since: str, limit: int = 50000
) -> list[dict[str, Any]]:
    """Every event of this idea's page since the window opened, unfiltered."""
    if not all(ch.isalnum() or ch == "-" for ch in idea_id):
        raise LiveError("posthog: idea_id must be a slug")
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=UTC)
    since_sql = since_dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    query = (
        "SELECT event, timestamp, properties FROM events "
        f"WHERE properties.ve_idea = '{idea_id}' AND timestamp >= toDateTime('{since_sql}') "
        f"ORDER BY timestamp LIMIT {int(limit)}"
    )
    out = http.call(
        "posthog", "POST", f"{host.rstrip('/')}/api/projects/{project_id}/query/",
        headers={"Authorization": f"Bearer {personal_key}"},
        json_body={"query": {"kind": "HogQLQuery", "query": query}}, timeout=120,
    )
    rows = []
    for rec in (out or {}).get("results") or []:
        event, ts, props = rec[0], rec[1], rec[2]
        if isinstance(props, str):
            try:
                props = json.loads(props)
            except json.JSONDecodeError:
                props = {}
        rows.append(posthog_row(str(event), str(ts), props if isinstance(props, dict) else {}))
    return rows


# ---------------------------------------------------------------------------------------------------
# Stripe: one Payment Link per framing, the deposits paid on them, refunds
# ---------------------------------------------------------------------------------------------------

STRIPE = "https://api.stripe.com/v1"


def _st(key: str, idem: str | None = None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {key}"}
    if idem:
        h["Idempotency-Key"] = idem
    return h


def stripe_payment_links(
    http: Http,
    key: str,
    *,
    idea_id: str,
    lock: str,
    variants: list[str],
    deposit_usd: int,
    product_name: str,
    done_url: str,
) -> dict[str, dict[str, str]]:
    """A fully refundable reservation link per framing (idempotent: a re-run gets the same links)."""
    product = http.call("stripe", "POST", f"{STRIPE}/products", headers=_st(key, f"ve-{idea_id}-{lock}-product"), form=[
        ("name", f"{product_name}: founding spot (fully refundable reservation)"),
        ("description", f"Early-access reservation. {product_name} is not available yet; the deposit is refundable any time."),
        ("metadata[ve_idea]", idea_id),
    ])
    price = http.call("stripe", "POST", f"{STRIPE}/prices", headers=_st(key, f"ve-{idea_id}-{lock}-price"), form=[
        ("product", product["id"]), ("currency", "usd"), ("unit_amount", str(int(deposit_usd) * 100)),
        ("metadata[ve_idea]", idea_id),
    ])
    links: dict[str, dict[str, str]] = {}
    for vid in variants:
        link = http.call("stripe", "POST", f"{STRIPE}/payment_links", headers=_st(key, f"ve-{idea_id}-{lock}-link-{vid}"), form=[
            ("line_items[0][price]", price["id"]),
            ("line_items[0][quantity]", "1"),
            ("after_completion[type]", "redirect"),
            ("after_completion[redirect][url]", done_url),
            ("custom_text[submit][message]",
             f"Fully refundable reservation: refunded any time on request, and in full if {product_name} "
             "does not launch within 90 days. Nothing ships today."),
            ("metadata[ve_idea]", idea_id),
            ("metadata[ve_variant]", vid),
            ("payment_intent_data[metadata][ve_idea]", idea_id),
            ("payment_intent_data[metadata][ve_variant]", vid),
        ])
        links[vid] = {"id": str(link["id"]), "url": str(link["url"])}
    return links


def _paged(http: Http, key: str, url: str, max_pages: int = 50) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    after = ""
    for _ in range(max_pages):
        sep = "&" if "?" in url else "?"
        page = http.call("stripe", "GET", f"{url}{sep}limit=100" + (f"&starting_after={after}" if after else ""),
                         headers=_st(key)) or {}
        data = page.get("data") or []
        items.extend(data)
        if not page.get("has_more") or not data:
            break
        after = str(data[-1]["id"])
    return items


def stripe_pull_deposits(http: Http, key: str, links: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Paid reservations on the test's links, plus a `refunded` row for each one given back."""
    rows: list[dict[str, Any]] = []
    for vid, link in links.items():
        for cs in _paged(http, key, f"{STRIPE}/checkout/sessions?payment_link={link['id']}"):
            if cs.get("payment_status") != "paid":
                continue
            created = datetime.fromtimestamp(int(cs.get("created") or 0), UTC)
            base = {
                "id": str(cs["id"]),
                "session_id": cs.get("client_reference_id"),
                "variant": vid,
                "email": str((cs.get("customer_details") or {}).get("email") or "").lower(),
                "amount_usd": (cs.get("amount_total") or 0) / 100,
                "payment_intent": cs.get("payment_intent"),
                "test_mode": not cs.get("livemode", False),
                "source": "stripe",
            }
            rows.append({**base, "status": "paid", "ts": iso(created)})
            pi = cs.get("payment_intent")
            if pi:
                for rf in _paged(http, key, f"{STRIPE}/refunds?payment_intent={pi}"):
                    if rf.get("status") in {"succeeded", "pending"}:
                        by_engine = (rf.get("metadata") or {}).get("ve_engine") == "1"
                        why = (rf.get("metadata") or {}).get("ve_why", "engine") if by_engine else "requested_by_customer"
                        rows.append({**base, "status": "refunded", "refund_id": rf.get("id"),
                                     "ts": iso(datetime.fromtimestamp(int(rf.get("created") or 0), UTC)),
                                     "refund_reason": why if not by_engine else f"engine:{why}"})
    return rows


def stripe_refund_all(http: Http, key: str, rows: list[dict[str, Any]], *, why: str) -> list[dict[str, Any]]:
    """Refund every paid deposit not refunded yet. Idempotent per payment."""
    refunded = {r["id"] for r in rows if r.get("status") == "refunded"}
    done = []
    for r in rows:
        if r.get("status") != "paid" or r["id"] in refunded or not r.get("payment_intent"):
            continue
        rf = http.call("stripe", "POST", f"{STRIPE}/refunds", headers=_st(key, f"ve-refund-{r['payment_intent']}"), form=[
            ("payment_intent", str(r["payment_intent"])),
            ("metadata[ve_engine]", "1"),
            ("metadata[ve_why]", why),
        ])
        done.append({**{k: v for k, v in r.items() if k != "status"}, "status": "refunded", "refund_id": (rf or {}).get("id"),
                     "ts": iso(), "refund_reason": f"engine:{why}"})
    return done


def dashboard_links(*, site: dict[str, Any] | None, links: dict[str, dict[str, str]], stripe_test: bool,
                    posthog_host: str, posthog_project: str) -> list[dict[str, str]]:
    """Evidence links for the scorecard: the live page, its deploys, the deposit links, the raw events."""
    out = []
    if site:
        out.append({"what": "live page", "link": str(site.get("ssl_url") or site.get("url") or "")})
        if site.get("admin_url"):
            out.append({"what": "host dashboard (deploys, form submissions)", "link": str(site["admin_url"])})
    base = "https://dashboard.stripe.com/" + ("test/" if stripe_test else "")
    for vid, link in links.items():
        out.append({"what": f"deposit link, framing {vid}", "link": f"{base}payment-links/{link['id']}"})
    if posthog_host and posthog_project:
        app = posthog_host.rstrip("/").replace(".i.posthog.com", ".posthog.com")
        out.append({"what": "raw page events (PostHog)", "link": f"{app}/project/{posthog_project}/activity/explore"})
    return out
