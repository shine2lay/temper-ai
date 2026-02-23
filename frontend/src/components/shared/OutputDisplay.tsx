import { useState, useMemo } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { MarkdownDisplay } from './MarkdownDisplay';
import { CollapsibleSection } from './Collapsible';
import { JsonViewer } from './JsonViewer';
import { cn } from '@/lib/utils';

interface OutputDisplayProps {
  data: Record<string, unknown>;
  className?: string;
}

const MIN_CONTENT_LENGTH = 50;
const CONTENT_KEYS = ['output', 'analysis', 'result', 'summary', 'answer', 'response', 'recommendation'];

function isContentString(key: string, value: unknown): boolean {
  if (typeof value !== 'string' || value.trim().length === 0) return false;
  if (CONTENT_KEYS.includes(key)) return true;
  return value.length >= MIN_CONTENT_LENGTH;
}

function formatKeyLabel(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

interface SeparatedData {
  contentFields: [string, string][];
  structuredFields: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
}

function separateData(data: Record<string, unknown>): SeparatedData {
  const contentFields: [string, string][] = [];
  const metadata: Record<string, unknown> = {};
  let structuredFields: Record<string, unknown> | null = null;

  for (const [key, value] of Object.entries(data)) {
    if (key === 'structured' && value != null && typeof value === 'object' && Object.keys(value as object).length > 0) {
      structuredFields = value as Record<string, unknown>;
    } else if (isContentString(key, value)) {
      contentFields.push([key, value as string]);
    } else {
      metadata[key] = value;
    }
  }

  // Sort: prioritize 'output' key first, then other CONTENT_KEYS, then by length
  contentFields.sort((a, b) => {
    const aIdx = CONTENT_KEYS.indexOf(a[0]);
    const bIdx = CONTENT_KEYS.indexOf(b[0]);
    if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx;
    if (aIdx !== -1) return -1;
    if (bIdx !== -1) return 1;
    return b[1].length - a[1].length;
  });

  return { contentFields, structuredFields, metadata };
}

export function OutputDisplay({ data, className }: OutputDisplayProps) {
  const { contentFields, structuredFields, metadata } = useMemo(() => separateData(data), [data]);
  const hasMetadata = Object.keys(metadata).length > 0;
  const [expanded, setExpanded] = useState(false);

  if (contentFields.length === 0 && !structuredFields && !hasMetadata) {
    return <p className="text-xs text-temper-text-dim">No data</p>;
  }

  return (
    <div className={cn('relative flex flex-col gap-3', className)}>
      {/* Content area — capped when collapsed, full height when expanded */}
      <div className={cn('overflow-hidden', !expanded && 'max-h-64')}>
        <div className="flex flex-col gap-3">
          {/* Text content sections — rendered as markdown */}
          {contentFields.map(([key, text]) => (
            <div key={key}>
              {contentFields.length > 1 && (
                <span className="text-[10px] font-medium text-temper-text-muted uppercase tracking-wide mb-1 block">
                  {formatKeyLabel(key)}
                </span>
              )}
              <MarkdownDisplay content={text} />
            </div>
          ))}

          {/* Structured fields — clean key-value table */}
          {structuredFields && (
            <div>
              <span className="text-[10px] font-medium text-temper-text-muted uppercase tracking-wide mb-1 block">
                Structured Data
              </span>
              <div className="rounded-md border border-temper-border bg-temper-panel overflow-hidden">
                <table className="w-full text-xs">
                  <tbody>
                    {Object.entries(structuredFields).map(([key, value]) => (
                      <tr key={key} className="border-b border-temper-border/30 last:border-b-0">
                        <td className="px-3 py-1.5 text-temper-text-muted font-medium whitespace-nowrap align-top w-1/4">
                          {formatKeyLabel(key)}
                        </td>
                        <td className="px-3 py-1.5 text-temper-text font-mono break-all">
                          {typeof value === 'object' && value !== null
                            ? JSON.stringify(value)
                            : String(value ?? '')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Metadata — collapsed raw JSON */}
          {hasMetadata && (
            <CollapsibleSection title="Raw Data">
              <JsonViewer data={metadata} />
            </CollapsibleSection>
          )}
        </div>
      </div>

      {/* Fade + expand/collapse toggle */}
      <div className={cn('flex items-center', !expanded && 'relative')}>
        {!expanded && (
          <div className="absolute -top-8 left-0 right-0 h-8 bg-gradient-to-t from-temper-bg to-transparent pointer-events-none" />
        )}
        <button
          onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
          className="inline-flex items-center gap-1 text-[10px] text-temper-text-muted hover:text-temper-text transition-colors"
        >
          {expanded ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
          {expanded ? 'Show less' : 'Show more'}
        </button>
      </div>
    </div>
  );
}
