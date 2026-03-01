/**
 * Three-panel layout shell for the Studio editor.
 * Left: StagePalette | Center: StudioCanvas | Right: PropertyPanel
 * Both side panels are collapsible to maximize canvas space.
 */
import { useState, useCallback, useEffect } from 'react';
import { ReactFlowProvider } from '@xyflow/react';
import { useDesignStore } from '@/store/designStore';
import { useResolveStageAgents } from '@/hooks/useResolveStageAgents';
import { StudioHeader } from './StudioHeader';
import { ValidationBanner } from './ValidationBanner';
import { StagePalette } from './StagePalette';
import { StudioCanvas } from './StudioCanvas';
import { PropertyPanel } from './PropertyPanel';
import { StudioLoadDialog } from './StudioLoadDialog';

const LEFT_WIDTH = 240;
const RIGHT_WIDTH = 320;
const COLLAPSED_WIDTH = 28;

function CollapseToggle({
  side,
  collapsed,
  onClick,
}: {
  side: 'left' | 'right';
  collapsed: boolean;
  onClick: () => void;
}) {
  const isLeft = side === 'left';
  // Arrow points toward the panel when collapsed (expand), away when expanded (collapse)
  const arrow = collapsed
    ? isLeft ? '\u25B6' : '\u25C0'
    : isLeft ? '\u25C0' : '\u25B6';
  const title = collapsed ? 'Expand panel' : 'Collapse panel';

  return (
    <button
      onClick={onClick}
      className="absolute top-1/2 -translate-y-1/2 z-20 w-5 h-10 flex items-center justify-center rounded bg-temper-surface border border-temper-border hover:bg-temper-accent/10 hover:border-temper-accent/40 transition-colors text-[10px] text-temper-text-dim hover:text-temper-text"
      style={isLeft ? { right: -12 } : { left: -12 }}
      title={title}
      aria-label={title}
    >
      {arrow}
    </button>
  );
}

export function StudioPage() {
  const [loadDialogOpen, setLoadDialogOpen] = useState(false);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const isDirty = useDesignStore((s) => s.isDirty);
  const selectedStageName = useDesignStore((s) => s.selectedStageName);
  const selectedAgentName = useDesignStore((s) => s.selectedAgentName);

  // Auto-expand right panel when something is selected
  useEffect(() => {
    if (selectedStageName || selectedAgentName) {
      setRightCollapsed(false);
    }
  }, [selectedStageName, selectedAgentName]);

  // Fetch stage configs to resolve agent info for all stage_ref stages
  useResolveStageAgents();

  // Warn on navigation if dirty
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault();
      }
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  const onOpenLoadDialog = useCallback(() => setLoadDialogOpen(true), []);
  const toggleLeft = useCallback(() => setLeftCollapsed((c) => !c), []);
  const toggleRight = useCallback(() => setRightCollapsed((c) => !c), []);

  return (
    <ReactFlowProvider>
      <div className="flex flex-col h-full bg-temper-bg">
        <StudioHeader onOpenLoadDialog={onOpenLoadDialog} />
        <ValidationBanner />

        <div className="flex-1 flex min-h-0">
          {/* Left: Stage Palette */}
          <div
            className="shrink-0 border-r border-temper-border bg-temper-bg overflow-hidden relative transition-[width] duration-200 ease-in-out"
            style={{ width: leftCollapsed ? COLLAPSED_WIDTH : LEFT_WIDTH }}
          >
            {leftCollapsed ? (
              <div className="h-full flex flex-col items-center pt-3">
                <span
                  className="text-[10px] text-temper-text-dim"
                  style={{ writingMode: 'vertical-rl', textOrientation: 'mixed' }}
                >
                  Stages
                </span>
              </div>
            ) : (
              <StagePalette />
            )}
            <CollapseToggle side="left" collapsed={leftCollapsed} onClick={toggleLeft} />
          </div>

          {/* Center: Canvas */}
          <div className="flex-1 relative min-w-0">
            <StudioCanvas />
            <EmptyCanvasOverlay />
          </div>

          {/* Right: Property Panel */}
          <div
            className="shrink-0 overflow-hidden relative transition-[width] duration-200 ease-in-out"
            style={{ width: rightCollapsed ? COLLAPSED_WIDTH : RIGHT_WIDTH }}
          >
            {rightCollapsed ? (
              <div className="h-full flex flex-col items-center pt-3 border-l border-temper-border bg-temper-bg">
                <span
                  className="text-[10px] text-temper-text-dim"
                  style={{ writingMode: 'vertical-rl', textOrientation: 'mixed' }}
                >
                  Properties
                </span>
              </div>
            ) : (
              <PropertyPanel />
            )}
            <CollapseToggle side="right" collapsed={rightCollapsed} onClick={toggleRight} />
          </div>
        </div>

        <StudioLoadDialog open={loadDialogOpen} onOpenChange={setLoadDialogOpen} />
      </div>
    </ReactFlowProvider>
  );
}

function EmptyCanvasOverlay() {
  const stageCount = useDesignStore((s) => s.stages.length);

  if (stageCount > 0) return null;

  return (
    <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
      <div className="text-center">
        <p className="text-sm text-temper-text-muted">
          Drag stages from the left panel, or use the + buttons to create new ones
        </p>
        <p className="text-xs text-temper-text-dim mt-1">
          or load an existing workflow
        </p>
      </div>
    </div>
  );
}
