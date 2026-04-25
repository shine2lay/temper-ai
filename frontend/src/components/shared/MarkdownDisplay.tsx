import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';

interface MarkdownDisplayProps {
  content: string;
  className?: string;
}

export function MarkdownDisplay({ content, className }: MarkdownDisplayProps) {
  return (
    <div
      className={cn(
        'rounded-md bg-temper-panel p-4 text-sm text-temper-text',
        'border border-temper-border prose dark:prose-invert prose-sm max-w-none',
        'prose-headings:text-temper-text prose-p:text-temper-text prose-li:text-temper-text',
        'prose-strong:text-temper-text prose-code:text-temper-accent prose-code:text-xs',
        'prose-pre:bg-temper-surface prose-pre:border prose-pre:border-temper-border',
        className,
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}
