/**
 * Which You/Temper hub batches draw lines and must keep Design's D81 bars.
 * team-glance-map.spec.ts flies one batch on each map story, then routes
 * every group below with the page's own router (hubPaths) on the page's own
 * measured map, in Node.
 *
 * Must pass (D81's bars: 16 px from every count, nothing within 18 px beside
 * a line, every crossing hopped): every member alone, and any two at once,
 * in either order, at 1024 and 1440.
 *
 * Three or more members in the same second draw no lines at all: the
 * sender's tag and the receiving rings light up instead, at every width
 * (Design D82, threshold 3 from 21:10 on 2026-10-09). That closes #19's two
 * pinned gap lists (groups of three at 1024 on maps of 4 to 6 members, and
 * all members at once): no known D81 gap is left, so every group here must
 * pass. The light-up has its own check in team-glance-map.spec.ts.
 */
import { HUB_BATCH_MIN } from '../src/lib/teamGlance';
import { describeGap, hubGaps, routeHubGroup, type HubReport } from './team-glance-map-measure';

export type HubInput = Omit<HubReport, 'routes'>;

export interface HubGroup {
  /** The receivers, in the order the batch routes them. */
  to: string[];
}

const orders = (list: string[]): string[][] =>
  list.length <= 1 ? [list] : list.flatMap((first, i) => orders([...list.slice(0, i), ...list.slice(i + 1)]).map((rest) => [first, ...rest]));

function subsets(list: string[], k: number, from = 0, acc: string[] = []): string[][] {
  if (acc.length === k) return [acc];
  return list.slice(from).flatMap((item, i) => subsets(list, k, from + i + 1, [...acc, item]));
}

/** Every batch that draws lines on a map of `members` (map order): one or two receivers, in every order. */
export function hubGroupsFor(members: string[]): HubGroup[] {
  const groups: HubGroup[] = [];
  for (let k = 1; k < HUB_BATCH_MIN && k <= members.length; k++) {
    for (const set of subsets(members, k)) for (const to of orders(set)) groups.push({ to });
  }
  return groups;
}

export interface HubGroupResult extends HubGroup {
  gaps: string[];
}

/**
 * Route every group of `hubGroupsFor` on one measured map with hubPaths and
 * judge it: what fails (nothing is the bar), with each group's faults.
 */
export function checkHubGroups(map: string, width: number, input: HubInput, members: string[]): { results: HubGroupResult[]; problems: string[] } {
  const results: HubGroupResult[] = [];
  const problems: string[] = [];
  for (const group of hubGroupsFor(members)) {
    const gaps = hubGaps(routeHubGroup(input, group.to)).map(describeGap);
    results.push({ ...group, gaps });
    if (gaps.length) problems.push(`${map} at ${width} [${group.to.join(', ')}]: ${gaps.join('; ')}`);
  }
  return { results, problems };
}
