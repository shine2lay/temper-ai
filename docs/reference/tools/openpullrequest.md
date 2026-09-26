[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `OpenPullRequest` Tool

[Back to Tools](index.md)

> Push the branch checked out in a task's git worktree to GitHub and open a pull request for it into `base`. Returns the PR's URL. If a PR for the branch is already open, pushes the new commits and returns that PR. It never merges, never force-pushes, and refuses protected branches (main, master, staging, ...).

The one tool in temper that writes to GitHub. The token is read here, in the
tool, from ``TEMPER_GITHUB_TOKEN`` in the server's environment: an agent's
shell never sees it (the Bash tool strips every ``*_TOKEN`` variable), and
the agent that calls this tool only says which worktree, which base and what
the PR says. What it may push is decided here, not by the model:

* only to a repository on the allowlist (``repos`` in the tool config, else
  ``TEMPER_GITHUB_PR_REPOS``), and only one whose clone the worktree is: the
  worktree has to be ``<workspaces>/repos/<name>/worktrees/<slug>``, with
  ``<name>`` the repository's name, and the branch has to share history with
  the repository's base branch. A worktree of the private roamee cannot be
  pushed to the public temper-ai, whatever the agent asks.
* never to a protected branch (main, master, staging, production, ...), never
  to the base branch, and never a branch with nothing on it;
* never with --force: a push GitHub would reject as non-fast-forward is
  reported, not overwritten.

The push does not run in the worktree. The implementer had a shell in there,
so its git config and hooks are the implementer's: a pre-push hook, a
credential helper, or a ``url.*.insteadOf`` could each hand the token to
someone else. So the branch is fetched into a fresh bare repository that has
no hooks and no config, and pushed from there, with the token passed as an
HTTP header through the environment (not the command line, which any process
may read).

If a PR for the branch is already open, it is returned as it is: a later run
on the same issue pushes new commits to the same PR.

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo` | string | Yes | owner/name of the GitHub repository, e.g. shine2lay/roamee |
| `worktree` | string | Yes | Path of the task's git worktree (the build's worktree_path) |
| `base` | string | Yes | Branch the PR merges into, e.g. staging or master |
| `title` | string | Yes | PR title |
| `body` | string | Yes | PR description (markdown) |
| `draft` | boolean | No | Open as a draft PR (default false) |

## Usage

Add `OpenPullRequest` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [OpenPullRequest]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
