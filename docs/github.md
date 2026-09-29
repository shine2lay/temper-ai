# GitHub — start temper from an issue or pull request

Temper works GitHub issues and pull requests as its own GitHub app,
**temper-ai-bot**, and answers in the same thread. Everything it posts from
GitHub work — comments, reviews, pull requests — shows as
`temper-ai-bot[bot]`, never as a person. (Linear and Notion work, and builds,
still sign with `TEMPER_GITHUB_TOKEN`, as before.)

```
GitHub ──webhook──▶ https://hooks.<zone>/api/hooks/github ──▶ trigger rules ──▶ github_work / github_review
                    (public, signed)                        configs/triggers/    agents act as the app
```

## Three ways to start it

| You do | Rule | Temper |
|---|---|---|
| Put the label **temper** on an issue | `github_label` | Reads the issue. Unclear: asks in the thread. Clear: makes the change and opens a pull request, then comments its link. |
| Write **@temper-ai-bot …** in a comment on an issue or pull request | `github_mention` | Does what is asked: answers a question, makes a change (a pull request), or reviews that pull request. Replies in that thread. |
| Reply in the thread of an issue labelled **temper** | `github_reply` | Carries the work on: an answer to its question starts the change, a change request updates the pull request, a question gets an answer, a comment that asks nothing of it gets nothing. |
| Open a pull request | `github_pr_review` — **off** | Nothing, until turned on (see [Settings](#settings)). Ask for a review with "@temper-ai-bot review this" instead. |

How a run goes (`configs/workflows/github_work.yaml`):

1. **triage** reads the whole thread and decides: *go* (clear work), *ask*
   (one comment with its questions, then stops), *answer* (one comment, then
   stops), *review* (the next step), or *none* (nothing asked of it: no
   reply).
2. **review** (review only): one review of the pull request that only
   comments — lines of the diff and a summary. It never approves, never
   requests changes and never merges: the tool always sends `COMMENT`,
   whatever the agent asks.
3. **repo** (go only): where the work happens, from the signed event, never
   from the model's words. An issue #12 is worked on branch
   `temper-issue-12`, cut from the default branch (roamee: `staging`). A
   change asked on temper's own pull request updates that same branch.
   Someone else's pull request #7 gets branch `temper-pr-7`, cut from theirs,
   and the pull request goes into their branch. A pull request from a fork is
   refused.
4. **build** is `epd_task`, as for Linear: plan, implement, review, security,
   the repository's CI checks and the gate's fix rounds.
5. **report** opens (or updates) the pull request as the app — a draft when
   the gate still has objections — with "Closes #12" for an issue, and
   comments its link in the thread. If there is nothing to push, it says what
   went wrong. It runs after a failed build too.

A reply after a question starts the next run, which reads the whole thread
again, including your answer.

## Who can start it

Only the accounts in `allowed_authors` (see below; `shine2lay` to start
with). Anyone else's label, comment or pull request is recorded as
`skipped: <login> may not start temper`, and so is anything the app did
itself (`skipped: the app's own doing`), so its own comments never start a
loop.

**One run per issue or pull request at a time.** A comment while a run for
that thread is still going starts nothing (recorded as skipped); the comment
stays in the thread and the next run reads it. This holds across restarts.

## Limits

- It **never merges**, approves, or requests changes, and never pushes a
  protected branch (`main`, `master`, `staging`, ...). The push and the pull
  request are temper's `OpenPullRequest` tool (with `identity: app`), not an
  agent's shell.
- Pull requests go only to repositories the app is installed on — temper
  asks GitHub which — and roamee's go into `staging`.
- On GitHub it only comments, reviews (comments only), and pushes its own
  branch. It does not close, label, edit or merge anything.
- **Private repositories** are cloned over ssh with the repository's own
  read-only deploy key (`local/github-deploy/setup.sh owner/name`); without
  one, the build of a private repository stops at the clone. Public ones are
  cloned over https.

## Settings

Everything is read on each event: a change works from the next one, no
restart.

**`configs/github/github.yaml`** — the server's settings (a git-ignored
`configs/github/local/github.yaml` is used instead when it exists):

```yaml
github:
  app: temper-ai-bot         # the app's name on GitHub: "@temper-ai-bot" calls on it,
                             # and "temper-ai-bot[bot]" is the app itself
  allowed_authors:           # who may start temper
    - shine2lay
```

**`configs/triggers/github_*.yaml`** — one file per way in. Each has
`enabled`, and optional filters under `on:`:

```yaml
trigger:
  name: github_pr_review
  source: github
  enabled: false             # true turns it on
  on:                        # every key optional; each a value or a list (any of)
    event: pull_request      # issues, issue_comment, pull_request
    action: [opened, ready_for_review]
    label: temper            # the label just put on (issues.labeled)
    has_label: temper        # the issue or PR carries this label
    mention: true            # the comment says "@<app>"
    pull_request: true       # the thread is a pull request (false: an issue)
    draft: false             # the pull request is (not) a draft
    repos: [shine2lay/temper-ai, shine2lay/*]   # only these repositories
    authors: [shine2lay]     # only these people (narrows allowed_authors, never widens it)
  workflow: github_review
  inputs:                    # workflow input -> template over the event
    repo: "{{ github.repo }}"
    number: "{{ github.number }}"
```

To **review new pull requests automatically** in some repositories: in
`github_pr_review.yaml`, set `enabled: true` and list them under `repos:`.
Drafts, and the app's own pull requests, are left alone.

`inputs` see the event as GitHub sent it, plus `github.*`: `repo`, `number`,
`kind` (issue or pull), `action`, `label`, `labels`, `sender`, `comment_id`,
`is_pull`, `draft`, `default_branch`, `private`, and for a pull request
`head_ref`, `head_repo` and `base_ref`. An unknown key under `on:` is an
error in the rule, not a filter that never applies.

## Setup

Once. The app's id, private key and webhook secret go in `~/temper-ai/.env`
with the other keys.

1. **Make the app** (on the host, where the env file is). This serves a page
   that hands GitHub the app's manifest — the name, the webhook
   `https://hooks.wai2shine.com/api/hooks/github`, the events (issues,
   issue comments, pull requests) and the permissions (issues, pull requests
   and contents read/write, metadata read):

   ```
   temper github setup --env-file ~/temper-ai/.env --listen <this machine's address>:8765
   ```

   Open the page it names in a browser that can reach that address, and click
   **Create GitHub App** on GitHub. GitHub sends the browser back to the page,
   which trades the code for the app's keys and writes them into the env
   file (the key base64 on one line):

   ```
   GITHUB_APP_ID=...
   GITHUB_APP_PRIVATE_KEY=...
   GITHUB_APP_WEBHOOK_SECRET=...
   ```

   Nothing secret is printed. By hand instead: `temper github manifest`, then
   `temper github convert CODE --env-file ~/temper-ai/.env` with the code
   GitHub put in the address (it works once, within an hour).

   **Or make it on GitHub's own form** (Settings → Developer settings →
   GitHub Apps → New GitHub App), as temper-ai-bot was made. It needs:
   the webhook URL above with a secret you make up, content type
   `application/json`; repository permissions **Contents**, **Issues** and
   **Pull requests** read and write (Metadata read comes with them); and the
   events **Issues**, **Issue comment** and **Pull request**. Then generate a
   private key, and put the three values in the env file yourself — the key
   as `base64 -w0 key.pem`, and delete the `.pem` after. More permissions do
   no harm (the tokens temper makes never carry them); more events are
   answered and dropped, but are noise in GitHub's delivery log.

   Keep the env file to yourself: `chmod 600 ~/temper-ai/.env`. Where the
   checkout is mounted into temper's server (a local
   `docker-compose.override.yml`), a run's box sees it too, and an env file
   others may read would give every key in it to the agents.

2. **Install it** on the repositories it may work on (the link is on the
   page after Create: `https://github.com/apps/temper-ai-bot/installations/new`).
   Installing it on more later needs no change in temper.

3. **Open the public path**, next to Linear's and Notion's:

   ```
   standee gateway route add hooks.wai2shine.com 127.0.0.1:8420 --only /api/hooks/github --public
   ```

4. **Restart temper** with `temper-deploy restart`, so the server reads the
   new keys. `temper-deploy hooks` shows every public hook path answering.

5. **Check it:** `docker compose exec server temper github check` — the app
   as GitHub knows it, where it is installed, a token for each installation,
   the webhook secret, the settings and which rules are on. It exits 1 with
   `warnings` for anything that stops temper working: a permission or event
   the app lacks, an installation that has not accepted the app's new
   permissions (the account's Settings → Applications), a settings name that
   is not the app's, an env file others can read. `notes` list what the app
   has that temper never uses.

If the app's name is not `temper-ai-bot` (say it was taken), set `app:` in
`configs/github/github.yaml` to its real name: that is the word people
@mention and how temper knows its own doings.

## Where the key is

Only temper's server holds the private key. It is taken out of the
environment when temper starts, so nothing temper starts inherits it: an
agent's shell (the Bash tool strips it too), a run's box, a CLI model. A
run that acts as the app asks the server for a token for one repository
(`POST /api/github/token`, not public), which works for at most an hour; the
server makes those from the key and reuses each until five minutes before
it runs out.

A token is only ever for that one repository, and carries only what temper
uses there — contents, issues and pull requests (read and write), metadata
(read) — however much more the app was given on GitHub. (Listing where the
app is installed takes a token with metadata read only.)

## How an event is handled

- **Genuine.** `X-Hub-Signature-256` must be the HMAC-SHA256 of the exact
  body under `GITHUB_APP_WEBHOOK_SECRET`, compared in constant time.
  Otherwise 401, and nothing runs.
- **Kept first.** An event that checks out is saved in temper's event inbox
  before temper answers, and handled from there: failures are tried again
  (1 min, 5 min, 30 min, 2 h) and a restart picks up where it left off.
  Until the webhook secret is set, events are kept unchecked (answered 202)
  and checked once it is; forged ones are then dropped.
- **Once.** GitHub's redeliveries carry the same `X-GitHub-Delivery` id,
  which the inbox already has, so nothing starts twice.
- **Only what can start work.** Issues, issue comments and pull requests
  are kept, and so are the app's own `ping` and installation events (a
  record of when it was set up). Any other event the app is sent — CI runs,
  check runs — is checked, answered 200 (`ignored`) and dropped, not kept.
- **Visible.** `temper events list --source github` lists events and what
  became of each ("started github_work …", "no trigger matched",
  "skipped: …"). `GET /api/hooks/github/recent` (behind the API token, not
  public) lists the last ones.
