import '@testing-library/jest-dom/vitest';
import { configure } from '@testing-library/react';

// findBy* and waitFor give up after Testing Library's default of 1 s. In a whole-suite run
// (about 19 workers on 20 cores, after the commit hook's pytest) a page that waits on its
// mocked fetch can take longer than that to draw, so tests that pass alone failed there:
// teamC's form options and teamAnswer's needs-you card, on master too (2026-10-19). A wait
// returns as soon as its element is there, so a passing test is no slower; 4 s only moves
// the point where a missing element is called missing. Same reasoning as testTimeout in
// vite.config.ts: the budget was the default, not a decision. Not 5 s: teamRunOwnership
// catches the feed's 5 s retry timers by their delay, and would count waitFor's own too.
configure({ asyncUtilTimeout: 4_000 });

// jsdom doesn't implement scrollIntoView
Element.prototype.scrollIntoView = () => {};

// The big view is a Radix dialog and its folds are Radix collapsibles. jsdom
// has none of the browser APIs they reach for, so stub the few they touch —
// without these a test that opens the view dies inside Radix, not in our code.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof window.ResizeObserver;
}

if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}
