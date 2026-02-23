import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { cn } from '@/lib/utils';

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
    const result: { id: string; name: string; content: string }[] = [];
    for (const [agentId, entry] of streamingContent) {
      if (entry.done) continue;
      const agent = agents.get(agentId);
      const name = agent?.agent_name ?? agent?.name ?? agentId;
      result.push({ id: agentId, name, content: entry.content });
    }
    return result;
  }, [streamingContent, agents]);

  // Stable ref so the auto-switch effect can read streamingAgents without
  // adding it as a dependency (which would cause re-fire loops).
  const streamingAgentsRef = useRef(streamingAgents);
  streamingAgentsRef.current = streamingAgents;

  // Stable fingerprint: changes only when active agent set or content lengths change
  const streamFingerprint = useMemo(() => {
    const parts: string[] = [];
    for (const [agentId, entry] of streamingContent) {
      if (!entry.done) parts.push(`${agentId}:${entry.content.length}`);
    }
    return parts.join('|');
  }, [streamingContent]);

  const isStreaming = streamingAgents.length > 0;

  // Reset dismissed state when streaming stops
  useEffect(() => {
    if (!isStreaming) setDismissed(false);
  }, [isStreaming]);

  // Auto-switch to most recently updated agent.
  // Uses streamFingerprint (not streamingAgents) as dep to avoid new-array-reference
  // re-fires, and reads streamingAgentsRef to avoid adding activeAgentId as a dep
  // (which would cause the effect to re-run every time it sets state).
  useEffect(() => {
    const agents = streamingAgentsRef.current;
    if (agents.length === 0) {
      setActiveAgentId(null);
      return;
    }

    let maxDelta = -1;
    let bestId = agents[0].id;

    for (const sa of agents) {
      const prevLen = prevLengthsRef.current.get(sa.id) ?? 0;
      const delta = sa.content.length - prevLen;
      if (delta > maxDelta) {
        maxDelta = delta;
        bestId = sa.id;
      }
    }

    // Update previous lengths
    const newLengths = new Map<string, number>();
    for (const sa of agents) {
      newLengths.set(sa.id, sa.content.length);
    }
    prevLengthsRef.current = newLengths;

    if (maxDelta > 0) {
      setActiveAgentId(bestId);
    } else {
      setActiveAgentId((prev) => {
        if (!prev || !agents.some((sa) => sa.id === prev)) return bestId;
        return prev;
      });
    }
  }, [streamFingerprint]);

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
                onClick={() => setActiveAgentId(sa.id)}
                className={cn(
                  'text-[10px] px-1.5 py-0.5 rounded transition-colors',
                  sa.id === activeAgentId
                    ? 'bg-temper-accent/20 text-temper-accent'
                    : 'text-temper-text-muted hover:text-temper-text',
                )}
              >
                {sa.name}
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
        {expanded ? displayContent : compactLines}
        <span className="animate-pulse text-temper-accent">&#x2588;</span>
      </pre>
    </div>
  );
}
