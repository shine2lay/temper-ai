import { Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { memberAnchor, reservedHint, reservedWords, type FormMember } from '@/lib/teamForm';
import type { TeamFinding, TeamRole } from '@/types/team';
import { teamField } from '../teamUi';
import { FieldProblems } from './FormFindings';

const LABEL = 'mb-1 block text-sm font-semibold text-temper-text';

/** A role in the Role select: "<id>: <title>"; one that can't join says so and can't be picked. */
function roleOption(role: TeamRole): string {
  const cant = (role.problems ?? []).length > 0;
  return `${role.id}${role.title ? `: ${role.title}` : ''}${cant ? " (can't join)" : ''}`;
}

/**
 * One member row (boards F1-F3, S6): Role, Team name, Leader, remove, and
 * the tools. Bash can't be ticked while Temper says it is off; its reason
 * is in text under the rows. The row's problems sit at its foot.
 */
export function MemberRow({
  index,
  member,
  roles,
  reserved,
  tools,
  bashAllowed,
  leader,
  canRemove,
  disabled,
  problems,
  onRole,
  onName,
  onLeader,
  onTool,
  onRemove,
}: {
  index: number;
  member: FormMember;
  roles: readonly TeamRole[];
  reserved: readonly string[];
  tools: readonly string[];
  bashAllowed: boolean;
  leader: boolean;
  canRemove: boolean;
  disabled: boolean;
  problems: readonly TeamFinding[];
  onRole: (role: string) => void;
  onName: (name: string) => void;
  onLeader: () => void;
  onTool: (tool: string, on: boolean) => void;
  onRemove: () => void;
}) {
  const id = memberAnchor(member.key);
  const bad = problems.length > 0;
  const hint = reservedHint(member, reserved);
  const nameHelp = hint ? `${id}-reserved` : undefined;
  const problemIds = problems.map((_, i) => `${id}-problem-${i}`);
  return (
    <fieldset
      id={id}
      tabIndex={-1}
      data-member-row={member.key}
      data-bad={bad || undefined}
      aria-describedby={problemIds.length > 0 ? problemIds.join(' ') : undefined}
      className={cn(
        'm-0 min-w-0 rounded-lg border bg-temper-bg px-3 pt-3 pb-3',
        bad ? 'border-[var(--badge-failed-border)] border-2' : 'border-temper-border',
      )}
    >
      <legend className="sr-only">Member {index + 1}</legend>
      <div className="grid grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)_auto_auto] items-end gap-3">
        <div className="min-w-0">
          <label htmlFor={`${id}-role`} className={LABEL}>
            Role
          </label>
          <select
            id={`${id}-role`}
            value={member.role}
            disabled={disabled}
            onChange={(event) => onRole(event.target.value)}
            className={cn(teamField, 'min-h-10')}
          >
            <option value="">Pick a role</option>
            {roles.map((role) => (
              <option key={role.id} value={role.id} disabled={(role.problems ?? []).length > 0}>
                {roleOption(role)}
              </option>
            ))}
            {member.role !== '' && !roles.some((r) => r.id === member.role) && (
              <option value={member.role}>{member.role}</option>
            )}
          </select>
        </div>
        <div className="min-w-0">
          <label htmlFor={`${id}-name`} className={LABEL}>
            Team name
          </label>
          <input
            id={`${id}-name`}
            type="text"
            placeholder="give it a name"
            value={member.name}
            disabled={disabled}
            autoComplete="off"
            spellCheck={false}
            aria-describedby={nameHelp}
            onChange={(event) => onName(event.target.value)}
            className={cn(teamField, 'min-h-10')}
          />
        </div>
        <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 text-sm text-temper-text">
          <input
            type="radio"
            name="team-leader"
            checked={leader}
            disabled={disabled}
            onChange={onLeader}
            className="h-4 w-4 cursor-pointer rounded-full accent-temper-accent"
          />
          Leader
        </label>
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled || !canRemove}
          aria-label={`Remove member ${index + 1}`}
          title={canRemove ? `Remove member ${index + 1}` : 'A team needs at least one member'}
          className="inline-flex h-10 w-8 cursor-pointer items-center justify-center rounded-md border border-transparent bg-transparent text-temper-text-muted hover:bg-temper-surface hover:text-temper-text disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Trash2 className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      {hint && (
        <p id={`${id}-reserved`} className="m-0 mt-1.5 text-xs text-temper-text-muted">
          {reservedWords(member.role)}
        </p>
      )}
      <fieldset className="m-0 mt-2 flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 border-0 p-0">
        <legend className="float-left mr-1 p-0 text-xs text-temper-text-muted">Tools</legend>
        {tools.map((tool) => {
          const off = tool === 'Bash' && !bashAllowed;
          return (
            <label
              key={tool}
              className={cn(
                'inline-flex min-h-6 items-center gap-1.5 text-sm',
                off ? 'cursor-not-allowed text-temper-text-muted line-through' : 'cursor-pointer text-temper-text',
              )}
            >
              <input
                type="checkbox"
                checked={!off && member.tools.includes(tool)}
                disabled={disabled || off}
                aria-describedby={off ? 'team-bash-why' : undefined}
                onChange={(event) => onTool(tool, event.target.checked)}
                className="h-4 w-4 cursor-pointer accent-temper-accent disabled:cursor-not-allowed"
              />
              {tool}
            </label>
          );
        })}
      </fieldset>
      <FieldProblems id={id} problems={problems} className="mt-2" />
    </fieldset>
  );
}
