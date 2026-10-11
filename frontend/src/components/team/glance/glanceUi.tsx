/** The glance page's icons, by the names the glance model uses, and its small text helpers. */
import { Fragment, type ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  Check,
  Circle,
  CircleAlert,
  CircleDashed,
  CircleDot,
  CirclePlay,
  Clock,
  Flag,
  GitBranch,
  Hand,
  MessageSquare,
  Moon,
  Pause,
  Play,
  RotateCcw,
  RotateCw,
  Settings,
  Square,
  TriangleAlert,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type { GlanceIcon, Moment, MomentPart } from '@/lib/teamGlance';

const GLANCE_ICONS: Record<GlanceIcon | Moment['icon'], LucideIcon> = {
  play: Play,
  pause: Pause,
  flag: Flag,
  moon: Moon,
  settings: Settings,
  hand: Hand,
  clock: Clock,
  restart: RotateCw,
  check: Check,
  stop: Square,
  alert: CircleAlert,
  circle: Circle,
  retry: RotateCcw,
  ready: CircleDot,
  wait: CircleDashed,
  message: MessageSquare,
  share: GitBranch,
  start: CirclePlay,
  conflict: TriangleAlert,
};

/** S2: all parts are plain React text; exact file names are code, never links or markup. */
export function MomentText({ parts }: { parts: readonly MomentPart[] }) {
  return <>{parts.map((p, i) => p.code ? (
    <code key={i} className="font-mono [overflow-wrap:anywhere]">{p.text}</code>
  ) : p.strong ? (
    <b key={i} className="font-semibold">{p.text}</b>
  ) : (
    <span key={i}><PathText text={p.text} /></span>
  ))}</>;
}

export function GIcon({ name, className }: { name: GlanceIcon | Moment['icon']; className?: string }) {
  const Icon = GLANCE_ICONS[name] ?? Circle;
  return <Icon className={className ?? 'h-4 w-4 shrink-0'} aria-hidden="true" />;
}

/**
 * D50: a path in event words breaks only after a "/" (a <wbr> after each
 * one), so "/reports/export.csv" never splits inside "export.csv".
 */
export function PathText({ text }: { text: string }) {
  if (!text.includes('/')) return <>{text}</>;
  const parts = text.split('/');
  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {part}
          {i < parts.length - 1 && (
            <>
              /<wbr />
            </>
          )}
        </Fragment>
      ))}
    </>
  );
}

/**
 * D40, D69: facts in one wrapping row, each kept whole with its dot in
 * front. The dot that would start a line is clipped (glance.css), so no
 * line starts or ends with a stray "\u00b7". The dots are not read out.
 */
/** One fact with a class of its own ("max-md:hidden": left out on a phone, D74). */
export interface Fact {
  fact: ReactNode;
  className?: string;
}

function isFact(item: ReactNode | Fact): item is Fact {
  return typeof item === 'object' && item !== null && 'fact' in item;
}

export function Facts({ items, className, testId }: { items: (ReactNode | Fact)[]; className?: string; testId?: string }) {
  return (
    <div className={cn('glance-facts', className)} data-testid={testId}>
      <ul role="list">
        {items.map((item, i) => (
          <li key={i} className={isFact(item) ? item.className : undefined}>
            <span className="glance-sep" aria-hidden="true">
              {'\u00b7'}
            </span>
            {isFact(item) ? item.fact : item}
          </li>
        ))}
      </ul>
    </div>
  );
}
