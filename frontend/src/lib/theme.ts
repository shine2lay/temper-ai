const STORAGE_KEY = 'temper_theme';

type Theme = 'light' | 'dark';

/** Read the stored theme preference, or null if none is set. */
function getStoredTheme(): Theme | null {
  try {
    const val = localStorage.getItem(STORAGE_KEY);
    if (val === 'light' || val === 'dark') return val;
  } catch {
    // localStorage may be unavailable in some environments
  }
  return null;
}

/** Persist the theme preference to localStorage. */
function setStoredTheme(theme: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // ignore
  }
}

/** Resolve the effective theme, taking system preference into account
 *  when no explicit choice is stored. */
function resolveTheme(theme: Theme | null): Theme {
  if (theme !== null) return theme;
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

/** Apply the given theme by:
 *   - setting data-theme on <html> (drives the temper-* CSS custom
 *     properties via [data-theme="light"] / [data-theme="dark"])
 *   - toggling the .dark class on <html> (drives Tailwind's `dark:`
 *     variant, which is configured as `&:is(.dark *)`)
 *  When `theme` is null we fall back to system preference, but still
 *  apply the resolved class so Tailwind dark: utilities stay in sync.
 */
function applyTheme(theme: Theme | null): void {
  const root = document.documentElement;
  const resolved = resolveTheme(theme);
  if (theme === null) {
    root.removeAttribute('data-theme');
  } else {
    root.setAttribute('data-theme', theme);
  }
  root.classList.toggle('dark', resolved === 'dark');
}

/** Initialise the theme as early as possible (call from main.tsx or inline
 *  script).  Reads localStorage first, then falls back to system preference. */
export function initTheme(): void {
  const stored = getStoredTheme();
  applyTheme(stored);
}

/** Return the currently active theme, resolving system preference when no
 *  explicit theme has been stored. */
export function getActiveTheme(): Theme {
  const stored = getStoredTheme();
  if (stored) return stored;
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

/** Toggle between light and dark, persisting the result to localStorage. */
export function toggleTheme(): Theme {
  const next: Theme = getActiveTheme() === 'dark' ? 'light' : 'dark';
  setStoredTheme(next);
  applyTheme(next);
  return next;
}
