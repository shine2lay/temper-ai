import { useState } from 'react';
import { cn } from '@/lib/utils';
import { CopyButton } from './CopyButton';

interface JsonViewerProps {
  data: unknown;
  className?: string;
}

export function JsonViewer({ data, className }: JsonViewerProps) {
  if (data == null) {
    return <p className="text-xs text-temper-text-dim">No data</p>;
  }

  const jsonStr = JSON.stringify(data, null, 2);

  return (
    <div className={cn('relative rounded-md bg-temper-panel border border-temper-border', className)}>
      <div className="absolute top-1 right-1 z-10">
        <CopyButton text={jsonStr} />
      </div>
      <div className="p-3 max-h-80 overflow-auto text-xs font-mono">
        <JsonNode value={data} depth={0} />
      </div>
    </div>
  );
}

const AUTO_EXPAND_DEPTH = 2;

function JsonNode({ value, depth }: { value: unknown; depth: number }) {
  const [expanded, setExpanded] = useState(depth < AUTO_EXPAND_DEPTH);

  if (value === null) return <span className="text-temper-text-dim">null</span>;
  if (typeof value === 'boolean') return <span className="text-amber-400">{String(value)}</span>;
  if (typeof value === 'number') return <span className="text-emerald-400">{value}</span>;
  if (typeof value === 'string') return <span className="text-sky-400">&quot;{value}&quot;</span>;

  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-temper-text-muted">[]</span>;
    return (
      <CollapsibleNode
        expanded={expanded}
        onToggle={() => setExpanded(!expanded)}
        bracket={['[', ']']}
        count={value.length}
      >
        {value.map((item, i) => (
          <div key={i} className="pl-4">
            <JsonNode value={item} depth={depth + 1} />
            {i < value.length - 1 && <span className="text-temper-text-dim">,</span>}
          </div>
        ))}
      </CollapsibleNode>
    );
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-temper-text-muted">{'{}'}</span>;
    return (
      <CollapsibleNode
        expanded={expanded}
        onToggle={() => setExpanded(!expanded)}
        bracket={['{', '}']}
        count={entries.length}
      >
        {entries.map(([key, val], i) => (
          <div key={key} className="pl-4">
            <span className="text-purple-400">&quot;{key}&quot;</span>
            <span className="text-temper-text-dim">: </span>
            <JsonNode value={val} depth={depth + 1} />
            {i < entries.length - 1 && <span className="text-temper-text-dim">,</span>}
          </div>
        ))}
      </CollapsibleNode>
    );
  }

  return <span className="text-temper-text">{String(value)}</span>;
}

function CollapsibleNode({
  expanded,
  onToggle,
  bracket,
  count,
  children,
}: {
  expanded: boolean;
  onToggle: () => void;
  bracket: [string, string];
  count: number;
  children: React.ReactNode;
}) {
  return (
    <span>
      <button
        onClick={onToggle}
        className="text-temper-text-muted hover:text-temper-text mr-1 text-[10px]"
      >
        {expanded ? '\u25BC' : '\u25B6'}
      </button>
      <span className="text-temper-text">{bracket[0]}</span>
      {expanded ? (
        <>
          <div>{children}</div>
          <span className="text-temper-text">{bracket[1]}</span>
        </>
      ) : (
        <span>
          <span className="text-temper-text-dim"> {count} items </span>
          <span className="text-temper-text">{bracket[1]}</span>
        </span>
      )}
    </span>
  );
}
