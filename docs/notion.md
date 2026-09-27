# Notion

Temper works with Notion the way it works with Slack, Linear and Telegram:

- **Agents read and write Notion** during any workflow (tools below), e.g. keep
  a CRM table up to date from web pages (`notion_crm_update`).
- **A marked row starts work**: set a task's Status to `Temper` and
  `notion_work` reads it, asks on the page if it is unclear, and otherwise
  makes the change and opens a pull request (it never merges).
- **Runs report on the page**: a run started from a page posts its notices
  there as comments; a question it asks is a comment, and a reply answers it.
- **@temper and `/temper ask` answer from Notion pages** too, naming the page.

Temper writes to Notion only when a workflow step, an agent, the config or a
run's `notify:` asks for it, and only to the configured targets, pages under
them, and the page a run was started from. Nothing deletes or archives.

## Two identities

| | acts as | used by |
|---|---|---|
| **Temper connection** (`NOTION_TOKEN`) | the "Temper" bot; sees only pages shared with it | temper's Notion tools, triggers, notices, questions |
| **Your sign-in** (`temper connect notion`, an OAuth MCP grant) | you | agents that declare `notion.*` tools (Notion's MCP server) |

## Setup

1. In Notion: *Settings → Connections → Develop or manage integrations → New
   integration*. Name **Temper**, type *Internal*, your workspace.
   Capabilities: read, update and insert content; read and insert comments;
   no user information (emails).
2. Put its secret in `~/temper-ai/.env` as `NOTION_TOKEN=...`.
3. Share pages with it: on a page, *⋯ → Connections → Temper*. Temper sees
   that page and everything under it.
4. `configs/notion/local/notion.yaml` (git-ignored; the tracked
   `configs/notion/notion.yaml` is the example):

   ```yaml
   notion:
     targets:
       qa:     {page: <page id or URL>}
       tasks:  {table: <database id or URL>, key: Name}
       crm:
         table: <database id or URL>
         key: Company                  # the column that identifies a row
         fields: {company: Company, website: Website, industry: Industry}
     answer_from: all                  # or a list of target names / page ids
   ```

   Agents and workflows name a target (`crm`), never an id.
5. Webhook (for triggers and replies). The route is public only on this path:

   ```sh
   standee gateway route add hooks.wai2shine.com 127.0.0.1:8420 --only /api/hooks/notion --public
   ```

   In the integration's *Webhooks* tab: URL
   `https://hooks.wai2shine.com/api/hooks/notion`, events *Page* (created,
   properties updated, content updated) and *Comment* (created). Notion posts
   a verification token; `temper notion check` shows it. Paste it into Notion
   to verify, and put it in `.env` as `NOTION_WEBHOOK_SECRET=...` (every event
   is signed with it; unsigned or wrongly signed events are refused). Restart
   when idle.
6. `temper notion check` (in the server container:
   `docker exec -w /app temper-ai-server-1 /app/.venv/bin/temper notion check`)
   should be all `ok`.

`TEMPER_NOTION=0` turns it all off.

## Agent tools

| tool | does |
|---|---|
| `NotionSearch` | find pages and tables shared with Temper by words |
| `NotionRead` | a page or row as text (properties, body, tables; `comments: true` adds its comments), or a table's columns and rows |
| `NotionWrite` | a new page under a page, or text appended to a page |
| `NotionUpsert` | a table row found by its key, updated or created (never a duplicate); `row: origin` updates the run's own row (e.g. its Status) |
| `NotionComment` | a comment on a page |

A target is a name from the config, `origin` (the page the run started from),
or a page id/URL that is a target or under one. With tool config
`{scope: answer}` (as `repo_answer` uses) search and read are limited to
`answer_from`. Property values are converted to the column's type (title,
text, number, select, multi-select, status, date, URL, email, phone,
checkbox).

## Trigger rules

Rules live in `configs/triggers/` with `source: notion`:

```yaml
trigger:
  name: notion_work
  source: notion
  on:
    event: row            # row (created or properties changed) or comment
    table: tasks          # a table target
    property: Status      # with value: fires when it is set to this
    value: Temper
    # has_run: true       # only pages temper already worked (for comments)
    # actor_type: person  # default; temper's own changes never match
  workflow: notion_work
  inputs:
    page_id: "{{ page.id }}"
```

Templates see `page` (`id`, `url`, `title`, `properties`), `comment` (`id`,
`text`, `discussion_id`) and `event`. Notion's events only say *what*
changed, so temper reads the page before matching. One run per page at a
time: a change while one is going starts nothing (the recent list says
"skipped"). `GET /api/hooks/notion/recent` (API token) lists the last events
and what became of each.

## Workflows

- `notion_work` — the Linear way, for a Notion task row: triage (asks on the
  page if unclear or the **Repo** property is empty; `roamee` or
  `temper-ai`), build with `epd_task` on branch `notion-<page id>`, then a
  pull request, its link as a comment, and Status → *In Review*. A person's
  comment continues it (`notion_work_comment`).
- `notion_crm_update` — `urls` and/or `text` in, one upserted row per company
  in the `crm` table (or `table=`) out; a second run updates, never
  duplicates.
- `repo_answer` — also reads Notion pages for questions about them.

## Notices and questions

Notion is a place in `configs/notify` (see [notify.md](notify.md)): a run
started from a page sends its notices there as comments (its origin), and
`places: {qa-page: {notion: qa}}` names a page for any run. A question is
posted as a comment. Reply in its thread (or, if it is the only open
question on the page, anywhere on the page):

- `reject` / `no` / `stop` … stops the run;
- one question: the reply is the answer (an option's name picks it);
- several: `1. …` / `2. …` lines;
- no questions: `ok` approves.

Every other copy (Slack, Telegram) then says who answered in Notion.
