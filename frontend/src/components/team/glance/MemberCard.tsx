/**
 * One member, as real text: initial in a ring, name, role, leader tag, the
 * state chip (icon + word + how long), one line of what it is on, and its
 * turns and cost. The ring's style says the state too, so colour never works
 * alone.
 */
import { forwardRef } from 'react';
import { TriangleAlert } from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  conflictLine,
  memberChip,
  memberLine,
  toolsLine,
  turnsLine,
  type CardPhase,
  type GlanceMember,
} from '@/lib/teamGlance';
import { GIcon } from './glanceUi';
import { initialOf, ringAttr, toneText } from './glanceStyle';

export interface MemberCardProps {
  member: GlanceMember;
  /** The team phase, with whether its question to the owner is open (D88: a pause is yellow only then). */
  phase: CardPhase;
  /** Temper's clock (as_of), or null when no reply carried one. */
  now: number | null;
  /** The busy ring may turn (Animate on, no reduced motion, fresh data). */
  moving: boolean;
  /** The phone list's row (no card box, the chip on the right). */
  row?: boolean;
}

export const MemberCard = forwardRef<HTMLDivElement, MemberCardProps>(function MemberCard(
  { member: m, phase, now, moving, row = false },
  ref,
) {
  const chip = memberChip(m, phase, now);
  const line = memberLine(m, phase);
  const tools = toolsLine(m);
  const conflict = conflictLine(m);
  return (
    <div
      ref={ref}
      data-member={m.name}
      data-state={m.state}
      className={cn(
        'glance-card flex min-w-0 flex-col gap-1.5',
        // On the map the card fills its grid cell, so row-mates share the tallest one's height (D78).
        row ? 'py-3' : 'flex-1 rounded-lg border border-temper-border p-3',
        m.leader && !row && 'border-temper-control',
      )}
    >
      <div className="flex min-w-0 items-start gap-2.5">
        <span className={cn('glance-ring', chip.busy && moving && 'glance-busy')} {...ringAttr(chip.ring)} aria-hidden="true">
          {initialOf(m.name)}
          <span className="glance-pulse" data-pulse={m.name} />
        </span>
        <div className={cn('flex min-w-0 flex-1 gap-x-2 gap-y-1', row ? 'flex-wrap items-center justify-between' : 'flex-col')}>
          {/* SPEC 5: the name 17 px semibold, the role 15 px muted, the leader tag 14 px. */}
          <h3 className="m-0 flex min-w-0 flex-col text-[17px] leading-[1.25] text-temper-text">
            <span className="font-semibold break-words">{m.name}</span>
            {/* D51: role and leader tag on their own line under the name, no middot to orphan. */}
            {(m.role || m.leader) && (
              <span className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5" data-testid="glance-role">
                {m.role && <span className="text-[15px] leading-5 break-words text-temper-text-muted">{m.role}</span>}
                {m.leader && (
                  <span className="rounded-md border border-temper-control px-2 py-px text-sm leading-5 font-semibold whitespace-nowrap text-temper-text">
                    leader
                  </span>
                )}
              </span>
            )}
          </h3>
          {/* SPEC 5: the chip 15 px semibold, the On line 15 px. */}
          <p
            className={cn('m-0 flex min-w-0 items-center gap-1.5 text-[15px] font-semibold', toneText[chip.tone])}
            data-testid="glance-chip"
          >
            <GIcon name={chip.icon} />
            <span className="break-words">{chip.text}</span>
          </p>
        </div>
      </div>
      {line && (
        <p className="m-0 min-w-0 text-[15px] break-words text-temper-text" data-testid="glance-on">
          {line.label && <span className="text-temper-text-muted">{line.label} </span>}
          {line.text && (line.quoted ? <>&ldquo;{line.text}&rdquo;</> : line.text)}
          {/* D95: a ready member's waiting messages, after its words; no-break spaces keep "· 2 messages" whole (D69). */}
          {line.messages && <span data-testid="glance-on-messages">{line.text ? `\u00a0\u00b7\u00a0${line.messages}` : line.messages}</span>}
        </p>
      )}
      {conflict && (
        <p className="m-0 flex items-center gap-1.5 text-sm text-[var(--badge-waiting-text)]">
          <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{conflict}</span>
        </p>
      )}
      <p className="m-0 text-sm text-temper-text-muted break-words">
        {tools && (
          <>
            <span data-testid="glance-tools">{tools}</span> ·{' '}
          </>
        )}
        {turnsLine(m)}
      </p>
    </div>
  );
});
