import { cn } from '@/lib/utils';
import { decisionWords } from '@/lib/teamText';
import type { TeamRun } from '@/types/team';
import { teamCard, teamLabel } from '../teamUi';
import { VerdictChip } from './Timeline';

/** At most this many segments are drawn; the words always carry the numbers. */
const MAX_SEGMENTS = 12;

/**
 * The round the team is on: how many rounds have gone by without done
 * (the team pauses for you when it reaches the limit), and the latest
 * review with every member's view and the leader's decision.
 */
export function RoundCard({ run }: { run: TeamRun }) {
  const { round, reviews, trial } = run;
  if (round.current < 1 && reviews.length === 0) return null;

  const limit = round.pause_after_rounds || trial.pause_after_rounds;
  const without = round.keep_goings;
  const segments = limit > 0 && limit <= MAX_SEGMENTS ? limit : 0;
  const latest = reviews.reduce<(typeof reviews)[number] | null>(
    (best, r) => (best === null || r.round >= best.round ? r : best),
    null,
  );
  const meterWords = `${without} of ${limit} rounds without done`;

  return (
    <section aria-labelledby="team-round-title" className={cn(teamCard, 'p-4')}>
      <h2 id="team-round-title" className={teamLabel}>
        Round {Math.max(round.current, 1)}
      </h2>
      {segments > 0 && (
        <div role="img" aria-label={meterWords} className="mb-2 flex gap-1.5">
          {Array.from({ length: segments }, (_, i) => (
            <span
              key={i}
              className={cn(
                'h-2 w-10 rounded border',
                i < without ? 'border-temper-waiting bg-temper-waiting' : 'border-temper-control',
              )}
            />
          ))}
        </div>
      )}
      <p className="m-0 text-xs text-temper-text">
        <b className="font-semibold">
          {without} of {limit}
        </b>{' '}
        rounds without done <span className="text-temper-text-muted">· the team pauses for you at {limit}</span>
      </p>
      {latest && (
        <>
          <div className="my-3 border-t border-temper-border" />
          <p className="m-0 text-xs text-temper-text">
            <b className="font-semibold">Latest review</b>{' '}
            <span className="text-temper-text-muted">· round {latest.round}</span>
            {latest.commit && (
              <>
                {' '}
                <span className="text-temper-text-muted">· commit</span>{' '}
                <span className="font-mono">{latest.commit.slice(0, 7)}</span>
              </>
            )}
            {latest.files_count != null && (
              <span className="text-temper-text-muted">
                {' '}
                · {latest.files_count} {latest.files_count === 1 ? 'file' : 'files'}
              </span>
            )}
          </p>
          {Object.keys(latest.views).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(latest.views).map(([member, view]) => (
                <VerdictChip key={member} verdict={view.verdict} label={`${member}: ${view.verdict.replace(/_/g, ' ')}`} />
              ))}
            </div>
          )}
          {latest.refusal ? (
            <p className="m-0 mt-2 text-xs text-temper-text-muted">{trial.leader} said done; refused</p>
          ) : (
            latest.decision && (
              <p className="m-0 mt-2 text-xs text-temper-text">
                <span className="text-temper-text-muted">{trial.leader} decided:</span>{' '}
                <b className="font-semibold">{decisionWords(latest.decision)}</b>
              </p>
            )
          )}
        </>
      )}
    </section>
  );
}
