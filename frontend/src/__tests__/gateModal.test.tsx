/**
 * The gate modal: what a run parked at a human gate shows, and what the
 * approval carries back.
 *
 * The gate API is stubbed at `authFetch`, so these tests cover the modal and
 * the hook together — what lands in the POST body is the contract the
 * backend's `normalise_response` reads.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, act, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useExecutionStore } from '@/store/executionStore';
import { GateModal } from '@/components/layout/GateModal';
import type { WaitingGate } from '@/hooks/useGates';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/authFetch', () => ({ authFetch }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

const EXECUTION_ID = 'run-1';

const GATE: WaitingGate = {
  node_name: 'approve',
  status: 'waiting',
  event_id: 'ev-1',
  upstream: [
    {
      node: 'draft',
      output: 'Two options for the schema.',
      full_output: '{"summary": "Two options for the schema.", "questions": ["Which schema?"]}',
      structured_output: null,
    },
  ],
  questions: [
    {
      id: 'q1',
      question: 'Which schema?',
      header: 'Schema',
      detail: 'This decides the migration.',
      options: [
        { label: 'Single table', description: 'Simpler', preview: 'CREATE TABLE runs (...)' },
        { label: 'Two tables' },
      ],
      node: 'draft',
    },
  ],
};

/** Answer the gate POST, and serve `gates` until it is approved. */
function stubGates(gate: WaitingGate | null) {
  const posted: { url: string; body: unknown }[] = [];
  let current = gate;
  authFetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      posted.push({ url, body: JSON.parse(String(init.body)) });
      current = null;
      return { ok: true, json: async () => ({ status: 'approved' }) };
    }
    return {
      ok: true,
      json: async () => ({ execution_id: EXECUTION_ID, gates: current ? [current] : [] }),
    };
  });
  return posted;
}

function renderModal() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <GateModal executionId={EXECUTION_ID} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  authFetch.mockReset();
  Object.values(toast).forEach((fn) => fn.mockReset());
  act(() => {
    useExecutionStore.setState({
      workflow: { ...(useExecutionStore.getState().workflow ?? ({} as never)), status: 'running' },
      gateNodeName: null,
    });
  });
});

describe('GateModal', () => {
  it('opens by itself when a run is parked at a gate', async () => {
    stubGates(GATE);
    renderModal();

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(/Approval needed/)).toBeInTheDocument();
    expect(screen.getByText('approve')).toBeInTheDocument();
  });

  it('shows what the previous node produced and what it asked', async () => {
    stubGates(GATE);
    renderModal();

    await screen.findByRole('dialog');
    expect(screen.getByText('draft')).toBeInTheDocument();
    expect(screen.getByText('Two options for the schema.')).toBeInTheDocument();
    expect(screen.getByText('Which schema?')).toBeInTheDocument();
    expect(screen.getByText('This decides the migration.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Single table/ })).toBeInTheDocument();
  });

  it('keeps the raw output out of the way behind "Full output"', async () => {
    stubGates(GATE);
    renderModal();

    await screen.findByRole('dialog');
    // The prose is on screen; the JSON it came from is only a disclosure away,
    // not printed above the form that was built from it.
    expect(screen.getByText('Two options for the schema.')).toBeInTheDocument();
    const raw = screen.getByText(/"questions":/);
    expect(raw.closest('details')).not.toBeNull();
    expect(screen.getByText('Full output')).toBeInTheDocument();
  });

  it('says nothing about a full output when the whole output is shown', async () => {
    stubGates({
      ...GATE,
      upstream: [{ node: 'draft', output: 'a plain plan', structured_output: null }],
    });
    renderModal();

    await screen.findByRole('dialog');
    expect(screen.queryByText('Full output')).not.toBeInTheDocument();
  });

  it('reveals an option preview only once it is chosen', async () => {
    stubGates(GATE);
    renderModal();

    await screen.findByRole('dialog');
    expect(screen.queryByText(/CREATE TABLE runs/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Single table/ }));
    expect(screen.getByText(/CREATE TABLE runs/)).toBeInTheDocument();
  });

  it('will not approve until a question with options is answered', async () => {
    stubGates(GATE);
    renderModal();

    await screen.findByRole('dialog');
    const approve = screen.getByRole('button', { name: /Approve & continue/ });
    expect(approve).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /Two tables/ }));
    expect(approve).toBeEnabled();
  });

  it('sends the chosen option, the typed answer and the free text', async () => {
    const posted = stubGates(GATE);
    renderModal();

    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('button', { name: /Single table/ }));
    fireEvent.change(screen.getByLabelText('Which schema?'), { target: { value: 'but index created_at' } });
    fireEvent.change(screen.getByLabelText(/Anything else/), { target: { value: 'ship it tonight' } });
    fireEvent.click(screen.getByRole('button', { name: /Approve & continue/ }));

    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0].url).toBe(`/api/runs/${EXECUTION_ID}/approve/approve`);
    expect(posted[0].body).toEqual({
      response: 'ship it tonight',
      answers: [
        {
          id: 'q1',
          question: 'Which schema?',
          selected: ['Single table'],
          custom: 'but index created_at',
        },
      ],
      event_id: 'ev-1',
      request_id: expect.any(String),
    });
  });

  it('keeps one choice for a single-select question', async () => {
    const posted = stubGates(GATE);
    renderModal();

    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('button', { name: /Single table/ }));
    fireEvent.click(screen.getByRole('button', { name: /Two tables/ }));
    fireEvent.click(screen.getByRole('button', { name: /Approve & continue/ }));

    await waitFor(() => expect(posted).toHaveLength(1));
    expect((posted[0].body as { answers: { selected: string[] }[] }).answers[0].selected).toEqual([
      'Two tables',
    ]);
  });

  it('keeps every choice for a multi-select question', async () => {
    const posted = stubGates({
      ...GATE,
      questions: [{ ...GATE.questions[0], multiSelect: true }],
    });
    renderModal();

    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('button', { name: /Single table/ }));
    fireEvent.click(screen.getByRole('button', { name: /Two tables/ }));
    fireEvent.click(screen.getByRole('button', { name: /Approve & continue/ }));

    await waitFor(() => expect(posted).toHaveLength(1));
    expect((posted[0].body as { answers: { selected: string[] }[] }).answers[0].selected).toEqual([
      'Single table',
      'Two tables',
    ]);
  });

  it('approves with an empty body when there is nothing to ask', async () => {
    const posted = stubGates({ ...GATE, questions: [] });
    renderModal();

    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('button', { name: /Approve & continue/ }));

    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0].body).toEqual({
      response: '',
      answers: [],
      event_id: 'ev-1',
      request_id: expect.any(String),
    });
  });

  it('names the wait it answers and sends a new request id with each click', async () => {
    const posted: { body: { event_id: string; request_id: string } }[] = [];
    authFetch.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        posted.push({ body: JSON.parse(String(init.body)) });
        // The first click fails for a reason that is not a refusal; the gate stays open.
        return posted.length === 1
          ? { ok: false, status: 502, json: async () => ({ detail: 'Bad gateway' }) }
          : { ok: true, json: async () => ({ status: 'approved' }) };
      }
      return { ok: true, json: async () => ({ gates: [{ ...GATE, questions: [] }] }) };
    });
    renderModal();

    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('button', { name: /Approve & continue/ }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Could not approve: Bad gateway'));
    fireEvent.click(screen.getByRole('button', { name: /Approve & continue/ }));

    await waitFor(() => expect(posted).toHaveLength(2));
    expect(posted.map((p) => p.body.event_id)).toEqual(['ev-1', 'ev-1']);
    expect(posted[0].body.request_id).toBeTruthy();
    expect(posted[1].body.request_id).toBeTruthy();
    expect(posted[0].body.request_id).not.toBe(posted[1].body.request_id);
  });

  it('says plainly when the wait was already answered or replaced (409), and closes it', async () => {
    const refusal = {
      message:
        'Already answered by Ana (Slack) at 2026-10-03T20:41:00+00:00: the approval at ' +
        "'approve' round 1 is closed, so this one changed nothing.",
      reason: 'already_answered',
      event_id: 'ev-1',
    };
    let open = true;
    authFetch.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        open = false;
        return { ok: false, status: 409, json: async () => ({ detail: refusal }) };
      }
      return { ok: true, json: async () => ({ gates: open ? [{ ...GATE, questions: [] }] : [] }) };
    });
    renderModal();

    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('button', { name: /Approve & continue/ }));

    await waitFor(() => expect(toast.warning).toHaveBeenCalledWith(refusal.message));
    expect(toast.error).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('says the run needs Resume when it approved a run that is not running', async () => {
    const message =
      'Approved and kept. The run is not running, so it needs Resume; when it comes back it goes ' +
      'on with this answer without asking again.';
    authFetch.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        return { ok: true, json: async () => ({ status: 'approved', needs_resume: true, message }) };
      }
      return { ok: true, json: async () => ({ gates: [{ ...GATE, questions: [] }] }) };
    });
    renderModal();

    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('button', { name: /Approve & continue/ }));

    await waitFor(() => expect(toast.warning).toHaveBeenCalledWith(message));
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('opens the wait it was asked for when two steps of one name are waiting', async () => {
    const first = { ...GATE, event_id: 'ev-a', path: 'build.approve', questions: [] };
    const second = { ...GATE, event_id: 'ev-b', path: 'ship.approve', round: 2, questions: [] };
    const posted: { body: { event_id: string } }[] = [];
    authFetch.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        posted.push({ body: JSON.parse(String(init.body)) });
        return { ok: true, json: async () => ({ status: 'approved' }) };
      }
      return { ok: true, json: async () => ({ gates: [first, second] }) };
    });
    renderModal();

    // The first opens by itself; "Later" brings up the next one, the other step of that name.
    expect(await screen.findByRole('dialog')).not.toHaveTextContent('round 2');
    fireEvent.click(screen.getByRole('button', { name: 'Later' }));
    await waitFor(() => expect(screen.getByRole('dialog')).toHaveTextContent('round 2'));
    fireEvent.click(screen.getByRole('button', { name: /Approve & continue/ }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0].body.event_id).toBe('ev-b');

    // A card naming the first one's path opens that one, and approves that one.
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    act(() => useExecutionStore.getState().openGate('build.approve'));
    expect(screen.getByRole('dialog')).not.toHaveTextContent('round 2');
    fireEvent.click(screen.getByRole('button', { name: /Approve & continue/ }));
    await waitFor(() => expect(posted).toHaveLength(2));
    expect(posted[1].body.event_id).toBe('ev-a');
  });

  it('"Later" leaves the run waiting and does not reopen on the next poll', async () => {
    const posted = stubGates(GATE);
    renderModal();

    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('button', { name: 'Later' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(posted).toHaveLength(0);
    // The gate is still waiting; the modal must not spring back on its own.
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('reopens a dismissed gate when its card asks for it', async () => {
    stubGates(GATE);
    renderModal();

    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('button', { name: 'Later' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    act(() => useExecutionStore.getState().openGate('approve'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('stays out of the way when no gate is waiting', async () => {
    stubGates(null);
    renderModal();

    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
