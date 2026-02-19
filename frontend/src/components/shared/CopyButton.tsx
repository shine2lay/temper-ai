import { useState } from 'react';
import { Copy, Check } from 'lucide-react';

const COPIED_RESET_MS = 2000;

interface CopyButtonProps {
  text: string;
  className?: string;
}

export function CopyButton({ text, className }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), COPIED_RESET_MS);
  }

  return (
    <button
      onClick={handleCopy}
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-temper-text-muted hover:text-temper-text transition-colors ${className ?? ''}`}
      aria-label={copied ? 'Copied' : 'Copy to clipboard'}
    >
      {copied ? (
        <>
          <Check className="size-3" />
          <span>Copied!</span>
        </>
      ) : (
        <Copy className="size-3" />
      )}
    </button>
  );
}
