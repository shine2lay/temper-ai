# Linear — events in, reads and writes out

Temper takes Linear's webhooks and starts workflows from them, and its agents
read and write Linear through Linear's hosted MCP server. It acts as its own
Linear app, so everything it writes shows as **Temper**, not as a person, and
its own changes never start another run.

```
Linear ──webhook──▶ https://hooks.<zone>/api/hooks/linear ──▶ trigger rules ──▶ workflow
                    (the only public path)                 configs/triggers/    agents use linear.* tools
```

## Working an issue

Put the label **temper** on an issue, and a label saying which repository:
**repo:roamee** or **repo:temper-ai**. Temper works it, and stops at a pull
request (`configs/workflows/linear_work.yaml`):

1. **triage** reads the issue and its thread. Unclear, or no `repo:` label:
   it asks on the issue and stops. Clear: moves the issue to *In Progress*,
   says so, and writes the brief.
2. **repo** looks the label up in a fixed table (roamee: branch from
   `staging`, over its read-only deploy key; temper-ai: from `master`). A
   repository not in the table stops here.
3. **build** is `epd_task`: a worktree on branch `linear-<issue>`, plan,
   implement, review, security, the repository's CI checks, and the gate's fix
   rounds. No dev stack and no browser QA.
4. **report** opens the pull request (a draft when the gate still has
   objections), comments its link, and moves the issue to *In Review*. If there
   is nothing to push, it says on the issue what went wrong. It runs after a
   failed build too.

**Reply on the issue** to continue: an answer to temper's question starts the
work, a change request updates the same branch and pull request, a question
gets an answer, and a comment that asks nothing of temper gets nothing. Any
person's comment on a `temper` issue starts a run; temper's own never do.
While a run for the issue is still going, a comment starts nothing (one run per
issue at a time); the next run reads it.

It **never merges**, and never pushes `main`, `master` or `staging`: the push
and the pull request are temper's `OpenPullRequest` tool, not an agent's shell,
with the token in `TEMPER_GITHUB_TOKEN`. On the issue it only comments and
moves the state (`LinearMoveIssue`). A run on code costs a few dollars, so it
only runs when a person labels or replies.

`linear_reply` (read the issue, reply with a plan, no code) is still there to
run by hand: `temper run linear_reply --input issue_id=ROA-5`.

## Setup

Once, by a Linear workspace admin:

1. **The app.** Linear → Settings → API → OAuth applications → *New*. Name it
   `Temper`, turn on **Client credentials**, save. Put its client id and secret
   in `.env`:

   ```
   LINEAR_CLIENT_ID=...
   LINEAR_CLIENT_SECRET=...
   ```

2. **The webhook.** On the same app (or Settings → API → Webhooks): URL
   `https://hooks.wai2shine.com/api/hooks/linear`, events **Issues** and
   **Comments** (add others when a rule needs them). Copy its signing secret
   into `.env`:

   ```
   LINEAR_WEBHOOK_SECRET=...
   ```

   For [working issues](#working-an-issue): the labels `temper`,
   `repo:roamee` and `repo:temper-ai`; a GitHub token that can push and open
   pull requests on those repositories, as `TEMPER_GITHUB_TOKEN`; and for a
   private repository, its own read-only deploy key
   (`local/github-deploy/setup.sh owner/repo`).

3. **Restart temper** so the server and worker read the new variables
   (`docker compose up -d server worker`; this ends runs in progress).

4. **Check it:**

   ```
   temper linear check          # who temper acts as, the MCP tools, the webhook secret
   temper linear issue ENG-123  # read an issue and its comments
   ```

The public address is made with standee (0.23+), and only the one path is on
the internet — every other path stops at Cloudflare's edge with a 404, and the
API and dashboard stay tailnet-only:

```
standee gateway route add hooks.wai2shine.com 127.0.0.1:8420 --only /api/hooks/linear --public
```

Until `LINEAR_WEBHOOK_SECRET` is set the path answers 503 and does nothing.

## Rules

One YAML file per rule in `configs/triggers/` (or the gitignored
`configs/triggers/local/`). Rules are read on every delivery, so a new or
changed rule works from the next event, with no restart.

```yaml
trigger:
  name: linear_work
  source: linear
  on:                        # every key optional; each a value or a list (any of)
    type: Issue              # Issue, Comment, IssueLabel, Project, Cycle, ...
    action: create           # create, update, remove
    team: ENG                # the issue's team key (a comment's: its issue's)
    has_label: temper        # the issue carries the label now (true on every edit)
    label_added: temper      # the label was just put on (or the issue created with it); fires once
    actor_type: user         # who did it: user (a person) or integration, oauthClient, ...
  workflow: linear_work
  ignore_self: true          # default: skip changes temper made itself
  enabled: true
  inputs:                    # workflow input -> template over the delivery
    issue_id: "{{ data.id }}"
    identifier: "{{ data.identifier }}"
```

- A Comment delivery names its issue but not the issue's labels or team, so
  for a Comment temper asks Linear for them first and puts the issue at
  `data.issue` (`data.issue.identifier`, `data.issue.labels`): that is what
  `has_label` and `team` read for a comment.

- Labels and team keys compare case-insensitively. An unknown key under `on:`
  is an error in the rule, not a filter that never applies.
- `inputs` are Jinja templates over the delivery body (`data`, `url`,
  `actor`, `updatedFrom`, ...) in a sandbox, with every field required: a
  rule naming a field the event lacks is logged as an error rather than
  starting a workflow with a blank input. Text people typed into Linear is
  data and is never evaluated as a template.
- One rule failing (a missing workflow, a bad template) does not stop the
  others.
- Prefer `label_added` to `has_label` for anything that writes back: a
  `has_label` rule fires again on every edit of a labelled issue.

## Reading and writing from a workflow

Agents list the tools they use, prefixed `linear.`:

```yaml
tools:
  - linear.get_issue
  - linear.list_comments
  - linear.save_comment      # also: linear.list_issues, linear.save_issue (create or update), ...
```

The server is `configs/mcp_servers/linear.yaml` (`https://mcp.linear.app/mcp`,
`auth: client_credentials`). Temper gets a token for the app with the client
id and secret — no browser login, no refresh token — and renews it before it
expires. Linear renames tools now and then; `temper linear check` lists the
current ones and says if one the Linear agents need is gone.

The scope is `read,write` (`LINEAR_SCOPE` overrides it). The MCP server and
the webhook's self-check must ask for the **same** scope: Linear revokes every
token an app holds when one is requested with a different scope.

From the shell, as the app: `temper linear comment ENG-123 < reply.md`.

## How a delivery is handled

- **Genuine.** `Linear-Signature` must be the HMAC-SHA256 of the exact body
  under `LINEAR_WEBHOOK_SECRET` (compared in constant time), and the body's
  `webhookTimestamp` within a minute of now. Otherwise 401, and nothing runs.
- **Once.** Linear retries with the same `Linear-Delivery` id; ids seen in
  the last 24 h are acknowledged without starting anything again.
- **Fast.** Linear gives up after 5 s, so the handler answers as soon as the
  delivery checks out; matching rules and starting runs happen after.
- **Not its own.** With `ignore_self` (the default) a change whose actor is
  the app itself is skipped. If temper cannot tell (the app is not set up, or
  Linear does not answer), a guarded rule does not fire — a missed event is
  cheaper than a loop.
- **Visible.** `GET /api/hooks/linear/recent` (behind the API token, not
  public) lists the last 50 deliveries and what became of each: the runs
  started, "no trigger matched", "ignored: temper's own change", or the error.
  The server log has the same.
