# Alerts: Details and the way to the action — spec for Frontend

Draft A v3 direction. Prototype: `draft-a/index.html` → the bell in the top bar → Alerts (`draft-a/src/screens/alerts.js`). Data: `fixture.json` `alerts` (the cards) + `fixtures/alerts_more.json` (each alert's Details; stands in for `GET /api/alerts` `Alert` rows). Checks: `node draft-a/check-orders-alerts-more.mjs` (Details and the action, real clicks at 1440×900, 390×844, 320×568) and `node draft-a/check-alerts-more.mjs` (the rest of the screen); both exit 0.

## What it is

Each alert card says what happened in plain words and offers the one thing to do about it. Under it, a "Details" row, closed by default, holds what someone checking the alert wants: the full plain message, the engine's technical text, the rule that fired, and how each channel delivered it. The closed row already sums up delivery in one line, so a failed push is visible without opening anything.

## Card, top to bottom (unchanged parts in short)

| Part | What it shows | Today's code / data it maps to |
|---|---|---|
| Head | "New" (unread), severity chip, time · how it reached you ("Push to phone", "Telegram", "Email" or "In the app") | `Alert.severity`, `created_at`; "reached you by" = the first delivered of ntfy/Pushover (→ Push to phone), then Telegram, Email, else In the app |
| Title + lead | e.g. "XOM roll due" + the alert's body | `alertCopy` headline + `Alert.body` |
| Action | open action: one button to it (see below); done action (PFE filled): none | `Alert.meta.rec_id` / linked recommendation (today's `hrefLabel` link) |
| Details row (button, `aria-expanded`, `aria-controls`) | "Details" + delivery line + chevron (points down closed, up open) | today's "Details ▾" / "Hide details ▴" |
| Details panel (hidden until opened) | plain message, Technical, Rule, Delivery | today's `hc-drawer` |

## The action: to Today

- An open action's button goes to its card on Today: `data-act="action-open" data-id="<action id>"`, e.g. T "See the call" → `data-id="act-t-new-call"` (tonal). Today's side (scroll to and highlight that card) is Design #191; until it is in a build, the button only needs those attributes.
- XOM keeps its direct "Review the roll" (solid primary, opens the roll ladder, `data-act="open-roll"`) and adds a ghost "Open on Today" (`data-act="action-open" data-id="act-xom-roll"`). After the roll is sent: "Roll sent · working at the broker. It shows in Orders." and no buttons.
- A done action (PFE order filled) has no button.
- One solid primary per view.
- Maps to: today's `Link to={href}` with `hrefLabel` ("See this action", or the recommendation's own label); the build points it at Today's card for `Alert.meta.rec_id` instead of the Actions page.

## Details

Closed delivery line (one line, from the deliveries; amber when anything failed):

| Deliveries | Line |
|---|---|
| ntfy sent | "Sent by ntfy" |
| ntfy failed, Telegram sent | "ntfy failed · sent by Telegram" |
| ntfy and Telegram failed (app only) | "ntfy and Telegram failed · in the app only" |

"In the app" is never named in the line unless it is the only one that worked. A line that starts with a channel keeps its name as written (ntfy is lower case).

Open, in this order:

1. **Plain message** — the full plain-English summary (16 px, `--ink-text`). `Alert.meta.summary` (today's `copy.summary`).
2. **Technical** — eyebrow "Technical", then the engine's text, e.g. "XOM 11/06/26 112C x2: spot 114.60, ITM 2.60 (cushion -2.3%), …" (16 px body face, `--ink-600`, wraps anywhere; never clipped). `Alert.meta.details` (today's `copy.technical`).
3. **Rule** — "Rule" + plain name + the id in a quiet pill: "Roll for credit · roll.credit". Name from `ruleLabel(rule)`; id `Alert.meta.rule`.
4. **Delivery** — eyebrow "Delivery", then one row per channel, always all five, in this order with exactly these names: **ntfy, Pushover, Telegram, Email, In the app** (backend ids `ntfy`, `pushover`, `telegram`, `email`, `inapp`).

| Row state | When | Shows |
|---|---|---|
| Sent (teal) | a delivery row with `ok: true` | "Sent" + time ("6:31 AM"; date added when not the alert's day) |
| Failed (coral) | a delivery row with `ok: false` | "Failed" + time + the reason under it ("ntfy.sh didn't answer within 10 s.") |
| Not needed (quiet) | no delivery row; channel is the backup (Settings fallback) and the first channel worked | "Not needed" + "Backup, used only when ntfy fails" |
| Off (quiet) | no delivery row; channel not on in Settings | "Off" + "Not set up" (Pushover) / "Turned off in Settings" (Email) |

Delivery times are in the alert's own time zone. Failure reasons are the backend's plain `detail`; never codes, tokens or URLs with secrets.

Layout: desktop rows are a grid (name · state · time, reason under, Off/Not needed reasons right-aligned in the time column); phone rows put name and state on one line and time (14 px) or reason on the next.

## Behaviours

- Details toggles in place; focus stays on the Details button; each card opens on its own (several can be open).
- "Mark all read" and its Undo are unchanged (check-alerts-more.mjs).
- The bell's Alerts screen's Back returns to the screen the bell was pressed on (unchanged).

## Sizes and type

Desktop 1440×900 (center column), phone 390×844 and 320×568, cards full width. Body 16 px, labels and times 14 px, 12 px only for uppercase eyebrows ("TECHNICAL", "DELIVERY"); Details button and action buttons 44 px+ on the phone. No text clipped or line-clamped. Tokens and classes from `draft-a/src/page.html`.

## PNGs (made by the check, in `draft-a/`, one each for `desktop`, `phone390`, `phone320`)

- `alerts-details-closed-<size>.png` — all cards, Details closed with their delivery lines
- `alerts-details-<size>.png` — XOM's Details open (plain, technical, rule, five channels)
- `alerts-details-failed-<size>.png` — PFE's delivery: ntfy failed with its reason, Telegram sent

## Removed or renamed versus today's page

| Today (`frontend/src/pages/Alerts.tsx`) | Draft A |
|---|---|
| Footer "✓ in-app, ntfy ✗ telegram" with a hover title for times | Closed Details line ("ntfy failed · sent by Telegram"); times in the open Details rows (no hover needed, works on a phone) |
| Channel labels "in-app", "email" | "In the app", "Email" (ntfy, Telegram unchanged); Pushover added |
| "Sent" row listing only channels that were tried | "Delivery": all five channels, each Sent / Failed / Off / Not needed with time or reason |
| "When" row | Removed: the card head has the time, each delivery row its own |
| "Key" row (`rec:act-xom-roll:roll.credit`) | Removed from view; it stays in System > Audit with the alert |
| "History" link "Dispatch and per-channel delivery, in the audit trail" | Removed from Details (delivery is now shown in full); System > Audit unchanged |
| Link "See this action" → Actions page | Button to the action's card on Today (`action-open`); XOM also keeps "Review the roll" |
