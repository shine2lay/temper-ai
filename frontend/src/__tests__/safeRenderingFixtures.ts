/**
 * Inert, made-up content for the safe-rendering proofs.
 *
 * Shared by the component tests (safeRendering.test.tsx) and the browser
 * tripwire (e2e/safeRendering.spec.ts), so both prove the same words.
 *
 * Every address points at a reserved `.invalid` host, so nothing could ever
 * answer, and the browser test aborts every request anyway. The markup is
 * harmless custom markup (`x-probe`) and `data-probe` tripwire attributes:
 * if either ever turns up as a real element or attribute, content became
 * markup. No script, no handler attribute, no credential-like value and no
 * real agent output appears here.
 */

/** The tripwire attribute: it must never become a real attribute. */
export const PROBE_ATTR = 'data-probe';

/** A plain sentence every surface shows, so a test can wait for the content. */
export const MARKER = 'Probe marker sentence.';

/* ---------- ordinary words ---------- */

export const PUNCTUATION = `Quotes "double" and 'single', an ampersand & and angle brackets < and > in a sentence.`;

/** Harmless custom markup: it must stay literal text. */
export const CUSTOM_MARKUP = '<x-probe data-probe="raw">raw markup stays text</x-probe>';

/** Raw image markup: it must stay literal text and never load. */
export const RAW_IMAGE = '<img src="https://images.invalid/probe-raw.png" alt="raw probe">';

/* ---------- links ---------- */

export interface LinkCase {
  name: string;
  markdown: string;
  /** The words shown for the link. */
  text: string;
  /** What the link must be: an anchor to `href`, or plain text. */
  expect: { anchor: true; href: string; external: boolean } | { anchor: false };
}

export const LINKS: LinkCase[] = [
  {
    name: 'https link',
    markdown: '[external docs](https://docs.invalid/guide)',
    text: 'external docs',
    expect: { anchor: true, href: 'https://docs.invalid/guide', external: true },
  },
  {
    name: 'quote inside the address',
    markdown: '[quoted docs](https://docs.invalid/a"data-probe="link)',
    text: 'quoted docs',
    expect: { anchor: true, href: 'https://docs.invalid/a%22data-probe=%22link', external: true },
  },
  {
    name: 'dashboard page under /app/',
    markdown: '[run list](/app/runs)',
    text: 'run list',
    expect: { anchor: true, href: '/app/runs', external: false },
  },
  {
    name: 'fragment',
    markdown: '[notes section](#notes)',
    text: 'notes section',
    expect: { anchor: true, href: '#notes', external: false },
  },
  { name: 'mailto', markdown: '[mail probe](mailto:someone@docs.invalid)', text: 'mail probe', expect: { anchor: false } },
  { name: 'ftp', markdown: '[ftp probe](ftp://files.invalid/probe.txt)', text: 'ftp probe', expect: { anchor: false } },
  { name: 'tel', markdown: '[tel probe](tel:0000)', text: 'tel probe', expect: { anchor: false } },
  { name: 'unknown scheme', markdown: '[scheme probe](x-probe:inert)', text: 'scheme probe', expect: { anchor: false } },
  { name: 'data address', markdown: '[data link probe](data:text/plain,probe)', text: 'data link probe', expect: { anchor: false } },
  {
    name: 'userinfo',
    markdown: '[userinfo docs](https://someone@docs.invalid/guide)',
    text: 'userinfo docs',
    expect: { anchor: false },
  },
  { name: 'dashboard api path', markdown: '[api path](/api/runs)', text: 'api path', expect: { anchor: false } },
  { name: 'dot segments out of /app/', markdown: '[dotted path](/app/../api/runs)', text: 'dotted path', expect: { anchor: false } },
  {
    name: 'encoded slash out of /app/',
    markdown: '[encoded path](/app/..%2Fapi/runs)',
    text: 'encoded path',
    expect: { anchor: false },
  },
];

/** One paragraph per link, so each can be found on its own. */
export const LINK_DOC = LINKS.map((l) => `Link: ${l.markdown}`).join('\n\n');

/* ---------- images ---------- */

export interface ImageCase {
  name: string;
  /** The markdown, and any definition it needs (added at the end of the document). */
  markdown: string;
  definition?: string;
  alt: string;
  /** The host shown in the placeholder; `ORIGIN_HOST` means the dashboard's own. */
  host: string;
  /** A deliberate link to this address, or plain text. */
  link: string | null;
}

/** Stands for the dashboard's own host (localhost:<port> in a test). */
export const ORIGIN_HOST = '<origin host>';

export const IMAGES: ImageCase[] = [
  {
    name: 'inline',
    markdown: '![inline probe](https://images.invalid/probe-inline.png)',
    alt: 'inline probe',
    host: 'images.invalid',
    link: 'https://images.invalid/probe-inline.png',
  },
  {
    name: 'titled',
    markdown: '![titled probe](https://images.invalid/probe-titled.png "A title")',
    alt: 'titled probe',
    host: 'images.invalid',
    link: 'https://images.invalid/probe-titled.png',
  },
  {
    name: 'full reference',
    markdown: '![reference probe][probe-ref]',
    definition: '[probe-ref]: https://images.invalid/probe-reference.png',
    alt: 'reference probe',
    host: 'images.invalid',
    link: 'https://images.invalid/probe-reference.png',
  },
  {
    name: 'collapsed reference',
    markdown: '![collapsed probe][]',
    definition: '[collapsed probe]: https://images.invalid/probe-collapsed.png',
    alt: 'collapsed probe',
    host: 'images.invalid',
    link: 'https://images.invalid/probe-collapsed.png',
  },
  {
    name: 'shortcut reference',
    markdown: '![shortcut probe]',
    definition: '[shortcut probe]: https://images.invalid/probe-shortcut.png',
    alt: 'shortcut probe',
    host: 'images.invalid',
    link: 'https://images.invalid/probe-shortcut.png',
  },
  {
    name: 'empty alt',
    markdown: '![](https://images.invalid/probe-empty.png)',
    alt: 'untitled',
    host: 'images.invalid',
    link: 'https://images.invalid/probe-empty.png',
  },
  {
    name: 'angle-bracket address',
    markdown: '![angle probe](<https://images.invalid/probe angle.png>)',
    alt: 'angle probe',
    host: 'images.invalid',
    link: 'https://images.invalid/probe%20angle.png',
  },
  {
    name: 'dashboard page under /app/',
    markdown: '![app probe](/app/probe-app.png)',
    alt: 'app probe',
    host: ORIGIN_HOST,
    link: '/app/probe-app.png',
  },
  {
    name: 'dashboard api path',
    markdown: '![api probe](/api/probe.png)',
    alt: 'api probe',
    host: ORIGIN_HOST,
    link: null,
  },
  {
    name: 'userinfo',
    markdown: '![userinfo probe](https://someone@images.invalid/probe-userinfo.png)',
    alt: 'userinfo probe',
    host: 'images.invalid',
    link: null,
  },
  {
    name: 'ftp address',
    markdown: '![ftp probe](ftp://files.invalid/probe.png)',
    alt: 'ftp probe',
    host: 'files.invalid',
    link: null,
  },
  {
    name: 'data address',
    markdown: '![data probe](data:text/plain,probe)',
    alt: 'data probe',
    host: 'no web address',
    link: null,
  },
];

/** An image inside a link: the link stays, the image becomes its words. */
export const LINKED_IMAGE = {
  markdown: '[![linked probe](https://images.invalid/probe-linked.png)](https://docs.invalid/linked)',
  alt: 'linked probe',
  host: 'images.invalid',
  href: 'https://docs.invalid/linked',
};

export const IMAGE_DOC = [
  ...IMAGES.map((i) => i.markdown),
  LINKED_IMAGE.markdown,
  RAW_IMAGE,
  ...IMAGES.flatMap((i) => (i.definition ? [i.definition] : [])),
].join('\n\n');

/** The words a placeholder shows. */
export function placeholderText(alt: string, host: string, originHost: string): string {
  return `Image: ${alt} (${host === ORIGIN_HOST ? originHost : host})`;
}

/* ---------- whole documents ---------- */

/** What MarkdownDisplay is given on every surface that uses it. */
export const DISPLAY_PROBE_DOC = [
  '# Probe report',
  MARKER,
  PUNCTUATION,
  CUSTOM_MARKUP,
  LINK_DOC,
  'Email autolink: someone@docs.invalid',
  IMAGE_DOC,
].join('\n\n');

/** What SmartContent is given as markdown (it starts with a heading, so it is read as markdown). */
export const SMART_PROBE_DOC = [
  '# Probe report',
  MARKER,
  PUNCTUATION,
  CUSTOM_MARKUP,
  LINK_DOC,
  IMAGES[0].markdown,
  LINKED_IMAGE.markdown,
  RAW_IMAGE,
].join('\n\n');

/* ---------- code ---------- */

/** Fenced code holding markup: every character must show as typed. */
export const CODE_MARKUP_LINES = [
  '<x-probe data-probe="code">probe</x-probe>',
  '<img src="https://images.invalid/probe-code.png" alt="code probe">',
];
export const CODE_FENCED_MARKUP = ['```html', ...CODE_MARKUP_LINES, '```'].join('\n');

/** Code found by its first word, not a fence. */
export const CODE_AUTO_MARKUP = `const probe = '<x-probe data-probe="auto">auto</x-probe>';`;

/** Generic type brackets: they must stay visible. */
export const CODE_GENERIC_LINE = 'List<String> names = new ArrayList<>();';
export const CODE_GENERIC = ['```java', CODE_GENERIC_LINE, '```'].join('\n');

/** Ordinary code: today's three colours. */
export const CODE_ORDINARY_LINES = [
  'const greeting = "hello"; // say hi',
  'def main():  # entry point',
  '    return None',
];
export const CODE_ORDINARY = ['```', ...CODE_ORDINARY_LINES, '```'].join('\n');

/** The code a code surface shows in the browser tripwire. */
export const CODE_PROBE = ['```html', MARKER, ...CODE_MARKUP_LINES, CODE_GENERIC_LINE, '```'].join('\n');

/* ---------- JSON and plain text ---------- */

export const JSON_PROBE = JSON.stringify({
  '<x-probe data-probe="key">': '<x-probe data-probe="value">value</x-probe>',
  image: '![json probe](https://images.invalid/probe-json.png)',
  quote: `say "hi" & 'bye'`,
});

export const TEXT_PROBE = `Plain words with <x-probe data-probe="text">markup</x-probe> & "quotes" stay as they are.`;
