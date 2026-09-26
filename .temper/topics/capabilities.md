# What temper-ai can do

<!-- temper:capabilities v1 -->
<!-- The list of capabilities is DERIVED from the code: do not edit it by hand, -->
<!-- it is rewritten on every refresh. The sentence after each entry is WRITTEN, -->
<!-- and is kept across refreshes. Refresh/verify with capabilities.py. -->

55 capabilities, 55 described. Probes matched: fastapi, argparse-cli.

## What this is

Temper is a self-hosted engine that runs multi-step AI agent workflows written as YAML: agents in `configs/agents/`, workflows in `configs/workflows/`. A worker runs each workflow, records every step, stops at approval gates, and can be resumed or forked from a checkpoint. It is reached through an HTTP API, a web dashboard at /app, an MCP server at /mcp, the `temper` CLI, Slack (`temper_ai/integrations/slack/`) and Linear. Its owner uses it to run his product loops (EPD for rollcall: `configs/epd/`) and coding workflows. The work it can do is the workflow configs themselves: each one's `@description` says what it does, and `GET /api/workflows/search?q=` finds them. Below is every HTTP route and CLI command, derived from the code.

## HTTP API (31)

### pools

- `GET /api/pools` — The token pools behind each LLM provider (e.g. the Claude accounts it rotates over): each pool's name, size, and each model family's state. · `temper_ai/api/pools.py:24`

### temper_ai/api/docs.py

- `GET /api/docs/examples/{tier}` — Return example YAML configs for a tier. · `temper_ai/api/docs.py:204`
- `GET /api/docs/registries` — Return all registered types with descriptions. · `temper_ai/api/docs.py:233`
- `GET /api/docs/schemas/{tier}` — Return field-level schema documentation for a config tier. · `temper_ai/api/docs.py:136`

### temper_ai/api/routes.py

- `GET /api/mcp-servers` — List configured MCP server names from config files. · `temper_ai/api/routes.py:952`
- `GET /api/runs/{execution_id}/checkpoints` — Get checkpoint history for an execution. · `temper_ai/api/routes.py:814`
- `GET /api/runs/{execution_id}/decisions` — Every gate this run has opened, and how each was answered. · `temper_ai/api/routes.py:780`
- `GET /api/runs/{execution_id}/gates` — List all gates currently waiting for approval in an execution. · `temper_ai/api/routes.py:723`
- `GET /api/runtime-config` — Runtime config for the frontend. · `temper_ai/api/routes.py:968`
- `GET /api/slack/status` — Whether this server runs Slack, and how its socket and notices are doing. · `temper_ai/api/routes.py:320`
- `GET /api/workflows` — List workflow executions with summary data. · `temper_ai/api/routes.py:298`
- `GET /api/workflows/search` — Workflow configs matching the words of ``q``, best first. · `temper_ai/api/routes.py:306`
- `GET /api/workflows/{execution_id}` — Get full workflow execution hierarchy. · `temper_ai/api/routes.py:328`
- `POST /api/runs` — Start a workflow execution. · `temper_ai/api/routes.py:115`
- `POST /api/runs/fork` — Fork a new execution from a specific checkpoint in another execution. · `temper_ai/api/routes.py:560`
- `POST /api/runs/{execution_id}/approve/{node_name}` — Approve a gate node, allowing the workflow to continue. · `temper_ai/api/routes.py:684`
- `POST /api/runs/{execution_id}/cancel` — Cancel a running workflow execution. · `temper_ai/api/routes.py:370`
- `POST /api/runs/{execution_id}/resume` — Resume a workflow from its last checkpoint. · `temper_ai/api/routes.py:445`

### temper_ai/api/studio.py

- `DELETE /api/studio/configs/{config_type}/{name}` — Delete a config. · `temper_ai/api/studio.py:150`
- `GET /api/studio/configs/{config_type}` — List all configs of a type. · `temper_ai/api/studio.py:46`
- `GET /api/studio/configs/{config_type}/{name}` — Get a single config by type and name. · `temper_ai/api/studio.py:56`
- `GET /api/studio/registry` — Return all registered types for dynamic dropdowns in the Studio UI. · `temper_ai/api/studio.py:192`
- `POST /api/studio/configs/{config_type}/{name}` — Create a new config. · `temper_ai/api/studio.py:118`
- `POST /api/studio/validate/{config_type}` — Validate a config without saving it. · `temper_ai/api/studio.py:162`
- `PUT /api/studio/configs/{config_type}/{name}` — Update an existing config. · `temper_ai/api/studio.py:134`

### temper_ai/server.py

- `GET /api/health` — Liveness only: answers `healthy`, the version and the time whenever the server is up; it checks nothing else. · `temper_ai/server.py:475`
- `GET /app` — The web dashboard (the React app built into frontend/dist): runs, their steps and gates, and the config studio. · `temper_ai/server.py:526`
- `GET /app/{full_path:path}` — Serve index.html for all frontend routes (SPA client-side routing). · `temper_ai/server.py:516`

### triggers

- `GET /api/triggers` — Every trigger (a config that starts runs on a schedule or a condition) and its current state, from the trigger scheduler. · `temper_ai/api/triggers.py:20`
- `GET /api/triggers/fires` — The scheduler's record of past trigger fires and what each decided; `trigger` narrows it to one trigger, `limit` 1–500 (default 50). · `temper_ai/api/triggers.py:25`
- `POST /api/triggers/tick` — Runs one scheduler pass now instead of waiting for the next one, and returns each trigger's decision. · `temper_ai/api/triggers.py:30`

## Commands (24)

### configs/epd/bin/epd_loop.py

- `approve` — append a candidate to backlog.md (same as adding the line yourself) · `configs/epd/bin/epd_loop.py:3068`
- `collect` — record what the last run (proposal or bet) produced, once temper is done · `configs/epd/bin/epd_loop.py:3063`
- `down` — tear down a bet's stacks (b004) or a proposal's (r001) · `configs/epd/bin/epd_loop.py:3079`
- `next` — the open bet's stages one at a time, here (takes the top backlog bet if none is open) · `configs/epd/bin/epd_loop.py:3065`
- `propose` — walk the product on the Alpaca paper account and write candidates now, whatever else is out; market hours only, unless --after-close; returns once submitted · `configs/epd/bin/epd_loop.py:3044`
- `reject` — turn a candidate down for good · `configs/epd/bin/epd_loop.py:3071`
- `resume` — fork the open bet's failed loop run at its last good stage and run the rest · `configs/epd/bin/epd_loop.py:3060`
- `run` — one turn: collect what finished, then the top backlog bet as one temper run, or a proposal when there is nothing planned; returns once submitted · `configs/epd/bin/epd_loop.py:3038`
- `scorecard` — the owner's decisions on bets and PRs, by the config versions that earned them · `configs/epd/bin/epd_loop.py:3081`
- `stage` — run one stage alone, on the bet's files · `configs/epd/bin/epd_loop.py:3075`
- `status` — Prints the EPD bets ledger (each bet's id, date, status, title and outcome) and the backlog queue in order. · `configs/epd/bin/epd_loop.py:3037`

### temper_ai/cli/linear.py

- `check` — the app token, who it acts as, the MCP tools, the webhook secret · `temper_ai/cli/linear.py:194`
- `comment` — comment on an issue as temper; the body is read from stdin · `temper_ai/cli/linear.py:197`
- `issue` — print an issue and its comments as JSON · `temper_ai/cli/linear.py:195`
- `linear` — Check the Linear setup; read or comment on an issue · `temper_ai/cli/linear.py:192`

### temper_ai/cli/main.py

- `connect` — Authorize an OAuth MCP server once; the grant is stored and reused · `temper_ai/cli/main.py:69`
- `connections` — Show configured HTTP MCP servers and whether they are authorized · `temper_ai/cli/main.py:90`
- `disconnect` — Forget a stored MCP authorization · `temper_ai/cli/main.py:98`
- `mcp` — Serve temper's MCP tools over stdio (proxies to a running server) · `temper_ai/cli/main.py:52`
- `run-workflow` — Worker entry point: execute a pre-queued WorkflowRun row by id · `temper_ai/cli/main.py:128`
- `serve` — Start the API server + dashboard · `temper_ai/cli/main.py:44`
- `validate` — Validate a workflow config · `temper_ai/cli/main.py:117`
- `watch-queue` — Daemon: poll Postgres for queued WorkflowRun rows, spawn each as a subprocess · `temper_ai/cli/main.py:143`

### temper_ai/cli/slack.py

- `slack` — Check temper's Slack app setup · `temper_ai/cli/slack.py:136`
