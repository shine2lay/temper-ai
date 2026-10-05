# What a run box holds

Every run executes in its own box, a container named `temper-run-<execution_id>`
that the worker starts from the server's container (`TEMPER_SPAWNER=docker`,
[reference/architecture.md](reference/architecture.md)). Whatever is in a box's
environment can be read from inside it with one `env`, by any agent in the run,
including one that a web page or a ticket talked into it. So a box gets only what
something in it reads, and an agent's tools get even less.

## Two layers

| Who | Gets | Where it's decided |
|---|---|---|
| The box (its own Python process that runs the workflow and records it) | Only the variables named on the box's allow-list, plus `TEMPER_RUN_CONTAINER` | `configs/boxes/env.yaml` + `configs/boxes/local/env.yaml`, read by `temper_ai/shared/box_env.py` at every spawn |
| An agent's tool processes: the Claude CLI and so its Bash, the Bash tool, script steps, `git`, OpenPullRequest's git, tmux for the interactive CLI | PATH, HOME, the locale, TZ, the proxies, `TEMPER_RUN_CONTAINER`, the list's `agent_tools: true` names, the one model credential that call uses, and the variables the agent's config passes explicitly (script steps' inputs) | `env_for_agent_tool()` in `temper_ai/shared/agent_env.py` |

An agent tool process never gets the database URL, the secret key, Redis, other
providers' keys or the rest of a token pool, whatever the list says. Pi steps run
in their own container with a fixed environment and get their model access over a
socket (`temper_ai/pi_agent/box.py`, [pi-agent.md](pi-agent.md)); MCP servers
started over stdio get the MCP SDK's minimal environment plus their config's `env:`.

## The allow-list

```yaml
box_env:
  - names: [WORKSPACE_DIR, TEMPER_API]
    why: scripts find the run's workspace and the server with them
    agent_tools: true          # the agent's tools may see them too
  - names: [TEMPER_DATABASE_URL]
    why: the runner records the run       # the box's own process only
```

- A name not on either file stays in the server. A new secret added to `.env`
  stays out of boxes until somebody lists it, with a reason.
- `configs/boxes/env.yaml` holds temper's own names and is tracked;
  `configs/boxes/local/env.yaml` holds this install's names (a design tool's URL,
  a browser bridge's token) and is git-ignored. The tracked file must exist; the
  local one is optional. A name listed twice is an error.
- `why:` is required: say who in the box reads the names.
- The GitHub app's keys (`integrations/github/secret.py` `SERVER_ONLY`) can never be
  listed; loading refuses them. A run asks the server for short-lived tokens instead.
- A secret (database URL, secret key, Redis URL, any `*_KEY`, `*_TOKEN`, `*_SECRET`,
  `*_PASSWORD`, `*_CREDENTIALS`) may be listed for the box's process, never with
  `agent_tools: true`.
- The list is read again for every run, so an edit reaches the next box with no
  restart. A list that does not load stops every run from starting (the spawn fails
  with "The box's allow-list is broken"); `temper check` names the problem first.
- At each spawn the worker logs the names it left out (`left out N variable(s) not
  on the box list: ...`), never a value.

## What a box no longer gets

The server keeps everything only it reads: the Slack and Telegram bots' tokens,
the Linear, Notion and GitHub webhook secrets, the API's token file, the Slack
test entry's token, and the worker's own settings. Temper's notices, questions
and answers in Slack and Telegram are sent by the server, so runs started there
work as before. The agent tools that act as a bot themselves (`SlackPost`,
`SlackReply`, `SlackReadThread`, `TelegramSend`; no shipped workflow uses them)
fail in a box with "..._TOKEN is not set" unless an install lists the token for
the box's process, which puts it within every agent's reach ("Still exposed").

## A run's own key

A box holds no key that lets it change things on the server: with the write
guard on ([api-access.md](api-access.md)), answering a wait, cancelling,
resuming or cleaning up from a box is refused. A workflow whose script steps
start other runs declares `starts_runs: true`; its run then makes a key of its
own that its script steps get as `TEMPER_RUN_TOKEN` (never agent tools), which
may only start and fork runs, and which dies with the run. The shared
`TEMPER_API_TOKEN` a box's process may carry counts for nothing there.

## Emergency rollback

`TEMPER_BOX_ENV=inherit` in the worker's environment brings back the old box: a copy
of the server's whole environment minus the GitHub app's keys, and the old deny-list
for agent tools. It is off by default, logs a warning on every spawn, and is for an
emergency only: with it on, any agent can read every secret the server has. Anything
else in the switch reads as the list.

## Still exposed

What temper cannot close by itself yet, handed to Architecture:

- The box's own process holds the database URL (full write access), the secret key
  (decrypts stored sign-ins) and the model providers' keys and token pool, because
  it records the run, opens stored MCP sign-ins and calls the models. It also holds
  the other credentials its own tools use: `NOTION_TOKEN`, the Linear MCP's client
  credentials (`LINEAR_CLIENT_SECRET`), `TEMPER_GITHUB_TOKEN`, `TEMPER_API_TOKEN`
  (asks the server for GitHub tokens and starts runs) and whatever secrets an
  install's local list gives the process (a browser bridge's token, a design
  tool's password).
- Agent tools run as the same user as that process, so they can read
  `/proc/1/environ` and the main process's `/proc/<pid>/environ` and find those
  values there. Scrubbing the tool environment stops a casual `env`, not a
  determined agent.
- Options under consideration: secrets passed in a file that deletes itself, with
  the main process made non-dumpable; a separate user for agent tools; a database
  role per box limited to its own run; a model-call proxy so boxes hold no
  provider keys.

## Checking it

- `temper check` loads both files.
- `ci_box_env` (no model, $0) lists the names in a box's tool environment and in
  every `/proc/*/environ` it can read, and fails on a server-only name anywhere in
  the box or a secret in a tool's environment. The machine check runs it on every
  commit ([ci-gate.md](ci-gate.md)); after a change to a list, run it live:
  `POST /api/runs {"workflow": "ci_box_env"}`.
- `tests/test_spawner/test_docker_spawner.py` (TestBoxEnvAllowList),
  `tests/test_shared/test_box_env.py` and `tests/test_shared/test_agent_env.py`.
- In a live box, list names only, never values:
  `env | cut -d= -f1 | sort` and
  `for f in /proc/[0-9]*/environ; do tr '\0' '\n' < "$f" 2>/dev/null | cut -d= -f1; done | sort -u`.
