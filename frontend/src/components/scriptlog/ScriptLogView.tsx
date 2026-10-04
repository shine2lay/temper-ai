/**
 * A script agent's log: what its script printed, line by line, while it runs and after.
 *
 * Shown in the live panel when a script agent is picked, and in the agent's full-screen view.
 * Both read the same saved log (hooks/useScriptLog.ts), so a refresh, a reconnect or a script
 * that was stopped shows what was saved, and new output follows on as it is saved.
 *
 * Each line has the time it was read and where it came from: stdout plain, stderr marked "err"
 * in red. Notes from temper itself (the limit was reached, output could not be saved, how the
 * attempt ended) are set apart. Everything is text: nothing the script printed is ever read as
 * HTML.
 *
 * The view follows new output while you are at the bottom; scroll up and it stays where you are
 * and says there is more below. It holds a bounded window of the log (lib/scriptLog.ts) and
 * draws at most RENDER_LINES lines of it at a time; "earlier lines" and "older output" go back.
 */
import { memo, useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ArrowDown, Check, CircleSlash, Clock, X } from 'lucide-react';
import { useExecutionStore } from '@/store/executionStore';
import { useScriptLogStore } from '@/store/scriptLogStore';
import { useScriptLog } from '@/hooks/useScriptLog';
import {
  DEFAULT_LOG_LIMIT,
  buildLines,
  formatBytes,
  formatLogTime,
  outcomeWords,
  scriptConfigOf,
  type LogLine,
  type ScriptLogRow,
} from '@/lib/scriptLog';
import { cn } from '@/lib/utils';

/** Lines drawn at once; "earlier lines" adds this many more. */
export const RENDER_LINES = 1500;
/** Characters of one line drawn until it is opened in full. */
export const LINE_SHOWN_CHARS = 10_000;

const NO_ROWS: ScriptLogRow[] = [];

interface Props {
  attemptId: string;
  /** A fixed height (the full-screen view); without one it fills its parent (the live panel). */
  height?: number;
  className?: string;
}

export function ScriptLogView({ attemptId, height, className }: Props) {
  const runId = useExecutionStore((s) => s.workflow?.id);
  const agent = useExecutionStore((s) => s.agents.get(attemptId));
  const running = agent?.status === 'running';
  const attempt = useScriptLog(runId, attemptId, running);
  const loadBefore = useScriptLogStore((s) => s.loadBefore);
  const loadAfter = useScriptLogStore((s) => s.loadAfter);
  const loadTail = useScriptLogStore((s) => s.loadTail);
  const jumpToLatest = useScriptLogStore((s) => s.jumpToLatest);

  const win = attempt?.win;
  const rows = win?.rows ?? NO_ROWS;
  const lines = useMemo(() => buildLines(rows), [rows]);
  const [drawn, setDrawn] = useState(RENDER_LINES);
  const shown = lines.length > drawn ? lines.slice(lines.length - drawn) : lines;
  const hiddenInMemory = lines.length - shown.length;

  // ------------------------------------------------------------ following, and staying put
  const scrollRef = useRef<HTMLDivElement>(null);
  // Following the end: true until the reader scrolls up, true again once they are back down.
  const [pinned, setPinned] = useState(true);
  const anchor = useRef<{ key: string; offset: number } | null>(null);
  const tail = shown.length > 0 ? `${shown[shown.length - 1].key}:${shown[shown.length - 1].text.length}` : '';
  const tailRef = useRef(tail);
  // The last line the reader saw at the bottom: anything after it is "new output below".
  const [seenTail, setSeenTail] = useState(tail);
  const unseen = !pinned && tail !== seenTail;

  const captureAnchor = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const items = el.querySelectorAll<HTMLElement>('[data-line-key]');
    let lo = 0;
    let hi = items.length - 1;
    let found: HTMLElement | null = null;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const item = items[mid];
      if (item.offsetTop + item.offsetHeight > el.scrollTop) {
        found = item;
        hi = mid - 1;
      } else {
        lo = mid + 1;
      }
    }
    anchor.current = found
      ? { key: found.dataset.lineKey ?? '', offset: found.offsetTop - el.scrollTop }
      : null;
  }, []);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setPinned(bottom);
    if (bottom) setSeenTail(tailRef.current);
    captureAnchor();
  }, [captureAnchor]);

  useLayoutEffect(() => {
    tailRef.current = tail;
    const el = scrollRef.current;
    if (!el) return;
    if (pinned) {
      el.scrollTop = el.scrollHeight;
    } else if (anchor.current) {
      // Lines came or went above what is being read (older output, earlier lines, the oldest
      // let go): keep the same line at the same place.
      const keep = el.querySelector<HTMLElement>(`[data-line-key="${CSS.escape(anchor.current.key)}"]`);
      if (keep) el.scrollTop = keep.offsetTop - anchor.current.offset;
    }
    captureAnchor();
  }, [shown, tail, pinned, captureAnchor]);

  const toBottom = useCallback(() => {
    const el = scrollRef.current;
    setPinned(true);
    setSeenTail(tailRef.current);
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  // ------------------------------------------------------------ what the header says
  const config = scriptConfigOf(agent);
  const latest = win?.latest ?? null;
  const summary = agent?.log ?? null;
  const configured = typeof config?.log_max_bytes === 'number' ? config.log_max_bytes : undefined;
  const limit = latest?.limit ?? summary?.limit ?? configured ?? DEFAULT_LOG_LIMIT;
  const saved = latest?.saved_bytes ?? summary?.saved_bytes ?? 0;
  const truncated = latest?.truncated ?? summary?.truncated ?? false;
  const dropped = Math.max(latest?.dropped_bytes ?? 0, summary?.dropped_bytes ?? 0);
  const lost = Math.max(latest?.lost_bytes ?? 0, summary?.lost_bytes ?? 0);
  const end = latest?.end;
  const finished = agent != null && !running && agent.status !== 'pending';

  let status: { text: string; tone: 'live' | 'ok' | 'bad' | 'muted'; title?: string };
  if (end) {
    status = { text: outcomeWords(end) ?? end.outcome, tone: end.outcome === 'completed' ? 'ok' : 'bad' };
  } else if (running) {
    status = { text: 'Live', tone: 'live', title: 'The script is running; new output appears as it is saved' };
  } else if (!win?.loaded) {
    status = { text: attempt?.error ? 'Not loaded' : 'Loading…', tone: 'muted' };
  } else if (!latest) {
    status = {
      text: 'Nothing saved',
      tone: 'muted',
      title: 'The script printed nothing, or it ran before temper saved script logs',
    };
  } else if (finished) {
    status = {
      text: 'Ended without its end note',
      tone: 'bad',
      title: 'temper could not save the end of this log: the last lines may be missing',
    };
  } else {
    status = { text: 'Saved so far', tone: 'muted' };
  }

  const loading = attempt?.loading ?? null;
  const error = attempt?.error ?? null;

  return (
    <div
      data-testid="script-log"
      data-attempt={attemptId}
      data-status={end?.outcome ?? (running ? 'live' : win?.loaded ? 'saved' : 'loading')}
      className={cn('flex min-h-0 flex-col', height == null && 'h-full', className)}
      style={height != null ? { height } : undefined}
    >
      <div className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-0.5 border-b border-temper-border px-3 py-1 text-[11px]">
        <span
          data-testid="script-log-status"
          title={status.title}
          className={cn(
            'flex items-center gap-1 rounded px-1.5 py-0.5 font-medium',
            status.tone === 'live' && 'bg-temper-running/15 text-temper-text',
            status.tone === 'ok' && 'bg-emerald-500/15 text-emerald-400',
            status.tone === 'bad' && 'bg-red-500/15 text-red-400',
            status.tone === 'muted' && 'bg-temper-surface text-temper-text-muted',
          )}
        >
          {status.tone === 'live' && <span className="size-1.5 animate-pulse rounded-full bg-temper-running" />}
          {status.text}
        </span>
        <span
          data-testid="script-log-limit"
          className="text-temper-text-muted"
          title={`${saved.toLocaleString()} of ${limit.toLocaleString()} bytes saved. The limit is the agent's log_max_bytes.`}
        >
          {formatBytes(saved)} saved · limit {formatBytes(limit)}
        </span>
        {truncated && (
          <span
            data-testid="script-log-truncated"
            className="flex items-center gap-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-500"
            title="Output past the limit is not saved; the script keeps running and its final result is unchanged"
          >
            <AlertTriangle className="size-3" />
            Limit reached{dropped > 0 ? `: ${formatBytes(dropped)} not saved` : ''}
          </span>
        )}
        {lost > 0 && (
          <span className="flex items-center gap-1 text-amber-500" title="Saving fell behind the script">
            <AlertTriangle className="size-3" />
            {formatBytes(lost)} could not be saved
          </span>
        )}
        {summary?.complete === false && (
          <span className="text-amber-500" title="temper could not save the whole log">
            log incomplete
          </span>
        )}
        <span className="ml-auto text-temper-text-dim">
          {latest ? `${latest.seq} row${latest.seq === 1 ? '' : 's'}` : ''}
        </span>
      </div>

      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={onScroll}
          data-testid="script-log-lines"
          className="relative h-full overflow-y-auto px-3 py-1 font-mono text-[11px] leading-[1.45]"
          style={{ overflowAnchor: 'none' }}
        >
          {hiddenInMemory > 0 && (
            <button
              type="button"
              data-testid="script-log-earlier"
              onClick={() => setDrawn((n) => n + RENDER_LINES)}
              className="my-1 w-full rounded border border-temper-border bg-temper-surface/60 px-2 py-1 font-sans text-[11px] text-temper-text-muted hover:text-temper-text"
            >
              Show {Math.min(hiddenInMemory, RENDER_LINES).toLocaleString()} earlier line{hiddenInMemory === 1 ? '' : 's'}
            </button>
          )}
          {hiddenInMemory === 0 && win?.hasMoreBefore && (
            <button
              type="button"
              data-testid="script-log-older"
              disabled={loading !== null}
              onClick={() => void loadBefore(attemptId)}
              className="my-1 w-full rounded border border-temper-border bg-temper-surface/60 px-2 py-1 font-sans text-[11px] text-temper-text-muted hover:text-temper-text disabled:opacity-60"
            >
              {loading === 'before' ? 'Loading older output…' : 'Load older output'}
            </button>
          )}

          {shown.map((line) => (
            <LogLineRow key={line.key} line={line} />
          ))}

          {win?.loaded && lines.length === 0 && !win.hasMoreBefore && (
            <p data-testid="script-log-empty" className="py-3 font-sans text-xs text-temper-text-dim">
              {running
                ? 'Waiting for the script’s first output… A program that buffers its output shows it only when it flushes.'
                : 'Nothing was saved for this attempt: the script printed nothing, or it ran before temper saved script logs.'}
            </p>
          )}
          {!win?.loaded && !error && (
            <p className="py-3 font-sans text-xs text-temper-text-dim">Loading the log…</p>
          )}
          {error && (
            <p data-testid="script-log-error" className="flex items-center gap-2 py-2 font-sans text-xs text-red-400">
              <X className="size-3 shrink-0" />
              {error}
              {attempt?.retryable !== false && (
                <button
                  type="button"
                  onClick={() => void (win?.loaded ? loadAfter(attemptId) : loadTail(attemptId))}
                  className="rounded border border-temper-border px-1.5 py-0.5 text-temper-text-muted hover:text-temper-text"
                >
                  Try again
                </button>
              )}
            </p>
          )}

          {win?.hasMoreAfter && (
            <div
              data-testid="script-log-newer"
              className="my-1 flex items-center gap-2 rounded border border-temper-border bg-temper-surface/60 px-2 py-1 font-sans text-[11px] text-temper-text-muted"
            >
              Newer output is not shown.
              <button
                type="button"
                disabled={loading !== null}
                onClick={() => void loadAfter(attemptId)}
                className="rounded border border-temper-border px-1.5 py-0.5 hover:text-temper-text disabled:opacity-60"
              >
                Load newer
              </button>
              <button
                type="button"
                data-testid="script-log-latest"
                onClick={() => {
                  setPinned(true);
                  void jumpToLatest(attemptId);
                }}
                className="rounded border border-temper-border px-1.5 py-0.5 hover:text-temper-text"
              >
                Jump to latest
              </button>
            </div>
          )}
        </div>

        {unseen && (
          <button
            type="button"
            data-testid="script-log-new-below"
            onClick={toBottom}
            className="absolute bottom-2 right-4 flex items-center gap-1 rounded-full border border-temper-border bg-temper-bg px-2 py-0.5 text-[11px] text-temper-text shadow"
          >
            <ArrowDown className="size-3" />
            New output below
          </button>
        )}
      </div>
    </div>
  );
}

const NOTE_ICON: Record<string, typeof Check> = {
  completed: Check,
  failed: X,
  timed_out: Clock,
  cancelled: CircleSlash,
};

const LogLineRow = memo(
  function LogLineRow({ line }: { line: LogLine }) {
    const [whole, setWhole] = useState(false);
    if (line.stream === 'temper') {
      const ok = line.kind === 'end' && line.outcome === 'completed';
      const Icon = line.kind === 'end' ? NOTE_ICON[line.outcome ?? ''] ?? X : AlertTriangle;
      return (
        <div
          data-line-key={line.key}
          data-testid="script-log-note"
          data-kind={line.kind}
          data-outcome={line.outcome}
          className={cn(
            'my-0.5 flex items-start gap-2 rounded px-1 py-0.5 font-sans',
            ok ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500',
            line.kind === 'end' && !ok && 'bg-red-500/10 text-red-400',
          )}
        >
          <time className="shrink-0 font-mono tabular-nums opacity-90" dateTime={line.t} title={line.t}>
            {formatLogTime(line.t)}
          </time>
          <Icon className="mt-0.5 size-3 shrink-0" />
          <span className="min-w-0 whitespace-pre-wrap break-words">{line.text}</span>
        </div>
      );
    }
    const err = line.stream === 'stderr';
    const long = line.text.length > LINE_SHOWN_CHARS && !whole;
    return (
      <div data-line-key={line.key} data-testid="script-log-line" data-stream={line.stream} className="flex gap-2">
        <time className="shrink-0 tabular-nums text-temper-text-dim" dateTime={line.t} title={line.t}>
          {formatLogTime(line.t)}
        </time>
        <span
          className={cn(
            'mt-px h-fit w-7 shrink-0 rounded text-center font-sans text-[9px] uppercase leading-[14px]',
            err ? 'bg-red-500/15 text-red-400' : 'text-temper-text-dim',
          )}
          title={err ? 'printed to stderr' : 'printed to stdout'}
        >
          {err ? 'err' : 'out'}
        </span>
        <span className={cn('min-w-0 whitespace-pre-wrap break-all', err ? 'text-red-400' : 'text-temper-text')}>
          {long ? line.text.slice(0, LINE_SHOWN_CHARS) : line.text}
          {long && (
            <button
              type="button"
              onClick={() => setWhole(true)}
              className="ml-1 rounded border border-temper-border px-1 font-sans text-[10px] text-temper-text-muted hover:text-temper-text"
            >
              … {(line.text.length - LINE_SHOWN_CHARS).toLocaleString()} more characters
            </button>
          )}
        </span>
      </div>
    );
  },
  (a, b) =>
    a.line.text === b.line.text && a.line.t === b.line.t && a.line.stream === b.line.stream && a.line.kind === b.line.kind,
);
