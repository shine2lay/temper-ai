import { cn } from '@/lib/utils';
import { isoOf, ownerActionWhat, shortId, teamSource, teamTime, teamTimeFull, teamWho } from '@/lib/teamText';
import type { TeamOwnerAction, TeamRun } from '@/types/team';
import { TeamWho } from '../TeamWho';
import { teamCard, teamLabel } from '../teamUi';

/** The unknown caller's label, as a sentence for the action it took. */
function unknownLabel(action: TeamOwnerAction): string {
  switch (action.kind) {
    case 'start':
      return 'Started by an unknown caller';
    case 'answer':
      return 'Answered by an unknown caller';
    case 'message':
      return 'Sent by an unknown caller';
    case 'stop':
      return 'Stopped by an unknown caller';
    default:
      return 'unknown caller';
  }
}

/**
 * Every action a person (or a caller) took on this trial: when, who, from
 * where, what it did and the request it came with. An unknown caller's row
 * stands out, never passing as yours.
 */
export function WhoDidWhat({ run }: { run: TeamRun }) {
  const th = 'pb-2 pr-4 text-left text-xs font-semibold text-temper-text-muted';
  return (
    <section aria-labelledby="team-actions-title" className={cn(teamCard, 'p-4')}>
      <h2 id="team-actions-title" className={teamLabel}>
        Who did what
      </h2>
      {run.owner_actions.length === 0 ? (
        <p className="m-0 text-sm text-temper-text-muted">Nothing yet.</p>
      ) : (
        // On a narrow screen the table scrolls sideways: the box takes the keyboard's focus so
        // the arrow keys can scroll it (WCAG 2.1.1; axe scrollable-region-focusable).
        <div className="overflow-x-auto" tabIndex={0} role="group" aria-label="Who did what, table">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                <th scope="col" className={th}>
                  When
                </th>
                <th scope="col" className={th}>
                  Who
                </th>
                <th scope="col" className={th}>
                  From
                </th>
                <th scope="col" className={th}>
                  What
                </th>
                <th scope="col" className={cn(th, 'pr-0')}>
                  Request
                </th>
              </tr>
            </thead>
            <tbody>
              {run.owner_actions.map((action, i) => {
                const unknown = teamWho(action.by).kind === 'unknown';
                const td = cn('border-t border-temper-border py-2 pr-4 align-middle', unknown && 'bg-[var(--team-unknown-bg)]');
                return (
                  <tr key={`${action.request_id ?? ''}:${i}`} data-unknown={unknown ? 'true' : undefined}>
                    <td className={cn(td, 'whitespace-nowrap text-xs text-temper-text-muted', unknown && 'pl-2')}>
                      <time dateTime={isoOf(action.at)} title={teamTimeFull(action.at) || undefined}>
                        {teamTime(action.at)}
                      </time>
                    </td>
                    <td className={td}>
                      <TeamWho by={action.by} unknownLabel={unknownLabel(action)} className="text-sm" />
                    </td>
                    <td className={cn(td, 'text-xs text-temper-text-muted')}>{teamSource(action.source).table}</td>
                    <td className={cn(td, 'text-xs text-temper-text')}>{ownerActionWhat(action, run)}</td>
                    <td className={cn(td, 'pr-0 font-mono text-xs text-temper-text-muted')}>
                      <span title={action.request_id ?? undefined}>{shortId(action.request_id)}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
