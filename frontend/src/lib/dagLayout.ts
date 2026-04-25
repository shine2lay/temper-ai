/**
 * Lightweight DAG layout helpers.
 *
 * Most of the DAG/edge layout work moved to `lib/elkLayout.ts` (ELK)
 * for the execution DAG view. This module retains only the small graph
 * utilities still consumed by the Studio editor (`useDesignElements`),
 * which uses its own positioning logic for the workflow editor.
 */

/**
 * Compute longest-path depths from a dependency map.
 * Roots (no deps) get depth 0; each other stage = max(pred depths) + 1.
 *
 * Used by the Studio editor for column-based stage placement during
 * workflow editing. Distinct from runtime DAG layout which now uses
 * ELK's `layered` algorithm.
 */
export function computeDepthsFromDepMap(
  depMap: Map<string, string[]>,
): Map<string, number> {
  const depths = new Map<string, number>();
  for (const [name, deps] of depMap) {
    if (deps.length === 0) depths.set(name, 0);
  }
  let changed = true;
  while (changed) {
    changed = false;
    for (const [name, deps] of depMap) {
      if (deps.length === 0) continue;
      if (!deps.every((d) => depths.has(d))) continue;
      const newDepth = Math.max(...deps.map((d) => depths.get(d)!)) + 1;
      if (depths.get(name) !== newDepth) {
        depths.set(name, newDepth);
        changed = true;
      }
    }
  }
  return depths;
}
