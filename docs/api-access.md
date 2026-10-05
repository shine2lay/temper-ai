# Who may change things: the write guard

Anyone who can reach temper's server can read it. Changing something (starting
a run, answering a wait, cancelling, resuming, forking, cleaning up, writing a
config) can be made to need a named key, and every such action records who did
it. Run boxes can reach the server too (on the compose network and through any
proxy the host has), so no network rule would fence them; a key they never get
does.

## Modes

`TEMPER_API_GUARD` on the server (`.env`, then recreate the server):

| mode | an action from an unknown caller | logged |
|------|----------------------------------|--------|
| `off` (default) | allowed, as before | nothing |
| `record` | allowed | one line per action, and a count |
| `enforce` | refused: 401 (no key), 403 (a run's own key used beyond its scope); a wait stays open | the same line |

The log line names the action, the way in (`POST /api/runs/<id>/approve/<node>`,
`mcp approve_gate`, or the Python function for an in-process call), the source
address and the run id. Never a key.

`GET /api/guard` (open, read-only) shows the mode and, per caller and action,
how often and when it was last seen; `caller: null` is a writer nobody could
name. `caller: "?browser"` is an unknown writer whose request carried the
`Sec-Fetch-Mode` header every browser sends (most likely the dashboard before
anyone typed its key in; `enforce` will ask for it). That is a hint for
reading the record, never an identity: anyone can send the header, and
`enforce` refuses it like any other unknown caller. Before switching to
`enforce`, run `record` until that list has no null row you can't explain.

Rollback: set the mode back to `record` (or `off`) and restart.

The older `TEMPER_API_TOKEN` (one token for every route, reads too) is
unchanged and independent. It does **not** name a writer for this guard,
because every run box's own process carries it (see [boxes.md](boxes.md)).

## What needs a key

Every operation that changes state checks its caller itself
(`require_caller_may` in `temper_ai/api/caller.py`), not its route: the MCP
tools, Slack and Telegram call the same functions in-process, so a check on the
HTTP route alone would let the MCP side door straight past.

| action | HTTP | MCP tool | other ways in |
|--------|------|----------|---------------|
| start a run | `POST /api/runs` | `run_workflow` | Slack, Telegram, Notion, Linear/GitHub hooks, triggers |
| answer a wait | `POST /api/runs/{id}/approve/{node}` | `approve_gate` | Slack, Telegram, Notion buttons and replies |
| cancel (rejects open waits) | `POST /api/runs/{id}/cancel` | `cancel_run` | Slack, Telegram |
| resume | `POST /api/runs/{id}/resume` | | Slack, Telegram, start-up pickup |
| fork | `POST /api/runs/fork` | | |
| clean up a held run | `POST /api/runs/{id}/cleanup` | | |
| write a config | `POST`/`PUT`/`DELETE /api/studio/configs/{type}/{name}` | | |
| replay an inbox event | `POST /api/events/{id}/replay` | | |
| run the triggers now | `POST /api/triggers/tick` | | |
| mint a GitHub repo token | `POST /api/github/token` | | a run's own process (GitHub app tools) |

Not behind the guard, each with its own check:

- the signed hooks (`/api/hooks/linear|notion|github`): their signature is
  their key; what they start runs as `hook:<source>`;
- the Slack test entry (`POST /api/test/slack`): its own secret
  (`TEMPER_SLACK_TEST_TOKEN`, server-only); the fake event then acts as the
  Slack user it names. Fake replies come from the server itself;
- `POST /api/studio/validate/{type}` changes nothing;
- the WebSocket only sends; it takes no actions;
- `/mcp` read tools.

## Callers and their names

| caller | how it is named |
|--------|-----------------|
| the dashboard | a named key (e.g. `owner-dashboard`), asked for once per browser on the first action; reading needs none |
| scripts and tools on the host | a named key each, read from its file (`TEMPER_API_KEY_FILE`) |
| pi's temper MCP connection | a named key (e.g. `pi`) in the MCP connection's `Authorization` header, or `temper_ai.mcp.bridge` with `TEMPER_API_KEY_FILE` |
| `temper run` from `docker exec` in the server container | `server`: the server's own loopback, only when runs happen in their own boxes (`TEMPER_EXECUTION_MODE=external` in a container); elsewhere it needs a key |
| Slack | `slack:<user id>`, after the Slack access fence ([slack.md](slack.md)) |
| Telegram | `telegram:<user id>`, after its own allow-list ([telegram.md](telegram.md)) |
| Linear, Notion, GitHub hooks | `hook:linear`, `hook:notion`, `hook:github` |
| triggers | `trigger:<trigger name>` |
| start-up pickup | `pickup` |
| carrying a parked run on after its answer, when no one is bound (the run's own thread letting go) | `carry-on`: only while the run is still parked on an answered wait; inside an answer it stays the answerer |
| a run's script steps (`starts_runs: true`) | `box:<run id>`: start and fork runs only |

Source addresses, as the server sees them in a compose install: the host, a
host-network container and anything through a reverse proxy on the host all
arrive from the network's gateway (e.g. 172.21.0.1); a box or the worker from
its own address; `docker exec` inside the server from 127.0.0.1. So the address
can't tell the host from a box that went through the proxy: only a key can.

## Named keys

The server keeps only sha256 hashes, in `configs/api/local/keys.json`
(git-ignored; or `TEMPER_API_KEYS_FILE`):

```json
{"keys": {"owner-dashboard": "sha256:<64 hex>", "autopilot": "sha256:<64 hex>"}}
```

It re-reads the file when it changes: removing a name stops that key on the
next request, no restart. A malformed file accepts no key (and `temper check`
says why); a raw value instead of a hash is refused. Names are lower-case
`[a-z0-9._-]`; names the server gives itself (`server`, `pickup`, `carry-on`, `box:...`,
`slack:...`, `telegram:...`, `hook:...`, `trigger:...`) can't be taken by a key.

```bash
python3 scripts/api_key.py add autopilot      # key -> ~/.config/temper/api-keys/autopilot.key (600)
python3 scripts/api_key.py list               # names only
python3 scripts/api_key.py remove autopilot   # revoked on the next request
```

The key itself lives only in its file, outside every folder mounted into the
server, the worker or a box (a box is made from the server's container, so it
sees the server's mounts; `docker inspect temper-ai-server-1` lists them; the
whole repo is one of them). `api_key.py` refuses a key folder inside the repo.
Never put a key in `.env`, a tracked file, a box's environment, a log or a chat.

A client sends it as `Authorization: Bearer <key>` (or `X-Temper-Token`).
Not as `?token=` or a cookie: those end up in logs and are sent by a browser on
its own. temper's own clients (`temper run`, the MCP bridge, the CI scripts)
read it from the file named by `TEMPER_API_KEY_FILE`.

## A run's own key (`starts_runs`)

A workflow whose script steps start other runs declares it:

```yaml
workflow:
  name: epd_loop
  starts_runs: true
```

When such a run starts, its process makes a fresh key (`temper_ai/api/run_tokens.py`):

- the server stores its sha256 with the run (table `run_tokens`);
- the key stays in the run process's memory, not its environment, and is
  given only to its **script** steps as `TEMPER_RUN_TOKEN`; agent tools never
  get it, so a model never holds it;
- it is named `box:<run id>` and may start and fork runs, nothing else: never
  answer a wait, cancel, resume or clean up (403);
- it dies with the run: dropped when the run's process ends, and ignored once
  the run is finished.

A script sends it like any key: `Authorization: Bearer $TEMPER_RUN_TOKEN`.
A workflow without `starts_runs` gets no key; `temper check` lists the ones
that hold one and flags a `starts_runs` that isn't `true` or `false`.

## What is recorded

- On every answered or rejected wait (the event's data): `gate_decided_by`
  (who, as the answering side tells it: "Shine (Slack)", "MCP"; else the
  caller's name), and `gate_caller`, `gate_caller_from`,
  `gate_caller_request_id` (the key's name, source address, and the request's
  `X-Request-ID` or a generated one). `gate_request_id` stays the client's own
  de-duplication id. `GET /api/runs/{id}/decisions` returns them; the
  dashboard shows "decided by" with the answer.
- On every start, fork, cancel, resume and clean-up: a `caller.action` event on
  the run with `action`, `caller`, `from`, `request_id` and details.
- Waits and runs from before this have none of these fields; they read as before.

## Still open

- Reads are open to anyone who can reach the server, run boxes included.
  Scoping reads per run is a later step.
- A box's own process holds the database URL ([boxes.md](boxes.md), "Still
  exposed"), and an agent in the box can read it: a direct database write
  goes around this guard. That is Architecture's to close.
- `POST /api/github/token` is guarded, and a run's own process asks it for
  repo tokens: until that has its own key, `enforce` refuses it.

## Checking it

- `tests/test_api/test_api_guard.py`: the modes, keys, the MCP side door, the
  in-process names, a run's own key, the record.
- The machine check ([ci-gate.md](ci-gate.md)) runs its throwaway stack in
  `enforce` with a throwaway key: "write guard" parks a `gate_smoke` wait,
  shows a keyless answer refused, runs `ci_run_token` (its script tries to
  answer and cancel the wait with its run key and is refused, then starts a
  `smoke_test` run, which it may), and checks the wait is still open before
  its own key answers it, recorded under that key's name.
