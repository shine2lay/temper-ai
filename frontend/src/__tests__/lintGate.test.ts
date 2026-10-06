/**
 * The lint gate behind safe rendering: lints small made-up snippets through
 * this repo's real eslint config and checks each banned pattern is caught.
 * The snippets are never run; they only exist as text here.
 */
import { describe, it, expect } from 'vitest';

import { ESLint } from 'eslint';

// The frontend folder, with a trailing slash (this file is src/__tests__/lintGate.test.ts).
// Plain string work: the app's tsconfig has no Node types.
const FRONTEND = decodeURIComponent(import.meta.url.replace(/^file:\/\//, '').replace(/src\/__tests__\/[^/]+$/, ''));
const eslint = new ESLint({ cwd: FRONTEND });

async function rulesFor(code: string, file: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath: FRONTEND + file });
  return result.messages.map((m) => m.ruleId ?? 'fatal: ' + m.message);
}

const APP_FILE = 'src/components/probe/Probe.tsx';
const SAFE_MARKDOWN = 'src/components/shared/SafeMarkdown.tsx';

const SINKS: [string, string][] = [
  ['dangerouslySetInnerHTML (JSX)', `export const A = () => <div dangerouslySetInnerHTML={{ __html: '' }} />;`],
  ['dangerouslySetInnerHTML (props object)', `export const props = { dangerouslySetInnerHTML: { __html: '' } };`],
  ['innerHTML', `export function f(el: HTMLElement) { el.innerHTML = ''; }`],
  ['outerHTML', `export function f(el: HTMLElement) { el.outerHTML = ''; }`],
  ['innerHTML (computed)', `export function f(el: HTMLElement) { el['innerHTML'] = ''; }`],
  ['insertAdjacentHTML', `export function f(el: HTMLElement) { el.insertAdjacentHTML('beforeend', ''); }`],
  ['createContextualFragment', `export const f = () => document.createRange().createContextualFragment('');`],
  ['document.write', `export const f = () => document.write('');`],
  ['DOMParser', `export const f = () => new DOMParser();`],
  ['srcDoc', `export const A = () => <iframe title="t" srcDoc="" />;`],
  ['srcdoc property', `export function f(el: HTMLIFrameElement) { el.srcdoc = ''; }`],
];

const RAW_HTML_PACKAGES = ['rehype-raw', 'rehype-sanitize', 'rehype-highlight', 'rehype', 'remark-rehype', 'hast-util-raw'];

describe('the lint gate', () => {
  it('bans every HTML sink in src', async () => {
    for (const [name, code] of SINKS) {
      const rules = await rulesFor(code, APP_FILE);
      expect(rules, name).toContain('no-restricted-syntax');
    }
  }, 60_000);

  it('bans rehype plugins and raw-HTML packages everywhere', async () => {
    for (const pkg of RAW_HTML_PACKAGES) {
      const code = `import probe from '${pkg}';\nexport const used = probe;`;
      for (const file of [APP_FILE, SAFE_MARKDOWN, 'e2e/probe.spec.ts']) {
        expect(await rulesFor(code, file), `${pkg} in ${file}`).toContain('no-restricted-imports');
      }
    }
  }, 60_000);

  it('allows react-markdown only in SafeMarkdown.tsx', async () => {
    const code = `import ReactMarkdown from 'react-markdown';\nexport const used = ReactMarkdown;`;
    expect(await rulesFor(code, APP_FILE)).toContain('no-restricted-imports');
    expect(await rulesFor(code, 'src/components/shared/MarkdownDisplay.tsx')).toContain('no-restricted-imports');
    expect(await rulesFor(code, SAFE_MARKDOWN)).not.toContain('no-restricted-imports');
  }, 60_000);

  it('leaves tests free to use the sinks', async () => {
    const code = `export function f(el: HTMLElement) { return el.innerHTML; }`;
    expect(await rulesFor(code, 'src/__tests__/probe.test.tsx')).not.toContain('no-restricted-syntax');
  }, 60_000);
});
