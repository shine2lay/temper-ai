# The Pi agent step (`type: pi`) — switched off

A Pi agent step is an ordinary Temper node that holds a conversation with one Pi role
running in a sealed worker box. It is **off by default**: with the switch off, the `pi`
agent type does not exist (a workflow naming it fails with "Unknown agent type"), none of
its code is imported, no `pi_` table is created and no route, page or event changes.

Switch: the environment setting `TEMPER_PI_AGENT=1` (also `true`, `on`, `yes`), read when
`temper_ai.agent` is first imported. Box config: `TEMPER_PI_BOX_CONFIG=<json file>`.

## A step

```yaml
- name: talk
  depends_on: [brief]          # never the first node (see "Rules")
  agent:
    type: pi
    role: scout                # a role folder under the box config's identities_dir
    provider: openai-codex
    model: gpt-6.1-sol
    thinking: medium
    tools: [read]
    message: "Read note.txt and tell me its first word. Topic: {{ topic }}."
    workspace_files: {note.txt: "..."}   # written once into the worker's folder
```

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
  extensions loaded, the role is bound (`/identity`) and the probe reports exactly that
  role, the launched tools and the private notebook snapshot.
- The worker's process group and container are always removed when the turn ends.

## Rules

- Not the first node of a workflow: an owner wait needs a checkpoint of an earlier node
  to resume from. The step refuses to run as a first node, before any worker starts.
- One role per step (several roles talking is a later stage).
- The step never raises and never returns empty output.
