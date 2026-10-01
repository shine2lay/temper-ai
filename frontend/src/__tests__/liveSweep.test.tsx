/**
 * Every live message, at a page that is already drawing a run.
 *
 * The run page used to go blank mid-run with "h is not iterable": somewhere
 * in the live path a list that is normally there was missing, and the code
 * walked it anyway. This sweep fires every message type the engine sends,
 * with the fields the engine can leave out (and, where the engine's own
 * payload is shaped by a plugin, with a value that is not a list at all),
 * and insists the page keeps drawing.
 *
 * The event names come from temper_ai (grep for `"stage.started"` and the
 * rest) and from the store's own switch; if a new one is added, add it here.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, act, cleanup } from '@testing-library/react';
import { ReactFlowProvider } from '@xyflow/react';

import { ExecutionDAG } from '@/components/dag/ExecutionDAG';
import { LivePanel } from '@/components/live/LivePanel';
import { useExecutionStore } from '@/store/executionStore';
import type { NodeExecution, WorkflowExecution, WSEvent } from '@/types';

const RUN = 'sweep-run-0001';
const T0 = '2026-10-01T23:28:00Z';
const store = () => useExecutionStore.getState();

const node = (id: string, name: string): NodeExecution =>
  ({
    id,
    name,
    type: 'agent',
    status: 'running',
    start_time: T0,
    end_time: null,
    depends_on: [],
    agents: [],
    agent: {
      id: `a-${id}`,
      agent_name: name,
      status: 'running',
      start_time: T0,
      end_time: null,
      llm_calls: [],
      tool_calls: [],
    },
  }) as unknown as NodeExecution;

const snapshot = (): WorkflowExecution =>
  ({
    id: RUN,
    workflow_name: 'sweep',
    status: 'running',
    start_time: T0,
    nodes: [node('n-1', 'planner')],
    agent_index: [],
  }) as unknown as WorkflowExecution;

const ev = (event_type: string, data: Record<string, unknown>): WSEvent =>
  ({ type: 'event', event_type, data, timestamp: T0 }) as WSEvent;

/**
 * Every live message type, each with the leanest payload the engine can
 * send: a new node or agent carries no lists of its own, because the lists
 * only exist once the snapshot is rebuilt.
 */
const LEAN: WSEvent[] = [
  ev('workflow.started', { event_id: RUN, workflow_name: 'sweep' }),
  ev('workflow_start', { event_id: RUN }),
  ev('stage.started', { event_id: 's-new', name: 'fresh', type: 'agent' }),
  ev('stage_start', { event_id: 's-new2', name: 'fresh2' }),
  ev('agent.started', { event_id: 'ag-new', agent_name: 'fresh', parent_id: 's-new' }),
  ev('agent_start', { event_id: 'ag-new2', agent_name: 'fresh2', parent_id: 's-new2' }),
  ev('agent_output', { agent_id: 'ag-new', content: 'hello' }),
  ev('llm_call', { agent_id: 'ag-new', model: 'claude', call_id: 'c1' }),
  ev('llm.call.completed', { agent_id: 'ag-new', call_id: 'c1' }),
  ev('llm_stream_batch', { chunks: [{ agent_id: 'ag-new', content: 'hi' }] }),
  ev('llm.stream.chunk', { agent_id: 'ag-new', content: 'hi' }),
  ev('tool_call_start', { agent_id: 'ag-new', tool_name: 'bash', call_id: 't1' }),
  ev('tool.call.started', { agent_id: 'ag-new', tool_name: 'bash', call_id: 't2' }),
  ev('tool_call', { agent_id: 'ag-new', tool_name: 'bash', call_id: 't1' }),
  ev('tool.call.completed', { agent_id: 'ag-new', call_id: 't2' }),
  ev('tool.call.failed', { agent_id: 'ag-new', call_id: 't2', error: 'boom' }),
  ev('dispatch.applied', { dispatcher: 'planner', added: ['fresh'] }),
  ev('event.updated', { event_id: 's-new', status: 'completed' }),
  ev('agent.completed', { event_id: 'ag-new', status: 'completed' }),
  ev('agent.failed', { event_id: 'ag-new2', status: 'failed', error: 'boom' }),
  ev('agent_end', { agent_id: 'ag-new', status: 'completed' }),
  ev('stage.completed', { event_id: 's-new', status: 'completed' }),
  ev('stage.failed', { event_id: 's-new2', status: 'failed' }),
  ev('stage_end', { event_id: 's-new', status: 'completed' }),
  ev('workflow.completed', { event_id: RUN, status: 'completed' }),
  ev('workflow.failed', { event_id: RUN, status: 'failed' }),
  ev('workflow_end', { event_id: RUN, status: 'completed' }),
];

/**
 * The same messages with their list fields filled in wrongly: missing, null,
 * or an object where a list belongs. A websocket payload is whatever reached
 * the socket; the page may not fall over because of it.
 */
const BENT: WSEvent[] = [
  ev('llm_stream_batch', {}),
  ev('llm_stream_batch', { chunks: null }),
  ev('llm_stream_batch', { chunks: { agent_id: 'ag-new', content: 'hi' } }),
  ev('llm_stream_batch', { chunks: 'hi' }),
  ev('dispatch.applied', { dispatcher: 'planner' }),
  ev('dispatch.applied', { dispatcher: 'planner', added: null }),
  ev('dispatch.applied', { dispatcher: 'planner', added: { a: 1 } }),
  ev('dispatch.applied', { dispatcher: 'planner', added: 'fresh' }),
  ev('stage.started', { event_id: 's-bent', name: 'bent', agents: null, depends_on: null }),
  ev('stage.started', { event_id: 's-bent2', name: 'bent2', agents: {}, depends_on: {} }),
  ev('agent.started', { event_id: 'ag-bent', agent_name: 'bent', parent_id: 's-nobody' }),
  ev('tool_call', { agent_id: 'ag-bent', tool_name: 'bash', call_id: 't9', result: null }),
  ev('event.updated', { event_id: 'nobody-at-all', status: 'completed' }),
];

beforeEach(() => {
  store().reset();
  vi.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

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

function complaints(): string[] {
  const spy = console.error as unknown as { mock: { calls: unknown[][] } };
  return spy.mock.calls.map((c) => String(c[0] ?? ''));
}

describe('every live message, one at a time, at a drawing page', () => {
  for (const message of [...LEAN, ...BENT]) {
    const shape = Object.keys(message.data ?? {}).join(',') || 'nothing';
    it(`keeps drawing through ${message.event_type} (${shape})`, async () => {
      store().applySnapshot(snapshot());
      const view = renderRunView();
      await act(async () => {
        await Promise.resolve();
      });

      await act(async () => {
        store().applyEvent(message);
        await new Promise((r) => setTimeout(r, 20));
      });

      expect(view.container.querySelector('.react-flow')).toBeTruthy();
      expect(complaints().filter((c) => c.includes('is not iterable'))).toEqual([]);
    });
  }

  it('keeps drawing through all of them, in a row, on one page', async () => {
    store().applySnapshot(snapshot());
    const view = renderRunView();
    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      for (const message of [...LEAN, ...BENT]) store().applyEvent(message);
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(view.container.querySelector('.react-flow')).toBeTruthy();
    expect(complaints().filter((c) => c.includes('is not iterable'))).toEqual([]);
  });
});
