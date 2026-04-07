/**
 * ThinkingContent — renders text that may contain <think>...</think> blocks.
 * Thinking blocks get distinct violet styling. Content outside thinking blocks
 * is rendered via a provided render function or as plain text.
 *
 * Works with both complete and streaming content (handles unclosed <think> tags).
 */
import { cn } from '@/lib/utils';

interface ThinkingContentProps {
  content: string;
  className?: string;
  /** Render function for non-thinking content. Defaults to plain <span>. */
  renderContent?: (text: string, key: number) => React.ReactNode;
}

interface Segment {
  type: 'text' | 'thinking';
  content: string;
}

function parseThinkingBlocks(content: string): Segment[] {
  const segments: Segment[] = [];
  let i = 0;
  let current = '';
  let inThink = false;

  while (i < content.length) {
    if (!inThink && content.startsWith('<think>', i)) {
      if (current) segments.push({ type: 'text', content: current });
      current = '';
      inThink = true;
      i += 7;
      continue;
    }
    if (inThink && content.startsWith('</think>', i)) {
      if (current) segments.push({ type: 'thinking', content: current });
      current = '';
      inThink = false;
      i += 8;
      continue;
    }
    current += content[i];
    i++;
  }

  if (current) {
    segments.push({ type: inThink ? 'thinking' : 'text', content: current });
  }

  return segments;
}

export function ThinkingContent({ content, className, renderContent }: ThinkingContentProps) {
  if (!content) return null;

  // Fast path: no <think> tags at all
  if (!content.includes('<think>')) {
    return <>{renderContent ? renderContent(content, 0) : <span className={className}>{content}</span>}</>;
  }

  const segments = parseThinkingBlocks(content);

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

/** Strip <think>...</think> tags from content, returning just the non-thinking text. */
export function stripThinkingTags(content: string): string {
  return content.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
}
