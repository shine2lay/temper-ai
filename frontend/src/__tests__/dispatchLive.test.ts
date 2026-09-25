/**
 * A run whose nodes are created while it runs, as the dashboard sees it.
 *
 * The event sequence is the one the server sent for ui_dispatch_rounds
 * (recorded off the WebSocket): the dispatcher's `dispatch.applied` comes
 * first, then each added node's start, its agent's start (parent_id = the
 * node's start event), the agent's completion (a new event whose parent_id
 * is the agent's start) and finally an `event.updated` closing the node.
 *
 * Before these were handled, every node added live stayed "running" until
 * the run ended, drew as an empty pill with no edge to its dispatcher, and
 * a REST refresh collapsed the counts to the one top-level node.
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { snapshotFingerprint } from '@/hooks/useInitialData';
import { useExecutionStore } from '@/store/executionStore';
import type { NodeExecution, WorkflowExecution, WSEvent } from '@/types';

const T0 = '2026-09-24T20:00:00Z';

function ev(event_type: string, data: Record<string, unknown>, timestamp = T0): WSEvent {
  return { type: 'event', event_type, data, timestamp };
}

function node(id: string, name: string, extra: Partial<NodeExecution> = {}): NodeExecution {
  return {
    id,
    name,
    type: 'agent',
    status: 'running',
    depends_on: [],
    ...extra,
  } as NodeExecution;
}

function workflow(nodes: NodeExecution[], status = 'running'): WorkflowExecution {
  return {
    id: 'run-1',
    workflow_name: 'ui_dispatch_rounds',
    status,
    start_time: T0,
    end_time: null,
    duration_seconds: null,
    nodes,
  } as unknown as WorkflowExecution;
}

const store = () => useExecutionStore.getState();

/** One dispatched node's whole life on the WebSocket. */
function runChild(name: string, stageId: string, agentId: string, dispatcher = 'round') {
  store().applyEvent(ev('dispatch.applied', { dispatcher, added: [name], event_id: `d-${name}` }));
  store().applyEvent(ev('stage.started', {
    event_id: stageId, name, type: 'agent', depends_on: [], status: 'running',
  }));
  store().applyEvent(ev('agent.started', {
    event_id: agentId, agent_name: 'ui_child_slow', parent_id: stageId, status: 'running',
  }));
}

function finishChild(stageId: string, agentId: string) {
  store().applyEvent(ev('agent.completed', {
    event_id: `done-${agentId}`, parent_id: agentId, agent_name: 'ui_child_slow',
    status: 'completed', output: 'ok', duration_seconds: 12,
  }, '2026-09-24T20:00:12Z'));
  store().applyEvent(ev('event.updated', {
    event_id: stageId, status: 'completed', duration_seconds: 12, cost_usd: 0, total_tokens: 0,
  }, '2026-09-24T20:00:12Z'));
}

beforeEach(() => {
  store().reset();
  store().applySnapshot(workflow([node('round-1', 'round', { status: 'completed' })]));
});

describe('a node added while the run is live', () => {
  it('is tied to the dispatcher that added it, though it starts after the dispatch', () => {
    runChild('r1_alpha', 's-a', 'a-a');
    expect(store().stages.get('s-a')?.dispatched_by).toBe('round');
    expect(store().stages.get('round-1')?.dispatched_children).toEqual(['r1_alpha']);
  });

  it('draws its agent: the agent is found by the parent_id of its start', () => {
    runChild('r1_alpha', 's-a', 'a-a');
    const stage = store().stages.get('s-a')!;
    expect(stage.agent?.id).toBe('a-a');
    expect(stage.agents?.map((a) => a.id)).toEqual(['a-a']);
  });

  it('stops running when the engine closes it, not when the run ends', () => {
    runChild('r1_alpha', 's-a', 'a-a');
    finishChild('s-a', 'a-a');

    const stage = store().stages.get('s-a')!;
    expect(stage.status).toBe('completed');
    expect(stage.end_time).toBe('2026-09-24T20:00:12Z');

    const agent = store().agents.get('a-a')!;
    expect(agent.status).toBe('completed');
    expect(agent.end_time).toBe('2026-09-24T20:00:12Z');
    // The completion's own id is not the agent's.
    expect(store().agents.has('done-a-a')).toBe(false);
  });

  it('ends the run from its update event', () => {
    store().applyEvent(ev('event.updated', { event_id: 'run-1', status: 'completed' }));
    expect(store().workflow?.status).toBe('completed');
  });
});

describe('a REST refresh while nodes are being dispatched', () => {
  /** What the API returns: each dispatched node nested in its dispatcher. */
  function nested(childStatus: string): WorkflowExecution {
    const kid = (id: string, name: string, agentId: string) => node(id, name, {
      status: childStatus as NodeExecution['status'],
      dispatched_by: 'round',
      agent: { id: agentId, agent_name: 'ui_child_slow', status: childStatus },
    } as unknown as Partial<NodeExecution>);
    return workflow([
      node('round-1', 'round', {
        status: 'completed',
        agent: { id: 'a-round', agent_name: 'ui_dispatch_round', status: 'completed' },
        child_nodes: [kid('s-a', 'r1_alpha', 'a-a'), kid('s-b', 'r1_bravo', 'a-b')],
        dispatched_children: ['r1_alpha', 'r1_bravo'],
      } as unknown as Partial<NodeExecution>),
    ]);
  }

  it('keeps every node and agent, not just the top level', () => {
    store().applySnapshot(nested('running'));
    expect([...store().stages.keys()]).toEqual(['round-1', 's-a', 's-b']);
    expect([...store().agents.keys()].sort()).toEqual(['a-a', 'a-b', 'a-round']);
    expect(store().stages.get('round-1')?.child_nodes).toBeUndefined();
  });

  it('does not put back "running" on a node the WebSocket already closed', () => {
    runChild('r1_alpha', 's-a', 'a-a');
    finishChild('s-a', 'a-a');
    store().applySnapshot(nested('running'));
    expect(store().stages.get('s-a')?.status).toBe('completed');
    expect(store().agents.get('a-a')?.status).toBe('completed');
  });

  it('keeps a node that started after the poll was taken', () => {
    runChild('r2_alpha', 's-late', 'a-late', 'round_2');
    store().applySnapshot(nested('running'));
    expect(store().stages.get('s-late')?.name).toBe('r2_alpha');
  });

  it('opens nothing on its own: a fresh page has no selection', () => {
    store().reset();
    store().applySnapshot(nested('running'));
    expect(store().selection).toBeNull();
  });

  it('keeps what the user selected', () => {
    store().applySnapshot(nested('running'));
    store().select('stage', 's-b');
    store().applySnapshot(nested('completed'));
    expect(store().selection).toEqual({ type: 'stage', id: 's-b' });
  });

  it('is noticed by the poll when only a nested node changed', () => {
    expect(snapshotFingerprint(nested('running'))).not.toBe(snapshotFingerprint(nested('completed')));
  });
});
