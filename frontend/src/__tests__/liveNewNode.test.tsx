/**
 * A run that grows while you watch it, drawn the whole time.
 *
 * In external mode a new node reaches the page two ways: the poll brings a
 * bigger snapshot, and the WebSocket brings the node's own start before the
 * next poll. Both land on a page that is already drawing the run — and a
 * step that arrives before the node it sits in is normal, not a mistake.
 *
 * The shapes here are the server's own (recorded off
 * `GET /api/workflows/<id>` and the WebSocket of a demo_dispatch_scripted
 * run): an agent node carries `agent`, never a filled `agents`; a node
 * started live carries only what its start event says, so it has no
 * `agents`, no `child_nodes`, and — when the engine did not write one — no
 * `depends_on`.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, act, cleanup } from '@testing-library/react';
import { ReactFlowProvider } from '@xyflow/react';

import { ExecutionDAG } from '@/components/dag/ExecutionDAG';
import { LivePanel } from '@/components/live/LivePanel';
import { useExecutionStore } from '@/store/executionStore';
import { buildFindEntries } from '@/lib/runSearch';
import { buildRoster } from '@/lib/agentRoster';
import { layoutWithElk } from '@/lib/elkLayout';
import type {
  AgentExecution,
  NodeExecution,
  WorkflowExecution,
  WSEvent,
} from '@/types';

const RUN = 'e25decb6-f08d-4018-826d-8cf7ecd4295c';
const T0 = '2026-10-01T23:28:00Z';

const store = () => useExecutionStore.getState();

function agent(id: string, name: string, status = 'running'): AgentExecution {
  return {
    id,
    agent_name: name,
    status,
    start_time: T0,
    end_time: null,
    duration_seconds: null,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    estimated_cost_usd: 0,
    total_llm_calls: 0,
    total_tool_calls: 0,
    llm_calls: [],
    tool_calls: [],
  } as unknown as AgentExecution;
}

/** An agent node as `GET /api/workflows/<id>` returns it. */
function apiAgentNode(
  id: string,
  name: string,
  over: Partial<NodeExecution> = {},
): NodeExecution {
  return {
    id,
    name,
    type: 'agent',
    status: 'running',
    start_time: T0,
    end_time: null,
    duration_seconds: null,
    cost_usd: 0,
    total_tokens: 0,
    depends_on: [],
    agents: [],
    agent: agent(`a-${id}`, name),
    ...over,
  } as unknown as NodeExecution;
}

function snapshot(nodes: NodeExecution[], status = 'running'): WorkflowExecution {
  return {
    id: RUN,
    workflow_name: 'demo_dispatch_scripted',
    status,
    start_time: T0,
    end_time: null,
    duration_seconds: null,
    nodes,
    agent_index: [],
  } as unknown as WorkflowExecution;
}

function ev(event_type: string, data: Record<string, unknown>, at = T0): WSEvent {
  return { type: 'event', event_type, data, timestamp: at } as WSEvent;
}

/** The planner alone, as the first poll of the run sees it. */
const FIRST = snapshot([apiAgentNode('n-planner', 'planner')]);

/**
 * What the engine really sends when a dispatcher adds a node, in order:
 * the dispatch, the node's start, its agent's start (parent_id = the node's
 * start event). A node start carries no `agents` and, for a dispatched node
 * whose config names no dependency, no `depends_on` either.
 */
function addNodeLive(name: string, stageId: string, agentId: string): WSEvent[] {
  return [
    ev('dispatch.applied', { dispatcher: 'planner', added: [name], event_id: `d-${name}` }),
    ev('stage.started', { event_id: stageId, name, type: 'agent', status: 'running' }),
    ev('agent.started', {
      event_id: agentId,
      agent_name: name,
      parent_id: stageId,
      status: 'running',
    }),
  ];
}

beforeEach(() => {
  store().reset();
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** The run page's canvas and live panel, mounted the way the page mounts them. */
function renderRunView() {
  return render(
    <ReactFlowProvider>
      <div className="relative w-full h-full">
        <ExecutionDAG />
        <LivePanel />
      </div>
    </ReactFlowProvider>,
  );
}

describe('a run that grows while the page is watching it', () => {
  it('keeps drawing when the WebSocket adds a node, a nested node and an agent', async () => {
    store().applySnapshot(FIRST);
    const view = renderRunView();
    await act(async () => { await Promise.resolve(); });

    await act(async () => {
      for (const e of addNodeLive('research_Tokyo', 's-tokyo', 'ag-tokyo')) store().applyEvent(e);
      // A step whose parent the page has never seen: the agent of a node
      // whose start event has not arrived (or was dropped by a reconnect).
      store().applyEvent(ev('agent.started', {
        event_id: 'ag-orphan', agent_name: 'research_Kyoto', parent_id: 's-kyoto',
        status: 'running',
      }));
      // ...and then the node it belongs to.
      store().applyEvent(ev('stage.started', {
        event_id: 's-kyoto', name: 'research_Kyoto', type: 'agent', status: 'running',
      }));
      // A node inside another node, which the graph does not draw a box for.
      store().applyEvent(ev('stage.started', {
        event_id: 's-inner', name: 'inner_check', type: 'stage', status: 'running',
        parent_id: 's-tokyo',
      }));
      await Promise.resolve();
    });

    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });

    expect(view.container.querySelector('.react-flow')).toBeTruthy();
    expect(store().stages.has('s-tokyo')).toBe(true);
    const crashed = (console.error as unknown as { mock: { calls: unknown[][] } }).mock.calls
      .filter((c) => String(c[0] ?? '').includes('is not iterable'));
    expect(crashed).toEqual([]);
  });

  it('keeps drawing when a poll brings a snapshot with nodes the page has not seen', async () => {
    store().applySnapshot(FIRST);
    const view = renderRunView();
    await act(async () => { await Promise.resolve(); });

    const grown = snapshot([
      apiAgentNode('n-planner', 'planner', {
        status: 'completed',
        child_nodes: [
          apiAgentNode('n-tokyo', 'research_Tokyo', {
            depends_on: ['planner'], dispatched_by: 'planner',
          }),
          apiAgentNode('n-kyoto', 'research_Kyoto', {
            depends_on: ['planner'], dispatched_by: 'planner',
          }),
        ],
      }),
    ]);
    await act(async () => {
      store().applySnapshot(grown);
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(view.container.querySelector('.react-flow')).toBeTruthy();
    expect(store().stages.size).toBe(3);
  });

  it('lays out, finds and rosters a node whose lists the start event never carried', async () => {
    // The parts that read a node's lists, each given a node with none of
    // them: this is the shape a live start event makes.
    const bare = {
      id: 's-bare', name: 'bare', type: 'agent', status: 'running', start_time: T0,
    } as unknown as NodeExecution;

    const laid = await layoutWithElk([bare]);
    expect(laid.nodes.map((n) => n.id)).toContain('s-bare');

    expect(() => buildFindEntries([
      { id: 's-bare', type: 'agentNode', position: { x: 0, y: 0 }, data: { stage: bare, agent: null } },
    ] as unknown as Parameters<typeof buildFindEntries>[0])).not.toThrow();

    expect(() =>
      buildRoster(new Map([['s-bare', bare]]), new Map(), new Map()),
    ).not.toThrow();
  });
});
