import { Link } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { cn } from '@/lib/utils';
import { clockTime, formatNumber } from '@/lib/teamText';
import { teamBtn, teamLink } from './teamUi';

export type TeamTab = 'trials' | 'roles';

const TABS: Array<{ id: TeamTab; label: string; to: string }> = [
  { id: 'trials', label: 'Trials', to: '/team' },
  { id: 'roles', label: 'Roles', to: '/team/roles' },
];

/** "Updated 10:42:05 AM", and " · not current" while the last read failed (boards T1, T3). */
function Updated({ at, stale }: { at: number | null | undefined; stale?: boolean }) {
  if (at === null || at === undefined) return null;
  return (
    <p className="m-0 text-xs text-temper-text-muted" data-testid="team-updated">
      Updated {clockTime(at)}
      {stale && <> · not current</>}
    </p>
  );
}

/**
 * The Team page's header (the Workflows page pattern) and its two tabs,
 * each with its count once it is known. `tab` null is the New trial page:
 * a breadcrumb back to Team instead of the tabs (board F1).
 */
export function TeamPageHeader({
  tab,
  counts,
  updatedAt,
  stale,
}: {
  tab: TeamTab | null;
  counts?: Partial<Record<TeamTab, number | null>>;
  updatedAt?: number | null;
  stale?: boolean;
}) {
  if (tab === null) {
    return (
      <header className="flex flex-wrap items-end gap-x-4 gap-y-1 px-6 pt-3 pb-3">
        <div className="flex min-w-0 flex-col">
          <nav aria-label="Breadcrumb" className="text-xs text-temper-text-muted">
            <ol className="m-0 flex list-none items-center gap-1.5 p-0">
              <li>
                <Link to="/team" className={teamLink}>
                  Team
                </Link>
              </li>
              <li aria-hidden="true">/</li>
              <li aria-current="page">New trial</li>
            </ol>
          </nav>
          <h1 className="m-0 text-xl font-semibold text-temper-text">New trial</h1>
        </div>
        <span className="flex-1" />
        <Updated at={updatedAt} stale={stale} />
      </header>
    );
  }
  return (
    <>
      <header className="flex flex-wrap items-center gap-4 px-6 pt-4 pb-3">
        <h1 className="m-0 text-xl font-semibold text-temper-text">Team</h1>
        <span className="text-xs text-temper-text-muted">pi roles working together on one goal</span>
        <span className="flex-1" />
        <Updated at={updatedAt} stale={stale} />
        <Link to="/team/new" className={teamBtn.primary}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          <span>New trial</span>
        </Link>
      </header>
      <nav aria-label="Team" className="flex gap-1 border-b border-temper-border px-6">
        {TABS.map((t) => {
          const on = t.id === tab;
          const count = counts?.[t.id];
          return (
            <Link
              key={t.id}
              to={t.to}
              aria-current={on ? 'page' : undefined}
              className={cn(
                '-mb-px inline-flex min-h-10 items-center gap-2 border-b-2 px-3 py-2 text-sm no-underline transition-colors',
                on
                  ? 'border-temper-accent font-semibold text-temper-text'
                  : 'border-transparent text-temper-text-muted hover:text-temper-text',
              )}
            >
              {t.label}
              {/* A space, so a screen reader says "Trials 4", not "Trials4". */}
              {count !== null && count !== undefined && ' '}
              {count !== null && count !== undefined && (
                <span data-tab-count="" className="text-xs font-normal text-temper-text-muted">
                  {formatNumber(count)}
                </span>
              )}
            </Link>
          );
        })}
      </nav>
    </>
  );
}
