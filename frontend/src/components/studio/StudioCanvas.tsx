/**
 * ReactFlow wrapper for the Studio visual editor.
 * Supports edge drawing (dependency + loop-back), drag-to-add from palette,
 * node selection, and auto-layout.
 */
import { useCallback, useEffect, useMemo, type DragEvent } from 'react';
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  Panel,
  useReactFlow,
  type OnConnect,
  type OnInit,
  type NodeChange,
  type EdgeChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useDesignStore, defaultDesignStage, type DesignStage } from '@/store/designStore';
import { useDesignElements } from '@/hooks/useDesignElements';
import { DesignStageNode } from './DesignStageNode';
import { DataFlowEdge } from './DataFlowEdge';
import { WorkflowSettingsOverlay } from './WorkflowSettingsOverlay';

const nodeTypes = { designStage: DesignStageNode };
const edgeTypes = { dataFlow: DataFlowEdge };

function generateStageName(existingNames: Set<string>, base: string): string {
  if (!existingNames.has(base)) return base;
  let n = 1;
  while (existingNames.has(`${base}_${n}`)) n++;
  return `${base}_${n}`;
}

export function StudioCanvas() {
  const { nodes, edges } = useDesignElements();
  const { setNodes, setEdges, fitView, screenToFlowPosition } = useReactFlow();

  const addStage = useDesignStore((s) => s.addStage);
  const addDependency = useDesignStore((s) => s.addDependency);
  const removeDependency = useDesignStore((s) => s.removeDependency);
  const setLoopBack = useDesignStore((s) => s.setLoopBack);
  const selectStage = useDesignStore((s) => s.selectStage);
  const setNodePosition = useDesignStore((s) => s.setNodePosition);
  const stages = useDesignStore((s) => s.stages);

  const existingNames = useMemo(
    () => new Set(stages.map((s) => s.name)),
    [stages],
  );

  // Push derived nodes/edges into React Flow
  useEffect(() => {
    setNodes(nodes);
    setEdges(edges);
  }, [nodes, edges, setNodes, setEdges]);

  const onInit: OnInit = useCallback(() => {
    setTimeout(() => fitView({ padding: 0.15, minZoom: 0.5, maxZoom: 1.2 }), 50);
  }, [fitView]);

  // Handle new connections: right→left = dependency, bottom→top = loop-back
  const onConnect: OnConnect = useCallback(
    (connection) => {
      if (!connection.source || !connection.target) return;
      if (connection.source === connection.target) return;

      if (
        connection.sourceHandle === 'bottom' &&
        connection.targetHandle === 'top'
      ) {
        setLoopBack(connection.source, connection.target, null);
      } else {
        addDependency(connection.source, connection.target);
      }
    },
    [addDependency, setLoopBack],
  );

  // Handle edge removal
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      for (const change of changes) {
        if (change.type !== 'remove') continue;
        const edgeId = change.id;
        if (edgeId.startsWith('dep|')) {
          const [, source, target] = edgeId.split('|');
          if (source && target) {
            removeDependency(source, target);
          }
        } else if (edgeId.startsWith('loop|')) {
          const [, source] = edgeId.split('|');
          if (source) {
            setLoopBack(source, null, null);
          }
        }
      }
    },
    [removeDependency, setLoopBack],
  );

  // Track node position changes from dragging
  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      for (const change of changes) {
        if (change.type === 'position' && change.position && change.dragging === false) {
          setNodePosition(change.id, change.position.x, change.position.y);
        }
      }
    },
    [setNodePosition],
  );

  // Handle drag-over from palette
  const onDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  // Handle drop from palette — create new stage at drop position
  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      const stageRef = e.dataTransfer.getData('application/studio-stage-ref');
      const stageName = e.dataTransfer.getData('application/studio-stage-name');
      if (!stageName) return;

      const position = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      const name = generateStageName(existingNames, stageName);

      const newStage: DesignStage = {
        ...defaultDesignStage(name),
        stage_ref: stageRef || null,
      };

      addStage(newStage);
      setNodePosition(name, position.x, position.y);
      selectStage(name);
    },
    [addStage, setNodePosition, selectStage, existingNames, screenToFlowPosition],
  );

  // Click on canvas background = deselect
  const onPaneClick = useCallback(() => {
    selectStage(null);
  }, [selectStage]);

  return (
    <ReactFlow
      defaultNodes={[]}
      defaultEdges={[]}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onInit={onInit}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onPaneClick={onPaneClick}
      minZoom={0.3}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
      nodesDraggable
      nodesConnectable
      deleteKeyCode="Delete"
    >
      <Background variant={BackgroundVariant.Dots} gap={24} size={1} />
      <Controls position="bottom-left" />
      <MiniMap
        nodeColor="#1e2a4a"
        maskColor="rgba(15, 23, 41, 0.7)"
        position="bottom-right"
      />
      <Panel position="top-left" className="!m-3">
        <WorkflowSettingsOverlay />
      </Panel>
    </ReactFlow>
  );
}
