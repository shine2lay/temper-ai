"""Shared pieces of the Validation Engine: state layout, rails, pre-registration, small io helpers.

The Validation Engine (docs/validation_engine.md) puts a shortlisted idea in front of real strangers
and measures what they do. Everything that decides something -- which mode a run may use, what the
pass/kill bars are, whether the bars were changed after the data came in -- lives in plain Python
here, so it can be tested without a model, an ad account or a card.

Stdlib only (PyYAML is used when present, never required): these scripts run under whatever
python3 the box or the container has.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------------------------------
# State layout: everything one idea's test produces lives under <workspace>/state/ve/<idea_id>/.
# ---------------------------------------------------------------------------------------------------


def idea_dir(workspace: str | Path, idea_id: str) -> Path:
    """The folder holding one idea's test (created on first use)."""
    d = Path(workspace) / "state" / "ve" / idea_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def slugify(text: str, max_len: int = 48) -> str:
    """`Hourly / blue-collar screening!` -> `hourly-blue-collar-screening`."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:max_len].rstrip("-")) or "idea"


# ---------------------------------------------------------------------------------------------------
# io helpers
# ---------------------------------------------------------------------------------------------------


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None = None) -> str:
    return (dt or now_utc()).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(text: str) -> datetime:
    """Parse the ISO timestamps this engine writes (and the ones PostHog/Stripe exports carry)."""
    t = text.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(t)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def today_utc() -> date:
    return now_utc().date()


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text())


def write_json(path: str | Path, data: Any) -> Path:
    """Write atomically (a half-written scorecard is worse than an old one)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=p.suffix)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=False, default=str)
        fh.write("\n")
    os.replace(tmp, p)
    return p


def write_text(path: str | Path, text: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=p.suffix)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.replace(tmp, p)
    return p


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Every parseable line of a JSON-lines file; a torn last line (a writer mid-append) is skipped."""
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def append_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("a") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            n += 1
    return n


def dump_yaml(data: Any) -> str:
    """YAML when PyYAML is installed; otherwise JSON, which is valid YAML 1.2 all the same."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover - depends on the interpreter
        return json.dumps(data, indent=2, default=str) + "\n"
    return str(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def sha256_of(data: Any) -> str:
    return hashlib.sha256(canonical_json(data).encode()).hexdigest()


# ---------------------------------------------------------------------------------------------------
# Rails: the accounts the owner provides once. The engine reads which ones exist; it never echoes a
# secret value anywhere (rails.json lists key NAMES and booleans, plus the few non-secret values such
# as the brand, the domain and the budgets).
# ---------------------------------------------------------------------------------------------------

DEFAULT_RAILS_FILE = "~/.config/validation-engine/rails.env"

# Names, not values, of the rails a LIVE screen/confirm run needs. Each entry: (group, keys, note).
LIVE_RAILS: list[tuple[str, tuple[str, ...], str]] = [
    ("brand", ("VE_BRAND",), "a neutral test brand name (never the owner's main brand)"),
    ("domain", ("VE_DOMAIN",), "a domain for the neutral test brand, DNS pointed at the host"),
    ("host", ("NETLIFY_AUTH_TOKEN",), "a Netlify account token (static hosting + Netlify Forms for signups)"),
    (
        "analytics",
        ("POSTHOG_PROJECT_API_KEY", "POSTHOG_PERSONAL_API_KEY", "POSTHOG_PROJECT_ID"),
        "a PostHog project (raw events, so the engine applies its own bot filter) + a personal API key to read them",
    ),
    (
        "ads",
        ("VE_AD_CHANNELS",),
        "ad account(s) with billing, e.g. VE_AD_CHANNELS=google-search,reddit-ads, plus each listed channel's API keys",
    ),
    ("stripe", ("STRIPE_SECRET_KEY",), "a Stripe account key (refundable deposits via Payment Links)"),
    (
        "budget",
        ("VE_SCREEN_BUDGET_USD", "VE_CONFIRM_BUDGET_USD"),
        "per-idea budgets: screen tier (~$50) and confirm tier (~$200-400)",
    ),
    ("go_ahead", ("VE_GO_AHEAD",), "VE_GO_AHEAD=yes: the owner's standing go-ahead to spend within the budgets"),
]

# Rung 4 (interviews) is optional and needs its own rails.
INTERVIEW_RAILS: list[tuple[str, tuple[str, ...], str]] = [
    ("panel", ("VE_PANEL", "VE_PANEL_API_KEY"), "an opt-in interview panel (User Interviews / Respondent)"),
    ("voice", ("VE_VOICE", "VE_VOICE_API_KEY"), "an AI voice-agent account (Vapi / Bland / Retell)"),
    ("interview_budget", ("VE_INTERVIEW_BUDGET_USD",), "a per-idea budget for panel incentives + voice minutes"),
]

AD_CHANNELS = ("google-search", "reddit-ads", "meta-ads")

# The API keys ve_campaign needs to launch, cap, pause and report each channel's ads.
AD_CHANNEL_KEYS: dict[str, tuple[str, ...]] = {
    "google-search": (
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID",
    ),
    "reddit-ads": ("REDDIT_ADS_CLIENT_ID", "REDDIT_ADS_CLIENT_SECRET", "REDDIT_ADS_REFRESH_TOKEN", "REDDIT_ADS_ACCOUNT_ID"),
    "meta-ads": ("META_ADS_ACCESS_TOKEN", "META_ADS_ACCOUNT_ID", "META_ADS_PAGE_ID"),
}


def ad_keys_missing(env: dict[str, str], channels: Iterable[str]) -> list[str]:
    """Names (never values) of the API keys the listed ad channels still lack."""
    return [k for c in channels for k in AD_CHANNEL_KEYS.get(c, ()) if not env.get(k, "").strip()]

# Values that are safe to copy into rails.json (everything else is reported as present/absent only).
NON_SECRET_KEYS = (
    "VE_BRAND",
    "VE_DOMAIN",
    "VE_AD_CHANNELS",
    "VE_SCREEN_BUDGET_USD",
    "VE_CONFIRM_BUDGET_USD",
    "VE_INTERVIEW_BUDGET_USD",
    "VE_GO_AHEAD",
    "VE_GO_AHEAD_BY",
    "VE_GO_AHEAD_DATE",
    "VE_PANEL",
    "VE_VOICE",
    "VE_TARGET_COUNTRIES",
    "POSTHOG_HOST",
    "POSTHOG_PROJECT_ID",
    "NETLIFY_SITE_ID",
    "GOOGLE_ADS_CUSTOMER_ID",
    "REDDIT_ADS_ACCOUNT_ID",
    "META_ADS_ACCOUNT_ID",
    "META_ADS_PAGE_ID",
)

# The owner's own brands: a test page must never carry them (neutral test brand only).
OWNER_BRANDS = ("wai2shine", "shinelay", "rollcall", "roamee", "temper-ai", "temper ai", "lomit")


def rails_checklist_markdown(missing_groups: Iterable[str] | None = None, interviews: bool = False) -> str:
    """The one-time owner setup, as a checklist; groups still missing are marked [ ]."""
    missing = set(missing_groups or [])
    lines = [
        "## Validation Engine rails (one-time owner setup)",
        "",
        f"Put these in `{DEFAULT_RAILS_FILE}` (chmod 600; never in the repo). The engine reads key "
        "names only and never prints a secret. Copy configs/validation/rails.example.env to start.",
        "",
    ]
    for group, keys, note in LIVE_RAILS + (INTERVIEW_RAILS if interviews else []):
        box = "[ ]" if group in missing else "[x]"
        lines.append(f"- {box} **{group}** — {note} (`{'`, `'.join(keys)}`)")
        if group == "ads":
            for channel, ckeys in AD_CHANNEL_KEYS.items():
                lines.append(f"  - {channel}: `{'`, `'.join(ckeys)}`")
    lines += [
        "",
        "Accounts connected + budgets set + `VE_GO_AHEAD=yes` is the standing authorisation; the engine "
        "still stops and asks before exceeding a set budget.",
    ]
    return "\n".join(lines) + "\n"


def parse_env_file(path: str | Path) -> dict[str, str]:
    """KEY=VALUE lines (optional `export `, quotes, # comments). A missing file is an empty mapping."""
    p = Path(os.path.expanduser(str(path)))
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            out[key] = value
    return out


def _money(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        v = float(value.strip().lstrip("$"))
    except ValueError:
        return None
    return v if v >= 0 else None


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "yes", "true", "y", "on"}


def _group_missing(env: dict[str, str], groups: list[tuple[str, tuple[str, ...], str]]) -> list[str]:
    missing = []
    for group, keys, _note in groups:
        if any(not env.get(k, "").strip() for k in keys):
            missing.append(group)
    return missing


def evaluate_rails(
    env: dict[str, str],
    *,
    requested_mode: str = "dry_run",
    phase: str = "all",
    tier: str = "screen",
    interviews: bool = False,
    budget_usd: float | None = None,
) -> dict[str, Any]:
    """Decide what a run may do, from the rails present. Never raises; `stop` says why it must not go on.

    - `dry_run` is always allowed: local test URL, zero spend, synthetic traffic.
    - `live` needs every live rail, a set budget for the tier and the owner's go-ahead. A requested
      budget above the owner's set budget is a stop, not a clamp: the engine asks before exceeding it.
    """
    requested_mode = (requested_mode or "dry_run").strip().lower()
    phase = (phase or "all").strip().lower()
    tier = (tier or "screen").strip().lower()
    stop: str | None = None
    if requested_mode not in {"dry_run", "live"}:
        stop = f"unknown mode {requested_mode!r}: use dry_run or live"
    if phase not in {"all", "collect"}:
        stop = f"unknown phase {phase!r}: use all or collect"
    if tier not in {"screen", "confirm"}:
        stop = f"unknown tier {tier!r}: use screen or confirm"

    missing = _group_missing(env, LIVE_RAILS)
    channels = [c.strip() for c in env.get("VE_AD_CHANNELS", "").split(",") if c.strip()]
    bad_channels = [c for c in channels if c not in AD_CHANNELS]
    ads_keys_missing = ad_keys_missing(env, channels)
    if (bad_channels or ads_keys_missing) and "ads" not in missing:
        missing.append("ads")
    if env.get("VE_GO_AHEAD") is not None and not _truthy(env.get("VE_GO_AHEAD")) and "go_ahead" not in missing:
        missing.append("go_ahead")
    screen_budget = _money(env.get("VE_SCREEN_BUDGET_USD"))
    confirm_budget = _money(env.get("VE_CONFIRM_BUDGET_USD"))
    owner_budget = screen_budget if tier == "screen" else confirm_budget
    if owner_budget is None and "budget" not in missing:
        missing.append("budget")
    interview_missing = _group_missing(env, INTERVIEW_RAILS) if interviews else []

    stripe_key = env.get("STRIPE_SECRET_KEY", "")
    stripe_mode = "test" if stripe_key.startswith(("sk_test_", "rk_test_")) else ("live" if stripe_key else None)

    mode = "dry_run"
    if stop is None and requested_mode == "live":
        if missing:
            stop = (
                "live mode needs rails that are not set up yet: "
                + ", ".join(missing)
                + ". Nothing was deployed and nothing was spent."
            )
        elif budget_usd is not None and owner_budget is not None and budget_usd > owner_budget + 1e-9:
            stop = (
                f"requested ${budget_usd:.2f} exceeds the owner's set {tier} budget ${owner_budget:.2f}: "
                "ask the owner before spending more."
            )
        else:
            mode = "live"

    effective_budget = 0.0
    if mode == "live":
        effective_budget = budget_usd if budget_usd is not None else float(owner_budget or 0.0)

    non_secret = {k: env[k] for k in NON_SECRET_KEYS if env.get(k)}
    present = sorted(k for k, v in env.items() if v.strip())
    build = phase == "all"
    return {
        "schema": SCHEMA_VERSION,
        "checked_at": iso(),
        "requested_mode": requested_mode,
        "mode": mode,
        "phase": phase,
        "tier": tier,
        "stop": stop,
        "missing": missing,
        "interview_missing": interview_missing,
        "ads_keys_missing": ads_keys_missing,  # names only
        "bad_channels": bad_channels,
        "present_keys": present,  # names only
        "values": non_secret,  # non-secret values only
        "channels": channels or ["google-search", "reddit-ads"],
        "stripe_mode": stripe_mode,
        "owner_budget_usd": owner_budget,
        "budget_usd": round(effective_budget, 2),
        "go_ahead": _truthy(env.get("VE_GO_AHEAD")),
        # Flags the workflow's node conditions read (a condition can name one value only).
        "build": build and stop is None,
        "live": mode == "live" and stop is None,
        "simulate": mode == "dry_run" and build and stop is None,
        "interviews": bool(interviews) and stop is None,
        "interviews_live": bool(interviews) and mode == "live" and not interview_missing and stop is None,
        "checklist": rails_checklist_markdown(missing + interview_missing, interviews=interviews),
    }


# ---------------------------------------------------------------------------------------------------
# Pre-registration: the bars are written and hash-locked BEFORE any data exists, so a result cannot be
# rationalised afterwards (docs/validation_engine.md, "Pre-registered thresholds").
# ---------------------------------------------------------------------------------------------------

DEFAULT_THRESHOLDS: dict[str, float | int] = {
    # Rung 1 -- does the pain headline land? (cold social ~0.5-1.5%; search-intent higher)
    "ctr": 0.005,
    "ctr_kill": 0.003,
    # Rung 2 -- landing -> email (10%+ strong for a genuine pain; under 3% weak)
    "signup_rate": 0.10,
    "signup_rate_weak": 0.03,
    # Rung 3 -- the bar that matters most: an absolute count of costly actions from the segment
    "deposit_n": 3,
    # depth: share of real (bot-filtered) visits that read the page
    "engaged_rate": 0.30,
    # how much data a call needs (below these the engine flags sample_too_small instead of judging)
    "min_impressions_for_ctr_call": 1000,
    "min_sessions_for_rate_call": 20,
    "min_signups_for_commitment_call": 10,
    "min_clicks_per_variant_ab": 100,
    # a pivot: the best framing beats the worst by this factor on signup rate (or CTR) ...
    "pivot_ratio": 2.0,
    # ... and the gap is not noise: one-sided Fisher exact test, best vs worst framing
    "pivot_alpha": 0.05,
    # whole-list silence on the follow-up question is a red flag once this many signed up
    "min_signups_for_silence_flag": 5,
    # quality flags: share of sessions the bot filter dropped / real visits from outside the segment
    "bot_share_flag": 0.30,
    "segment_leak_flag": 0.10,
}

DEFAULT_ENGAGED = {"min_seconds": 10, "min_scroll_pct": 50, "section": "how"}
DEFAULT_BOT_FILTER = {"min_session_seconds": 2.0, "datacenter_ips": True, "ua_bots": True, "webdriver": True}
DEFAULT_WINDOW_DAYS = {"screen": 7, "confirm": 10}
DEFAULT_BUDGET_USD = {"screen": 50.0, "confirm": 300.0}
DEFAULT_DEPOSIT_USD = 49
DEFAULT_ASSUMED_CPC_USD = 2.0  # the spec's "~$2/click", used only until a real CPC exists
CONFIRM_CLICKS = {"min": 150, "max": 300}


REFUND_WITHIN_DAYS = 90


def build_preregistration(
    *,
    idea_id: str,
    idea: str,
    tier: str,
    mode: str,
    budget_usd: float,
    confirm_budget_usd: float | None,
    channels: list[str],
    segment: str = "",
    countries: list[str] | None = None,
    deposit_usd: int = DEFAULT_DEPOSIT_USD,
    overrides: dict[str, Any] | None = None,
    start: date | None = None,
) -> dict[str, Any]:
    """The pre-registered plan for one idea's test. `overrides` may only tighten/adjust known keys."""
    thresholds: dict[str, float | int] = dict(DEFAULT_THRESHOLDS)
    unknown = []
    for k, v in (overrides or {}).items():
        if k in thresholds:
            thresholds[k] = type(thresholds[k])(v)
        else:
            unknown.append(k)
    if unknown:
        raise ValueError(f"unknown threshold override(s): {', '.join(sorted(unknown))}")
    start_day = start or today_utc()
    window_days = DEFAULT_WINDOW_DAYS[tier]
    body = {
        "schema": SCHEMA_VERSION,
        "idea_id": idea_id,
        "idea_sha256": hashlib.sha256(idea.encode()).hexdigest(),
        "tier": tier,
        "mode": mode,
        "segment": segment,
        "countries": countries or ["US"],
        "channels": channels,
        "run_window": {"start": start_day.isoformat(), "end": (start_day + timedelta(days=window_days)).isoformat()},
        # The page promises a full refund if nothing launches within 90 days: the date is part of the test.
        "refund_by": (start_day + timedelta(days=REFUND_WITHIN_DAYS)).isoformat(),
        "budget_usd": round(float(budget_usd), 2),
        "confirm_budget_usd": confirm_budget_usd,
        "deposit_usd": int(deposit_usd),
        "assumed_cpc_usd": DEFAULT_ASSUMED_CPC_USD,
        "thresholds": thresholds,
        "engaged_definition": dict(DEFAULT_ENGAGED),
        "bot_filter": dict(DEFAULT_BOT_FILTER),
        "confirm_clicks": dict(CONFIRM_CLICKS),
        "decision_rules": DECISION_RULES_TEXT[tier],
        "registered_at": iso(),
    }
    return {**body, "sha256": sha256_of(body)}


def verify_preregistration(prereg: dict[str, Any]) -> bool:
    """True when the pre-registration is exactly what was locked (no bar moved after the fact)."""
    body = {k: v for k, v in prereg.items() if k != "sha256"}
    return bool(prereg.get("sha256")) and sha256_of(body) == prereg["sha256"]


DECISION_RULES_TEXT: dict[str, list[str]] = {
    "screen": [
        "KILL if CTR < ctr_kill over >= min_impressions_for_ctr_call impressions and no framing reaches ctr.",
        "KILL if >= min_signups_for_commitment_call signups and zero deposits/booked calls.",
        "KILL if >= min_sessions_for_rate_call real visits, signup rate < signup_rate_weak, and no framing reaches signup_rate.",
        "PIVOT if one framing clearly works (reaches signup_rate or ctr) while another flops (under signup_rate_weak or ctr_kill), "
        "best/worst >= pivot_ratio and the gap is significant (one-sided Fisher exact p < pivot_alpha): carry the winner to confirm.",
        "ADVANCE (to the confirm tier) otherwise: the screen only kills duds; a survivor earns the confirm spend.",
    ],
    "confirm": [
        "KILL if CTR < ctr_kill over >= min_impressions_for_ctr_call impressions and no framing reaches ctr.",
        "KILL if >= min_signups_for_commitment_call signups and zero deposits/booked calls.",
        "KILL if >= min_sessions_for_rate_call real visits, signup rate < signup_rate_weak, and no framing reaches signup_rate.",
        "ADVANCE if deposits >= deposit_n AND engaged rate >= engaged_rate AND the list is not silent on the follow-up question.",
        "PIVOT if one framing clearly works while another flops (same test as the screen tier): re-test the winner's framing.",
        "KILL otherwise: it did not clear the commitment bar. A clean no is a win.",
    ],
}

