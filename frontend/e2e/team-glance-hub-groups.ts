/**
 * Which You/Temper hub batches must keep Design's D81 bars, and which are a
 * known gap Design was asked about. team-glance-map.spec.ts flies one batch
 * on each map story, then routes every group below with the page's own
 * router (hubPaths) on the page's own measured map, in Node.
 *
 * Must pass (D81's bars: 16 px from every count, nothing within 18 px beside
 * a line, every crossing hopped):
 * - every member alone, and any two at once, in either order, at 1024 and 1440;
 * - any three at once, in any order, at 1440;
 * - a whole team of three, in any order, at both widths.
 *
 * Known D81 gap, Design asked (2026-10-09): Design's hub routing, ported
 * exactly, can't keep the bars for some groups of three at 1024 on maps of 4
 * to 6 members, and for all members at once on those maps. Each is pinned
 * below with its faults; a group not listed must pass, and a listed one may
 * not get worse. Why, as measured: the 32 px gap under the hub holds one lane,
 * so lines leaving it run on top of each other; each side of the map has one
 * lane, so a second line sent round the map shares it; and a crossing in that
 * gap has no room for its hop. Groups of three and all members at once are
 * kept apart, so moving the line Design draws (no hub lines for four or more,
 * D82) is a one-line change.
 */
import { describeGap, hubGaps, routeHubGroup, type HubGap, type HubReport } from './team-glance-map-measure';

export type HubInput = Omit<HubReport, 'routes'>;
export type HubScope = 'must pass' | 'groups of 3' | 'all at once';

export interface HubGroup {
  scope: HubScope;
  /** The receivers, in the order the batch routes them. */
  to: string[];
}

/** A known gap: the map story, the window width, the receivers in routing order, and every fault (describeGap). */
export interface KnownGap {
  map: string;
  width: number;
  to: string[];
  gaps: string[];
}

const L = ['lead', 'builder', 'checker', 'designer', 'tester', 'writer'];
/** The first n members, in map order. */
const first = (n: number) => L.slice(0, n);

/**
 * Known D81 gap, Design asked: groups of three at 1024 on maps of 4 to 6
 * members (receivers in map order), the same in both themes. Every one has
 * the leader in it: its line takes the lane under the hub first.
 */
export const KNOWN_D81_GAP_GROUPS_OF_3: KnownGap[] = [
  { map: 'map_members_4', width: 1024, to: ['lead', 'builder', 'checker'], gaps: ['checker: 1 crossings, 0 hops, 1 unhopped'] },
  {
    map: 'map_members_4',
    width: 1024,
    to: ['lead', 'checker', 'designer'],
    gaps: ['designer: runs 30 px beside hub>checker, 0 px apart', 'designer: runs 238 px beside hub>checker, 0 px apart'],
  },
  { map: 'map_members_5', width: 1024, to: ['lead', 'builder', 'checker'], gaps: ['checker: 2 crossings, 1 hops, 1 unhopped'] },
  {
    map: 'map_members_5',
    width: 1024,
    to: ['lead', 'checker', 'designer'],
    gaps: ['designer: runs 30 px beside hub>checker, 0 px apart', 'designer: runs 238 px beside hub>checker, 0 px apart'],
  },
  {
    map: 'map_members_5',
    width: 1024,
    to: ['lead', 'checker', 'tester'],
    gaps: ['tester: runs 30 px beside hub>checker, 0 px apart', 'tester: runs 238 px beside hub>checker, 0 px apart'],
  },
  {
    map: 'map_members_5',
    width: 1024,
    to: ['lead', 'designer', 'tester'],
    gaps: ['tester: runs 15 px beside hub>designer, 0 px apart', 'tester: runs 238 px beside hub>designer, 0 px apart'],
  },
  { map: 'map_members_6', width: 1024, to: ['lead', 'builder', 'checker'], gaps: ['checker: 1 crossings, 0 hops, 1 unhopped'] },
  { map: 'map_members_6', width: 1024, to: ['lead', 'checker', 'designer'], gaps: ['designer: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_members_6', width: 1024, to: ['lead', 'checker', 'tester'], gaps: ['tester: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_members_6', width: 1024, to: ['lead', 'checker', 'writer'], gaps: ['writer: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_quiet', width: 1024, to: ['lead', 'builder', 'checker'], gaps: ['checker: 2 crossings, 1 hops, 1 unhopped'] },
  { map: 'map_quiet', width: 1024, to: ['lead', 'checker', 'designer'], gaps: ['designer: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_quiet', width: 1024, to: ['lead', 'checker', 'tester'], gaps: ['tester: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_quiet', width: 1024, to: ['lead', 'checker', 'writer'], gaps: ['writer: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_fanout_before', width: 1024, to: ['lead', 'builder', 'checker'], gaps: ['checker: 2 crossings, 1 hops, 1 unhopped'] },
  { map: 'map_fanout_before', width: 1024, to: ['lead', 'builder', 'designer'], gaps: ['designer: 1 crossings, 0 hops, 1 unhopped'] },
  { map: 'map_fanout_before', width: 1024, to: ['lead', 'checker', 'designer'], gaps: ['designer: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_fanout_before', width: 1024, to: ['lead', 'checker', 'tester'], gaps: ['tester: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_fanout_before', width: 1024, to: ['lead', 'checker', 'writer'], gaps: ['writer: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_fanout_before', width: 1024, to: ['lead', 'designer', 'tester'], gaps: ['tester: runs 30 px beside hub>designer, 0 px apart'] },
  { map: 'map_fanout_before', width: 1024, to: ['lead', 'designer', 'writer'], gaps: ['writer: runs 30 px beside hub>designer, 0 px apart'] },
  { map: 'map_burst', width: 1024, to: ['lead', 'builder', 'checker'], gaps: ['checker: 3 crossings, 2 hops, 1 unhopped'] },
  { map: 'map_burst', width: 1024, to: ['lead', 'checker', 'designer'], gaps: ['designer: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_burst', width: 1024, to: ['lead', 'checker', 'tester'], gaps: ['tester: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_burst', width: 1024, to: ['lead', 'checker', 'writer'], gaps: ['writer: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_fanout', width: 1024, to: ['lead', 'builder', 'checker'], gaps: ['checker: 3 crossings, 2 hops, 1 unhopped'] },
  { map: 'map_fanout', width: 1024, to: ['lead', 'checker', 'designer'], gaps: ['designer: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_fanout', width: 1024, to: ['lead', 'checker', 'tester'], gaps: ['tester: runs 30 px beside hub>checker, 0 px apart'] },
  { map: 'map_fanout', width: 1024, to: ['lead', 'checker', 'writer'], gaps: ['writer: runs 30 px beside hub>checker, 0 px apart'] },
];

/**
 * Known D81 gap, Design asked: all members at once on maps of 4 to 6 members
 * (receivers in map order), at both widths, the same in both themes.
 */
export const KNOWN_D81_GAP_ALL_AT_ONCE: KnownGap[] = [
  {
    map: 'map_members_4',
    width: 1024,
    to: first(4),
    gaps: [
      'checker: 1 crossings, 0 hops, 1 unhopped',
      'designer: runs 30 px beside hub>checker, 0 px apart',
      'designer: runs 238 px beside hub>checker, 0 px apart',
    ],
  },
  {
    map: 'map_members_5',
    width: 1024,
    to: first(5),
    gaps: [
      'checker: 2 crossings, 1 hops, 1 unhopped',
      'designer: runs 30 px beside hub>checker, 0 px apart',
      'designer: runs 238 px beside hub>checker, 0 px apart',
      'tester: runs 30 px beside hub>checker, 0 px apart',
      'tester: runs 238 px beside hub>checker, 0 px apart',
    ],
  },
  {
    map: 'map_members_6',
    width: 1024,
    to: first(6),
    gaps: [
      'checker: 1 crossings, 0 hops, 1 unhopped',
      'designer: runs 30 px beside hub>checker, 0 px apart',
      'tester: runs 71 px beside hub>checker, 0 px apart',
      'tester: runs 245 px beside hub>checker, 0 px apart',
      'writer: runs 144 px beside hub>checker, 0 px apart',
      'writer: runs 63.3 px beside hub>designer, 0 px apart',
      'writer: runs 100 px beside hub>designer, 0 px apart',
      'writer: runs 30 px beside hub>tester, 0 px apart',
      'writer: 3 crossings, 2 hops, 1 unhopped',
    ],
  },
  {
    map: 'map_quiet',
    width: 1024,
    to: first(6),
    gaps: [
      'checker: 2 crossings, 1 hops, 1 unhopped',
      'designer: runs 30 px beside hub>checker, 0 px apart',
      'tester: runs 71 px beside hub>checker, 0 px apart',
      'tester: runs 245 px beside hub>checker, 0 px apart',
      'writer: runs 70.7 px beside hub>lead, 0 px apart',
      'writer: runs 144 px beside hub>checker, 0 px apart',
      'writer: runs 63.3 px beside hub>designer, 0 px apart',
      'writer: runs 30 px beside hub>tester, 0 px apart',
      'writer: 7 crossings, 6 hops, 1 unhopped',
    ],
  },
  {
    map: 'map_fanout_before',
    width: 1024,
    to: first(6),
    gaps: [
      'checker: 2 crossings, 1 hops, 1 unhopped',
      'designer: runs 30 px beside hub>checker, 0 px apart',
      'tester: runs 30 px beside hub>checker, 0 px apart',
      'tester: runs 177.5 px beside hub>checker, 0 px apart',
      'writer: runs 70.7 px beside hub>lead, 0 px apart',
      'writer: runs 111.7 px beside hub>checker, 0 px apart',
      'writer: runs 63.3 px beside hub>designer, 0 px apart',
      'writer: 7 crossings, 6 hops, 1 unhopped',
    ],
  },
  {
    map: 'map_burst',
    width: 1024,
    to: first(6),
    gaps: [
      'checker: 3 crossings, 2 hops, 1 unhopped',
      'designer: runs 30 px beside hub>checker, 0 px apart',
      'tester: runs 30 px beside hub>checker, 0 px apart',
      'tester: runs 232 px beside hub>checker, 0 px apart',
      'writer: runs 111.7 px beside hub>checker, 0 px apart',
      'writer: runs 63.3 px beside hub>designer, 0 px apart',
      'writer: runs 100 px beside hub>designer, 0 px apart',
      'writer: 4 crossings, 3 hops, 1 unhopped',
    ],
  },
  {
    map: 'map_fanout',
    width: 1024,
    to: first(6),
    gaps: [
      'checker: 3 crossings, 2 hops, 1 unhopped',
      'designer: runs 30 px beside hub>checker, 0 px apart',
      'tester: runs 30 px beside hub>checker, 0 px apart',
      'tester: runs 198 px beside hub>checker, 0 px apart',
      'writer: runs 70.7 px beside hub>lead, 0 px apart',
      'writer: runs 111.7 px beside hub>checker, 0 px apart',
      'writer: runs 63.3 px beside hub>designer, 0 px apart',
      'writer: 6 crossings, 5 hops, 1 unhopped',
    ],
  },
  { map: 'map_members_4', width: 1440, to: first(4), gaps: ['designer: 1 crossings, 0 hops, 1 unhopped'] },
  {
    map: 'map_members_5',
    width: 1440,
    to: first(5),
    gaps: [
      'designer: 2 crossings, 1 hops, 1 unhopped',
      'tester: runs 30.3 px beside hub>designer, 0 px apart',
      'tester: runs 178 px beside hub>designer, 0 px apart',
    ],
  },
  {
    map: 'map_members_6',
    width: 1440,
    to: first(6),
    gaps: [
      'designer: 3 crossings, 2 hops, 1 unhopped',
      'tester: runs 95.3 px beside hub>designer, 0 px apart',
      'tester: runs 177 px beside hub>designer, 0 px apart',
      'writer: runs 131.3 px beside hub>checker, 0 px apart',
      'writer: runs 111 px beside hub>designer, 0 px apart',
      'writer: runs 30 px beside hub>tester, 0 px apart',
      'writer: 5 crossings, 4 hops, 1 unhopped',
    ],
  },
  {
    map: 'map_quiet',
    width: 1440,
    to: first(6),
    gaps: [
      'designer: 2 crossings, 1 hops, 1 unhopped',
      'tester: runs 95.3 px beside hub>designer, 0 px apart',
      'tester: runs 177 px beside hub>designer, 0 px apart',
      'writer: runs 131.3 px beside hub>checker, 0 px apart',
      'writer: runs 111 px beside hub>designer, 0 px apart',
      'writer: runs 30 px beside hub>tester, 0 px apart',
      'writer: 4 crossings, 3 hops, 1 unhopped',
    ],
  },
  {
    map: 'map_fanout_before',
    width: 1440,
    to: first(6),
    gaps: [
      'designer: 1 crossings, 0 hops, 1 unhopped',
      'tester: runs 95.3 px beside hub>designer, 0 px apart',
      'tester: runs 157.5 px beside hub>designer, 0 px apart',
      'writer: runs 131.3 px beside hub>checker, 0 px apart',
      'writer: runs 111 px beside hub>designer, 0 px apart',
      'writer: runs 30 px beside hub>tester, 0 px apart',
      'writer: 4 crossings, 3 hops, 1 unhopped',
    ],
  },
  {
    map: 'map_burst',
    width: 1440,
    to: first(6),
    gaps: [
      'designer: 4 crossings, 3 hops, 1 unhopped',
      'tester: runs 95.3 px beside hub>designer, 0 px apart',
      'tester: runs 177 px beside hub>designer, 0 px apart',
      'writer: runs 131.3 px beside hub>checker, 0 px apart',
      'writer: runs 111 px beside hub>designer, 0 px apart',
      'writer: runs 30 px beside hub>tester, 0 px apart',
      'writer: 5 crossings, 4 hops, 1 unhopped',
    ],
  },
  {
    map: 'map_fanout',
    width: 1440,
    to: first(6),
    gaps: [
      'designer: 4 crossings, 3 hops, 1 unhopped',
      'tester: runs 95.3 px beside hub>designer, 0 px apart',
      'tester: runs 178 px beside hub>designer, 0 px apart',
      'writer: runs 131.3 px beside hub>checker, 0 px apart',
      'writer: runs 111 px beside hub>designer, 0 px apart',
      'writer: runs 30 px beside hub>tester, 0 px apart',
      'writer: 5 crossings, 4 hops, 1 unhopped',
    ],
  },
];

const orders = (list: string[]): string[][] =>
  list.length <= 1 ? [list] : list.flatMap((first, i) => orders([...list.slice(0, i), ...list.slice(i + 1)]).map((rest) => [first, ...rest]));

function subsets(list: string[], k: number, from = 0, acc: string[] = []): string[][] {
  if (acc.length === k) return [acc];
  return list.slice(from).flatMap((item, i) => subsets(list, k, from + i + 1, [...acc, item]));
}

/** Every batch checked on a map of `members` (map order) at window width `width`. */
export function hubGroupsFor(members: string[], width: number): HubGroup[] {
  const groups: HubGroup[] = [];
  for (const k of [1, 2, 3]) {
    if (k > members.length) break;
    for (const set of subsets(members, k)) {
      if (k < 3 || members.length === 3 || width >= 1440) {
        for (const to of orders(set)) groups.push({ scope: 'must pass', to });
      } else {
        groups.push({ scope: 'groups of 3', to: set });
      }
    }
  }
  if (members.length >= 4) groups.push({ scope: 'all at once', to: members });
  return groups;
}

const TOLERANCE = 0.5;

function parseGap(text: string): HubGap {
  let m = /^(\S+): ([\d.]+) px from a count$/.exec(text);
  if (m) return { to: m[1], kind: 'count', clear: Number(m[2]) };
  m = /^(\S+): runs ([\d.]+) px beside (\S+), ([\d.]+) px apart$/.exec(text);
  if (m) return { to: m[1], kind: 'beside', line: m[3], gap: Number(m[4]), run: Number(m[2]) };
  m = /^(\S+): (\d+) crossings, (\d+) hops, (\d+) unhopped$/.exec(text);
  if (m) return { to: m[1], kind: 'unhopped', crossings: Number(m[2]), hops: Number(m[3]), unhopped: Number(m[4]) };
  throw new Error(`not a hub gap: ${text}`);
}

/** Where `found` is worse than `known`: a fault of a new kind, place or line, or a worse number (0.5 px slack). */
function worseThan(found: HubGap[], known: HubGap[]): string[] {
  const keyOf = (g: HubGap) => `${g.to} ${g.kind}${g.kind === 'beside' ? ` ${g.line}` : ''}`;
  const byKey = (list: HubGap[]) => {
    const map = new Map<string, HubGap[]>();
    for (const g of list) map.set(keyOf(g), [...(map.get(keyOf(g)) ?? []), g]);
    return map;
  };
  const was = byKey(known);
  const out: string[] = [];
  for (const [key, now] of byKey(found)) {
    const before = was.get(key) ?? [];
    if (now.length > before.length) {
      out.push(`${key}: ${now.length} now, ${before.length} pinned`);
      continue;
    }
    if (now[0].kind === 'beside') {
      const runs = (list: HubGap[]) => (list as Array<Extract<HubGap, { kind: 'beside' }>>).slice().sort((a, b) => b.run - a.run);
      const [n, b] = [runs(now), runs(before)];
      n.forEach((g, i) => {
        if (g.run > b[i].run + TOLERANCE || g.gap < b[i].gap - TOLERANCE) out.push(`${describeGap(g)} (pinned: ${describeGap(b[i])})`);
      });
    } else if (now[0].kind === 'count') {
      const [g, b] = [now[0] as Extract<HubGap, { kind: 'count' }>, before[0] as Extract<HubGap, { kind: 'count' }>];
      if (g.clear < b.clear - TOLERANCE) out.push(`${describeGap(g)} (pinned: ${describeGap(b)})`);
    } else {
      const [g, b] = [now[0] as Extract<HubGap, { kind: 'unhopped' }>, before[0] as Extract<HubGap, { kind: 'unhopped' }>];
      if (g.unhopped > b.unhopped) out.push(`${describeGap(g)} (pinned: ${describeGap(b)})`);
    }
  }
  return out;
}

export function knownGap(map: string, width: number, group: HubGroup): KnownGap | undefined {
  const list = group.scope === 'groups of 3' ? KNOWN_D81_GAP_GROUPS_OF_3 : group.scope === 'all at once' ? KNOWN_D81_GAP_ALL_AT_ONCE : [];
  return list.find((k) => k.map === map && k.width === width && k.to.join() === group.to.join());
}

export interface HubGroupResult extends HubGroup {
  gaps: string[];
  /** Pinned as a known D81 gap. */
  known: boolean;
}

/**
 * Route every group of `hubGroupsFor` on one measured map with hubPaths and
 * judge it: what fails (nothing is the bar), with each group's faults.
 */
export function checkHubGroups(map: string, width: number, input: HubInput, members: string[]): { results: HubGroupResult[]; problems: string[] } {
  const results: HubGroupResult[] = [];
  const problems: string[] = [];
  for (const group of hubGroupsFor(members, width)) {
    const found = hubGaps(routeHubGroup(input, group.to));
    const pinned = knownGap(map, width, group);
    const label = `${map} at ${width}, ${group.scope} [${group.to.join(', ')}]`;
    const gaps = found.map(describeGap);
    results.push({ ...group, gaps, known: Boolean(pinned) });
    if (!pinned) {
      if (found.length) problems.push(`${label}: ${gaps.join('; ')}`);
      continue;
    }
    if (!found.length) {
      problems.push(`${label}: a known D81 gap no longer there; drop it from the list`);
      continue;
    }
    const worse = worseThan(found, pinned.gaps.map(parseGap));
    if (worse.length) problems.push(`${label}: worse than pinned: ${worse.join('; ')}; now ${JSON.stringify(gaps)}`);
  }
  return { results, problems };
}
