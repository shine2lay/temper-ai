"""Freeze existing labelled inputs and explicit pairwise, retrieval and adversarial additions.
No live store reads: source paths inside data24 are provenance strings only.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PI = Path('/home/shinelay/projects/pi-openviking')
DATA = Path('/home/shinelay/temper-ai/trials/openviking-v2-model-bench/artifacts/cases.json')


def main():
    sources = ROOT / 'sources'
    sources.mkdir(exist_ok=True)
    for name, path in {
        'acceptance.json': PI / 'tests/v2-acceptance-fixtures.json',
        'data24.json': DATA,
        'candidate-gate.ts': PI / 'src/v2/candidate-gate.ts',
        'claim-text.ts': PI / 'src/v2/claim-text.ts',
        'injector.ts': PI / 'src/injector.ts',
    }.items():
        target = sources / name
        if target.exists() and target.read_bytes() != path.read_bytes():
            raise ValueError(f'E_FROZEN_SOURCE_CONFLICT: {name}')
        if not target.exists():
            target.write_bytes(path.read_bytes())
    judgment = json.loads((sources / 'acceptance.json').read_text())['judgment_set']
    pairs = []
    for category in ['must_merge', 'contradiction', 'near_twin', 'control']:
        for p in judgment[category]:
            pairs.append({**p, 'slice': 'judgment_set', 'label': category if category != 'control' else 'unrelated_control',
                          'decision': 'eject_b' if category == 'must_merge' else 'both_stay',
                          'rationale': 'Canonical Architecture judgment_set label; contradictions are candidates, not automatic ejections.'})
    # Direction means one whole note may be removed without losing a claim.
    # Complementary N-way merges are NOT duplicate pairs (Architecture rm-f22a8461).
    duplicate_directions = {'D01': 'eject_b', 'D02': 'eject_b', 'D05': 'eject_b',
                            'D09': 'eject_b', 'D10': 'eject_a', 'D12': 'eject_b'}
    data24 = json.loads((sources / 'data24.json').read_text())['cases']
    for c in data24:
        for a, b in itertools.combinations(c['notes'], 2):
            decision = duplicate_directions.get(c['id'], 'both_stay')
            if c['id'] == 'D14' and [a['id'], b['id']] == ['n1', 'n2']:
                decision = 'eject_b'
            if c['task'] == 'sweep':
                ejected = c['expected']['ejected']
                decision = 'eject_a' if a['id'] in ejected else 'eject_b' if b['id'] in ejected else 'both_stay'
            pairs.append({'id': f"{c['id']}-{a['id']}-{b['id']}", 'slice': 'data24',
                          'a': a['text'], 'b': b['text'], 'decision': decision,
                          'label': 'must_merge' if c['task'] == 'dedup' and decision != 'both_stay' else 'data24_both_stay' if decision == 'both_stay' else 'evidence_ejection',
                          'rationale': 'Pairwise whole-note redundancy' if c['id'] in duplicate_directions else 'Complementary or orthogonal facts both survive; sweep ejection only with canonical evidence.',
                          'source_case': c['id'], 'note_ids': [a['id'], b['id']],
                          'canonical_evidence': c['canonical_evidence']})
    twins = [
        ('Twilight allergy', 'Pollen exposure causes sneezing in spring.', 'Binary search', 'A sorted array permits logarithmic lookup.'),
        ('Ceramic glaze', 'Cobalt oxide produces a blue pottery finish.', 'DNS caching', 'Resolvers retain answers until their TTL expires.'),
        ('Ocean salinity', 'Evaporation increases the dissolved salt concentration.', 'Compiler parsing', 'An abstract syntax tree represents source grammar.'),
        ('Bread fermentation', 'Yeast releases carbon dioxide inside dough.', 'Bicycle brakes', 'Disc pads grip a rotor to reduce wheel speed.'),
        ('Moon geology', 'Basalt plains formed from ancient lava flows.', 'Invoice rounding', 'Totals use integer minor currency units.'),
        ('Violin tuning', 'The highest open string is tuned to E.', 'Database isolation', 'Serializable transactions avoid write skew.'),
    ]
    frontmatter = '---\nitem_id: shared-twin\nowner: data\naudience: role\ncategory: system\nproject: openviking\ntopic: retrieval-calibration\nstanding: false\nsaid_on: 2026-11-16\nevidence: task-21\ncontent_sha: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n---\n'
    for i, (ha, a, hb, b) in enumerate(twins, 1):
        pairs.append({'id': f'TWIN-{i}', 'slice': 'frontmatter_twin', 'label': 'unrelated_control',
                      'a': f'# {ha}\n{a}', 'b': f'# {hb}\n{b}', 'frontmatter': frontmatter,
                      'decision': 'both_stay', 'rationale': 'Orthogonal subject matter with byte-identical metadata.'})
    controls = [
        ('/api/v1/health returns HTTP 200 when the daemon is reachable.', '/api/v1/health documentation uses a green badge in screenshots.'),
        ('rollout-state.json stores pending_wt_land_syncs as an array.', 'rollout-state.json is excluded from the public backup archive.'),
        ('tokens.json defines spacing values in rem units.', 'tokens.json is mentioned in the onboarding translation glossary.'),
        ('/entries was retired from the dashboard API.', '/entries appeared in a historical user-research interview transcript.'),
    ]
    for i, (a, b) in enumerate(controls, 1):
        pairs.append({'id': f'GATE-CONTROL-{i}', 'slice': 'gate_surviving_control', 'label': 'unrelated_control',
                      'a': a, 'b': b, 'decision': 'both_stay',
                      'rationale': 'Shared identifier, orthogonal operational facts; neither note duplicates nor contradicts the other.'})
    topics = [
        ('staging-smoke', 'Staging smoke tests', 'Staging smoke tests start automatically after pi-web-deploy.', 'Check staging smoke tests after pi-web-deploy'),
        ('metric-unknown', 'Missing metric counts', 'Missing metric counts stay null; zero requires a complete inspected source.', 'Correct missing metric counts and null values'),
        ('currency-rounding', 'Currency rounding', 'Currency rounding uses integer minor units and rounds only once at the total.', 'Audit currency rounding and integer minor units'),
        ('fold-receipt', 'Fold receipt verification', 'Fold receipt verification checks message SHA before changing the chat.', 'Implement fold receipt verification and message SHA'),
        ('retrieval-scope', 'Retrieval scope isolation', 'Retrieval scope isolation excludes another role personal memories.', 'Repair retrieval scope isolation for personal memories'),
        ('resume-cursor', 'Durable resume cursor', 'A durable resume cursor skips completed items with the same hash.', 'Add a durable resume cursor and same hash skip'),
        ('snapshot-age', 'Snapshot age badge', 'Snapshot age badge appears after fifteen minutes unless a young rebuild is running.', 'Fix snapshot age badge during a young rebuild'),
        ('model-quota', 'Model quota observation', 'Model quota observation reads provider allowance; token counts are not spare quota.', 'Report model quota observation and provider allowance'),
        ('resource-sync', 'Resource sync failures', 'Resource sync failures keep pending_wt_land_syncs until a successful sync.', 'Fix resource sync failures and pending_wt_land_syncs'),
        ('test-workers', 'Local test workers', 'Local test workers default to ten once the adapter supports parallel tests.', 'Configure local test workers and parallel tests'),
        ('judge-order', 'Judge position bias', 'Judge position bias is checked by grading blinded pairs in both orders.', 'Measure judge position bias with blinded pairs'),
        ('cache-expiry', 'Cache expiry TTL', 'Cache expiry TTL is measured from insertion rather than the last read.', 'Repair cache expiry TTL and insertion timestamps'),
    ]
    items, lead, workers = [], [], []
    categories = ['gotcha', 'system', 'decision', 'preference']
    for i, (slug, headline, body, query) in enumerate(topics):
        project = 'rollcall' if i % 2 == 0 else 'temper-ai'
        expected = []
        for owner in ['resource', 'default', 'data']:
            uri = f'viking://resources/{project}/specs/{slug}.md' if owner == 'resource' else f'viking://user/{owner}/memories/{categories[i % 4]}/{slug}/{slug}.md'
            items.append({'id': f'{slug}-{owner}', 'uri': uri, 'owner': owner, 'project': project,
                          'headline': headline, 'body': body, 'state': 'active', 'category': categories[i % 4]})
            expected.append(uri)
        workers.append({'id': f'W-{i+1:02}', 'role': 'data', 'project': project,
                        'touches': [f'src/{slug}.py'], 'taskPrompt': query, 'expected': expected})
        if i < 8:
            lead.append({'id': f'L-DIRECT-{i+1}', 'kind': 'direct', 'role': 'data', 'project': project,
                         'message': query, 'topic': '', 'expected': expected})
        if i < 6:
            message = ['yes', 'continue', 'do it', 'sounds good', 'go ahead', 'thanks'][i]
            for anchor in [False, True]:
                lead.append({'id': f'L-FOLLOW-{i+1}-' + ('anchored' if anchor else 'unanchored'),
                             'kind': 'anchored_followup' if anchor else 'unanchored_followup',
                             'role': 'data', 'project': project, 'message': message,
                             'topic': headline if anchor else '', 'expected': expected if anchor else []})
    for i, message in enumerate(['How do I prune a lemon tree?', 'Translate good morning into Finnish.',
                                 'Explain the orbit of Neptune.', 'Recommend a vegetarian soup.',
                                 'What causes a rainbow?', 'Write a birthday poem for my cousin.'], 1):
        lead.append({'id': f'L-UNRELATED-{i}', 'kind': 'unrelated', 'role': 'data', 'project': None, 'message': message, 'topic': '', 'expected': []})
    for i in range(4):
        body = f'Backend private release codename nebula-{i} uses a violet canary.'
        items.append({'id': f'private-{i}', 'uri': f'viking://user/backend/memories/gotcha/private/nebula-{i}.md',
                      'owner': 'backend', 'project': 'rollcall', 'headline': f'Backend private nebula-{i}', 'body': body,
                      'state': 'active', 'category': 'gotcha'})
        lead.append({'id': f'L-CROSS-{i}', 'kind': 'cross_role', 'role': 'data', 'project': None,
                     'message': f'Tell me backend private nebula-{i} release details.', 'topic': '', 'expected': []})
    # 30 SAME-TOPIC distractors per positive topic, half legacy, half ejected.
    # Worst-case legacy saturation is intentional and is not a natural prevalence estimate.
    for slug, headline, body, _ in topics:
        for i in range(30):
            zone = '_legacy_v1/events' if i % 2 == 0 else '_ejected/system'
            items.append({'id': f'distractor-{slug}-{i}', 'uri': f'viking://user/default/memories/{zone}/{slug}/retired-{i:02}.md',
                          'owner': 'default', 'project': 'none', 'headline': headline, 'body': body,
                          'state': 'retired', 'category': 'system'})
    result = {'version': 1, 'sampling': 'Purposive frozen constructed retrieval store + existing judgment_set/data24 excerpts; not random or held-out population evidence.',
              'caller_role': 'data', 'shared_owner': 'default', 'thresholds': [0.35, 0.45, 0.50, 0.55, 0.60, 0.65],
              'pairs': pairs, 'items': items, 'lead': lead, 'worker': workers}
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    target = ROOT / 'cases.json'
    if target.exists() and target.read_text() != text:
        raise ValueError('E_CASES_HASH_CONFLICT')
    if not target.exists():
        target.write_text(text)
    print({key: len(result[key]) for key in ['pairs', 'items', 'lead', 'worker']})


if __name__ == '__main__':
    main()
