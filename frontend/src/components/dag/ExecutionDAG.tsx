import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
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
import { selectStageGroups, selectDagInfo } from '@/store/selectors';
import { useDagElements } from '@/hooks/useDagElements';
import { computeStagePositions } from '@/lib/dagLayout';
import { DAG_FIT_PADDING } from '@/lib/constants';
import { StageNode } from './StageNode';
import { AgentNodeComponent } from './AgentNodeComponent';
import { StageGroupNode } from './StageGroupNode';
import { LoopBackEdge } from './LoopBackEdge';

const nodeTypes = {
  stage: StageNode,
  agentNode: AgentNodeComponent,
  stageGroup: StageGroupNode,
};
const edgeTypes = { loopBack: LoopBackEdge };
const RELAYOUT_DELAY_MS = 150;

/**
 * Main React Flow container for the workflow execution DAG.
 *
 * Two-pass layout:
 * 1. Initial render with estimated positions (from useDagElements)
 * 2. After React Flow measures actual DOM dimensions, re-layout using
 *    real sizes so nodes never overlap.
 */
export function ExecutionDAG() {
  const computed = useDagElements();
  const { setNodes, setEdges, fitView, getNodes } = useReactFlow();
  const prevNodeCountRef = useRef(0);
  const expandedStages = useExecutionStore((s) => s.expandedStages);
  const stages = useExecutionStore((s) => s.stages);
  const agents = useExecutionStore((s) => s.agents);
  const select = useExecutionStore((s) => s.select);
  const clearSelection = useExecutionStore((s) => s.clearSelection);
  const relayoutTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const focusedNodeIndexRef = useRef<number>(-1);
  const [search, setSearch] = useState('');

  // Compute which agent IDs match the current search term.
  // Agent-type nodes use a stage name as their node id; stage-type nodes
  // are identified by their child agent ids. We track matching node ids
  // (stage names) so we can dim non-matching nodes.
  const matchingNodeIds = useCallback((): Set<string> | null => {
    const term = search.trim().toLowerCase();
    if (!term) return null;

    const matched = new Set<string>();

    // Check each agent
    for (const [, agent] of agents) {
      const haystack = [
        agent.output ?? '',
        JSON.stringify(agent.output_data ?? ''),
      ].join(' ').toLowerCase();

      if (haystack.includes(term)) {
        matched.add(agent.id);
      }
    }

    // Build a set of node ids (stage names) that contain a matching agent.
    // Note: stages map keys are execution UUIDs, but ReactFlow node IDs use stage.name.
    const matchedNodeIds = new Set<string>();
    for (const [, stage] of stages) {
      const nodeAgents = stage.agents ?? (stage.agent ? [stage.agent] : []);
      const hasMatch = nodeAgents.some((a: { id: string }) => matched.has(a.id));
      if (hasMatch && stage.name) matchedNodeIds.add(stage.name);
    }

    return matchedNodeIds;
  }, [search, agents, stages]);

  // Apply opacity to ReactFlow nodes based on search matches.
  useEffect(() => {
    const matchIds = matchingNodeIds();
    if (matchIds === null) {
      // No active search — restore full opacity on all nodes
      setNodes((prev) =>
        prev.map((n) => {
          if (n.style?.opacity === 1 || n.style?.opacity === undefined) return n;
          const { opacity: _removed, ...rest } = n.style ?? {};
          return { ...n, style: rest };
        }),
      );
      return;
    }

    setNodes((prev) =>
      prev.map((n) => {
        // For child nodes (parentId set), match based on parent stage
        const matchId = n.parentId ?? n.id;
        const isMatch = matchIds.has(matchId);
        const targetOpacity = isMatch ? 1 : 0.25;
        if (n.style?.opacity === targetOpacity) return n;
        return { ...n, style: { ...n.style, opacity: targetOpacity } };
      }),
    );
  }, [search, matchingNodeIds, setNodes]);

  const matchCount = useCallback((): number => {
    const ids = matchingNodeIds();
    return ids ? ids.size : 0;
  }, [matchingNodeIds]);

  const onInit: OnInit = useCallback(() => {
    setTimeout(() => fitView({ padding: DAG_FIT_PADDING }), 50);
  }, [fitView]);

  // Push computed nodes/edges into React Flow's internal store
  useEffect(() => {
    setNodes(computed.nodes);
    setEdges(computed.edges);
  }, [computed.nodes, computed.edges, setNodes, setEdges]);

  /**
   * Re-layout using actual DOM-measured dimensions from React Flow.
   * Reads measured.width/height from each node and recomputes positions
   * so no nodes overlap.
   */
  const relayoutFromMeasurements = useCallback(() => {
    const rfNodes = getNodes();
    if (rfNodes.length === 0) return;

    // Collect actual measured sizes
    const measuredSizes = new Map<string, { width: number; height: number }>();
    let allMeasured = true;
    for (const node of rfNodes) {
      if (node.measured?.width && node.measured?.height) {
        measuredSizes.set(node.id, {
          width: node.measured.width,
          height: node.measured.height,
        });
      } else {
        allMeasured = false;
      }
    }

    if (!allMeasured || measuredSizes.size === 0) return;

    // Re-compute positions with actual dimensions
    const stageGroups = selectStageGroups(stages);
    const dagInfo = selectDagInfo();
    const newPositions = computeStagePositions(
      stageGroups,
      dagInfo,
      expandedStages,
      measuredSizes,
    );

    // Auto-resize group containers based on actual child measurements
    const containerUpdates = new Map<string, { width: number; height: number }>();
    for (const node of rfNodes) {
      if (node.type === 'stageGroup') {
        const children = rfNodes.filter((n) => n.parentId === node.id);
        if (children.length > 0 && children.every((c) => c.measured?.width && c.measured?.height)) {
          let maxRight = 0;
          let maxBottom = 0;
          for (const child of children) {
            maxRight = Math.max(maxRight, child.position.x + (child.measured?.width ?? 0));
            maxBottom = Math.max(maxBottom, child.position.y + (child.measured?.height ?? 0));
          }
          const pad = 28;
          containerUpdates.set(node.id, {
            width: Math.max(maxRight + pad, 350),
            height: Math.max(maxBottom + pad, 200),
          });
        }
      }
    }

    // Check if positions or sizes changed to avoid unnecessary updates
    let changed = false;
    const updatedNodes = rfNodes.map((node) => {
      const containerSize = containerUpdates.get(node.id);
      const pos = newPositions.get(node.id);
      let updated = node;

      // Resize group containers
      if (containerSize) {
        const currentW = typeof node.style?.width === 'number' ? node.style.width : 0;
        const currentH = typeof node.style?.height === 'number' ? node.style.height : 0;
        if (Math.abs(containerSize.width - currentW) > 5 || Math.abs(containerSize.height - currentH) > 5) {
          changed = true;
          updated = { ...updated, style: { ...updated.style, width: containerSize.width, height: containerSize.height } };
        }
      }

      // Reposition
      if (pos && (Math.abs(node.position.x - pos.x) > 1 || Math.abs(node.position.y - pos.y) > 1)) {
        changed = true;
        updated = { ...updated, position: { x: pos.x, y: pos.y } };
      }

      return updated;
    });

    if (changed) {
      setNodes(updatedNodes);
      // Don't fitView here — preserve the user's current zoom/pan.
      // Only reposition nodes to avoid overlap.
    }
  }, [getNodes, stages, expandedStages, setNodes]);

  // Listen for dimension changes from React Flow and trigger re-layout
  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const hasDimensionChange = changes.some((c) => c.type === 'dimensions');
      if (hasDimensionChange) {
        // Debounce: multiple dimension changes fire in quick succession
        clearTimeout(relayoutTimer.current);
        relayoutTimer.current = setTimeout(relayoutFromMeasurements, RELAYOUT_DELAY_MS);
      }
    },
    [relayoutFromMeasurements],
  );

  // Auto-fit when new stages appear
  useEffect(() => {
    if (computed.nodes.length > 0 && computed.nodes.length !== prevNodeCountRef.current) {
      prevNodeCountRef.current = computed.nodes.length;
      const timer = setTimeout(() => fitView({ padding: DAG_FIT_PADDING, duration: 300 }), 100);
      return () => clearTimeout(timer);
    }
  }, [computed.nodes.length, fitView]);

  // Re-layout when stages are expanded or collapsed — but keep current viewport.
  useEffect(() => {
    const timer = setTimeout(() => {
      relayoutFromMeasurements();
    }, RELAYOUT_DELAY_MS);
    return () => clearTimeout(timer);
  }, [expandedStages, relayoutFromMeasurements]);

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
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div
      className="w-full h-full"
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
        fitView
        minZoom={0.1}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        nodesDraggable
        nodesConnectable={false}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} />
        <Controls position="bottom-left" />
        <MiniMap
          nodeColor="#1e2a4a"
          maskColor="rgba(15, 23, 41, 0.7)"
          position="bottom-right"
          style={{ width: 120, height: 80, opacity: 0.4 }}
          className="hover:!opacity-100 transition-opacity duration-200"
        />
        <Panel position="top-right">
          <div className="flex items-center gap-1.5">
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search outputs..."
              aria-label="Search agent outputs"
              className="px-2 py-1 text-xs bg-temper-surface border border-temper-border rounded text-temper-text placeholder:text-temper-text-dim w-48 focus:outline-none focus:border-temper-accent"
            />
            {search.trim() && (
              <span className="text-[10px] text-temper-text-muted whitespace-nowrap">
                {matchCount()} {matchCount() === 1 ? 'match' : 'matches'}
              </span>
            )}
          </div>
        </Panel>
      </ReactFlow>
    </div>
  );
}
