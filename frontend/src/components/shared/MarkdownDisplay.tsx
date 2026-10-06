import { cn } from '@/lib/utils';
import { SafeMarkdown } from './SafeMarkdown';

interface MarkdownDisplayProps {
  content: string;
  className?: string;
  /** When set, the prose scrolls inside its own box instead of growing. */
  maxHeight?: number;
}

export function MarkdownDisplay({ content, className, maxHeight }: MarkdownDisplayProps) {
  return (
    <div
      style={maxHeight != null ? { maxHeight } : undefined}
      className={cn(
        maxHeight != null && 'overflow-auto',
        'rounded-md bg-temper-panel p-4 text-sm text-temper-text',
        'border border-temper-border prose dark:prose-invert prose-sm max-w-none',
        'prose-headings:text-temper-text prose-p:text-temper-text prose-li:text-temper-text',
        'prose-strong:text-temper-text prose-code:text-temper-accent prose-code:text-xs',
        'prose-pre:bg-temper-surface prose-pre:border prose-pre:border-temper-border',
        className,
      )}
    >
      <SafeMarkdown content={content} gfm />
    </div>
  );
}
