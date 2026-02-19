import { TIMELINE } from './constants';

interface TimelineAxisProps {
  timeRange: [number, number];
  chartWidth: number;
  isRunning: boolean;
  now: number;
}

const TICK_COUNT = 6;

function formatAxisTime(ms: number): string {
  const d = new Date(ms);
  const h = String(d.getUTCHours()).padStart(2, '0');
  const m = String(d.getUTCMinutes()).padStart(2, '0');
  const s = String(d.getUTCSeconds()).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

/**
 * Top time axis with tick marks and optional "now" marker.
 */
export function TimelineAxis({
  timeRange,
  chartWidth,
  isRunning,
  now,
}: TimelineAxisProps) {
  const [start, end] = timeRange;
  const duration = end - start;
  if (duration <= 0 || chartWidth <= 0) return null;

  const ticks: Array<{ x: number; label: string }> = [];
  for (let i = 0; i <= TICK_COUNT; i++) {
    const t = start + (duration * i) / TICK_COUNT;
    const x = ((t - start) / duration) * chartWidth;
    ticks.push({ x, label: formatAxisTime(t) });
  }

  const nowX = isRunning ? ((now - start) / duration) * chartWidth : null;

  return (
    <div
      className="relative border-b border-maf-border"
      style={{
        height: TIMELINE.AXIS_HEIGHT,
        marginLeft: TIMELINE.LABEL_WIDTH,
        width: chartWidth,
      }}
    >
      {ticks.map((tick, i) => (
        <div
          key={i}
          className="absolute top-0 flex flex-col items-center"
          style={{ left: tick.x, transform: 'translateX(-50%)' }}
        >
          <div className="w-px h-2 bg-maf-border" />
          <span className="text-[9px] text-maf-text-dim mt-0.5 whitespace-nowrap">
            {tick.label}
          </span>
        </div>
      ))}

      {/* "Now" marker */}
      {nowX !== null && nowX >= 0 && nowX <= chartWidth && (
        <div className="timeline-now-cursor" style={{ left: nowX }} />
      )}
    </div>
  );
}
