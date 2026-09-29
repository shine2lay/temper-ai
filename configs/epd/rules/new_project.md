# A new project: the first builds set the patterns (temper's method)

Read with build.md, by the coding agent and the reviewer, when the task says the project is new: its first
build, or one of the builds soon after it. The owner has handed the project's standards to the build pair,
and there is no planner. The requester's request is at `.epd/plan.md` (it says what the user needs, not which
files to change); the product brief is in the repository (the task says where).

## Why this file exists

Every later build copies what it finds (D5). In a new project the first endpoint, screen, form, list, test
and error path become the examples every later one follows, so a slip in the foundation is not one fix: it is
copied into every feature after it. A new project's build is judged on build.md's two halves (the request
works; the codebase reads as if one careful author wrote it) and on a third that only the first builds can get
right: **the foundation is one a careful team would choose to copy.**

## N1-N8: what the first build decides and writes down

Before the first line of the feature, the coder decides each of these and builds the request on them. Decide
for the product the brief describes, not for this request alone: the brief names what is coming, and the
foundation must take it without a rewrite. Build only what this request needs.

- **N1 Layout.** The top-level folders, and inside each app where each KIND of thing lives (for example:
  routes, request and response shapes, product rules, storage, UI building blocks, feature screens, the API
  client, formatting, text shown to users, tests). One kind, one place: a newcomer can say where a new one
  goes without asking. Group by feature or by layer, either way, stated and kept. File and symbol names
  follow one convention per kind.
- **N2 Layers.** What each layer may do and may not, and which way imports run. A figure or a rule of the
  product is worked out once, on the server (D1); the web app formats it and shows it. Validation that
  protects the data lives on the server; a screen that checks early uses the same limits, from their one
  home, or shows the server's answer. Nothing reaches past a layer (a screen calling `fetch` around the API
  client, a route writing SQL around storage).
- **N3 Values.** The values the product lives on, each with one home for parsing, arithmetic, rounding and
  display: money (never binary floating point: integer minor units or decimals, one rounding rule), dates and
  periods (whose timezone, what "this month" means), identifiers. The API states how each travels.
- **N4 Shapes.** One shape per kind, set by its first example: an endpoint (paths, verbs, status codes, the
  error body), a request or response schema, a storage model and query, how the database's shape changes
  once a household has data in it, a screen (how it loads and changes data; its loading, empty, error and
  success states), a form (field errors, the server's errors, submitting), a list or table, a test at each
  layer. The first of each kind is the example later ones copy, and the standards name it
  (`path::symbol`).
- **N5 Building blocks.** What every screen and endpoint will need is built once and used from the first
  feature on. On the web: the controls (button, text and money inputs, select, form layout, confirm; each
  with its label, and its error tied to it for a screen reader), the
  displays (money, dates), the states (loading, empty, error), the page frame and navigation, and ONE API
  client (base URL, JSON, errors). On the server: the app's error type and how it becomes a response, the
  database session, settings. A block has one job and a name that says it; each has a user in the build that
  adds it. A later screen never re-writes markup or logic a block already has: it uses the block, or extends
  it (D4). Nor does it re-type what an earlier screen wrote by hand: the second user is the moment the shared
  part becomes a block, in that change, with the first screen moved onto it, and the standard names the
  block instead of describing the markup.
- **N6 Words.** A glossary: one word per thing, the same in the database, the API, the types, the screens and
  the copy (D3). The brief's words win; a word the brief lacks is chosen once and added.
- **N7 Checks.** Each app has one command per check: install, lint, format check, type check, test, build.
  CI runs every one on every pull request (the workflow the task names). Whatever a tool can enforce
  (formatting, import order, unused code, types) is enforced by a check, not by a line of prose. The checks
  pass on every build.
- **N8 Written down.** The decisions live in the repository, where every later build and review reads them
  first:
  - `.temper/standards.md`: the rules, numbered S1, S2, ... Each is a rule someone can check against a diff,
    with its example to copy (`path::symbol`), how strict it is (blocks the build, or noted) and its reason
    in a clause (D8: the job it does and, where it is not simply the stack's own way, why that would not
    do). Advice is not
    a standard ("keep components small" is not one; "a screen reaches the API only through
    `web/src/api/client.ts::request`" is). It ends with the check commands (N7).
  - `.temper/README.md`: what is where in `.temper/`.
  - `.temper/core/architecture.md`: the layout (N1) and the layers (N2), and the path of one request from a
    screen to the database and back, naming each file it passes through.
  - `.temper/core/glossary.md` (N6) and `.temper/core/figures.md`: every figure the product shows, with its
    one home.
  - The root README: what the project is, and how to install, run and check each app.
  Keep them short and true: they are read at the start of every build, and a note that disagrees with the
  code is a finding.

## Principles

- **Plain beats clever.** The stack's own conventions and a few well-known libraries before anything
  home-made; each dependency earns its place, and its line in the standards says why. No framework of your
  own, no generic base class or factory with one user, no option for a case the brief does not have.
  Everything a first build lays down is a new pattern, so each one earns its place as D8 says, and its
  standard carries the reason, where every later build reads it.
- **Small and named.** A file or function does one thing and is named in the product's words; one that grows
  a second job splits along the layout.
- **Types carry the rules.** Values (N3) and the API's shapes are typed end to end, and the web's types for
  the API match the server's schemas: generated from them, or held to them by a test, so a change on one side
  fails the other side's checks instead of reaching a user.
- **Tests at the layer that owns the rule.** A product rule or figure is tested where it is worked out; each
  endpoint through the app, on a throwaway database; each screen's states through its component. A test's
  name says the rule it pins, and it fails when the rule breaks.
- **Seams where the brief will grow.** Where the brief names a coming feature, the foundation lets it slot
  in (a new kind of record copies the first one's shape end to end), without building any of it.

## Later builds

The standards and the notes are part of the codebase and are judged like code.
- A build that adds a NEW KIND of thing (the first chart, the first file download, the first setting) sets
  its shape the way the first build did: its standard, its example and its reason (D8) go into
  `.temper/standards.md` in the same change. A second way of doing a job the project already does one way
  is not added beside the first: extend the one there is, or change its standard as the next line says.
- A build that finds a standard wrong, missing or in the way changes it in the same change, says why on the
  standard's line, and brings along every place the old standard shaped (D2). A build never breaks a standard
  quietly, and never loosens one to let its own code through.
- A building block that a new screen needs to do more is extended, not copied (D4, N5). What an earlier
  screen or endpoint wrote by hand and a new one needs too becomes a block both use, in that change (D4).
- A standard an earlier build wrote binds a later build only while it holds (see Precedence here): a build
  that leans on one to allow what a default forbids checks its reason first.
- The notes stay true: a change that makes one wrong fixes it.

## Precedence here

build.md's order holds: the request, then the project's standards, then the code around the change, then the
defaults. Here the standards are the pair's own work, not the owner's, so being written down blesses nothing:
N1-N8 and D1-D8 are the floor under them. A standard that breaks an N or a default (money in floats, a check
CI never runs, a twin kept "by design", a list that every screen re-types by hand) needs a reason that holds
by D8, saying why one home or one block cannot do the job; without one it is a finding against the rule it
breaks, and the code it governs is judged by that rule. The reviewer judges each standard the change writes
or leans on before it judges code by it.

## How the method changes on a new project

The coder's and the reviewer's methods hold, with these differences.

- **The plan is the request.** `.epd/plan.md` is the requester's request: what the user can do, numbered
  rules, and "Done when". It names no files and has no task list. Its rules are the plan's rules, its "Done
  when" lines are the acceptance criteria, and the strings it quotes are the copy. Read the brief whole with
  it: the brief names what is coming.
- **The first build writes the standards and the notes.** On the first build there is no code and no
  `.temper/`: deciding N1-N8 and writing them down is part of the job, and a first build without them is not
  done. On a later build, the standards and notes the earlier builds wrote are the project's: read them
  first; they bind like any project's (see Later builds).
- **The coder writes the tasks.** The map begins with `## Tasks`: the work split into tasks that each end
  green and are committed as `task N: <what>`. On the first build: the foundation first (the layout, the
  checks and CI; then the building blocks the feature needs), then the feature layer by layer (storage, the
  product's rules, the API, the web app's client, the screens), then the notes. Each rule and each "Done
  when" line of the request names the task that makes it true. A later round and the reviewer read the
  tasks there.
- **Then the foundation.** After the tasks, the first build's map has `## Foundation`: N1-N8, each decided in
  a few lines with its reason, as the standards will state it; and its `## New patterns` lists each
  dependency and each abstraction, layer, option or generic helper, with its reason (D8). A later build's
  map lists instead the standards and building blocks it uses, and under `## New patterns` each new kind it
  adds, with the standard it sets and its reason.
- **Shapes copied.** A first-of-its-kind thing has no sibling to copy: its `Shapes copied` line says `first of
  its kind: sets S<n>`, naming the standard that now describes its shape. A later build's new thing names its
  sibling as in any project.
- **Acceptance is shown by tests.** No one else will use the app before it merges: each rule and each "Done
  when" line is pinned by a test that fails when it breaks, at the layer that owns it: a rule of the product
  through the API; what a screen shows (a negative in red, a field's error, what an empty list says) through
  the screen's component test. The reviewer reads the tests as the evidence.
- **The checks are CI's.** The test step runs the `run:` steps of the pull-request workflows in
  `.github/workflows/` on a clean checkout of the commit, on a machine with Python 3.12 and uv, Node 20 and
  npm, and no make or Docker; `uses:` steps are skipped there. So the checks must pass from a clean clone:
  lock files committed, nothing that relies on the coder's own tree. Before handing over, the coder runs
  every one of those commands, as written, in a clean checkout of HEAD (`git -C <wt> worktree add --detach
  /tmp/<name> HEAD`, removed after).
- **Changed tests on a later build.** An assertion a later build removes, loosens or gives a new expected
  value needs a rule of the request that changes the behaviour it pins. The coder names the rule in the
  map's task; the reviewer checks it there, in place of the plan's tests-to-change.
- **A request that disagrees with itself or the brief.** Build the reading its rules support (the rules over
  an example; the brief's words over a request's), say so under `deviations`, and the reviewer lists it
  under `plan_defects`.

## What the reviewer adds

Besides build.md's two halves (on a new project "what was asked" is the request: its rules and its "done
when"):
- **The foundation, N1-N8.** Each decided, written down as checkable rules with examples, and true to the
  code. A decision the code makes that the notes do not record, a standard the code breaks, a note that says
  one thing where the code does another: each is a finding (N8, or the standard).
- **Fit within the change.** In a new project most of the change has no older sibling, so D1-D8 are judged
  within it: two things of one kind shaped two ways (D5); a building block written twice, bypassed or
  near-copied (D4, N5); markup or logic re-typed from an earlier screen or endpoint instead of held by a
  block, even where a standard describes it (D4); a figure or a limit worked out in two places or in the
  browser (D1, N2); two words for one thing (D3, N6).
- **The standards themselves.** Each standard the change writes or leans on, judged before the code is
  judged by it (Precedence here): a standard that allows what an N or a default forbids, with no reason that
  holds, is a finding, at least **major**, because every later build follows it.
- **Reasons (D8).** Every pattern the build sets has a reason that holds, written in its standard: the
  stack's own way used plainly, or a block already there, would not do the job, and nothing is bigger than
  the need. A dependency, abstraction, layer or option that no need in the brief or the request calls for
  is a finding; so is a standard with no reason, or a reason the code shows to be false.
- **Structure.** A kind with no clear home or with two, a layer doing another's job, an import running the
  wrong way, a file mixing kinds (N1, N2).
- **Values.** Money in binary floats; a rounding or timezone rule decided in more than one place (N3): a
  blocker when it can change a figure a user sees, else major.
- **Growth.** Would the next feature the brief names slot in by copying what is here? Where it would need a
  rewrite of what this build laid, not an extension, that is a finding against the N it breaks, saying what
  and why. A better idea that no N asks for goes under notes.
- **Severity.** As build.md, and: a foundation slip that later builds would copy (a wrong shape, a bypassed
  block, a missing or false standard, a pattern with no reason that holds) is at least **major**, because
  every copy of it costs a fix later.

The diff of a first build is the whole project. Leave generated files out of what you read (lock files:
`-- . ':!**/package-lock.json' ':!**/uv.lock'`), and read it in layers: the standards and notes first, then
the server from storage up, then the web app from the API client up.
