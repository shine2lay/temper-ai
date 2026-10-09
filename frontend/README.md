# Temper AI Dashboard

The Temper AI dashboard — a React single-page application for monitoring, debugging, and designing multi-agent workflows.

## Tech Stack

- **React 19** + TypeScript 5.9
- **Tailwind CSS 4.1** + Shadcn/ui (Radix primitives)
- **React Flow** — DAG visualization
- **Zustand + Immer** — state management
- **TanStack React Query** — server state
- **Vite** — build tool

## Development

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 (proxied to backend on :8420)
```

## Build

```bash
npm run build    # outputs to dist/
```

The backend serves `dist/` as static files at `/app/*`.

## Structure

```
src/
  pages/           # Route-level components (WorkflowList, ExecutionView, StudioView, etc.)
  components/      # Feature-grouped components
    dag/           # DAG visualization (StageNode, AgentNode, edges)
    layout/        # App shell (Sidebar, Header, Tabs, Panels)
    studio/        # Workflow designer (Canvas, Palette, Properties, Editors)
    docs/          # Config reference docs
    shared/        # Reusable primitives (StatusBadge, EmptyState, ThemeToggle)
    ui/            # Shadcn/ui components
  hooks/           # Custom hooks (useConfigAPI, useDagElements, useDocsAPI)
  store/           # Zustand stores (executionStore, designStore)
  lib/             # Utilities (constants, utils, dagLayout, theme)
```

## Team journey (live)

The Team page's happy path as one test: open Team, fill the Run project form and start a
project, watch the run, answer the needs-you card, send a message, then read the outcome card
and the projects list. Every step is checked in the light and the dark theme: what the page
should show, axe (nothing found) and every button and link at least 24 x 24 px, with a
full-page screenshot of each.

The gate runs it against recorded answers (`e2e/team-journey.spec.ts`). This entry runs it
against a live Temper with Team switched on. **It starts a real project** (unless
`TEAM_JOURNEY_STOP_AFTER` stops it first), so run it by hand, only against temper-dev (the one
Temper there is), when a project start is approved and none is running. The gate never runs it:
the default config's `testDir` is `./e2e`.

```bash
cd frontend
TEAM_JOURNEY_BASE_URL=http://127.0.0.1:<port> \
TEAM_JOURNEY_SHOTS_DIR=/absolute/private/folder \
  npx playwright test -c playwright.live.config.ts
```

| Variable | Default | What it does |
| --- | --- | --- |
| `TEAM_JOURNEY_BASE_URL` | required | The Temper whose dashboard (`/app/team`) the journey drives. |
| `TEAM_JOURNEY_SHOTS_DIR` | required | Absolute folder for the screenshots, `report.json` and Playwright's notes on a failure (`playwright-output/`). Refused inside any git checkout, judged where the disk really keeps it (links followed; a folder still to be made by its nearest existing parent; no `..`), before Playwright starts: this repository is public, so screenshots and reports stay out of it. |
| `TEAM_JOURNEY_OWNER_KEY_FILE` | none | A file holding the owner's API key. Read when the test runs and kept in the browser the way the dashboard keeps it; never printed, logged, screenshotted or written to the report. Without it the answer and the message come from an unknown caller, and a Temper that asks for a key stops the journey at step 1. |
| `TEAM_JOURNEY_TIMEOUT_S` | `300` | How long to wait for what only the team changes: the run opening, a new entry, the pause, the answer and the message showing, the end. |
| `TEAM_JOURNEY_ANSWER` | the first answer offered | The needs-you answer to pick, by the start of its visible label (for example `Continue`). The journey never picks Stop. |
| `TEAM_JOURNEY_ROLES` | one member, the first role offered | The form's Role for each member, comma-separated; the first one leads. |
| `TEAM_JOURNEY_PAUSE` | `1` | The form's "Pause after this many rounds without done": 1 makes the team ask after its first round. |
| `TEAM_JOURNEY_WHO_CAN_MESSAGE` | the form's own choice | The form's "Who can message whom", by the start of its visible label. |
| `TEAM_JOURNEY_PROJECT` | empty (Temper's default) | The form's Code folder (optional). |
| `TEAM_JOURNEY_STOP_AFTER` | none: the whole journey | Stop, passed, after this step: `team`, `form`, `run`, `needs-you`, `message` or `outcome`. `form` stops with the form filled in and not sent, so no project starts. |

The journey types a tag (`journey-<time>`) first in the project's goal and in the message, and
finds both again by it; it needs no member's words. For it to pass, the team must:

- be running when the page first reads the run, keep working for at least 10 seconds (the
  page reads every 5), and add at least one timeline entry after the run opens;
- pause after its first round (the needs-you card), with an answer other than Stop on offer;
- keep running for a minute or more after the answer, so the message is sent while it runs;
- then end: done, stopped, failed or didn't start.

The journey installs no route and makes no API call of its own. The owner's browser clicks
only New project, Add member (when given more than one role), Run project, one answer and Send
answer, and Send message; never Stop run, Cancel or a setting. The dark-theme looks come
from a second browser that only opens pages. If `GET /api/team/status` answers 404, the
journey stops at step 1 with "Team is switched off on this server".

`report.json`, written after every step, holds per step its checks and, per theme, the URL,
the checks passed, axe's findings by impact, any target under 24 px and the screenshot's
name; then the project's run id, the answer picked, who Temper says answered, the end state and
the result (`passed`, `failed` with the failing step and its error, or `stopped`).
