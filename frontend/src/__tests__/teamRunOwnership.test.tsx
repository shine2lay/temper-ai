/**
 * H-OWN-1: the real route owner, one mounted router and seeded QueryClient.
 * Deferred fetch replies exercise the production API helpers, including URL,
 * JSON body and request_id. No hooks/components are substituted and no server runs.
 */
import { useEffect } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TeamRunView from '@/pages/team/TeamRunView';
import { teamKeys } from '@/lib/teamApi';
import type { TeamRun } from '@/types/team';
import status from '../../e2e/fixtures/team/status-on.json';
import roles from '../../e2e/fixtures/team/roles-ok.json';
import { A, B, accepted, answered, event, flow, legacy, page, type Raw } from './teamOwnershipFixtures';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const reply = (body: unknown, code = 200) => new Response(JSON.stringify(body), {
  status: code, headers: { 'content-type': 'application/json' },
});
interface Request { path: string; body?: Raw }
type Handler = (req: Request, count: number) => Promise<Response> | Response;
const clients: QueryClient[] = [];
const captures: Request[][] = [];

function rig(a = flow(A), b = flow(B), { cachedB = true }: { cachedB?: boolean } = {}) {
  const requests: Request[] = [];
  captures.push(requests);
  const handlers = new Map<string, Handler>();
  const counts = new Map<string, number>();
  const runs = new Map([[A, a], [B, b]]);
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://fictional.invalid');
    const path = url.pathname + url.search;
    const req: Request = { path, ...(init?.method === 'POST' ? { body: JSON.parse(String(init.body)) as Raw } : {}) };
    requests.push(req);
    const count = (counts.get(url.pathname) ?? 0) + 1;
    counts.set(url.pathname, count);
    const handler = handlers.get(url.pathname);
    if (handler) return handler(req, count);
    if (url.pathname === '/api/team/status') return reply(status.body);
    if (url.pathname === '/api/team/roles') return reply(roles.body);
    const id = url.pathname.split('/')[4];
    if (url.pathname.endsWith('/events')) {
      const after = Number(url.searchParams.get('after'));
      return reply(page(after < 2 ? [event(id, 1), event(id, 2)] : [], Math.max(2, after)));
    }
    if (url.pathname.endsWith('/messages') && req.body) return reply(accepted(req.body.to as string), 201);
    if (url.pathname.includes('/messages/')) return reply({ body: `Only ${id}` });
    if (/\/waits\/[^/]+\/answer$/.test(url.pathname)) return reply(answered(url.pathname.split('/')[6]));
    if (/\/api\/runs\/[^/]+\/cancel$/.test(url.pathname)) return reply({ status: 'cancelled' });
    if (/^\/api\/team\/runs\/[^/]+$/.test(url.pathname)) return reply(runs.get(id));
    throw new Error(`Unmocked request: ${path}`);
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  clients.push(client);
  client.setQueryData(teamKeys.status, status.body);
  client.setQueryData(teamKeys.roles, roles.body);
  client.setQueryData(teamKeys.run(A), a);
  if (cachedB) client.setQueryData(teamKeys.run(B), b);
  let navigateTo!: (id: string) => void;
  function Navigate() {
    const navigate = useNavigate();
    useEffect(() => { navigateTo = (id) => navigate(`/team/runs/${id}`); }, [navigate]);
    return <nav aria-label="Fixture navigation">{[A, B].map((id) =>
      <button key={id} onClick={() => navigate(`/team/runs/${id}`)}>Visit {id}</button>)}</nav>;
  }
  const show = () => render(<QueryClientProvider client={client}>
    <MemoryRouter initialEntries={[`/team/runs/${A}`]}>
      <Navigate /><Routes><Route path="/team/runs/:executionId" element={<TeamRunView />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);
  const go = async (id: string) => {
    // Route changes can also arrive from browser Back/Forward while a modal is open.
    await act(async () => { navigateTo(id); });
    await screen.findByRole('heading', { level: 1, name: `Project ${id}`, hidden: true });
  };
  const runPath = (id: string) => `/api/team/runs/${id}`;
  const posts = () => requests.filter((r) => r.body !== undefined);
  const feeds = (id: string) => requests.filter((r) => r.path.startsWith(`${runPath(id)}/events?`));
  const update = async (run: TeamRun) => {
    runs.set(run.execution_id, run);
    await act(async () => { client.setQueryData(teamKeys.run(run.execution_id), run); });
  };
  return { requests, handlers, runs, client, show, go, posts, feeds, update, runPath };
}
const composer = () => within(screen.getByRole('region', { name: 'Message a member' }));
const messageBox = () => composer().getByRole('textbox', { name: 'Message' });
async function sendMessage(text: string, to = 'lead') {
  fireEvent.change(composer().getByLabelText('To'), { target: { value: to } });
  fireEvent.change(messageBox(), { target: { value: text } });
  await act(async () => { fireEvent.click(composer().getByRole('button', { name: 'Send message' })); });
}
async function openAnswer(text?: string) {
  fireEvent.click(screen.getByRole('button', { name: 'Answer' }));
  const group = within(screen.getByTestId('glance-answer-view'));
  if (text !== undefined) fireEvent.change(group.getByRole('textbox'), { target: { value: text } });
  return group;
}
async function sendAnswer(text: string) {
  const group = await openAnswer(text);
  await act(async () => { fireEvent.click(group.getByRole('button', { name: /^Send reply$/i })); });
}
async function settle(fn: () => void) { await act(async () => { fn(); }); }
const activity = () => screen.getByRole('region', { name: 'All activity' });

// The retained stage log includes exact fictional requests, also on failing originals.
afterEach(() => {
  console.info('OWNERSHIP_REQUESTS', expect.getState().currentTestName, JSON.stringify(captures));
  cleanup();
  clients.splice(0).forEach((c) => c.clear());
  captures.length = 0;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
  window.sessionStorage.clear();
});

describe('H-OWN-1: clean same-Project journey first', () => {
  it('keeps drafts, recipient, answer words, Animate and stop reason across a same-A query update', async () => {
    const r = rig(flow(A, 'question'), flow(B, 'question'));
    r.show();
    await waitFor(() => expect(activity()).toHaveTextContent(`Only ${A}`));
    fireEvent.change(messageBox(), { target: { value: 'Unsent A draft' } });
    fireEvent.change(composer().getByLabelText('To'), { target: { value: 'checker' } });
    await openAnswer('Unsent A answer');
    const animate = screen.getByRole('switch', { name: /Animate/i });
    fireEvent.click(animate);
    const box = messageBox();
    const recipient = composer().getByLabelText('To');
    const answerBox = within(screen.getByTestId('glance-answer-view')).getByRole('textbox');
    fireEvent.click(screen.getByRole('button', { name: 'Stop project' }));
    fireEvent.change(screen.getByLabelText('Your reason'), { target: { value: 'Unsent A reason' } });
    const dialog = screen.getByRole('alertdialog');
    await r.update({ ...flow(A, 'question'), cost_usd: 106 });
    expect(box).toBeInTheDocument();
    expect(box).toHaveValue('Unsent A draft');
    expect(recipient).toHaveValue('checker');
    expect(answerBox).toHaveValue('Unsent A answer');
    expect(animate).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('alertdialog')).toBe(dialog);
    expect(screen.getByLabelText('Your reason')).toHaveValue('Unsent A reason');
    expect(r.posts()).toEqual([]);
  });

  it('no-answer retries use the exact same URL/body/request_id and count acceptance once; edits get new IDs', async () => {
    const r = rig();
    const seen = new Set<string>();
    let acceptedCount = 0;
    r.handlers.set(`${r.runPath(A)}/messages`, (req, count) => {
      if (count <= 2) throw new TypeError('fictional never accepted');
      const id = req.body!.request_id as string;
      const repeated = seen.has(id);
      if (!repeated) { seen.add(id); acceptedCount += 1; }
      return reply(accepted(req.body!.to as string, repeated), 201);
    });
    r.show();
    await sendMessage('Keep these A words');
    await screen.findByText(/Temper didn't answer. Trying again is safe/);
    await act(async () => { fireEvent.click(composer().getByRole('button', { name: 'Try again' })); });
    await act(async () => { fireEvent.click(composer().getByRole('button', { name: 'Try again' })); });
    expect(r.posts().slice(0, 3).every((p) => JSON.stringify(p) === JSON.stringify(r.posts()[0]))).toBe(true);
    expect(acceptedCount).toBe(1);
    expect(messageBox()).toHaveValue('');
    await sendMessage('New A words');
    await sendMessage('New A words', 'checker');
    expect(new Set(r.posts().map((p) => p.body!.request_id)).size).toBe(3);
    expect(r.posts().every((p) => p.path === `${r.runPath(A)}/messages`)).toBe(true);
    expect(acceptedCount).toBe(3);
  });

  it('reply-lost accepted A retry dedupes exactly once; changed body/member after no-answer allocates a new ID', async () => {
    const r = rig();
    const stored = new Set<string>();
    r.handlers.set(`${r.runPath(A)}/messages`, (req, count) => {
      const id = req.body!.request_id as string;
      const repeated = stored.has(id);
      stored.add(id); // accepted, then the reply is lost: distinct from the preceding never-accepted case
      if (count === 1 || count >= 3) throw new TypeError('fictional accepted, reply lost');
      return reply(accepted(req.body!.to as string, repeated), 201);
    });
    r.show();
    await sendMessage('Reply lost A');
    await act(async () => { fireEvent.click(composer().getByRole('button', { name: 'Try again' })); });
    expect(stored.size).toBe(1);
    expect(r.posts()[1]).toEqual(r.posts()[0]);
    await sendMessage('Other A');
    await sendMessage('Changed A');
    await sendMessage('Changed A', 'checker');
    expect(new Set(r.posts().slice(2).map((p) => p.body!.request_id)).size).toBe(3);
  });

  it('same-A answer retry keeps ID; refreshed query does not reset its sender', async () => {
    const a = flow(A, 'question');
    const r = rig(a);
    const url = `${r.runPath(A)}/waits/${a.open_waits[0].wait_id}/answer`;
    r.handlers.set(url, (_req, n) => n === 1 ? Promise.reject(new TypeError('fictional lost answer')) : reply(answered(a.open_waits[0].wait_id)));
    r.show();
    await sendAnswer('A reply');
    await screen.findByText(/Temper didn't answer/);
    await r.update({ ...a, cost_usd: 109 });
    await sendAnswer('A reply');
    expect(r.posts()[1]).toEqual(r.posts()[0]);
    expect(r.posts()[0]).toMatchObject({ path: url, body: { answer: 'reply', text: 'A reply' } });
  });

  it('same-A settings confirmation keeps its node/focus across polls; B cannot inherit it', async () => {
    const r = rig(flow(A, 'settings'), flow(B, 'settings'));
    r.show();
    const you = within(screen.getByTestId('glance-you'));
    fireEvent.click(you.getByRole('button', { name: 'Stop project' }));
    const dialog = screen.getByRole('alertdialog');
    expect(dialog).toHaveTextContent('Stop this project at the settings check?');
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    cancel.focus();
    await r.update({ ...flow(A, 'settings'), cost_usd: 120 });
    expect(screen.getByRole('alertdialog')).toBe(dialog);
    expect(cancel).toHaveFocus();
    await r.go(B);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(within(screen.getByTestId('glance-you')).getByRole('button', { name: 'Go on' })).toBeEnabled();
    expect(r.posts()).toEqual([]);
  });

  it('same-A expanded history survives poll; B independent history starts collapsed', async () => {
    const r = rig(flow(A, 'working', 15), flow(B, 'working', 15));
    for (const id of [A, B]) r.handlers.set(`${r.runPath(id)}/events`, () => reply(page(
      Array.from({ length: 15 }, (_, n) => event(id, n + 1)), 15)));
    r.show();
    await waitFor(() => expect(within(activity()).getAllByRole('listitem')).toHaveLength(12));
    fireEvent.click(within(activity()).getByRole('button', { name: /^Show older/ }));
    expect(within(activity()).getAllByRole('listitem')).toHaveLength(15);
    const first = within(activity()).getAllByRole('listitem')[0];
    await r.update({ ...flow(A, 'working', 15), cost_usd: 70 });
    expect(within(activity()).getAllByRole('listitem')[0]).toBe(first);
    expect(within(activity()).getAllByRole('listitem')).toHaveLength(15);
    await r.go(B);
    await waitFor(() => expect(activity()).toHaveTextContent(`Only ${B}`));
    expect(within(activity()).getAllByRole('listitem')).toHaveLength(12);
    expect(within(activity()).getByRole('button', { name: /^Show older/ })).toBeInTheDocument();
  });

  it('same-A feed pages, catches up, sorts and dedupes quietly after reconnect', async () => {
    const r = rig(flow(A, 'working', 4));
    r.handlers.set(`${r.runPath(A)}/events`, (req, n) => {
      const after = Number(new URL(req.path, 'http://fictional.invalid').searchParams.get('after'));
      if (n === 1) return reply(page([event(A, 2), event(A, 1)], 2, true));
      if (after === 2) return reply(page([event(A, 2), event(A, 4)], 4));
      if (after === 4 && n === 3) throw new TypeError('fictional offline');
      return reply(page([event(A, 5)], 5));
    });
    r.show();
    await waitFor(() => expect(within(activity()).getAllByRole('listitem')).toHaveLength(3));
    expect(within(activity()).getAllByRole('listitem').map((li) => li.getAttribute('data-row'))).toEqual(['a4', 'a2', 'a1']);
    expect(screen.getByTestId('glance-map')).toHaveAttribute('data-dots-launched', '0');
    await r.update(flow(A, 'working', 5));
    await waitFor(() => expect(r.feeds(A)).toHaveLength(3));
    await r.update(flow(A, 'working', 6));
    await waitFor(() => expect(within(activity()).getAllByRole('listitem')).toHaveLength(4));
    expect(screen.getByTestId('glance-map')).toHaveAttribute('data-dots-launched', '0');
    expect(r.feeds(A).map((q) => new URL(q.path, 'http://fictional.invalid').searchParams.get('after'))).toEqual(['0', '2', '4', '4', '5']);
  });
});

describe('H-OWN-1: cached A→B event ownership negatives', () => {
  it.each(['success', 'error'] as const)('pending A event %s cannot suppress B read or overwrite its overlapping seq/asOf/cursor', async (outcome) => {
    const r = rig(flow(A, 'working', 900), flow(B));
    const pending = deferred<Response>();
    r.handlers.set(`${r.runPath(A)}/events`, () => pending.promise);
    r.show();
    await waitFor(() => expect(r.feeds(A)).toHaveLength(1));
    await r.go(B);
    expect.soft(r.feeds(B)).toHaveLength(1); // B must read before A completes, not be held by A's busy ref
    await settle(() => outcome === 'success'
      ? pending.resolve(reply(page([event(A, 1, 'Late A must not appear')], 900, false, '2026-10-11T18:38:00Z')))
      : pending.reject(new TypeError('fictional late A offline')));
    await waitFor(() => expect(activity()).toHaveTextContent(`Only ${B}`));
    expect(activity()).not.toHaveTextContent('Late A must not appear');
    expect(screen.getByRole('region', { name: 'Latest' })).not.toHaveTextContent('Late A');
    const bFacts = screen.getByTestId('glance-facts').textContent;
    await r.update(flow(B, 'working', 3));
    await waitFor(() => expect(r.feeds(B)).toHaveLength(2));
    expect(r.feeds(B).map((q) => new URL(q.path, 'http://fictional.invalid').searchParams.get('after'))).toEqual(['0', '2']);
    expect(screen.getByTestId('glance-facts')).toHaveTextContent(bFacts!);
    expect(screen.getByTestId('glance-just-sent')).not.toHaveTextContent('Late A');
    expect(r.posts()).toEqual([]);
  });

  it('loaded A larger cursor cannot suppress B overlapping history; B starts at zero', async () => {
    const r = rig(flow(A, 'working', 900));
    r.handlers.set(`${r.runPath(A)}/events`, () => reply(page([event(A, 1, 'Loaded A only')], 900)));
    r.show();
    await waitFor(() => expect(activity()).toHaveTextContent('Loaded A only'));
    await r.go(B);
    await waitFor(() => expect(activity()).toHaveTextContent(`Only ${B}`));
    expect(activity()).not.toHaveTextContent('Loaded A only');
    expect(r.feeds(B)[0].path).toBe(`${r.runPath(B)}/events?after=0&limit=500`);
  });

  it('A→B→A starts a fresh owner even when the first A settles after the second A', async () => {
    const r = rig();
    const firstA = deferred<Response>();
    r.handlers.set(`${r.runPath(A)}/events`, (_req, n) => n === 1 ? firstA.promise : reply(page([event(A, 1, 'Second A history')])));
    r.show();
    await waitFor(() => expect(r.feeds(A)).toHaveLength(1));
    await r.go(B);
    await r.go(A);
    expect.soft(r.feeds(A)).toHaveLength(2);
    await settle(() => firstA.resolve(reply(page([event(A, 1, 'First A obsolete callback')], 800))));
    await waitFor(() => expect(activity()).toHaveTextContent('Second A history'));
    expect(activity()).not.toHaveTextContent('First A obsolete callback');
  });

  it('late A retry timer cannot make terminal B retry or alter B historical activity', async () => {
    const r = rig(flow(A), flow(B, 'ended'));
    r.handlers.set(`${r.runPath(A)}/events`, () => Promise.reject(new TypeError('fictional A offline')));
    r.handlers.set(`${r.runPath(B)}/events`, () => Promise.reject(new TypeError('fictional terminal B offline')));
    const retries: (() => void)[] = [];
    const realTimer = window.setTimeout.bind(window);
    vi.spyOn(window, 'setTimeout').mockImplementation(((fn: TimerHandler, delay?: number, ...args: unknown[]) => {
      if (delay === 5000 && typeof fn === 'function') {
        retries.push(() => fn(...args));
        return 90_000 + retries.length;
      }
      return realTimer(fn, delay, ...args);
    }) as typeof window.setTimeout);
    r.show();
    await waitFor(() => expect(retries).toHaveLength(1));
    await r.go(B);
    await act(async () => { await Promise.resolve(); });
    expect.soft(retries).toHaveLength(1); // terminal B must never schedule a feed retry
    await settle(() => retries.forEach((retry) => retry())); // deliver A's pending retry after navigation
    expect(r.feeds(B)).toHaveLength(1);
    expect(screen.getByTestId('glance-now-word')).toHaveTextContent('Done');
    expect(r.posts()).toEqual([]);
  });
});

describe('H-OWN-1: sender, answer, stop and child ownership negatives', () => {
  it.each(['never-accepted', 'accepted-reply-lost'] as const)('A %s retry/result/body does not migrate to same-recipient cached B', async (mode) => {
    const r = rig();
    let acceptedCount = 0;
    r.handlers.set(`${r.runPath(A)}/messages`, () => {
      if (mode === 'accepted-reply-lost') acceptedCount += 1;
      throw new TypeError(mode);
    });
    r.show();
    await sendMessage('A attempt only');
    await screen.findByText(/Temper didn't answer. Trying again is safe/);
    await r.go(B);
    expect.soft(composer().queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
    expect.soft(messageBox()).toHaveValue('');
    fireEvent.change(messageBox(), { target: { value: 'B own words' } });
    const leakedRetry = composer().queryByRole('button', { name: 'Try again' });
    if (leakedRetry) await act(async () => { fireEvent.click(leakedRetry); }); // reproduce real misdirected POST on original
    expect(r.posts().filter((p) => p.path === `${r.runPath(B)}/messages` && p.body!.body === 'A attempt only')).toEqual([]);
    await sendMessage('B own words');
    const bPost = r.posts().at(-1)!;
    expect(bPost).toMatchObject({ path: `${r.runPath(B)}/messages`, body: { to: 'lead', body: 'B own words' } });
    expect(bPost.body!.request_id).not.toBe(r.posts()[0].body!.request_id);
    expect(acceptedCount).toBe(mode === 'never-accepted' ? 0 : 1);
  });

  it.each([201, 409] as const)('late A message %s cannot alter B busy/result/draft or clear its identical text', async (code) => {
    const r = rig();
    const aReply = deferred<Response>();
    const bReply = deferred<Response>();
    r.handlers.set(`${r.runPath(A)}/messages`, () => aReply.promise);
    r.handlers.set(`${r.runPath(B)}/messages`, () => bReply.promise);
    r.show();
    await sendMessage('Identical words');
    await r.go(B);
    expect.soft(composer().queryByRole('button', { name: 'Sending…' })).not.toBeInTheDocument();
    expect.soft(messageBox()).toHaveValue('');
    fireEvent.change(messageBox(), { target: { value: 'Identical words' } });
    // Even if A is pending, B's sender must be usable independently.
    const sendB = composer().queryByRole('button', { name: 'Send message' });
    expect.soft(sendB).toBeEnabled();
    if (sendB) await act(async () => { fireEvent.click(sendB); });
    await settle(() => aReply.resolve(reply(code === 201 ? accepted() : { message: 'A refusal only' }, code)));
    expect(messageBox()).toHaveValue('Identical words');
    expect(screen.getByTestId('team-message-result')).toBeEmptyDOMElement();
    expect(composer().getByRole('button', { name: 'Sending…' })).toBeDisabled();
    expect(r.posts()).toHaveLength(2);
    await settle(() => bReply.resolve(reply(accepted(), 201)));
    expect(messageBox()).toHaveValue('');
  });

  it.each([200, 409] as const)('late A answer %s and A refresh cannot overwrite B answer state', async (code) => {
    const a = flow(A, 'question');
    const b = flow(B, 'question'); // deliberately same wait/member shape; identity is the route
    const r = rig(a, b);
    const pending = deferred<Response>();
    const refreshA = deferred<Response>();
    r.handlers.set(`${r.runPath(A)}/waits/${a.open_waits[0].wait_id}/answer`, () => pending.promise);
    r.handlers.set(r.runPath(A), (_req, n) => n === 1 ? reply(a) : refreshA.promise);
    r.show();
    await waitFor(() => expect(r.client.getQueryState(teamKeys.run(A))?.fetchStatus).toBe('idle'));
    await sendAnswer('Answer A only');
    await r.go(B);
    expect.soft(screen.getByRole('button', { name: 'Answer' })).toBeEnabled();
    await settle(() => pending.resolve(reply(code === 200 ? answered(a.open_waits[0].wait_id) : { message: 'A answer refusal only' }, code)));
    await waitFor(() => expect(r.requests.filter((q) => q.path === r.runPath(A))).toHaveLength(2));
    await settle(() => refreshA.resolve(reply({ ...a, open_waits: [] })));
    expect(document.getElementById('team-answer-result')).toBeNull();
    expect(screen.getByTestId('glance-you')).not.toHaveTextContent('A answer refusal only');
    await sendAnswer('B answer only');
    expect(r.posts().map((p) => p.path)).toEqual([
      `${r.runPath(A)}/waits/${a.open_waits[0].wait_id}/answer`,
      `${r.runPath(B)}/waits/${b.open_waits[0].wait_id}/answer`,
    ]);
    expect(r.posts()[1].body!.request_id).not.toBe(r.posts()[0].body!.request_id);
  });

  it('pending A refresh cannot clear cached B text or swap B waits/run data', async () => {
    const r = rig();
    const refreshA = deferred<Response>();
    r.handlers.set(r.runPath(A), (_req, n) => n === 1 ? reply(flow(A)) : refreshA.promise);
    r.show();
    await waitFor(() => expect(r.client.getQueryState(teamKeys.run(A))?.fetchStatus).toBe('idle'));
    await sendMessage('Accepted on A');
    await r.go(B);
    fireEvent.change(messageBox(), { target: { value: 'B draft retained' } });
    await settle(() => refreshA.resolve(reply(flow(A, 'question'))));
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(`Project ${B}`);
    expect(messageBox()).toHaveValue('B draft retained');
    expect(screen.queryByTestId('glance-answer-view')).not.toBeInTheDocument();
    expect(screen.getByTestId('team-message-result')).toBeEmptyDOMElement();
  });

  it.each([200, 403] as const)('late A stop %s cannot keep its dialog or close/replace a new B confirmation', async (code) => {
    const r = rig();
    const pending = deferred<Response>();
    r.handlers.set(`/api/runs/${A}/cancel`, () => pending.promise);
    r.show();
    fireEvent.click(screen.getByRole('button', { name: 'Stop project' }));
    fireEvent.change(screen.getByLabelText('Your reason'), { target: { value: 'Stop A only' } });
    await act(async () => { fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Stop project' })); });
    await r.go(B);
    expect.soft(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    if (!screen.queryByRole('alertdialog')) fireEvent.click(screen.getByRole('button', { name: 'Stop project' }));
    fireEvent.change(screen.getByLabelText('Your reason'), { target: { value: 'B own reason' } });
    await settle(() => pending.resolve(reply(code === 200 ? { status: 'cancelled' } : { detail: 'A stop refusal only' }, code)));
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
    expect(screen.getByLabelText('Your reason')).toHaveValue('B own reason');
    expect(screen.getByRole('alertdialog')).not.toHaveTextContent('A stop refusal only');
    expect(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Stop project' })).toBeEnabled();
    expect(r.posts()).toEqual([{ path: `/api/runs/${A}/cancel`, body: { reason: 'Stop A only' } }]);
  });

  it('old child selections, answer words and dialog do not survive A→B→A; Animate stays a deliberate session preference', async () => {
    const r = rig(flow(A, 'question'), flow(B, 'question'));
    r.show();
    fireEvent.change(messageBox(), { target: { value: 'A unsent' } });
    fireEvent.change(composer().getByLabelText('To'), { target: { value: 'checker' } });
    await openAnswer('A unsent answer');
    fireEvent.click(screen.getByRole('switch', { name: /Animate/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Stop project' }));
    await r.go(B);
    expect.soft(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect.soft(screen.queryByTestId('glance-answer-view')).not.toBeInTheDocument();
    expect.soft(messageBox()).toHaveValue('');
    expect.soft(composer().getByLabelText('To')).toHaveValue('lead');
    await r.go(A);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(screen.queryByTestId('glance-answer-view')).not.toBeInTheDocument();
    expect(messageBox()).toHaveValue('');
    expect(composer().getByLabelText('To')).toHaveValue('lead');
    expect(screen.getByRole('switch', { name: /Animate/i })).toHaveAttribute('aria-checked', 'false');
    expect(r.posts()).toEqual([]);
  });

  it('a non-messageable cached B cannot inherit A result and fabricate a composer', async () => {
    const r = rig(flow(A), flow(B, 'ended'));
    r.handlers.set(`${r.runPath(A)}/messages`, () => { throw new TypeError('fictional never accepted'); });
    r.show();
    await sendMessage('A only');
    await r.go(B);
    expect(screen.queryByRole('region', { name: 'Message a member' })).not.toBeInTheDocument();
    expect(r.posts()).toHaveLength(1);
  });
});

describe('H-OWN-1: loading, errors and both legacy/FLOW descendants', () => {
  it.each([404, 503] as const)('uncached B read %s shows only B own not-team/error view', async (code) => {
    const r = rig(flow(A), flow(B), { cachedB: false });
    const pending = deferred<Response>();
    r.handlers.set(r.runPath(B), () => pending.promise);
    r.show();
    await sendMessage('A accepted');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: `Visit ${B}` })); });
    expect(screen.getByTestId('glance-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('team-message-result')).not.toBeInTheDocument();
    await settle(() => pending.resolve(reply({ detail: `Fictional B read ${code}` }, code)));
    await screen.findByText(code === 404 ? "This run isn't a team project" : "This project couldn't be read");
    expect(r.posts()).toHaveLength(1);
  });

  it.each(['legacy→legacy', 'legacy→FLOW', 'FLOW→legacy'] as const)('%s encloses all sender/stop state, with correct old controls and URL', async (direction) => {
    const a = direction.startsWith('legacy') ? legacy(A) : flow(A);
    const b = direction.endsWith('legacy') ? legacy(B) : flow(B);
    const r = rig(a, b);
    r.handlers.set(`${r.runPath(A)}/messages`, () => { throw new TypeError('fictional legacy no-answer'); });
    r.show();
    await sendMessage('A legacy-or-flow only', a.trial.leader);
    await r.go(B);
    expect.soft(composer().queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
    expect.soft(messageBox()).toHaveValue('');
    expect(screen.queryByTestId('glance-page') !== null).toBe(direction.endsWith('FLOW'));
    expect(screen.getByRole('button', { name: direction.endsWith('legacy') ? 'Stop run' : 'Stop project' })).toBeInTheDocument();
    await sendMessage('B own', b.trial.leader);
    expect(r.posts()[1]).toMatchObject({ path: `${r.runPath(B)}/messages`, body: { to: b.trial.leader, body: 'B own' } });
    expect(r.posts()[1].body!.request_id).not.toBe(r.posts()[0].body!.request_id);
  });
});

describe('H-INTEGRATION-R1: combined Project owner × FLOW receipt (one mounted router, cached A/B)', () => {
  // The receipt lives inside the route-keyed owner. DOM mutations are evidence about
  // the region only, never a claim about what a screen reader speaks.
  const sentence = (to: string) => `Temper accepted your message for ${to}.`;
  const NO_ANSWER = "Temper didn't answer. Trying again is safe: the same request counts once.";
  const receipt = () => screen.getByTestId('team-message-result');
  function watch(node: Element) {
    const updates: string[] = [];
    const observer = new MutationObserver(() => updates.push(node.textContent ?? ''));
    observer.observe(node, { childList: true, characterData: true, subtree: true });
    return { updates, observer };
  }
  const flush = () => act(async () => { await Promise.resolve(); });

  it.each([['accepted', 201], ['refused', 409], ['no answer', 0]] as const)(
    'late A %s receipt never announces on cached B; B own smaller first seq still announces once', async (_outcome, code) => {
      const r = rig();
      const lateA = deferred<Response>();
      r.handlers.set(`${r.runPath(A)}/messages`, (req, n) => n <= 2 ? reply(accepted(req.body!.to as string), 201) : lateA.promise);
      r.show();
      for (const words of ['A one', 'A two']) { // two accepted A results: A's seq reaches 2
        await sendMessage(words);
        await waitFor(() => expect(messageBox()).toHaveValue(''));
      }
      expect(receipt().textContent).toBe(sentence('lead'));
      const aRegion = receipt();
      await sendMessage('A three'); // A's third result is still pending when the route changes
      await r.go(B);
      const bRegion = receipt();
      expect(aRegion.isConnected).toBe(false);
      expect(bRegion).toHaveAttribute('aria-live', 'polite');
      expect(bRegion).toHaveAttribute('aria-atomic', 'true');
      expect(bRegion).toBeEmptyDOMElement();
      const seen = watch(bRegion);
      try {
        await settle(() => code === 0
          ? lateA.reject(new TypeError('fictional late A no answer'))
          : lateA.resolve(reply(code === 201 ? accepted() : { message: 'A refusal only' }, code)));
        await flush();
        expect(seen.updates).toEqual([]);
        expect(bRegion).toBeEmptyDOMElement();
        expect(composer().queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
        await sendMessage('B own words', 'checker');
        await waitFor(() => expect(bRegion.textContent).toBe(sentence('checker')));
        expect(receipt()).toBe(bRegion);
        expect(seen.updates).toEqual([sentence('checker')]);
      } finally { seen.observer.disconnect(); }
      expect(r.posts().map((p) => p.path)).toEqual([
        `${r.runPath(A)}/messages`, `${r.runPath(A)}/messages`, `${r.runPath(A)}/messages`, `${r.runPath(B)}/messages`,
      ]);
    });

  it('identical repeated B receipts: one persistent polite atomic region in the B owner, one update per new seq, none per poll; a Project change remounts', async () => {
    const r = rig();
    r.show();
    await r.go(B);
    const region = receipt();
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toHaveAttribute('aria-atomic', 'true');
    const box = messageBox();
    const seen = watch(region);
    try {
      for (const n of [1, 2]) {
        box.focus();
        await sendMessage('Same B words');
        await waitFor(() => expect(seen.updates).toHaveLength(n));
        await waitFor(() => expect(box).toHaveValue(''));
        await r.update({ ...flow(B), cost_usd: 100 + n }); // a same-B poll
        await flush();
        expect(receipt()).toBe(region);
        expect(messageBox()).toBe(box);
        expect(seen.updates).toHaveLength(n);
        expect(document.activeElement).toBe(box);
      }
      expect(seen.updates).toEqual([sentence('lead'), sentence('lead')]);
      expect(region.textContent).toBe(sentence('lead'));
    } finally { seen.observer.disconnect(); }
    await r.go(A);
    expect(region.isConnected).toBe(false);
    expect(receipt()).toBeEmptyDOMElement();
    await r.go(B);
    expect(receipt()).not.toBe(region);
    expect(receipt()).toBeEmptyDOMElement();
    expect(r.posts().map((p) => p.path)).toEqual([`${r.runPath(B)}/messages`, `${r.runPath(B)}/messages`]);
    expect(new Set(r.posts().map((p) => p.body!.request_id)).size).toBe(2);
  });

  it('same-A no-answer retry in the route owner: a poll keeps draft, Try again and region; the retry repeats the exact request; one acceptance', async () => {
    const r = rig();
    r.handlers.set(`${r.runPath(A)}/messages`, (req, n) => {
      if (n === 1) throw new TypeError('fictional never accepted');
      return reply(accepted(req.body!.to as string), 201);
    });
    r.show();
    const region = receipt();
    const seen = watch(region);
    try {
      await sendMessage('Retry A words');
      await waitFor(() => expect(region.textContent).toBe(`${NO_ANSWER}Try again`));
      await r.update({ ...flow(A), cost_usd: 111 }); // a same-A poll between the no-answer and the retry
      await flush();
      expect(receipt()).toBe(region);
      expect(messageBox()).toHaveValue('Retry A words');
      expect(seen.updates).toEqual([`${NO_ANSWER}Try again`]);
      await act(async () => { fireEvent.click(composer().getByRole('button', { name: 'Try again' })); });
      await waitFor(() => expect(region.textContent).toBe(sentence('lead')));
      expect(receipt()).toBe(region);
      expect(seen.updates).toEqual([`${NO_ANSWER}Try again`, sentence('lead')]);
    } finally { seen.observer.disconnect(); }
    await waitFor(() => expect(messageBox()).toHaveValue(''));
    expect(r.posts()).toHaveLength(2);
    expect(r.posts()[1]).toEqual(r.posts()[0]);
    expect(r.posts()[0]).toMatchObject({ path: `${r.runPath(A)}/messages`, body: { to: 'lead', body: 'Retry A words' } });
  });
});
