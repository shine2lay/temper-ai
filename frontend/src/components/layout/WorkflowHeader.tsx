import { useState, useEffect, useCallback, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, Info, Pencil, Download } from 'lucide-react';
import { useExecutionStore } from '@/store/executionStore';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { formatDuration, formatTokens, formatCost, elapsedSeconds, cn } from '@/lib/utils';
import { DURATION_TICK_MS } from '@/lib/constants';
import { ThemeToggle } from '@/components/shared/ThemeToggle';

export function WorkflowHeader() {
  const navigate = useNavigate();
  const workflow = useExecutionStore((s) => s.workflow);
  const wsStatus = useExecutionStore((s) => s.wsStatus);
  const streamingContent = useExecutionStore((s) => s.streamingContent);
  const agents = useExecutionStore((s) => s.agents);
  const stages = useExecutionStore((s) => s.stages);
  const llmCalls = useExecutionStore((s) => s.llmCalls);
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
  let wsIndicator: ReactNode;
  if (wsStatus.connected) {
    wsIndicator = (
      <span className="flex items-center gap-1.5 text-xs text-temper-text-muted">
        <span className="inline-block h-2 w-2 rounded-full bg-temper-completed" />
        Connected
      </span>
    );
  } else if (wsStatus.wsError === 'auth_failed') {
    wsIndicator = (
      <span className="flex items-center gap-1.5 text-xs text-red-400">
        <span className="inline-block h-2 w-2 rounded-full bg-red-400" />
        Auth failed
      </span>
    );
  } else if (wsStatus.wsError === 'max_retries') {
    wsIndicator = (
      <span className="flex items-center gap-1.5 text-xs text-temper-text-muted">
        <span className="inline-block h-2 w-2 rounded-full bg-temper-text-dim" />
        Disconnected
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

  const taskInput = workflow?.input_data;
  const taskPreview = (() => {
    if (!taskInput) return null;
    const raw = taskInput.task ?? taskInput.input ?? taskInput.prompt ?? Object.values(taskInput)[0];
    if (!raw) return null;
    const str = typeof raw === 'string' ? raw : JSON.stringify(raw);
    return str.length > 120 ? str.slice(0, 120) + '…' : str;
  })();

  const exportReport = useCallback(() => {
    if (!workflow) return;

    const TRUNC = 2000;
    const trunc = (s: string) => (s.length > TRUNC ? s.slice(0, TRUNC) + '\n…(truncated)' : s);

    const lines: string[] = [];

    lines.push(`# Workflow Report: ${workflow.workflow_name}`);
    lines.push('');
    lines.push(`| Field | Value |`);
    lines.push(`|---|---|`);
    lines.push(`| Status | ${workflow.status} |`);
    lines.push(`| Duration | ${formatDuration(workflow.duration_seconds)} |`);
    lines.push(`| Total Tokens | ${formatTokens(workflow.total_tokens)} |`);
    lines.push(`| Total Cost | ${formatCost(workflow.total_cost_usd)} |`);
    lines.push(`| LLM Calls | ${workflow.total_llm_calls ?? 0} |`);
    lines.push(`| Tool Calls | ${workflow.total_tool_calls ?? 0} |`);
    if (workflow.start_time) lines.push(`| Started | ${workflow.start_time} |`);
    if (workflow.end_time) lines.push(`| Ended | ${workflow.end_time} |`);
    lines.push('');

    if (workflow.input_data) {
      lines.push('## Input');
      lines.push('```json');
      lines.push(trunc(JSON.stringify(workflow.input_data, null, 2)));
      lines.push('```');
      lines.push('');
    }

    lines.push('## Stages');
    lines.push('');

    for (const [, stage] of stages) {
      const stageName = stage.stage_name ?? stage.name ?? stage.id;
      lines.push(`### Stage: ${stageName}`);
      lines.push('');
      lines.push(`- **Status:** ${stage.status}`);
      lines.push(`- **Duration:** ${formatDuration(stage.duration_seconds)}`);
      if (stage.error_message) lines.push(`- **Error:** ${stage.error_message}`);
      lines.push('');

      const nodeAgents = stage.agents ?? (stage.agent ? [stage.agent] : []);
      for (const agentRef of nodeAgents) {
        const agent = agents.get(agentRef.id) ?? agentRef;
        const agentName = agent.agent_name ?? agent.name ?? agent.id;
        lines.push(`#### Agent: ${agentName}`);
        lines.push('');
        lines.push(`- **Status:** ${agent.status}`);
        lines.push(`- **Duration:** ${formatDuration(agent.duration_seconds)}`);
        lines.push(`- **Tokens:** ${formatTokens(agent.total_tokens)} | **Cost:** ${formatCost(agent.estimated_cost_usd)}`);
        lines.push(`- **LLM Calls:** ${agent.total_llm_calls} | **Tool Calls:** ${agent.total_tool_calls}`);

        if (agent.output) {
          lines.push('');
          lines.push('**Output:**');
          lines.push('');
          lines.push(trunc(agent.output));
        } else if (agent.output_data) {
          lines.push('');
          lines.push('**Output Data:**');
          lines.push('```json');
          lines.push(trunc(JSON.stringify(agent.output_data, null, 2)));
          lines.push('```');
        }

        if (agent.error_message) {
          lines.push('');
          lines.push(`**Error:** ${agent.error_message}`);
        }
        lines.push('');
      }
    }

    if (llmCalls.size > 0) {
      lines.push('## LLM Call Summary');
      lines.push('');
      lines.push('| Model | Tokens | Cost | Duration | Status |');
      lines.push('|---|---|---|---|---|');
      for (const [, call] of llmCalls) {
        const model = call.model ?? call.provider ?? 'unknown';
        lines.push(
          `| ${model} | ${formatTokens(call.total_tokens)} | ${formatCost(call.estimated_cost_usd)} | ${formatDuration(call.duration_seconds)} | ${call.status} |`,
        );
      }
      lines.push('');
    }

    const markdown = lines.join('\n');
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    const safeName = workflow.workflow_name.replace(/[^a-z0-9_-]/gi, '_');
    anchor.href = url;
    anchor.download = `${safeName}_report.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [workflow, stages, agents, llmCalls]);

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
            {streamingAgents.map((sa, i) => (
              <button
                key={sa.id}
                onClick={() => select('agent', sa.id)}
                className="px-2 py-0.5 rounded text-xs font-medium bg-temper-accent/20 text-temper-accent border border-temper-accent/30 animate-pulse-streaming hover:bg-temper-accent/30 transition-colors"
                style={{ animationDelay: `${i * 0.2}s` }}
              >
                {sa.name}
              </button>
            ))}
          </div>
        )}

        {workflow && (
          <Link
            to={`/studio/${workflow.workflow_name}`}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-temper-surface text-temper-text-muted hover:text-temper-accent hover:bg-temper-accent/10 border border-temper-border transition-colors shrink-0"
          >
            <Pencil className="w-3 h-3" />
            Edit in Studio
          </Link>
        )}
        {workflow && (
          <button
            onClick={exportReport}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-temper-surface text-temper-text-muted hover:text-temper-accent hover:bg-temper-accent/10 border border-temper-border transition-colors shrink-0"
            aria-label="Export run as Markdown report"
          >
            <Download className="w-3 h-3" />
            Export
          </button>
        )}

        <div className="ml-auto flex items-center gap-2"><ThemeToggle />{wsIndicator}</div>
      </header>
      {taskPreview && (
        <div className="px-4 py-1 bg-temper-surface/30 border-b border-temper-border/20 text-xs text-temper-text-dim truncate shrink-0">
          <span className="text-temper-text-muted mr-1">Task:</span>{taskPreview}
        </div>
      )}
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
