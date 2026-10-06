import type { LucideIcon } from 'lucide-react';
import { CircleDot, CircleStop, Crown, Hand, LoaderCircle, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { teamCost } from '@/lib/teamText';
import type { TeamMember, TeamRun } from '@/types/team';
import { teamCard, teamChip, teamChipTone, teamLabel } from '../teamUi';

const ACTIVITY: Record<string, { word: string; tone: keyof typeof teamChipTone; Icon: LucideIcon }> = {
  working: { word: 'Working', tone: 'running', Icon: LoaderCircle },
  idle: { word: 'Idle', tone: 'neutral', Icon: CircleDot },
  waiting_on_owner: { word: 'Waiting on you', tone: 'waiting', Icon: Hand },
  ended: { word: 'Ended', tone: 'neutral', Icon: CircleStop },
  failed: { word: 'Failed', tone: 'failed', Icon: X },
};

function ActivityChip({ activity }: { activity: string }) {
  const a = ACTIVITY[activity];
  if (!a) {
    return (
      <span className={cn(teamChip, teamChipTone.neutral)}>
        <span>{activity.replace(/_/g, ' ')}</span>
      </span>
    );
  }
  return (
    <span data-activity={activity} className={cn(teamChip, teamChipTone[a.tone])}>
      <a.Icon className="h-3.5 w-3.5" aria-hidden="true" />
      <span>{a.word}</span>
    </span>
  );
}

/**
 * Turns, cost, the model and thinking it was asked to run on, what its turns really used
 * when that differs (the turn receipts' words, "unknown" included), and its tools.
 */
function MemberLine({ member, tools }: { member: TeamMember; tools: string[] | undefined }) {
  const asked = [
    `${member.turns} ${member.turns === 1 ? 'turn' : 'turns'}`,
    teamCost(member.cost_usd),
    member.model,
    member.thinking,
  ].filter((p): p is string => Boolean(p));
  const used = member.effective;
  const differs = used && (used.model !== member.model || used.thinking !== member.thinking);
  const toolList = tools && tools.length > 0 ? tools.join(', ') : null;
  return (
    <p className="m-0 mt-1 text-xs text-temper-text-muted break-words">
      {asked.join(' · ')}
      {differs && (
        <>
          {' '}
          <span className="font-semibold text-temper-text">
            used {[used.model, used.thinking].filter(Boolean).join(' · ')}
          </span>
        </>
      )}
      {toolList && ` · ${toolList}`}
    </p>
  );
}

/** Every member: name, the leader's mark, what it is doing, and its numbers. */
export function MembersCard({ run }: { run: TeamRun }) {
  const tools = new Map(run.trial.members.map((m) => [m.name, m.tools]));
  return (
    <section aria-labelledby="team-members-title" className={cn(teamCard, 'p-4')}>
      <h2 id="team-members-title" className={teamLabel}>
        Members ({run.members.length})
      </h2>
      <ul className="m-0 list-none p-0">
        {run.members.map((member) => (
          <li key={member.name} className="border-t border-temper-border py-2 first:border-t-0 first:pt-0">
            <div className="flex items-center gap-2">
              <b className="min-w-0 max-w-[220px] truncate text-sm font-semibold text-temper-text" title={member.name}>
                {member.name}
              </b>
              {member.role && member.role !== member.name && (
                <span className="shrink-0 text-sm text-temper-text-muted">{member.role}</span>
              )}
              {member.leader && (
                <span className={cn(teamChip, teamChipTone.neutral)}>
                  <Crown className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>leader</span>
                </span>
              )}
              <span className="flex-1" />
              <ActivityChip activity={member.activity} />
            </div>
            <MemberLine member={member} tools={tools.get(member.name)} />
            {member.last_turn?.state === 'failed' && member.last_turn.error && (
              <p className="m-0 mt-1 flex gap-1.5 text-xs text-[var(--badge-failed-text)] break-words">
                <X className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span className="min-w-0">
                  turn {member.last_turn.turn_no}: {member.last_turn.error}
                </span>
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
