/**
 * Safe rendering proofs: content shown on the dashboard never becomes markup
 * and never makes the browser load anything.
 *
 * These tests drive the public components only (SmartContent,
 * MarkdownDisplay, OutputDisplay), so the same file runs on the old code
 * (where the expected failures are written down beforehand) and on the new.
 * Every fixture is inert and made up: see safeRenderingFixtures.ts.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import { SmartContent } from '@/components/shared/SmartContent';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import { OutputDisplay } from '@/components/shared/OutputDisplay';
import {
  CODE_AUTO_MARKUP,
  CODE_FENCED_MARKUP,
  CODE_GENERIC,
  CODE_GENERIC_LINE,
  CODE_MARKUP_LINES,
  CODE_ORDINARY,
  CODE_ORDINARY_LINES,
  CUSTOM_MARKUP,
  DISPLAY_PROBE_DOC,
  IMAGES,
  IMAGE_DOC,
  JSON_PROBE,
  LINKED_IMAGE,
  LINKS,
  PROBE_ATTR,
  RAW_IMAGE,
  SMART_PROBE_DOC,
  TEXT_PROBE,
  placeholderText,
} from './safeRenderingFixtures';

/** Every element that fetches something, or can. (svg itself is allowed: the copy button's icon is one.) */
const LOADING =
  'img, picture, video, audio, iframe, frame, object, embed, source, track, link, script, style, image, use, input[type="image"]';

const originHost = () => window.location.host;

function noMarkupFromContent(container: HTMLElement) {
  expect(container.querySelectorAll('x-probe')).toHaveLength(0);
  expect(container.querySelectorAll(`[${PROBE_ATTR}]`)).toHaveLength(0);
}

function nothingLoads(container: HTMLElement) {
  expect(container.querySelectorAll(LOADING)).toHaveLength(0);
}

function codeText(container: HTMLElement): string {
  const pre = container.querySelector('pre');
  expect(pre).not.toBeNull();
  return Array.from(pre!.querySelectorAll(':scope > div'))
    .map((row) => (row.lastElementChild?.textContent ?? ''))
    .join('\n');
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('SmartContent code (F1)', () => {
  it('fenced code shows markup as the literal source', () => {
    const { container } = render(<SmartContent content={CODE_FENCED_MARKUP} />);
    noMarkupFromContent(container);
    const text = codeText(container);
    for (const line of CODE_MARKUP_LINES) expect(text).toContain(line);
  });

  it('auto-detected code shows markup as the literal source', () => {
    const { container } = render(<SmartContent content={CODE_AUTO_MARKUP} />);
    noMarkupFromContent(container);
    expect(codeText(container)).toBe(CODE_AUTO_MARKUP);
  });

  it('code makes no element that loads anything', () => {
    const { container } = render(<SmartContent content={CODE_FENCED_MARKUP} />);
    nothingLoads(container);
  });

  it('generic type brackets stay visible', () => {
    const { container } = render(<SmartContent content={CODE_GENERIC} />);
    expect(codeText(container).split('\n')[0]).toBe(CODE_GENERIC_LINE);
  });

  it('keywords, strings and comments keep their three classes', () => {
    const { container } = render(<SmartContent content={CODE_ORDINARY} />);
    const coloured = Array.from(container.querySelectorAll('pre span[class]')).map((s) => [
      s.getAttribute('class'),
      s.textContent,
    ]);
    const keyword = 'text-violet-400 font-medium';
    const string = 'text-emerald-400';
    const comment = 'text-temper-text-dim italic';
    expect(coloured).toContainEqual([keyword, 'const']);
    expect(coloured).toContainEqual([string, '"hello"']);
    expect(coloured).toContainEqual([comment, '// say hi']);
    expect(coloured).toContainEqual([keyword, 'def']);
    expect(coloured).toContainEqual([comment, '# entry point']);
    expect(coloured).toContainEqual([keyword, 'return']);
    expect(coloured).toContainEqual([keyword, 'None']);
  });

  it('line numbers and wrapping stay as they are', () => {
    const { container } = render(<SmartContent content={CODE_ORDINARY} />);
    const pre = container.querySelector('pre')!;
    expect(pre.className).toContain('whitespace-pre-wrap');
    expect(pre.className).toContain('break-words');
    const rows = Array.from(pre.querySelectorAll(':scope > div'));
    // A fenced block keeps its trailing empty line, as it always has.
    expect(rows.length).toBeGreaterThanOrEqual(CODE_ORDINARY_LINES.length);
    CODE_ORDINARY_LINES.forEach((line, i) => expect(rows[i].lastElementChild!.textContent).toBe(line));
    rows.forEach((row, i) => {
      expect(row.className).toBe('flex');
      const number = row.firstElementChild!;
      expect(number.textContent).toBe(String(i + 1));
      expect(number.className).toContain('select-none');
      expect(row.lastElementChild!.className).toBe('flex-1');
    });
  });
});

describe('SmartContent markdown (F2)', () => {
  it('a quote inside a link address never becomes an attribute', () => {
    const { container } = render(<SmartContent content={SMART_PROBE_DOC} />);
    noMarkupFromContent(container);
  });

  it('allowed links stay links to the expected address', () => {
    render(<SmartContent content={SMART_PROBE_DOC} />);
    for (const link of LINKS) {
      if (!link.expect.anchor) continue;
      expect(screen.getByRole('link', { name: link.text })).toHaveAttribute('href', link.expect.href);
    }
  });

  it('https links carry noopener noreferrer and no referrer, in the same tab', () => {
    render(<SmartContent content={SMART_PROBE_DOC} />);
    for (const link of LINKS) {
      if (!link.expect.anchor || !link.expect.external) continue;
      const a = screen.getByRole('link', { name: link.text });
      expect(a).toHaveAttribute('rel', 'noopener noreferrer');
      expect(a).toHaveAttribute('referrerpolicy', 'no-referrer');
      expect(a).not.toHaveAttribute('target');
    }
  });

  it('other schemes, userinfo and other dashboard paths show as plain text', () => {
    render(<SmartContent content={SMART_PROBE_DOC} />);
    for (const link of LINKS) {
      if (link.expect.anchor) continue;
      expect(screen.queryByRole('link', { name: link.text })).toBeNull();
      expect(screen.getByText(link.text)).toBeInTheDocument();
    }
  });

  it('raw and custom markup stay literal text', () => {
    const { container } = render(<SmartContent content={SMART_PROBE_DOC} />);
    expect(container.textContent).toContain(CUSTOM_MARKUP);
    expect(container.textContent).toContain(RAW_IMAGE);
    noMarkupFromContent(container);
    nothingLoads(container);
  });

  it('markdown image syntax shows the image placeholder', () => {
    const { container } = render(<SmartContent content={SMART_PROBE_DOC} />);
    const image = IMAGES[0];
    const words = placeholderText(image.alt, image.host, originHost());
    const link = screen.getByRole('link', { name: words });
    expect(link).toHaveAttribute('href', image.link);
    expect(link).toHaveAttribute('target', '_blank');
    expect(container.textContent).not.toContain(`!${words}`);
    nothingLoads(container);
  });

  it('headings, emphasis, lists and inline code still render', () => {
    const { container } = render(
      <SmartContent content={'# Title\n\n**bold words** and *slanted words* and `inline code`\n\n- first item\n- second item'} />,
    );
    expect(screen.getByRole('heading', { name: 'Title' })).toBeInTheDocument();
    expect(container.querySelector('strong')?.textContent).toBe('bold words');
    expect(container.querySelector('em')?.textContent).toBe('slanted words');
    expect(container.querySelector('code')?.textContent).toBe('inline code');
    const items = screen.getAllByRole('listitem').map((li) => li.textContent);
    expect(items).toEqual(['first item', 'second item']);
  });

  it('single newlines still break lines', () => {
    render(<SmartContent content={'# Notes\n\nline one\nline two'} />);
    const first = screen.getByText(/line one/);
    const textNode = Array.from(first.childNodes).find((n) => n.textContent === 'line one');
    expect(textNode).toBeDefined();
    expect(textNode!.nextSibling?.nodeName).toBe('BR');
    let after = '';
    for (let n = textNode!.nextSibling?.nextSibling; n; n = n.nextSibling) after += n.textContent;
    expect(after.trim()).toBe('line two');
  });
});

describe('MarkdownDisplay images (F3)', () => {
  it('no image variant makes an element that loads anything', () => {
    const { container } = render(<MarkdownDisplay content={DISPLAY_PROBE_DOC} />);
    nothingLoads(container);
  });

  it('every image variant shows its placeholder', () => {
    render(<MarkdownDisplay content={IMAGE_DOC} />);
    for (const image of IMAGES) {
      expect(screen.getByText(placeholderText(image.alt, image.host, originHost()))).toBeInTheDocument();
    }
  });

  it('a placeholder whose address passes is a new-tab link without referrer', () => {
    render(<MarkdownDisplay content={IMAGE_DOC} />);
    for (const image of IMAGES) {
      if (image.link === null) continue;
      const link = screen.getByRole('link', { name: placeholderText(image.alt, image.host, originHost()) });
      expect(link).toHaveAttribute('href', image.link);
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
      expect(link).toHaveAttribute('referrerpolicy', 'no-referrer');
    }
  });

  it('a placeholder whose address fails is plain text', () => {
    render(<MarkdownDisplay content={IMAGE_DOC} />);
    for (const image of IMAGES) {
      if (image.link !== null) continue;
      const words = placeholderText(image.alt, image.host, originHost());
      expect(screen.getByText(words)).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: words })).toBeNull();
    }
  });

  it('an image inside a link adds no second link', () => {
    const { container } = render(<MarkdownDisplay content={LINKED_IMAGE.markdown} />);
    const words = placeholderText(LINKED_IMAGE.alt, LINKED_IMAGE.host, originHost());
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAccessibleName(words);
    expect(links[0]).toHaveAttribute('href', LINKED_IMAGE.href);
    expect(container.querySelectorAll('a a')).toHaveLength(0);
    nothingLoads(container);
  });

  it('raw image markup stays literal text', () => {
    const { container } = render(<MarkdownDisplay content={RAW_IMAGE} />);
    expect(container.textContent).toContain(RAW_IMAGE);
    nothingLoads(container);
  });
});

describe('MarkdownDisplay links and markup', () => {
  it('allowed links stay links to the expected address', () => {
    render(<MarkdownDisplay content={DISPLAY_PROBE_DOC} />);
    for (const link of LINKS) {
      if (!link.expect.anchor) continue;
      expect(screen.getByRole('link', { name: link.text })).toHaveAttribute('href', link.expect.href);
    }
  });

  it('https links carry noopener noreferrer and no referrer, in the same tab', () => {
    render(<MarkdownDisplay content={DISPLAY_PROBE_DOC} />);
    for (const link of LINKS) {
      if (!link.expect.anchor || !link.expect.external) continue;
      const a = screen.getByRole('link', { name: link.text });
      expect(a).toHaveAttribute('rel', 'noopener noreferrer');
      expect(a).toHaveAttribute('referrerpolicy', 'no-referrer');
      expect(a).not.toHaveAttribute('target');
    }
  });

  it('other schemes, userinfo and other dashboard paths show as plain text', () => {
    render(<MarkdownDisplay content={DISPLAY_PROBE_DOC} />);
    for (const link of LINKS) {
      if (link.expect.anchor) continue;
      expect(screen.queryByRole('link', { name: link.text })).toBeNull();
      expect(screen.getByText(link.text)).toBeInTheDocument();
    }
  });

  it('email autolinks show as plain text', () => {
    render(<MarkdownDisplay content={DISPLAY_PROBE_DOC} />);
    expect(screen.queryByRole('link', { name: 'someone@docs.invalid' })).toBeNull();
    expect(screen.getByText('someone@docs.invalid')).toBeInTheDocument();
  });

  it('a quote inside a link address never becomes an attribute', () => {
    const { container } = render(<MarkdownDisplay content={DISPLAY_PROBE_DOC} />);
    noMarkupFromContent(container);
  });

  it('raw and custom markup stay literal text', () => {
    const { container } = render(<MarkdownDisplay content={DISPLAY_PROBE_DOC} />);
    expect(screen.getByText(CUSTOM_MARKUP)).toBeInTheDocument();
    expect(container.textContent).toContain(RAW_IMAGE);
    noMarkupFromContent(container);
  });

  const GFM_DOC = [
    '| Left | Right |',
    '|:-----|------:|',
    '| a | b |',
    '',
    '- [x] done item',
    '- [ ] open item',
    '',
    '~~gone words~~',
    '',
    'A noted line[^1].',
    '',
    '[^1]: The footnote words.',
  ].join('\n');

  it('tables, task lists, strikethrough and footnotes still render', () => {
    const { container } = render(<MarkdownDisplay content={GFM_DOC} />);
    const table = screen.getByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'Left' })).toBeInTheDocument();
    expect(within(table).getByRole('cell', { name: 'b' })).toBeInTheDocument();
    const boxes = screen.getAllByRole('checkbox');
    expect(boxes).toHaveLength(2);
    expect(boxes[0]).toBeChecked();
    expect(boxes[1]).not.toBeChecked();
    for (const box of boxes) expect(box).toBeDisabled();
    expect(container.querySelector('del')?.textContent).toBe('gone words');
    expect(container.querySelector('sup a')).not.toBeNull();
    expect(container.textContent).toContain('The footnote words.');
  });

  it('content never sets a style attribute', () => {
    const { container } = render(<MarkdownDisplay content={GFM_DOC} />);
    expect(container.querySelectorAll('[style]')).toHaveLength(0);
    expect(screen.getByRole('columnheader', { name: 'Left' })).toHaveClass('text-left');
    expect(screen.getByRole('columnheader', { name: 'Right' })).toHaveClass('text-right');
  });
});

describe('JSON, plain text and copy', () => {
  it('JSON keys and values with markup stay literal', () => {
    const { container } = render(<SmartContent content={JSON_PROBE} />);
    noMarkupFromContent(container);
    nothingLoads(container);
    const parsed = JSON.parse(JSON_PROBE) as Record<string, string>;
    for (const [key, value] of Object.entries(parsed)) {
      expect(screen.getByText(key)).toBeInTheDocument();
      expect(screen.getByText(`"${value}"`)).toBeInTheDocument();
    }
  });

  it('plain text with markup stays literal', () => {
    const { container } = render(<SmartContent content={TEXT_PROBE} />);
    noMarkupFromContent(container);
    expect(screen.getByText(TEXT_PROBE)).toBeInTheDocument();
  });

  it('the copy button copies the raw content', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<SmartContent content={SMART_PROBE_DOC} />);
    fireEvent.click(screen.getByRole('button', { name: 'Copy to clipboard' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(SMART_PROBE_DOC));
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
  });
});

describe('OutputDisplay', () => {
  it('content fields show image placeholders, not images', () => {
    const { container } = render(<OutputDisplay data={{ output: IMAGE_DOC, summary: DISPLAY_PROBE_DOC }} />);
    nothingLoads(container);
    noMarkupFromContent(container);
    const image = IMAGES[0];
    expect(screen.getAllByText(placeholderText(image.alt, image.host, originHost())).length).toBeGreaterThan(0);
  });
});
