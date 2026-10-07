/**
 * Where the live Team journey (e2e-live/team-journey.live.spec.ts) may write
 * its screenshots, its report and Playwright's own notes: an absolute folder
 * outside every git checkout. temper-ai is public on GitHub, and those files
 * hold the live page.
 *
 * A folder is judged where the disk really keeps it: every link on the way is
 * followed, and a folder still to be made is judged by the real place of its
 * nearest existing parent. So a link from outside into a checkout, with or
 * without folders still to be made under it, is refused like a plain path
 * inside one. playwright.live.config.ts asks before Playwright starts or
 * writes anything; the live spec asks again before it opens a page. Both
 * write only to the real folder it returns.
 *
 * Only node:fs and node:path here: the live config imports it.
 */
import { existsSync, lstatSync, realpathSync } from 'node:fs';
import path from 'node:path';

const README = 'frontend/README.md, "Team journey (live)"';

/**
 * The real path `p` names: its nearest existing ancestor with every link
 * followed, then the names still to be made. A name that is there but leads
 * nowhere real (a link to nothing, a file on the way) is an error.
 */
export function realBackingPath(p: string): string {
  const missing: string[] = [];
  for (let at = path.resolve(p); ; at = path.dirname(at)) {
    try {
      return path.join(realpathSync.native(at), ...missing);
    } catch (e) {
      const code = (e as NodeJS.ErrnoException).code ?? 'an error';
      let there = true;
      try {
        lstatSync(at);
      } catch {
        there = false;
      }
      if (code !== 'ENOENT' || there) throw new Error(`${p} leads nowhere real (${code} at ${at})`);
      missing.unshift(path.basename(at));
    }
  }
}

/** The checkout a real path lies in: the nearest folder at or above it holding a .git (a folder, or a worktree's file); null if none. */
export function checkoutAround(realPath: string): string | null {
  for (let at = realPath; ; at = path.dirname(at)) {
    if (existsSync(path.join(at, '.git'))) return at;
    if (path.dirname(at) === at) return null;
  }
}

/**
 * The real folder TEAM_JOURNEY_SHOTS_DIR names, or an error saying why it is
 * refused: unset, relative, going up with '..', leading nowhere real, or
 * really inside a git checkout. It makes nothing.
 */
export function privateFolder(raw: string | undefined): string {
  const dir = raw?.trim() ?? '';
  if (!dir || !path.isAbsolute(dir)) {
    throw new Error(`Set TEAM_JOURNEY_SHOTS_DIR to an absolute folder outside every git checkout (${README}).`);
  }
  if (dir.split(/[\\/]/).includes('..')) {
    throw new Error(`TEAM_JOURNEY_SHOTS_DIR must not go up with '..': name the folder itself (${README}).`);
  }
  let real: string;
  try {
    real = realBackingPath(dir);
  } catch (e) {
    throw new Error(`TEAM_JOURNEY_SHOTS_DIR ${(e as Error).message}: pick a private folder (${README}).`);
  }
  const checkout = checkoutAround(real);
  if (checkout) {
    const via = real === path.resolve(dir) ? '' : ` (${dir} really is ${real})`;
    throw new Error(
      `TEAM_JOURNEY_SHOTS_DIR is inside the git checkout ${checkout}${via}: screenshots and the report stay out of every repository (temper-ai is public). Pick a private folder.`,
    );
  }
  return real;
}
