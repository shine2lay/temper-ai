import { useState } from 'react';
import { Check, FileText, RefreshCw, WifiOff, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { clockTime, formatNumber, readFailWords } from '@/lib/teamText';
import type { TeamListRead } from '@/hooks/useTeamLists';
import type { TeamRole, TeamRoles } from '@/types/team';
import { EngineQuote } from '../TeamQuote';
import { TeamNote } from '../TeamNote';
import { teamBtn } from '../teamUi';
import { RoleAboutSheet } from './RoleAboutSheet';

const TH = 'px-4 py-2.5 text-left text-xs font-semibold tracking-[0.06em] text-temper-text-muted uppercase';
const TD = 'px-4 py-3 align-top text-sm text-temper-text';

function TryButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" className={teamBtn.secondary} onClick={onClick}>
      <RefreshCw className="h-4 w-4" aria-hidden="true" />
      <span>{label}</span>
    </button>
  );
}

/** The table's head, kept while the list loads (board L3); column widths as board L1 draws them. */
function Head() {
  return (
    <thead className="border-b border-temper-border">
      <tr>
        <th scope="col" className={cn(TH, 'w-[14%]')}>
          Role
        </th>
        <th scope="col" className={cn(TH, 'w-[20%]')}>
          Title
        </th>
        <th scope="col" className={cn(TH, 'w-[36%]')}>
          Can join a team
        </th>
        <th scope="col" className={cn(TH, 'w-[18%]')}>
          Home chat
        </th>
        <th scope="col" className={TH}>
          <span className="sr-only">About page</span>
        </th>
      </tr>
    </thead>
  );
}

function RoleRow({ role, onAbout }: { role: TeamRole; onAbout: (role: TeamRole) => void }) {
  const problems = role.problems ?? [];
  const cant = problems.length > 0;
  return (
    <tr
      data-role-row={role.id}
      data-cant-join={cant || undefined}
      className={cn('border-b border-temper-border last:border-b-0', cant && 'bg-[var(--badge-failed-bg)]')}
    >
      <th scope="row" className={cn(TD, 'text-left font-mono text-[13px] font-normal break-all')}>
        {role.id}
      </th>
      <td className={cn(TD, 'break-words')}>{role.title || <span className="text-temper-text-muted">—</span>}</td>
      <td className={TD}>
        {cant ? (
          <>
            <span className="inline-flex items-center gap-1.5">
              <X className="h-4 w-4 shrink-0 text-[var(--badge-failed-text)]" aria-hidden="true" />
              Can&apos;t join
            </span>
            <ul className="m-0 mt-1 list-disc pl-5 text-xs text-temper-text">
              {problems.map((p, i) => (
                <li key={i} className="break-words">
                  {p}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <span className="inline-flex items-center gap-1.5">
            <Check className="h-4 w-4 shrink-0 text-[var(--badge-completed-text)]" aria-hidden="true" />
            Can join
          </span>
        )}
      </td>
      <td className={TD}>
        {role.has_home_chat ? (
          <span className="inline-flex items-center gap-1.5">
            <Check className="h-4 w-4 shrink-0 text-[var(--badge-completed-text)]" aria-hidden="true" />
            Yes
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5">
            <X className="h-4 w-4 shrink-0 text-[var(--badge-failed-text)]" aria-hidden="true" />
            No
          </span>
        )}
      </td>
      <td className={cn(TD, 'text-right')}>
        <button
          type="button"
          className={cn(teamBtn.ghostXs, 'text-sm')}
          onClick={() => onAbout(role)}
          aria-label={`About page: ${role.id}`}
        >
          <FileText className="h-4 w-4" aria-hidden="true" />
          <span>About page</span>
        </button>
      </td>
    </tr>
  );
}

/**
 * The Roles tab (SPEC 2, boards L1-L4 and S5): the box's role list, read
 * only. A role that can't join a team says why, word for word, one reason
 * per line. Not set up, loading and a failed read each say so.
 */
export function RolesTable({ read }: { read: TeamListRead<TeamRoles> }) {
  const [about, setAbout] = useState<TeamRole | null>(null);
  const { data } = read;

  if (!data) {
    if (read.error) {
      return (
        <TeamNote
          tone="bad"
          live
          title="Couldn't load the role list."
          action={<TryButton label="Try again" onClick={read.refresh} />}
        >
          <EngineQuote className="mt-1" label="Temper said:">
            {readFailWords(read.error)}
          </EngineQuote>
          <p className="m-0 mt-2 text-temper-text-muted">
            Nothing changed. The page tries again every 5 s while it is open.
          </p>
        </TeamNote>
      );
    }
    return (
      <div className="flex flex-col gap-2">
        <p role="status" className="m-0 text-xs text-temper-text-muted">
          Loading the role list…
        </p>
        <div className="overflow-hidden rounded-lg border border-temper-border bg-temper-panel">
          <table className="w-full border-collapse" aria-busy="true" aria-label="Roles">
            <Head />
          </table>
        </div>
      </div>
    );
  }

  if (!data.configured) {
    return (
      <TeamNote tone="warn" title="The role list isn't set up">
        {data.problem && (
          <EngineQuote className="mt-1" label="Temper said:">
            {data.problem}
          </EngineQuote>
        )}
        <p className="m-0 mt-2 text-temper-text-muted">
          No roles can join a team until it is. Trials can&apos;t start; the trials list still shows past trials.
        </p>
      </TeamNote>
    );
  }

  const roles = data.roles;
  const cant = roles.filter((r) => (r.problems ?? []).length > 0).length;
  return (
    <div className="flex flex-col gap-2">
      {read.failedAt !== null && (
        <TeamNote tone="warn" icon={WifiOff} live action={<TryButton label="Try now" onClick={read.refresh} />}>
          <b className="font-semibold">Couldn&apos;t refresh at {clockTime(read.failedAt)}.</b>{' '}
          <span className="text-temper-text-muted">
            Showing what Temper said at {read.updatedAt !== null ? clockTime(read.updatedAt) : 'the last read'}.
          </span>
        </TeamNote>
      )}
      <p className="m-0 text-xs text-temper-text-muted" data-testid="roles-summary">
        {formatNumber(roles.length)} {roles.length === 1 ? 'role' : 'roles'} from the box&apos;s role list
        {cant > 0 && <> · {formatNumber(cant)} can&apos;t join yet</>}. Read only: roles are made and changed in pi, not
        here.
      </p>
      <div className="overflow-x-auto rounded-lg border border-temper-border bg-temper-panel">
        <table className="w-full min-w-[720px] border-collapse" aria-label="Roles">
          <Head />
          <tbody>
            {roles.map((role) => (
              <RoleRow key={role.id} role={role} onAbout={setAbout} />
            ))}
          </tbody>
        </table>
      </div>
      <RoleAboutSheet role={about} onClose={() => setAbout(null)} />
    </div>
  );
}
