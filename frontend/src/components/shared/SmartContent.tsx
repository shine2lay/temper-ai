/**
 * SmartContent — auto-detects content type and renders accordingly.
 * JSON → interactive collapsible tree with syntax coloring
 * Markdown (headers, lists, code blocks) → rendered markdown
 * Plain text → formatted with line breaks and basic structure
 *
 * Used in agent cards, detail panels, and anywhere long text needs
 * to be readable instead of a raw blob.
 */
import { useState, useMemo } from 'react';
import { cn } from '@/lib/utils';
import { CopyButton } from './CopyButton';

interface SmartContentProps {
  content: string;
  /** Max height before scroll. Default 200px. */
  maxHeight?: number;
  /** Compact mode — smaller text, tighter spacing. */
  compact?: boolean;
  className?: string;
}

type ContentType = 'json' | 'markdown' | 'code' | 'text';

function detectType(content: string): ContentType {
  const trimmed = content.trim();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try { JSON.parse(trimmed); return 'json'; } catch { /* not valid JSON */ }
  }
  if (trimmed.startsWith('```')) return 'code';
  // Markdown signals: headers, bullet lists, numbered lists, bold, links
  if (/^#{1,6}\s/m.test(trimmed) || /^\s*[-*]\s/m.test(trimmed) || /\*\*\w/.test(trimmed) || /\[.*\]\(.*\)/.test(trimmed)) {
    return 'markdown';
  }
  if (/^(import |from |def |function |class |const |let |var |export )/.test(trimmed)) return 'code';
  return 'text';
}

export function SmartContent({ content, maxHeight = 200, compact = false, className }: SmartContentProps) {
  const type = useMemo(() => detectType(content), [content]);
  const textSize = compact ? 'text-[10px]' : 'text-xs';

  return (
    <div className={cn('rounded border border-temper-border/30 overflow-hidden', className)}>
      {/* Type indicator + copy */}
      <div className="flex items-center justify-between px-2 py-0.5 bg-temper-surface/30 border-b border-temper-border/20">
        <span className={cn('font-mono uppercase tracking-wider text-temper-text-dim', compact ? 'text-[8px]' : 'text-[9px]')}>
          {type}
        </span>
        <CopyButton text={content} />
      </div>
      {/* Content */}
      <div className={cn('overflow-auto', textSize)} style={{ maxHeight }}>
        {type === 'json' && <JsonContent content={content} compact={compact} />}
        {type === 'markdown' && <MarkdownContent content={content} compact={compact} />}
        {type === 'code' && <CodeContent content={content} />}
        {type === 'text' && <TextContent content={content} />}
      </div>
    </div>
  );
}

/* --- JSON --- */

function JsonContent({ content, compact }: { content: string; compact?: boolean }) {
  const [collapsed, setCollapsed] = useState(new Set<string>());
  const parsed = useMemo(() => { try { return JSON.parse(content.trim()); } catch { return null; } }, [content]);

  if (!parsed) return <pre className="p-2 font-mono text-temper-text-dim whitespace-pre-wrap">{content}</pre>;

  return (
    <div className={cn('p-2 font-mono', compact ? 'text-[10px]' : 'text-xs')}>
      <JsonNode value={parsed} path="" depth={0} collapsed={collapsed} toggle={(p) => {
        setCollapsed(prev => { const next = new Set(prev); next.has(p) ? next.delete(p) : next.add(p); return next; });
      }} />
    </div>
  );
}

function JsonNode({ value, path, depth, collapsed, toggle }: {
  value: unknown; path: string; depth: number;
  collapsed: Set<string>; toggle: (path: string) => void;
}) {
  if (value === null) return <span className="text-temper-text-dim">null</span>;
  if (typeof value === 'boolean') return <span className="text-amber-400">{String(value)}</span>;
  if (typeof value === 'number') return <span className="text-emerald-400">{value}</span>;
  if (typeof value === 'string') {
    // Long strings get their own line with wrapping
    if (value.length > 80) {
      return <span className="text-sky-400 break-words whitespace-pre-wrap">&quot;{value}&quot;</span>;
    }
    return <span className="text-sky-400">&quot;{value}&quot;</span>;
  }

  const isArray = Array.isArray(value);
  const entries = isArray ? (value as unknown[]).map((v, i) => [String(i), v] as const) : Object.entries(value as Record<string, unknown>);
  const isCollapsed = depth >= 2 ? collapsed.has(path) === false && depth >= 3 : collapsed.has(path);
  const bracket = isArray ? ['[', ']'] : ['{', '}'];

  if (entries.length === 0) return <span className="text-temper-text-dim">{bracket.join('')}</span>;

  return (
    <span>
      <button onClick={() => toggle(path)} className="text-temper-text-dim hover:text-temper-text text-[9px] mr-0.5 w-3 inline-block text-center">
        {isCollapsed ? '\u25B6' : '\u25BC'}
      </button>
      <span className="text-temper-text">{bracket[0]}</span>
      {isCollapsed ? (
        <span>
          <span className="text-temper-text-dim"> {entries.length} {isArray ? 'items' : 'keys'} </span>
          <span className="text-temper-text">{bracket[1]}</span>
        </span>
      ) : (
        <>
          {entries.map(([key, val], i) => (
            <div key={key} className="pl-4">
              {!isArray && <><span className="text-violet-400">{key}</span><span className="text-temper-text-dim">: </span></>}
              <JsonNode value={val} path={`${path}.${key}`} depth={depth + 1} collapsed={collapsed} toggle={toggle} />
              {i < entries.length - 1 && <span className="text-temper-text-dim">,</span>}
            </div>
          ))}
          <span className="text-temper-text">{bracket[1]}</span>
        </>
      )}
    </span>
  );
}

/* --- Markdown --- */

function MarkdownContent({ content, compact }: { content: string; compact?: boolean }) {
  // Lightweight markdown rendering without heavy dependencies
  // Handles: headers, bold, italic, code blocks, inline code, lists, links
  const html = useMemo(() => renderMarkdown(content), [content]);
  return (
    <div
      className={cn(
        'p-2 leading-relaxed',
        compact ? 'text-[10px]' : 'text-xs',
        'text-temper-text',
        '[&_h1]:text-sm [&_h1]:font-bold [&_h1]:text-temper-text [&_h1]:mt-3 [&_h1]:mb-1',
        '[&_h2]:text-xs [&_h2]:font-bold [&_h2]:text-temper-text [&_h2]:mt-2 [&_h2]:mb-1',
        '[&_h3]:text-xs [&_h3]:font-semibold [&_h3]:text-temper-text [&_h3]:mt-2 [&_h3]:mb-0.5',
        '[&_p]:mb-1.5 [&_p]:text-temper-text',
        '[&_ul]:pl-4 [&_ul]:mb-1.5 [&_ul]:list-disc',
        '[&_ol]:pl-4 [&_ol]:mb-1.5 [&_ol]:list-decimal',
        '[&_li]:mb-0.5 [&_li]:text-temper-text',
        '[&_code]:bg-temper-surface [&_code]:px-1 [&_code]:py-px [&_code]:rounded [&_code]:text-temper-accent [&_code]:font-mono',
        '[&_pre]:bg-temper-surface [&_pre]:p-2 [&_pre]:rounded [&_pre]:border [&_pre]:border-temper-border/30 [&_pre]:overflow-x-auto [&_pre]:mb-2',
        '[&_pre_code]:bg-transparent [&_pre_code]:p-0',
        '[&_strong]:font-semibold [&_strong]:text-temper-text',
        '[&_a]:text-temper-accent [&_a]:underline',
        '[&_blockquote]:border-l-2 [&_blockquote]:border-temper-accent/30 [&_blockquote]:pl-3 [&_blockquote]:text-temper-text-dim [&_blockquote]:italic',
      )}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

/** Lightweight markdown to HTML — handles common patterns without a full parser. */
function renderMarkdown(md: string): string {
  let html = md
    // Escape HTML
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    // Code blocks (``` ... ```)
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
    // Headers
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    // Bold + italic
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // Unordered lists
    .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
    // Numbered lists
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>')
    // Blockquotes
    .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
    // Paragraphs (double newline)
    .replace(/\n\n/g, '</p><p>')
    // Line breaks
    .replace(/\n/g, '<br/>');

  // Wrap consecutive <li> in <ul>
  html = html.replace(/(<li>.*?<\/li>(?:<br\/>)?)+/g, (match) => {
    return '<ul>' + match.replace(/<br\/>/g, '') + '</ul>';
  });

  return '<p>' + html + '</p>';
}

/* --- Code --- */

function CodeContent({ content }: { content: string }) {
  // Strip leading/trailing ``` markers
  let code = content.trim();
  if (code.startsWith('```')) {
    code = code.replace(/^```\w*\n?/, '').replace(/```$/, '');
  }

  return (
    <pre className="p-2 font-mono text-[11px] text-temper-text leading-relaxed whitespace-pre-wrap break-words">
      {code.split('\n').map((line, i) => (
        <div key={i} className="flex">
          <span className="w-8 text-right pr-2 text-temper-text-dim select-none shrink-0">{i + 1}</span>
          <span className="flex-1">{highlightCodeLine(line)}</span>
        </div>
      ))}
    </pre>
  );
}

/** Basic syntax highlighting for common patterns. */
function highlightCodeLine(line: string): React.ReactNode {
  // Keywords
  const highlighted = line
    .replace(/\b(import|from|export|default|const|let|var|function|return|class|if|else|for|while|async|await|try|catch|def|self|None|True|False)\b/g,
      '<kw>$1</kw>')
    .replace(/(["'`])([^"'`]*)\1/g, '<str>$1$2$1</str>')
    .replace(/\/\/.*/g, '<cmt>$&</cmt>')
    .replace(/#.*/g, '<cmt>$&</cmt>');

  return (
    <span dangerouslySetInnerHTML={{ __html: highlighted
      .replace(/<kw>/g, '<span class="text-violet-400 font-medium">')
      .replace(/<\/kw>/g, '</span>')
      .replace(/<str>/g, '<span class="text-emerald-400">')
      .replace(/<\/str>/g, '</span>')
      .replace(/<cmt>/g, '<span class="text-temper-text-dim italic">')
      .replace(/<\/cmt>/g, '</span>')
    }} />
  );
}
