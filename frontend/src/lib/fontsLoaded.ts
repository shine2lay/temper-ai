/**
 * The page's own fonts (index.css, `font-display: swap`) can arrive after the
 * first layout, so a size measured then is a fallback font's. `onFontsLoaded`
 * calls `measure` once the fonts are ready and again whenever more finish
 * loading, so nothing keeps a size measured with a fallback font (Design
 * D80). Where the browser has no font loading API it does nothing.
 *
 * Returns the clean-up, for an effect's return.
 */
export function onFontsLoaded(measure: () => void): () => void {
  const fonts = typeof document !== 'undefined' ? document.fonts : undefined;
  if (!fonts) return () => undefined;
  let alive = true;
  const again = () => {
    if (alive) measure();
  };
  void fonts.ready.then(again, () => undefined);
  fonts.addEventListener?.('loadingdone', again);
  return () => {
    alive = false;
    fonts.removeEventListener?.('loadingdone', again);
  };
}
