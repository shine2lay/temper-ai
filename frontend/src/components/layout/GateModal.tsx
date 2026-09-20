import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { PauseCircle, X } from 'lucide-react';
import { useExecutionStore } from '@/store/executionStore';
import { useGates, type GateAnswer, type GateQuestion, type WaitingGate } from '@/hooks/useGates';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';

interface GateModalProps {
  executionId: string | undefined;
}

/**
 * The dialog a run parked at a human gate opens: what the previous node
 * produced, the questions it asked, and the answers going back.
 *
 * It replaces a banner with an Approve button — which could only say yes,
 * never say anything — and is modelled on pi's `ask_user_question`: a
 * question, optional options with descriptions and a preview of the chosen
 * one, single or multi select, and a free-text box either way.
 *
 * Opens by itself when a run stops at a gate, reopens from the gated node's
 * card in the DAG (the store's `gateNodeName`), and can be dismissed —
 * "Later" leaves the run waiting, it does not approve anything.
 */
export function GateModal({ executionId }: GateModalProps) {
  const { gates, approve } = useGates(executionId);
  const gateNodeName = useExecutionStore((s) => s.gateNodeName);
  const openGate = useExecutionStore((s) => s.openGate);
  const closeGate = useExecutionStore((s) => s.closeGate);
  // Gates already shown once, so dismissing one does not immediately reopen
  // on the next poll. Keyed by the waiting event, so the next lap of a loop
  // opens again for the same node name. A ref, not state: nothing renders
  // from it, and writing it must not cost a render.
  const seen = useRef<Set<string>>(new Set());

  const gateKey = (g: WaitingGate) => g.event_id ?? g.node_name;
  const open = gates.find((g) => g.node_name === gateNodeName);

  // A run that stops at a gate should say so without being clicked.
  useEffect(() => {
    if (gateNodeName) return;
    const next = gates.find((g) => !seen.current.has(gateKey(g)));
    if (next) {
      seen.current.add(gateKey(next));
      openGate(next.node_name);
    }
  }, [gates, gateNodeName, openGate]);

  if (!open) return null;
  return (
    <GateDialog
      key={gateKey(open)}
      gate={open}
      pending={approve.isPending}
      onClose={closeGate}
      onSubmit={(response, answers) =>
        approve.mutate(
          { nodeName: open.node_name, response, answers },
          {
            onSuccess: () => {
              toast.success(`Approved "${open.node_name}"`);
              closeGate();
            },
            onError: (err: Error) => toast.error(`Could not approve: ${err.message}`),
          },
        )
      }
    />
  );
}

function GateDialog({
  gate,
  pending,
  onClose,
  onSubmit,
}: {
  gate: WaitingGate;
  pending: boolean;
  onClose: () => void;
  onSubmit: (response: string, answers: GateAnswer[]) => void;
}) {
  const [selections, setSelections] = useState<Record<string, string[]>>({});
  const [customs, setCustoms] = useState<Record<string, string>>({});
  const [response, setResponse] = useState('');

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const toggle = (q: GateQuestion, label: string) =>
    setSelections((prev) => {
      const current = prev[q.id] ?? [];
      if (q.multiSelect) {
        return {
          ...prev,
          [q.id]: current.includes(label)
            ? current.filter((l) => l !== label)
            : [...current, label],
        };
      }
      return { ...prev, [q.id]: current.includes(label) ? [] : [label] };
    });

  /** A question with options needs one picked (or typed) before approving. */
  const answered = (q: GateQuestion) =>
    (q.options?.length ?? 0) === 0 ||
    (selections[q.id]?.length ?? 0) > 0 ||
    (customs[q.id] ?? '').trim() !== '';
  const ready = gate.questions.every(answered);

  const answers = useMemo(
    () =>
      gate.questions.map((q) => ({
        id: q.id,
        question: q.question,
        selected: selections[q.id] ?? [],
        custom: (customs[q.id] ?? '').trim(),
      })),
    [gate.questions, selections, customs],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Approval needed: ${gate.node_name}`}
        className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-lg border border-temper-border bg-temper-panel shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center gap-2 border-b border-temper-border px-5 py-3">
          <PauseCircle
            className="size-4 shrink-0"
            style={{ color: 'var(--color-temper-waiting)' }}
            aria-hidden
          />
          <h2 className="text-sm font-semibold text-temper-text">
            Approval needed — <span className="font-mono">{gate.node_name}</span>
          </h2>
          <span className="text-xs text-temper-text-muted">This run is paused until you answer.</span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto rounded p-1 text-temper-text-muted hover:bg-temper-surface hover:text-temper-text"
          >
            <X className="size-4" aria-hidden />
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          {gate.upstream.map((up) => (
            <section key={up.node}>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-temper-text-muted">
                {up.node}
              </h3>
              {up.output ? (
                <MarkdownDisplay content={up.output} className="max-h-64 overflow-y-auto" />
              ) : (
                !up.full_output && <p className="text-xs italic text-temper-text-dim">No output.</p>
              )}
              {up.full_output && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs text-temper-text-muted hover:text-temper-text">
                    Full output
                  </summary>
                  <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded-md border border-temper-border bg-temper-panel p-2 text-xs text-temper-text-muted">
                    {up.full_output}
                  </pre>
                </details>
              )}
            </section>
          ))}
          {gate.upstream.length === 0 && (
            <p className="text-xs italic text-temper-text-dim">
              Nothing ran before this gate.
            </p>
          )}

          {gate.questions.map((q, i) => (
            <section key={q.id} className="rounded-md border border-temper-border bg-temper-surface/40 p-3">
              <h3 className="text-xs font-medium uppercase tracking-wide text-temper-text-muted">
                {q.header ?? `Question ${i + 1}`}
                {q.node && <span className="ml-1 normal-case text-temper-text-dim">· {q.node}</span>}
              </h3>
              <p className="mt-1 text-sm text-temper-text">{q.question}</p>
              {q.detail && <p className="mt-1 text-xs text-temper-text-muted">{q.detail}</p>}

              {(q.options?.length ?? 0) > 0 && (
                <div className="mt-2 space-y-1">
                  {q.options!.map((opt) => {
                    const active = (selections[q.id] ?? []).includes(opt.label);
                    return (
                      <div key={opt.label}>
                        <button
                          type="button"
                          aria-pressed={active}
                          onClick={() => toggle(q, opt.label)}
                          className={`flex w-full items-start gap-2 rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                            active
                              ? 'border-temper-accent bg-temper-accent/10 text-temper-text'
                              : 'border-temper-border bg-temper-panel text-temper-text-muted hover:bg-temper-surface'
                          }`}
                        >
                          <span aria-hidden className="mt-px font-mono text-xs">
                            {q.multiSelect ? (active ? '☑' : '☐') : active ? '●' : '○'}
                          </span>
                          <span>
                            {opt.label}
                            {opt.description && (
                              <span className="block text-xs text-temper-text-dim">{opt.description}</span>
                            )}
                          </span>
                        </button>
                        {active && opt.preview && (
                          <MarkdownDisplay content={opt.preview} className="mt-1 max-h-40 overflow-y-auto" />
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              <input
                value={customs[q.id] ?? ''}
                onChange={(e) => setCustoms((prev) => ({ ...prev, [q.id]: e.target.value }))}
                placeholder={(q.options?.length ?? 0) > 0 ? 'Or answer in your own words…' : 'Your answer…'}
                aria-label={q.question}
                className="mt-2 w-full rounded-md border border-temper-border bg-temper-panel px-3 py-1.5 text-sm text-temper-text placeholder:text-temper-text-dim focus:border-temper-accent focus:outline-none"
              />
            </section>
          ))}

          <section>
            <label
              htmlFor="gate-response"
              className="text-xs font-medium uppercase tracking-wide text-temper-text-muted"
            >
              {gate.questions.length > 0 ? 'Anything else' : 'Response'}{' '}
              <span className="normal-case text-temper-text-dim">(optional)</span>
            </label>
            <textarea
              id="gate-response"
              rows={3}
              value={response}
              onChange={(e) => setResponse(e.target.value)}
              placeholder="Goes to the next node as gate.text…"
              className="mt-1 w-full resize-y rounded-md border border-temper-border bg-temper-panel px-3 py-2 text-sm text-temper-text placeholder:text-temper-text-dim focus:border-temper-accent focus:outline-none"
            />
          </section>
        </div>

        <div className="flex shrink-0 items-center gap-2 border-t border-temper-border px-5 py-3">
          <span className="text-xs text-temper-text-dim">
            {ready ? 'The run continues when you approve.' : 'Answer the questions to continue.'}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-temper-border bg-temper-surface px-3 py-1.5 text-xs font-medium text-temper-text hover:brightness-110"
            >
              Later
            </button>
            <button
              type="button"
              disabled={pending || !ready}
              onClick={() => onSubmit(response.trim(), answers)}
              className="rounded-md bg-temper-accent px-3 py-1.5 text-xs font-medium text-white transition-colors hover:brightness-110 disabled:opacity-50"
            >
              {pending ? 'Approving…' : 'Approve & continue'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
