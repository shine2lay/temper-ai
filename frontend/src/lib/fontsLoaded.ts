/**
 * The page's own fonts (index.css, `font-display: swap`) can arrive after the
 * first layout, so a size measured then is a fallback font's. `onFontsLoaded`
 * asks for both of the page's faces outright and calls `measure` once they
 * have loaded, again once the fonts are ready and whenever more finish
 * loading, so nothing keeps a size measured with a fallback font (Design
 * D80; page.mjs renders again after the same two loads). If a face fails to
 * load, the layout stays as it is and `loadingdone` still re-measures. Where
 * the browser has no font loading API it does nothing.
 *
 * `done` hears once whether the faces loaded ('loaded'), failed ('failed')
 * or can't be asked for ('none'), after the measure that follows: the page
 * marks its map with it and the browser checks wait for it.
 *
 * Returns the clean-up, for an effect's return.
 */

/** The page's two faces (index.css): regular and semibold, the one file for every heavier weight. */
export const PAGE_FACES = ['400 16px "Source Sans Pro"', '600 16px "Source Sans Pro"'] as const;

/** 'waiting' until the faces' load has settled; then what `onFontsLoaded` reported. */
export type FontsState = 'waiting' | 'loaded' | 'failed' | 'none';

export function onFontsLoaded(measure: () => void, done?: (state: Exclude<FontsState, 'waiting'>) => void): () => void {
  const fonts = typeof document !== 'undefined' ? document.fonts : undefined;
  if (!fonts) {
    done?.('none');
    return () => undefined;
  }
  let alive = true;
  const again = () => {
    if (alive) measure();
  };
  const settle = (state: 'loaded' | 'failed') => () => {
    if (!alive) return;
    measure();
    done?.(state);
  };
  if (typeof fonts.load === 'function') {
    // A face is only fetched once some text needs it, so ask for both before the page counts as measured.
    void Promise.all(PAGE_FACES.map((face) => fonts.load(face))).then(settle('loaded'), settle('failed'));
  } else {
    done?.('none');
  }
  void fonts.ready.then(again, () => undefined);
  fonts.addEventListener?.('loadingdone', again);
  return () => {
    alive = false;
    fonts.removeEventListener?.('loadingdone', again);
  };
}
