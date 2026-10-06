/**
 * A run waiting on a person is still going (SW-79).
 *
 * The server says "waiting" while a wait is open for a person -- a gate, a step's question, a
 * resumed Pi run's recovery question -- however the run's earlier attempts ended. The run page
 * reads that as a run still going: a ticking timer and a Cancel button, not the Re-run of a
 * finished one, and not the red of the attempt that failed before it.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useExecutionStore } from '@/store/executionStore';
import { WorkflowHeader } from '@/components/layout/WorkflowHeader';
import { isGoing } from '@/lib/runStatus';
import type { ExecutionStatus } from '@/types';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/authFetch', () => ({ authFetch }));

function showRun(status: ExecutionStatus) {
  act(() => {
    useExecutionStore.setState({
      workflow: {
        ...(useExecutionStore.getState().workflow ?? ({} as never)),
        id: 'run-1',
        workflow_name: 'pi_talk',
        status,
        start_time: '2026-10-05T20:00:00Z',
      },
    });
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WorkflowHeader />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockResolvedValue({ ok: true, json: async () => ({ execution_id: 'run-1', gates: [] }) });
});

describe('isGoing', () => {
  it('counts a run at work or waiting on a person as going', () => {
    expect(isGoing('running')).toBe(true);
    expect(isGoing('waiting')).toBe(true);
  });

  it('counts an ended run, or none, as not going', () => {
    for (const status of ['completed', 'failed', 'cancelled', 'interrupted', '', null, undefined]) {
      expect(isGoing(status)).toBe(false);
    }
  });
});

describe('the run header of a resumed run', () => {
  it('shows a run waiting at its recovery question as waiting, with Cancel and no Re-run', () => {
    showRun('waiting');

    expect(screen.getByText('waiting')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Cancel/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Re-run/ })).not.toBeInTheDocument();
  });

  it('shows the run as failed once the owner stops it, with Re-run and no Cancel', () => {
    showRun('failed');

    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Cancel/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Re-run/ })).toBeInTheDocument();
  });
});
