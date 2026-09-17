import type { ToolCall } from '@/types';

/** "MCP · browser" for a call that went over MCP; "via claude" when a
 *  provider ran the tool itself. Nothing for a temper-run builtin, which
 *  is the historical default and needs no explanation. */
export function ToolOriginBadge({ tool, className = '' }: { tool: Pick<ToolCall, 'transport' | 'server' | 'executed_by'>; className?: string }) {
  const parts: { text: string; title: string; cls: string }[] = [];
  if (tool.transport === 'mcp') {
    parts.push({
      text: tool.server ? `MCP · ${tool.server}` : 'MCP',
      title: tool.server ? `Called over MCP on server "${tool.server}"` : 'Called over MCP',
      cls: 'bg-violet-500/15 text-violet-800 dark:text-violet-300 border-violet-500/40',
    });
  }
  if (tool.executed_by && tool.executed_by !== 'temper') {
    parts.push({
      text: `via ${tool.executed_by}`,
      title: `Executed inside the ${tool.executed_by} provider, not by temper`,
      cls: 'bg-temper-surface text-temper-text-muted border-temper-border',
    });
  }
  if (parts.length === 0) return null;
  return (
    <span className={`inline-flex items-center gap-1 ${className}`}>
      {parts.map((p) => (
        <span
          key={p.text}
          title={p.title}
          className={`text-[10px] px-1.5 py-px rounded border font-medium whitespace-nowrap ${p.cls}`}
        >
          {p.text}
        </span>
      ))}
    </span>
  );
}
