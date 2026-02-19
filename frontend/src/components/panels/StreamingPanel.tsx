import { useEffect, useRef, useState } from 'react';
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
  const bottomRef = useRef<HTMLDivElement>(null);
  const [thinkingOpen, setThinkingOpen] = useState(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [stream?.content, stream?.thinking]);

  if (!stream) {
    return (
      <div className="rounded-md bg-maf-panel p-4 text-sm text-maf-text-muted">
        <p>Waiting for stream data...</p>
        <p className="mt-1 text-xs text-maf-text-dim">
          Streaming requires the workflow to run in the dashboard process.
          Workflows started via CLI (maf run) update via DB polling and cannot stream.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {stream.thinking && (
        <Collapsible open={thinkingOpen} onOpenChange={setThinkingOpen}>
          <CollapsibleTrigger className="flex items-center gap-1.5 text-xs font-medium text-maf-text-muted hover:text-maf-text">
            <ChevronRight
              className={cn(
                'size-3.5 transition-transform',
                thinkingOpen && 'rotate-90',
              )}
            />
            Thinking
          </CollapsibleTrigger>
          <CollapsibleContent>
            <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-maf-panel p-3 text-xs italic text-maf-text-muted whitespace-pre-wrap">
              {stream.thinking}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      )}

      {stream.done ? (
        <div className="relative">
          {stream.content && (
            <div className="absolute top-2 right-2 z-10">
              <CopyButton text={stream.content} />
            </div>
          )}
          <MarkdownDisplay content={stream.content} className="max-h-80 overflow-auto" />
          <div className="mt-2 text-xs text-maf-completed">
            Stream complete
          </div>
          <div ref={bottomRef} />
        </div>
      ) : (
        <div className="relative max-h-80 overflow-auto rounded-md bg-maf-panel p-3">
          {stream.content && (
            <div className="absolute top-2 right-2">
              <CopyButton text={stream.content} />
            </div>
          )}
          {/* React auto-escapes JSX expressions — stream.content is safe */}
          <pre className="text-sm text-maf-text whitespace-pre-wrap">
            {stream.content}
            <span className="animate-pulse-streaming text-maf-accent">|</span>
          </pre>
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}
