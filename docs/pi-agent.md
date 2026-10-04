# The Pi agent step (`type: pi`) — switched off

A Pi agent step is an ordinary Temper node that holds a conversation with one Pi role
running in a sealed worker box. It is **off by default**: with the switch off, the `pi`
agent type and the `team` strategy do not exist (a workflow naming either fails as unknown),
none of their code is imported, no strategy has a run-start check, no `pi_` table is created
and no route, page or event changes.

Switch: the environment setting `TEMPER_PI_AGENT=1` (also `true`, `on`, `yes`), read when
`temper_ai.agent` is first imported. Box config: `TEMPER_PI_BOX_CONFIG=<json file>`.

## A step

```yaml
- name: talk
  depends_on: [brief]          # never the first node (see "Rules")
  agent:
    type: pi
    role: scout                # a role folder under the box config's identities_dir
    tools: [Read]              # Temper's tool names (see "Member settings")
    message: "Read note.txt and tell me its first word. Topic: {{ topic }}."
    workspace_files: {note.txt: "..."}   # written once into the worker's folder
    # provider: anthropic  model: claude-opus-5-5  thinking: max   (the defaults)
    # add_ons: [billion-context-pi, pi-image-trim, pi-tldr]       (the default: all allowed)
```

## Member settings (`temper_ai/pi_agent/member.py`)

- Model: `provider` (default `anthropic`), `model` (default `claude-opus-5-5`), `thinking`
  (default `max`; one of off, minimal, low, medium, high, xhigh, max). Pi must report exactly
  these before the prompt, or the step fails red; it never switches model or account.
- Tools: one `tools:` list with Temper's names, as for other agents, mapped to Pi's
  built-ins: Read→read, Edit→edit, Write→write, Bash→bash, Grep→grep, Glob→find+ls
  (default `[Read]`). A tool Pi has no equivalent for (WebFetch, NotionSearch, GitHub,
  Linear, ...) refuses the config by name; it is never dropped silently.
- Add-ons: `add_ons:` defaults to every allowed add-on: `pi-tldr`, `pi-image-trim`,
  `billion-context-pi` (its delegate tools are never launched: they start agents Temper can't
  see). pi-identity always comes through `role`; a route's login extension stays route
  config. Refused by name, with the reason: pi-worktree, pi-subagents, relays, pi-memory,
  pi-mcp-adapter, pi-web-access, pi-web-search, pi-control-chrome, pi-multi-pass, pi-queue,
  pi-company, and the team messaging add-on ("not available yet").
- Each add-on runs from a pinned copy named in the box config, never from the owner's live
  `~/.pi/agent`: `"add_ons": {"pi-tldr": {"dir": "...", "entry": "index.ts", "sha256":
  "<tree digest>"}}`. The copy is checked against its digest when the config loads and when
  each box starts, mounted read only at `/ext/addons/<name>`, and its digest goes into the
  turn's pin. Its commands count as allowed only from that folder. An add-on that fails in
  the box (needs the network, writes outside the run folder, runs unexpected commands) is left
  out and reported, not patched around.
- A usage or rate limit from the provider ends the turn in a recovery wait whose reason names
  the limit (`usage limit: ...`); the owner answers `accept` or `retry`. No quiet retry, no
  other model or account.

## A team stage (`strategy: team`)

A team is one stage, a fourth strategy beside parallel, sequential and leader. Its members
are the stage's `agents:`, each a `type: pi` agent config pointing at an existing pi role
(a run never creates a role), known in the team by its `name:`.

```yaml
- name: build
  type: stage
  strategy: team
  agents: [design, frontend, qa]          # type: pi agent configs
  input_map: {goal: input.goal}           # the team's goal
  strategy_config:
    mode: {type: leader, leader: design}  # who gets the brief and says done
    communication:                        # all (default), or edges: one-direction lists
      type: edges
      edges: {design: [frontend, qa], frontend: [qa]}
    pause_after_rounds: 3                 # required, no default
```

Each section has a `type` plus that type's options (`temper_ai/pi_agent/team.py`, section
models `LeaderMode`, `AllCommunication`, `EdgesCommunication`, `TeamSettings`). Unknown
sections, types and keys are refused by name; `workspace`, `lessons`, `ask_owner` and
`conversation` are refused as "not available yet" until their runtime piece exists.

**Pre-run check** (`temper_ai/pi_agent/team_check.py`, `check_team`): when a run starts,
before any node, with no model call and no container, the loader checks every team stage
(`GraphLoader.load_workflow(..., run_start=True)`, through the strategy's registered
run-start check) and reports every problem at once; any problem means the run does not
start (`POST /api/runs` answers 400; `temper run` exits). It checks each member (its agent
config loads; a valid `type: pi` config; its role exists under that exact id, with a close
name suggested but never picked; `identity.json` and `about.md` readable; `identity.json`
names a home chat; a worker route for its provider; pinned copies of its add-ons), the team
(leader is a member, edges name members, every member reachable from the leader,
`pause_after_rounds` set, a goal) and the workflow (each `safety: policies:` entry is refused
by name, since a team can't enforce one yet). The role list is the box config's
`identities_dir`, only read; unset means "role list not configured". A resume doesn't check
again.

**The team node** (`temper_ai/pi_agent/team_node.py`, `TeamNode`): the stage holds one
node, `<stage>.team`. Until the team runtime (T4 messaging, T5 inboxes, M1 leader mode) is
built it fails red with "team runtime not built yet (T4/T5/M1)"; it never passes.

## How it runs (ADR-A6-1)

- The node keeps its conversation in its own ledger (`temper_ai/pi_agent/ledger.py`,
  tables `pi_participants`, `pi_messages`, `pi_turns`, `pi_waits`; schema in the L2 proof
  folder `schema.md`). One role = one participant = one Pi session, kept for the whole
  run: a later turn, a Resume or a restart reopens the same session.
- A turn takes every message waiting for the role as one prompt and runs one worker box
  (`temper_ai/pi_agent/turn.py`). Each turn is its own agent on the run page
  (`agent.started` … `agent.completed|failed`, `executed_by: pi`) with its model calls,
  tool calls and live words below it (`temper_ai/llm/pi_stream.py`).
- After each turn the owner is asked what next through a wait with its own gate name,
  `<node path>~wait-<id>`, answered through the ordinary approve route. A reply is the
  role's next message in the same session; `done` finishes the step.
- A turn cut off after its prompt was sent (worker gone, timeout, a tool that never ended,
  the service stopped) is never re-run on its own: it becomes *uncertain* and the owner
  answers `accept` or `retry`. A turn that failed visibly (box not sealed, settings not
  effective, role/tools/notebook not as launched, provider error) fails the step red; a
  Resume then asks the owner `accept` or `retry`. After either decision, a session whose
  active branch ends unfinished is moved back to its last settled entry, in the same
  session file, before the next prompt.

## The worker box

- One container per turn, created from a pinned image and Pi runtime
  (`runtime_dir`, `pi_version` checked against the installed package): `--network none`,
  read-only root, all capabilities dropped, no new privileges, own user, no logs, only
  the participant's folder writable. `docker inspect` is checked before the start.
- Way out: an in-container relay on 127.0.0.1:3128 to a host Unix socket; the host lets
  through only `CONNECT <route host>:443`.
- Login: Pi's `apiKey` command asks the host over a second socket; within the turn's
  allowance the host runs `pi auth print-bearer-token --provider <p> --min-expiry 30m` on
  the host Pi and passes the token through. Nothing is stored; the redactor learns the
  token before Pi has it.
- Before the prompt: the session folder holds only the participant's session, the pinned
  settings still match, Pi reports the pinned model/thinking/session, only the allowed
  extensions loaded (identity, the box probe, the route's login extension, the member's
  pinned add-ons), the role is bound (`/identity`) and the probe reports exactly that
  role, the launched tools and the private notebook snapshot.
- The worker's process group and container are always removed when the turn ends.

## Rules

- Not the first node of a workflow: an owner wait needs a checkpoint of an earlier node
  to resume from. The step refuses to run as a first node, before any worker starts.
- One role per step; several roles work together only as a team stage, whose runtime is
  not built yet.
- The step never raises and never returns empty output.
