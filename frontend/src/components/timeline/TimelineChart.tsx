import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useTimelineData } from '@/hooks/useTimelineData';
import { useExecutionStore } from '@/store/executionStore';
import { TimelineAxis } from './TimelineAxis';
import { TimelineRow } from './TimelineRow';
import { TIMELINE } from './constants';

/**
 * Hierarchical Gantt chart: workflow > stages > agents.
 * Stages can be collapsed/expanded to hide agent rows.
 */
export function TimelineChart() {
  const { rows, timeRange } = useTimelineData();
  const workflow = useExecutionStore((s) => s.workflow);
  const select = useExecutionStore((s) => s.select);
  const isRunning = workflow?.status === 'running';
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [chartWidth, setChartWidth] = useState(0);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [now, setNow] = useState(Date.now());
  const containerRef = useRef<HTMLDivElement>(null);

  // Responsive width via ResizeObserver
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const width = entry.contentRect.width - TIMELINE.LABEL_WIDTH;
        setChartWidth(Math.max(width, 0));
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Tick "now" forward while workflow is running
  useEffect(() => {
    if (!isRunning) return;
    const id = setInterval(() => setNow(Date.now()), TIMELINE.NOW_TICK_INTERVAL_MS);
    return () => clearInterval(id);
  }, [isRunning]);

  const toggleCollapse = useCallback((id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  // Filter out children of collapsed parents (memoized with index for O(n))
  const visibleRows = useMemo(() => {
    const rowById = new Map(rows.map((r) => [r.id, r]));
    return rows.filter((row) => {
      let pid = row.parentId;
      while (pid !== null) {
        if (collapsed.has(pid)) return false;
        pid = rowById.get(pid)?.parentId ?? null;
      }
      return true;
    });
  }, [rows, collapsed]);

  if (rows.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-2">
        <span className="text-2xl">&#x23F1;</span>
        <p className="text-temper-text-muted text-sm">Waiting for first stage to start</p>
        <p className="text-xs text-temper-text-dim">Timeline bars will appear as stages and agents begin executing</p>
      </div>
    );
  }

  const zoomedWidth = chartWidth * zoomLevel;
  const MIN_ZOOM = 0.5;
  const MAX_ZOOM = 10;
  const ZOOM_STEP = 1.5;

  return (
    <div ref={containerRef} className="flex-1 flex flex-col min-h-0">
      {/* Zoom controls */}
      <div className="flex items-center gap-2 px-4 py-1.5 border-b border-temper-border/30 shrink-0">
        <span className="text-xs text-temper-text-muted">Zoom</span>
        <button
          onClick={() => setZoomLevel((z) => Math.max(MIN_ZOOM, z / ZOOM_STEP))}
          className="px-1.5 py-0.5 rounded text-xs bg-temper-surface text-temper-text-muted hover:text-temper-text"
          aria-label="Zoom out"
        >
          &minus;
        </button>
        <span className="text-xs text-temper-text-muted font-mono w-10 text-center">
          {Math.round(zoomLevel * 100)}%
        </span>
        <button
          onClick={() => setZoomLevel((z) => Math.min(MAX_ZOOM, z * ZOOM_STEP))}
          className="px-1.5 py-0.5 rounded text-xs bg-temper-surface text-temper-text-muted hover:text-temper-text"
          aria-label="Zoom in"
        >
          +
        </button>
        <button
          onClick={() => setZoomLevel(1)}
          className="px-1.5 py-0.5 rounded text-xs text-temper-text-muted hover:text-temper-text"
        >
          Reset
        </button>
      </div>

      {/* Scrollable timeline area */}
      <div className="flex-1 min-h-0 overflow-auto relative">
        <TimelineAxis
          timeRange={timeRange}
          chartWidth={zoomedWidth}
          isRunning={!!isRunning}
          now={now}
        />
        <div className="min-h-0">
          {visibleRows.map((row) => (
            <TimelineRow
              key={row.id}
              row={row}
              timeRange={timeRange}
              chartWidth={zoomedWidth}
              isCollapsed={collapsed.has(row.id)}
              onToggle={() => toggleCollapse(row.id)}
              now={now}
              onClick={() => select(row.level as 'workflow' | 'stage' | 'agent', row.entityId)}
            />
          ))}
        </div>
        {isRunning && zoomedWidth > 0 && (() => {
          const [start, end] = timeRange;
          const duration = end - start;
          if (duration <= 0) return null;
          const nowX = ((now - start) / duration) * zoomedWidth;
          if (nowX < 0 || nowX > zoomedWidth) return null;
          return (
            <div
              className="absolute top-0 bottom-0 w-px bg-temper-accent/40 pointer-events-none z-10"
              style={{ left: TIMELINE.LABEL_WIDTH + nowX }}
            />
          );
        })()}
      </div>
    </div>
  );
}
