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

/** Apply the given theme by setting data-theme on <html>, or remove the
 *  attribute to fall back to system preference. */
function applyTheme(theme: Theme | null): void {
  const root = document.documentElement;
  if (theme === null) {
    root.removeAttribute('data-theme');
  } else {
    root.setAttribute('data-theme', theme);
  }
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
