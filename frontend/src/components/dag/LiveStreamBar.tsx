import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { cn } from '@/lib/utils';
import { liveAgents } from '@/lib/liveAgents';
import { buildStreamSegments, tailLines } from '@/lib/streamSegments';
import type { ToolActivity } from '@/types';

/** Lines the strip shows while collapsed: the newest ones. */
export const COLLAPSED_LINES = 6;

export function LiveStreamBar() {
  const streamingContent = useExecutionStore((s) => s.streamingContent);
  const agents = useExecutionStore((s) => s.agents);
  const runStatus = useExecutionStore((s) => s.workflow?.status);
  const select = useExecutionStore((s) => s.select);

  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [activeAgentId, setActiveAgentId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevLengthsRef = useRef(new Map<string, number>());

  // The agents at work. An agent stays while its record says it is running:
  // a finished one's trace is in its panel, and one the page cannot name
  // yet waits until it can (never shown as an id).
  const streamingAgents = useMemo(() => {
    return liveAgents(streamingContent, agents, runStatus).map((live) => ({
      id: live.id,
      name: live.name,
      entry: live.entry,
      size: live.entry.content.length + live.entry.thinking.length,
      activeToolCall: live.entry.activeToolCall ?? '',
      toolActivity: live.entry.toolActivity ?? [],
    }));
  }, [streamingContent, agents, runStatus]);

  const isStreaming = streamingAgents.length > 0;

  // Track which agents have new content since last viewed (for notification dots)
  const updatedAgents = useMemo(() => {
    const updated = new Set<string>();
    for (const sa of streamingAgents) {
      const prevLen = prevLengthsRef.current.get(sa.id) ?? 0;
      if (sa.size > prevLen && sa.id !== activeAgentId) {
        updated.add(sa.id);
      }
    }
    // Update previous lengths for active agent only (so dots stay on inactive tabs)
    if (activeAgentId) {
      const active = streamingAgents.find((sa) => sa.id === activeAgentId);
      if (active) {
        prevLengthsRef.current.set(activeAgentId, active.size);
      }
    }
    return updated;
  }, [streamingAgents, activeAgentId]);

  // Reset dismissed state when streaming stops
  useEffect(() => {
    if (!isStreaming) setDismissed(false);
  }, [isStreaming]);

  // Auto-select first agent only — never auto-switch after that
  useEffect(() => {
    if (streamingAgents.length > 0 && !activeAgentId) {
      setActiveAgentId(streamingAgents[0].id);
    }
    // Clear if active agent is no longer streaming
    if (activeAgentId && !streamingAgents.some((sa) => sa.id === activeAgentId)) {
      setActiveAgentId(streamingAgents.length > 0 ? streamingAgents[0].id : null);
    }
  }, [streamingAgents, activeAgentId]);

  const activeStream = streamingAgents.find((sa) => sa.id === activeAgentId);
  const activeSize = activeStream?.size ?? 0;
  const activeToolCallContent = activeStream?.activeToolCall ?? '';

  // Thinking and text in the order they came. Split before cutting to the
  // newest lines, so lines of a thinking block opened further up still show
  // as thinking.
  const allSegments = useMemo(
    () => (activeStream ? buildStreamSegments(activeStream.entry) : []),
    [activeStream],
  );
  const segments = expanded ? allSegments : tailLines(allSegments, COLLAPSED_LINES);

  // Auto-scroll only when content changes (not every render)
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [activeSize, activeToolCallContent, expanded]);

  const handleOpenDetail = useCallback(() => {
    if (activeAgentId) select('agent', activeAgentId);
  }, [activeAgentId, select]);

  if (!isStreaming || dismissed) return null;

  return (
    <div
      data-testid="live-stream-bar"
      className="absolute bottom-0 left-0 right-0 z-20 bg-temper-panel/95 backdrop-blur-sm border-t border-temper-border shadow-lg"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-temper-border/30">
        {/* Pulsing dot */}
        <span className="w-2 h-2 rounded-full bg-temper-accent animate-pulse shrink-0" />
        <span className="text-xs font-medium text-temper-text shrink-0">Live Output</span>

        {/* Agent tabs: every agent at work, by name. One agent gets a tab
            too, so its name shows and a click opens its panel. */}
        <div className="flex items-center gap-1 ml-2 min-w-0 overflow-x-auto">
          {streamingAgents.map((sa) => (
            <button
              key={sa.id}
              onClick={() => {
                if (sa.id === activeAgentId) {
                  select('agent', sa.id);
                } else {
                  setActiveAgentId(sa.id);
                }
                prevLengthsRef.current.set(sa.id, sa.size);
              }}
              title={sa.id === activeAgentId ? `Open ${sa.name}` : `Show ${sa.name}`}
              className={cn(
                'text-[10px] px-1.5 py-0.5 rounded transition-colors relative shrink-0',
                sa.id === activeAgentId
                  ? 'bg-temper-accent/20 text-temper-accent'
                  : 'text-temper-text-muted hover:text-temper-text',
              )}
            >
              {sa.name}
              {updatedAgents.has(sa.id) && (
                <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-temper-accent animate-pulse" />
              )}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-1 shrink-0">
          <button
            onClick={handleOpenDetail}
            className="text-[10px] px-1.5 py-0.5 rounded text-temper-accent hover:bg-temper-accent/10 transition-colors"
          >
            Open Detail
          </button>
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-[10px] px-1.5 py-0.5 rounded text-temper-text-muted hover:text-temper-text transition-colors"
          >
            {expanded ? 'Collapse' : 'Expand'}
          </button>
          <button
            onClick={() => setDismissed(true)}
            className="text-[10px] px-1.5 py-0.5 rounded text-temper-text-muted hover:text-red-400 transition-colors"
            title="Dismiss"
          >
            &#x2715;
          </button>
        </div>
      </div>

      {/* Content */}
      <div
        ref={scrollRef}
        className={cn(
          'px-3 py-2 text-xs font-mono overflow-auto select-text',
          expanded ? 'max-h-56' : 'max-h-20',
        )}
      >
        <ToolActivityIndicator activities={activeStream?.toolActivity ?? []} />
        {segments.map((seg, i) => {
          if (seg.type === 'thinking') {
            return (
              <div key={i} data-testid="live-thinking" className="my-1 px-2 py-1 rounded bg-violet-500/10 border-l-2 border-violet-500/40">
                <span className="text-[9px] text-violet-700 dark:text-violet-400 font-medium block mb-0.5">thinking</span>
                <span className="text-violet-700/80 dark:text-violet-300/70 whitespace-pre-wrap">{seg.content}</span>
              </div>
            );
          }
          if (seg.type === 'tool_call') {
            return (
              <div key={i} className="my-0.5 text-amber-700 dark:text-amber-400 whitespace-pre-wrap">
                {seg.content}
              </div>
            );
          }
          return <span key={i} className="text-temper-text whitespace-pre-wrap">{seg.content}</span>;
        })}
        {/* Active tool call being streamed — shown separately with distinct styling */}
        {activeToolCallContent && (
          <div className="mt-1 px-2 py-1.5 rounded bg-amber-500/10 border-l-2 border-amber-500/40">
            <span className="text-[9px] text-amber-700 dark:text-amber-400 font-medium block mb-0.5">tool call</span>
            <span className="text-amber-800/90 dark:text-amber-300/90 whitespace-pre-wrap break-all">{activeToolCallContent}</span>
            <span className="animate-pulse text-amber-700 dark:text-amber-400">&#x2588;</span>
          </div>
        )}
        {!activeToolCallContent && <span className="animate-pulse text-temper-accent">&#x2588;</span>}
      </div>
    </div>
  );
}

function ToolActivityIndicator({ activities }: { activities: ToolActivity[] }) {
  if (!activities.length) return null;
  const running = activities.filter((t) => t.status === 'running');
  const completed = activities.filter((t) => t.status !== 'running');
  return (
    <div className="flex flex-col gap-1 mb-1">
      {completed.length > 0 && (
        <span className="text-[10px] text-temper-text-dim">
          {completed.length} tool{completed.length !== 1 ? 's' : ''} completed
        </span>
      )}
      {running.map((t, i) => (
        <div key={i} className="text-[10px]">
          <span className="flex items-center gap-1 text-temper-accent">
            <span className="w-1.5 h-1.5 rounded-full bg-temper-accent animate-pulse shrink-0" />
            <span className="font-medium">{t.toolName}</span>
          </span>
          {t.args && Object.keys(t.args).length > 0 && (
            <pre className="pl-3 mt-0.5 text-temper-text-dim font-mono whitespace-pre-wrap break-all">
              {Object.entries(t.args).map(([k, v]) => {
                const val = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
                return `${k}: ${val}`;
              }).join('\n')}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}
