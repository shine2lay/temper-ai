/**
 * "Pi switched off": what the run page says about a parked Pi run while the
 * Pi switch is off (M4 SW-32). The run waits with any answer kept and carries
 * on once the switch is back on, so the page must say why it waits instead of
 * leaving it to look stuck. The server says it in words (runner/parked.py);
 * the header shows the badge and keeps the words on hover.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useExecutionStore } from '@/store/executionStore';
import { WorkflowHeader } from '@/components/layout/WorkflowHeader';
import type { WorkflowExecution } from '@/types';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/authFetch', () => ({ authFetch }));

const NOTE =
  'Pi switched off: this run waits, with any answer kept, and carries on once the Pi switch ' +
  '(TEMPER_PI_AGENT) is back on';

function renderHeader(workflow: Partial<WorkflowExecution>) {
  act(() => {
    useExecutionStore.setState({
      workflow: {
        ...(useExecutionStore.getState().workflow ?? ({} as never)),
        id: 'run-1',
        workflow_name: 'team_wf',
        status: 'waiting',
        pi_switched_off: undefined,
        ...workflow,
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

describe('the "Pi switched off" badge', () => {
  it('says a parked Pi run waits for the Pi switch, with the server\'s words on hover', () => {
    renderHeader({ pi_switched_off: NOTE });

    const badge = screen.getByText('Pi switched off');
    expect(badge.getAttribute('title')).toBe(NOTE);
  });

  it('is not there for any other run', () => {
    renderHeader({});

    expect(screen.queryByText('Pi switched off')).toBeNull();
  });
});
