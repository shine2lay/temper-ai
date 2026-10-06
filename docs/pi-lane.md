# The Pi lane — switched off

Pi runs (any workflow with a Pi step at any depth, which includes a team stage of Pi
members, [pi-agent.md](pi-agent.md)) run in one place only: the **Pi lane**, a small worker of
its own, the `pi-worker` compose service. The main worker never claims a Pi run; the Pi lane
never runs anything else. M4 ADR-M4-01, -03, -05, -06 and -11, and HOME-REVIEW H1–H4.

It is **off**: `pi-worker` is under the compose profile `pi`, which nothing starts by default,
and its runs need the Pi switch ([pi-agent.md](pi-agent.md)). With the lane down, a Pi run
waits in the queue, visibly; it never falls back to the main worker.

## The lane mark

A Pi run's row carries `{"lane": "pi"}` in `workflow_runs.spawner_metadata`; every other run
carries no mark and is created, claimed and run exactly as before (`temper_ai/runner/lanes.py`,
no new column). The mark is decided from the workflow as it loads (`lane_for`), and the two
places that write a run row set it, through one helper (`mark_lane`), on every insert and every
re-queue:

- `runner/queue.py` `queue_run`: the insert, and the re-queue of a resumed, forked, cleaned-up
  or picked-up run. A re-queue whose caller didn't load the workflow keeps the row's own mark
  (`KEEP_LANE`); the worker's own keys (`box_profile`, `pi_lane`) survive it too.
- `api/routes.py` `_start_run_subprocess`, the server's direct spawn. A Pi run never spawns
  there: it goes to the queue for the Pi lane, in every execution mode.

Every way a run is made reaches one of them: `POST /api/runs` (and so `temper run`, which posts
to the server, MCP `temper_start_run`, triggers and schedules, Slack, the GitHub, Linear and
Notion hooks, and a team trial's start), Resume, fork, the clean-up pass and its hold sweeper,
the parked-run carry-on (`runner/parked.py`), the server's start-up pick-up
(`runner/pickup.py`) and the Pi lane's own (`runner/pi_lane.py`). A claim (`cli/watch_queue.py`
`_stamp_handle`) and an unclaim merge the metadata, so the mark stays.

Who claims what (`lane_clause`, on SQLite and Postgres alike):

- the main watcher, its reaper and the server's pick-up: rows without the mark only;
- the Pi lane's watcher (`TEMPER_LANE=pi`), its reaper and its pick-up: marked rows only.

**One Pi run at a time**, counting a parked one (ADR-M4-11, SW-55): the Pi lane claims a
queued Pi run, oldest first, only while no other Pi run is running, parked, or claimed and not
yet started (one guarded `UPDATE`). A queued Pi run the lane hasn't claimed shows
`"queued_reason": "waiting for the Pi lane"` on `GET /api/workflows/{id}` (SW-40), and the
run page shows it beside the status, whether the lane is down, switched off or busy; the
watcher logs it once per run. Cancelling one ends it at
once (no worker would).

## What runs in it: the Pi-only rule

The Pi lane holds the Docker socket its member boxes need, so it runs only Pi steps, team
stages of Pi members, and gates on any of them (ADR-M4-01, SW-41, SW-30). Refused by name:
script steps and every other agent type, a step that asks for MCP or tool servers, and the
workflow's own `safety: policies:` (the member box is the boundary). The rule is checked at
submit (`400`, naming every step) and again at claim, on the workflow as it loads then (a
changed config fails the run red, naming the step). `configs/workflows/ci_pi_waits.yaml`, with
its script steps, is refused, so only tests run it ([gates.md](gates.md)).

**A Pi step outside the lane refuses** (SW-42): a run process that isn't the Pi lane never
starts a marked run, and the Pi step and the team node fail "Pi steps run only in the Pi lane"
before anything of theirs runs. Within the lane, a run without the mark is refused too.

## Before each run: the preflight

The run process checks, before the run is marked running and before any turn
(`runner/pi_preflight.py`, ADR-M4-05, SW-46). A failed check fails the run red, naming every
reason; nothing of it runs:

| reason | fails when |
| --- | --- |
| `pi_switched_off` | the Pi step isn't switched on in the Pi lane's worker |
| `commit_unreadable` | the temper commit the worker runs can't be read from the checkout's `.git` (a dropped mount, say), which every Pi run records (SW-16) |
| `box_config` | the box config can't be read or fails its own checks: runtime, Pi version, identity files, add-on and search-tool pins (until #53, see below) |
| `roots` | no roots, a root that isn't a folder here, a state or socket root that isn't writable |
| `uid` | the worker isn't 1000:1000, so its members wouldn't be (SW-43) |
| `socket_path` | a turn's socket path would reach 100 bytes (SW-44) |
| `docker` | Docker doesn't answer |
| `image` | the pinned worker image isn't on this Docker host |
| `host_helper` | live mode without the helper's socket, a helper that doesn't answer ok, or a login bridge that isn't ready |
| `template_mounts` | the run-box template (the server's container) mounts a Pi or project folder (the folder itself, inside it or above it), or can't be read |
| `workspace_overlap` | a Pi folder (state, sockets, pins, role folders, the helper's socket folder, project roots) inside `WORKSPACE_DIR`, which every run box may mount (H3, SW-77) |
| `pi_schema` | the `pi_` tables can't be brought to this build's version |
| `disk` | less than 2 GiB free under the state root |

Until queue #53 lands its pins function, the box config's own checks stand in for the pins
check and the identity settings' read-back (D3). They sit behind one function,
`pins_and_identity()`, which #53 replaces with its own. The project folder's real checks run at
the team's start ([pi-team-api.md](pi-team-api.md)).

Inside `pi-worker`, `workspace_overlap` compares the paths as the container sees them. Docker
resolves a linked source on the host when it mounts it, so a link on the host can hide an
overlap from it: the host's own read-back at switch-on (SW-77) stays the real check.

The same run process also imports every temper module before the run (H2, SW-76), at the
start and at every resume (each is a new process): a deploy that changes the code on disk
never mixes into a running Pi run. And it records the temper commit it runs on (SW-16), in the
row's `spawner_metadata` as `pi_lane.commits` (`{at, start, commit}`, one per attempt) and in
the log. The commit is read from the checkout's `.git`, which `pi-worker` alone mounts,
read-only (never a member box or a run box; SW-38). No git command runs on that mount: the
commit is read from `HEAD` and the ref files the way `git rev-parse HEAD` resolves them, so no
hook, no fsmonitor and no ownership check runs. In the Pi lane a commit that can't be read
refuses the run (`commit_unreadable`); outside it (in-process, dev, CI) it records `unknown`.

## The pi-worker service

`docker-compose.yml` `pi-worker`: the worker image (no build of its own), profile `pi`,
`stop_grace_period: 960s`, `init: true`, no `depends_on` (recreating `server` or `worker` never
touches it), no `env_file`. It runs `watch-queue` as the image's user, uid 1000
(`temperai-worker`), the one uid the host helper answers.

It holds **no secrets beyond the database and Redis URLs**: no provider keys, no token pool, no
integration secrets and no `TEMPER_SECRET_KEY` (its one reader is MCP OAuth,
`tools/mcp_auth.py`, and the Pi lane runs no MCP servers). Model logins come per turn from the
host helper ([pi-host-helper.md](pi-host-helper.md)). Its environment, in full:
`HOME`, `PYTHONDONTWRITEBYTECODE`, `TEMPER_DATABASE_URL`, `TEMPER_REDIS_URL`,
`TEMPER_LOG_LEVEL`, `TEMPER_LANE=pi`, `TEMPER_SPAWNER=subprocess`, `TEMPER_PI_AGENT=1`,
`TEMPER_PI_BOX_CONFIG`, and, read by the preflight only, `TEMPER_DOCKER_TEMPLATE_CONTAINER`
and `WORKSPACE_DIR` (a name and a path; the workspaces are not mounted).

Its mounts: the code (`temper_ai/`, `configs/`) and the checkout's `.git` (for the commit;
`pi-worker` alone gets it), read-only; the Docker socket. The machine's own folders are mounted **at the same paths as on the host**,
because the member boxes it starts mount them by those paths (ADR-M4-03): the state root, the
socket root (which holds the host helper's socket), the pins (`~/.local/share/temper/`), and,
read-only, the role folders, the project roots and `local/pi/` (the box config). Those paths are
this machine's, so they live in the git-ignored `docker-compose.override.yml`, never in the
public file:

```yaml
# docker-compose.override.yml (git-ignored): a self-sufficient entry, so compose still
# works when the base file has no pi-worker (rollback)
services:
  pi-worker:
    image: temper-ai-worker
    profiles: [pi]
    environment:
      TEMPER_PI_BOX_CONFIG: /home/<you>/temper-ai/local/pi/pi-box.json
    volumes:
      - {type: bind, source: /home/<you>/.local/state/temper/pi/runs,
         target: /home/<you>/.local/state/temper/pi/runs, bind: {create_host_path: false}}
      # ... the socket root and the pins the same way; the role folders, the project
      # roots and local/pi/ the same way with read_only: true
```

Never mounted: `~/.claude/.credentials.json`, the rest of `local/`, `~/.temper/`, the Claude
versions folder, `WORKSPACE_DIR`.

Its member boxes (`pi_agent/box.py`, SW-43, SW-44): `--user` the worker's own uid and gid
(1000:1000), never the template's or the docker group; every bind source inside the box
config's `roots` (`bind_source_outside_roots` otherwise); every socket path under 100 bytes
(`socket_path_too_long`); the step's assets sealed-copied into the state root before they are
mounted; `no_owner_pi_mount` checked against `host_home` as well as the worker's own home.
Nothing sweeps the socket root: a box removes only its own `b*` folder when it closes, never
the helper's `host.sock`. A later sweep of stale per-box folders (after a crash) must keep to
the `b*` folders and come with a test that `host.sock` survives it.

**Only the Pi lane may run child processes beside a Docker socket** (H1, SW-75): any worker
with `TEMPER_SPAWNER=subprocess` that can reach Docker refuses to start, except one with
`TEMPER_LANE=pi`; that one refuses any other spawner and refuses to start without the Pi
switch. An unknown `TEMPER_LANE` stops any worker. A run box never gets `TEMPER_LANE`
(`shared/box_env.py` `PI_ONLY`, [boxes.md](boxes.md)).

## Decided from database rows (H4)

Every Pi lane decision is read back from rows at the moment it is made (SW-78):

- **claim and cancel**: `workflow_runs` (status, claim, lane mark, `cancel_requested`), read by
  the watcher's scan and the reaper;
- **waits and their answers**, a team's stop, carry-on and question answers among them: the
  `pi_waits` rows and the answer `Event` rows that `stage/step_waits.py` files under each
  wait's name. #38's leader loop asks through `pi_agent/owner_waits.py` and reads its answers
  back from those rows (`ask_owner`, `gate_events`); #48's routes write rows only (an answer
  through `approve_wait`, a message into the ledger's inbox). A parked run carries on only on
  an approved row (`runner/parked.py` `answered`);
- **the account-limit state**: an uncertain turn and its recovery wait, `pi_` ledger rows;
- **the switch**: the process's own setting, `TEMPER_PI_AGENT`, never a message.

Redis carries only the live chunks and script logs a run streams to the dashboard
(`streaming/`) and the token pool's shared cooldowns, which Pi doesn't use. No module the lane
decides in reads it; the lane polls the database, so there is nothing for a message to wake.
A forged message (a cancel, an answer, a switch-off, a cleared limit, a claim) only reaches
the dashboard's live view. This defeats forged Redis events only: until the box secrets steps
(#46) and a restricted database role (#26) stop run boxes writing the database, those rows are
not a security boundary (HOME-REVIEW R7).

## Stopping and starting (ADR-M4-06, SW-48, SW-49)

**On SIGTERM** the Pi lane claims nothing more and raises a drain mark (`TEMPER_PI_DRAIN_MARK`,
a file inside its container) that its runs check at each turn boundary: a team before its next
member turn, a Pi step before its next turn. A turn under way finishes (its 900 s hang guard
included); the run then leaves as interrupted (exit 75), with no turn half done, and the
watcher waits up to 930 s for them, inside the 960 s grace. A parked run has no process and is
untouched.

**At its start**, before claiming anything (`pi_lane.start_up`): it stops and removes leftover
member boxes, each by its exact name (from the ledger's unsettled turns and the
`temper.pi.box=1` label; never a prune); puts back the runs the last instance claimed but never
started; ends the ones it was running (their processes went with its container: a parked one
is let go to wait, any other is interrupted); and picks up the Pi runs a stop cut off in the
last 12 h, from their ledger, through the same one-claim resume as Resume (SW-80). A turn that
was cut off mid-way becomes a recovery wait when the run resumes (`Ledger.take_over`).

## lane-status: for temper-deploy

```bash
docker compose exec -T server /app/.venv/bin/temper pi lane-status --json
```

It reads database rows only: no model, no API call, no credential, and it answers with the Pi
switch off. It never creates a table. Exit 0 with one JSON object:

```json
{"ok": true, "checked_at": "<UTC ISO time>",
 "active": [{"run_id": "...", "why": "turn_running"}],
 "parked": [{"run_id": "...", "waiting_on": "owner"}],
 "queued": [{"run_id": "..."}]}
```

- `active`: a Pi run with a member turn running (`turn_running`), or claimed and not parked
  (`claimed`);
- `parked`: a Pi run waiting with no process; `waiting_on` is its first open wait's kind
  (`owner`, `recovery`, `stalled`, `pause`), or `gate` for a gate's wait;
- `queued`: a Pi run not claimed yet.

Run ids, why and wait kinds only, never content. Any failure (no database configured, the
database unreachable, tables missing or not as expected) exits 2 with
`{"ok": false, "error": "<plain text>"}`, never an empty list.

temper-deploy recreates `pi-worker` only while `active` is empty, with
`docker compose --profile pi up -d --no-deps --no-build --force-recreate pi-worker`, and never
starts it when it isn't running; its own `SERVICES` stay `server worker`. A parked run doesn't
block an update: its resume records the commit it resumes on.

## Rollback

`docker compose --profile pi stop pi-worker`. The main worker keeps refusing Pi runs; they wait
in the queue, "waiting for the Pi lane", and a parked one keeps waiting. To switch Pi off as
well, follow [pi-agent.md](pi-agent.md).

## Tests

`tests/test_runner/pi_lane/`: the mark on every entry point both ways, the claims and one run
at a time, the Pi-only rule, the preflight's reasons, drain and start-up, lane-status, H1
(`tests/test_spawner/test_subprocess_beside_docker.py`), H2, H4's forged Redis messages
(`test_redis_decides_nothing.py`), and the secret key never read, on SQLite and the Postgres
tier. A stop and a crash mid-turn, end to end: `tests/test_runner/pi_parking/test_pi_lane_restarts.py`.
The Pi step's own tests run as the Pi lane (`tests/test_pi_agent/support.py`
`into_the_pi_lane`).
