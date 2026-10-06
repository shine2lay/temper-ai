/**
 * The shared safe markdown renderer's own rules (src/components/shared/SafeMarkdown.tsx,
 * src/lib/safeMarkdownPolicy.ts) and SmartContent's code colouring (src/lib/codeTokens.ts).
 * All content is made up and inert.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { SafeMarkdown } from '@/components/shared/SafeMarkdown';
import { ALLOWED_ELEMENTS, LOADING_ELEMENTS, imagePlaceholderText } from '@/lib/safeMarkdownPolicy';
import { CODE_TOKEN_CLASS, tokenizeCodeLine, type CodeToken } from '@/lib/codeTokens';

afterEach(cleanup);

describe('SafeMarkdown policy', () => {
  it('allows no element that loads anything', () => {
    const allowed = new Set<string>(ALLOWED_ELEMENTS);
    for (const tag of LOADING_ELEMENTS) expect(allowed.has(tag), tag).toBe(false);
  });

  it('allows text structure only', () => {
    expect([...ALLOWED_ELEMENTS].sort()).toEqual(
      ['a', 'blockquote', 'br', 'code', 'del', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'input', 'li', 'ol', 'p',
        'pre', 'section', 'strong', 'sup', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'ul'].sort(),
    );
  });

  it('words an image by its alt and host', () => {
    expect(imagePlaceholderText('a chart', 'https://images.invalid/c.png')).toBe('Image: a chart (images.invalid)');
    expect(imagePlaceholderText('', 'https://images.invalid/c.png')).toBe('Image: untitled (images.invalid)');
    expect(imagePlaceholderText('  ', 'data:text/plain,x')).toBe('Image: untitled (no web address)');
  });

  it('shows a reference image without a definition as its own text', () => {
    const { container } = render(<SafeMarkdown content="![no such image][missing]" />);
    expect(container.textContent).toBe('![no such image][missing]');
    expect(container.querySelector('img')).toBeNull();
  });

  it('keeps a placeholder marker out of reach of content', () => {
    const { container } = render(
      <SafeMarkdown content={'<a href="ftp://files.invalid/x" data-image-placeholder="true">raw</a>'} />,
    );
    expect(container.querySelector('a')).toBeNull();
    expect(container.textContent).toContain('data-image-placeholder');
  });

  it('turns a task list box into a disabled checkbox only', () => {
    render(<SafeMarkdown content={'- [x] done\n- [ ] open'} gfm />);
    const boxes = screen.getAllByRole('checkbox');
    expect(boxes.map((b) => [(b as HTMLInputElement).type, (b as HTMLInputElement).disabled])).toEqual([
      ['checkbox', true],
      ['checkbox', true],
    ]);
  });

  it('keeps footnote links working inside the page', () => {
    const { container } = render(<SafeMarkdown content={'A note[^1].\n\n[^1]: Words.'} gfm />);
    const ref = container.querySelector('sup a')!;
    expect(ref.getAttribute('href')).toMatch(/^#/);
    expect(container.querySelector(ref.getAttribute('href')!)).not.toBeNull();
  });

  it('shows indented and fenced code as text', () => {
    const { container } = render(<SafeMarkdown content={'```\n<x-probe>code</x-probe>\n```'} />);
    expect(container.querySelector('x-probe')).toBeNull();
    expect(container.querySelector('pre code')?.textContent).toBe('<x-probe>code</x-probe>\n');
  });

  it('breaks single newlines only when asked', () => {
    const { container: plain } = render(<SafeMarkdown content={'one\ntwo'} />);
    expect(plain.querySelectorAll('br')).toHaveLength(0);
    cleanup();
    const { container: broken } = render(<SafeMarkdown content={'one\ntwo'} softBreaks />);
    expect(broken.querySelectorAll('br')).toHaveLength(1);
  });
});

const t = (kind: CodeToken['kind'], text: string): CodeToken => ({ kind, text });

describe('tokenizeCodeLine', () => {
  it.each<[string, CodeToken[]]>([
    ['', []],
    ['plain words', [t('plain', 'plain words')]],
    ['const x = 1;', [t('keyword', 'const'), t('plain', ' x = 1;')]],
    ['reimport classy', [t('plain', 'reimport classy')]],
    ['x.import(y)', [t('plain', 'x.'), t('keyword', 'import'), t('plain', '(y)')]],
    ['s = "a // b" // note', [t('plain', 's = '), t('string', '"a // b"'), t('plain', ' '), t('comment', '// note')]],
    ["c = '#fff'  # colour", [t('plain', 'c = '), t('string', "'#fff'"), t('plain', '  '), t('comment', '# colour')]],
    ['# for each one', [t('comment', '# for each one')]],
    ["# don't 'stop'", [t('comment', "# don't 'stop'")]],
    ['say "it\'s" now', [t('plain', 'say "it\'s" now')]],
    ['`tpl ${x}`', [t('string', '`tpl ${x}`')]],
    ['a < b > c', [t('plain', 'a < b > c')]],
    ['return None', [t('keyword', 'return'), t('plain', ' '), t('keyword', 'None')]],
  ])('colours %j', (line, expected) => {
    const tokens = tokenizeCodeLine(line);
    expect(tokens.map((x) => x.text).join('')).toBe(line);
    expect(tokens).toEqual(expected);
  });

  it('never loses or adds a character', () => {
    for (const line of ['<x-probe data-probe="code">probe</x-probe>', 'List<String> a = new ArrayList<>();', '\'"`', '//', '#']) {
      expect(tokenizeCodeLine(line).map((x) => x.text).join('')).toBe(line);
    }
  });

  it('keeps the three classes', () => {
    expect(CODE_TOKEN_CLASS).toEqual({
      keyword: 'text-violet-400 font-medium',
      string: 'text-emerald-400',
      comment: 'text-temper-text-dim italic',
    });
  });
});
