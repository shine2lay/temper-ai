# What "done" means for a build (temper's method)

Read by the coding agent (task_implement) and the reviewer (task_review), so both hold a change to the same
rules. It says HOW temper judges a change. WHAT good looks like in a particular codebase is the project's call,
in its own `<repo>/.temper/standards.md` (with its codebase notes, `.temper/`). Where a project says nothing,
the defaults below apply.

**Done** = the change does everything the bet and its plan ask, AND the codebase afterwards reads as if one
careful author wrote all of it: every thing the change touches has one home, one name and one shape, every
new way of doing things is there for a good reason, and it all agrees with itself everywhere a user or a
developer can meet it.

## Who wins when rules disagree

1. The bet (the task and its details) and the owner's decisions (`.temper/core/decisions.md`, lines tagged
   `[owner ...]`).
2. The project's standards (`.temper/standards.md`): its rules, how strict each is, what to copy, what not to.
3. The code around the change: its naming, structure, error handling, comments and tests.
4. The defaults below.

The plan is how the bet gets built; it is not a rule of its own. A plan choice that breaks a standard or a
default **without saying why** is a plan slip: the coder does the conforming thing and reports it under
`deviations`; the reviewer holds the code to the rule and lists the slip under `plan_defects`. A plan choice
that states its reason (the plan's "Design vs rules" section, or a quoted owner decision) stands.

## The defaults: D1-D8

- **D1 One home.** Each figure, rule, threshold, word and piece of user-visible copy has one home (a
  function, a constant, a glossary entry); everything else reads it. Screens show what the server worked out:
  the browser formats, it never re-works a figure. A new figure gets one home, listed where the project lists
  its figures. Where twins already exist, the project's source is the home; never add another twin.
  A surface (a screen, a ticket, a message) answers each question once: two figures a user would read as the
  answer to the same question are twins even when one carries a label of its own ("estimated", "by the
  model", "for this order"), because a label does not make one thing two.
- **D2 The whole family.** When the change alters what a number, word, rule or state means, or adds one,
  every place it lives follows: the server, every screen, every message sent (alerts, chat replies, emails),
  the CLI, the API types and mocks, the glossary and copy, docs, tests, fixtures and seed data. Places
  outside the planned files are still part of the job.
- **D3 One word per thing.** Use the project's word (its glossary); the same thing has the same name on every
  surface, in code and in copy; no new synonyms; a word the project retired stays retired.
- **D4 Reuse before writing.** Before writing a helper, component, query or pattern, search for one that
  already does the job, by name AND by what it does (the formula, the operands, the output). Extend it rather
  than write its near-twin. Copy a sibling's shape (D5), not its code: where a new thing would re-type what a
  sibling already has (the same markup, attributes, wiring or steps, not merely the same kind of steps), that
  part becomes one block both use, in this change, and the sibling moves onto it. A rule every instance must
  re-type to follow is held by a block, and the standard names the block: prose is followed by copying, and
  copies drift.
- **D5 Copy the existing shape.** A new thing goes where its kind lives and looks like its closest existing
  sibling of the same kind: layers, naming, errors, logging, audit, tests. Say which sibling you copied.
- **D6 A clean diff.** Every changed line serves the bet. No reformatting untouched code, no drive-by
  renames, no dead code or debug leftovers, no new TODOs, no weakened or skipped tests. Comments and doc
  comments stay attached to what they describe and stay true after the change: a new function never goes
  between an existing doc comment and its function, and a comment that describes old behaviour is updated.
- **D7 Fix the class.** A problem found once is looked for everywhere the change reaches and fixed
  everywhere; the report says where.
- **D8 A new pattern earns its place.** A new pattern is a way of doing a kind of job that the change brings
  in rather than copies: the first of its kind (the first chart, the first file download), a second way of
  doing a job the codebase already does, an abstraction, layer, option or generic helper, a dependency, a
  home-made version of what the stack or a library already in use does, or an exception to a standard. Each
  needs a good reason, and the change must show it:
  - **A real need**: something the bet asks for (or the brief, a standard, an owner decision). Taste
    ("cleaner", "more flexible", "more modern"), a case no one has asked for yet, and speed of writing are
    not reasons.
  - **What exists cannot do it**: the existing way, and the stack's own, was searched for by name and by
    what it does, and it cannot do this job, or extending it would break its users or give it a second job.
    The reason says concretely what it lacks. "There was none" holds only if a search finds none.
  - **No bigger than the need**: one user needs no generic version; one case needs no option.

  An exception to a default written as a standard (a twin kept "by design", a copy where a block would do)
  is a new pattern too: its reason says why one home or one block cannot do the job. How twins are kept in
  step (a test that pins them) is not a reason for there to be two.

  A new way to do the SAME job as an existing one, only better, is not added beside it: in the same change,
  move every user of the old way to it (D2), or leave the idea to the owner under `standards_proposals`.
  The reason is written where later builds will meet it: a pattern later code should copy becomes a
  standard, with its example and its reason (a proposal for the owner where the owner keeps the
  standards); an exception gets a comment at the place saying why the usual way does not fit. The coder's
  map lists every new pattern with its reason; the reviewer checks every new pattern it finds, listed or
  not. With no reason that holds, use what is there.

## Caused by the bet, or there before

The owner's rule: **fail it if the bet caused the difference; if it was there before, only note it.**
The bet caused it when the change made it, changed it, copied it somewhere new, or put it where a user now
sees it disagree with something (a new figure placed beside an older twin that shows a different value).
Those are findings. A twin, stale word or slip that was already on the base branch, that the change does not
touch and does not make visible, is a note (`follow_ups`), not a finding: it goes to the codebase notes and
is not this branch's to fix.

**Fix it here** (the owner, 2026-09-28). When the change puts older code where a user now sees it disagree
with what the change shows or promises (an older sentence, figure, label or reason on a surface the change
touches, or one that speaks about what the change alters), the change fixes it in the same branch, even on a
line it did not otherwise touch: a feature that adds a refusal also fixes the older line beside it that says
the order is fine. Keeping an older wording "word for word" inside a sentence the change rewrote is not
leaving it alone.

## A finding

- **rule**: what it breaks: a plan clause (`plan: Rules 2`, `plan: Acceptance 3`, `plan: Copy`), a project
  standard (`S3`), or a default (`D2`). **No rule, no finding**: a better idea that no rule asks for goes
  under `notes`, and a problem that keeps coming back with no rule to name goes under
  `standards_proposals` for the owner to decide.
- **severity**:
  - `blocker`: a wrong result, broken behaviour, lost data, a security hole, a test deleted or bent to pass,
    work left uncommitted, a report claim the evidence contradicts.
  - `major`: something a user could see disagree (two values or two words for one thing, labelled or not);
    a place in the family still saying the old thing; a figure worked out away from its home or a second
    home added (D1);
    planned behaviour, copy or a planned test missing or wrong; a test that cannot fail; a new pattern
    without a reason that holds (D8): a second way of doing a job, or an abstraction, layer, option or
    dependency that no need calls for.
  - `minor`: code-only fit that a user never sees: a naming slip, a stale or detached comment, dead code, a
    formatting-only change, a near-twin of a generic helper, a new pattern whose reason holds but is not
    written down where D8 says.
  A project's standards may move a rule to another severity. Every finding, minor ones included, holds the
  branch until it is fixed.
- **places**: EVERY place the problem occurs, found by searching, not only the first one seen
  (`path::symbol` or `path:line`, one per place). `where` is the first of them.
- **what**: the problem and the evidence (the line, the command output) in one or two sentences.
- **fix**: what to change, for the whole class, specific enough to act on without re-deriving it. The fix
  meets the rule: it never offers a way out that leaves the problem where a user or a later build meets it
  (a label beside a second value, a comment beside a twin, a standard loosened to allow the copy).
