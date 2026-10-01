/**
 * Does the machine ask for less motion?
 *
 * The CSS already stops every animation in that case; this hook is for the
 * decisions CSS cannot make — staggering timeline rows, say, which has to be
 * a number rather than a rule. It follows the setting live, so turning
 * "reduce motion" on in the system settings takes effect without a reload.
 */
import { useSyncExternalStore } from 'react';

const QUERY = '(prefers-reduced-motion: reduce)';

function media(): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null;
  return window.matchMedia(QUERY);
}

function subscribe(onChange: () => void): () => void {
  const mq = media();
  if (!mq) return () => {};
  // Safari below 14 only has the deprecated form.
  if (typeof mq.addEventListener === 'function') {
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }
  mq.addListener(onChange);
  return () => mq.removeListener(onChange);
}

function read(): boolean {
  return media()?.matches ?? false;
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, read, () => false);
}
