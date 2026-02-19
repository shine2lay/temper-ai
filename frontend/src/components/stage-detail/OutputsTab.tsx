import { useState, useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { cn } from '@/lib/utils';
import { JsonViewer } from '@/components/shared/JsonViewer';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { CopyButton } from '@/components/shared/CopyButton';
import type { AgentExecution } from '@/types';

interface OutputsTabProps {
  agents: AgentExecution[];
  stageOutputData?: Record<string, unknown>;
  strategy?: string;
}

type OutputView = 'grid' | 'comparison';

/**
 * Outputs watch panel showing all agent outputs.
 * Grid view: Dify-style variable watch panel.
 * Comparison view: side-by-side for debate/voting strategies.
 */
export function OutputsTab({ agents, stageOutputData, strategy }: OutputsTabProps) {
  const isDebateOrVoting = strategy === 'debate' || strategy === 'voting';
  const [viewMode, setViewMode] = useState<OutputView>(isDebateOrVoting ? 'comparison' : 'grid');

  const agentsWithOutput = useMemo(
    () => agents.filter((a) => a.output_data || a.output || a.reasoning),
    [agents],
  );

  return (
    <div className="flex flex-col gap-3">
      {/* Controls */}
      <div className="flex items-center gap-3">
        <div role="radiogroup" aria-label="Output view mode" className="flex rounded-md bg-temper-surface overflow-hidden">
          <button
            role="radio"
            aria-checked={viewMode === 'grid'}
            className={cn(
              'px-3 py-1 text-xs transition-colors',
              viewMode === 'grid'
                ? 'bg-temper-accent/20 text-temper-accent'
                : 'text-temper-text-muted hover:text-temper-text',
            )}
            onClick={() => setViewMode('grid')}
          >
            Watch Panel
          </button>
          <button
            role="radio"
            aria-checked={viewMode === 'comparison'}
            className={cn(
              'px-3 py-1 text-xs transition-colors',
              viewMode === 'comparison'
                ? 'bg-temper-accent/20 text-temper-accent'
                : 'text-temper-text-muted hover:text-temper-text',
            )}
            onClick={() => setViewMode('comparison')}
          >
            Compare
          </button>
        </div>
        <span className="text-[10px] text-temper-text-dim ml-auto">
          {agentsWithOutput.length} of {agents.length} agents with output
        </span>
      </div>

      {/* Stage-level output */}
      {stageOutputData && Object.keys(stageOutputData).length > 0 && (
        <div className="rounded-lg border border-temper-accent/30 bg-temper-accent/5 p-3">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-medium text-temper-accent">Stage Output (Final)</span>
            <CopyButton text={JSON.stringify(stageOutputData, null, 2)} />
          </div>
          <div className="max-h-48 overflow-y-auto">
            <JsonViewer data={stageOutputData} />
          </div>
        </div>
      )}

      {agentsWithOutput.length === 0 ? (
        <div className="text-xs text-temper-text-muted py-6 text-center">
          No agent outputs available yet.
        </div>
      ) : viewMode === 'grid' ? (
        <WatchPanelGrid agents={agentsWithOutput} />
      ) : (
        <ComparisonView agents={agentsWithOutput} />
      )}
    </div>
  );
}

/** Dify-style watch panel — each agent output as an expandable card. */
function WatchPanelGrid({ agents }: { agents: AgentExecution[] }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {agents.map((agent) => (
        <WatchCard key={agent.id} agent={agent} />
      ))}
    </div>
  );
}

function WatchCard({ agent }: { agent: AgentExecution }) {
  const [expanded, setExpanded] = useState(false);
  const select = useExecutionStore((s) => s.select);
  const name = agent.agent_name ?? agent.name ?? agent.id;
  const hasOutput = agent.output_data && Object.keys(agent.output_data).length > 0;
  const outputText = agent.output ?? '';

  return (
    <div className="rounded-lg border border-temper-border/40 bg-temper-panel/50 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-temper-surface/30">
        <span className="text-xs font-medium text-temper-text truncate">{name}</span>
        <StatusBadge status={agent.status} className="text-[10px] py-0 px-1" />
        {agent.confidence_score != null && (
          <span
            className={cn(
              'text-[10px] px-1 rounded font-mono ml-auto',
              agent.confidence_score >= 0.8
                ? 'text-emerald-400'
                : agent.confidence_score >= 0.5
                  ? 'text-amber-400'
                  : 'text-red-400',
            )}
          >
            {(agent.confidence_score * 100).toFixed(0)}%
          </span>
        )}
        <CopyButton
          text={hasOutput ? JSON.stringify(agent.output_data, null, 2) : outputText}
        />
      </div>

      {/* Output preview / full */}
      <div className="px-3 py-2">
        <div
          className={cn('overflow-hidden transition-all', expanded ? 'max-h-96' : 'max-h-24')}
        >
          {hasOutput ? (
            <JsonViewer data={agent.output_data} />
          ) : outputText ? (
            <div className="text-xs text-temper-text font-mono whitespace-pre-wrap">
              {outputText}
            </div>
          ) : (
            <span className="text-xs text-temper-text-dim">No output</span>
          )}
        </div>

        {/* Expand/collapse + detail link */}
        <div className="flex items-center gap-2 mt-1">
          <button
            className="text-[10px] text-temper-text-muted hover:text-temper-text"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? 'Show less' : 'Show more'}
          </button>
          <button
            className="text-[10px] text-temper-accent hover:underline ml-auto"
            onClick={() => select('agent', agent.id)}
          >
            Full details
          </button>
        </div>
      </div>
    </div>
  );
}

/** Side-by-side comparison for debate/voting strategies. */
function ComparisonView({ agents }: { agents: AgentExecution[] }) {
  return (
    <div
      className="grid gap-3"
      style={{ gridTemplateColumns: `repeat(${Math.min(agents.length, 3)}, minmax(0, 1fr))` }}
    >
      {agents.map((agent) => {
        const name = agent.agent_name ?? agent.name ?? agent.id;
        const hasOutput = agent.output_data && Object.keys(agent.output_data).length > 0;
        const outputText = agent.output ?? '';

        return (
          <div
            key={agent.id}
            className="flex flex-col rounded-lg border border-temper-border/40 bg-temper-panel/50 overflow-hidden"
          >
            {/* Agent header */}
            <div className="flex items-center gap-2 px-3 py-2 bg-temper-surface/30 border-b border-temper-border/30">
              <span className="text-xs font-medium text-temper-text truncate">{name}</span>
              <StatusBadge status={agent.status} className="text-[10px] py-0 px-1" />
              {agent.confidence_score != null && (
                <span
                  className={cn(
                    'text-[10px] px-1 rounded font-mono ml-auto',
                    agent.confidence_score >= 0.8
                      ? 'text-emerald-400'
                      : agent.confidence_score >= 0.5
                        ? 'text-amber-400'
                        : 'text-red-400',
                  )}
                >
                  {(agent.confidence_score * 100).toFixed(0)}%
                </span>
              )}
            </div>

            {/* Output content */}
            <div className="flex-1 p-3 max-h-80 overflow-y-auto">
              {hasOutput ? (
                <JsonViewer data={agent.output_data} />
              ) : outputText ? (
                <div className="text-xs text-temper-text font-mono whitespace-pre-wrap">
                  {outputText}
                </div>
              ) : (
                <span className="text-xs text-temper-text-dim">No output</span>
              )}
            </div>

            {/* Reasoning section */}
            {agent.reasoning && (
              <div className="border-t border-temper-border/30 px-3 py-2">
                <span className="text-[10px] font-medium text-temper-text-muted block mb-1">
                  Reasoning
                </span>
                <div className="text-[11px] text-temper-text-dim font-mono whitespace-pre-wrap max-h-32 overflow-y-auto">
                  {agent.reasoning}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
