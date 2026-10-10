/**
 * D97: what the latest version holds, as two 16 px lines in Now, from Temper's
 * work.latest (never a made-up summary). Line 1: "Latest version v6 from
 * Backend · 4 min ago", who and when in the secondary text colour. Line 2: the
 * member's share note, quoted (a person's words, D94), on one line; a note too
 * long for it is cut to the room left with its closing quote kept (D111), the
 * whole note in the line's title and in All activity. With no note: "4 files
 * changed". D111: under 768 px the time leads line 2 instead, so line 1 stays
 * one line. Before any share: "No shared version yet."
 */
import { Fragment, useLayoutEffect, useRef } from 'react';
import { useIsNarrow } from '@/lib/useMediaQuery';
import { cutNote, keepTogether, versionLines, type GlanceShare } from '@/lib/teamGlance';
import { Facts } from './glanceUi';

/**
 * Cuts the note in `trunc` to the room `line` leaves it, as the reference's
 * fitNotes(): the room is the line's width less its other parts; the longest
 * cut that fits wins. The span's text is set here only (React renders it
 * empty), so measuring never fights React's own text node. Runs on render, on
 * resize and once the fonts load; the CSS ellipsis is the fallback. Returns
 * the refs for line 2 and the note's span.
 */
function useFitNote(note: string | null, layout: string) {
  const line = useRef<HTMLDivElement>(null);
  const trunc = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const v2 = line.current;
    const t = trunc.current;
    if (!v2 || !t || note === null) return;
    const fit = () => {
      const room =
        v2.getBoundingClientRect().width -
        [...v2.children].filter((c) => c !== t).reduce((w, c) => w + c.getBoundingClientRect().width, 0);
      const width = (s: string) => {
        t.textContent = s;
        return t.getBoundingClientRect().width;
      };
      // Measured at its own width, not the width the line squeezes it to.
      t.style.flex = 'none';
      if (width(cutNote(note, note.length)) > room + 0.01) {
        let lo = 0;
        let hi = note.length;
        while (lo < hi) {
          const mid = (lo + hi + 1) >> 1;
          if (width(cutNote(note, mid)) <= room + 0.01) lo = mid;
          else hi = mid - 1;
        }
        t.textContent = cutNote(note, lo);
      }
      t.style.flex = '';
    };
    fit();
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(fit);
    ro?.observe(v2);
    const fonts = typeof document === 'undefined' ? undefined : document.fonts;
    let live = true;
    void fonts?.ready.then(() => {
      if (live) fit();
    });
    fonts?.addEventListener?.('loadingdone', fit);
    return () => {
      live = false;
      ro?.disconnect();
      fonts?.removeEventListener?.('loadingdone', fit);
    };
  }, [note, layout]);
  return { line, trunc };
}

export function NowVersion({ latest, agesAt }: { latest: GlanceShare | null; agesAt: number | null }) {
  const narrow = useIsNarrow();
  const v = versionLines(latest, agesAt);
  const note = v?.note ?? null;
  const { line: line2, trunc } = useFitNote(note, `${narrow}|${v?.ago ?? ''}`);
  if (!v) {
    return (
      <p className="m-0 text-[15px] text-temper-text-muted" data-testid="glance-version">
        No shared version yet.
      </p>
    );
  }
  const who = (
    <>
      Latest version <b className="font-semibold">v{v.versionNo}</b>
      {v.by && (
        <>
          {' '}
          <span className="text-temper-text-2">from&nbsp;{v.by}</span>
        </>
      )}
    </>
  );
  // D69: "4 min ago" stays on one line.
  const when = v.ago ? <span className="text-temper-text-2">{v.ago.endsWith(' ago') ? keepTogether(v.ago) : v.ago}</span> : null;
  const body = note ? (
    // The text is set by useFitNote (whole, or cut to the room left).
    <span ref={trunc} className="glance-trunc" data-testid="glance-version-note" />
  ) : (
    v.files && <span data-testid="glance-version-files">{v.files}</span>
  );
  const parts = [narrow ? when : null, body].filter(Boolean);
  return (
    <div className="glance-ver" data-testid="glance-version">
      <Facts items={narrow || !when ? [who] : [who, when]} testId="glance-version-line1" />
      {parts.length > 0 && (
        <div ref={line2} className="glance-ver2" title={note ?? undefined} data-testid="glance-version-line2">
          {/* Flat children: the room left for the note is the line less its other parts (useFitNote). */}
          {parts.map((p, i) => (
            <Fragment key={i}>
              {i > 0 && <span className="glance-vsep" aria-hidden="true" />}
              {p}
            </Fragment>
          ))}
        </div>
      )}
    </div>
  );
}
