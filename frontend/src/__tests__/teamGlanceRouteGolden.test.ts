/**
 * The glance map router's fixed outputs (teamGlanceRoute: mapGeometry and
 * hubPaths), so a router change that moves a drawn line, a count or a
 * You/Temper line can't pass unseen. teamGlanceMap.test.ts checks what a line
 * must do; this file checks that the lines stay where they are.
 *
 * Twenty made-up teams, each laid out as the page's grid lays it out at 1024
 * and 1440 px (mapSlots: the leader in the middle, the others clockwise from
 * the top left; a row as tall as its tallest card, D78), with fixed card
 * sizes, so no font is measured. Each has one to four drawn lines (MAX_LINES)
 * with counts as the page routes them (badgeCount). The teams were picked by
 * a coverage search over 4000 random teams, so that between them they reach
 * the branches listed in REACHES.
 *
 * Each output is written as canonical JSON (Maps as entry lists; -0, NaN and
 * Infinity spelled out) and compared, by its sha256 and its number of paths,
 * with ROUTED below. A change that means to move lines: check the map in the
 * browser first, then replace the entries with the list the failure prints.
 */
import { describe, expect, it } from 'vitest';
import { hubPaths, mapGeometry, type HubPath, type MapGeometry, type MapLineIn, type Rect } from '@/lib/teamGlanceRoute';

type Width = 1024 | 1440;

/** The page's map grid at each width: the box's width, each column's x and width, a card's height by its size. */
const GRID: Record<Width, { box: number; cols: ReadonlyArray<readonly [x: number, w: number]>; heights: readonly number[] }> = {
  1024: {
    box: 742,
    cols: [
      [36, 180.65625],
      [280.65625, 180.671875],
      [525.328125, 180.671875],
    ],
    heights: [172.75, 195.25, 217.75, 241.75],
  },
  1440: {
    box: 1158,
    cols: [
      [53.65625, 284],
      [436.984375, 284],
      [820.328125, 284],
    ],
    heights: [150.25, 154.25, 172.75, 176.75],
  },
};
/** The You/Temper corner: no line crosses it. */
const HUB: Rect = { x: 10, y: 8, w: 256, h: 24 };
const TOP = 64;
const ROW_GAP = 72;
const BOTTOM = 64;

interface Team {
  /** The leader first, then the others in member order. */
  members: string[];
  /** Each card's size: an index into the width's heights. */
  sizes: number[];
  /** The drawn pairs, newest first: [a, b, count] with a before b. */
  lines: Array<[a: string, b: string, count: number]>;
}

/** The cards where the page's grid puts them, and the map's box. */
function layout(team: Team, width: Width): { cards: Map<string, Rect>; box: { w: number; h: number } } {
  const g = GRID[width];
  const [leader, ...others] = team.members;
  const rows = Math.max(1, Math.ceil(others.length / 2));
  const ring: Array<{ col: 0 | 2; row: number }> = [{ col: 0, row: 0 }];
  for (let r = 0; r < rows; r += 1) ring.push({ col: 2, row: r });
  for (let r = rows - 1; r >= 1; r -= 1) ring.push({ col: 0, row: r });
  const own = (i: number) => g.heights[team.sizes[i]];
  const rowH = new Array<number>(rows).fill(0);
  others.forEach((_, i) => {
    rowH[ring[i].row] = Math.max(rowH[ring[i].row], own(i + 1));
  });
  // One row: the leader shares it and stretches with it. More: the leader keeps its height, centred.
  if (rows === 1) rowH[0] = Math.max(rowH[0], own(0));
  const rowY: number[] = [];
  let y = TOP;
  for (const h of rowH) {
    rowY.push(y);
    y += h + ROW_GAP;
  }
  const bottom = rowY[rows - 1] + rowH[rows - 1];
  const lh = rows === 1 ? rowH[0] : own(0);
  const cards = new Map<string, Rect>([[leader, { x: g.cols[1][0], y: TOP + (bottom - TOP - lh) / 2, w: g.cols[1][1], h: lh }]]);
  others.forEach((name, i) => {
    const { col, row } = ring[i];
    cards.set(name, { x: g.cols[col][0], y: rowY[row], w: g.cols[col][1], h: rowH[row] });
  });
  return { cards, box: { w: g.box, h: Math.round(bottom + BOTTOM) } };
}

const TEAMS: Team[] = [
  { members: ['dov', 'oona', 'ada', 'kit', 'finn'], sizes: [3, 3, 3, 3, 2], lines: [['ada', 'dov', 100], ['ada', 'finn', 10], ['kit', 'oona', 1], ['ada', 'oona', 1000]] },
  { members: ['juno', 'dov', 'ada', 'finn', 'pim', 'lars'], sizes: [2, 3, 2, 0, 2, 3], lines: [['ada', 'lars', 1000], ['dov', 'juno', 1000], ['finn', 'juno', 1000], ['dov', 'pim', 1000]] },
  { members: ['esme', 'oona', 'juno', 'gus', 'bram', 'mira'], sizes: [3, 1, 1, 3, 3, 1], lines: [['esme', 'gus', 10], ['bram', 'oona', 10], ['esme', 'oona', 1]] },
  { members: ['nell', 'cleo', 'juno', 'ada', 'gus', 'esme'], sizes: [3, 1, 2, 0, 1, 1], lines: [['gus', 'juno', 1000], ['juno', 'nell', 1000]] },
  { members: ['pim', 'cleo', 'ada', 'oona'], sizes: [3, 0, 1, 1], lines: [['ada', 'cleo', 100]] },
  { members: ['bram', 'ada', 'esme', 'oona'], sizes: [3, 0, 1, 2], lines: [['bram', 'oona', 1000], ['ada', 'esme', 1], ['ada', 'bram', 10], ['ada', 'oona', 1000]] },
  { members: ['gus', 'ada', 'pim', 'lars'], sizes: [3, 2, 0, 1], lines: [['ada', 'lars', 10], ['gus', 'pim', 10], ['ada', 'gus', 1]] },
  { members: ['bram', 'ivo', 'esme'], sizes: [3, 1, 2], lines: [['esme', 'ivo', 100], ['bram', 'ivo', 10], ['bram', 'esme', 1]] },
  { members: ['lars', 'ada'], sizes: [3, 2], lines: [['ada', 'lars', 1]] },
  { members: ['cleo', 'ada', 'esme', 'hana', 'juno', 'mira'], sizes: [3, 2, 3, 2, 0, 2], lines: [['ada', 'mira', 1], ['cleo', 'juno', 10], ['cleo', 'mira', 1000], ['ada', 'esme', 10]] },
  { members: ['cleo', 'juno', 'hana', 'mira', 'pim', 'dov'], sizes: [3, 1, 3, 1, 0, 0], lines: [['mira', 'pim', 1000], ['dov', 'juno', 10], ['cleo', 'dov', 10]] },
  { members: ['bram', 'finn', 'juno', 'cleo', 'ivo', 'dov'], sizes: [3, 3, 2, 0, 3, 3], lines: [['bram', 'dov', 10]] },
  { members: ['finn', 'nell', 'esme', 'oona', 'hana'], sizes: [2, 0, 2, 3, 1], lines: [['esme', 'oona', 10], ['finn', 'oona', 1], ['esme', 'finn', 1000], ['hana', 'oona', 10]] },
  { members: ['cleo', 'juno', 'lars', 'finn', 'bram'], sizes: [3, 0, 0, 0, 2], lines: [['bram', 'juno', 10], ['cleo', 'juno', 100], ['bram', 'finn', 1]] },
  { members: ['pim', 'juno', 'oona', 'hana', 'gus'], sizes: [3, 3, 2, 3, 1], lines: [['oona', 'pim', 10], ['hana', 'juno', 10]] },
  { members: ['gus', 'nell', 'pim', 'kit', 'lars'], sizes: [2, 1, 2, 0, 3], lines: [['gus', 'lars', 10]] },
  { members: ['gus', 'hana', 'juno', 'kit'], sizes: [3, 1, 0, 3], lines: [['gus', 'kit', 100], ['juno', 'kit', 1]] },
  { members: ['finn', 'nell', 'pim'], sizes: [3, 3, 2], lines: [['nell', 'pim', 10], ['finn', 'nell', 10]] },
  { members: ['oona', 'ada', 'mira'], sizes: [3, 0, 0], lines: [['mira', 'oona', 1]] },
  { members: ['cleo', 'juno', 'mira', 'nell', 'pim', 'bram'], sizes: [3, 2, 0, 1, 2, 2], lines: [['bram', 'pim', 1], ['nell', 'pim', 10], ['bram', 'nell', 10], ['juno', 'pim', 1]] },
];

/** The You/Temper receivers routed on each map: each member alone, each with the next one, and all of them. */
function hubGroups(members: string[]): string[][] {
  const out = members.map((m) => [m]);
  for (let i = 0; i + 1 < members.length; i += 1) out.push([members[i], members[i + 1]]);
  if (members.length > 2) out.push([...members]);
  return out;
}

interface Routed {
  id: string;
  map: MapGeometry;
  hub: Array<[receivers: string[], paths: Map<string, HubPath>]>;
}

function route(): Routed[] {
  return TEAMS.flatMap((team, i) =>
    ([1024, 1440] as const).map((width) => {
      const { cards, box } = layout(team, width);
      const lines: MapLineIn[] = team.lines.map(([a, b, count]) => ({ key: `${a}|${b}`, a, b, count }));
      const map = mapGeometry(lines, cards, [HUB], box);
      // What the page routes a batch's You/Temper lines round (TeamMap's hubInput): the drawn routes before hops
      // and the counts drawn.
      const input = {
        rects: cards,
        hub: HUB,
        lines: map.lines.map((l) => l.route),
        badges: map.badges.filter((b) => !b.forced).map((b) => b.box),
        width: box.w,
        height: box.h,
      };
      const hub = hubGroups(team.members).map((g): [string[], Map<string, HubPath>] => [g, hubPaths(g, input)]);
      return { id: `${String(i + 1).padStart(2, '0')} ${width}`, map, hub };
    }),
  );
}

let routed: Routed[] | null = null;
const routes = () => (routed ??= route());

/** JSON with Maps as entry lists and -0, NaN and Infinity spelled out, so none can hide. */
function canon(v: unknown): string {
  return JSON.stringify(v, (_k, x: unknown) => {
    if (typeof x === 'number') {
      if (Object.is(x, -0)) return '-0';
      if (!Number.isFinite(x)) return String(x);
      return x;
    }
    if (x instanceof Map) return { map: [...x.entries()] };
    if (x instanceof Set) return { set: [...x.values()] };
    return x;
  });
}

async function sha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** What the teams reach between them (the branches they were picked for); a team that stops reaching one is a smaller test. */
const REACHES = [
  'straight',
  'routed',
  'hop',
  'unhopped',
  'beside a card',
  'near a line',
  'D83 re-route',
  'tier 1',
  'tier 2',
  'tier 3',
  'tier 4',
  'tier 5',
  'badge 28',
  'badge 34',
  'badge 43',
  'badge 52',
  'hub try 1',
  'hub try 2',
  'hub try 3',
  'hub hop',
  'hub unhopped',
];

function reached(r: Routed): string[] {
  const out = r.map.lines.flatMap((l) => [
    l.straight ? 'straight' : 'routed',
    ...(l.hops > 0 ? ['hop'] : []),
    ...(l.unhopped > 0 ? ['unhopped'] : []),
    ...(l.hug > 0.5 ? ['beside a card'] : []),
  ]);
  out.push(...r.map.badges.flatMap((b) => [`tier ${b.tier}`, `badge ${b.box.w}`]));
  if (r.map.near > 0) out.push('near a line');
  if (r.map.rerouted) out.push('D83 re-route');
  for (const [, paths] of r.hub)
    for (const p of paths.values()) out.push(`hub try ${p.try}`, ...(p.hops > 0 ? ['hub hop'] : []), ...(p.unhopped > 0 ? ['hub unhopped'] : []));
  return out;
}

type Listed = Record<string, readonly [paths: number, sha256: string]>;

/** Each output's paths (a map's drawn lines; then its You/Temper lines, all groups) and its canonical JSON's sha256. */
const ROUTED: Listed = {
  '01 1024 map': [4, 'd0af0f3d9ef6cbd43a4436c9c2738cbb308ecd833b7b11306fed98728e327f5e'],
  '01 1024 hub': [18, 'a7919ca2a235700fdb05e39dc5ebd45428182a0458a423c94045911568e0260f'],
  '01 1440 map': [4, '4c70e9e02b1b2576c49f79cc52adb08863631274e9ebecad116af5608385979f'],
  '01 1440 hub': [18, '03b64963980d38710c1e22e43b70bf40869df5e4f77a9bef0e7225f98bc47077'],
  '02 1024 map': [4, 'd197997fa3fe9fbb0af145615730d12d3d5e2114f10894d1324e1c8dec5065fb'],
  '02 1024 hub': [22, '08ca1c757c11a2042d498376ce42a07e2641489d5e6886d41730afd8e1cea862'],
  '02 1440 map': [4, '57e5723e17d25741c7ade32266ee1dd263a4b5a3d85ced335e11d23be2bc3f0b'],
  '02 1440 hub': [22, '0ebe6e03ae69dd45f40b510b0b29bb7c3344e17662cc4076b5e0062ec3ab63d2'],
  '03 1024 map': [3, '8053569b41da7b42a581312071b4802d5997ca084a56f8677008b70645227675'],
  '03 1024 hub': [22, '2805a92d9c3f31a9e89668a9ff9d32aacf0671415422e72640fef9ab76255a2f'],
  '03 1440 map': [3, 'a240b9ac105ca31536536e82154f206fde7efd2bdd4d48ddabc2b49eb3c00539'],
  '03 1440 hub': [22, '2b3852e8ada441f78efa4c4eb419c0aeb9446bb928924d7eda49e92374e4e194'],
  '04 1024 map': [2, 'd7cfff0be457526f2ca5baf1937ab424205fe8dfec9d3d238a528fa91d50392e'],
  '04 1024 hub': [22, 'a2df9b4ac7eba01e1c9692f19c87a726ed770d6581935fff24e82cc46baa7bd1'],
  '04 1440 map': [2, 'dc25bf65ee3bf4ab3703e1f9232df95b91b5d3cc638106cead467bfb5bef4af4'],
  '04 1440 hub': [22, '48df97524a5343c0f5f8595f75754fb41d1b172121d8cd611d1b4faa9619f77f'],
  '05 1024 map': [1, '78f310c31b5b953b9b4fc641bbead03a1f293bebb3d1a304632b24b81c846a38'],
  '05 1024 hub': [14, '8c97efa304810b7a9fefcbc793e2d9b8376febeff5452382afee78a9c69a6dde'],
  '05 1440 map': [1, '9f41c008bad03f009c79d3925eb2b15bcd7a442e685ab8700fd5fe0d8d27d61f'],
  '05 1440 hub': [14, '6eb4dd51094dd06ad60e75849a6f52a03f372b8a92902c521e84d447ddda379a'],
  '06 1024 map': [4, 'ad956b0c00bb6ec38b1c1b3ef05b8127d139ede6dac245235229a071e6cf8139'],
  '06 1024 hub': [14, 'beaaeac4a65ba23a9911b0163343d0818ec943310f76219260c8a46d6a64520f'],
  '06 1440 map': [4, '4edf1f2d77d9d35d31771577c819de39fc4cab5cc6cfb05cdf6ea8774455b7b7'],
  '06 1440 hub': [14, 'ae181b741cc7ed84fcc313bc839ca714ccbec03f61a51f4816d2fb2cf3526e74'],
  '07 1024 map': [3, '47ff9f6e00f74c93c58372739719437324ea27058f50712a9a8e4947e3918c6a'],
  '07 1024 hub': [14, 'a5d8aa2c75a7c00cc2796127846d07dd6389d706c7a1e53b6b3688e86f3fc13b'],
  '07 1440 map': [3, '6b3ee3f2ea0e6c74b68e4ab6edde59b839376c271d542f3c55ae4ed39a7ddd06'],
  '07 1440 hub': [14, '6e44989864bad4c2897b54914d12e1757afeaab0852d2d27886c841749b66896'],
  '08 1024 map': [3, 'd19279cbd4c7f09ba574d56adedc4bebcb02c01cc1eae1bbec2bcafd4e40a4b1'],
  '08 1024 hub': [10, 'f7b63f0e2445d0991a99d19357d27937ae485f65c042ff104ee2dc32c03438a9'],
  '08 1440 map': [3, '0c1c6d6cbf4a46f993314beeb01424c9d6d1f17f6a8dfa742e79641d0b91a0b5'],
  '08 1440 hub': [10, 'bcfc6f05f10de05122ccd249317f4d39d5bf45f01435beb2e3c4361e8ef986c2'],
  '09 1024 map': [1, 'efb783dd26328b9ac521caf91c96def7adfb9b2c5971de54ac8f91ef700c3749'],
  '09 1024 hub': [4, '3d17829339327ef0b7d47bd73846b619e0324a8538d313b21ce8561890bd93c0'],
  '09 1440 map': [1, '817316f3d4b4f52cdf0090ede13e45205f9bcb461bdca25dd886880691f340c2'],
  '09 1440 hub': [4, '8105d9647c938acecea48b2a6b69ef76cbc57eea09b27beea2ef1b3f161f9034'],
  '10 1024 map': [4, '9072fc90f7778fc8e92a81b1ca3db32de6f2fcfbdd50a48afb642a933d6e4460'],
  '10 1024 hub': [22, 'e181afd487e8eaf0843a67a621908561d684874627c0cd8f26e26e0453fb189a'],
  '10 1440 map': [4, 'b20089d717281e9a15679410532b62985daa4e0a4c76e23c4e346b5d56cfdf9e'],
  '10 1440 hub': [22, '37cd6163d7aff73ac89a3d62a7bb47624ffa05ed1b45b50f171a9fae8b22d7ab'],
  '11 1024 map': [3, '49513996b02386fd46f3866253666f122a299c34dd0d3f957526d02eea2cedcf'],
  '11 1024 hub': [22, '708697231dcbd2b07fd633af68836e35ecb5d42a21df8f4262f327ca734d8783'],
  '11 1440 map': [3, '0dfe0a09055311f839d7cfe8efeebcefaf1a0a7fca466d4890e23cc9c888408f'],
  '11 1440 hub': [22, 'd4160e8287f7d2755a527b99ca9b84e91524d1e5912fdc8166e28712935a36ef'],
  '12 1024 map': [1, 'b5853b682cf7661b0d732d62b11672c253835e62df47696619aa514a54a45451'],
  '12 1024 hub': [22, 'ddcbf9aea57e29f0cddbf50e09288f8c1ab000512c741b34e19e96075e514974'],
  '12 1440 map': [1, 'be9192fa5bc645379e51f6461447a87ea604565cce2c0cc3d72b46d491648d2a'],
  '12 1440 hub': [22, '638808a20f62c89233d9bd568f0ae21e5d5790c722ee730a6ac39203c4149bc5'],
  '13 1024 map': [4, 'aa9c096a462eac5726d732072ee07e30b834166b0f9f824e970e3dec0940e60a'],
  '13 1024 hub': [18, 'b5ceedd57e84478475cbdac7197a1894ac709a8b18b8745dba3113c57c3c7623'],
  '13 1440 map': [4, 'fd9385b460d62e85c295e0c9814158a2babc6a70a312ab05ee74b2a2fd205d15'],
  '13 1440 hub': [18, '153ada858c7fee80e598a8ac1785d37b1a61dc395025c2d73a11599ffb88b50d'],
  '14 1024 map': [3, 'a69c6efe6dbca6987243afad0e95eb5dd860e73511dbd415b4029f2a9d12588d'],
  '14 1024 hub': [18, 'a0bda7c95b3dfe86043814640c7e020fa793b572d002da3510187bf156e6ff73'],
  '14 1440 map': [3, 'c93d05a84bf197782664edd67b5ec566930e6bb060fb87c1c3a6c93889f772e3'],
  '14 1440 hub': [18, 'e447adfd8f1fbc4cff9f259c28d4e95dfb99988f3c0af7c2ef7ae8199c52b91a'],
  '15 1024 map': [2, 'c36b5c62e50edccf38dba77a25117f5ed7943b1d33f8a45f8499b74e9fc6fef7'],
  '15 1024 hub': [18, '96dc2191efe27b047afdd1fdc6f17e1cf83f1e393a7e11dca9958cbac131b07b'],
  '15 1440 map': [2, '6b66cce9a272a76483a1491d458ec99278386b46c189b7d229d3e6db80520c95'],
  '15 1440 hub': [18, '7a6f322a20bb5cd76fa4ed40433cf801c05087ae5a18e5618b6fa64962a2eb0c'],
  '16 1024 map': [1, 'd3d9ff7c3ecfe56b367cfcf330c8ca7b15a4b92e7d568c811e56ccae484c4202'],
  '16 1024 hub': [18, '20c12e32ae07ea0c993538f2cf5b43d4b0e9ede90fc0f17dc340610010378631'],
  '16 1440 map': [1, '1013ecebe93012858907dc41cf5ad5c036a13d1969126bdc24e127bb8d5f33f4'],
  '16 1440 hub': [18, '74165f8b56517b563fafc61f5673649001618c3b5d1374a13a0bbcde97c4f1a8'],
  '17 1024 map': [2, 'b2af474c2c7d6270b78fb6f39727043293490a0cad033216991c4440b00cf1fd'],
  '17 1024 hub': [14, 'b3e8942fc16dac88b0129f5228d0ec24db277fb3bf62cd0dd7d6a68b7ec211f6'],
  '17 1440 map': [2, '3356ecab760f7633dfc2c6eb439dd30da9e9038e791a85eb9e2f98d4abe0f80b'],
  '17 1440 hub': [14, '408ea607d166263cdfb800b84d75525c682132f78a276997b19219cc7542d648'],
  '18 1024 map': [2, 'e01e421b6b3151cbe09988320bc7dd5f565c063595d3b7bfc21c7de35469d8b6'],
  '18 1024 hub': [10, '4f947027d35e30632962e810c78b922e500c7066c2cb16d9f092ea0bc167ad72'],
  '18 1440 map': [2, 'b20b62f001d76cbafb5aa2f084ac247e61c74bf606bdf3081955eefef26f7b81'],
  '18 1440 hub': [10, '0016e32fc42a49d19d38adb4c334784f835376f925660bd8f642ecf50c6e2ac4'],
  '19 1024 map': [1, 'c7473eefb330ad4b32565b4618fc31aebdde60c7e38a2d541b6a369550a6350a'],
  '19 1024 hub': [10, '5ca6f51539ddbc835b562cdcdfb75ee5be890088510d6dc737ecbea74303ff5f'],
  '19 1440 map': [1, '2e1eb3cfd02ef4418fa5bb9142d447832c6be33d02292950839191be6654ddd1'],
  '19 1440 hub': [10, '3c8e247454d74b0b6833ea3274657499ab2d59ca665be1aa2e93a450daa95afd'],
  '20 1024 map': [4, 'e92c6112e5b783d28b42bf025122d77867248132d1e5a53f3d584697abb3c3bd'],
  '20 1024 hub': [22, 'e2a7232ef6a48b16396b7a90c3c2c1930ee6e82dc9ef20a9f72fda5d63da7626'],
  '20 1440 map': [4, 'e94233666d065d57a5e3af4438a13a2b12b2a35f7c40237ed7826e38248b0743'],
  '20 1440 hub': [22, '609892bf743703c24eda6f9b34d78b833e156ad9d0a0d3bb622fda02b773e82e'],
};

describe('the glance map router, on fixed maps', () => {
  it('lays the cards out apart and clear of the hub, as the page does', () => {
    const apart = (a: Rect, b: Rect) => a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y;
    for (const team of TEAMS)
      for (const width of [1024, 1440] as const) {
        const { cards, box } = layout(team, width);
        const rects = [...cards.values(), HUB];
        expect(cards.size).toBe(team.members.length);
        rects.forEach((a, i) => rects.slice(i + 1).forEach((b) => expect(apart(a, b)).toBe(true)));
        rects.forEach((r) => expect(r.x + r.w <= box.w && r.y + r.h <= box.h).toBe(true));
      }
  });

  it('still reaches every branch the teams were picked for', () => {
    const got = new Set(routes().flatMap(reached));
    expect(REACHES.filter((x) => !got.has(x))).toEqual([]);
  });

  it('draws every map and every You/Temper line exactly as listed', async () => {
    const got: Listed = {};
    for (const r of routes()) {
      got[`${r.id} map`] = [r.map.lines.length, await sha256(canon(r.map))];
      got[`${r.id} hub`] = [r.hub.reduce((n, [, paths]) => n + paths.size, 0), await sha256(canon(r.hub))];
    }
    const list = Object.entries(got)
      .map(([k, [n, h]]) => `  '${k}': [${n}, '${h}'],`)
      .join('\n');
    expect(got, `The router's output moved. If that is meant (check the map in the browser first), the new list:\n${list}\n`).toEqual(
      ROUTED,
    );
  });
});
