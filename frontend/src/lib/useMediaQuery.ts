/**
 * Media queries as React state.
 *
 * The big view asks the machine two things: does it want less motion, and is
 * the screen narrow enough that the in/out panes have to stack instead of
 * flanking the box. Both are the same question in CSS, so they share one
 * hook — and because the answer lives in React state, a component can leave
 * an animation class off entirely rather than hope a stylesheet overrides it.
 */
import { useEffect, useState } from 'react';

function read(query: string): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  try {
    return window.matchMedia(query).matches;
  } catch {
    // jsdom and older browsers throw on queries they cannot parse.
    return false;
  }
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => read(query));

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    let mql: MediaQueryList;
    try {
      mql = window.matchMedia(query);
    } catch {
      return;
    }
    const onChange = () => setMatches(mql.matches);
    onChange();
    // Safari < 14 only has the deprecated addListener.
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    }
    const legacy = mql as unknown as {
      addListener?: (cb: () => void) => void;
      removeListener?: (cb: () => void) => void;
    };
    legacy.addListener?.(onChange);
    return () => legacy.removeListener?.(onChange);
  }, [query]);

  return matches;
}

export const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
export const NARROW_QUERY = '(max-width: 767px)';

/** True when the machine asks for less motion. Every animation honours it. */
export function useReducedMotion(): boolean {
  return useMediaQuery(REDUCED_MOTION_QUERY);
}

/** True on a phone-width screen, where the view stacks instead of flanking. */
export function useIsNarrow(): boolean {
  return useMediaQuery(NARROW_QUERY);
}
