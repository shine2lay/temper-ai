import { useCallback, useEffect, useRef } from 'react';
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  useReactFlow,
  type OnInit,
  type NodeChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useExecutionStore } from '@/store/executionStore';
import { selectStageGroups, selectDagInfo } from '@/store/selectors';
import { useDagElements } from '@/hooks/useDagElements';
import { computeStagePositions } from '@/lib/dagLayout';
import { StageNode } from './StageNode';

const nodeTypes = { stage: StageNode };
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
  const relayoutTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const onInit: OnInit = useCallback(() => {
    setTimeout(() => fitView({ padding: 0.15 }), 50);
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

    // Check if positions actually changed to avoid unnecessary updates
    let changed = false;
    const updatedNodes = rfNodes.map((node) => {
      const pos = newPositions.get(node.id);
      if (pos && (Math.abs(node.position.x - pos.x) > 1 || Math.abs(node.position.y - pos.y) > 1)) {
        changed = true;
        return { ...node, position: { x: pos.x, y: pos.y } };
      }
      return node;
    });

    if (changed) {
      setNodes(updatedNodes);
      setTimeout(() => fitView({ padding: 0.15, duration: 300 }), 50);
    }
  }, [getNodes, stages, expandedStages, setNodes, fitView]);

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
      const timer = setTimeout(() => fitView({ padding: 0.15, duration: 300 }), 100);
      return () => clearTimeout(timer);
    }
  }, [computed.nodes.length, fitView]);

  // Re-fit + re-layout when stages are expanded or collapsed
  useEffect(() => {
    const timer = setTimeout(() => {
      relayoutFromMeasurements();
      fitView({ padding: 0.15, duration: 300 });
    }, RELAYOUT_DELAY_MS);
    return () => clearTimeout(timer);
  }, [expandedStages, fitView, relayoutFromMeasurements]);

  return (
    <ReactFlow
      defaultNodes={[]}
      defaultEdges={[]}
      onNodesChange={onNodesChange}
      nodeTypes={nodeTypes}
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
      />
    </ReactFlow>
  );
}
