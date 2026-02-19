import { useMemo, useState, useEffect } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { cn, formatDuration, ensureUTC } from '@/lib/utils';
import { STATUS_COLORS, DURATION_TICK_MS } from '@/lib/constants';
import type { AgentExecution } from '@/types';

interface GanttTimelineProps {
  agents: AgentExecution[];
  stageDurationSeconds: number | null;
  stageStartTime: string | null;
}

interface GanttBar {
  agent: AgentExecution;
  label: string;
  offsetPct: number;
  widthPct: number;
  status: string;
}

const MIN_BAR_WIDTH_PCT = 3;
const BAR_HEIGHT_PX = 28;
const ROW_GAP_PX = 4;
const LABEL_WIDTH_PX = 120;
const TICK_COUNT = 5;

/**
 * Gantt timeline showing agent execution timing on a shared time axis.
 * Parallel agents overlap visually; sequential ones stagger.
 * Inspired by Kestra / Prefect execution timeline.
 */
export function GanttTimeline({ agents, stageDurationSeconds, stageStartTime }: GanttTimelineProps) {
  const select = useExecutionStore((s) => s.select);
  const hasRunningAgent = agents.some((a) => a.status === 'running');

  // Tick for live-updating running agent bars
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!hasRunningAgent) return;
    const id = setInterval(() => setNow(Date.now()), DURATION_TICK_MS);
    return () => clearInterval(id);
  }, [hasRunningAgent]);

  const { bars, totalDuration, tickMarks } = useMemo(() => {
    if (!stageStartTime || agents.length === 0) {
      return { bars: [], totalDuration: 0, tickMarks: [] };
    }

    const stageStart = new Date(ensureUTC(stageStartTime)).getTime();
    const total = stageDurationSeconds ?? 0;

    // Use the max agent end time if stage duration not yet set (still running)
    let effectiveTotal = total;
    if (effectiveTotal <= 0) {
      const maxEnd = agents.reduce((max, a) => {
        if (!a.end_time) return Math.max(max, (now - stageStart) / 1000);
        const end = (new Date(ensureUTC(a.end_time)).getTime() - stageStart) / 1000;
        return Math.max(max, end);
      }, 0);
      effectiveTotal = Math.max(maxEnd, 1);
    }

    const computedBars: GanttBar[] = agents.map((agent) => {
      const agentStart = agent.start_time
        ? (new Date(ensureUTC(agent.start_time)).getTime() - stageStart) / 1000
        : 0;
      const agentDur = agent.duration_seconds ?? (agent.start_time
        ? (now - new Date(ensureUTC(agent.start_time)).getTime()) / 1000
        : 0);

      const offsetPct = Math.max(0, (agentStart / effectiveTotal) * 100);
      const widthPct = Math.max(MIN_BAR_WIDTH_PCT, (agentDur / effectiveTotal) * 100);

      return {
        agent,
        label: agent.agent_name ?? agent.name ?? agent.id,
        offsetPct,
        widthPct: Math.min(widthPct, 100 - offsetPct),
        status: agent.status,
      };
    });

    const ticks = Array.from({ length: TICK_COUNT + 1 }, (_, i) => ({
      pct: (i / TICK_COUNT) * 100,
      label: formatDuration((i / TICK_COUNT) * effectiveTotal),
    }));

    return { bars: computedBars, totalDuration: effectiveTotal, tickMarks: ticks };
  }, [agents, stageDurationSeconds, stageStartTime, now]);

  if (bars.length === 0) {
    return (
      <div className="text-xs text-maf-text-muted px-2 py-3">
        No timing data available.
      </div>
    );
  }

  const chartHeight = bars.length * (BAR_HEIGHT_PX + ROW_GAP_PX) + ROW_GAP_PX;

  return (
    <div className="flex flex-col gap-1">
      {/* Header */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs font-medium text-maf-text-muted">
          Execution Timeline
        </span>
        <span className="text-[10px] text-maf-text-dim">
          Total: {formatDuration(totalDuration)}
        </span>
      </div>

      {/* Chart area */}
      <div className="flex">
        {/* Agent name labels */}
        <div
          className="flex flex-col shrink-0"
          style={{ width: LABEL_WIDTH_PX, gap: ROW_GAP_PX, paddingTop: ROW_GAP_PX }}
        >
          {bars.map((bar) => (
            <button
              key={bar.agent.id}
              className="text-xs text-maf-text truncate text-left hover:text-maf-accent transition-colors px-1"
              style={{ height: BAR_HEIGHT_PX, lineHeight: `${BAR_HEIGHT_PX}px` }}
              onClick={() => select('agent', bar.agent.id)}
              title={bar.label}
              aria-label={`Navigate to agent ${bar.label}`}
            >
              {bar.label}
            </button>
          ))}
        </div>

        {/* Bars area */}
        <div className="relative flex-1 bg-maf-surface/50 rounded overflow-hidden" style={{ height: chartHeight }}>
          {/* Tick grid lines */}
          {tickMarks.map((tick) => (
            <div
              key={tick.pct}
              className="absolute top-0 bottom-0 border-l border-maf-border/30"
              style={{ left: `${tick.pct}%` }}
            />
          ))}

          {/* Agent bars */}
          {bars.map((bar, i) => {
            const top = ROW_GAP_PX + i * (BAR_HEIGHT_PX + ROW_GAP_PX);
            const color = STATUS_COLORS[bar.status] ?? STATUS_COLORS.pending;
            const isRunning = bar.status === 'running';

            return (
              <button
                key={bar.agent.id}
                className={cn(
                  'absolute rounded-sm cursor-pointer transition-all',
                  'hover:brightness-125 hover:shadow-md',
                  isRunning && 'animate-pulse',
                )}
                style={{
                  top,
                  left: `${bar.offsetPct}%`,
                  width: `${bar.widthPct}%`,
                  height: BAR_HEIGHT_PX,
                  backgroundColor: color,
                  opacity: 0.85,
                }}
                onClick={() => select('agent', bar.agent.id)}
                title={`${bar.label}: ${formatDuration(bar.agent.duration_seconds)} | ${bar.agent.total_tokens ?? 0} tokens`}
                aria-label={`${bar.label}: ${bar.status}, ${formatDuration(bar.agent.duration_seconds)}`}
              >
                {/* Duration label inside bar if wide enough */}
                {bar.widthPct > 12 && (
                  <span className="absolute inset-0 flex items-center justify-center text-[10px] font-medium text-white/90 drop-shadow-sm">
                    {formatDuration(bar.agent.duration_seconds)}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Tick labels */}
      <div className="flex" style={{ paddingLeft: LABEL_WIDTH_PX }}>
        <div className="relative flex-1 h-4">
          {tickMarks.map((tick) => (
            <span
              key={tick.pct}
              className="absolute text-[9px] text-maf-text-dim -translate-x-1/2"
              style={{ left: `${tick.pct}%` }}
            >
              {tick.label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
