/**
 * The navigation policy for addresses from content (src/lib/safeUrl.ts).
 *
 * Script-capable scheme names appear here as strings only: they are checked,
 * never rendered or followed.
 */
import { describe, it, expect } from 'vitest';
import { addressHost, normaliseUrl, safeUrl } from '@/lib/safeUrl';

const ORIGIN = 'https://dashboard.invalid';

const ALLOWED: [string, 'external' | 'internal' | 'fragment', string][] = [
  ['https://docs.invalid/guide', 'external', 'https://docs.invalid/guide'],
  ['http://docs.invalid/guide', 'external', 'http://docs.invalid/guide'],
  ['HTTPS://DOCS.invalid/Guide', 'external', 'https://docs.invalid/Guide'],
  ['https://docs.invalid/a"b', 'external', 'https://docs.invalid/a%22b'],
  ['//docs.invalid/guide', 'external', 'https://docs.invalid/guide'],
  ['\\\\docs.invalid\\guide', 'external', 'https://docs.invalid/guide'],
  ['  https://docs.invalid/guide  ', 'external', 'https://docs.invalid/guide'],
  ['\u0000\u001fhttps://docs.invalid/guide\u0007', 'external', 'https://docs.invalid/guide'],
  ['ht\ttps://docs.invalid/gu\nide\r', 'external', 'https://docs.invalid/guide'],
  ['https://docs.invalid:8443/guide?q=1#top', 'external', 'https://docs.invalid:8443/guide?q=1#top'],
  ['/app/runs', 'internal', '/app/runs'],
  ['/app/workflow/abc?tab=out#x', 'internal', '/app/workflow/abc?tab=out#x'],
  ['app/runs', 'internal', '/app/runs'],
  ['https://dashboard.invalid/app/runs', 'internal', '/app/runs'],
  ['#notes', 'fragment', '#notes'],
  ['  #notes', 'fragment', '#notes'],
];

const REJECTED: [string, string][] = [
  ['mailto', 'mailto:someone@docs.invalid'],
  ['ftp', 'ftp://files.invalid/probe.txt'],
  ['tel', 'tel:0000'],
  ['unknown scheme', 'x-probe:inert'],
  ['data', 'data:text/plain,probe'],
  ['blob', 'blob:https://docs.invalid/0000'],
  ['file', 'file:///probe.txt'],
  ['javascript', 'javascript:void(0)'],
  ['javascript, mixed case', 'JaVaScRiPt:void(0)'],
  ['javascript, tab inside', 'java\tscript:void(0)'],
  ['javascript, newline inside', 'java\nscript:void(0)'],
  ['javascript, leading control', '\u0001javascript:void(0)'],
  ['vbscript', 'vbscript:probe'],
  ['user name', 'https://someone@docs.invalid/guide'],
  ['user name and password', 'https://someone:placeholder@docs.invalid/guide'],
  ['empty user name with password', 'https://:placeholder@docs.invalid/guide'],
  ['dashboard api', '/api/runs'],
  ['dashboard api, absolute', 'https://dashboard.invalid/api/runs'],
  ['dashboard root', '/'],
  ['dashboard /app without slash', '/app'],
  ['other dashboard path', '/apples'],
  ['upper-case APP', '/APP/runs'],
  ['dot segments out of /app/', '/app/../api/runs'],
  ['encoded dot segments', '/app/%2e%2e/api/runs'],
  ['encoded slash out of /app/', '/app/..%2Fapi/runs'],
  ['encoded slash after app', '/app%2Fruns'],
  ['backslash dot segments', '/app/..\\api\\runs'],
  ['relative path off /app/', 'runs'],
  ['bad escape', '/app/%E0%A4%A'],
  ['empty', ''],
  ['spaces only', '   '],
  ['controls only', '\u0000\u0001'],
];

describe('safeUrl', () => {
  it.each(ALLOWED)('allows %j as %s', (raw, kind, href) => {
    expect(safeUrl(raw, ORIGIN)).toMatchObject({ kind, href });
  });

  it.each(REJECTED)('shows %s as plain text', (_name, raw) => {
    expect(safeUrl(raw, ORIGIN)).toBeNull();
  });

  it('rejects what is not a string', () => {
    expect(safeUrl(null, ORIGIN)).toBeNull();
    expect(safeUrl(undefined, ORIGIN)).toBeNull();
  });

  it('gives back an accepted address unchanged when checked again', () => {
    for (const [raw] of ALLOWED) {
      const first = safeUrl(raw, ORIGIN)!;
      expect(safeUrl(first.href, ORIGIN)).toEqual(first);
    }
  });

  it('names the host to show', () => {
    expect(safeUrl('https://docs.invalid/guide', ORIGIN)?.host).toBe('docs.invalid');
    expect(safeUrl('/app/runs', ORIGIN)?.host).toBe('dashboard.invalid');
    expect(safeUrl('#notes', ORIGIN)?.host).toBe('');
  });

  it('uses the page origin by default', () => {
    expect(safeUrl('/app/runs')).toMatchObject({ kind: 'internal', host: window.location.host });
    expect(safeUrl('/api/runs')).toBeNull();
  });
});

describe('normaliseUrl', () => {
  it('strips tab, CR and LF everywhere and controls and spaces at both ends', () => {
    expect(normaliseUrl(' \u0000ht\ttp\ns://a.invalid/b\r \u001f')).toBe('https://a.invalid/b');
    expect(normaliseUrl('https://a.invalid/b c')).toBe('https://a.invalid/b c');
  });
});

describe('addressHost', () => {
  it.each([
    ['https://images.invalid/p.png', 'images.invalid'],
    ['https://someone@images.invalid/p.png', 'images.invalid'],
    ['ftp://files.invalid/p.png', 'files.invalid'],
    ['/app/p.png', 'dashboard.invalid'],
    ['/api/p.png', 'dashboard.invalid'],
    ['data:text/plain,probe', 'no web address'],
    ['x-probe:inert', 'no web address'],
    ['', 'no web address'],
    ['  ', 'no web address'],
  ])('names the host of %j as %j', (raw, host) => {
    expect(addressHost(raw, ORIGIN)).toBe(host);
  });

  it('has no host for what is not a string', () => {
    expect(addressHost(undefined, ORIGIN)).toBe('no web address');
  });
});
