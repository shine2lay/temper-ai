import '@testing-library/jest-dom/vitest';

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
