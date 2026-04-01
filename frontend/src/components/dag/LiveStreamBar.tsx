import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { cn } from '@/lib/utils';
import type { ToolActivity } from '@/types';

export function LiveStreamBar() {
  const streamingContent = useExecutionStore((s) => s.streamingContent);
  const agents = useExecutionStore((s) => s.agents);
  const select = useExecutionStore((s) => s.select);

  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [activeAgentId, setActiveAgentId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLPreElement>(null);
  const prevLengthsRef = useRef(new Map<string, number>());

  // Active (non-done) streaming agents
  const streamingAgents = useMemo(() => {
    const result: { id: string; name: string; content: string; toolActivity: ToolActivity[] }[] = [];
    for (const [agentId, entry] of streamingContent) {
      if (entry.done) continue;
      const agent = agents.get(agentId);
      const name = agent?.agent_name ?? agent?.name ?? agentId;
      result.push({ id: agentId, name, content: entry.content, toolActivity: entry.toolActivity ?? [] });
    }
    return result;
  }, [streamingContent, agents]);

  const isStreaming = streamingAgents.length > 0;

  // Track which agents have new content since last viewed (for notification dots)
  const updatedAgents = useMemo(() => {
    const updated = new Set<string>();
    for (const sa of streamingAgents) {
      const prevLen = prevLengthsRef.current.get(sa.id) ?? 0;
      if (sa.content.length > prevLen && sa.id !== activeAgentId) {
        updated.add(sa.id);
      }
    }
    // Update previous lengths for active agent only (so dots stay on inactive tabs)
    if (activeAgentId) {
      const active = streamingAgents.find((sa) => sa.id === activeAgentId);
      if (active) {
        prevLengthsRef.current.set(activeAgentId, active.content.length);
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

  // Auto-scroll only when content changes (not every render)
  const activeContent = streamingAgents.find((sa) => sa.id === activeAgentId)?.content ?? '';
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [activeContent]);

  const handleOpenDetail = useCallback(() => {
    if (activeAgentId) select('agent', activeAgentId);
  }, [activeAgentId, select]);

  if (!isStreaming || dismissed) return null;

  const activeStream = streamingAgents.find((sa) => sa.id === activeAgentId);
  const displayContent = activeStream?.content ?? '';
  const compactLines = displayContent.split('\n').slice(-3).join('\n');

  return (
    <div className="absolute bottom-0 left-0 right-0 z-20 bg-temper-panel/95 backdrop-blur-sm border-t border-temper-border shadow-lg">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-temper-border/30">
        {/* Pulsing dot */}
        <span className="w-2 h-2 rounded-full bg-temper-accent animate-pulse shrink-0" />
        <span className="text-xs font-medium text-temper-text">Live Output</span>

        {/* Agent tabs */}
        {streamingAgents.length > 1 && (
          <div className="flex items-center gap-1 ml-2">
            {streamingAgents.map((sa) => (
              <button
                key={sa.id}
                onClick={() => { setActiveAgentId(sa.id); prevLengthsRef.current.set(sa.id, sa.content.length); }}
                className={cn(
                  'text-[10px] px-1.5 py-0.5 rounded transition-colors relative',
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
        )}

        <div className="ml-auto flex items-center gap-1">
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
      <pre
        ref={scrollRef}
        className={cn(
          'px-3 py-2 text-xs text-temper-text font-mono whitespace-pre-wrap overflow-auto select-text',
          expanded ? 'max-h-56' : 'max-h-16',
        )}
      >
        <ToolActivityIndicator activities={activeStream?.toolActivity ?? []} />
        {expanded ? displayContent : compactLines}
        <span className="animate-pulse text-temper-accent">&#x2588;</span>
      </pre>
    </div>
  );
}

function ToolActivityIndicator({ activities }: { activities: ToolActivity[] }) {
  if (!activities.length) return null;
  const running = activities.filter((t) => t.status === 'running');
  const completed = activities.filter((t) => t.status !== 'running');
  return (
    <div className="flex flex-col gap-0.5 mb-1">
      {completed.length > 0 && (
        <span className="text-[10px] text-temper-text-dim">
          {completed.length} tool{completed.length !== 1 ? 's' : ''} completed
        </span>
      )}
      {running.map((t, i) => (
        <span key={i} className="text-[10px] text-temper-accent flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-temper-accent animate-pulse" />
          Calling {t.toolName}...
        </span>
      ))}
    </div>
  );
}
