# The Pi agent step (`type: pi`) — switched off

A Pi agent step is an ordinary Temper node that holds a conversation with one Pi role
running in a sealed worker box. It is **off by default**: with the switch off, the `pi`
agent type and the `team` strategy do not exist (a workflow naming either fails as unknown),
none of their code is imported, no strategy has a run-start check, no `pi_` table is created
and no route, page or event changes.

Switch: the environment setting `TEMPER_PI_AGENT=1` (also `true`, `on`, `yes`), read when
`temper_ai.agent` is first imported. Box config: `TEMPER_PI_BOX_CONFIG=<json file>`. Both
are the server's and the Pi lane's own settings: a run box never gets either, and
`configs/boxes/env.yaml` can't list them (M4 SW-42, [boxes.md](boxes.md)).

**Pi runs run only in the Pi lane** ([pi-lane.md](pi-lane.md), M4 ADR-M4-01): a workflow
with a Pi step at any depth is marked for the lane when it starts, and only the
`pi-worker` service runs it, itself off by default (compose profile `pi`). The lane runs only
Pi steps, team stages of Pi members and gates: anything else is refused at submit, naming
the step. A Pi step anywhere else refuses "Pi steps run only in the Pi lane". With the lane
down, a Pi run waits in the queue, "waiting for the Pi lane". Switching Pi on takes all
of: `TEMPER_PI_AGENT=1` on the server and on `pi-worker`, the box config on `pi-worker`, the
profile started, and the host helper ([pi-host-helper.md](pi-host-helper.md)); each run's
preflight names whatever is missing.

**The sealed boundary doesn't cover the Pi lane, by design** (BS1,
`TEMPER_BOX_RUNTIME_BOUNDARY=sealed`, [boxes.md](boxes.md)): `pi-worker` starts its run
processes as plain processes, not in run boxes. There the Pi-only rule (SW-41), `pi-worker`'s
explicit settings and mounts, and the refusal of child processes beside a Docker socket
anywhere else (SW-75) do that job.

**Switching off never fails a waiting run** (M4 ADR-M4-05, SW-32). Only Pi workflows park
([gates.md](gates.md) "Pi workflows"), so a parked run is a Pi run, and with the switch off its Pi steps
don't exist. It waits instead of failing with "Unknown strategy 'team'": the run page's
header shows a grey "Pi switched off" badge; an answer is kept, and the approve reply says
"Pi switched off: this run waits, with any answer kept, and carries on once the Pi switch
(TEMPER_PI_AGENT) is back on"; Resume answers 409 with the same sentence; nothing else
carries it on (`runner/parked.py`, `carry_on`). Once the switch is back on, the next
carry-on (start-up, an answer, Resume) carries it on as usual. A cancel while switched off
ends the run at once; its team's rows end at the first sweep once the switch is back on
(T4T5 G-a, SW-09).

## A step

A step names an agent file, as every agent step does; the Pi settings live in that file
(`configs/agents/ci_pi_talk.yaml` is a real one). The loader does not take an agent written
inline in the workflow.

```yaml
# configs/workflows/<workflow>.yaml
- name: talk
  type: agent
  agent: scout_talk            # configs/agents/scout_talk.yaml
  depends_on: [brief]          # optional: a Pi step may be the first node
```

```yaml
# configs/agents/scout_talk.yaml
agent:
  name: scout_talk
  type: pi
  role: scout                  # a role folder under the box config's identities_dir
  tools: [Read]                # Temper's tool names (see "Member settings")
  message: "Read note.txt and tell me its first word. Topic: {{ topic }}."
  workspace_files: {note.txt: "..."}   # written once into the worker's folder
  # provider: anthropic  model: claude-opus-5-5  thinking: max   (the defaults)
  # add_ons: [pi-image-trim, pi-tldr]                           (the default: all allowed)
```

## Member settings (`temper_ai/pi_agent/member.py`)

- Model: `provider` (default `anthropic`), `model` (default `claude-opus-5-5`), `thinking`
  (default `max`; one of off, minimal, low, medium, high, xhigh, max). Pi must report exactly
  these before the prompt, or the step fails red; it never switches model or account.
- Tools: one `tools:` list with Temper's names, as for other agents, mapped to Pi's
  built-ins: Read→read, Edit→edit, Write→write, Bash→bash, Grep→grep, Glob→find+ls
  (default `[Read]`). A tool Pi has no equivalent for (WebFetch, NotionSearch, GitHub,
  Linear, ...) refuses the config by name; it is never dropped silently. Grep and Glob need
  the box's pinned `rg` and `fd` (see [The worker box](#the-worker-box)).
- Add-ons: `add_ons:` defaults to every allowed add-on: `pi-tldr` and `pi-image-trim`, the
  ones that passed the worker box test. pi-identity always comes through `role`; a route's
  login extension stays route config. Refused by name, with the reason: pi-worktree,
  pi-subagents, relays, pi-memory, pi-mcp-adapter, pi-web-access, pi-web-search,
  pi-control-chrome, pi-multi-pass, pi-queue, pi-company, the team messaging add-on ("not
  available yet"), and `billion-context-pi`, left out after the box test: it writes its own
  file beside the Pi session (`<session>.jsonl.acp.json`), which the turn's private-session
  check refuses.
- Each add-on runs from a pinned copy named in the box config, never from the owner's live
  `~/.pi/agent`: `"add_ons": {"pi-tldr": {"dir": "...", "entry": "index.ts", "sha256":
  "<tree digest>"}}`. The copy is checked against its digest when the config loads and when
  each box starts, mounted read only at `/ext/addons/<name>`, and its digest goes into the
  turn's pin. The production box config pins exactly the two allowed ones: a pin for any
  other add-on, or an allowed one without a pin, is a mismatch in the pin check (SW-29;
  [pi-lane.md](pi-lane.md#the-pins)). Its commands count as allowed only from that folder.
  An add-on that fails in
  the box (needs the network, writes outside the run folder, runs unexpected commands) is left
  out and reported, not patched around.
- A usage or rate limit from the provider ends the turn in a recovery wait whose reason names
  the limit (`usage limit: ...`); the owner answers `accept` or `retry`. No quiet retry, no
  other model or account.

## A team stage (`strategy: team`)

A team is one stage, a fourth strategy beside parallel, sequential and leader. Its members
are the stage's `agents:`, each the name of an agent file (`configs/agents/<name>.yaml`)
holding a `type: pi` agent config that points at an existing pi role (a run never creates a
role); the member is known in the team by that config's `name:`.

```yaml
# configs/workflows/<workflow>.yaml
- name: build
  type: stage
  strategy: team
  agents: [design, frontend, qa]          # configs/agents/design.yaml, frontend.yaml, qa.yaml
  input_map: {goal: input.goal}           # the team's goal
  strategy_config:
    mode: {type: leader, leader: design}  # who gets the brief and says done
    communication: {type: all}            # the default; edges isn't built yet (below)
    pause_after_rounds: 3                 # required, no default
```

```yaml
# configs/agents/design.yaml (frontend.yaml and qa.yaml alike, each with its own role)
agent:
  name: design
  type: pi
  role: architecture           # an existing role folder under the box config's identities_dir
  tools: [Read, Grep, Glob]
  # provider, model, thinking and add_ons as for a step (see "Member settings")
```

`communication` is `all` (any member may message any member) or `edges`, one-direction lists
of whom each member may start a conversation with, e.g. `{type: edges, edges: {design:
[frontend, qa], frontend: [qa]}}`. The first team runtime is `all` only (R2 rule B7): edges
are parsed and checked like the rest, and the pre-run check refuses them with
"communication: edges isn't built yet; use all" until a later slice builds them.

Each section has a `type` plus that type's options (`temper_ai/pi_agent/team.py`, section
models `LeaderMode`, `AllCommunication`, `EdgesCommunication`, `TeamSettings`). Unknown
sections, types and keys are refused by name; `workspace`, `lessons`, `ask_owner` and
`conversation` are refused as "not available yet" until their runtime piece exists.

The later slice's features each need their own proof before use, so asking for one is
refused with a plain sentence, by the name a config would use for it (M4 SW-04; R2's
`not_approved` list). In the stage's `strategy_config`:

| Asked for | Refused with |
|---|---|
| `mode: {type: unanimous}` | `mode: unanimous mode isn't built yet; use leader` |
| `conversation: {type: fresh_each_round}` (or just `fresh_each_round`) | `conversation: fresh_each_round isn't built yet: members keep their conversation for the whole team stage` |
| `conversation: {continue_from: <stage>}` (two team stages continuing) | `conversation: continuing members' conversations from an earlier team stage (continue_from) isn't built yet: each team stage starts its members' conversations fresh` |
| `private_children` (or `children`) | `private_children: private children aren't built yet: a team is the members it lists, and none of them can start a private helper` |
| `concurrent_turns` (or `concurrency`) | `concurrent_turns: concurrent member turns aren't built yet: members take turns one at a time` |
| `communication: {type: edges, ...}` | `communication: edges isn't built yet; use all` (below) |

A member's own agent config asking for one of these (`conversation`, `continue_from`,
`private_children`, `children`, `concurrent_turns`) is refused the same way, prefixed
`member '<name>':`. A change to the team's members while its run is going (one added,
removed or renamed, or a member given another role) is refused when the team reopens ("team
settings changed since the team started (members)", R2 C3). Any other change to the team's
settings or a member's is asked about instead, at one settings wait for the whole team
([Settings changed while a conversation waits](#settings-changed-while-a-conversation-waits)).

**Pre-run check** (`temper_ai/pi_agent/team_check.py`, `check_team`): when a run starts,
before any node, with no model call and no container, the loader checks every team stage
(`GraphLoader.load_workflow(..., run_start=True)`, through the strategy's registered
run-start check) and reports every problem at once; any problem means the run does not
start (`POST /api/runs` answers 400; `temper run` exits). It checks each member (its agent
config loads; a valid `type: pi` config; its role exists under that exact id, with a close
name suggested but never picked; `identity.json` and `about.md` readable; `identity.json`
names a home chat; a worker route for its provider; pinned copies of its add-ons), the team
(leader is a member, edges name members, every member reachable from the leader, edges not
used yet, `pause_after_rounds` set, a goal, no two members with the same role, every
member's name matching `^[a-z][a-z0-9_-]{0,39}$`, no member named like one of Temper's own
ids -- `owner`, `system`, `all`, ... from `pi_agent/route/model.py` `RESERVED_IDS`, and no
member given Bash while `TEMPER_API_GUARD` isn't `enforce`: "member '<m>': Bash is off
until owner-only writes are enforced (#45)") and the workflow (each `safety: policies:` entry
is refused by name, since a team can't enforce one yet). The role list is the box config's
`identities_dir`, only read; unset means "role list not configured". A resume or a fork
never runs this check (they run the workflow config as it is now), so the team node runs it
again when it starts, with the goal it was handed, and fails red before any member is set
up. The run-start problems, the graph's own and the Pi loop rule come in one error. The
same findings, each with its form field and member, are what the Team page's check gives
([pi-team-api.md](pi-team-api.md)).

A team's members are `type: pi` agents, so a workflow with a team stage is a Pi workflow
(`stage/pi_workflows.py`, docs/gates.md "Pi workflows") even when it has no other Pi step:
its gates park and its loops must say `on_max_loops: fail`.

**The team node** (`temper_ai/pi_agent/team_node.py`, `TeamNode`): the stage holds one
node, `<stage>.team`, which runs the leader loop on the team's messages and inboxes:
review rounds, the pause after `pause_after_rounds` keep-goings, done recorded by Temper
([pi-team-runtime.md](pi-team-runtime.md); messaging and inboxes:
[pi-team-messages.md](pi-team-messages.md)). A failed team fails its stage too; a stop at
the pause or when stalled ends it, its stage and its run cancelled. The Team page starts
and follows trials through its own API, [pi-team-api.md](pi-team-api.md).

## How it runs (ADR-A6-1)

- The node keeps its conversation in its own ledger (`temper_ai/pi_agent/ledger.py`,
  tables `pi_participants`, `pi_messages`, `pi_turns`, `pi_waits`, `pi_reviews`; schema in
  the L2 proof folder `schema.md`, extended for teams in the T4T5 folder `tables.md`). One
  role = one participant = one Pi session, kept for the whole run: a later turn, a Resume
  or a restart reopens the same session.
- The `pi_` tables carry their layout version in `pi_schema_version`, one row (M4
  ADR-M4-07, SW-12, SW-13). Version 1 is the tables with every column built from a path or
  a name as `Text` (`host_path`, `gate_name`, `dedupe_key`, `claim_key`, `claimed_by`,
  `box_name`, `session_dir`; and the Team page's `request_id`), so a long node path never
  fails a write; version 2 adds
  `pi_participants.snapshot_sha256` (the role snapshot below). Every open (`Ledger.ensure`)
  takes a lock -- a Postgres advisory lock, a plain one on SQLite -- makes what is missing
  and runs the forward-only steps from the stored version up, in one transaction; a step
  only adds, never drops or rewrites a row. Pi refuses a database, changing nothing, whose
  stored version is newer than this Temper knows ("this database's Pi tables are at layout
  version 3, but this Temper knows only up to version 2: a newer Temper made them; ...") or
  that has `pi_` tables with no version ("... from a Pi build before their layout was
  versioned, so their layout is unknown; Temper changed nothing. Use a fresh database for
  Pi"). A Pi step then fails "Pi refused this database: <why>", a team fails red with the
  same words before any member is set up, and the Team page's API answers 503.
- A turn takes every message waiting for the role as one prompt and runs one worker box
  (`temper_ai/pi_agent/turn.py`). Each turn is its own agent on the run page
  (`agent.started` … `agent.completed|failed`, `executed_by: pi`) with its model calls,
  tool calls and live words below it (`temper_ai/llm/pi_stream.py`).
- After each turn the owner is asked what next, answered through the ordinary approve
  route. A reply is the role's next message in the same session; `done` finishes the
  step. Every owner wait ("what next", and the recovery waits below) is written first as a
  `pi_waits` row, then asked through `ask_owner` under that row's own id
  (`temper_ai/pi_agent/owner_waits.py`): its name is `<node path>~ask-<wait id>`, one id
  per turn and per recovery. Like any wait in a Pi workflow it lets the worker go (the run
  parks, [gates.md](gates.md) "Pi workflows"); the answer carries the run on, the step
  runs again, finds the answer at the same wait id and goes on from its ledger -- a
  settled turn is never run again. Where the run cannot save where it is, the wait holds
  the worker instead, and a cancel there ends the conversation before the step stops.
- A turn cut off after its prompt was sent (worker gone, timeout, a tool that never ended,
  the service stopped) is never re-run on its own: it becomes *uncertain* and the owner
  answers `accept` or `retry`. A turn that failed visibly (box not sealed, settings not
  effective, role/tools/notebook not as launched, provider error) fails the step red; a
  Resume then asks the owner `retry` or `stop` (there is nothing to accept from a failed
  turn). While that question is open the run shows `waiting`, not the failed attempt's red,
  and only one Resume (or the start-up pick-up) carries a cut-off run on ([gates.md](gates.md)
  "Pi workflows"). The owner may always answer `stop`, which ends the step red: "<role> turn <n>
  failed and the step was stopped" (or "did not finish"), never naming who stopped it. A
  picked option on the run page counts the same as typing it, and text typed beside a pick
  is its words; with no pick, the typed text's first word is the choice and the rest its
  words. The question and its reply syntax are kept apart (`question`, `reply_hint`) and
  shown together, as before. Any other answer (empty, another word, `accept` at a failed turn)
  decides nothing, and the owner is asked again at a new wait for the same turn. A retry
  gives the turn the same messages again, with the same ids, marked as given again; they
  are never posted as new. After a decision, a session whose active
  branch ends unfinished is moved back to its last settled entry, in the same session
  file, before the next prompt.
- Taking over a turn whose run was cut off first makes sure its old worker box is gone:
  the box's name is recorded on the turn before the box is created, and the box is killed
  and removed if it is still there. If that can't be confirmed the step fails red.

### A replaced attempt stands down

One run normally has one live attempt: a run that is queued or running is not started again,
its box has one name, and a resume is claimed. A rollback run mode, or a box whose stop
failed, can still leave an older attempt alive, holding its worker at a wait. When a later
attempt of the run takes that wait over (the wait is closed as `replaced`,
[gates.md](gates.md) "Restarts"), or has started by the time the older one would take its
step's turns over, the older attempt *stands down* (`ReplacedByLaterAttempt`, SW-84):

- its step is not tried again, and it takes no turn over: a turn held by an attempt that
  started after it is that attempt's live work, left exactly as it is (same epoch, its box
  running, no recovery wait; `Ledger.take_over(newer_attempts=...)`);
- a Pi step or a team leaves the conversation to the newer attempt: nothing is ended, no
  outcome is written, no message is dropped;
- it writes down only its own events, as `cancelled` marked `replaced_by_later_attempt`. The
  run's row and status, the newer attempt's events and waits, and the run's notices (the
  webhook, the end of the live stream) stay the newer attempt's. The run's cancel signal
  is never set for it;
- its own workflow event (and a stage's) says what the attempt spent, `cost_usd` and
  `total_tokens`, summed as a parked or ended one's are: the finished steps and the ones a
  loop threw away;
- writing those events is best-effort: when the database fails the write, a warning is
  logged and the attempt stands down all the same. It never turns into a failure that
  would end the newer attempt's run.

A stop at a held wait is unchanged: the conversation ends first, then the step.

### Settings changed while a conversation waits

A conversation is pinned to the settings it started with (`pin_for` in
`temper_ai/pi_agent/host.py`): Pi's version, the image, provider, model and thinking, the
tools, the extension and add-on code, the worker route, the workflow, the agent config's
digest, the working folder and, for a team member, the team's settings. Every owner answer
reopens the conversation in a new attempt, which checks the pin against what the configs
and the box say now. Every land deploys, and conversations move at the owner's pace, so a
change while one waits is bound to happen. Temper used to refuse to reopen it, which failed
the step red with no way on. Now it asks (SW-85, M3 E24; `temper_ai/pi_agent/settings_wait.py`):

- **Asked first.** The reopen opens a wait of its own kind, `settings`, before anything else:
  before any other open wait is settled and before any turn. The answer that reopened the
  conversation is *held*: it is not applied until the settings are decided. Nothing has
  failed and no session file is touched.
- **What the owner sees.** The question names what changed, old -> new for the short
  values (Pi's version, the image, provider, model, thinking) and the first 12 characters
  of a digest for the rest, then the whole pin's fingerprint, old -> new. The answers are
  `go on` and `stop` (a pick on the run page or typed). The same changes are typed fields
  on the wait (below), so a page builds its own table and never reads the question.
- **`go on`** re-pins the conversation to the new settings, in the same transaction as the
  decision, and only if the stored pin is still the one the wait named (compare-and-set on
  its digest). Then the step carries on as it would have: the held answer is applied once,
  and the next turn runs with the new settings. If the settings changed again while the
  wait was open, the `go on` re-pins nothing (`applied: false`) and a new settings wait
  names the newer settings.
- **`stop`** ends the conversation where it is, so a later Resume doesn't reopen it, and
  ends the step and the run **cancelled**, not failed: nothing failed, it is the owner's
  choice (M3 E18), like the stop at a team's pause. The step's reason is neutral, "the Pi
  step was stopped: its settings changed since its conversation started (<keys>)", and never
  names who answered. The stop is returned, never raised, so it is never retried, and the
  run's cancel signal is never set for it. No turn runs and the held answer is never
  applied. Nothing new starts anywhere in the run after it (SW-86, below); the run ends
  cancelled with the step's reason.
- **Anything else** (another word, an empty answer) decides nothing: the owner is asked
  again at a new settings wait. There is no default, either way.
- **A team** asks the same at one settings wait for the whole team, listing each changed
  member's settings and a changed team digest; `go on` re-pins every member it named, in
  one transaction, and `stop` ends the team `stopped` ("stopped when the team's settings
  changed since its conversations started (<member>: <keys>; ...)") and the run cancelled
  ([pi-team-runtime.md](pi-team-runtime.md)). A changed set of members is still refused, as
  above: a conversation can't be carried into a different team.

Why ask, rather than the alternatives Architecture listed (C7 C1): holding every land while
a conversation waits would stall all work behind the slowest owner answer and would change
temper-ci and temper-deploy; only showing the change would leave the conversation stuck.
The settings wait shows the change at the next answer; nothing warns before it.

What a settings wait holds, in its `pi_waits` row (no schema change: the kind is a string,
the subject and decision are JSON):

| Field | Holds |
|---|---|
| `subject.settings_changes` | one entry per changed setting: `scope` (`team` or `member`), `member` (the member's name; `null` for the team; a single step's is its role), `key`, `value_kind` (`text` or `sha256`), `old`, `new` |
| `subject.pins` | one entry per changed member: `member`, `participant_id`, `pin_old`, `pin_new` (the full sha256 of the pin's canonical JSON, keys sorted, no spaces) |
| `subject.pin_old`, `subject.pin_new` | a single step's two pin digests (the same as its `pins` entry) |
| `subject.question`, `reply_hint`, `options`, `header` | the question, "Reply 'go on' or 'stop'.", `["go on", "stop"]`, `settings` |
| `decision` | `answer` (`go on`, `stop` or `invalid`), `changed` ([{scope, member, key}]), the digests (`pin_old`/`pin_new`, or `pins`), `applied` (`go on` only; with `why` when false), who answered (`by`, `source`, `request_id`) and the typed text's sha256; a team's stop also keeps the owner's `words` |

The keys (`key`) and their kinds: `pi_version`, `image`, `provider`, `model`, `thinking`
are `text`. Every other key is a full 64-hex sha256: `extensions.<name>` (`identity`,
`temper-box`, `auth`) and `add_ons.<name>` are the folders' own digests,
`agent_config_sha256` and `team` are the pin's own digests, and `tools`, `route_host`,
`workflow` and `cwd` are the sha256 of the value's canonical JSON. No file's contents and
no environment value is ever in a wait.

## A stopped step starts nothing more (SW-86)

A Pi step that ends cancelled **by itself** (`cancelled_ends_stage`, with the run's cancel
signal unset) closes the run's one start door, `RunStop` through `_held_or_skipped`. This
covers a team's stop at the pause or when stalled, a settings stop, and a conversation
ended elsewhere while its step waited (`_settled_meanwhile`). No dependent or independent
branch starts another step. `run_after_failure` is no exception, and an approval after the
stop opens no wait. Its sole record is a neutral skip:

> not started: the run was stopped at 'talk'

The quoted name is the full node path (a team's own node is `talk.team`). The run still
ends **cancelled**, with the stopped step's original reason; E18's run-list sentence is
unchanged. A sibling already running is **not** interrupted: the run's cancel signal is
not set, so the sibling finishes under the existing tool/turn/wait rules and keeps its
result. An earlier or later sibling failure remains visible on that step but cannot turn
this stopped run failed. The first qualifying self-stop keeps its path and reason if
several steps stop themselves. Producer admission and the stop share one lock, after
blocking input, approval and event-recording work (also in a timeout worker). If the
stop wins, the provisional node event becomes the sole neutral skip; the producer never
runs. Already-admitted siblings keep the existing rules, without holding that lock during
their work. An approved preflight answer whose producer lost admission stays visible but
unconsumed. A gate already parked cannot keep the run waiting, consume
an answer, or turn the run failed. Its open wait is closed as rejected, without setting the
run's cancel signal; a concurrent answer remains visible but unused.

**Setup-release clean-ups are kept back too**, in both `on_failure: hold` and `cleanup`:
they have the same neutral skip. Setup stays standing. This is a stop, not a retryable
failure: no failure hold or automatic deadline-release pass is scheduled. Releasing setup
needs an explicitly requested separate run. This strict choice avoids starting a model
agent merely because it is marked `undoes`, and avoids a cleanup-only pass changing a
cancelled run to failed. The Pi lane has no setup-release clean-ups today.

The self-stop's path and reason are kept in its node checkpoint (`metadata.self_cancelled`)
and propagated through enclosing stages. The saved stop is read **before** enqueue clears
terminal fields, any running transition, setup take-over, runtime/tool registration or
MCP setup. Public Resume, answered parked waits, startup pickup, shared
`queue_run(start="resume")`, `execute_workflow` and `run-workflow` use the same DB-only
admission helper (`runner/resume_authority.py`). A known stop is state-only: no new
workflow attempt, producer, owner/settings wait or cleanup. Revised/missing configuration
is not loaded to keep the cancellation. Saved reasons/results/costs stay intact even if
checkpoint reconciliation or the separate observation diagnostic fails. Bare graph resume
also restores `RunStop` before scheduling; any ended-source inspection bypasses revised
conditions, inputs and approvals. Restart pickup leaves a cancelled run alone.

**Unreadable authority refuses the attempt, not the run.** This also applies to ordinary
workflows with no self-cancelled step: an unreadable resume is refused, keeping its previous
outcome, reason, results and costs rather than marking the run failed. A successful empty
read still follows normal resume behavior; a read fault never becomes empty history, fake
cancellation, replacement or failure. The API returns HTTP 503 with a bounded diagnostic. The worker/CLI
returns `RESUME_ATTEMPT_REFUSED_EXIT` (7), distinct from box, lane and replacement exits.
Only `caller.action` records the refusal; no terminal row writer, failed workflow event,
viewer/end sentinel, `_see_to_parked`, new wait, automatic retry or setup release follows it.
Only this attempt's own resources may be closed.

Valid enqueue atomically reserves a server-owned token and the prior canonical projection
in existing JSON metadata **before clearing it**. Caller `extra` cannot supply reserved
keys or a baseline. Claim/spawn is not admission: the worker re-reads checkpoint authority
and ownership, commits admission, then marks running and opens runtime. It reuses that
trusted snapshot, without freezing mutable waits, answers, cancellation, limits or claims.
Held setup is taken over only after this check. Normal resume/loop/dispatch behavior remains.

A refused worker restores the saved projection only under the same token, original attempt,
claim, checkpoint-version and independent-cancel fences. Append-only box/commit history is
kept. An unknown/newer owner or cancellation permits no rollback or release. Reaper/startup
recover a never-admitted reservation, not a failed/orphaned run; an admitted-but-not-started
reservation additionally needs its own box proved gone. A DB outage leaves durable recovery
bookkeeping and no work; the watcher stays up. Missing/corrupt baseline authorizes neither
work nor a manufactured outcome. Recovery never retries the refused workflow.
The run's own cancel signal still uses its existing path; workflows without a self-stop
keep their failure policies and outcomes unchanged.

## The worker box

- One container per turn, created from a pinned image and Pi runtime
  (`runtime_dir`, `pi_version` checked against the installed package): `--network none`,
  read-only root, all capabilities dropped, no new privileges, own user, no logs, only
  the participant's folder writable. `docker inspect` is checked before the start.
- Before any docker call, each start reads back the identity extension, the shared identity
  settings and the route's login extension and catalog, and refuses the start
  (`pin_changed`) when one no longer has the digest the box config pins (M2-roles D3,
  SW-26). The turn records what it read (`pins_read_back` in its checks). The whole pin
  list and its check: [pi-lane.md](pi-lane.md#the-pins).
- Way out: an in-container relay on 127.0.0.1:3128 to a host Unix socket; the host lets
  through only `CONNECT <route host>:443`.
- Login: Pi's `apiKey` command asks the host over a second socket; within the turn's
  allowance the host gets a token and passes it through. Nothing is stored; the redactor
  learns the token before Pi has it.
  - With `host_helper_socket` set (the Pi worker), the token comes from the host helper
    (`docs/pi-host-helper.md`): `token <slot>` for the run's pinned account slot
    (`BoxSpec.slot`) and nothing else. Its refusal names the slot, is recorded on the turn's
    receipt (`handoff_slot`, `handoff_refused`) and leads the turn's errors. The box
    config then needs no `host_node` or `host_pi`.
  - Without it (host-process instances, tests) the host runs
    `pi auth print-bearer-token --provider <p> --min-expiry 30m` on the host Pi, as
    before; a live box config then needs both `host_node` and `host_pi`.
  - A done trial's branch goes through the helper's `branch` verb when the socket is set
    (E10, `temper_ai/pi_agent/team_branch.py`).
- Before the prompt: the session folder holds only the participant's session, the pinned
  settings still match, Pi reports the pinned model/thinking/session, only the allowed
  extensions loaded (identity, the box probe, the route's login extension, the member's
  pinned add-ons), the role is bound (`/identity`) and the probe reports exactly that
  role, the launched tools and the private notebook snapshot.
- The role snapshot (M4 ADR-M4-08, SW-25; `temper_ai/pi_agent/member_tree.py`): before a
  participant's first turn its role folder (`<identities_dir>/<role>`) is copied to a
  temporary folder next to the target (`.<role>.partial-<id>`). The source's digest before
  the copy, after it, and the copy's must be one; if not, it copies once more, then refuses
  ("the role folder '<role>' kept changing while Temper copied it (twice); nothing was put
  in place. ..."). The copy is renamed into place in one step and its digest recorded on
  the participant row (`snapshot_sha256`) last. Links are never followed: one pointing
  inside the role folder is kept as a link; one pointing outside it refuses the snapshot,
  naming it ("the role folder '<role>' has a link 'notes/x.md' pointing outside it
  ('/etc/passwd'); Temper never follows links out of a role folder, ..."); anything that
  is not a file, folder or link refuses it too. A crash mid-copy leaves nothing reusable:
  until the digest is on the row, each attach removes any temporary folder and any copy in
  place and copies afresh. Once recorded the snapshot is the member's for the whole run:
  the role's real folder may change meanwhile (M1's live run: Design's did, L4-F4) without
  reaching it. A refusal fails a Pi step "the Pi step's role snapshot was refused: ...",
  and a team "member <m>'s role snapshot was refused: ...", before any turn.
- Reads of what a member writes never follow a link (M4 ADR-M4-08, SW-51). The
  participant's folder is mounted read-write in its box, so Temper reads there through
  `member_tree` (`read_member_text`, `member_entry`, `list_member_dir`,
  `write_member_file`), opening each path part without following links and reading only
  regular files: the box-state and rewind answers, the notebook's digest, the session
  folder and file, the working folder handed to git for a team's project copies, and the
  folders a box start makes. A link there -- to `/etc`, to another member's folder,
  anywhere -- is refused, never read (`member_link_refused`, `session_folder_not_private`,
  or the copy's "working folder ... is a link").
- A member's identity guidance is Temper's own (`assets/temper-box/role-section.md`,
  written as the box's `pi-identity-role.md`; M4 SW-27, M2-roles D1): it says the box has no
  notebook, memory_write, daily log, queue or ask-the-owner tools and asks for lessons,
  findings and questions for the owner in the reply. A chat's own guidance, which tells the
  role to keep notes with those tools, never reaches a box. The text sits in the pinned
  temper-box folder, so a change to it is a settings change a reopened conversation asks
  the owner about ([above](#settings-changed-while-a-conversation-waits)).
- The worker's process group and container are always removed when the turn ends.
- In the Pi lane (M4 ADR-M4-03, SW-43, SW-44; [pi-lane.md](pi-lane.md)): the box runs as
  the worker's own uid and gid (1000:1000), never the template's or the docker group; with
  `roots` in the box config, every bind source must be inside them
  (`bind_source_outside_roots`) and every turn socket path under 100 bytes
  (`socket_path_too_long`); the step's own assets are mounted from a sealed copy in the
  state root; and the pi folder check looks under `host_home` as well as the worker's home.

### Pi's grep and find: pinned `rg` and `fd`

Pi's `grep` runs ripgrep (`rg`) and its `find` runs `fd`. The box image has neither, and Pi
can't download them in the box (`--network none`, `PI_OFFLINE=1`), so the runtime folder
carries them (queue #47):

- Pins (`temper_ai/pi_agent/search_tools.py`): ripgrep 15.2.0 and fd 10.5.0, the official
  static musl builds for aarch64 only, each with its release URL, the archive's sha256, the
  binary's path in the archive and the binary's own sha256.
- `scripts/pi_search_tools.py --from <runtime> --to <new runtime>` (on the host, stdlib
  only) downloads both archives, checks the archive digest, takes out only the named binary
  and checks its digest. It copies `<runtime>` unchanged (links kept) and adds `rg` and `fd`
  (mode 0555) at its top level, so they are `/pi-runtime/rg` and `/pi-runtime/fd`, first on
  the box `PATH`. It writes `search-tools.json` (versions, URLs, digests, the source's tree
  digest), makes the tree read only and moves it into place. Pi finds them by itself: it
  tries `/w/agent/bin`, then `rg --version` / `fd --version` on `PATH`; its code is
  unchanged. The script refuses a `--to` that exists, a `--to` folder that doesn't, a
  machine that isn't aarch64, and any digest that differs; nothing is written then.
  `<runtime>` is never changed: its tree digest is compared before and after. Nothing
  downloads at run time, and the box's network rules are unchanged.
- The script prints the box config's `search_tools` block; it goes next to `runtime_dir`
  and `pi_version`:

  ```json
  "runtime_dir": "/home/shinelay/.local/share/temper/pi-runtime/pi-0.87.1-rg15.2.0-fd10.5.0",
  "pi_version": "0.87.1",
  "search_tools": {
    "fd": {"version": "10.5.0", "sha256": "90dab774d92889926d75a85b47c4b2dc4c9adfa792cd3a6ccfcb98b0eabc9b94"},
    "rg": {"version": "15.2.0", "sha256": "c14cdb389f34e504d69e386cfc67d5c5d9a730a990de03ca6910b2a15e30386a"}
  }
  ```

  The config refuses, when it loads and again on the host before every box start (before
  the read-only mount), a name Temper doesn't pin, and a binary that is missing, a link, not
  executable or not exactly the pinned digest (`search_tool_changed` at a start). No in-box
  read-back per turn.
- A Pi step or team member whose tools include grep or find (Temper's Grep or Glob) is
  refused when the box config doesn't pin `rg` / `fd`: a Pi step fails before any worker or
  model call, a team stage's pre-run check names the member, and a box start raises
  `search_tool_missing` before any docker call. Each refusal names the script.
- Proof: `tests/test_pi_agent/test_box_search_tools.py`. Its sealed tests always run. The
  real-box test starts a box with the box's own create args, mounts and environment, runs
  Pi's own grep and find on a small fixture, reads `rg --version` and `fd --version` back
  from inside and checks `NetworkMode` none. It is skipped unless
  `TEMPER_PI_BOX_TEST_RUNTIME` names a runtime the script made
  (`TEMPER_PI_BOX_TEST_IMAGE` overrides the image, default
  `sha256:8cee32bd74cfacf0b0abfb8c919add49c74cf48dfcb967ac0ed73669cac121c0`):

  ```bash
  TEMPER_PI_BOX_TEST_RUNTIME=/home/shinelay/.local/share/temper/pi-runtime/pi-0.87.1-rg15.2.0-fd10.5.0 \
    uv run pytest tests/test_pi_agent/test_box_search_tools.py::test_pi_grep_and_find_work_offline_in_the_box -v -rs -s
  ```

- Rollback: point the box config back at the old runtime and drop `search_tools`. Members
  with Grep or Glob are then refused again, as above. An existing runtime folder is never
  changed in place; a new pin means a new folder.

## Rules

- May be the first node of a workflow: an owner wait saves where the run is under the
  wait's own id (a `step_parked` checkpoint), so the answer carries the run on from there
  even when nothing ran before it.
- One role per step; several roles work together only as a team stage, whose messaging
  is built ([pi-team-messages.md](pi-team-messages.md)) but whose leader loop is not yet.
- The step never returns empty output, and raises only `RunParked` (its run let the worker
  go at an owner wait) and `CancellationError` (the run was stopped while the step held its
  worker at a wait).
