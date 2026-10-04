/**
 * A Pi agent's run, read live and read back, in the real dashboard build.
 *
 * Nothing here is a real run. The messages are the A2 fixtures: a scripted
 * provider drove the real Pi binary in a sealed container, the mapper in
 * temper_ai/llm/pi_stream.py turned its events into Temper's, and the real
 * WebSocketManager framed them (tests/test_llm/pi_a2_replay.py writes them).
 * The page is the real build; only its two sources are replaced, as in
 * liveReplay.ts, here with a socket that can also drop and come back.
 *
 * Serve a build anywhere but the live server, then point the spec at it:
 *
 *     npx vite build && npx vite preview --host 127.0.0.1 --port 4719 --strictPort
 *     TEMPER_E2E_BASE_URL=http://127.0.0.1:4719 npx playwright test e2e/piA2.spec.ts
 *
 * Each picture asserts the state it means to show before the shutter fires.
 */
import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const OUT = process.env.TEMPER_PROOF_DIR ?? 'e2e/proofs/pi-a2';
// Planted in the fixtures' sources; neither may reach the page.
const SECRET = 'A2-SYNTH-SECRET-8c41f2d9';
const SYSTEM_MARKER = 'A2-FIXTURE: system message removed';

interface Msg {
  type: string;
  event_type?: string;
  data?: { chunks?: Array<{ chunk_type?: string }> };
}
interface Snap {
  id: string;
  status: string;
  agent_index?: unknown[];
}
interface Fixture {
  live: Msg[];
  start: { index: number; snapshot: Snap };
  mid: { index: number; snapshot: Snap };
  final: Snap;
}

/** What the agent's story shows, as counts and words. */
interface Told {
  words: string;
  thinking: number;
  steps: string[];
  errors: string[];
  requests: number;
  progress: number;
  clipped: number;
  chars: number;
}

declare global {
  interface Window {
    __pi?: { send: (msg: unknown) => void; drop: () => void; connects: number; ready: number };
    __piServed?: () => Promise<unknown>;
  }
}

function fixture(name: string): Fixture {
  const file = path.join(process.cwd(), 'src/__tests__/fixtures/pi_a2', `${name}.json`);
  return JSON.parse(readFileSync(file, 'utf8')) as Fixture;
}

const isStarted = (m: Msg) => m.event_type === 'tool.call.started';
const hasProgress = (m: Msg) =>
  m.event_type === 'llm_stream_batch' && (m.data?.chunks ?? []).some((c) => c.chunk_type === 'tool_progress');

/** One page on one run, with the server's word in `served`. */
class Run {
  served: Snap;
  readonly crashes: string[] = [];
  readonly dialogs: string[] = [];

  constructor(
    readonly page: Page,
    readonly f: Fixture,
  ) {
    this.served = f.start.snapshot;
    page.on('pageerror', (e) => this.crashes.push(e.message));
    page.on('dialog', (d) => {
      this.dialogs.push(d.type());
      void d.dismiss();
    });
  }

  /** Open the page; the record it opens with is `served` (the run's start unless set). */
  async open(): Promise<void> {
    const page = this.page;
    await page.exposeFunction('__piServed', () => this.served);
    // Every request for data is answered here; nothing reaches a server.
    await page.route('**/api/**', async (route) => {
      const p = new URL(route.request().url()).pathname;
      if (p.startsWith('/api/workflows/') && p.endsWith('/agents')) {
        await route.fulfill({ json: { agents: this.served.agent_index ?? [] } });
      } else if (p.startsWith('/api/workflows/')) {
        await route.fulfill({ json: this.served });
      } else if (p.startsWith('/api/runs/')) {
        await route.fulfill({ json: { gates: [], checkpoints: [] } });
      } else {
        await route.fulfill({ status: 404, json: { detail: 'not part of this proof' } });
      }
    });
    // A socket that says what the test tells it to. Like the server's, every
    // connection opens with the record as it stands; drop() loses it the way
    // a network does (no clean close), so the page reconnects on its own.
    await page.addInitScript(() => {
      const pi: NonNullable<Window['__pi']> = { send: () => {}, drop: () => {}, connects: 0, ready: 0 };
      window.__pi = pi;
      class PiSocket {
        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSING = 2;
        static CLOSED = 3;
        readyState = 0;
        onopen: ((e: unknown) => void) | null = null;
        onmessage: ((e: { data: string }) => void) | null = null;
        onerror: ((e: unknown) => void) | null = null;
        onclose: ((e: { code: number }) => void) | null = null;
        constructor() {
          pi.connects += 1;
          const n = pi.connects;
          pi.send = (msg: unknown) => {
            if (this.readyState === 1) this.onmessage?.({ data: JSON.stringify(msg) });
          };
          pi.drop = () => {
            this.readyState = 3;
            this.onclose?.({ code: 1006 });
          };
          setTimeout(async () => {
            this.readyState = 1;
            this.onopen?.({});
            const workflow = await window.__piServed?.();
            this.onmessage?.({ data: JSON.stringify({ type: 'snapshot', workflow }) });
            pi.ready = n;
          }, 0);
        }
        send() {}
        close() {
          this.readyState = 3;
        }
        addEventListener() {}
        removeEventListener() {}
      }
      (window as unknown as { WebSocket: unknown }).WebSocket = PiSocket;
    });
    await page.goto(`/app/workflow/${this.served.id}`);
    await expect(page.getByTestId('live-panel')).toBeVisible();
    await this.connected(1);
  }

  /** Wait until connection `n` has had its opening snapshot. */
  async connected(n: number): Promise<void> {
    await this.page.waitForFunction((want) => window.__pi?.ready === want, n);
  }

  async play(msgs: Msg[]): Promise<void> {
    await this.page.evaluate((list) => {
      for (const m of list) window.__pi?.send(m);
    }, msgs);
  }

  async drop(): Promise<void> {
    await this.page.evaluate(() => window.__pi?.drop());
  }

  /** Read the page afresh with only the record, as someone opening it at the end would. */
  async readBack(): Promise<Told> {
    this.served = this.f.final;
    await this.page.reload();
    await expect(this.page.getByTestId('live-panel')).toBeVisible();
    await this.connected(1);
    await expect(this.page.getByTestId('agent-story')).toBeVisible();
    return this.settled();
  }

  async told(): Promise<Told> {
    return this.page.evaluate(() => {
      const story = document.querySelector('[data-testid="agent-story"]');
      const q = (id: string) => Array.from(story?.querySelectorAll(`[data-testid="${id}"]`) ?? []);
      const state = (step: Element) =>
        step.querySelector('.animate-pulse') ? 'running' : step.querySelector('svg.text-red-400') ? 'failed' : 'completed';
      return {
        words: q('story-text').map((e) => e.textContent ?? '').join(''),
        thinking: q('story-thinking').length,
        steps: q('story-tool').map(state),
        errors: q('story-error').map((e) => e.textContent ?? ''),
        requests: q('story-request').length,
        progress: q('story-tool-progress').length,
        clipped: q('story-clipped').length,
        chars: story?.textContent?.length ?? 0,
      };
    });
  }

  /** What the story says once it stops changing. */
  async settled(): Promise<Told> {
    let last = '';
    for (let i = 0; i < 40; i++) {
      const now = await this.told();
      const key = JSON.stringify(now);
      if (key === last) return now;
      last = key;
      await this.page.waitForTimeout(250);
    }
    throw new Error('the story never stopped changing');
  }

  async shot(name: string): Promise<void> {
    await this.page.getByTestId('live-panel').screenshot({ path: path.join(OUT, `${name}.png`) });
  }

  /** Nothing crashed, nothing popped up, nothing planted got through. */
  async clean(): Promise<void> {
    expect(this.crashes).toEqual([]);
    expect(this.dialogs).toEqual([]);
    const html = await this.page.content();
    expect(html.includes(SECRET)).toBe(false);
    expect(html.includes(SYSTEM_MARKER)).toBe(false);
  }
}

/** Two readings tell the same story (asked-for items are live-only notes). */
function sameStory(a: Told, b: Told): void {
  expect(a.words).toBe(b.words);
  expect(a.thinking).toBe(b.thinking);
  expect([...a.steps].sort()).toEqual([...b.steps].sort());
  expect([...a.errors].sort()).toEqual([...b.errors].sort());
}

test.use({ viewport: { width: 1440, height: 900 } });

test.describe('a Pi agent in the live panel', () => {
  test('asked-for steps are not runs, progress replaces itself, the end matches the record', async ({ page }) => {
    const f = fixture('s1_stream');
    const run = new Run(page, f);
    await run.open();
    const firstStep = f.live.findIndex(isStarted);
    const firstProgress = f.live.findIndex(hasProgress);
    expect(firstStep).toBeGreaterThan(f.start.index);
    expect(firstProgress).toBeGreaterThan(firstStep);

    // The model has written its tool calls; nothing has run yet.
    await run.play(f.live.slice(f.start.index, firstStep));
    await expect(page.getByTestId('story-request').first()).toBeVisible();
    await expect(page.getByTestId('story-tool')).toHaveCount(0);
    await run.shot('1-asked-for-not-run');

    // Both steps run; the long one shows its latest output.
    await run.play(f.live.slice(firstStep, firstProgress + 1));
    await expect(page.getByTestId('story-tool')).toHaveCount(2);
    await expect(page.getByTestId('story-tool-progress')).toHaveCount(1);
    await run.shot('2-steps-running-with-progress');

    await run.play(f.live.slice(firstProgress + 1));
    await expect(page.getByTestId('story-tool-progress')).toHaveCount(0);
    const live = await run.settled();
    expect(live.steps).toEqual(['completed', 'completed']);
    expect(live.errors).toEqual([]);
    expect(live.words.length).toBeGreaterThan(0);
    await run.shot('3-finished-live');

    const back = await run.readBack();
    sameStory(live, back);
    await run.shot('4-read-back');
    await run.clean();
  });

  test.describe('west of UTC', () => {
    // Stored times carry no zone, live ones do: only a browser off UTC can mix them up.
    test.use({ timezoneId: 'America/Los_Angeles' });

    test('a page opened halfway puts what it missed first', async ({ page }) => {
      const f = fixture('s1_stream');
      const run = new Run(page, f);
      run.served = f.mid.snapshot;
      await run.open();
      await run.play(f.live.slice(f.mid.index));
      await expect(page.getByTestId('story-tool-progress')).toHaveCount(0);
      const joined = await run.settled();
      expect(joined.thinking).toBeGreaterThan(1);
      await run.shot('9-opened-halfway');

      const back = await run.readBack();
      sameStory(joined, back);
      await run.clean();
    });
  });

  test('a dropped connection mends from the record', async ({ page }) => {
    const f = fixture('s1_stream');
    const run = new Run(page, f);
    await run.open();
    const k = f.start.index + Math.max(1, Math.floor((f.mid.index - f.start.index) / 2));

    await run.play(f.live.slice(f.start.index, k));
    // Lost: everything from k until the page is back. The record moves on meanwhile.
    run.served = f.mid.snapshot;
    await run.drop();
    await run.connected(2);
    // A resend of something already shown, then the rest as it happens.
    await run.play([f.live[k - 1], ...f.live.slice(f.mid.index)]);
    await expect(page.getByTestId('story-tool-progress')).toHaveCount(0);
    const mended = await run.settled();
    expect(mended.steps).toEqual(['completed', 'completed']);
    await run.shot('5-mended-after-drop');

    const back = await run.readBack();
    sameStory(mended, back);
    await run.clean();
  });

  for (const [name, errors] of [
    ['s5_retry_fail', 3],
    ['s6_abort', 2],
  ] as const) {
    test(`${name}: failures stay in sight, live and read back`, async ({ page }) => {
      const f = fixture(name);
      const run = new Run(page, f);
      await run.open();
      await run.play(f.live.slice(f.start.index));
      await expect(page.getByTestId('story-error')).toHaveCount(errors);
      const live = await run.settled();
      await run.shot(`6-${name}-live`);

      const back = await run.readBack();
      expect(back.errors.length).toBe(errors);
      sameStory(live, back);
      await run.shot(`7-${name}-read-back`);
      await run.clean();
    });
  }

  test('a long, hostile answer stays bounded and inert', async ({ page }) => {
    const f = fixture('s3_large_untrusted');
    const run = new Run(page, f);
    await run.open();
    await run.play(f.live.slice(f.start.index));
    await expect(page.getByTestId('story-clipped').first()).toBeVisible();
    const live = await run.settled();
    expect(live.chars).toBeLessThan(50_000);
    await run.shot('8-long-answer-bounded');

    // Open every step so its output renders too, then look for anything live.
    const steps = page.getByTestId('story-tool');
    const count = await steps.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i++) await steps.nth(i).getByRole('button').first().click();
    const inert = await page.getByTestId('agent-story').evaluate((el) => ({
      active: el.querySelectorAll('script,iframe,object,embed,img,form,link,meta,style').length,
      handlers: Array.from(el.querySelectorAll('*')).filter((n) =>
        Array.from(n.attributes).some((a) => a.name.toLowerCase().startsWith('on')),
      ).length,
      jsUrls: Array.from(el.querySelectorAll('[href],[src]')).filter((n) =>
        /^\s*javascript:/i.test(n.getAttribute('href') ?? n.getAttribute('src') ?? ''),
      ).length,
    }));
    expect(inert).toEqual({ active: 0, handlers: 0, jsUrls: 0 });
    await run.clean();
  });
});
