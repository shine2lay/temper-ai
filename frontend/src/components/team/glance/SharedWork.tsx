/**
 * Shared work: the team's latest shared version big, who shared it and
 * when, files changed, commit and its share note; the two before it below;
 * and, once the leader said done, the leader's own summary (never a
 * generated one). Facts wrap whole, with no stray dot (D69). There is no
 * "See the changes" link: no version view is reachable from this page yet,
 * and a dead or raw-JSON link is never shown (D54).
 */
import { cn } from '@/lib/utils';
import { agoText, type GlanceRun, type GlanceShare } from '@/lib/teamGlance';
import { teamCard } from '@/components/team/teamUi';
import { Facts } from './glanceUi';
import { glanceCardHead } from './glanceStyle';

function filesWords(s: GlanceShare): string | null {
  if (s.filesChanged === null) return null;
  return `${s.filesChanged} ${s.filesChanged === 1 ? 'file' : 'files'} changed`;
}

/** `now`: the clock every "ago" counts to. */
export function SharedWork({ run, now }: { run: GlanceRun; now: number | null }) {
  const { latest, shares, total, summary } = run.work;
  const older = shares.filter((s) => s.versionNo !== latest?.versionNo).slice(0, 2);
  return (
    <section className={cn(teamCard, 'flex min-w-0 flex-col gap-3 p-4')} aria-labelledby="glance-work-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="glance-work-title" className={glanceCardHead}>
          Shared work
        </h2>
        {total > 0 && (
          <p className="m-0 text-sm text-temper-text-muted">
            {total} {total === 1 ? 'version' : 'versions'}
          </p>
        )}
      </div>
      {summary && (
        <div className="flex min-w-0 flex-col gap-1" data-testid="glance-summary">
          <h3 id="glance-summary" tabIndex={-1} className="m-0 text-sm font-semibold text-temper-text">
            {run.leader}&apos;s summary
          </h3>
          <blockquote className="m-0 border-l-2 border-temper-control pl-3 text-sm whitespace-pre-line break-words text-temper-text">
            {summary}
          </blockquote>
        </div>
      )}
      {latest ? (
        <div className="flex min-w-0 items-start gap-3" data-testid="glance-latest-version">
          {/* SPEC 7: "v6" 28 px semibold (D93); who and when, files and commit 15 px; the share note 16 px. */}
          <span
            className="rounded-md border border-temper-control px-2.5 py-1 text-[28px] leading-9 font-semibold text-temper-text"
            data-testid="glance-version-number"
          >
            v{latest.versionNo}
          </span>
          <div className="flex min-w-0 flex-col gap-0.5 text-[15px]">
            <Facts
              className="text-temper-text"
              testId="glance-latest-by"
              items={[
                <>
                  Shared by <b className="font-semibold">{latest.by ?? 'a member'}</b>
                </>,
                ...(latest.at && agoText(latest.at, now) ? [agoText(latest.at, now)] : []),
              ]}
            />
            {(filesWords(latest) || latest.commitShort) && (
              <Facts
                className="text-temper-text-muted"
                testId="glance-latest-files"
                items={[filesWords(latest), latest.commitShort ? `commit ${latest.commitShort.slice(0, 7)}` : null].filter(
                  (f): f is string => f !== null,
                )}
              />
            )}
            {latest.note && <p className="m-0 text-base break-words text-temper-text">&ldquo;{latest.note}&rdquo;</p>}
          </div>
        </div>
      ) : (
        <p className="m-0 text-sm text-temper-text-muted" data-testid="glance-work-empty">
          No shared version yet. When a member shares its work it shows here as v1, v2 and so on.
        </p>
      )}
      {older.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1 border-t border-temper-border p-0 pt-2 text-sm">
          {older.map((s) => (
            <li key={s.versionNo} className="min-w-0 text-temper-text-muted">
              <Facts
                items={[
                  <span className="font-semibold text-temper-text">v{s.versionNo}</span>,
                  s.by ?? 'a member',
                  ...(s.at && agoText(s.at, now) ? [agoText(s.at, now)] : []),
                  ...(s.note ? [<>&ldquo;{s.note}&rdquo;</>] : []),
                ]}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
