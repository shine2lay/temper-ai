/**
 * A real EPD build, replayed at the real run page.
 *
 * The fixture is a run that actually happened (`epd_build_replay`,
 * d336a9e3-9063-4b56-a667-6fe8ffe8c566), exported with
 * `scripts/export_run_fixture.py`: the snapshot `GET /api/workflows/<id>`
 * returns, and every event the engine recorded, in the order it recorded
 * them (its thousands of repetitive model and tool calls sampled down).
 *
 * The page is opened on a part-grown run — the snapshot, with only the
 * events up to that point applied — and then fed everything that came
 * after, which is exactly what watching a live run is: stages and agents
 * turning up one at a time, each carrying only what its own event says.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, act, cleanup } from '@testing-library/react';
import { ReactFlowProvider } from '@xyflow/react';

import { ExecutionDAG } from '@/components/dag/ExecutionDAG';
import { LivePanel } from '@/components/live/LivePanel';
import { useExecutionStore } from '@/store/executionStore';
import type { WorkflowExecution, WSEvent } from '@/types';
import fixture from './fixtures/epdBuildRun.json';

interface StoredEvent {
  id: string;
  type: string;
  parent_id: string | null;
  execution_id: string;
  status: string | null;
  data: Record<string, unknown> | null;
  timestamp: string;
}

const snapshot = fixture.snapshot as unknown as WorkflowExecution;
const stored = fixture.events as unknown as StoredEvent[];

/**
 * A stored event as the websocket sends it: the engine broadcasts the row's
 * own id as `event_id` inside `data`, with `parent_id` and `status`
 * alongside — that is how a node's start event and its agents are tied
 * together on the page.
 */
function asMessage(e: StoredEvent): WSEvent {
  return {
    type: 'event',
    event_type: e.type,
    execution_id: e.execution_id,
    timestamp: e.timestamp,
    data: {
      ...(e.data ?? {}),
      event_id: e.id,
      parent_id: e.parent_id ?? undefined,
      ...(e.status ? { status: e.status } : {}),
    },
  } as unknown as WSEvent;
}

const store = () => useExecutionStore.getState();

beforeEach(() => {
  store().reset();
  vi.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function complaints(): string[] {
  const spy = console.error as unknown as { mock: { calls: unknown[][] } };
  return spy.mock.calls.map((c) => c.map((x) => String(x)).join(' '));
}

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

describe('a real EPD build, watched as it grows', () => {
  it('keeps drawing through every event of the run, one at a time', async () => {
    store().applySnapshot(snapshot);
    const view = renderRunView();
    await act(async () => {
      await Promise.resolve();
    });

    for (const e of stored) {
      await act(async () => {
        store().applyEvent(asMessage(e));
        await Promise.resolve();
      });
      expect(
        complaints().filter((c) => c.includes('is not iterable')),
        `the page broke on ${e.type}`,
      ).toEqual([]);
      expect(view.container.querySelector('.react-flow'), `nothing left to draw after ${e.type}`)
        .toBeTruthy();
    }
  });

  it('keeps drawing when the page is opened part-grown and fed the rest', async () => {
    // Only the first quarter of the run has happened when the page opens;
    // everything else arrives live, including nodes the snapshot never had.
    const cut = Math.floor(stored.length / 4);
    const early = {
      ...snapshot,
      status: 'running',
      end_time: null,
      nodes: (snapshot.nodes ?? []).slice(0, 1),
    } as WorkflowExecution;

    store().applySnapshot(early);
    const view = renderRunView();
    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      for (const e of stored.slice(0, cut)) store().applyEvent(asMessage(e));
      await new Promise((r) => setTimeout(r, 30));
    });
    const half = store().stages.size;

    await act(async () => {
      for (const e of stored.slice(cut)) store().applyEvent(asMessage(e));
      await new Promise((r) => setTimeout(r, 30));
    });

    // It really grew while the page was open, and the page is still there.
    expect(store().stages.size).toBeGreaterThan(half);
    expect(view.container.querySelector('.react-flow')).toBeTruthy();
    expect(complaints().filter((c) => c.includes('is not iterable'))).toEqual([]);
  });

  it('keeps drawing when a later poll brings the finished run', async () => {
    store().applySnapshot({
      ...snapshot,
      status: 'running',
      nodes: (snapshot.nodes ?? []).slice(0, 1),
    } as WorkflowExecution);
    const view = renderRunView();
    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      for (const e of stored) store().applyEvent(asMessage(e));
      await new Promise((r) => setTimeout(r, 30));
    });
    await act(async () => {
      store().applySnapshot(snapshot);
      await new Promise((r) => setTimeout(r, 30));
    });

    expect(view.container.querySelector('.react-flow')).toBeTruthy();
    expect(complaints().filter((c) => c.includes('is not iterable'))).toEqual([]);
  });
});
