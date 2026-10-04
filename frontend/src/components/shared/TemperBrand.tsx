import symbolUrl from '@/assets/brand/temper-symbol.svg';
import symbolReverseUrl from '@/assets/brand/temper-symbol-reverse.svg';
import lockupUrl from '@/assets/brand/temper-ai-lockup.svg';
import { cn } from '@/lib/utils';

/*
 * Temper's mark, as Design delivered it (design-lab temper-logo packet,
 * BRAND.md). The files are used as they are: never recoloured, stretched,
 * cropped or given effects.
 *
 * - Light grounds take the ink colourway, dark grounds the reverse one. Both
 *   are rendered and the theme's `dark` class shows one, so the mark follows
 *   the theme switch without a re-render.
 * - The symbol is at least 24 px. Its 128-unit file already keeps the glyph
 *   clear of the edges; callers add margin so a quarter of the symbol box
 *   stays empty on every side.
 * - There is no reverse lockup in the packet, so on dark grounds the lockup is
 *   the reverse symbol next to the live name, set in the brand face.
 */

const SYMBOL_MIN_PX = 24;

interface SymbolProps {
  /** Rendered width and height in px; never below 24. */
  size?: number;
  /** Accessible name. Empty when the name is written right next to it. */
  label?: string;
  className?: string;
}

export function TemperSymbol({ size = 32, label = '', className }: SymbolProps) {
  const px = Math.max(size, SYMBOL_MIN_PX);
  const common = {
    width: px,
    height: px,
    alt: label,
    draggable: false,
    // A fixed square: the mark must never be squeezed by a flex row.
    style: { width: px, height: px },
  } as const;
  return (
    <span
      className={cn('inline-flex shrink-0', className)}
      data-testid="temper-symbol"
      style={{ width: px, height: px }}
    >
      <img {...common} src={symbolUrl} className="block dark:hidden" data-colourway="ink" />
      <img {...common} src={symbolReverseUrl} className="hidden dark:block" data-colourway="reverse" />
    </span>
  );
}

interface LockupProps {
  /** Width of the light lockup in px; never below 160. */
  width?: number;
  className?: string;
}

const LOCKUP_MIN_PX = 160;
// temper-ai-lockup.svg is 360 x 96.
const LOCKUP_RATIO = 96 / 360;

/** "Temper AI" with the symbol, for places with room for the full lockup. */
export function TemperLockup({ width = 200, className }: LockupProps) {
  const w = Math.max(width, LOCKUP_MIN_PX);
  const h = Math.round(w * LOCKUP_RATIO);
  return (
    <div className={cn('inline-flex', className)} role="img" aria-label="Temper AI" data-testid="temper-lockup">
      <img
        src={lockupUrl}
        alt=""
        width={w}
        height={h}
        draggable={false}
        style={{ width: w, height: h }}
        className="block dark:hidden"
      />
      <span className="hidden dark:inline-flex items-center gap-2" style={{ height: h }}>
        <TemperSymbol size={h} />
        <span className="font-semibold text-temper-text whitespace-nowrap" style={{ fontSize: Math.round(h * 0.42) }}>
          Temper AI
        </span>
      </span>
    </div>
  );
}
