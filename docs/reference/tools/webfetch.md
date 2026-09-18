[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `WebFetch` Tool

[Back to Tools](index.md)

> Fetch a web page and return its readable text — scripts, styles, nav and footers removed. Use this to read documentation, articles and API pages. JSON responses are returned formatted. Output is capped (default 30k characters) and says so when truncated. Use the http tool instead when you need the raw body, headers or a non-GET method.

Five agents (research_business, research_pm, research_marketing, research_designer,
…) declared `WebFetch` in their tools list for months; no such tool existed, so
`load_tools` logged a warning and dropped it. They only worked because they ran on
provider: claude, where Claude Code supplies its own WebFetch.

The gap it fills next to `http`: `http` returns `response.text` — for a docs page
that is mostly markup, and it is capped at 128KB of it. This strips scripts,
styles, nav and footers and returns the prose, which is the part an agent asked
for. Same shape of saving as Read vs `cat`, on a different axis.

Ported from pi's `fetch_content` (readable mode), which is the one pi extension
tool with no session coupling at all. Deliberately narrower than pi's:

* no `mode: "answer"` — that runs an LLM over the page. temper has its own model
  and its own orchestration; a tool that quietly starts a second inference is the
  wrong shape here.
* no PDF/YouTube/GitHub-repo handling — those are real features of pi's version
  that would each need a dependency. HTML and text are the 90% case; the tool
  says plainly when it meets something it cannot read.

Extraction is stdlib-only (`html.parser`). A real DOM library would handle
malformed markup better, but the job is boilerplate removal, and the container is
better off without another dependency.

Tightened for unattended use: private, loopback and link-local addresses are
refused by default, because an agent following a link into
`http://169.254.169.254/` or an internal service is a different event from an
agent reading a docs page. `allow_private_hosts` is tool CONFIG, not a model
parameter — the model cannot turn it off.

- **Modifies state:** No (read-only)

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | Absolute http(s) URL to fetch. |
| `max_chars` | integer | No | Maximum characters to return (default 30000, max 200000). |

## Usage

Add `WebFetch` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [WebFetch]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
