import { useRef } from 'react';
import { Dialog } from 'radix-ui';
import { X } from 'lucide-react';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import type { TeamRole } from '@/types/team';

/**
 * A role's about page in a side sheet (board L1b). The about.md text is
 * untrusted: it goes through the app's safe markdown, never as HTML.
 * Holds focus while open; Esc and Close give focus back to the row's
 * About page button.
 */
export function RoleAboutSheet({ role, onClose }: { role: TeamRole | null; onClose: () => void }) {
  const opener = useRef<HTMLElement | null>(null);
  const about = (role?.about ?? '').trim();
  return (
    <Dialog.Root open={role !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60" />
        <Dialog.Content
          data-testid="role-about-sheet"
          aria-describedby={undefined}
          className="fixed inset-y-0 right-0 z-50 flex w-[560px] max-w-[calc(100vw-2rem)] flex-col border-l border-temper-border bg-temper-panel text-temper-text shadow-xl"
          onOpenAutoFocus={() => {
            opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
          }}
          onCloseAutoFocus={(event) => {
            const back = opener.current;
            opener.current = null;
            if (back?.isConnected) {
              event.preventDefault();
              back.focus();
            }
          }}
        >
          {role && (
            <>
              <div className="flex items-start gap-2 border-b border-temper-border px-6 py-4">
                <div className="min-w-0 flex-1">
                  <p className="m-0 text-xs font-semibold tracking-[0.06em] text-temper-text-muted uppercase">
                    About page
                  </p>
                  <Dialog.Title className="m-0 mt-1 text-sm font-semibold break-words text-temper-text">
                    {role.title || role.id} <span className="font-mono font-normal text-temper-text-muted">{role.id}</span>
                  </Dialog.Title>
                </div>
                <Dialog.Close
                  aria-label="Close"
                  className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md border border-transparent bg-transparent text-temper-text-muted hover:bg-temper-surface hover:text-temper-text"
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                </Dialog.Close>
              </div>
              <div className="min-h-0 flex-1 overflow-auto px-6 py-4">
                {about ? (
                  <MarkdownDisplay content={about} className="rounded-none border-0 bg-transparent p-0" />
                ) : (
                  <p className="m-0 text-sm text-temper-text-muted">This role has no about page.</p>
                )}
              </div>
              <p className="m-0 border-t border-temper-border px-6 py-3 text-xs text-temper-text-muted">
                Shown as markdown, never as HTML. From the role&apos;s about.md.
              </p>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
