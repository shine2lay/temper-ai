import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  Panel,
  useReactFlow,
  type OnInit,
  type NodeChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useExecutionStore } from '@/store/executionStore';
import { useDagElements } from '@/hooks/useDagElements';
import { useRunFind, type RunFind } from '@/hooks/useRunFind';
import { DAG_FIT_MIN_ZOOM, DAG_FIT_PADDING } from '@/lib/constants';
import { RunFindBar } from './RunFindBar';
import { StageNode } from './StageNode';
import { AgentNodeComponent } from './AgentNodeComponent';
import { StageGroupNode } from './StageGroupNode';
import { LoopBackEdge } from './LoopBackEdge';
import { DispatchEdge } from './DispatchEdge';
import { RoutedEdge } from './RoutedEdge';

const STORAGE_KEY_HIDE_SKIPPED = 'temper-dag-hide-skipped';

/** How faint a node goes when the find bar is not pointing at it. */
const FIND_DIM_OPACITY = 0.18;

const nodeTypes = {
  stage: StageNode,
  agentNode: AgentNodeComponent,
  stageGroup: StageGroupNode,
};
const edgeTypes = {
  loopBack: LoopBackEdge,
  dispatch: DispatchEdge,
  routed: RoutedEdge,
};

/**
 * Main React Flow container for the workflow execution DAG.
 *
 * Two-pass layout:
 * 1. Initial render with estimated positions (from useDagElements)
 * 2. After React Flow measures actual DOM dimensions, re-layout using
 *    real sizes so nodes never overlap.
 */
export function ExecutionDAG() {
  // Skipped nodes are shown by default: a branch that a condition skipped is
  // part of what happened, and both the header's stage count and the Timeline
  // list it. Users who prefer the compact graph can hide them; the choice
  // sticks.
  const [hideSkipped, setHideSkipped] = useState(
    () => localStorage.getItem(STORAGE_KEY_HIDE_SKIPPED) === '1',
  );
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_HIDE_SKIPPED, hideSkipped ? '1' : '0');
  }, [hideSkipped]);

  const computed = useDagElements(hideSkipped);
  const { setNodes, setEdges, fitView } = useReactFlow();
  const prevLayoutRef = useRef('');
  const userMovedRef = useRef(false);
  const [legendOpen, setLegendOpen] = useState(false);
  const select = useExecutionStore((s) => s.select);
  const clearSelection = useExecutionStore((s) => s.clearSelection);
  const setHoveredNodeId = useExecutionStore((s) => s.setHoveredNodeId);
  const focusedNodeIndexRef = useRef<number>(-1);

  // The find bar: search, stepping, the trouble jump and the status filter.
  const find = useRunFind(computed.nodes);
  // The keyboard listener is hung on the window once; it reads the live find
  // through a ref so it is not torn down and rebuilt on every keystroke.
  const findRef = useRef<RunFind>(find);
  findRef.current = find;

  const checkpointPreview = useExecutionStore((s) => s.checkpointPreview);
  const setCheckpointPreview = useExecutionStore((s) => s.setCheckpointPreview);

  // `/` puts the cursor in the search box, `n` and `shift+n` step through the
  // matches, Escape gives the whole run back. Nothing fires while you are
  // typing somewhere else on the page.
  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        !!target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable);
      const current = findRef.current;

      if (event.key === 'Escape') {
        if (current.query || current.status !== 'all' || current.focusedId) current.clear();
        return;
      }
      if (typing || event.metaKey || event.ctrlKey || event.altKey) return;

      if (event.key === '/') {
        event.preventDefault();
        current.inputRef.current?.focus();
        current.inputRef.current?.select();
        return;
      }
      if (event.key.toLowerCase() === 'n') {
        event.preventDefault();
        current.step(event.shiftKey ? -1 : 1);
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const onInit: OnInit = useCallback(() => {
    setTimeout(() => fitView({ padding: DAG_FIT_PADDING, minZoom: DAG_FIT_MIN_ZOOM }), 50);
  }, [fitView]);

  // Push computed nodes/edges into React Flow's internal store. Split
  // into two effects so a hover-only edge restyle (computed.edges
  // changes, computed.nodes stays referentially stable) doesn't
  // re-call setNodes — that triggers React Flow to re-measure node
  // dimensions, which in turn jitters layout slightly.
  //
  // Each node keeps the size React Flow last measured for it. A node object
  // without `measured` is one React Flow has never seen: it drops the
  // node's handle positions and draws none of its edges until a
  // ResizeObserver measures it again -- so every status change blanked
  // every edge for a frame or more. With `measured` it reuses the handles,
  // and still re-measures any node whose size really changed.
  useEffect(() => {
    setNodes((prev) => {
      const measured = new Map(prev.map((n) => [n.id, n.measured]));
      return computed.nodes.map((n) => {
        const m = measured.get(n.id);
        return m?.width && m?.height ? { ...n, measured: m } : n;
      });
    });
  }, [computed.nodes, setNodes]);
  useEffect(() => {
    setEdges(computed.edges);
  }, [computed.edges, setEdges]);

  // One dimming pass over whatever is on the canvas: the checkpoint preview
  // when there is one, otherwise the find bar. It runs after the push above
  // (same commit, declared later), so nodes arriving from a live update are
  // dimmed too instead of flashing back to full.
  //
  // Nothing is removed — a run you cannot see whole is a run you cannot read.
  const { lit, focusedId } = find;
  useEffect(() => {
    setNodes((prev) =>
      prev.map((node) => {
        let opacity = 1;
        if (checkpointPreview) {
          const id = node.parentId ?? node.id;
          opacity =
            checkpointPreview.completedNodes.has(id) || checkpointPreview.failedNodes.has(id)
              ? 1
              : 0.2;
        } else if (lit) {
          opacity = lit.has(node.id) ? 1 : FIND_DIM_OPACITY;
        }
        const onIt = !!focusedId && node.id === focusedId;
        const className = onIt
          ? `${(node.className ?? '').replace(/\s*run-find-current/g, '')} run-find-current`.trim()
          : (node.className ?? '').replace(/\s*run-find-current/g, '').trim() || undefined;
        if (node.style?.opacity === opacity && node.className === className) return node;
        return { ...node, className, style: { ...node.style, opacity } };
      }),
    );
  }, [computed.nodes, lit, focusedId, checkpointPreview, setNodes]);

  /**
   * Layout is now driven entirely by ELK in `useDagElements`. The old
   * "render with estimates → measure DOM → recompute" two-pass dance
   * is gone; ELK does its own size-aware layout in one async call.
   */

  // ELK gives us final positions + container sizes + edge routing in
  // one async pass via useDagElements, so we no longer need the
  // legacy "render-with-estimates → measure DOM → relayout" two-pass
  // dance. onNodesChange is a no-op now (kept as a stub so React Flow
  // doesn't lose the interactive position-on-drag controlled mode).
  const onNodesChange = useCallback((_changes: NodeChange[]) => {
    // Intentionally empty — ELK is the source of truth for layout.
  }, []);

  // Auto-fit whenever the layout changes, not just when the node count does.
  // ELK resolves sizes and positions asynchronously, so fitting on count
  // alone ran before the final geometry existed and left nodes cut off at
  // the edges of the viewport. Once the user pans or zooms, their view is
  // left alone.
  const layoutSignature = useMemo(
    () =>
      computed.nodes
        .map((n) => `${n.id}:${Math.round(n.position?.x ?? 0)},${Math.round(n.position?.y ?? 0)}`)
        .join('|'),
    [computed.nodes],
  );

  useEffect(() => {
    if (computed.nodes.length === 0) return;
    if (userMovedRef.current) return;
    // While the find bar holds a node, the view belongs to it: a live update
    // must not yank the page back to the whole run mid-search.
    if (focusedId) return;
    if (layoutSignature === prevLayoutRef.current) return;
    prevLayoutRef.current = layoutSignature;
    const timer = setTimeout(() => fitView({ padding: DAG_FIT_PADDING, duration: 300, minZoom: DAG_FIT_MIN_ZOOM }), 120);
    return () => clearTimeout(timer);
  }, [layoutSignature, computed.nodes.length, focusedId, fitView]);

  // React Flow passes the originating event only for user gestures;
  // programmatic fitView calls pass none.
  const onMoveStart = useCallback((event: unknown) => {
    if (event) userMovedRef.current = true;
  }, []);

  /**
   * Keyboard navigation for the DAG container.
   * Tab/Shift+Tab: cycle focus through stage nodes.
   * Enter: select the currently focused stage.
   * Escape: clear selection.
   */
  const onContainerKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      const stageNodes = computed.nodes.filter((n) => n.type === 'stage');
      if (stageNodes.length === 0) return;

      if (e.key === 'Tab') {
        e.preventDefault();
        const dir = e.shiftKey ? -1 : 1;
        const next = (focusedNodeIndexRef.current + dir + stageNodes.length) % stageNodes.length;
        focusedNodeIndexRef.current = next;
        // Focus the DOM node for the stage
        const nodeEl = document.querySelector<HTMLElement>(
          `[data-id="${stageNodes[next].id}"] [role="button"]`,
        );
        nodeEl?.focus();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        clearSelection();
        focusedNodeIndexRef.current = -1;
      } else if (e.key === 'Enter' && focusedNodeIndexRef.current >= 0) {
        const focused = stageNodes[focusedNodeIndexRef.current];
        if (focused) {
          e.preventDefault();
          select('stage', focused.id);
        }
      }
    },
    [computed.nodes, select, clearSelection],
  );

  return (
    <div
      className="w-full h-full"
      role="group"
      tabIndex={0}
      onKeyDown={onContainerKeyDown}
      aria-label="Workflow execution DAG. Use Tab to cycle through stages, Enter to select, Escape to deselect."
    >
      <ReactFlow
        defaultNodes={[]}
        defaultEdges={[]}
        onNodesChange={onNodesChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onInit={onInit}
        onMoveStart={onMoveStart}
        onNodeMouseEnter={(_, node) => setHoveredNodeId(node.id)}
        onNodeMouseLeave={() => setHoveredNodeId(null)}
        fitView
        minZoom={DAG_FIT_MIN_ZOOM}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        nodesDraggable
        nodesConnectable={false}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} />
        <Controls position="bottom-left" />
        {/* Collapsed by default: as a permanently expanded box in the corner
            it sat on top of whichever node ELK placed there. */}
        <Panel position="bottom-left" className="!bottom-28 !left-2">
          {legendOpen ? (
            <div className="flex flex-col gap-1 px-2 py-1.5 rounded bg-temper-panel/90 border border-temper-border/50 text-[10px] text-temper-text-muted">
              <button
                onClick={() => setLegendOpen(false)}
                className="flex items-center justify-between gap-3 font-medium text-temper-text-dim mb-0.5 hover:text-temper-text"
              >
                <span>Node border = status</span>
                <span aria-hidden>×</span>
              </button>
              {[
                ['border-[var(--color-temper-completed)]', 'Completed'],
                ['border-[var(--color-temper-running)]', 'Running'],
                ['border-[var(--color-temper-failed)]', 'Failed'],
                ['border-[var(--color-temper-waiting)]', 'Waiting for approval'],
                ['border-[var(--color-temper-cancelled)]', 'Cancelled'],
                ['border-[var(--color-temper-skipped)] border-dashed', 'Skipped'],
                ['border-[var(--color-temper-pending)]', 'Pending'],
              ].map(([border, label]) => (
                <div key={label} className="flex items-center gap-1.5">
                  <span className={`inline-block w-3 h-2.5 rounded-sm border-2 ${border} bg-temper-surface`} />
                  <span>{label}</span>
                </div>
              ))}
            </div>
          ) : (
            <button
              onClick={() => setLegendOpen(true)}
              className="px-2 py-1 rounded bg-temper-panel/90 border border-temper-border/50 text-[10px] text-temper-text-muted hover:text-temper-text"
            >
              Legend
            </button>
          )}
        </Panel>
        <MiniMap
          nodeColor="var(--temper-minimap-node)"
          maskColor="var(--temper-minimap-mask)"
          position="bottom-right"
          style={{ width: 120, height: 80 }}
          className="temper-minimap-opacity hover:!opacity-100 transition-opacity duration-200"
        />
        <Panel position="top-right">
          <div className="flex flex-col items-end gap-1.5">
            {checkpointPreview && (
              <div className="flex items-center gap-2 px-2.5 py-1.5 bg-amber-500/15 border border-amber-500/30 rounded text-amber-700 dark:text-amber-400 text-xs">
                <span>Checkpoint #{checkpointPreview.sequence}</span>
                <span className="text-[10px] text-amber-700/70 dark:text-amber-400/70">
                  {checkpointPreview.completedNodes.size} completed
                  {checkpointPreview.failedNodes.size > 0 && `, ${checkpointPreview.failedNodes.size} failed`}
                </span>
                <button
                  onClick={() => setCheckpointPreview(null)}
                  className="ml-1 text-amber-700/60 hover:text-amber-700 dark:text-amber-400/60 dark:hover:text-amber-400 transition-colors"
                  aria-label="Clear checkpoint preview"
                >
                  ✕
                </button>
              </div>
            )}
            <div className="flex items-center gap-1.5">
              <label className="flex items-center gap-1 px-2 py-1 rounded bg-temper-surface border border-temper-border text-[10px] text-temper-text-muted cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={!hideSkipped}
                  onChange={(e) => setHideSkipped(!e.target.checked)}
                  className="accent-[var(--color-temper-accent)]"
                />
                Show skipped
              </label>
              <RunFindBar find={find} />
            </div>
          </div>
        </Panel>
      </ReactFlow>
    </div>
  );
}
