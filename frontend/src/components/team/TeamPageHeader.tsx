import { Link } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { cn } from '@/lib/utils';
import { teamBtn } from './teamUi';

export type TeamTab = 'trials' | 'roles';

const TABS: Array<{ id: TeamTab; label: string; to: string }> = [
  { id: 'trials', label: 'Trials', to: '/team' },
  { id: 'roles', label: 'Roles', to: '/team/roles' },
];

/**
 * The Team page's header (the Workflows page pattern) and its two tabs.
 * `tab` is the open one; none is marked on the New trial page.
 */
export function TeamPageHeader({ tab }: { tab: TeamTab | null }) {
  return (
    <>
      <header className="flex flex-wrap items-center gap-4 px-6 pt-4 pb-3">
        <h1 className="m-0 text-xl font-semibold text-temper-text">Team</h1>
        <span className="text-xs text-temper-text-muted">pi roles working together on one goal</span>
        <span className="flex-1" />
        <Link to="/team/new" className={teamBtn.primary}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          <span>New trial</span>
        </Link>
      </header>
      <nav aria-label="Team" className="flex gap-1 border-b border-temper-border px-6">
        {TABS.map((t) => {
          const on = t.id === tab;
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
            </Link>
          );
        })}
      </nav>
    </>
  );
}
