import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Info } from 'lucide-react';
import { useExecutionStore } from '@/store/executionStore';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { formatDuration, elapsedSeconds, cn } from '@/lib/utils';
import { DURATION_TICK_MS } from '@/lib/constants';

export function WorkflowHeader() {
  const navigate = useNavigate();
  const workflow = useExecutionStore((s) => s.workflow);
  const wsStatus = useExecutionStore((s) => s.wsStatus);
  const streamingContent = useExecutionStore((s) => s.streamingContent);
  const agents = useExecutionStore((s) => s.agents);
  const select = useExecutionStore((s) => s.select);

  const [elapsed, setElapsed] = useState(0);
  const [errorExpanded, setErrorExpanded] = useState(false);

  const isRunning = workflow?.status === 'running';

  useEffect(() => {
    if (!isRunning || !workflow?.start_time) return;

    setElapsed(elapsedSeconds(workflow.start_time));
    const id = setInterval(() => {
      setElapsed(elapsedSeconds(workflow.start_time));
    }, DURATION_TICK_MS);

    return () => clearInterval(id);
  }, [isRunning, workflow?.start_time]);

  const displayDuration = isRunning
    ? formatDuration(elapsed)
    : formatDuration(workflow?.duration_seconds);

  // Streaming agents (not done)
  const streamingAgents: Array<{ id: string; name: string }> = [];
  streamingContent.forEach((entry, agentId) => {
    if (!entry.done) {
      const agent = agents.get(agentId);
      streamingAgents.push({ id: agentId, name: agent?.agent_name ?? agentId });
    }
  });

  // WS status indicator
  let wsIndicator: React.ReactNode;
  if (wsStatus.connected) {
    wsIndicator = (
      <span className="flex items-center gap-1.5 text-xs text-temper-text-muted">
        <span className="inline-block h-2 w-2 rounded-full bg-temper-completed" />
        Connected
      </span>
    );
  } else if (wsStatus.reconnectAttempt > 0) {
    wsIndicator = (
      <span className="flex items-center gap-1.5 text-xs text-yellow-400">
        <span className="inline-block h-2 w-2 rounded-full bg-yellow-400" />
        Reconnecting ({wsStatus.reconnectAttempt})
      </span>
    );
  } else {
    wsIndicator = (
      <span className="flex items-center gap-1.5 text-xs text-temper-text-muted">
        <span className="inline-block h-2 w-2 rounded-full bg-temper-text-dim" />
        Disconnected
      </span>
    );
  }

  return (
    <>
      <header className="flex items-center gap-4 bg-temper-panel px-4 py-3 border-b border-temper-border shrink-0">
        <button
          onClick={() => navigate('/')}
          className="text-temper-text-muted hover:text-temper-text transition-colors shrink-0"
          aria-label="Back to workflow list"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>

        <h1 className="text-lg font-semibold text-temper-text truncate">
          {workflow?.workflow_name ?? 'Loading...'}
        </h1>

        <button
          onClick={() => workflow && select('workflow', workflow.id)}
          className="text-temper-text-muted hover:text-temper-text transition-colors shrink-0"
          aria-label="Workflow details"
        >
          <Info className="w-4 h-4" />
        </button>

        {workflow && <StatusBadge status={workflow.status} />}

        <span className={cn(
          'text-sm font-mono',
          workflow?.status === 'failed' ? 'text-temper-failed' :
          workflow?.status === 'completed' ? 'text-temper-completed' :
          'text-temper-text-muted'
        )}>
          {displayDuration}
        </span>

        {/* Streaming agent badges */}
        {streamingAgents.length > 0 && (
          <div className="flex items-center gap-1.5 ml-2">
            {streamingAgents.map((sa) => (
              <button
                key={sa.id}
                onClick={() => select('agent', sa.id)}
                className="px-2 py-0.5 rounded text-xs font-medium bg-temper-accent/20 text-temper-accent border border-temper-accent/30 animate-pulse-streaming hover:bg-temper-accent/30 transition-colors"
              >
                {sa.name}
              </button>
            ))}
          </div>
        )}

        <div className="ml-auto">{wsIndicator}</div>
      </header>
      {workflow?.status === 'failed' && workflow?.error_message && (
        <div
          onClick={() => setErrorExpanded(!errorExpanded)}
          className={cn(
            'bg-red-950/50 border-b border-red-900/50 px-4 py-2 text-sm text-red-400 cursor-pointer hover:bg-red-950/70 shrink-0',
            !errorExpanded && 'truncate',
          )}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setErrorExpanded(!errorExpanded); }}
        >
          {workflow.error_message}
        </div>
      )}
    </>
  );
}
