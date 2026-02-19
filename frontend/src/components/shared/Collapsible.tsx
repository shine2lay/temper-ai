import { useState } from 'react';
import {
  Collapsible as CollapsibleRoot,
  CollapsibleTrigger,
  CollapsibleContent,
} from '@/components/ui/collapsible';
import { cn } from '@/lib/utils';

interface CollapsibleSectionProps {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}

export function CollapsibleSection({ title, children, defaultOpen = false }: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <CollapsibleRoot open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium text-maf-text hover:bg-maf-surface rounded-md transition-colors">
        <span
          className={cn(
            'inline-block transition-transform text-maf-text-muted text-xs',
            open && 'rotate-90',
          )}
        >
          &#9654;
        </span>
        {title}
      </CollapsibleTrigger>
      <CollapsibleContent className="px-3 pb-2">
        {children}
      </CollapsibleContent>
    </CollapsibleRoot>
  );
}
