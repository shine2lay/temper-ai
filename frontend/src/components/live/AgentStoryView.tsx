/**
 * One agent's story, told in order: what it thought, what it wrote, and
 * every step it took.
 *
 * Thinking is kept whole — the newest is open while it streams, older
 * thinking folds to a line. A tool step is one line in plain words; open it
 * to see what it was given and what came back. Anything that failed is red.
 */
import { memo, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Check, ChevronRight, X } from 'lucide-react';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import { JsonViewer } from '@/components/shared/JsonViewer';
import { parseStreamText } from '@/lib/streamSegments';
import { toolStepLabel } from '@/lib/toolLabels';
import { cn, formatDuration } from '@/lib/utils';
import type { StoryItem, StoryTool } from '@/lib/agentStory';

/** Steps shown at first: the latest part of a long story. */
export const WINDOW = 40;

interface AgentStoryViewProps {
  items: StoryItem[];
  /** The agent is still working: keep the view at the newest words. */
  live: boolean;
}

/**
 * Render one agent's story. Mount it with `key={agentId}`: a different agent
 * is a different story, and starts with its own window on it.
 */
export function AgentStoryView({ items, live }: AgentStoryViewProps) {
  const [limit, setLimit] = useState(WINDOW);
  const scrollRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);

  const shown = useMemo(
    () => (items.length > limit ? items.slice(items.length - limit) : items),
    [items, limit],
  );
  const hidden = items.length - shown.length;

  // The newest unfinished thinking is the one that stays open.
  const openThinkingId = useMemo(() => {
    for (let i = items.length - 1; i >= 0; i--) {
      const item = items[i];
      if (item.kind === 'thinking') return item.closed ? null : item.id;
      if (item.kind === 'text' && !item.closed) return null;
    }
    return null;
  }, [items]);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight;
  });

  if (items.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-xs text-temper-text-dim">
        {live ? 'Waiting for this agent to say something…' : 'Nothing recorded for this agent.'}
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      data-testid="agent-story"
      onScroll={() => {
        const el = scrollRef.current;
        if (el) atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      }}
      className="h-full overflow-y-auto px-3 py-2"
    >
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setLimit((l) => l + WINDOW * 2)}
          className="mb-2 w-full rounded border border-temper-border bg-temper-surface/60 px-2 py-1 text-[11px] text-temper-text-muted hover:text-temper-text"
        >
          Show earlier ({hidden} more)
        </button>
      )}
      <div className="flex flex-col gap-1.5">
        {shown.map((item) => (
          <StoryRow key={item.id} item={item} openThinking={item.id === openThinkingId} />
        ))}
      </div>
    </div>
  );
}

const StoryRow = memo(function StoryRow({
  item,
  openThinking,
}: {
  item: StoryItem;
  openThinking: boolean;
}) {
  if (item.kind === 'thinking') return <Thinking text={item.text} open={openThinking} />;
  if (item.kind === 'tool') return <ToolStep step={item} />;
  return <Text text={item.text} />;
});

/** Model text. Old runs put thinking and tool lines inside it; split those out. */
function Text({ text }: { text: string }) {
  const segments = useMemo(() => parseStreamText(text, { toolLines: true }), [text]);
  return (
    <>
      {segments.map((seg, i) => {
        if (seg.type === 'thinking') return <Thinking key={i} text={seg.content} open={false} />;
        if (seg.type === 'tool_call') {
          return (
            <div key={i} className="font-mono text-[11px] text-temper-text-muted">
              {seg.content}
            </div>
          );
        }
        return (
          <div key={i} data-testid="story-text" className="text-xs leading-relaxed text-temper-text">
            <MarkdownDisplay content={seg.content} />
          </div>
        );
      })}
    </>
  );
}

function firstLine(text: string, max = 90): string {
  const line = text.replace(/\s+/g, ' ').trim();
  return line.length > max ? `${line.slice(0, max - 1)}…` : line;
}

function Thinking({ text, open }: { text: string; open: boolean }) {
  // Open while it streams, folded once it is done \u2014 unless the reader has said
  // otherwise, in which case their choice stands.
  const [chosen, setChosen] = useState<boolean | null>(null);
  const expanded = chosen ?? open;
  const setExpanded = (next: boolean | ((was: boolean) => boolean)) =>
    setChosen(typeof next === 'function' ? next(expanded) : next);

  if (!text.trim()) return null;

  return (
    <div
      className="rounded border-l-2 border-violet-500/40 bg-violet-500/10 px-2 py-1"
      data-testid="story-thinking"
    >
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center gap-1 text-left text-[9px] font-medium text-violet-700 dark:text-violet-400"
      >
        <ChevronRight className={cn('size-3 transition-transform', expanded && 'rotate-90')} />
        thinking
        {!expanded && (
          <span className="truncate font-normal text-violet-700/70 dark:text-violet-300/60">· {firstLine(text)}</span>
        )}
      </button>
      {/* Violet says thinking in both themes: pale violet on the dark
          background, and a dark violet on the light one, where the pale one
          was there but could not be read. */}
      {expanded && (
        <div className="mt-1 whitespace-pre-wrap text-[11px] leading-relaxed text-violet-900 dark:text-violet-300/80">
          {text}
        </div>
      )}
    </div>
  );
}

function ToolStep({ step }: { step: StoryTool }) {
  const [open, setOpen] = useState(false);
  const label = toolStepLabel(step.toolName, step.args);
  const failed = step.status === 'failed';

  return (
    <div data-testid="story-tool">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left text-[11px] hover:bg-temper-surface/50',
          failed ? 'text-red-400' : 'text-temper-text-muted',
        )}
      >
        {step.status === 'running' ? (
          <span className="size-3 shrink-0 animate-pulse rounded-full bg-temper-running/70" />
        ) : failed ? (
          <X className="size-3 shrink-0 text-red-400" />
        ) : (
          <Check className="size-3 shrink-0 text-emerald-500" />
        )}
        <span className="truncate">{label}</span>
        <span className="ml-auto shrink-0 font-mono text-[9px] tabular-nums opacity-60">
          {step.durationSeconds != null ? formatDuration(step.durationSeconds) : step.status === 'running' ? '…' : ''}
        </span>
      </button>
      {open && (
        <div className="ml-4 mt-1 flex flex-col gap-1 border-l border-temper-border pl-2">
          <Detail title="given">{step.args ? <JsonViewer data={step.args} /> : <Empty />}</Detail>
          <Detail title={failed ? 'what went wrong' : 'back'}>
            {failed && step.error
              ? <pre className="whitespace-pre-wrap text-[10px] text-red-400">{step.error}</pre>
              : step.result !== undefined && step.result !== null
                ? <JsonViewer data={step.result} />
                : <Empty />}
          </Detail>
        </div>
      )}
    </div>
  );
}

function Detail({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wide text-temper-text-dim">{title}</div>
      {children}
    </div>
  );
}

function Empty() {
  return <span className="text-[10px] text-temper-text-dim">nothing</span>;
}
