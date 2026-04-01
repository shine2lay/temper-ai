import { useCallback, useEffect, useRef, useState } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { CopyButton } from '@/components/shared/CopyButton';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import { ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

interface StreamingPanelProps {
  agentId: string;
}

export function StreamingPanel({ agentId }: StreamingPanelProps) {
  const stream = useExecutionStore((s) => s.streamingContent.get(agentId));
  const containerRef = useRef<HTMLDivElement>(null);
  const [thinkingOpen, setThinkingOpen] = useState(false);
  const [isAtBottom, setIsAtBottom] = useState(true);

  const scrollToBottom = useCallback(() => {
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
    setIsAtBottom(atBottom);
  }, []);

  useEffect(() => {
    if (isAtBottom) scrollToBottom();
  }, [stream?.content, stream?.thinking, isAtBottom, scrollToBottom]);

  if (!stream) {
    return (
      <div className="rounded-md bg-temper-panel p-4 text-sm text-temper-text-muted">
        <p>Waiting for stream data...</p>
        <p className="mt-1 text-xs text-temper-text-dim">
          Streaming requires the workflow to run in the dashboard process.
          Workflows started via CLI (temper-ai run) update via DB polling and cannot stream.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {stream.thinking && (
        <Collapsible open={thinkingOpen} onOpenChange={setThinkingOpen}>
          <CollapsibleTrigger className="flex items-center gap-1.5 text-xs font-medium text-temper-text-muted hover:text-temper-text">
            <ChevronRight
              className={cn(
                'size-3.5 transition-transform',
                thinkingOpen && 'rotate-90',
              )}
            />
            Thinking
          </CollapsibleTrigger>
          <CollapsibleContent>
            <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-temper-panel p-3 text-xs italic text-temper-text-muted whitespace-pre-wrap">
              {stream.thinking}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      )}

      {stream.done ? (
        <div ref={containerRef} onScroll={handleScroll} className="relative max-h-80 overflow-auto">
          {stream.content && (
            <div className="absolute top-2 right-2 z-10">
              <CopyButton text={stream.content} />
            </div>
          )}
          <MarkdownDisplay content={stream.content} />
          <div className="mt-2 text-xs text-temper-completed">
            Stream complete
          </div>
        </div>
      ) : (
        <div ref={containerRef} onScroll={handleScroll} className="relative max-h-80 overflow-auto rounded-md bg-temper-panel p-3">
          {stream.content && (
            <div className="absolute top-2 right-2">
              <CopyButton text={stream.content} />
            </div>
          )}
          {stream.toolActivity && stream.toolActivity.length > 0 && (
            <div className="mb-2 flex flex-col gap-1">
              {stream.toolActivity.map((tool, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  {tool.status === 'running' ? (
                    <span className="w-1.5 h-1.5 rounded-full bg-temper-accent animate-pulse shrink-0" />
                  ) : tool.status === 'completed' ? (
                    <span className="w-1.5 h-1.5 rounded-full bg-temper-completed shrink-0" />
                  ) : (
                    <span className="w-1.5 h-1.5 rounded-full bg-temper-failed shrink-0" />
                  )}
                  <span
                    className={cn(
                      'font-mono',
                      tool.status === 'running' ? 'text-temper-accent' : 'text-temper-text-muted',
                    )}
                  >
                    {tool.toolName}
                  </span>
                  {tool.durationSeconds != null && (
                    <span className="text-temper-text-dim">
                      {tool.durationSeconds.toFixed(1)}s
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
          {/* React auto-escapes JSX expressions — stream.content is safe */}
          <pre className="text-sm text-temper-text whitespace-pre-wrap">
            {stream.content}
            <span className="animate-pulse-streaming text-temper-accent">|</span>
          </pre>
          {!isAtBottom && (
            <button
              onClick={() => {
                scrollToBottom();
                setIsAtBottom(true);
              }}
              className="sticky bottom-2 left-1/2 -translate-x-1/2 rounded-full bg-temper-accent/90 px-3 py-1 text-xs font-medium text-white shadow-md backdrop-blur-sm hover:bg-temper-accent"
            >
              Jump to bottom
            </button>
          )}
        </div>
      )}
    </div>
  );
}
