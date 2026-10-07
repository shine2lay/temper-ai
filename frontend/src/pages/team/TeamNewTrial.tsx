import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CalendarClock, ListChecks, Lock, Play, Plus, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useDocumentTitle } from '@/hooks/useDocumentTitle';
import { useTeamStatus } from '@/hooks/useTeamStatus';
import { useTeamRoles } from '@/hooks/useTeamLists';
import { useTeamStart } from '@/hooks/useTeamStart';
import { readFailWords, shortId } from '@/lib/teamText';
import {
  emptyForm,
  FALLBACK_TOOLS,
  findingIds,
  memberAnchor,
  newMember,
  pickRole,
  placeFindings,
  sentRows,
  TEAM_MAX_MEMBERS,
  trialInput,
  type CheckOutcome,
  type FormMember,
  type PlacedFindings,
  type SentRow,
  type StartOutcome,
  type TrialForm,
} from '@/lib/teamForm';
import type { TeamFinding } from '@/types/team';
import { TeamGuardBanner } from '@/components/team/TeamGuardBanner';
import { TeamPageHeader } from '@/components/team/TeamPageHeader';
import { TeamNote } from '@/components/team/TeamNote';
import { EngineQuote } from '@/components/team/TeamQuote';
import { TeamCharCount } from '@/components/team/TeamCharCount';
import { teamBtn, teamCard, teamChip, teamChipTone, teamField, teamFieldBad, teamFieldTag, teamLabel } from '@/components/team/teamUi';
import { FieldNotes, FieldProblems, FindingLink, FindingsSummary } from '@/components/team/form/FormFindings';
import { MemberRow } from '@/components/team/form/MemberRow';

const DEFAULT_GOAL_MAX = 20_000;

/** What each way of talking means (board F1). */
const COMMUNICATION_WORDS: Record<string, string> = {
  all: 'every member can message every other member',
  edges: 'pick who talks to whom',
};

type FormResult =
  | { kind: 'check_passed'; notes: PlacedFindings }
  | { kind: 'problems'; from: 'check' | 'start'; problems: PlacedFindings; notes: PlacedFindings }
  | { kind: 'refused'; from: 'check' | 'start'; words: string }
  | { kind: 'no_answer'; from: 'check' }
  | { kind: 'no_answer'; from: 'start'; requestId: string };

const NONE = placeFindings([], []);

function checkResult(outcome: CheckOutcome, rows: SentRow[]): FormResult {
  switch (outcome.kind) {
    case 'passed':
      return { kind: 'check_passed', notes: placeFindings(outcome.notes, rows) };
    case 'problems':
      return {
        kind: 'problems',
        from: 'check',
        problems: placeFindings(outcome.problems, rows),
        notes: placeFindings(outcome.notes, rows),
      };
    case 'refused':
      return { kind: 'refused', from: 'check', words: outcome.words };
    case 'no_answer':
      return { kind: 'no_answer', from: 'check' };
  }
}

function startResult(outcome: Exclude<StartOutcome, { kind: 'started' }>, rows: SentRow[]): FormResult {
  switch (outcome.kind) {
    case 'problems':
      return {
        kind: 'problems',
        from: 'start',
        problems: placeFindings(outcome.problems, rows),
        notes: placeFindings(outcome.notes, rows),
      };
    case 'refused':
      return { kind: 'refused', from: 'start', words: outcome.words };
    case 'no_answer':
      return { kind: 'no_answer', from: 'start', requestId: outcome.requestId };
  }
}

/** A field's aria-describedby: its problems and notes first, then its own help. */
function describedBy(id: string, problems: readonly TeamFinding[], notes: readonly TeamFinding[], ...more: string[]) {
  return [...findingIds(id, problems, notes), ...more].join(' ') || undefined;
}

/**
 * New project: the form (Design's SPEC 3, boards F1-F5, S1, S2, S6). It
 * checks nothing itself but the character counts; Check and Run project ask
 * Temper, and Temper's problems and notes come back word for word, each
 * under its field and all in a list at the top.
 */
export default function TeamNewTrial() {
  useDocumentTitle('New project');
  const navigate = useNavigate();
  const { status, updatedAt } = useTeamStatus();
  const roles = useTeamRoles();
  const starter = useTeamStart();
  const [form, setForm] = useState<TrialForm>(() => emptyForm(status));
  const [result, setResult] = useState<{ seq: number; value: FormResult } | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const addRef = useRef<HTMLButtonElement>(null);
  const focusNext = useRef<string | null>(null);

  const reserved = status?.limits.reserved_names ?? [];
  const goalMax = status?.limits.goal_max_chars ?? DEFAULT_GOAL_MAX;
  const tools = status?.tools.available ?? FALLBACK_TOOLS;
  const bashAllowed = status?.tools.bash_allowed ?? false;
  const roleList = roles.data?.configured ? roles.data.roles : [];
  const busy = starter.busy;
  const input = useMemo(() => trialInput(form), [form]);
  const retry = busy === null ? starter.retrying(input) : null;

  const value = result?.value ?? null;
  const problems = value?.kind === 'problems' ? value.problems : NONE;
  const notes = value?.kind === 'problems' || value?.kind === 'check_passed' ? value.notes : NONE;

  // The problem list takes the focus when it appears (GOV.UK error summary).
  useEffect(() => {
    if (result?.value.kind === 'problems') headingRef.current?.focus();
  }, [result]);

  // A new row's Role select takes the focus.
  useEffect(() => {
    if (!focusNext.current) return;
    document.getElementById(`${memberAnchor(focusNext.current)}-role`)?.focus();
    focusNext.current = null;
  }, [form.members]);

  function show(next: FormResult) {
    setResult((prev) => ({ seq: (prev?.seq ?? 0) + 1, value: next }));
  }

  async function onCheck() {
    const rows = sentRows(form);
    show(checkResult(await starter.check(trialInput(form)), rows));
  }

  async function onRun() {
    const rows = sentRows(form);
    const outcome = await starter.start(trialInput(form));
    if (outcome.kind === 'started') {
      navigate(`/team/runs/${encodeURIComponent(outcome.started.execution_id)}`);
      return;
    }
    show(startResult(outcome, rows));
  }

  function update(key: string, change: (member: FormMember) => FormMember) {
    setForm((f) => ({ ...f, members: f.members.map((m) => (m.key === key ? change(m) : m)) }));
  }

  function addMember() {
    const member = newMember(status);
    focusNext.current = member.key;
    setForm((f) => (f.members.length >= TEAM_MAX_MEMBERS ? f : { ...f, members: [...f.members, member] }));
  }

  function removeMember(key: string) {
    setForm((f) => {
      const members = f.members.filter((m) => m.key !== key);
      return { ...f, members, leader: f.leader === key ? (members[0]?.key ?? '') : f.leader };
    });
    addRef.current?.focus();
  }

  const goalProblems = problems.fields.goal;
  const pauseProblems = problems.fields.pause_after_rounds;
  const commProblems = problems.fields.communication;
  const projectProblems = problems.fields.project_path;
  const membersProblems = problems.fields.members;
  const later = status?.communication.later ?? [];
  const available = status?.communication.available ?? ['all'];
  const roots = status?.project_roots ?? [];
  const settingsProblems = (status?.project_problems ?? []).filter((p): p is string => typeof p === 'string');
  const model = status?.defaults ?? null;
  const n = form.members.length;

  return (
    <div className="flex h-full flex-col overflow-auto bg-temper-bg">
      <TeamPageHeader tab={null} updatedAt={updatedAt} />
      <div className="flex flex-col gap-4 px-6 py-4">
        <TeamGuardBanner mode={status?.guard_mode} />
        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_384px]">
          <form
            data-testid="team-form"
            aria-label="New project"
            noValidate
            onSubmit={(event) => event.preventDefault()}
            className="flex min-w-0 flex-col gap-4"
          >
            {value?.kind === 'problems' && (
              <FindingsSummary from={value.from} placed={value.problems.all} headingRef={headingRef} />
            )}

            <section className={cn(teamCard, 'p-4')}>
              <div className="flex items-baseline gap-2">
                <label htmlFor="team-goal" className="text-sm font-semibold text-temper-text">
                  Goal
                </label>
                <span className={teamFieldTag}>required</span>
                <TeamCharCount text={form.goal} limit={goalMax} id="team-goal-count" className="ml-auto" />
              </div>
              <textarea
                id="team-goal"
                rows={5}
                value={form.goal}
                disabled={busy !== null}
                aria-invalid={goalProblems.length > 0 || undefined}
                aria-describedby={describedBy('team-goal', goalProblems, notes.fields.goal, 'team-goal-count', 'team-goal-help')}
                onChange={(event) => setForm((f) => ({ ...f, goal: event.target.value }))}
                className={cn(teamField, 'mt-2 min-h-28 resize-y', goalProblems.length > 0 && teamFieldBad)}
              />
              <FieldProblems id="team-goal" problems={goalProblems} className="mt-1.5" />
              <FieldNotes id="team-goal" notes={notes.fields.goal} className="mt-1.5" />
              <p id="team-goal-help" className="m-0 mt-1.5 text-xs text-temper-text-muted">
                What the team should do. Markdown is fine; it is shown as text.
              </p>
            </section>

            <section aria-labelledby="team-members-title" className={cn(teamCard, 'p-4')}>
              <div className="flex items-baseline gap-2">
                <h2 id="team-members-title" className="m-0 text-sm font-semibold text-temper-text">
                  Members
                </h2>
                <span id="team-members-count" className="ml-auto text-xs text-temper-text-muted">
                  {n} of up to {TEAM_MAX_MEMBERS}
                </span>
              </div>
              <p className="m-0 mt-1 text-xs text-temper-text-muted">
                Team names: lower-case letters, digits, - and _, up to 40 characters, starting with a letter. Each role
                joins once. The leader is one of the members.
              </p>
              {roles.data && !roles.data.configured && (
                // Inside the form's card the note's tint is lighter than on the page: muted text
                // there is 4.36:1 in the dark theme, so the note keeps to the main text colour.
                <TeamNote tone="warn" title="The role list isn't set up" className="mt-3">
                  {roles.data.problem && (
                    <EngineQuote className="mt-1" label="Temper said:" labelClassName="text-temper-text">
                      {roles.data.problem}
                    </EngineQuote>
                  )}
                  <p className="m-0 mt-2 text-temper-text">No roles can join a team until it is.</p>
                </TeamNote>
              )}
              {!roles.data && roles.error != null && (
                <TeamNote
                  tone="bad"
                  title="Couldn't load the role list."
                  className="mt-3"
                  action={
                    <button type="button" className={teamBtn.secondary} onClick={roles.refresh}>
                      <RefreshCw className="h-4 w-4" aria-hidden="true" />
                      <span>Try again</span>
                    </button>
                  }
                >
                  <EngineQuote className="mt-1" label="Temper said:" labelClassName="text-temper-text">
                    {readFailWords(roles.error)}
                  </EngineQuote>
                </TeamNote>
              )}
              {!roles.data && roles.error == null && (
                <p role="status" className="m-0 mt-3 text-xs text-temper-text-muted">
                  Loading the role list…
                </p>
              )}
              <div id="team-members-problems" tabIndex={-1} className="outline-offset-2">
                <FieldProblems id="team-members" problems={membersProblems} className="mt-3" />
                <FieldNotes id="team-members" notes={notes.fields.members} className="mt-2" />
              </div>
              <div className="mt-3 flex flex-col gap-2">
                {form.members.map((member, index) => (
                  <MemberRow
                    key={member.key}
                    index={index}
                    member={member}
                    roles={roleList}
                    reserved={reserved}
                    tools={tools}
                    bashAllowed={bashAllowed}
                    leader={form.leader === member.key}
                    canRemove={n > 1}
                    disabled={busy !== null}
                    problems={problems.rows[member.key] ?? []}
                    onRole={(role) => update(member.key, (m) => pickRole(m, role, reserved))}
                    onName={(name) => update(member.key, (m) => ({ ...m, name, named: true }))}
                    onLeader={() => setForm((f) => ({ ...f, leader: member.key }))}
                    onTool={(tool, on) =>
                      update(member.key, (m) => ({
                        ...m,
                        tools: tools.filter((t) => (t === tool ? on : m.tools.includes(t))),
                      }))
                    }
                    onRemove={() => removeMember(member.key)}
                  />
                ))}
              </div>
              <button
                ref={addRef}
                type="button"
                onClick={addMember}
                disabled={busy !== null || n >= TEAM_MAX_MEMBERS}
                aria-describedby="team-members-count"
                className={cn(teamBtn.secondaryMd, 'mt-3')}
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
                <span>Add member</span>
              </button>
              {tools.includes('Bash') && !bashAllowed && (
                <p id="team-bash-why" className="m-0 mt-3 flex items-start gap-1.5 text-xs text-temper-text-muted">
                  <Lock className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  <span>
                    <b className="font-semibold text-temper-text">Bash:</b>{' '}
                    {status?.tools.bash_why || 'Bash is off on this server.'}
                  </span>
                </p>
              )}
            </section>

            <section aria-labelledby="team-how-title" className={cn(teamCard, 'p-4')}>
              <h2 id="team-how-title" className="m-0 text-sm font-semibold text-temper-text">
                How the team works
              </h2>
              <div className="mt-3 flex items-baseline gap-2">
                <label htmlFor="team-pause" className="text-sm font-semibold text-temper-text">
                  Pause after this many rounds without done
                </label>
                <span className={teamFieldTag}>required</span>
              </div>
              <input
                id="team-pause"
                type="number"
                inputMode="numeric"
                min={1}
                step={1}
                value={form.pause}
                disabled={busy !== null}
                aria-invalid={pauseProblems.length > 0 || undefined}
                aria-describedby={describedBy('team-pause', pauseProblems, notes.fields.pause_after_rounds, 'team-pause-help')}
                onChange={(event) => setForm((f) => ({ ...f, pause: event.target.value }))}
                className={cn(teamField, 'mt-2 w-32', pauseProblems.length > 0 && teamFieldBad)}
              />
              <FieldProblems id="team-pause" problems={pauseProblems} className="mt-1.5" />
              <FieldNotes id="team-pause" notes={notes.fields.pause_after_rounds} className="mt-1.5" />
              <p id="team-pause-help" className="m-0 mt-1.5 text-xs text-temper-text-muted">
                No default. The team pauses for you when it has kept going this many rounds in a row without the
                leader saying done.
              </p>

              <fieldset
                id="team-communication"
                tabIndex={-1}
                aria-invalid={commProblems.length > 0 || undefined}
                aria-describedby={describedBy('team-communication', commProblems, notes.fields.communication)}
                className="m-0 mt-4 min-w-0 border-0 p-0"
              >
                <legend className="mb-1 p-0 text-sm font-semibold text-temper-text">Who can message whom</legend>
                {available.map((way) => (
                  <label key={way} className="flex min-h-8 cursor-pointer items-center gap-2 text-sm text-temper-text">
                    <input
                      type="radio"
                      name="team-communication"
                      value={way}
                      checked={form.communication === way}
                      disabled={busy !== null}
                      onChange={() => setForm((f) => ({ ...f, communication: way }))}
                      className="h-4 w-4 cursor-pointer rounded-full accent-temper-accent"
                    />
                    <b className="font-semibold">{way}</b>
                    {COMMUNICATION_WORDS[way] && <span className="text-temper-text-muted">· {COMMUNICATION_WORDS[way]}</span>}
                  </label>
                ))}
                {later.map((way) => (
                  <label key={way} className="flex min-h-8 cursor-not-allowed items-center gap-2 text-sm text-temper-text-muted">
                    <input
                      type="radio"
                      name="team-communication"
                      value={way}
                      disabled
                      className="h-4 w-4 rounded-full accent-temper-accent"
                    />
                    <span>{way}</span>
                    {COMMUNICATION_WORDS[way] && <span>· {COMMUNICATION_WORDS[way]}</span>}
                    <span className={cn(teamChip, teamChipTone.neutral, 'ml-2 text-temper-text-muted')}>
                      <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
                      comes later
                    </span>
                  </label>
                ))}
                <FieldProblems id="team-communication" problems={commProblems} className="mt-1.5" />
                <FieldNotes id="team-communication" notes={notes.fields.communication} className="mt-1.5" />
              </fieldset>
            </section>

            <section className={cn(teamCard, 'p-4')}>
              <div className="flex items-baseline gap-2">
                <label htmlFor="team-project" className="inline-flex items-baseline gap-2 text-sm font-semibold text-temper-text">
                  Code folder <span className={teamFieldTag}>(optional)</span>
                </label>
              </div>
              <input
                id="team-project"
                type="text"
                placeholder={roots.length > 0 ? `${roots[0].replace(/\/+$/, '')}/…` : undefined}
                value={form.project}
                disabled={busy !== null}
                autoComplete="off"
                spellCheck={false}
                aria-invalid={projectProblems.length > 0 || undefined}
                aria-describedby={describedBy('team-project', projectProblems, notes.fields.project_path, 'team-project-help')}
                onChange={(event) => setForm((f) => ({ ...f, project: event.target.value }))}
                className={cn(teamField, 'mt-2 font-mono', projectProblems.length > 0 && teamFieldBad)}
              />
              <FieldProblems id="team-project" problems={projectProblems} className="mt-1.5" />
              <FieldNotes id="team-project" notes={notes.fields.project_path} className="mt-1.5" />
              <p id="team-project-help" className="m-0 mt-1.5 text-xs break-words text-temper-text-muted">
                {roots.length > 0 ? (
                  <>
                    A git folder in:{' '}
                    {roots.map((root, i) => (
                      <span key={root}>
                        {i > 0 && ', '}
                        <code className="font-mono text-temper-text">{root}</code>
                      </span>
                    ))}
                    . The team works on copies of its committed content.
                  </>
                ) : (
                  <>No project folders are set up for teams, so a folder can&apos;t be used yet.</>
                )}{' '}
                Leave it empty to start from an empty project: then no branch is made at the end.
              </p>
              {settingsProblems.length > 0 && (
                <TeamNote tone="warn" title="Temper's team settings have a problem:" className="mt-3">
                  <ul className="m-0 list-disc pl-5">
                    {settingsProblems.map((p, i) => (
                      <li key={i} className="break-words" data-engine-words>
                        {p}
                      </li>
                    ))}
                  </ul>
                </TeamNote>
              )}
            </section>

            <div aria-live="polite" data-testid="team-form-result">
              {value?.kind === 'check_passed' && (
                <TeamNote tone="ok">
                  <p className="m-0">
                    <b className="font-semibold">The check passed.</b> Nothing was saved or started.
                  </p>
                  {value.notes.all.length > 0 && (
                    <>
                      <p className="m-0 mt-1 text-xs text-temper-text-muted">
                        Temper&apos;s note, so a passed check doesn&apos;t promise the start:
                      </p>
                      <ul className="m-0 mt-1.5 list-disc pl-5 text-xs">
                        {value.notes.all.map((p, i) => (
                          <li key={i}>
                            <FindingLink placed={p} />
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </TeamNote>
              )}
              {value?.kind === 'refused' && (
                <TeamNote
                  tone="bad"
                  title={value.from === 'start' ? 'Temper refused to start the project.' : 'Temper refused the check.'}
                >
                  <p className="m-0 break-words" data-engine-words>
                    {value.words}
                  </p>
                  <p className="m-0 mt-1 text-temper-text-muted">Nothing was saved or started.</p>
                </TeamNote>
              )}
              {value?.kind === 'no_answer' && value.from === 'start' && (
                <TeamNote tone="bad" title="Temper didn't answer. Trying again is safe: the same request counts once.">
                  <p className="m-0 text-temper-text-muted">
                    Request <code className="font-mono text-temper-text">{shortId(value.requestId)}</code> · your
                    inputs are kept.
                  </p>
                </TeamNote>
              )}
              {value?.kind === 'no_answer' && value.from === 'check' && (
                <TeamNote tone="bad" title="Temper didn't answer the check.">
                  <p className="m-0 text-temper-text-muted">Nothing was saved or started. Checking again is safe.</p>
                </TeamNote>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <p className="m-0 mr-auto text-xs text-temper-text-muted">
                {busy !== null ? 'Sending to Temper…' : 'Check runs the same checks without starting anything.'}
              </p>
              <button
                type="button"
                onClick={onCheck}
                disabled={busy !== null}
                aria-busy={busy === 'check' || undefined}
                className={teamBtn.secondaryMd}
              >
                <ListChecks className="h-4 w-4" aria-hidden="true" />
                <span>{busy === 'check' ? 'Checking…' : 'Check'}</span>
              </button>
              <button
                type="button"
                onClick={onRun}
                disabled={busy !== null}
                aria-busy={busy === 'start' || undefined}
                className={teamBtn.primaryMd}
              >
                {retry ? <RefreshCw className="h-4 w-4" aria-hidden="true" /> : <Play className="h-4 w-4" aria-hidden="true" />}
                <span>{busy === 'start' ? 'Starting…' : retry ? 'Try again' : 'Run project'}</span>
              </button>
            </div>
          </form>

          <aside className="flex min-w-0 flex-col gap-4" aria-label="About this project">
            <section className={cn(teamCard, 'p-4')}>
              <h2 className={teamLabel}>Model and thinking</h2>
              {model ? (
                <p className="m-0 text-sm text-temper-text">
                  <b className="font-semibold">{model.model}</b>
                  <span className="text-temper-text-muted"> · {model.provider} · thinking </span>
                  <b className="font-semibold">{model.thinking}</b>
                </p>
              ) : (
                <p className="m-0 text-sm text-temper-text-muted">Temper&apos;s default model.</p>
              )}
              <p className="m-0 mt-1 text-xs text-temper-text-muted">
                Every member uses these. Choosing per member comes later.
              </p>
            </section>
            <section className={cn(teamCard, 'p-4')}>
              <h2 className={teamLabel}>When you press Run project</h2>
              <ol className="m-0 flex list-decimal flex-col gap-1.5 pl-5 text-xs text-temper-text">
                <li>
                  Temper starts one run named <code className="font-mono">team-trial-…</code>; it shows in Workflows
                  too.
                </li>
                <li>Members take turns, ask each other for review and send work back.</li>
                <li>Temper asks you when the team pauses, has nothing to do, or a member needs you.</li>
                <li>You can message a member or stop the run at any time.</li>
              </ol>
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
}
