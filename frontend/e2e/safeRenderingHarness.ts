/**
 * A sealed browser for the safe-rendering proofs.
 *
 * Each test gets a fresh context: no storage state, no token, no profile,
 * service workers blocked. Every request the page tries is seen here first:
 *
 * - the preview's own files (pages under /app/, /app/assets/*, the three
 *   icons) are let through;
 * - /api/* reads are answered locally by the test (unknown ones get a 404),
 *   so nothing ever reaches a real server;
 * - everything else is aborted and counted.
 *
 * Attempts are counted from request events, not responses, so an aborted
 * image counts as much as a loaded one. The websocket is faked in the page;
 * a real one would be closed at once and counted. Only counts are kept,
 * never addresses.
 */
import { expect, type Browser, type BrowserContext, type Page, type Request } from '@playwright/test';

export type ApiAnswer = { status: number; body: unknown } | null;
export type ApiHandler = (pathname: string, method: string) => ApiAnswer;

export interface Sealed {
  context: BrowserContext;
  page: Page;
  /** Aborted attempts so far that no deliberate key press asked for. */
  contentAttempts: () => number;
  /** Aborted attempts after `deliberate()` was called. */
  deliberateAttempts: () => number;
  /** Navigation requests seen after `deliberate()`, for header checks. */
  deliberateRequests: () => Request[];
  /** From now on, attempts count as deliberate (a key press follows). */
  deliberate: () => void;
  close: () => Promise<void>;
}

const OWN_ICONS = new Set(['/app/favicon.svg', '/app/favicon-32.png', '/app/apple-touch-icon.png']);

type Kind = 'own' | 'api' | 'blocked';

function classify(raw: string, resourceType: string, origin: string): Kind {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return 'blocked';
  }
  if (url.origin !== origin) return 'blocked';
  const path = url.pathname;
  if (path.startsWith('/api/') && (resourceType === 'fetch' || resourceType === 'xhr')) return 'api';
  if (resourceType === 'document' && (path === '/app' || path.startsWith('/app/'))) return 'own';
  if (path.startsWith('/app/assets/') || OWN_ICONS.has(path)) return 'own';
  return 'blocked';
}

/** A websocket that only says what the test tells it to (window.__replay.send). */
function fakeSocket(snapshot: unknown) {
  class ReplaySocket {
    static OPEN = 1;
    readyState = 1;
    onopen: ((e: unknown) => void) | null = null;
    onmessage: ((e: { data: string }) => void) | null = null;
    onerror: ((e: unknown) => void) | null = null;
    onclose: ((e: unknown) => void) | null = null;
    constructor() {
      (window as unknown as { __replay: unknown }).__replay = {
        open: true,
        send: (msg: unknown) => this.onmessage?.({ data: JSON.stringify(msg) }),
      };
      setTimeout(() => {
        this.onopen?.({});
        if (snapshot) this.onmessage?.({ data: JSON.stringify({ type: 'snapshot', workflow: snapshot }) });
      }, 0);
    }
    send() {}
    close() {
      this.readyState = 3;
    }
    addEventListener() {}
    removeEventListener() {}
  }
  (window as unknown as { WebSocket: unknown }).WebSocket = ReplaySocket;
}

export async function openSealed(
  browser: Browser,
  baseURL: string,
  api: ApiHandler,
  { theme = 'dark', snapshot = null, viewport = { width: 1440, height: 900 } }: {
    theme?: 'dark' | 'light';
    snapshot?: unknown;
    viewport?: { width: number; height: number };
  } = {},
): Promise<Sealed> {
  const origin = new URL(baseURL).origin;
  const context = await browser.newContext({ baseURL, viewport, serviceWorkers: 'block' });
  let deliberate = false;
  let content = 0;
  let deliberateCount = 0;
  const navigations: Request[] = [];

  context.on('request', (req) => {
    if (deliberate && req.isNavigationRequest()) navigations.push(req);
    if (classify(req.url(), req.resourceType(), origin) !== 'blocked') return;
    if (deliberate) deliberateCount++;
    else content++;
  });

  await context.route('**/*', async (route) => {
    const req = route.request();
    const kind = classify(req.url(), req.resourceType(), origin);
    if (kind === 'own') return route.continue();
    if (kind === 'api') {
      const answer = api(new URL(req.url()).pathname, req.method()) ?? { status: 404, body: { detail: 'Not Found' } };
      return route.fulfill({ status: answer.status, contentType: 'application/json', body: JSON.stringify(answer.body) });
    }
    return route.abort('blockedbyclient');
  });

  await context.routeWebSocket(/.*/, (ws) => {
    if (deliberate) deliberateCount++;
    else content++;
    void ws.close();
  });

  await context.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
  await context.addInitScript(fakeSocket, snapshot);
  const page = await context.newPage();

  return {
    context,
    page,
    contentAttempts: () => content,
    deliberateAttempts: () => deliberateCount,
    deliberateRequests: () => [...navigations],
    deliberate: () => {
      deliberate = true;
    },
    close: () => context.close(),
  };
}

/** Send one message through the fake websocket. */
export async function sendEvent(page: Page, msg: unknown): Promise<void> {
  await page.evaluate((m) => {
    (window as unknown as { __replay: { send: (x: unknown) => void } }).__replay.send(m);
  }, msg);
}

/** Elements that would load something, minus the app's own logo files. */
const LOADING = 'img, picture, source, video, audio, track, iframe, frame, object, embed, link[rel], script, style, image, use, input[type="image"]';

export interface DomFindings {
  probeAttributes: number;
  probeElements: number;
  loading: number;
}

/** What content turned into, page-wide: tripwire attributes, custom elements, loading elements. */
export async function domFindings(page: Page): Promise<DomFindings> {
  return page.evaluate((selector) => {
    const own = (el: Element) => {
      const src = el.getAttribute('src') ?? el.getAttribute('href') ?? '';
      if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE' || el.tagName === 'LINK') return el.closest('head') !== null;
      return src.startsWith('/app/assets/') || src.startsWith('data:image/svg') || el.closest('[data-testid="temper-lockup"]') !== null || el.hasAttribute('data-colourway');
    };
    return {
      probeAttributes: document.querySelectorAll('[data-probe]').length,
      probeElements: document.querySelectorAll('x-probe').length,
      loading: [...document.querySelectorAll(selector)].filter((el) => !own(el)).length,
    };
  }, LOADING);
}

/** Give eager loads time to start after content shows. */
export async function settle(page: Page): Promise<void> {
  await page.waitForTimeout(800);
}

export function recordAttempts(info: { annotations: { type: string; description?: string }[] }, sealed: Sealed) {
  info.annotations.push({ type: 'content-request-attempts', description: String(sealed.contentAttempts()) });
  info.annotations.push({ type: 'deliberate-request-attempts', description: String(sealed.deliberateAttempts()) });
}

/** The page-wide tripwire checks every surface test ends with. */
export async function expectNothingLoaded(sealed: Sealed): Promise<void> {
  const found = await domFindings(sealed.page);
  expect.soft(found.probeAttributes, 'data-probe attributes made from content').toBe(0);
  expect.soft(found.probeElements, 'x-probe elements made from content').toBe(0);
  expect.soft(found.loading, 'elements that load something, made from content').toBe(0);
  expect.soft(sealed.contentAttempts(), 'request attempts caused by showing content').toBe(0);
}
