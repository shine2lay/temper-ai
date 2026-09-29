/**
 * ThinkingContent — renders text that may contain thinking blocks, written
 * `<think>...</think>` by most models and `<thinking>...</thinking>` by the
 * Claude Code provider. Thinking blocks get distinct violet styling. Content
 * outside thinking blocks is rendered via a provided render function or as
 * plain text.
 *
 * Works with both complete and streaming content (handles unclosed tags).
 */
import { cn } from '@/lib/utils';
import { hasThinkingTags, parseStreamText } from '@/lib/streamSegments';

interface ThinkingContentProps {
  content: string;
  className?: string;
  /** Render function for non-thinking content. Defaults to plain <span>. */
  renderContent?: (text: string, key: number) => React.ReactNode;
}

export function ThinkingContent({ content, className, renderContent }: ThinkingContentProps) {
  if (!content) return null;

  // Fast path: no thinking tags at all
  if (!hasThinkingTags(content)) {
    return <>{renderContent ? renderContent(content, 0) : <span className={className}>{content}</span>}</>;
  }

  const segments = parseStreamText(content);

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      {segments.map((seg, i) => {
        if (seg.type === 'thinking') {
          return (
            <div key={i} className="px-3 py-2 rounded bg-violet-500/10 border-l-2 border-violet-500/40">
              <span className="text-[9px] text-violet-400 font-medium block mb-1">thinking</span>
              <div className="text-violet-300/70 whitespace-pre-wrap text-xs">{seg.content}</div>
            </div>
          );
        }
        return renderContent
          ? <div key={i}>{renderContent(seg.content, i)}</div>
          : <span key={i} className="whitespace-pre-wrap">{seg.content}</span>;
      })}
    </div>
  );
}
