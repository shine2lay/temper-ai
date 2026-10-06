import { cn } from '@/lib/utils';
import { charCount } from '@/lib/teamText';

/**
 * "<n> / <limit>" under a text field, counted as the server counts
 * (characters, not bytes). Over the limit it says by how much, in the
 * failed colour; the send button stays enabled so the server's own refusal
 * can be shown.
 */
export function TeamCharCount({ text, limit, id, className }: { text: string; limit: number; id?: string; className?: string }) {
  const { over, label } = charCount(text, limit);
  return (
    <span
      id={id}
      data-over={over > 0 ? 'true' : 'false'}
      className={cn(
        'text-xs tabular-nums',
        over > 0 ? 'font-semibold text-[var(--badge-failed-text)]' : 'text-temper-text-muted',
        className,
      )}
    >
      {label}
    </span>
  );
}
