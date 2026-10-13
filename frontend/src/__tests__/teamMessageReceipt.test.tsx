/**
 * F-MF3: the real composer, serializer-shaped fictional HTTP receipts, and
 * the real message sender. DOM mutations are not a claim about AT speech.
 * The new copy/atomic assertions must fail on frozen 78cee5a3; held/legacy
 * and request-id counters must pass there as well as on the repair.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MessageComposer } from '@/components/team/run/MessageComposer';
import { useTeamMessage, type MessageResult, type TeamMessageSender } from '@/hooks/useTeamMessage';
import { messageSent } from '@/lib/teamMessage';
import type { TeamMessageSent, TeamRun } from '@/types/team';
import receipts from '../../e2e/fixtures/team/message-receipts-fictional.json';
import runEnvelope from '../../e2e/fixtures/team/run-running.json';

const ACCEPTED = 'Temper accepted your message for maker.';
const HELD = 'Sent: held until you answer the open question.';
const PAUSED = `${HELD} The team is paused, so no member takes a turn until then.`;
const LEGACY = 'Sent. maker gets it at its next turn.';
const NO_ANSWER = "Temper didn't answer. Trying again is safe: the same request counts once.";

function run(paused = false, activity = 'working'): TeamRun {
  // The captured envelope supplies the serializer fields, not trial output.
  const raw = structuredClone(runEnvelope.body) as unknown as TeamRun;
  raw.execution_id = 'fictional-receipt-run';
  raw.trial.goal = 'Fictional receipt test.';
  raw.trial.leader = 'maker';
  raw.timeline = { entries: [], not_shown: 0 };
  raw.owner_actions = [];
  raw.reviews = [];
  raw.members = raw.members.filter((m) => m.name === 'maker').map((m) => ({ ...m, activity, last_turn: null }));
  raw.state = paused ? 'paused' : 'running';
  return raw;
}

function accepted(seq = 1, reply: TeamMessageSent = receipts.pending.body): MessageResult {
  return { seq, sent: { requestId: `fictional-${seq}`, to: 'maker', body: 'Fictional words.' }, outcome: messageSent(reply) };
}

function sender(result: MessageResult | null): TeamMessageSender {
  return { result, sending: false, send: vi.fn(), retry: vi.fn() };
}

const receipt = () => screen.getByTestId('team-message-result');
const words = () => receipt().textContent;
const settle = () => act(async () => { await Promise.resolve(); });

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('FLOW acceptance — actual composer', () => {
  for (const activity of ['working', 'idle']) {
    it(`${activity === 'idle' ? 'ready' : activity}: exactly the acceptance sentence, no prefix or delivery promise`, () => {
      render(<MessageComposer run={run(false, activity)} limit={20_000} sender={sender(accepted())} textScale="glance" />);
      expect(words()).toBe(ACCEPTED);
      expect(words()).not.toMatch(/Sent\.|^Accepted\.|next turn|delivered|read|acted/i);
    });
  }

  it('repeated success has the same whole sentence, not a duplicate or completed-delivery claim', () => {
    render(<MessageComposer run={run()} limit={20_000} sender={sender(accepted(2, receipts.repeated.body))} textScale="glance" />);
    expect(words()).toBe(ACCEPTED);
  });

  it('supplied long/metacharacter recipient is literal text, never HTML or a transformed name', () => {
    const to = `<img src=x onerror="alert(1)"> & ${'long-recipient-'.repeat(12)}`;
    render(<MessageComposer run={run()} limit={20_000} sender={sender(accepted(1, { ...receipts.pending.body, to }))} textScale="glance" />);
    expect(words()).toBe(`Temper accepted your message for ${to}.`);
    expect(receipt().querySelector('img')).toBeNull();
    expect(receipt().querySelector('[onerror]')).toBeNull();
  });

  it('one polite atomic region exists before the first result; no nested announcer', () => {
    const shown = render(<MessageComposer run={run()} limit={20_000} sender={sender(null)} textScale="glance" />);
    const region = receipt();
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toHaveAttribute('aria-atomic', 'true');
    shown.rerender(<MessageComposer run={run()} limit={20_000} sender={sender(accepted())} textScale="glance" />);
    expect(receipt()).toBe(region);
    expect(region.querySelectorAll('[aria-live], [role="status"], [role="alert"]')).toHaveLength(0);
  });

  it('same region, one content update per new seq including identical text, none for same seq; no focus movement', async () => {
    const shown = render(<MessageComposer run={run()} limit={20_000} sender={sender(null)} textScale="glance" />);
    const region = receipt();
    const box = screen.getByRole('textbox', { name: 'Message' });
    box.focus();
    const updates: string[] = [];
    const observer = new MutationObserver(() => updates.push(region.textContent ?? ''));
    observer.observe(region, { childList: true, characterData: true, subtree: true });
    try {
      for (const seq of [1, 2, 3]) {
        shown.rerender(<MessageComposer run={run()} limit={20_000} sender={sender(accepted(seq, receipts.repeated.body))} textScale="glance" />);
        await settle();
        expect(receipt()).toBe(region);
        expect(updates).toHaveLength(seq);
        expect(document.activeElement).toBe(box);
      }
      const before = [...updates];
      shown.rerender(<MessageComposer run={run()} limit={20_000} sender={sender(accepted(3, receipts.repeated.body))} textScale="glance" />);
      fireEvent.change(box, { target: { value: 'A new draft, same result seq.' } });
      await settle();
      expect(updates).toEqual(before);
      expect(document.activeElement).toBe(box);
      expect(updates).toEqual([ACCEPTED, ACCEPTED, ACCEPTED]);
    } finally { observer.disconnect(); }
  });
});

describe('held/legacy/refused/no-answer clean counters', () => {
  for (const textScale of ['team', 'glance'] as const) {
    for (const paused of [false, true]) {
      it(`${textScale} held, paused=${paused}: existing sentence stays exact`, () => {
        render(<MessageComposer run={run(paused)} limit={20_000} sender={sender(accepted(1, receipts.held.body))} textScale={textScale} />);
        expect(words()).toBe(paused ? PAUSED : HELD);
        expect(words()).not.toContain('Temper accepted');
      });
    }
  }

  it('held detected from the after_open_wait enum also keeps existing wording', () => {
    render(<MessageComposer run={run()} limit={20_000} sender={sender(accepted(1, { ...receipts.pending.body, delivers: 'after_open_wait' }))} textScale="glance" />);
    expect(words()).toBe(HELD);
  });

  it('legacy non-held and repeated non-held keep their exact old sentence', () => {
    const shown = render(<MessageComposer run={run()} limit={20_000} sender={sender(accepted())} />);
    expect(words()).toBe(LEGACY);
    expect(receipt()).not.toHaveAttribute('aria-atomic');
    shown.rerender(<MessageComposer run={run()} limit={20_000} sender={sender(accepted(2, receipts.repeated.body))} />);
    expect(words()).toBe(LEGACY);
  });

  for (const textScale of ['team', 'glance'] as const) {
    it(`${textScale} actual sender: refusal/no answer are not acceptance; retry retains request id`, async () => {
      const captured: { path: string; body: Record<string, unknown> }[] = [];
      let n = 0;
      vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
        captured.push({ path: url, body: JSON.parse(String(init.body)) as Record<string, unknown> });
        n += 1;
        if (n === 2) throw new TypeError('Failed to fetch');
        const reply = n === 1 ? receipts.refused : receipts.repeated;
        return new Response(JSON.stringify(reply.body), { status: reply.status, headers: { 'content-type': 'application/json' } });
      }));
      const refresh = vi.fn(async () => null);
      let id = 0;
      const make = () => `fictional-request-${++id}`;
      function ComposerWithRealSender() {
        const actual = useTeamMessage('fictional-receipt-run', refresh, make);
        return <MessageComposer run={run()} limit={20_000} sender={actual} textScale={textScale} />;
      }
      render(<ComposerWithRealSender />);
      const box = screen.getByRole('textbox', { name: 'Message' });
      fireEvent.change(box, { target: { value: 'Fictional words.' } });
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Send message' })); });
      expect(words()).toBe('Temper refused: Fictional member has ended. Your text is kept.');
      expect(box).toHaveValue('Fictional words.');
      expect(words()).not.toContain('Temper accepted');
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Send message' })); });
      expect(words()).toBe(`${NO_ANSWER}Try again`);
      expect(words()).not.toContain('Temper accepted');
      expect(box).toHaveValue('Fictional words.');
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Try again' })); });
      expect(words()).toBe(textScale === 'glance' ? ACCEPTED : LEGACY);
      expect(box).toHaveValue('');
      expect(captured.map((c) => c.path)).toEqual(Array(3).fill('/api/team/runs/fictional-receipt-run/messages'));
      expect(captured.map((c) => c.body)).toEqual([
        { request_id: 'fictional-request-1', to: 'maker', body: 'Fictional words.' },
        { request_id: 'fictional-request-2', to: 'maker', body: 'Fictional words.' },
        { request_id: 'fictional-request-2', to: 'maker', body: 'Fictional words.' },
      ]);
      expect(refresh).toHaveBeenCalledTimes(3);
    });
  }
});
