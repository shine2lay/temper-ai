/**
 * The comparison table, on data that does not move.
 *
 * The "differs" marker used to be tested only through the end-to-end test,
 * which started two real runs and asserted the exact text of a row label.
 * Whether two runs take the same tenth of a second is a coin toss, so the
 * marker appeared at random and the test failed at random. The behaviour is
 * pinned here instead, with runs whose numbers are whatever the test says.
 */
import { render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CompareView } from '@/pages/CompareView';

const run = (over: Record<string, unknown>) => ({
  execution_id: 'x',
  workflow_name: 'smoke_test',
  status: 'completed',
  start_time: '2026-09-29T10:00:00',
  duration_seconds: 1.2,
  total_tokens: 100,
  total_cost_usd: 0.01,
  total_llm_calls: 1,
  total_tool_calls: 0,
  nodes: [{ name: 'first', status: 'completed', duration_seconds: 0.5, cost_usd: 0.01 }],
  ...over,
});

function show(a: Record<string, unknown>, b: Record<string, unknown>) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) =>
    new Response(JSON.stringify(String(url).endsWith('/a') ? a : b), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
  ));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/compare?ids=a,b']}>
        <CompareView />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CompareView', () => {
  beforeEach(() => vi.unstubAllGlobals());

  it('names every row, whatever the numbers are', async () => {
    show(run({ execution_id: 'a' }), run({ execution_id: 'b', duration_seconds: 9.9 }));

    for (const label of ['Status', 'Started', 'Duration', 'Tokens', 'Cost']) {
      expect(await screen.findByRole('rowheader', { name: new RegExp(`^${label}`) })).toBeTruthy();
    }
  });

  it('marks the rows whose values disagree, and only those', async () => {
    show(
      run({ execution_id: 'a', duration_seconds: 1.2, total_tokens: 100 }),
      run({ execution_id: 'b', duration_seconds: 9.9, total_tokens: 100 }),
    );

    // Wait for the data, not just the table: the rows are drawn before the
    // runs arrive, and an empty row differs from nothing.
    await screen.findByText('9.9s');

    const duration = screen.getByRole('rowheader', { name: /^Duration/ });
    expect(within(duration).queryByText('differs')).toBeTruthy();

    const tokens = screen.getByRole('rowheader', { name: /^Tokens/ });
    expect(within(tokens).queryByText('differs')).toBeNull();
  });

  it('shows the union of the nodes, saying which run lacks one', async () => {
    show(
      run({ execution_id: 'a' }),
      run({
        execution_id: 'b',
        nodes: [{ name: 'second', status: 'completed', duration_seconds: 0.4, cost_usd: 0 }],
      }),
    );

    expect(await screen.findByRole('rowheader', { name: 'first' })).toBeTruthy();
    expect(screen.getByRole('rowheader', { name: 'second' })).toBeTruthy();
    expect(screen.getAllByText('not in this run')).toHaveLength(2);
  });

  it('reads a start time without a zone as UTC, not as local time', async () => {
    // The API returns some times bare and some with an offset. Appending "Z"
    // blindly turned the second kind into "Invalid Date" on this very row.
    show(
      run({ execution_id: 'a', start_time: '2026-09-29T10:00:00' }),
      run({ execution_id: 'b', start_time: '2026-09-29T10:00:00+00:00' }),
    );

    await screen.findAllByText(/2026/);
    const started = screen.getByRole('rowheader', { name: /^Started/ });
    const row = started.closest('tr')!;
    const [first, second] = within(row).getAllByRole('cell');
    expect(first.textContent).not.toMatch(/Invalid/);
    expect(second.textContent).toEqual(first.textContent);
    expect(within(started).queryByText('differs')).toBeNull();
  });
});
