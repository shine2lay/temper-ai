/**
 * The one navigation policy for addresses that come from content.
 *
 * Agent output is not ours: a link or image address in it can name any
 * scheme, carry a user name, hide control characters, or point back at the
 * dashboard's own API. So every address shown from content passes here, and
 * only three kinds survive:
 *
 * - `external`: http or https on another host, with no user name or password;
 * - `internal`: a page of this dashboard, under /app/;
 * - `fragment`: a jump within the page (`#…`).
 *
 * Anything else returns null and is shown as plain text: mailto, ftp, tel,
 * data and every other scheme, user names, and other paths on this host
 * (`/api/…` above all).
 *
 * The address is normalised the way the browser's own URL parser does before
 * it is checked (tab, CR and LF removed; control characters and spaces
 * trimmed from both ends), so the address checked is the address followed.
 * The result is idempotent: checking an accepted href again gives it back.
 */

export type SafeUrlKind = 'external' | 'internal' | 'fragment';

export interface SafeUrl {
  kind: SafeUrlKind;
  /** What goes in the element's href. */
  href: string;
  /** The host shown to the reader ("" for a fragment). */
  host: string;
}

const APP_PREFIX = '/app/';

const TAB_OR_NEWLINE = /[\t\n\r]/g;
// eslint-disable-next-line no-control-regex -- C0 controls and space, as the URL parser trims them
const EDGE_CONTROLS = /^[\u0000-\u0020]+|[\u0000-\u0020]+$/g;

/** Strip what the URL parser would strip, so the check sees what the browser follows. */
export function normaliseUrl(raw: string): string {
  return raw.replace(TAB_OR_NEWLINE, '').replace(EDGE_CONTROLS, '');
}

function currentOrigin(): string {
  return typeof window === 'undefined' ? 'http://localhost' : window.location.origin;
}

/** A same-origin path is allowed only inside the dashboard's pages, with no way back out. */
function isAppPath(pathname: string): boolean {
  let decoded: string;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    return false;
  }
  if (!pathname.startsWith(APP_PREFIX) || !decoded.startsWith(APP_PREFIX)) return false;
  return !decoded.split(/[/\\]/).some((segment) => segment === '.' || segment === '..');
}

/**
 * Check an address from content. Returns what to link to, or null when it
 * must be shown as plain text.
 */
export function safeUrl(raw: string | null | undefined, origin: string = currentOrigin()): SafeUrl | null {
  if (typeof raw !== 'string') return null;
  const value = normaliseUrl(raw);
  if (value === '') return null;
  if (value.startsWith('#')) return { kind: 'fragment', href: value, host: '' };

  let url: URL;
  let base: URL;
  try {
    base = new URL(origin);
    url = new URL(value, `${base.origin}/`);
  } catch {
    return null;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  if (url.username !== '' || url.password !== '') return null;

  if (url.origin === base.origin) {
    if (!isAppPath(url.pathname)) return null;
    return { kind: 'internal', href: `${url.pathname}${url.search}${url.hash}`, host: url.host };
  }
  return { kind: 'external', href: url.href, host: url.host };
}

/**
 * The host to name in an image placeholder, whether or not the address may
 * be followed: the parsed host, or "no web address" when it has none.
 */
export function addressHost(raw: string | null | undefined, origin: string = currentOrigin()): string {
  if (typeof raw !== 'string') return 'no web address';
  const value = normaliseUrl(raw);
  if (value === '') return 'no web address';
  try {
    const url = new URL(value, `${new URL(origin).origin}/`);
    return url.host || 'no web address';
  } catch {
    return 'no web address';
  }
}
