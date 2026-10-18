# .temper/: what temper's agents know about this codebase

Written for agents, not people: dense, one fact per line. temper's agents read it before they answer a question about temper-ai or plan a change to it, so they start from a map instead of rediscovering the code. The first reader is temper's own Slack bot: `@temper` / `/temper ask` answer questions about the repos from these notes first, then from the code.

## layout
| file | holds | read by |
|---|---|---|
| topics/capabilities.md | what temper is (one paragraph), then every HTTP route and CLI command, derived from the code, one written sentence each with its file | anyone asking what temper can do or where a feature lives |

The work temper can do is its workflow configs: each `configs/workflows/*.yaml` carries a `@description`, and `GET /api/workflows/search?q=` finds them, so they are not repeated here. More files can join as agents learn the codebase (rollcall's `.temper/` also has core/map.md, core/decisions.md, core/gotchas.md and topic files); add each one to this table.

## keeping it true
A line that has quietly gone false is worse than no line: it is read with the same confidence.
- capabilities.md: the list is rewritten from the code by `configs/epd/bin/capabilities.py --repo .`; only the paragraph under "What this is" and the sentence after each entry are written by hand, and a refresh keeps them.
- A new route or command arrives undescribed: write its sentence. A sentence that went false is rewritten, never annotated.
- Check before committing: `capabilities.py --repo . --check --strict` (the list matches the code and every entry has a sentence).
