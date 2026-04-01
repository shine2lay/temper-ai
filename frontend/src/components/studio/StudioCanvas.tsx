/**
 * ReactFlow wrapper for the Studio visual editor.
 * Supports edge drawing (dependency + loop-back), drag-to-add from palette,
 * node selection, and auto-layout.
 */
import { useCallback, useEffect, useMemo, useState, type DragEvent, type MouseEvent as ReactMouseEvent } from 'react';
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  Panel,
  useReactFlow,
  applyNodeChanges,
  applyEdgeChanges,
  type OnConnect,
  type OnInit,
  type NodeChange,
  type EdgeChange,
  type Node,
  type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useDesignStore, defaultDesignStage, type DesignStage } from '@/store/designStore';
import { useDesignElements } from '@/hooks/useDesignElements';
import { DesignStageNode } from './DesignStageNode';
import { DataFlowEdge } from './DataFlowEdge';
import { DataWireEdge } from './DataWireEdge';
import { WorkflowSettingsOverlay } from './WorkflowSettingsOverlay';

const nodeTypes = { designStage: DesignStageNode };
const edgeTypes = { dataFlow: DataFlowEdge, dataWire: DataWireEdge };

function generateStageName(existingNames: Set<string>, base: string): string {
  if (!existingNames.has(base)) return base;
  let n = 1;
  while (existingNames.has(`${base}_${n}`)) n++;
  return `${base}_${n}`;
}

export function StudioCanvas() {
  const { nodes: derivedNodes, edges: derivedEdges } = useDesignElements();
  const { fitView, screenToFlowPosition } = useReactFlow();

  const addStage = useDesignStore((s) => s.addStage);
  const addDependency = useDesignStore((s) => s.addDependency);
  const addDataWire = useDesignStore((s) => s.addDataWire);
  const removeDataWire = useDesignStore((s) => s.removeDataWire);
  const removeDependency = useDesignStore((s) => s.removeDependency);
  const setLoopBack = useDesignStore((s) => s.setLoopBack);
  const selectStage = useDesignStore((s) => s.selectStage);
  const setNodePosition = useDesignStore((s) => s.setNodePosition);
  const setAutoFocusStageName = useDesignStore((s) => s.setAutoFocusStageName);
  const stages = useDesignStore((s) => s.stages);

  const existingNames = useMemo(
    () => new Set(stages.map((s) => s.name)),
    [stages],
  );

  // Controlled nodes/edges — merge derived data with React Flow interaction state
  const [rfNodes, setRfNodes] = useState<Node[]>([]);
  const [rfEdges, setRfEdges] = useState<Edge[]>([]);

  // Sync derived nodes into RF state, preserving selection/position from RF
  useEffect(() => {
    setRfNodes((prev) => {
      const prevMap = new Map(prev.map((n) => [n.id, n]));
      return derivedNodes.map((dn) => {
        const existing = prevMap.get(dn.id);
        return {
          ...dn,
          selected: existing?.selected ?? false,
        };
      });
    });
    setRfEdges(derivedEdges);
  }, [derivedNodes, derivedEdges]);

  const onInit: OnInit = useCallback(() => {
    setTimeout(() => fitView({ padding: 0.15, minZoom: 0.5, maxZoom: 1.2 }), 50);
  }, [fitView]);

  // Handle new connections:
  // out:* → in:*  = per-field data wire
  // out:* → left  = data wire (auto-name input after output field)
  // right → left  = dependency only
  // bottom → top  = loop-back
  const onConnect: OnConnect = useCallback(
    (connection) => {
      if (!connection.source || !connection.target) return;
      if (connection.source === connection.target) return;

      const srcHandle = connection.sourceHandle ?? '';
      const tgtHandle = connection.targetHandle ?? '';

      if (srcHandle.startsWith('bottom') && tgtHandle.startsWith('top')) {
        setLoopBack(connection.source, connection.target, null);
      } else if (srcHandle.startsWith('out:')) {
        const sourceField = srcHandle.slice('out:'.length);
        const targetField = tgtHandle.startsWith('in:')
          ? tgtHandle.slice('in:'.length)
          : sourceField; // auto-name when drawing to generic "left" handle
        addDataWire(connection.source, sourceField, connection.target, targetField);
        // Select target so the new wire is immediately visible
        selectStage(connection.target);
      } else {
        // right → left: dependency + auto-wire output → input
        addDependency(connection.source, connection.target);
        addDataWire(connection.source, 'output', connection.target, `${connection.source}_output`);
        selectStage(connection.target);
      }
    },
    [addDependency, addDataWire, setLoopBack, selectStage],
  );

  // Handle edge changes (removal + selection)
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      setRfEdges((eds) => applyEdgeChanges(changes, eds));

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
        } else if (edgeId.startsWith('wire|')) {
          // wire|srcStage|srcField|targetStage|targetField
          const parts = edgeId.split('|');
          const [, srcStage, srcField, targetStage, targetField] = parts;
          if (srcStage && srcField && targetStage && targetField) {
            removeDataWire(srcStage, srcField, targetStage, targetField);
          }
        }
      }
    },
    [removeDependency, removeDataWire, setLoopBack],
  );

  // Handle all node changes: position, selection, etc.
  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      // Apply all changes to controlled state (position, selection, dimensions, etc.)
      setRfNodes((nds) => applyNodeChanges(changes, nds));

      for (const change of changes) {
        if (change.type === 'position' && change.position && change.dragging === false) {
          setNodePosition(change.id, change.position.x, change.position.y);
        }
        // Sync selection to our store
        if (change.type === 'select') {
          if (change.selected) {
            selectStage(change.id);
          }
        }
      }
    },
    [setNodePosition, selectStage],
  );

  // Handle drag-over from palette
  const onDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  // Handle drop from palette — create new stage/agent node at drop position
  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      const stageRef = e.dataTransfer.getData('application/studio-stage-ref');
      const stageName = e.dataTransfer.getData('application/studio-stage-name');
      const agentName = e.dataTransfer.getData('application/studio-agent-name');
      if (!stageName && !agentName) return;

      const position = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      const baseName = stageName || agentName || 'new_node';
      const name = generateStageName(existingNames, baseName);

      const newStage: DesignStage = {
        ...defaultDesignStage(name),
        stage_ref: stageRef || null,
        agents: agentName ? [agentName] : [],
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

  // Create a blank stage at a given flow position
  const createStageAt = useCallback(
    (x: number, y: number) => {
      const name = generateStageName(existingNames, 'new_stage');
      const newStage: DesignStage = {
        ...defaultDesignStage(name),
        stage_ref: null,
      };
      addStage(newStage);
      setNodePosition(name, x, y);
      selectStage(name);
      setAutoFocusStageName(name);
    },
    [addStage, setNodePosition, selectStage, setAutoFocusStageName, existingNames],
  );

  // Double-click on canvas background = add stage at click position
  const onDoubleClick = useCallback(
    (e: ReactMouseEvent) => {
      // Only create a stage when double-clicking the pane, not a node or edge
      const target = e.target as HTMLElement;
      if (target.closest('.react-flow__node') || target.closest('.react-flow__edge')) {
        return;
      }
      const position = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      createStageAt(position.x, position.y);
    },
    [screenToFlowPosition, createStageAt],
  );

  // "Add Stage" button — add at viewport center
  const onAddStageClick = useCallback(() => {
    const container = document.querySelector('.react-flow');
    const rect = container?.getBoundingClientRect();
    const cx = rect ? rect.left + rect.width / 2 : window.innerWidth / 2;
    const cy = rect ? rect.top + rect.height / 2 : window.innerHeight / 2;
    const position = screenToFlowPosition({ x: cx, y: cy });
    createStageAt(position.x, position.y);
  }, [screenToFlowPosition, createStageAt]);

  return (
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onInit={onInit}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onPaneClick={onPaneClick}
      onDoubleClick={onDoubleClick}
      zoomOnDoubleClick={false}
      minZoom={0.3}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
      nodesDraggable
      nodesConnectable
      elementsSelectable
      connectionRadius={20}
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
      <Panel position="bottom-center" className="!mb-4">
        <button
          onClick={onAddStageClick}
          className="px-3 py-1.5 rounded-md text-xs font-medium bg-temper-surface border border-temper-border hover:border-temper-accent/60 hover:bg-temper-accent/10 text-temper-text transition-colors shadow-sm"
        >
          + Add Stage
        </button>
      </Panel>
    </ReactFlow>
  );
}
