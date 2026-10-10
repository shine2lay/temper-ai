/**
 * The page's own fonts (index.css, `font-display: swap`) can arrive after the
 * first layout, so a size measured then is a fallback font's. `onFontsLoaded`
 * asks for both of the page's faces outright, with the symbol faces of each
 * weight (`PAGE_TEXT`), and calls `measure` once they
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

/**
 * The text the faces are asked for: a space for the page's own files, and the
 * four symbols they lack (right and down arrows, play and warning signs), whose
 * small faces in index.css cover only those. `fonts.load` fetches only the faces
 * whose unicode-range holds a character of its text, a single space by default,
 * so without the symbols here the ready point would not wait for their faces.
 */
export const PAGE_TEXT = ' \u2192\u2193\u25B6\u26A0';

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
    void Promise.all(PAGE_FACES.map((face) => fonts.load(face, PAGE_TEXT))).then(settle('loaded'), settle('failed'));
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
