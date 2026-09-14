import { TIMELINE } from './constants';

interface TimelineAxisProps {
  timeRange: [number, number];
  chartWidth: number;
  isRunning: boolean;
  now: number;
}

const TICK_COUNT = 6;

function formatAxisTime(ms: number): string {
  // Local time, like every other timestamp in the app. The axis used to
  // render UTC while the detail panels rendered local, so the same event
  // appeared at two different clock times depending on where you looked.
  const d = new Date(ms);
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  const s = String(d.getSeconds()).padStart(2, '0');
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
      className="relative border-b border-temper-border"
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
          <div className="w-px h-2 bg-temper-border" />
          <span className="text-[9px] text-temper-text-dim mt-0.5 whitespace-nowrap">
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
