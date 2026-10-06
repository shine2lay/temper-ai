/**
 * Small controls with a 24 px target and an unchanged look (WCAG 2.2, 2.5.8).
 *
 * A control inside a clickable row can't use the criterion's spacing
 * exception, because the row is a target too. So the control's own box grows
 * to 24 px and stays see-through, and its old look is drawn on a span inside
 * it. The span takes its hover from the control (`group/hit`), and the
 * keyboard ring stays on the part you see, where it was before.
 */

/**
 * For the 24 px control. It draws no ring of its own; the `!` is needed
 * because the app-wide ring (`:focus-visible` in index.css) is unlayered.
 * While focused it sits above its neighbours, so the next control along
 * can't paint over the ring.
 */
export const HIT_AREA = 'group/hit relative focus-visible:z-10 focus-visible:outline-none!';

/** For the span inside: the app-wide focus ring, while the control has keyboard focus. */
export const HIT_AREA_RING =
  'group-focus-visible/hit:outline-2 group-focus-visible/hit:outline-offset-2 group-focus-visible/hit:outline-temper-accent group-focus-visible/hit:rounded-[2px]';
