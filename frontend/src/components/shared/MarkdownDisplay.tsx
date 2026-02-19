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
        'rounded-md bg-maf-panel p-4 text-sm text-maf-text',
        'border border-maf-border prose prose-invert prose-sm max-w-none',
        'prose-headings:text-maf-text prose-p:text-maf-text prose-li:text-maf-text',
        'prose-strong:text-maf-text prose-code:text-maf-accent prose-code:text-xs',
        'prose-pre:bg-maf-surface prose-pre:border prose-pre:border-maf-border',
        className,
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}
