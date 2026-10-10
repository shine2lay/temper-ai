/**
 * D85 (Design, HOME-DECISIONS-2026-10-09-2030 Q5): an All activity row whose
 * words are cut gets a "Show all" text button that opens the row in place to
 * the whole text and becomes "Show less". On Temper's real working reply and
 * feed (e2e/fixtures/team/flow/real, FLOW #80); a message's whole body comes
 * from its message read, as on the round page. Keyboard, the 24 px target and
 * the page not moving are the browser's: e2e/team-glance.spec.ts.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AllActivity } from '@/components/team/glance/AllActivity';
import { activityRow, messageWholeParts, type GlanceEvent, type MomentPart } from '@/lib/teamGlance';
import { toGlanceEvent, toGlanceRun } from '@/lib/teamGlanceAdapter';

import working from '../../e2e/fixtures/team/flow/real/working.json';
import workingFeed from '../../e2e/fixtures/team/flow/real/working-events.json';

type Raw = Record<string, unknown>;

const RUN = toGlanceRun(working);
const FEED = (workingFeed as { events: Raw[] }).events;
const events = (raw: Raw[]) => raw.map(toGlanceEvent).filter((e): e is GlanceEvent => e !== null);
const message = (seq: number) => FEED.find((e) => e.seq === seq) as Raw;

/** The leader's work request to the builder (seq 4): Temper's feed quotes its first line. */
const LONG_ID = message(4).message_id as string;
const LONG_BODY = 'Build the builder part and share it.\n\nKeep it under 40 lines.\nAdd a Usage section with one example.';
/** The request to the checker (seq 6): its body is the same one line, so nothing is cut. */
const SHORT_ID = message(6).message_id as string;

let reads: string[] = [];

beforeEach(() => {
  reads = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), 'http://x').pathname;
      reads.push(path);
      const id = path.split('/').pop();
      const body = id === LONG_ID ? LONG_BODY : id === SHORT_ID ? 'Build the checker part and share it.' : null;
      return body === null
        ? new Response(JSON.stringify({ detail: 'No such message' }), { status: 404, headers: { 'content-type': 'application/json' } })
        : new Response(JSON.stringify({ message_id: id, body, from: 'lead', to: 'builder', kind: 'work_request' }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          });
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function show(feed: Raw[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui = (list: Raw[]) => (
    <QueryClientProvider client={client}>
      <AllActivity run={{ ...RUN, eventsTotal: list.length }} events={events(list)} ready />
    </QueryClientProvider>
  );
  const view = render(ui(feed));
  return { ...view, again: (list: Raw[]) => view.rerender(ui(list)) };
}

const row = (seq: number) => {
  const li = document.querySelector(`[data-row="a${seq}"]`);
  if (!li) throw new Error(`no row a${seq}`);
  return li as HTMLElement;
};

describe('D85 Show all in All activity', () => {
  it('opens a cut message in place, keeps it open through new events, and closes it again', async () => {
    const { again } = show(FEED);
    // The cut row gets its button once Temper's body says more than the row's first line.
    const button = await within(row(4)).findByRole('button', { name: 'Show all' });
    expect(button).toHaveAttribute('type', 'button');
    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(row(4)).toHaveTextContent('lead asked builder: \u201cBuild the builder part and share it.\u201dShow all');
    // The checker's body is its one line: no cut, no button.
    await waitFor(() => expect(reads).toContain(`/api/team/runs/${RUN.executionId}/messages/${SHORT_ID}`));
    expect(within(row(6)).queryByRole('button')).toBeNull();
    // Rows with no cut words read nothing and get no button.
    expect(within(row(5)).queryByRole('button')).toBeNull();

    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(button).toHaveTextContent('Show less');
    expect(button.getAttribute('aria-controls')).toBe('glance-activity-a4-text');
    const text = document.getElementById('glance-activity-a4-text');
    expect(text?.textContent).toBe(`lead asked builder: \u201c${LONG_BODY}\u201d`);
    // The whole body keeps its line breaks.
    expect(text?.parentElement).toHaveClass('whitespace-pre-wrap');

    // A new event arrives (the page's poll): the open row stays open, its body read once.
    const next = { ...message(6), seq: 99, at: message(6).at, text: 'One more thing.', message_id: 'm-new' };
    again([...FEED, next]);
    expect(screen.getByRole('button', { name: 'Show less' })).toBe(within(row(4)).getByRole('button'));
    expect(reads.filter((p) => p.endsWith(LONG_ID))).toHaveLength(1);

    fireEvent.click(within(row(4)).getByRole('button', { name: 'Show less' }));
    expect(within(row(4)).getByRole('button', { name: 'Show all' })).toHaveAttribute('aria-expanded', 'false');
    expect(document.getElementById('glance-activity-a4-text')?.textContent).toBe(
      'lead asked builder: \u201cBuild the builder part and share it.\u201d',
    );
  });

  it('opens a share or idle note the feed holds whole, with no read', async () => {
    const note = 'First cut of the README.\nUsage comes next.';
    const share = { ...message(4), kind: 'share', seq: 50, member: 'builder', version_no: 1, commit_short: 'abc1234', note, files_changed: 1 };
    const idle = { ...message(4), kind: 'idle', seq: 51, member: 'checker', reason: 'idle_call', note: 'Waiting on v1.\nNothing to check yet.' };
    show([...FEED, share, idle]);
    const shareButton = within(row(50)).getByRole('button', { name: 'Show all' });
    fireEvent.click(shareButton);
    expect(document.getElementById('glance-activity-a50-text')?.textContent).toBe(`builder shared v1: \u201c${note}\u201d`);
    fireEvent.click(within(row(51)).getByRole('button', { name: 'Show all' }));
    expect(document.getElementById('glance-activity-a51-text')?.textContent).toBe(
      'checker went idle: \u201cWaiting on v1.\nNothing to check yet.\u201d',
    );
    await act(async () => {});
    expect(reads.some((p) => p.endsWith('/messages/'))).toBe(false);
  });

  it('cuts only what Temper cut or the row cut', () => {
    const run = { startedBy: RUN.startedBy, members: RUN.members };
    const [one] = events([message(6)]);
    const row6 = activityRow(one, run);
    expect(row6.more).toEqual({ messageId: SHORT_ID, lead: row6.parts.slice(0, 3), shown: 'Build the checker part and share it.' });
    const more = row6.more as { lead: MomentPart[]; shown: string };
    // A body that says no more than the row: no cut.
    expect(messageWholeParts(more, '  Build the checker part and share it.\n')).toBeNull();
    expect(messageWholeParts(more, null)).toBeNull();
    // More lines (or Temper's 120-character cut): a cut, and the whole row quotes the whole body.
    const whole = messageWholeParts(more, 'Build the checker part and share it.\nThen tell me.');
    expect(whole?.map((p) => p.text).join('')).toBe('lead asked checker: \u201cBuild the checker part and share it.\nThen tell me.\u201d');
    // A one-line note is whole already.
    const [share] = events([{ ...message(4), kind: 'share', seq: 7, member: 'builder', version_no: 1, note: 'All in one line.' }]);
    expect(activityRow(share, run).more).toBeUndefined();
  });
});
