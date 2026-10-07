/**
 * The words of an ended team run (Design's spec, section 5.4): the outcome
 * card's title, who stopped it, and why the run list's status may differ
 * from the page's state.
 *
 * On an ended run the run list's status is read from `run_status`, never
 * guessed from the kind of question the team was stopped at. As Temper
 * records it today, a stop at a pause, a stop when the team is quiet and
 * Stop run all leave the run cancelled, and a stop at a member's failed or
 * unfinished turn leaves it failed. The words are Design's (spec 5.4, 5.8).
 */
import type { TeamOwnerAction, TeamRun, TeamWait } from '@/types/team';
import { teamStateWord } from '@/lib/teamText';

/** The outcome card's title. */
export function outcomeTitle(state: string): string {
  switch (state) {
    case 'done':
      return "Done: the leader's version was approved";
    case 'stopped':
      return 'Stopped';
    case 'failed':
      return 'Failed';
    case 'didnt_start':
      return "Didn't start";
    default:
      return teamStateWord(state);
  }
}

/**
 * The owner action that stopped the team: Stop run for a cancelled run,
 * the answer "stop" for a team stopped at a question. The latest one wins.
 * Before the outcome is written, only an answer "stop" can have stopped
 * the team (Stop run leaves no stopped entry to explain).
 */
export function stopAction(run: Pick<TeamRun, 'owner_actions' | 'outcome'>): TeamOwnerAction | null {
  const decision = run.outcome?.decision ?? 'stopped';
  for (let i = run.owner_actions.length - 1; i >= 0; i--) {
    const action = run.owner_actions[i];
    if (decision === 'cancelled' && action.kind === 'stop') return action;
    if (decision === 'stopped' && action.kind === 'answer' && action.detail?.answer === 'stop') return action;
  }
  return null;
}

/** Who stopped the team, from where, and when. */
export interface TeamStopper {
  /** The owner action that stopped it, when Temper recorded one. */
  action: TeamOwnerAction | null;
  by: string | null;
  source: string | null;
  at: string | null;
}

/**
 * Who stopped the team, from where and when: the stopping owner action
 * (its by, source and time), else the outcome's own by and time. The
 * outcome card's "Stopped by" line and the timeline's "stopped the team"
 * row both read this, so the two always agree. The engine's own stopped
 * entry is never read for it: that entry always names the owner and has
 * no time.
 */
export function teamStopper(run: Pick<TeamRun, 'owner_actions' | 'outcome'>): TeamStopper {
  const action = stopAction(run);
  return {
    action,
    by: action?.by ?? run.outcome?.by ?? null,
    source: action?.source ?? null,
    at: action?.at ?? run.outcome?.at ?? null,
  };
}

/**
 * Why the run list says failed while the page says Stopped. Picked from
 * the run's own status: a stopped team whose run reads cancelled needs no
 * note, as both lists say the same.
 */
export function runListExplanation(run: Pick<TeamRun, 'run_status' | 'outcome' | 'state'>): string | null {
  if (run.state !== 'stopped' || !run.outcome) return null;
  if (run.run_status === 'failed') {
    return "Why the run list says failed: Temper records a team stopped at a member's failed or unfinished turn as failed. Here the stop was a choice, not a crash: who stopped it and why are on the left.";
  }
  return null;
}

/**
 * The stop-answer confirm's run-list sentence, by the kind of question
 * being answered. Null for a kind Design hasn't worded yet: the confirm
 * then says only that the team ends.
 */
export function stopAnswerRunList(kind: TeamWait['kind']): string | null {
  switch (kind) {
    case 'pause':
    case 'stalled':
      return "The run list will show this run as cancelled, like Stop run. This page shows Stopped, with Temper's reason and your words.";
    case 'recovery':
      return "The run list will show this run as failed: Temper records a stop at a member's failed or unfinished turn as failed. This page shows Stopped, with Temper's reason and your words.";
    case 'settings':
      return 'The run list will show this run as cancelled, like Stop run.';
    default:
      return null;
  }
}

/** The confirm's title and its first "What happens" line, by the kind of question (O1c, O1e). */
export function stopAnswerWords(kind: TeamWait['kind']): { title: string; ends: string } {
  if (kind === 'settings') {
    return {
      title: 'Stop the team at the settings check?',
      ends: 'The team ends here, before anything runs with the new settings. Your last answer is not applied, and nothing more is spent.',
    };
  }
  return { title: 'Stop the team at this question?', ends: 'The team ends here and nothing more is spent.' };
}

/** A problem as Temper wrote it: a string, or an object's own words. */
export function problemText(problem: unknown): string {
  if (typeof problem === 'string') return problem;
  if (problem && typeof problem === 'object') {
    const p = problem as { problem?: unknown; message?: unknown; detail?: unknown };
    for (const value of [p.problem, p.message, p.detail]) {
      if (typeof value === 'string' && value) return value;
    }
    return JSON.stringify(problem);
  }
  return String(problem);
}

/** The branch line of a done outcome. */
export function branchWords(
  branch: { name: string; made: boolean; why: string | null } | null | undefined,
  project: string | null,
): { kind: 'made' | 'not_made' | 'none'; words: string } {
  if (!branch) {
    return {
      kind: 'none',
      words: 'No branch: this project started from an empty project. Getting its files out comes later.',
    };
  }
  if (branch.made) {
    return {
      kind: 'made',
      words: `${branch.name}${project ? ` in ${project}` : ''}, at the approved commit (a local branch)`,
    };
  }
  return {
    kind: 'not_made',
    words: `branch not made: ${branch.why || 'no reason given'} · the approved commit stays fetchable from Temper's kept copy.`,
  };
}

/** The last part of a project path: "notes-app" for /srv/example/projects/notes-app. */
export function projectName(source: string): string {
  const parts = source.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? source;
}
