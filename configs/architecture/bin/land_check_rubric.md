# Land check: Architecture's method

A land check answers one question about one branch: may this exact head land on master now, as it
is, and under which conditions? Big temper changes land switched off. The check is the last look
before temper-ci deploys the commit to production, so a missed step costs the most here. The answer
is a decision first, then the reasons, the consequences and what to watch for.

The draft you help write is read by the System architecture role, who writes the real check itself.

## What the case folder holds

- request.md: the gate, the branch, the checked head, master at the check, the check time, the
  switch, the evidence files, the proof inputs with their recorded digests, and the bindings the
  branch claims (each with its named tests). Its JSON block is the machine-readable copy.
- code/: the repository at the checked head. The ref `master` is master as it was at the check.
  Commits the evidence names are under refs/evidence/.
- proof/: copies of the inputs the check may use: the branch's report and result, its evidence, the
  gate's own records (reviews, approvals, design checks). Nothing written after the check time.
- scratch/facts.json: the mechanical facts, computed by a script before any model reads the case.
  scratch/diff.patch: git diff base head.

## 1. Mechanical checks (arch_land_facts runs them; never argue a failed one away)

Each has a fixed name and passes or fails on facts, never on judgement. A draft that fails one names
it and lands false. Spot-check anything in facts.json that looks odd.

1. commit_identity: the head resolves; its tree, the base (merge-base with master at the check), the
   commits, the changed files and the combined patch-id (git diff base head | git patch-id --stable)
   are recorded exactly.
2. clean_worktree: git status --porcelain in code/ is empty. Landing a dirty tree lands something
   nobody tested.
3. master_overlap: master's commits after the base touch none of the branch's files. An overlap stops
   the check: the branch is rebased and checked again (a rebase question), never landed blind.
   Master moving without overlap is fine: the landing conditions keep the patch-id rule.
4. input_digests: every input with a recorded digest still has it, and every batch folder still
   matches its MANIFEST.sha256. A changed input means the evidence is not what was reported.
5. evidence_binding: every evidence run passed and names the commit it ran on: the head, or a rebased
   copy of it (the same patches commit for commit), or an earlier commit of the branch when every
   later commit changes tests only. A tree it names must be that commit's tree; a clean it names must
   be true. Worker images and Pi versions are recorded; differing ones are a warning.
6. binding_tests: every test a claimed binding names exists at the head, and no evidence lists it as
   failed or leaves it out of a per-test list that should hold it.
7. switch_off: the slice's switch defaults off: every read of its setting at the head has an off
   default, no config the branch changes turns it on, and a fresh process without the setting sees
   it off.
8. department_rows: every agent or workflow config the branch adds has its row in
   docs/departments.md.

## 2. The review: judgement on top of the facts

Read the facts, then the diff, then the code where the diff leads. A report is a claim about code:
check claims against what the code does.

1. The request. What did the gate allow and forbid? What must stay unchanged while switched off
   (existing workflows, routes, pages, tables and jobs behave as today)?
2. Existing files. List every existing file the branch changes outside its own new package. For each,
   say why the new behaviour is inert when switched off, or for runs that are not the new kind. A
   core file changed without that reason is the first place to look.
3. Evidence. Does it cover what the request claims, on this head? A report claim the tests do not
   back (for example "checked at the end of every scenario" when some scenarios skip the check) is a
   finding.
4. Claimed bindings. Spot-read the named tests: do they assert what the binding says, or only that
   nothing crashed?
5. Failure modes. For each new write path: what if the process dies between two writes? What if two
   callers race? What do cancel, restart and retry do; is an id reused where it must be fresh? Do
   threads, sockets, child processes, rows or dictionaries grow per turn or per run? Does error
   handling match on loose text (a string that also appears in unrelated errors)?
6. The plan-review list, one line each, so nothing is skipped:
   - failure modes;
   - migration and rollback (new tables, stored formats, can it be undone);
   - security (secrets, tokens, what crosses a boundary, the sandbox's edges);
   - observability (a failure shows red where the owner looks; nothing fails silently);
   - cost (work per turn or per run that grows);
   - ownership and dependencies (files outside the slice, other roles' areas, who owns a follow-up);
   - fit with past decisions (the gate's bindings, earlier checks);
   - reversibility (two-way door or one-way: stored data, public interfaces, deletions);
   - tests (does each claim have a test that would fail without the change; does anything run only
     against fakes when the real thing differs: a real box, database or daemon?).
7. Master. If master moved after the base, read what it changed.

Kinds of findings Architecture raised on past land checks, to calibrate what is worth writing:
- a gap between two writes that a crash leaves half done (run row ended, team rows still open);
- a resource that grows per turn (an accept thread per turn that never exits);
- tests that claim an invariant but skip its check in some scenarios;
- a path proven only against a fake, never end to end against the real environment;
- a dictionary that only grows in a long-lived process;
- a caught signal that silently drops what it carried (a question nobody will see);
- bindings the next slice must keep or fix (a refusal that must stay, a check a resumed run must
  repeat, a read-back the switch-on must do);
- follow-ups for another owner (an engine bug found on the way: a lost request id, a question asked
  twice, processes left as zombies, an answer lost when a process dies mid-step);
- residual risks with a named later step (a route not yet live, a pinned version, a rule a later
  task must carry).

## 3. Severity: what blocks landing now

must-fix blocks landing this head now. Only:
- the branch changes what production does today while switched off;
- the evidence does not show the branch works on this head, or a claimed binding is not proven;
- a security or data-loss problem production can reach after this lands;
- the branch breaks a decision its gate set.
(A failed mechanical check blocks by itself; it is not repeated as a finding.)

follow-up does not block, but must be fixed later: name who or which task (a binding for a later
task such as #38, L3 or C7 when the proof names it; a follow-up for another chat; a residual risk
and what proves it later). Most real findings on a switched-off branch are follow-ups.

nit is optional and never part of the verdict. Prefix it "Nit:" and say when (now, when the file is
next touched, before switch-on).

Approve a change once it clearly improves the code's health, even if it is not perfect (Google's
standard). Taste is never a must-fix. When unsure whether something blocks, it does not: write it as
a follow-up with the reason, and let Architecture decide.

## 4. Writing a finding

Each finding names: id; severity; place (path:line or path::function); risk (what goes wrong, and
when); why here (why it matters in this codebase and this slice, not in general); fix (concrete, with
its owner or task); evidence (what you read: file:line, test name, proof file). A finding without a
reason cannot be weighed by the gate.

## 5. The verdict and the draft's sections

- land = every mechanical check passes AND no must-fix stands after the challenge.
- decision: one paragraph, the verdict first, then reasons, consequences, what to watch for.
- findings (problems only), verified (what was checked and passed, and how), nits_not_blocking,
  landing_conditions, bindings_for_later_tasks, follow_ups (for other chats), residual_risks,
  not_covered (what this check did not look at).

Usual landing conditions (adapt to the case):
- Land exactly the checked commits through wt land; fast-forward if master has not moved.
- If master moved without touching the branch's files: rebase, run the repo gate once on the rebased
  tree, and land only if the combined patch-id is unchanged.
- If a newer master commit touches the branch's files: stop and write a rebase question for a
  re-check.
- No manual restart: temper-ci deploys the landed commit; confirm the deployed commit contains it.
- Production stays as it is: the switch stays unset, no settings change; say how that is checked.

## 6. Never

- Never invent evidence, or trust a report's claim without the proof file that backs it.
- Never run the branch's tests against live services, start runs, or change anything outside
  scratch/ and the files your step must write.
