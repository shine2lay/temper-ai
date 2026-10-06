import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { ownerWordsLabel, teamWho } from '@/lib/teamText';

/**
 * Temper's own words (a reason, a question), word for word, in a quote with
 * a bar on the left. Shown as plain text: these strings come from the
 * engine and from members, so they are never rendered as HTML.
 */
export function EngineQuote({
  label,
  children,
  className,
  labelClassName,
}: {
  label?: ReactNode;
  children: string;
  className?: string;
  /** Extra classes for the label, e.g. the outcome card's capitals. */
  labelClassName?: string;
}) {
  return (
    <figure data-quote="engine" className={cn('m-0', className)}>
      {label && (
        <figcaption className={cn('mb-1 text-xs font-semibold text-temper-text-muted', labelClassName)}>{label}</figcaption>
      )}
      <blockquote className="m-0 border-l-[3px] border-temper-control py-1 pl-3 text-sm text-temper-text whitespace-pre-wrap break-words">
        {children}
      </blockquote>
    </figure>
  );
}

/**
 * The words a person sent with an action, kept apart from Temper's: its own
 * quote, its own label ("Your words", "temper-ci's words", "Words from an
 * unknown caller"), and the unknown caller's red bar.
 */
export function OwnerWords({
  by,
  words,
  className,
  labelClassName,
}: {
  by: string | null | undefined;
  words: string;
  className?: string;
  /** Extra classes for the label, e.g. the outcome card's capitals. */
  labelClassName?: string;
}) {
  const unknown = teamWho(by).kind === 'unknown';
  return (
    <figure data-quote="owner" className={cn('m-0', className)}>
      <figcaption
        className={cn(
          'mb-1 text-xs font-semibold',
          unknown ? 'text-[var(--team-unknown-text)]' : 'text-temper-text-muted',
          labelClassName,
        )}
      >
        {ownerWordsLabel(by)}
      </figcaption>
      <blockquote
        className={cn(
          'm-0 border-l-[3px] py-1 pl-3 text-sm text-temper-text whitespace-pre-wrap break-words',
          unknown ? 'border-[var(--team-unknown-border)]' : 'border-temper-control',
        )}
      >
        {words}
      </blockquote>
    </figure>
  );
}
