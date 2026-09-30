import { useState, useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { CollapsibleSection } from '@/components/shared/Collapsible';
import { JsonViewer } from '@/components/shared/JsonViewer';
import { MetricCell } from '@/components/shared/MetricCell';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn, formatDuration, formatTimestamp, categorizeError } from '@/lib/utils';

interface StageDetailPanelProps {
  stageId: string;
}

export function StageDetailPanel({ stageId }: StageDetailPanelProps) {
  const stage = useExecutionStore((s) => s.stages.get(stageId));
  const select = useExecutionStore((s) => s.select);
  const stages = useExecutionStore((s) => s.stages);

  const iterations = useMemo(() => {
    if (!stage) return [];
    const baseName = stage.stage_name ?? stage.name;
    if (!baseName) return [];
    return Array.from(stages.values()).filter(s => (s.stage_name ?? s.name) === baseName);
  }, [stages, stage]);

  const [selectedIteration, setSelectedIteration] = useState(0);

  if (!stage) {
    return (
      <div className="p-4 text-sm text-temper-text-muted">Stage not found.</div>
    );
  }

  const executed = stage.num_agents_executed ?? stage.agents?.length ?? 0;
  const succeeded = stage.num_agents_succeeded ?? 0;
  const failed = stage.num_agents_failed ?? 0;
  const total = Math.max(executed, succeeded + failed, 1);
  const successPct = (succeeded / total) * 100;
  const failPct = (failed / total) * 100;

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Header */}
      <div className="flex items-center gap-3 sticky top-0 z-10 bg-temper-bg pb-2">
        <h3 className="text-lg font-semibold text-temper-text">
          {stage.stage_name ?? stage.name ?? stageId}
        </h3>
        <StatusBadge status={stage.status} />
        {stage.stage_type && (
          <Badge variant="secondary" className="text-xs">
            {stage.stage_type}
          </Badge>
        )}
      </div>

      {/* Iteration selector */}
      {iterations.length > 1 && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-temper-text-muted">Iteration:</span>
          {iterations.map((iter, i) => (
            <button
              key={iter.id}
              onClick={() => { setSelectedIteration(i); select('stage', iter.id); }}
              className={cn(
                'px-2 py-0.5 rounded text-xs',
                i === selectedIteration
                  ? 'bg-temper-accent/20 text-temper-accent'
                  : 'text-temper-text-muted hover:text-temper-text',
              )}
            >
              #{i + 1}
            </button>
          ))}
        </div>
      )}

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-3">
        <MetricCell label="Agents Executed" value={String(executed)} />
        <MetricCell label="Succeeded" value={String(succeeded)} />
        <MetricCell label="Failed" value={String(failed)} />
        <MetricCell
          label="Duration"
          value={formatDuration(stage.duration_seconds)}
        />
        <MetricCell label="Start Time" value={formatTimestamp(stage.start_time)} />
        <MetricCell label="End Time" value={formatTimestamp(stage.end_time)} />
      </div>

      {/* Error */}
      {stage.error_message && (() => {
        const { type, retryable } = categorizeError(stage.error_message);
        return (
          <div className="rounded-md bg-temper-bg-failed p-3 text-sm text-temper-failed">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-red-100 border border-red-300 dark:bg-red-950 dark:border-red-900/50">{type}</span>
              {retryable && <span className="text-xs text-amber-600 dark:text-amber-400">Retryable</span>}
            </div>
            {stage.error_message}
          </div>
        );
      })()}

      {/* Agent success bar */}
      {executed > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-temper-text-muted">Agent Results</span>
          <div className="flex h-3 w-full overflow-hidden rounded-full bg-temper-panel">
            {successPct > 0 && (
              <div
                className="bg-temper-completed transition-all"
                style={{ width: `${successPct}%` }}
              />
            )}
            {failPct > 0 && (
              <div
                className="bg-temper-failed transition-all"
                style={{ width: `${failPct}%` }}
              />
            )}
          </div>
          <div className="flex gap-3 text-xs text-temper-text-dim">
            <span className="flex items-center gap-1">
              <span className="inline-block size-2 rounded-full bg-temper-completed" />
              {succeeded} succeeded
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block size-2 rounded-full bg-temper-failed" />
              {failed} failed
            </span>
          </div>
        </div>
      )}

      <Separator />

      {/* Collapsible sections */}
      <CollapsibleSection title="Input Data">
        <JsonViewer data={stage.input_data} />
      </CollapsibleSection>

      <CollapsibleSection title="Output Data">
        <JsonViewer data={stage.output_data} />
      </CollapsibleSection>

      {stage.collaboration_events && stage.collaboration_events.length > 0 && (
        <CollapsibleSection title="Collaboration Events">
          <div className="mt-1 flex flex-col">
            {stage.collaboration_events.map((evt, i) => (
              <div key={i} className="flex gap-3 relative">
                {/* Vertical line */}
                {i < stage.collaboration_events!.length - 1 && (
                  <div className="absolute left-[7px] top-5 bottom-0 w-px bg-temper-border" />
                )}
                {/* Dot */}
                <div className="w-3.5 h-3.5 rounded-full bg-temper-accent/30 border-2 border-temper-accent shrink-0 mt-0.5 z-10" />
                {/* Content */}
                <div className="flex-1 rounded-md bg-temper-panel p-2 text-xs text-temper-text mb-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-temper-accent">{evt.event_type}</span>
                    {evt.from_agent && <span className="text-temper-text-muted">from {evt.from_agent}</span>}
                    {evt.to_agent && <span className="text-temper-text-muted">to {evt.to_agent}</span>}
                    {evt.agents_involved && evt.agents_involved.length > 0 && (
                      <span className="text-temper-text-muted">({evt.agents_involved.join(', ')})</span>
                    )}
                  </div>
                  {evt.timestamp && (
                    <span className="text-[10px] text-temper-text-dim mt-0.5 block">{formatTimestamp(evt.timestamp)}</span>
                  )}
                  {evt.data && Object.keys(evt.data).length > 0 && (
                    <JsonViewer data={evt.data} className="mt-1" />
                  )}
                </div>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

      <Separator />

      {/* Agent list */}
      {stage.agents && stage.agents.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-temper-text-muted">
            Agents
          </span>
          {stage.agents.map((agent) => (
            <Button
              key={agent.id}
              variant="ghost"
              size="sm"
              className="justify-between text-left"
              onClick={() => select('agent', agent.id)}
            >
              <span className="text-temper-text">
                {agent.agent_name ?? agent.name ?? agent.id}
              </span>
              <StatusBadge status={agent.status} />
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
