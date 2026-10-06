/**
 * What the timeline needs beyond the words of one entry: the title of the
 * wait an entry stands for and when an entry happened. Both read the same
 * helpers as the cards beside it, so the timeline can't say something
 * different from them.
 */
import { waitTitle } from '@/lib/teamText';
import { teamStopper } from '@/lib/teamOutcome';
import type { TeamEntry, TeamOtherEntry, TeamOwnerAction, TeamOwnerWaitEntry, TeamRun } from '@/types/team';

type AnyEntry = TeamEntry | TeamOtherEntry;

/**
 * The title of the wait an owner_wait entry stands for, through waitTitle
 * as the needs-you card does: an open wait's own title, word for word; a
 * closed one from the entry's kind, round, member and turn. Never the wait
 * id or Temper's name for the question.
 */
export function waitEntryTitle(entry: TeamOwnerWaitEntry, run: Pick<TeamRun, 'open_waits'>): string {
  const open = run.open_waits.find((w) => w.wait_id === entry.data.wait_id);
  if (open) return waitTitle(open);
  return waitTitle({
    kind: entry.wait_kind,
    round: entry.data.round ?? entry.round ?? null,
    member: entry.data.member ?? null,
    turn_no: entry.data.turn_no ?? null,
  });
}

/** Is this the entry Temper adds when the team was stopped at a question? */
export function isStoppedEntry(entry: AnyEntry): boolean {
  return entry.entry === 'decision' && (entry as { decision?: string }).decision === 'stopped';
}

function latest(actions: TeamOwnerAction[], match: (a: TeamOwnerAction) => boolean): string | null {
  for (let i = actions.length - 1; i >= 0; i--) {
    if (match(actions[i])) return actions[i].at;
  }
  return null;
}

/**
 * When an entry happened, or null when Temper sent no time for it (the
 * page then shows none, never a made-up one):
 * - the "stopped the team" entry: the stopping action's time, as the
 *   outcome card shows it (teamStopper). Temper's own entry has none.
 * - any other entry: its own time, else, for an owner's answer or
 *   message, the time of the owner action that records it.
 */
export function entryTime(entry: AnyEntry, run: Pick<TeamRun, 'owner_actions' | 'outcome'>): string | null {
  if (isStoppedEntry(entry)) return teamStopper(run).at ?? entry.timestamp ?? null;
  if (entry.timestamp) return entry.timestamp;
  const data = (entry.data ?? {}) as { wait_id?: string; answer?: string; message_id?: string; request_id?: string };
  if (entry.entry === 'owner_answer') {
    const requestId = (entry as { request_id?: string | null }).request_id ?? data.request_id ?? null;
    if (requestId) {
      const at = latest(run.owner_actions, (a) => a.kind === 'answer' && a.request_id === requestId);
      if (at) return at;
    }
    return latest(
      run.owner_actions,
      (a) => a.kind === 'answer' && a.detail?.wait_id === data.wait_id && a.detail?.answer === data.answer,
    );
  }
  if (entry.entry === 'message' && entry.from_agent === 'owner' && data.message_id) {
    return latest(run.owner_actions, (a) => a.kind === 'message' && a.detail?.message_id === data.message_id);
  }
  return null;
}
