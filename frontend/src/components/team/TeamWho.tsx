import { Bot, ShieldAlert, User } from 'lucide-react';
import { cn } from '@/lib/utils';
import { teamWho } from '@/lib/teamText';

/**
 * Who did something: "You" (person icon), a named caller (bot icon and its
 * name) or an unknown caller (shield icon, red outline, bold), so an action
 * nobody can be named for always stands out.
 *
 * `unknownLabel` replaces "unknown caller" where the sentence needs it
 * ("Answered by an unknown caller" in Who did what).
 */
export function TeamWho({
  by,
  unknownLabel,
  className,
}: {
  by: string | null | undefined;
  unknownLabel?: string;
  className?: string;
}) {
  const who = teamWho(by);
  if (who.kind === 'unknown') {
    return (
      <span
        data-who="unknown"
        className={cn(
          'inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-bold',
          'bg-[var(--team-unknown-bg)] text-[var(--team-unknown-text)] border-[var(--team-unknown-border)]',
          className,
        )}
      >
        <ShieldAlert className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>{unknownLabel ?? who.label}</span>
      </span>
    );
  }
  const Icon = who.kind === 'owner' ? User : Bot;
  return (
    <span data-who={who.kind} className={cn('inline-flex items-center gap-1.5 font-semibold text-temper-text', className)}>
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span className="truncate">{who.label}</span>
    </span>
  );
}
