/**
 * One renderer for every piece of content in the big view.
 *
 * Nothing is ever a raw dump: markdown renders as markdown, JSON as a tree
 * you can fold, code as code, plain text keeps its line breaks. Everything
 * is given a height and scrolls inside its own box, so one long answer can
 * never push the rest of the picture off the screen.
 *
 * `SmartContent` already tells JSON, markdown, code and text apart, so the
 * `auto` kind hands straight to it; the other kinds are the cases where the
 * shape already knows what it has and should not be guessed at.
 */
import { memo } from 'react';
import { cn } from '@/lib/utils';
import { SmartContent } from '@/components/shared/SmartContent';
import { JsonViewer } from '@/components/shared/JsonViewer';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import { CopyButton } from '@/components/shared/CopyButton';
import { ThinkingContent } from '@/components/shared/ThinkingContent';
import { StreamingPanel } from '@/components/shared/StreamingPanel';
import { ScriptLogView } from '@/components/scriptlog/ScriptLogView';
import { CostBreakdownSection } from '@/components/shared/CostBreakdownSection';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { hasThinkingTags } from '@/lib/streamSegments';
import { formatTimestamp } from '@/lib/utils';
import type { CollaborationEvent } from '@/types';
import type { ContentValue, ShapeLink } from './types';

/** Every box of content gets a height and scrolls; none of them grow. */
export const CONTENT_HEIGHT = 420;

interface ContentProps {
  value: ContentValue;
  maxHeight?: number;
  className?: string;
}

export const Content = memo(function Content({ value, maxHeight = CONTENT_HEIGHT, className }: ContentProps) {
  switch (value.kind) {
    case 'empty':
      return (
        <p data-testid="bv-empty" className={cn('px-1 py-2 text-xs text-temper-text-dim', className)}>
          {value.note}
        </p>
      );

    case 'auto':
      return (
        <div data-testid="bv-auto" className={className}>
          {hasThinkingTags(value.text) ? (
            <div className="overflow-auto" style={{ maxHeight }}>
              <ThinkingContent
                content={value.text}
                renderContent={(part, key) => <SmartContent key={key} content={part} maxHeight={maxHeight} />}
              />
            </div>
          ) : (
            <SmartContent content={value.text} maxHeight={maxHeight} />
          )}
        </div>
      );

    case 'markdown':
      return (
        <div data-testid="bv-markdown" className={cn('relative', className)}>
          <div className="absolute right-1 top-1 z-10">
            <CopyButton text={value.text} />
          </div>
          {hasThinkingTags(value.text) ? (
            <div className="overflow-auto" style={{ maxHeight }}>
              <ThinkingContent
                content={value.text}
                renderContent={(part, key) => <MarkdownDisplay key={key} content={part} />}
              />
            </div>
          ) : (
            <MarkdownDisplay content={value.text} maxHeight={maxHeight} />
          )}
        </div>
      );

    case 'code':
      return (
        <div data-testid="bv-code" className={className}>
          <SmartContent content={asFencedCode(value.text)} maxHeight={maxHeight} />
        </div>
      );

    case 'json':
      return (
        <div data-testid="bv-json" className={className}>
          <JsonViewer data={value.data} maxHeight={maxHeight} />
        </div>
      );

    case 'thinking':
      return (
        <div
          data-testid="bv-thinking"
          className={cn(
            'overflow-auto rounded-md border border-violet-500/30 bg-violet-500/10 p-2',
            className,
          )}
          style={{ maxHeight }}
        >
          <span className="mb-1 block text-[9px] font-medium uppercase tracking-wider text-violet-400">
            thinking
          </span>
          <MarkdownDisplay
            content={value.text}
            className="border-0 bg-transparent p-0 text-violet-900 dark:text-violet-300/80"
          />
        </div>
      );

    case 'stream':
      return (
        <div data-testid="bv-stream" className={cn('overflow-auto', className)} style={{ maxHeight }}>
          <StreamingPanel agentId={value.agentId} />
        </div>
      );

    case 'scriptLog':
      // Its own height and scrolling: it follows new output, and reads older output on demand.
      return (
        <div
          data-testid="bv-script-log"
          className={cn('overflow-hidden rounded-md border border-temper-border', className)}
        >
          <ScriptLogView attemptId={value.attemptId} height={Math.max(maxHeight, 480)} />
        </div>
      );

    case 'messages':
      return <Conversation data-testid="bv-messages" messages={value.messages} maxHeight={maxHeight} className={className} />;

    case 'widget':
      return <Widget value={value} maxHeight={maxHeight} className={className} />;

    case 'group':
      return (
        <div data-testid="bv-group" className={cn('flex flex-col gap-3', className)}>
          {value.parts.map((part, i) => (
            <div key={part.label ?? i} className="min-w-0">
              {part.label && (
                <span className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-temper-text-muted">
                  {part.label}
                </span>
              )}
              <Content value={part.value} maxHeight={maxHeight} />
            </div>
          ))}
        </div>
      );
  }
});

/** Wrap bare source in a fence so SmartContent renders it as code, not prose. */
function asFencedCode(code: string): string {
  return code.trim().startsWith('```') ? code : `\`\`\`\n${code}\n\`\`\``;
}

/* ---------- the conversation sent to a model ---------- */

function Conversation({
  messages,
  maxHeight,
  className,
}: {
  messages: unknown;
  maxHeight: number;
  className?: string;
} & { 'data-testid'?: string }) {
  if (!Array.isArray(messages)) {
    return <Content value={{ kind: 'json', data: messages }} maxHeight={maxHeight} className={className} />;
  }

  return (
    <div
      data-testid="bv-messages"
      className={cn('flex flex-col gap-2 overflow-auto pr-1', className)}
      style={{ maxHeight }}
    >
      {messages.map((raw, i) => {
        const msg = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>;
        const role = msg.role;
        const asked = msg.tool_calls as Record<string, unknown>[] | undefined;
        const body = msg.content;
        const bodyText =
          body == null
            ? ''
            : typeof body === 'string'
              ? body
              : JSON.stringify(body, null, 2) ?? '';
        return (
          <div key={i} className="overflow-hidden rounded-md border border-temper-border/40">
            <div className="flex items-center gap-2 bg-temper-accent/10 px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-temper-text">
              {role != null ? String(role) : `message ${i + 1}`}
              {asked && asked.length > 0 && (
                <span className="font-normal normal-case text-amber-400">
                  {asked.length} tool call{asked.length !== 1 ? 's' : ''}
                </span>
              )}
            </div>
            {bodyText ? (
              <Content value={{ kind: 'auto', text: bodyText }} maxHeight={Math.round(maxHeight * 0.75)} />
            ) : !asked ? (
              <p className="px-2 py-1 text-[10px] text-temper-text-dim">empty</p>
            ) : null}
            {asked && asked.length > 0 && (
              <div className="border-t border-temper-border/20 bg-amber-500/5 px-2 py-1">
                {asked.map((call, j) => {
                  const fn = call.function as Record<string, unknown> | undefined;
                  const name = fn?.name ?? call.name ?? 'unknown';
                  return (
                    <div key={j} className="truncate font-mono text-[10px] text-amber-400">
                      {String(name)}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ---------- ready-made pieces ---------- */

function Widget({
  value,
  maxHeight,
  className,
}: {
  value: Extract<ContentValue, { kind: 'widget' }>;
  maxHeight: number;
  className?: string;
}) {
  const box = cn('overflow-auto', className);

  switch (value.name) {
    case 'cost-breakdown':
      return (
        <div data-testid="bv-widget-cost" className={box} style={{ maxHeight }}>
          <CostBreakdownSection />
        </div>
      );

    case 'tool-names': {
      const names = (value.data as string[]) ?? [];
      return (
        <div data-testid="bv-widget-tools" className={cn('flex flex-wrap gap-1', box)} style={{ maxHeight }}>
          {names.map((name) => (
            <span
              key={name}
              className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[10px] text-amber-500"
            >
              {name}
            </span>
          ))}
        </div>
      );
    }

    case 'declared-io': {
      const io = (value.data ?? {}) as {
        inputs?: Record<string, unknown>;
        outputs?: Record<string, unknown>;
      };
      return (
        <div data-testid="bv-widget-io" className={cn('flex flex-col gap-3', box)} style={{ maxHeight }}>
          {(['inputs', 'outputs'] as const).map((side) =>
            io[side] ? (
              <div key={side}>
                <span className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-temper-text-muted">
                  {side}
                </span>
                <table className="w-full overflow-hidden rounded-md border border-temper-border bg-temper-panel text-xs">
                  <tbody>
                    {Object.entries(io[side]!).map(([name, decl]) => {
                      const d = (decl ?? {}) as Record<string, unknown>;
                      return (
                        <tr key={name} className="border-b border-temper-border/30 last:border-b-0">
                          <td className="px-3 py-1 font-medium text-temper-text">{name}</td>
                          <td className="px-3 py-1 font-mono text-temper-text-muted">{String(d.type ?? '')}</td>
                          <td className="px-3 py-1 text-temper-text-dim">
                            {side === 'inputs'
                              ? d.required
                                ? 'required'
                                : 'optional'
                              : String(d.description ?? '')}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null,
          )}
        </div>
      );
    }

    case 'collaboration': {
      const events = (value.data as CollaborationEvent[]) ?? [];
      return (
        <div data-testid="bv-widget-collab" className={cn('flex flex-col gap-2', box)} style={{ maxHeight }}>
          {events.map((evt, i) => (
            <div key={i} className="rounded-md bg-temper-panel p-2 text-xs text-temper-text">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-temper-accent">{evt.event_type}</span>
                {evt.from_agent && <span className="text-temper-text-muted">from {evt.from_agent}</span>}
                {evt.to_agent && <span className="text-temper-text-muted">to {evt.to_agent}</span>}
                {evt.timestamp && (
                  <span className="text-[10px] text-temper-text-dim">{formatTimestamp(evt.timestamp)}</span>
                )}
              </div>
              {evt.data && Object.keys(evt.data).length > 0 && (
                <JsonViewer data={evt.data} className="mt-1" maxHeight={180} />
              )}
            </div>
          ))}
        </div>
      );
    }

    case 'links': {
      const links = (value.data as ShapeLink[]) ?? [];
      return (
        <div data-testid="bv-widget-links" className={cn('flex flex-col gap-1', box)} style={{ maxHeight }}>
          {links.map((link) => (
            <button
              key={link.id}
              type="button"
              onClick={link.open}
              className="flex items-center justify-between gap-2 rounded-md bg-temper-panel px-2 py-1 text-left text-xs transition-colors hover:bg-temper-surface"
            >
              <span className="min-w-0 truncate text-temper-text">{link.label}</span>
              <span className="flex shrink-0 items-center gap-2 text-temper-text-dim">
                {link.meta && <span className="text-[10px]">{link.meta}</span>}
                {link.status && <StatusBadge status={link.status} />}
              </span>
            </button>
          ))}
        </div>
      );
    }
  }
}
