import { useRef, type ReactNode, type RefObject } from 'react';
import { AlertDialog as Dialog } from 'radix-ui';
import { Square, X } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * The Team page's confirm dialog (Design's O1 and O1c boards, the run
 * page's GateModal look): a red stop icon and the title, the body, and a
 * footer with a hint on the left and the buttons on the right.
 *
 * It holds focus while open, starts on `initialFocus` (else the first
 * button Radix picks), closes on Esc and gives focus back to the button
 * that opened it. When that button has gone meanwhile (Stop run, once the
 * run has ended), focus goes to `focusWhenGone` instead of the page's
 * body. `busy` keeps it open while a request is on its way.
 */
export function TeamDialog({
  open,
  onOpenChange,
  title,
  subtitle,
  children,
  hint,
  buttons,
  initialFocus,
  focusWhenGone,
  busy = false,
  testId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  hint?: ReactNode;
  buttons: ReactNode;
  initialFocus?: RefObject<HTMLElement | null>;
  focusWhenGone?: () => HTMLElement | null;
  busy?: boolean;
  testId?: string;
}) {
  const opener = useRef<HTMLElement | null>(null);
  return (
    <Dialog.Root open={open} onOpenChange={(next) => (busy && !next ? undefined : onOpenChange(next))}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60" />
        <Dialog.Content
          data-testid={testId}
          className={cn(
            'fixed left-1/2 top-24 z-50 flex max-h-[calc(100vh-8rem)] w-[600px] max-w-[calc(100vw-2rem)] -translate-x-1/2 flex-col',
            'rounded-xl border border-temper-border bg-temper-panel text-temper-text shadow-xl',
          )}
          onOpenAutoFocus={(event) => {
            opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
            if (initialFocus?.current) {
              event.preventDefault();
              initialFocus.current.focus();
            }
          }}
          onCloseAutoFocus={(event) => {
            // Radix gives focus back to a Dialog.Trigger; these dialogs are
            // opened by the page's own buttons, so the page does it.
            const back = opener.current;
            opener.current = null;
            const target = back?.isConnected ? back : focusWhenGone?.();
            if (target) {
              event.preventDefault();
              target.focus();
            }
          }}
          onEscapeKeyDown={(event) => {
            if (busy) event.preventDefault();
          }}
        >
          <div className="flex items-center gap-2 border-b border-temper-border px-4 py-3">
            <Square className="h-4 w-4 shrink-0 text-[var(--badge-failed-text)]" aria-hidden="true" />
            <Dialog.Title className="m-0 min-w-0 text-sm font-semibold text-temper-text">{title}</Dialog.Title>
            {subtitle ? (
              <Dialog.Description className="m-0 min-w-0 flex-1 truncate text-xs text-temper-text-muted">
                {subtitle}
              </Dialog.Description>
            ) : (
              <span className="flex-1" />
            )}
            <Dialog.Cancel
              aria-label="Close"
              disabled={busy}
              className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md border border-transparent bg-transparent text-temper-text-muted hover:bg-temper-surface hover:text-temper-text disabled:cursor-not-allowed disabled:opacity-55"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Dialog.Cancel>
          </div>
          <div className="flex min-h-0 flex-col gap-2 overflow-auto p-4">{children}</div>
          <div className="flex flex-wrap items-center gap-2 border-t border-temper-border px-4 py-3">
            <span className="min-w-0 flex-1 text-xs text-temper-text-muted">{hint}</span>
            {buttons}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** Closes the dialog: a secondary button ("Keep running", "Keep the team", "Close"). */
export const TeamDialogCancel = Dialog.Cancel;

/** A section label inside a dialog ("What stops", "Your words"). */
export function TeamDialogLabel({ children }: { children: ReactNode }) {
  return <p className="m-0 text-xs font-semibold uppercase tracking-[0.06em] text-temper-text-muted">{children}</p>;
}
