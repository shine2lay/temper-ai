import { ChevronDown, ChevronRight } from 'lucide-react';
import { TIMELINE } from './constants';
import { formatDuration, formatTimestamp } from '@/lib/utils';
import type { TimelineRow as TimelineRowData } from '@/hooks/useTimelineData';

interface TimelineRowProps {
  row: TimelineRowData;
  timeRange: [number, number];
  chartWidth: number;
  isCollapsed: boolean;
  onToggle: () => void;
  now: number;
  onClick?: () => void;
}

const LEVEL_INDENT: Record<string, number> = {
  workflow: 0,
  stage: 1,
  agent: 2,
};

function buildTooltip(row: TimelineRowData): string {
  const parts = [row.label, `Status: ${row.status}`];
  if (row.startTime !== null) {
    parts.push(`Start: ${formatTimestamp(new Date(row.startTime).toISOString())}`);
  }
  if (row.endTime !== null) {
    parts.push(`End: ${formatTimestamp(new Date(row.endTime).toISOString())}`);
    const durSec = (row.endTime - (row.startTime ?? row.endTime)) / 1000;
    parts.push(`Duration: ${formatDuration(durSec)}`);
  } else if (row.status === 'running') {
    parts.push('Running...');
  }
  return parts.join('\n');
}

/**
 * Single row in the Gantt chart: label on the left, time bar on the right.
 */
export function TimelineRow({
  row,
  timeRange,
  chartWidth,
  isCollapsed,
  onToggle,
  now,
  onClick,
}: TimelineRowProps) {
  const [start, end] = timeRange;
  const duration = end - start;
  const indent = (LEVEL_INDENT[row.level] ?? 0) * TIMELINE.INDENT_PX;

  // Bar position
  let barLeft = 0;
  let barWidth = 0;
  const isRunning = row.status === 'running';

  if (row.startTime !== null && duration > 0) {
    barLeft = ((row.startTime - start) / duration) * chartWidth;
    const barEnd = row.endTime !== null
      ? ((row.endTime - start) / duration) * chartWidth
      : isRunning
        ? ((now - start) / duration) * chartWidth
        : barLeft + TIMELINE.MIN_BAR_WIDTH;
    barWidth = Math.max(barEnd - barLeft, TIMELINE.MIN_BAR_WIDTH);
  }

  const fontWeight = row.level === 'workflow' ? 'font-semibold' : row.level === 'stage' ? 'font-medium' : '';
  const fontSize = row.level === 'agent' ? 'text-[11px]' : 'text-xs';

  return (
    <div
      role="row"
      aria-label={`${row.level}: ${row.label}, status: ${row.status}`}
      className={`flex items-stretch border-b border-maf-border/30 hover:bg-maf-surface/30${onClick ? ' cursor-pointer' : ''}`}
      style={{ height: TIMELINE.ROW_HEIGHT }}
      onClick={onClick}
    >
      {/* Label column */}
      <div
        className="shrink-0 flex items-center overflow-hidden"
        style={{ width: TIMELINE.LABEL_WIDTH, paddingLeft: indent + 8 }}
      >
        {/* Collapse toggle */}
        {row.hasChildren ? (
          <button
            onClick={(e) => { e.stopPropagation(); onToggle(); }}
            className="w-4 h-4 flex items-center justify-center text-maf-text-muted hover:text-maf-text shrink-0 mr-1"
            aria-expanded={!isCollapsed}
            aria-label="Toggle children"
          >
            {isCollapsed ? (
              <ChevronRight className="w-3 h-3" />
            ) : (
              <ChevronDown className="w-3 h-3" />
            )}
          </button>
        ) : (
          <span className="w-4 mr-1 shrink-0" />
        )}

        <span className={`truncate text-maf-text ${fontSize} ${fontWeight}`}>
          {row.label}
        </span>
      </div>

      {/* Bar area */}
      <div
        className="relative flex-1 min-w-0"
        style={{ width: chartWidth }}
      >
        {row.startTime !== null && (
          <div
            className="absolute top-1/2 -translate-y-1/2 rounded-sm"
            style={{
              left: barLeft,
              width: barWidth,
              height: TIMELINE.ROW_HEIGHT - 12,
              backgroundColor: row.color,
              opacity: 0.8,
            }}
            title={buildTooltip(row)}
          >
            {/* Animated right edge for running items */}
            {isRunning && (
              <div
                className="absolute right-0 top-0 bottom-0 w-2 rounded-r-sm animate-pulse"
                style={{ backgroundColor: row.color }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
