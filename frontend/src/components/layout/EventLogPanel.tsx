import { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { Badge } from '@/components/ui/badge';
import { formatTimestamp, cn } from '@/lib/utils';
import type { SelectionType } from '@/types';

const EVENT_TYPE_STYLES: Record<string, string> = {
  stage: 'bg-[#42a5f5]/20 text-[#42a5f5] border-[#42a5f5]/30',
  agent: 'bg-[#66bb6a]/20 text-[#66bb6a] border-[#66bb6a]/30',
  llm: 'bg-[#ab47bc]/20 text-[#ab47bc] border-[#ab47bc]/30',
  tool: 'bg-[#ffa726]/20 text-[#ffa726] border-[#ffa726]/30',
  workflow: 'bg-[#4fc3f7]/20 text-[#4fc3f7] border-[#4fc3f7]/30',
};

const FILTER_CATEGORIES = ['all', 'workflow', 'stage', 'agent', 'llm', 'tool'] as const;

function eventStyle(eventType: string): string {
  const prefix = eventType.split('_')[0];
  return EVENT_TYPE_STYLES[prefix] ?? EVENT_TYPE_STYLES.workflow;
}

/** Map event_type to a SelectionType + entity ID, or null if not selectable */
function resolveSelection(
  eventType: string,
  data?: Record<string, unknown>,
): { type: SelectionType; id: string } | null {
  if (!data) return null;
  const prefix = eventType.split('_')[0];

  switch (prefix) {
    case 'stage': {
      const id = (data.stage_id ?? data.id) as string | undefined;
      return id ? { type: 'stage', id } : null;
    }
    case 'agent': {
      const id = (data.agent_id ?? data.id) as string | undefined;
      return id ? { type: 'agent', id } : null;
    }
    case 'llm': {
      const id = (data.llm_call_id ?? data.id) as string | undefined;
      return id ? { type: 'llmCall', id } : null;
    }
    case 'tool': {
      const id = (data.tool_execution_id ?? data.id) as string | undefined;
      return id ? { type: 'toolCall', id } : null;
    }
    default:
      return null;
  }
}

export function EventLogPanel() {
  const eventLog = useExecutionStore((s) => s.eventLog);
  const select = useExecutionStore((s) => s.select);
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [filter, setFilter] = useState<string | null>(null);
  const [searchText, setSearchText] = useState('');
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [newEvents, setNewEvents] = useState(0);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
    setIsAtBottom(atBottom);
    if (atBottom) setNewEvents(0);
  }, []);

  useEffect(() => {
    if (isAtBottom) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    } else {
      setNewEvents((n) => n + 1);
    }
  }, [eventLog.length]); // eslint-disable-line react-hooks/exhaustive-deps -- intentional: only on new events

  const handleClick = useCallback(
    (eventType: string, data?: Record<string, unknown>) => {
      const sel = resolveSelection(eventType, data);
      if (sel) select(sel.type, sel.id);
    },
    [select],
  );

  const handleKeyActivate = useCallback(
    (e: React.KeyboardEvent, eventType: string, data?: Record<string, unknown>) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleClick(eventType, data);
      }
    },
    [handleClick],
  );

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    setNewEvents(0);
  }, []);

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: eventLog.length };
    for (const e of eventLog) {
      const prefix = e.event_type.split('_')[0];
      counts[prefix] = (counts[prefix] ?? 0) + 1;
    }
    return counts;
  }, [eventLog]);

  const filtered = useMemo(() => {
    return eventLog
      .filter((e) => e.event_type !== 'llm_stream_batch')
      .filter((e) => !filter || e.event_type.startsWith(filter))
      .filter(
        (e) =>
          !searchText ||
          e.label.toLowerCase().includes(searchText.toLowerCase()) ||
          e.event_type.includes(searchText.toLowerCase()),
      );
  }, [eventLog, filter, searchText]);

  if (eventLog.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-maf-text-muted gap-2">
        <span className="text-2xl">&#x1F4CB;</span>
        <span className="text-sm">Waiting for workflow events...</span>
        <span className="text-xs text-maf-text-dim">Events will appear here as the workflow executes</span>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Filter chips + search */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-maf-border/30 shrink-0 flex-wrap">
        {FILTER_CATEGORIES.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f === 'all' ? null : f)}
            className={cn(
              'px-2 py-0.5 rounded text-xs transition-colors',
              filter === f || (f === 'all' && !filter)
                ? 'bg-maf-accent/20 text-maf-accent'
                : 'text-maf-text-muted hover:text-maf-text',
            )}
          >
            {f}
            {categoryCounts[f] != null && (
              <span className="ml-1 text-[10px] opacity-60">({categoryCounts[f]})</span>
            )}
          </button>
        ))}
        <input
          type="text"
          placeholder="Search events..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          className="px-2 py-0.5 rounded text-xs bg-maf-surface border border-maf-border text-maf-text placeholder:text-maf-text-dim focus:outline-none focus:ring-1 focus:ring-maf-accent w-full sm:w-40"
        />
        <span className="ml-auto text-xs text-maf-text-muted">
          {filtered.length} events
        </span>
      </div>

      {/* Event list */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-2 space-y-1 min-h-0 relative"
        role="log"
        aria-label="Event log"
        aria-live="polite"
      >
        {filtered.map((entry, idx) => {
          const sel = resolveSelection(entry.event_type, entry.data);
          return (
            <div
              key={idx}
              className={cn(
                'flex items-center gap-3 py-1 text-sm border-b border-maf-border/30 last:border-0',
                sel && 'cursor-pointer hover:bg-maf-surface/50',
              )}
              onClick={sel ? () => handleClick(entry.event_type, entry.data) : undefined}
              onKeyDown={sel ? (e) => handleKeyActivate(e, entry.event_type, entry.data) : undefined}
              role={sel ? 'button' : undefined}
              tabIndex={sel ? 0 : undefined}
            >
              <span className="font-mono text-xs text-maf-text-muted shrink-0 w-28">
                {formatTimestamp(entry.timestamp)}
              </span>
              <Badge variant="outline" className={`text-xs shrink-0 ${eventStyle(entry.event_type)}`}>
                {entry.event_type}
              </Badge>
              <span className="text-maf-text truncate">{entry.label}</span>
            </div>
          );
        })}
        <div ref={bottomRef} />
        {!isAtBottom && (
          <button
            onClick={scrollToBottom}
            className="sticky bottom-2 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full text-xs bg-maf-accent text-maf-panel shadow-lg z-10"
          >
            {newEvents > 0 ? `${newEvents} new events` : 'Jump to bottom'}
          </button>
        )}
      </div>
    </div>
  );
}
