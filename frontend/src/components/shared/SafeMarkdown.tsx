/**
 * The one place markdown from content is rendered.
 *
 * Agent output is shown as text, never as markup, and showing it never makes
 * the browser fetch anything:
 *
 * - react-markdown builds React elements, never an HTML string. `skipHtml`
 *   stays off, so raw HTML in content becomes literal text, and there are no
 *   rehype plugins at all (the lint gate keeps it so).
 * - Only text-structure elements are allowed (ALLOWED_ELEMENTS); none of them
 *   loads anything.
 * - Links pass the one navigation policy (safeUrl): http/https without a user
 *   name, pages under /app/, and fragments. Anything else is plain text.
 *   External links get `rel="noopener noreferrer"` and no referrer.
 * - Images never become images: "Image: <alt> (<host>)", a deliberate link
 *   (new tab, no referrer) when the address passes the policy.
 *
 * This is the only file allowed to import react-markdown (eslint.config.js).
 */
import type { ReactNode } from 'react';
import ReactMarkdown, { type Components, type ExtraProps } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { safeUrl } from '@/lib/safeUrl';
import {
  ALLOWED_ELEMENTS,
  IMAGE_PLACEHOLDER_PROP,
  remarkInertImages,
  remarkSoftBreaks,
} from '@/lib/safeMarkdownPolicy';

interface SafeMarkdownProps {
  content: string;
  /** GitHub extras: tables, task lists, strikethrough, footnotes, autolinks. */
  gfm?: boolean;
  /** A single newline inside a paragraph is a line break. */
  softBreaks?: boolean;
}

type AnchorProps = React.JSX.IntrinsicElements['a'] & ExtraProps;
type CellProps = React.JSX.IntrinsicElements['td'] & ExtraProps;
type InputProps = React.JSX.IntrinsicElements['input'] & ExtraProps;

function SafeLink({ node, href, title, id, className, children, ...rest }: AnchorProps) {
  const target = safeUrl(href);
  if (!target) return <span className={className}>{children}</span>;

  const attrs = rest as Record<string, unknown>;
  const pass = {
    title,
    id,
    className,
    'aria-describedby': attrs['aria-describedby'] as string | undefined,
    'aria-label': attrs['aria-label'] as string | undefined,
    'data-footnote-ref': attrs['data-footnote-ref'] as string | undefined,
    'data-footnote-backref': attrs['data-footnote-backref'] as string | undefined,
  };

  if (node?.properties?.[IMAGE_PLACEHOLDER_PROP] === 'true') {
    return (
      <a {...pass} href={target.href} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">
        {children}
      </a>
    );
  }
  if (target.kind === 'external') {
    return (
      <a {...pass} href={target.href} rel="noopener noreferrer" referrerPolicy="no-referrer">
        {children}
      </a>
    );
  }
  return (
    <a {...pass} href={target.href}>
      {children}
    </a>
  );
}

const ALIGN_CLASS: Record<string, string> = { left: 'text-left', center: 'text-center', right: 'text-right' };

/** GFM column alignment as a class: content never sets a style attribute. */
function alignClass(style: React.CSSProperties | undefined): string | undefined {
  const align = style?.textAlign;
  return typeof align === 'string' ? ALIGN_CLASS[align] : undefined;
}

function Th({ style, children }: CellProps) {
  return <th className={alignClass(style)}>{children}</th>;
}

function Td({ style, children }: CellProps) {
  return <td className={alignClass(style)}>{children}</td>;
}

/** A GFM task item's box: always a disabled checkbox, never another kind of input. */
function TaskBox({ checked }: InputProps) {
  return <input type="checkbox" checked={Boolean(checked)} disabled readOnly />;
}

const COMPONENTS: Components = { a: SafeLink, th: Th, td: Td, input: TaskBox };

const ALLOWED = [...ALLOWED_ELEMENTS];

function urlTransform(url: string): string {
  return safeUrl(url)?.href ?? '';
}

const PLUGINS = {
  gfm: [remarkGfm, remarkInertImages],
  plain: [remarkInertImages],
  plainBreaks: [remarkSoftBreaks, remarkInertImages],
};

export function SafeMarkdown({ content, gfm = false, softBreaks = false }: SafeMarkdownProps): ReactNode {
  const remarkPlugins = gfm ? PLUGINS.gfm : softBreaks ? PLUGINS.plainBreaks : PLUGINS.plain;
  return (
    <ReactMarkdown
      remarkPlugins={remarkPlugins}
      skipHtml={false}
      allowedElements={ALLOWED}
      unwrapDisallowed
      urlTransform={urlTransform}
      components={COMPONENTS}
    >
      {content}
    </ReactMarkdown>
  );
}
