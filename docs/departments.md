# Departments

temper's agents and workflows are looked after by **department roles**: AI
roles that each stand in for one department of a tech company (product,
design, QA and so on) and use temper to test, improve and automate that
department's part of the work. A role does nothing on its own: it works only
when the owner starts a chat as it.

Each role has a charter (what it covers, what it owns, how it tests and lands
a change) and a journal of its discipline's best practices, applied to its
agents, that grows with every trial it runs. Both are kept outside this
repository. This page is the shared part: who owns which config, and how a
role tests and lands a change.

## The roles

| Role | Department | Looks after |
|---|---|---|
| `product` | Product management | Finding and building a new product that reaches product-market fit and pays, with a temper pipeline for each product-management process: so far the market scan, the signal harvest, the opportunity brief and the validation engine. New products only: RollCall's loop is not its part. |
| `marketing` | Product marketing | `blog_writer` and its agents; next, launch notes and positioning for what the loop ships. |
| `design` | Design | The personas, walks and report stage; measured design reviews and their planted-problem grader; editable Penpot homepage and original vector logo workflows with owner gates ([design.md](design.md), [design-logo.md](design-logo.md)). |
| `architecture` | System architecture | The plan stage (lead, architect, check), the build's reviewer, the code lens, the structure and pattern graders, the build rules, `code_review`. |
| `frontend` | Frontend engineering | The plan stage's frontend engineer, `frontend_dev`, and the frontend side of every build. |
| `backend` | Backend engineering | The plan stage's backend engineer, the build workflow with its planner, coder and verdict steps, the build replays and grader. |
| `qa` | QA | The plan stage's QA engineer, the reach and break lenses, the build's test run and browser check, the walkers' seeded accounts. |
| `systems` | System engineering | Claims, worktrees, test stacks, deploys, cleanup, shipping, the probe, and the CI and smoke workflows temper-ci runs. |
| `security` | Security | The build's security read and its diff scan, and the security reviewer of `code_review`. |
| `data` | Data & analytics | The measure stage, the stage scorecard and its judge, the walk report, and the plan stage's numbers engineer. |
| `docs` | Docs | The knowledge-folder check (`.temper/`) and capability maps; next, a docs grader, a doc step for builds, changelogs. |

Two owners are not departments:

- **temper**: the engine (`temper_ai/`), the integrations (GitHub, Linear,
  Notion, Slack, Telegram), the demos, and the settings, triggers and MCP
  servers they use.
- **RollCall**: runs the EPD loop (firing bets, gates, merges) and owns how
  its stages connect: `epd_loop`'s wiring and the scripts around it. It also
  owns the loop's proposal side: the problems, bets and pitches, the pitch
  review with its fit lens, and their graders (product handed them back on
  2026-10-01 to work on new products only).

## Who owns what

- Every agent and workflow under `configs/` (outside `local/` folders) has
  exactly one owner, listed in the [table](#the-ownership-table) below.
- A department owns its agents, plus its own test and automation workflows.
- A step several departments use has one owner: the one whose work it mostly
  does. The others propose changes through that owner.
- A config that is added, renamed or removed changes its row here in the same
  commit, and a new one gets its owner when it is added. The roles keep this
  page up to date, each its own rows.
- `local/` folders are per installation (gitignored) and have no rows.

## How a role tests and lands a change

The same six steps for every role, built on what temper already has. A live
config is never edited to try something.

1. **Build a candidate next to the live config.** Either a `_next` copy that
   only a test workflow uses (as `task_implement_next` and `task_review_next`
   are for the build pair), or a config in a `local/` folder under `configs/`
   (gitignored, this installation only). Configs are found by name, so a
   candidate always gets a name of its own, never a live config's.
2. **Re-run past work with it.** Either fork a past run onto a candidate
   workflow (`POST /api/runs/fork` takes the `workflow` to continue on, the
   `source_execution_id` and the checkpoint `sequence`; the new run shares
   the old one's history up to that point, then goes on by itself), or use a
   replay workflow: `epd_build_replay` (a past bet built again by the
   candidate coder and reviewer), `epd_review_replay` (the candidate reviewer
   alone on a past change), `epd_build_new` (a new project from nothing), or
   `epd_probe` (the deploy and verify mechanics, with no model work except the
   browser check).
3. **Grade both**, the live config's work and the candidate's, with the role's
   grader (below). A role without one builds one first, and checks it against
   verdicts the owner has already given.
4. **Compare score and cost.** A candidate that scores the same for less is a
   winner too.
5. **Land only a winner.** Promote the candidate into the live config in a
   worktree of its own, and land it through the repository's gate: lint,
   types, the tests (including `tests/test_epd`), the frontend, e2e and a
   whole temper built from the commit must all pass before master moves.
   temper-ci deploys a landed commit by itself; temper is never restarted by
   hand. Configs reach runs only from master: each run's worker reads
   `configs/` from master when it starts.
6. **Record it.** The result goes into the role's journal: what changed, both
   scores and costs, the run ids. A change to an EPD agent affects live bets
   from the next run on, so RollCall is told as well.

**Trial rules**

- Never trial on live bets: forks and replays only.
- Trials up to $10 go ahead; above that, the owner decides on an estimate,
  unless the owner has set a role a rule of its own (product has no cap
  since 2026-10-01).
- Check the spare subscription allowance first, and wait when an account is
  near its weekly limit.
- Delete local candidates when the trial is over.

### Graders and test workflows

| Workflow | What it grades or tries | Owner |
|---|---|---|
| `epd_pitch_grade` | A pitch, against what happened to the pitch the loop built for the same problem | RollCall |
| `epd_lens_grade` | A pitch review: which known problems it caught, and whether its other findings were real | RollCall |
| `epd_plan_grade` | A plan, against what happened to the plan the loop built for the same pitch | architecture |
| `epd_structure_grade` | A codebase built from nothing: structure, architecture, keeping to its patterns | architecture |
| `epd_pattern_audit` | One change: how well it kept to the patterns already there | architecture |
| `epd_review_replay` | The candidate reviewer alone, on a past change | architecture |
| `epd_build_grade` | One finished build of a bet, graded blind | backend |
| `epd_build_replay`, `epd_build_new` | The candidate coder and reviewer, on a past bet or a new project | backend |
| `epd_scorecard` | Every stage of one shipped bet, by three judges who don't see each other | data |
| `epd_probe` | Claim, worktree, stack, deploy, verify and cleanup, pass or fail | systems |
| `smoke_test`, `gate_smoke`, `ci_*` | An installation, at no model cost | systems |

Still to build: a grader for launch notes (marketing), the walks and the UI
(design), the frontend side of a build (frontend), seeded defects for the
build's test run and browser check (qa), seeded flaws for the security read
(security), and docs (docs).

## The ownership table

Paths are under `configs/`. *agent (script)* is an agent that runs a script
instead of a model; *script* is a helper in a `bin/` folder (`epd/bin/`,
`validation/bin/`).

### product (59)

| Config | Kind |
|---|---|
| `workflows/scan_market.yaml` | workflow |
| `agents/scan_check.yaml` | agent |
| `agents/scan_lens_demand.yaml` | agent |
| `agents/scan_lens_market.yaml` | agent |
| `agents/scan_lens_timing.yaml` | agent |
| `agents/scan_synthesize.yaml` | agent |
| `workflows/scan_serving.yaml` | workflow |
| `agents/scan_serving_prepare.yaml` | agent (script) |
| `agents/scan_serving_pain.yaml` | agent |
| `agents/scan_serving_screen.yaml` | agent |
| `agents/scan_serving_evidence.yaml` | agent (script) |
| `agents/scan_serving_audit.yaml` | agent |
| `agents/scan_serving_verify.yaml` | agent (script) |
| `agents/scan_serving_grade.yaml` | agent |
| `agents/scan_serving_assets/check_serving.py` | script |
| `agents/scan_serving_assets/cite.py` | script |
| `agents/scan_serving_assets/fixtures.json` | fixture |
| `workflows/signal_harvest.yaml` | workflow |
| `agents/signal_competitors.yaml` | agent |
| `agents/signal_jobs.yaml` | agent |
| `agents/signal_pain.yaml` | agent |
| `agents/signal_search.yaml` | agent |
| `agents/signal_synthesize.yaml` | agent |
| `workflows/opportunity_brief.yaml` | workflow |
| `agents/brief_check.yaml` | agent (script) |
| `agents/brief_competition.yaml` | agent |
| `agents/brief_feasibility.yaml` | agent |
| `agents/brief_gtm.yaml` | agent |
| `agents/brief_setup.yaml` | agent (script) |
| `agents/brief_synthesize.yaml` | agent |
| `agents/brief_viability.yaml` | agent |
| `workflows/desk_check.yaml` | workflow |
| `agents/desk_assumption.yaml` | agent |
| `agents/desk_final.yaml` | agent (script) |
| `agents/desk_setup.yaml` | agent (script) |
| `agents/desk_synthesize.yaml` | agent |
| `validation/workflows/validation_engine.yaml` | workflow |
| `validation/agents/ve_campaign.yaml` | agent |
| `validation/agents/ve_collect.yaml` | agent (script) |
| `validation/agents/ve_decide.yaml` | agent (script) |
| `validation/agents/ve_deploy.yaml` | agent (script) |
| `validation/agents/ve_interview.yaml` | agent |
| `validation/agents/ve_page.yaml` | agent |
| `validation/agents/ve_setup.yaml` | agent (script) |
| `validation/agents/ve_simulate.yaml` | agent (script) |
| `validation/bin/ve.py` | script |
| `validation/bin/ve_common.py` | script |
| `validation/bin/ve_live.py` | script |
| `validation/bin/ve_score.py` | script |
| `validation/bin/ve_site.py` | script |
| `validation/bin/ve_traffic.py` | script |
| `workflows/product_visibility_smoke.yaml` | workflow (non-model) |
| `agents/product_visibility_probe.yaml` | agent (script) |
| `product/bin/server_run.py` | script |
| `product/bin/weekly_scan.py` | script |
| `product/bin/visibility_evidence.py` | script |
| `product/bin/visibility_assets/probe.py` | script |
| `product/bin/visibility_assets/fixture.txt` | fixture |
| `product/bin/tests/test_server_run.py` | helper tests |

Product execution: [shared runs and local candidates](product-runs.md). Deployed live names
still load from master. Product trials instead register a transitive, uniquely namespaced
candidate with the supported Studio API; names absent from the deployed config tree survive
worker import without overwriting live definitions. Stage assets in a dedicated shared
workspace. Past direct-CLI execution history stays local-only; do not inject old events.

### marketing (4)

| Config | Kind |
|---|---|
| `workflows/blog_writer.yaml` | workflow |
| `agents/blog_drafter.yaml` | agent |
| `agents/editor.yaml` | agent |
| `agents/topic_researcher.yaml` | agent |

### design (20)

| Config | Kind |
|---|---|
| `epd/workflows/epd_report.yaml` | workflow |
| `design/workflows/design_review.yaml` | workflow |
| `design/workflows/design_review_grade.yaml` | workflow |
| `design/workflows/design_homepage_v1.yaml` | workflow (real direction/final owner gates) |
| `design/workflows/design_homepage_pilot_v1.yaml` | workflow (fictional-only provisional selection) |
| `design/agents/design_homepage_stage_v1.yaml` | agent (script; Penpot source, budget, evidence, handoff) |
| `design/workflows/design_logo_v1.yaml` | workflow (real original vector identity; direction/final owner gates) |
| `design/workflows/design_logo_fixture_v1.yaml` | workflow (model-free fictional gate/source/resume contract proof) |
| `design/agents/design_logo_stage_v1.yaml` | agent (script; schema, native source, receipts, budget, handoff) |
| `design/agents/design_logo_explore_v1.yaml` | agent (new original monochrome vectors) |
| `design/agents/design_logo_palette_v1.yaml` | agent (new shortlist and role palettes) |
| `design/agents/design_logo_critic_v1.yaml` | agent (new logo rubric/contract board; taste advisory) |
| `design/agents/design_logo_refine_v1.yaml` | agent (new bounded selected-direction refinement) |
| `epd/agents/epd_personas.yaml` | agent |
| `epd/agents/epd_walk.yaml` | agent |
| `design/agents/design_capture.yaml` | agent (script) |
| `design/agents/design_critic.yaml` | agent |
| `design/agents/design_merge.yaml` | agent |
| `design/agents/design_grade.yaml` | agent |
| `design/agents/design_score.yaml` | agent (script) |

### architecture (23)

| Config | Kind |
|---|---|
| `epd/workflows/epd_pattern_audit.yaml` | workflow |
| `epd/workflows/epd_plan.yaml` | workflow |
| `epd/workflows/epd_plan_grade.yaml` | workflow |
| `epd/workflows/epd_review_replay.yaml` | workflow |
| `epd/workflows/epd_structure_grade.yaml` | workflow |
| `epd/workflows/epd_tasks.yaml` | workflow |
| `workflows/code_review.yaml` | workflow |
| `agents/code_analyst.yaml` | agent |
| `agents/code_improver.yaml` | agent |
| `epd/agents/epd_lens_code.yaml` | agent |
| `epd/agents/epd_pattern_audit.yaml` | agent |
| `epd/agents/epd_plan_architect.yaml` | agent |
| `epd/agents/epd_plan_changes.yaml` | agent (script) |
| `epd/agents/epd_plan_check.yaml` | agent |
| `epd/agents/epd_plan_docs.yaml` | agent (script) |
| `epd/agents/epd_plan_grade.yaml` | agent |
| `epd/agents/epd_plan_lead.yaml` | agent |
| `epd/agents/epd_structure_grade.yaml` | agent |
| `epd/agents/epd_tasks.yaml` | agent |
| `epd/agents/task_review.yaml` | agent |
| `epd/agents/task_review_next.yaml` | agent |
| `epd/rules/build.md` | build rules |
| `epd/rules/new_project.md` | build rules |

### frontend (2)

| Config | Kind |
|---|---|
| `agents/frontend_dev.yaml` | agent |
| `epd/agents/epd_plan_frontend.yaml` | agent |

### backend (14)

| Config | Kind |
|---|---|
| `epd/workflows/epd_build_grade.yaml` | workflow |
| `epd/workflows/epd_build_new.yaml` | workflow |
| `epd/workflows/epd_build_replay.yaml` | workflow |
| `epd/workflows/epd_task.yaml` | workflow |
| `agents/backend_dev.yaml` | agent |
| `agents/coder.yaml` | agent |
| `epd/agents/epd_build_grade.yaml` | agent |
| `epd/agents/epd_plan_backend.yaml` | agent |
| `epd/agents/task_final.yaml` | agent (script) |
| `epd/agents/task_gate.yaml` | agent (script) |
| `epd/agents/task_implement.yaml` | agent |
| `epd/agents/task_implement_next.yaml` | agent |
| `epd/agents/task_minors.yaml` | agent (script) |
| `epd/agents/task_plan.yaml` | agent |

### qa (6)

| Config | Kind |
|---|---|
| `epd/agents/epd_lens_break.yaml` | agent |
| `epd/agents/epd_lens_reach.yaml` | agent |
| `epd/agents/epd_plan_qa.yaml` | agent |
| `epd/agents/task_seed_slot.yaml` | agent (script) |
| `epd/agents/task_test.yaml` | agent (script) |
| `epd/agents/task_verify.yaml` | agent |

### systems (22)

| Config | Kind |
|---|---|
| `epd/workflows/epd_deploy.yaml` | workflow |
| `epd/workflows/epd_probe.yaml` | workflow |
| `epd/workflows/epd_ship.yaml` | workflow |
| `workflows/ci_nested.yaml` | workflow |
| `workflows/ci_parallel.yaml` | workflow |
| `workflows/ci_slow.yaml` | workflow |
| `workflows/gate_smoke.yaml` | workflow |
| `workflows/smoke_test.yaml` | workflow |
| `agents/ci_step.yaml` | agent (script) |
| `agents/gate_smoke_ask.yaml` | agent (script) |
| `agents/gate_smoke_use.yaml` | agent (script) |
| `agents/smoke_echo.yaml` | agent (script) |
| `epd/agents/epd_deploy.yaml` | agent (script) |
| `epd/agents/epd_ship.yaml` | agent (script) |
| `epd/agents/task_branch_check.yaml` | agent (script) |
| `epd/agents/task_claim.yaml` | agent (script) |
| `epd/agents/task_cleanup.yaml` | agent (script) |
| `epd/agents/task_deploy.yaml` | agent (script) |
| `epd/agents/task_stack_detect.yaml` | agent (script) |
| `epd/agents/task_stack_down.yaml` | agent (script) |
| `epd/agents/task_stack_up.yaml` | agent (script) |
| `epd/agents/task_worktree.yaml` | agent (script) |

### security (3)

| Config | Kind |
|---|---|
| `agents/security_reviewer.yaml` | agent |
| `epd/agents/task_security.yaml` | agent |
| `epd/bin/diff_scan.py` | script |

### data (6)

| Config | Kind |
|---|---|
| `epd/workflows/epd_measure.yaml` | workflow |
| `epd/workflows/epd_scorecard.yaml` | workflow |
| `epd/agents/epd_judge.yaml` | agent |
| `epd/agents/epd_measure.yaml` | agent |
| `epd/agents/epd_plan_numbers.yaml` | agent |
| `epd/agents/epd_report.yaml` | agent |

### docs (2)

| Config | Kind |
|---|---|
| `epd/bin/capabilities.py` | script |
| `epd/bin/kb_check.py` | script |

### RollCall (24)

| Config | Kind |
|---|---|
| `epd/workflows/epd_bet.yaml` | workflow |
| `epd/workflows/epd_lens.yaml` | workflow |
| `epd/workflows/epd_lens_grade.yaml` | workflow |
| `epd/workflows/epd_loop.yaml` | workflow |
| `epd/workflows/epd_pitch.yaml` | workflow |
| `epd/workflows/epd_pitch_grade.yaml` | workflow |
| `epd/workflows/epd_propose.yaml` | workflow |
| `epd/agents/epd_bet.yaml` | agent |
| `epd/agents/epd_bet_approved.yaml` | agent (script) |
| `epd/agents/epd_lens_fit.yaml` | agent |
| `epd/agents/epd_lens_grade.yaml` | agent |
| `epd/agents/epd_pitch_changes.yaml` | agent (script) |
| `epd/agents/epd_pitch_check.yaml` | agent |
| `epd/agents/epd_pitch_fix.yaml` | agent |
| `epd/agents/epd_pitch_grade.yaml` | agent |
| `epd/agents/epd_pitch_inputs.yaml` | agent (script) |
| `epd/agents/epd_pitch_previous.yaml` | agent (script) |
| `epd/agents/epd_pitch_write.yaml` | agent |
| `epd/agents/epd_problems.yaml` | agent |
| `epd/agents/epd_turn.yaml` | agent (script) |
| `epd/bin/epd_adopt.py` | script |
| `epd/bin/epd_loop.py` | script |
| `epd/bin/push_configs.py` | script |
| `epd/README.md` | readme |

### temper (74)

| Config | Kind |
|---|---|
| `workflows/demo_delegate.yaml` | workflow |
| `workflows/demo_dispatch.yaml` | workflow |
| `workflows/demo_dispatch_advanced.yaml` | workflow |
| `workflows/demo_dispatch_multilevel.yaml` | workflow |
| `workflows/demo_dispatch_scripted.yaml` | workflow |
| `workflows/demo_structured.yaml` | workflow |
| `workflows/github_review.yaml` | workflow |
| `workflows/github_work.yaml` | workflow |
| `workflows/linear_reply.yaml` | workflow |
| `workflows/linear_work.yaml` | workflow |
| `workflows/notify_probe.yaml` | workflow |
| `workflows/notion_crm_update.yaml` | workflow |
| `workflows/notion_work.yaml` | workflow |
| `workflows/repo_answer.yaml` | workflow |
| `workflows/roamee_answer.yaml` | workflow |
| `workflows/slack_pick.yaml` | workflow |
| `workflows/sprint.yaml` | workflow |
| `agents/context_scanner.yaml` | agent (script) |
| `agents/demo_coordinator.yaml` | agent |
| `agents/demo_dispatch_advanced_planner.yaml` | agent |
| `agents/demo_dispatch_critic.yaml` | agent |
| `agents/demo_dispatch_orchestrator.yaml` | agent |
| `agents/demo_dispatch_researcher.yaml` | agent |
| `agents/demo_dispatch_scout.yaml` | agent |
| `agents/demo_dispatch_scripted_planner.yaml` | agent (script) |
| `agents/demo_dispatch_summarizer.yaml` | agent |
| `agents/demo_summarizer.yaml` | agent |
| `agents/github_repo.yaml` | agent (script) |
| `agents/github_report.yaml` | agent |
| `agents/github_reviewer.yaml` | agent |
| `agents/github_triage.yaml` | agent |
| `agents/goal_checker.yaml` | agent |
| `agents/linear_reply.yaml` | agent |
| `agents/linear_repo.yaml` | agent (script) |
| `agents/linear_report.yaml` | agent |
| `agents/linear_triage.yaml` | agent |
| `agents/notion_crm_update.yaml` | agent |
| `agents/notion_repo.yaml` | agent (script) |
| `agents/notion_report.yaml` | agent |
| `agents/notion_triage.yaml` | agent |
| `agents/planner.yaml` | agent |
| `agents/repo_answer.yaml` | agent |
| `agents/repo_copies.yaml` | agent (script) |
| `agents/review_gate.yaml` | agent (script) |
| `agents/reviewer.yaml` | agent |
| `agents/roamee_answer.yaml` | agent |
| `agents/slack_pick.yaml` | agent |
| `agents/sprint_planner.yaml` | agent |
| `agents/sprint_recorder.yaml` | agent (script) |
| `agents/sprint_reviewer.yaml` | agent |
| `agents/sprint_worker.yaml` | agent |
| `github/github.yaml` | settings |
| `mcp_servers/git.yaml` | MCP server |
| `mcp_servers/linear.yaml` | MCP server |
| `mcp_servers/notion.yaml` | MCP server |
| `mcp_servers/playwright.yaml` | MCP server |
| `mcp_servers/puppeteer.yaml` | MCP server |
| `mcp_servers/searxng.yaml.disabled` | MCP server |
| `notify/notify.yaml` | settings |
| `notion/notion.yaml` | settings |
| `retention/retention.yaml` | settings |
| `slack/access.yaml` | settings |
| `slack/slack.yaml` | settings |
| `stages/code_review.yaml` | stage |
| `telegram/telegram.yaml` | settings |
| `tools/custom_tool_example.yaml` | tool |
| `triggers/github_label.yaml` | trigger |
| `triggers/github_mention.yaml` | trigger |
| `triggers/github_pr_review.yaml` | trigger |
| `triggers/github_reply.yaml` | trigger |
| `triggers/linear_work.yaml` | trigger |
| `triggers/linear_work_comment.yaml` | trigger |
| `triggers/notion_work.yaml` | trigger |
| `triggers/notion_work_comment.yaml` | trigger |
