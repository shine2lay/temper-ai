# Portable Container Git Stages (`code_checkout`, `code_save`, `code_land`)

Owned by **System engineering** (`systems`). Together these stages check out a GitHub repository inside a container-local directory, commit and push changes without persisting credentials on disk, and land a branch onto its base with required check-run verification, clean conflict auto-resolution, and gate-backed resumption across container restarts.

## Overview

| Stage | Config | Kind | Purpose |
|---|---|---|---|
| `code_checkout` | `configs/epd/agents/code_checkout.yaml` | Script agent | Shallow single-branch clone at `<root>/repo` using an ephemeral GitHub App installation token |
| `code_save` | `configs/epd/agents/code_save.yaml` | Script agent | Stage, secret-scan, commit, and push `HEAD` to `origin/<branch>` |
| `code_land` | `configs/epd/workflows/code_land.yaml` | Reusable stage workflow | Open/reuse PR (`mode=pr`) or merge directly (`mode=merge`), auto-resolve clean conflicts, enforce GitHub check-runs, and pause at a Temper gate instead of failing on human-actionable blockers |

All network authentication mints short-lived GitHub App installation tokens on demand from `POST ${TEMPER_SERVER_URL}/api/github/token` authenticated by `TEMPER_RUN_TOKEN`, injecting them via transient `GIT_CONFIG_*` environment headers. Tokens are never written to `.git/config`, remote URLs, stdout, stderr, or commit messages.

---

## `code_save` (`configs/epd/agents/code_save.yaml`)

### Inputs

| Input | Default | Description |
|---|---|---|
| `work_dir` | *(required)* | Container-local git checkout path (rejects `/home/shinelay*`, `/app/workspaces*`, and `${WORKSPACE_DIR}`) |
| `message` | *(required)* | Non-empty commit message |
| `branch` | current `HEAD` branch | Target branch on `origin`; refuses protected/base branches (`main`, `master`, `production`, `prod`, `release`) |
| `files` | `""` (all changes) | Optional JSON array or newline-separated repo-relative paths; rejects absolute paths, `..`, and `.git` |
| `allow_empty` | `"false"` | `"true"` creates and pushes an empty commit when the worktree is clean; `"false"` returns `pushed=false` without pushing |

### Secret & credential guard

Before committing, `code_save` scans every staged file path and added diff line (`git diff --cached -U0`). It unstages and fails loud if any staged file matches `.env*` (except `.env.example`/`.sample`/`.template`), `*.pem`, `*.key`, `*credentials*`, `id_rsa`/`id_ed25519`, or added lines containing private-key headers or GitHub/OpenAI/Anthropic/AWS/Slack/Temper tokens.

### Structured output

```json
{"pushed": true, "branch": "feat/example", "sha": "<40-char-sha>", "clean": false}
```

---

## `code_land` (`configs/epd/workflows/code_land.yaml`)

`code_land` wraps two script agents so active check polling stays bounded while human gate waits have **no timeout** and survive container shutdowns:

1. `code_land_attempt` (`configs/epd/agents/code_land_attempt.yaml`, `timeout_seconds: 7200`)
2. `code_land_pause` (`configs/epd/agents/code_land_pause.yaml`, `gate: true` on workflow node, `condition: action == "pause"`, `loop_to: code_land_attempt`, `max_loops: 20`, `on_max_loops: fail`)

### Inputs

| Input | Default | Description |
|---|---|---|
| `branch` | *(required)* | Source branch on `origin` |
| `work_dir` | `""` | Container-local git checkout from Round 1 (optional when `repo` or `prior_pause` is present) |
| `repo` | `""` | Optional `owner/repo` or GitHub URL fallback when `work_dir` is absent |
| `base` | `"main"` | Target base branch |
| `mode` | `"pr"` | `"pr"` (idempotently find or create PR, then merge via Pulls API) or `"merge"` (merge onto `base` without opening a PR) |
| `merge_method` | `"squash"` | `"squash"`, `"merge"`, or `"rebase"` (`mode="pr"`) |
| `require_checks` | `"true"` | Enforce GitHub check-runs (`GET /repos/{owner}/{repo}/commits/{sha}/check-runs?per_page=100`) before merging in both modes |
| `title` / `body` | `""` | Optional PR title and body |
| `poll_interval_s` | `"10"` | Poll interval while check-runs or mergeability are pending |
| `checks_appear_timeout_s` | `"30"` | Grace window for initial check-runs to appear on `<head_sha>` when `require_checks="true"` |

### Behavior

- **Clean conflict auto-resolution**: When `base` has moved and GitHub reports `mergeable=false` (or `mode=merge` diverges), `code_land_attempt` fetches `origin/<base>` and `origin/<branch>` and runs `git merge --no-edit origin/<base>`.
  - If the merge is clean, it pushes the new merge commit `<new_sha>` to `origin/<branch>`, records `auto_resolved: true` and `resolved_files`, and **invalidates prior check-run state** so `<new_sha>` must pass check-runs afresh before merging.
  - If the merge conflicts, it runs `git merge --abort` immediately (never pushing conflict markers) and pauses at `code_land_pause` naming the conflicting files, PR URL, branch, and base.
- **`require_checks` enforcement**: Deduplicates reruns by `(app.id, name)` keeping the highest check-run `id`. Every check must reach `status == "completed"` with `conclusion` in `{"success", "neutral", "skipped"}`. Failing conclusions pause immediately (`checks.state = "failed"`); zero check-runs after `checks_appear_timeout_s` pause with `"no checks reported"` (`checks.state = "none"`).
- **Stateless resumption across box restarts**: `code_land_attempt` emits durable `{repo, pr_number, branch, base, sha, mode, require_checks}` and `code_land_pause` echoes that state across the gate. Whether a Pi workflow parks (`park_at_gates=True`, exiting the box immediately) or a non-Pi container dies after hours and is later approved and resumed (`needs_resume=True`), Round 2+ recovers full state even when Round 1's `/tmp` `work_dir` no longer exists on disk—cloning shallowly into an ephemeral temp directory only if local git conflict resolution is needed.

### Outputs

```json
{
  "merged": true,
  "sha": "<merged-commit-sha>",
  "pr_url": "https://github.com/owner/repo/pull/42",
  "pr_number": 42,
  "status": "merged",
  "auto_resolved": false,
  "resolved_files": [],
  "checks": {
    "state": "passed",
    "runs": [{"name": "temper-ci", "conclusion": "success"}]
  }
}
```
