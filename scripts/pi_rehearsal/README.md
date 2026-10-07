# Pi rehearsal rig

A team run on real member boxes with a scripted model, on its own compose project. Run it
by hand only. The gate never runs it; `tests/test_pi_rehearsal/` covers its pure parts
without Docker.

Queue #74 built it for one bundled normal run (the preliminary practice run). #54 adds its
other scenarios here.

## What it is

- **Real member boxes.** Every member turn runs in its own box, `temper-pi-<20 hex>`. The
  real launcher (`WorkerBox`, `temper_ai/pi_agent/box.py`) starts it through the rig's own
  pi-worker on this host's Docker. The boxes use production's image, by id, and copies of
  production's pins, digest-matched. Production's Pi roots are read and copied, never bound.
- **Rehearsal mode, scripted model.** The box config's `mode` is `rehearsal`:
  - each box's egress relay ends at `standin.py`, a local TLS stand-in for the provider in
    pi-worker's network namespace;
  - the stand-in plays the members from `scenario.py`;
  - tokens are synthetic, and the helper is never asked for one.

  A rehearsal box differs from a live one by exactly one read-only mount (`/box-ca/ca.pem`,
  the stand-in's CA) and one setting name (`NODE_EXTRA_CA_CERTS`).
- **An isolated rig.**
  - The compose project is `pi-rehearsal-<id>` (never `temper-ai`, and never `temper-box-*`,
    which is temper-ci's prefix).
  - It has its own Postgres and Redis and an internal network.
  - The dashboard is built in the rig's own clone and served on a free 127.0.0.1 port.
  - The test helper is `scripts/pi_host/temper_pi_host.py`, with a stub bridge and
    `project_roots: []`.
  - Synthetic role folders and throwaway API keys (one named `owner-dashboard`).
- **The first trial's settings** (ADR-M4-19, ADR-M4-22):
  - five members, led by product;
  - `account_pick: settings_order` with one slot and no account-room file;
  - pause after 1 round;
  - an empty start (no project).

## Steps

Run each step from a temper-ai checkout, under `systemd-run --user`. Every step after
`prepare` takes `--rig /tmp/pi-rehearsal/<id>`.

| Step | What it does |
| --- | --- |
| `prepare --label preparation\|evidence --head <rev> [--id <8 hex>]` | Makes the rig's 0700 temp tree: its clone at `<head>`, the dashboard build, the pin copies (refused unless their digests match production's), the box config, the CA, roles, the helper, keys and `compose.env`. An evidence rig must have this folder committed at `<head>`, along with the landed commits in `LANDED`. A preparation rig copies the folder over, uncommitted. |
| `build` | Builds the rig's server and worker images. |
| `create` | Creates every container without starting any. Then the mount check (`audit.py`): every bind source must be inside the rig's tree or its clone, except pi-worker's `docker.sock`. Owner credentials and role state are refused, and anything unknown counts as no. |
| `up` | Refuses while any member box exists on the host. Starts the helper and the rig; pi-worker starts through the real preflight, with the pin check. |
| `drive --via api\|page [--runs N]` | Runs the bundled normal scenario and reads it back. `api` answers the team's pause and sends the owner's message with the owner key. `page` runs Frontend's live journey (`frontend/e2e-live/team-journey.live.spec.ts`), which clicks as the owner would. |
| `down` | Removes the rig's containers, volumes, images, helper and temp tree. The record stays. |

## The record

Everything goes to `~/kept-from-tmp/<date>/pi-rehearsal/prelim/<label>-<id>/`. That folder
is private and is never committed.

- `prepare.json`: the head, the tree, the landed commits, the pins and the settings map.
- `mount-check.json`.
- `rig.json` and `helper.log`, written at `down`.
- `runs/<n>-<run id>/`:
  - `readback.json` and `ledger.json`;
  - `checks.json`, one row per check from `checks.py`;
  - `topology.json`;
  - `member-boxes.names.json`: names only, never a value;
  - `run-view.json`;
  - `logs/`.
- `runs/<n>-page/`: the journey's `report.json` and screenshots.

Each check row is an observation of that run on the rig. It is never a pass of a switch-on
item.

## Adding a scenario (#54)

1. In `scenario.py`, add rules and register them in `SCENARIOS`. The stand-in picks one with
   `STANDIN_SCENARIO`.
2. In `checks.py`, add the checks it needs.
3. In `rig.py`, add a driver if the owner's side differs.

Keep the existing checks and their names. Never weaken one to make a run pass.
