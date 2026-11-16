"""Deterministic operating tables and a compact, honest calibration report."""
from __future__ import annotations

import random
from collections import defaultdict

from calibration_core import paired_delta, recall, wilson
from selection import choose


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    x = (len(ordered)-1)*fraction
    lo = int(x)
    return ordered[lo] + (ordered[min(lo+1, len(ordered)-1)]-ordered[lo])*(x-lo)


def bootstrap(rows):
    groups = defaultdict(list)
    for family, value in rows:
        groups[family].append(value)
    if not groups:
        return None
    rng = random.Random(21)
    families = sorted(groups)
    means = []
    for _ in range(2000):
        values = [v for key in rng.choices(families, k=len(families)) for v in groups[key]]
        means.append(sum(values)/len(values))
    return [percentile(means, 0.025), percentile(means, 0.975)]


def family(case):
    return case['expected'][0].split('/')[-1] if case['expected'] else case['id']


def retrieval_table(cases, results, kind):
    rows = []
    queries = cases[kind]
    for policy in ['baseline', 'candidate']:
        for threshold in cases['thresholds']:
            for gated in ([False, True] if kind == 'lead' and policy == 'candidate' else [False]):
                for bonus in ([False, True] if policy == 'candidate' else [False]):
                    samples, negatives, memory, resources, leakage, retired, starvation = [], [], [], [], 0, 0, 0
                    kinds = defaultdict(list)
                    per_query = []
                    for c in queries:
                        raw = results[f"{kind}:{c['id']}"][policy]
                        selected = choose(raw, threshold, gated, bonus)
                        from selection import visible
                        leakage += int(any(u.startswith('viking://user/') and not any(u.startswith(f'viking://user/{o}/') for o in ('default', c['role'])) for u in selected))
                        retired += int(any(not visible(u, c['role']) for u in selected))
                        starvation += int(raw['starved'])
                        value = None
                        if c['expected']:
                            value = recall(c['expected'], selected)
                            samples.append((family(c), value))
                            kinds[c.get('kind', 'worker')].append(value)
                            mem = [u for u in c['expected'] if '/memories/' in u]
                            res = [u for u in c['expected'] if u.startswith('viking://resources/')]
                            memory.append(recall(mem, selected))
                            resources.append(recall(res, selected))
                        else:
                            negatives.append(bool(selected))
                        per_query.append({'id': c['id'], 'returned': selected, 'recall': value})
                    mean = sum(v for _, v in samples)/len(samples)
                    false_positive = sum(negatives)
                    bar = mean >= (0.85 if kind == 'lead' else 0.90) and false_positive == 0 and leakage == 0 and retired == 0
                    rows.append({'policy': policy, 'threshold': threshold, 'keyword_gate': gated, 'keyword_bonus': bonus,
                                 'recall': mean, 'recall_ci95_cluster_bootstrap': bootstrap(samples), 'positive_n': len(samples),
                                 'recall_by_kind': {k: {'n': len(v), 'recall': sum(v)/len(v)} for k, v in kinds.items()},
                                 'memory_recall': sum(memory)/len(memory), 'resource_recall': sum(resources)/len(resources),
                                 'noise_count': false_positive, 'negative_n': len(negatives), 'noise_ci95_wilson': wilson(false_positive, len(negatives)),
                                 'cross_role_queries': leakage, 'retired_queries': retired, 'query_n': len(queries),
                                 'starved_queries': starvation, 'passes_bar': bar, 'per_query': per_query})
    passing = [r for r in rows if r['policy'] == 'candidate' and r['passes_bar']]
    selected = max(passing, key=lambda r: (r['threshold'], r['keyword_gate'], not r['keyword_bonus'])) if passing else None
    return rows, None if selected is None else {key: selected[key] for key in ['threshold', 'keyword_gate', 'keyword_bonus', 'recall', 'noise_count', 'negative_n']}


def analyze(cases, units, gates):
    by_id = {u['id']: u['result'] for u in units}
    pair_rows = []
    for pair, gate in zip(cases['pairs'], gates, strict=True):
        result = by_id['pair:' + pair['id']]
        pair_rows.append({**{k: pair[k] for k in ['id', 'label', 'slice', 'decision']}, **result,
                          'delta': paired_delta(result['before'], result['after']), 'gate': gate})
    distributions = {}
    for label in sorted({p['label'] for p in pair_rows} | {'gate_surviving_control'}):
        values = [p['after'] for p in pair_rows if (p['slice'] == label if label == 'gate_surviving_control' else p['label'] == label)]
        distributions[label] = {'n': len(values), **{k: percentile(values, f) for k, f in [('min', 0), ('p10', .1), ('p50', .5), ('p90', .9), ('max', 1)]}}
    positives = [p for p in pair_rows if p['label'] in ('must_merge', 'contradiction')]
    controls = [p for p in pair_rows if p['label'] == 'unrelated_control']
    hard_controls = [p for p in pair_rows if p['slice'] == 'gate_surviving_control']
    roc = []
    for threshold in cases['thresholds']:
        retained = [p for p in positives if p['after'] >= threshold and p['gate']['pass']]
        roc.append({'simLow': threshold, 'positive_n': len(positives), 'retained': len(retained),
                    'recall': len(retained)/len(positives), 'recall_ci95_wilson': wilson(len(retained), len(positives)),
                    'raw_above_threshold': sum(p['after'] >= threshold for p in positives),
                    'gate_losses': [p['id'] for p in positives if not p['gate']['pass']],
                    'control_n': len(controls), 'controls_retained': sum(p['after'] >= threshold and p['gate']['pass'] for p in controls),
                    'hard_control_n': len(hard_controls), 'hard_controls_retained': sum(p['after'] >= threshold and p['gate']['pass'] for p in hard_controls)})
    sim = [r['simLow'] for r in roc if r['recall'] >= .95]
    lead, lead_choice = retrieval_table(cases, by_id, 'lead')
    worker, worker_choice = retrieval_table(cases, by_id, 'worker')
    twins = [p for p in pair_rows if p['slice'] == 'frontmatter_twin']
    return {'pair_results': pair_rows, 'distributions': distributions, 'simLow_operating_table': roc,
            'lead': lead, 'worker': worker, 'recommended': {'simLow': max(sim) if sim else None, 'lead': lead_choice, 'worker': worker_choice},
            'bars': {'twins_all_decrease': all(p['delta'] < 0 for p in twins), 'twins_n': len(twins),
                     'lead': lead_choice is not None, 'worker': worker_choice is not None,
                     'worker_baseline_v2_memory_recall_zero': all(r['memory_recall'] == 0 for r in worker if r['policy'] == 'baseline'),
                     'gate_controls_pass': all(p['gate']['pass'] for p in hard_controls)}}


def render(result, tables_only=False):
    lines = ['# OpenViking v2 retrieval and V-9 calibration', '', '## Result',
             'Source: frozen cases.json; purposive constructed store and existing Architecture/data24 labels.',
             f"Date: {result['date']}. Model: BAAI/bge-small-en-v1.5; real FastEmbed; OpenViking 0.5.4.",
             f"Preregistered commit: {result['preregistration_commit']}; no measurements preceded that commit.",
             f"Cases SHA-256: {result['cases_sha256']}.",
             f"Hit/miss: {result['bars']}",
             f"Recommended constants (null means NONE meets preregistered bar): {result['recommended']}", '',
             '## Lead L0 and Worker Turn-1',
             'Macro recall@5; topic-cluster bootstrap 95% CI in results.json (2,000 draws, seed 21).',
             'Noise is negative-query injection, not irrelevant-hit fraction. Server scores are NOT raw cosines.',
             'G=canonical lexical gate; B=+0.15/token ranking bonus capped +0.30; raw score still gates.',
             'Baseline is the frozen current search policy plus v2 active/access filter.',
             '| Slice | Policy | Threshold | G | B | Recall | Memory | Resource | Noise | Retired / cross-role | Starved |',
             '|---|---|---:|---|---|---:|---:|---:|---|---|---:|']
    for kind in ['lead', 'worker']:
        for row in result[kind]:
            lines.append(f"| {kind} | {row['policy']} | {row['threshold']:.2f} | {int(row['keyword_gate'])} | {int(row['keyword_bonus'])} | {row['recall']:.3f} | {row['memory_recall']:.3f} | {row['resource_recall']:.3f} | {row['noise_count']}/{row['negative_n']} | {row['retired_queries']} / {row['cross_role_queries']} | {row['starved_queries']} |")
    lines += ['', 'Lead positives n=14 (8 direct, 6 topic-anchored followups); negatives n=16',
              '(6 unanchored followups, 6 unrelated, 4 cross-role probes). Worker plans n=12;',
              'expected items per plan: 1 project resource + 1 shared memory + 1 own-role memory.',
              'No Worker negative-plan slice exists: Worker noise is N/A (0/0), NOT proved zero;',
              'retired/cross-role leakage is separately checked across all 12 plans.',
              f"Lead zero-noise 0/16 Wilson upper 95% bound = {wilson(0, 16)[1]:.4f};",
              f"Worker zero-leakage 0/12 upper bound = {wilson(0, 12)[1]:.4f}.",
              'Per-query hits, recall-by-kind and each policy CI are retained in results.json.', '',
              '## V-9 distributions', '| Label | n | min | p10 | p50 | p90 | max |', '|---|---:|---:|---:|---:|---:|---:|']
    for label, row in result['distributions'].items():
        lines.append(f"| {label} | {row['n']} | " + ' | '.join(f'{row[k]:.4f}' for k in ['min', 'p10', 'p50', 'p90', 'max']) + ' |')
    lines += ['', '### Frontmatter twins', '| Pair | Before | After | Delta | Pass |', '|---|---:|---:|---:|---|']
    for p in result['pair_results']:
        if p['slice'] == 'frontmatter_twin':
            lines.append(f"| {p['id']} | {p['before']:.4f} | {p['after']:.4f} | {p['delta']:.4f} | {p['delta'] < 0} |")
    lines += ['', '### simLow candidate-generation operating table',
              '| simLow | Positive retained / n | Recall | Controls passed / n | Gate-surviving controls passed / n |', '|---:|---|---:|---|---|']
    for r in result['simLow_operating_table']:
        lines.append(f"| {r['simLow']:.2f} | {r['retained']}/{r['positive_n']} | {r['recall']:.3f} | {r['controls_retained']}/{r['control_n']} | {r['hard_controls_retained']}/{r['hard_control_n']} |")
    lines += ['', '## Safety and reproducibility',
              'All writes use vectors_only against a disposable localhost OpenViking workspace under /tmp.',
              f"Isolation audit: {result['isolation']}",
              'Parent/child Python audit guards block live paths and all other TCP ports, including 1933.',
              'These are Python audit observations, not an OS-wide syscall trace; native extensions are a limitation.',
              'Raw measurement units are append-only; plan and input hashes freeze once; partial resume and',
              'completed skip attempts are in evidence. Temporary server configuration/logs remain under /tmp;',
              'model payloads are never copied into this trial. Model weights hashes are recorded in results.json.',
              'manifest.json hashes all trial artifacts except itself and transient Python cache files.', '',
              '## Interpretation and limits',
              'Recommendations are in-sample candidate-generation settings, NOT safe deletion decisions.',
              'Identifier-sharing unrelated facts may survive the gate and similarity cutoff; a judge must still',
              'distinguish duplicates, contradictions and orthogonal facts. No constant authorizes auto-ejection.',
              'Frontmatter twins isolate metadata contamination; ordinary pairs use unmodified source texts.',
              'Data24 sweep ejections depend on canonical evidence and are not counted as semantic duplicates.',
              'This English purposive sample is small and adversarially saturated (360 retired distractors).',
              'Intervals describe frozen-case variation, not population guarantees. Recall with shared phrasing',
              'can be optimistic; multilingual, long-tail, natural topic titles and held-out plans remain untested.',
              'If a preregistered bar misses, keep it a miss. Architecture/Ops/QA decide implementation and QA',
              'owns the single independent final check. No live production defaults were changed.']
    start = lines.index('## Lead L0 and Worker Turn-1')
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == '')
    if tables_only:
        return '# Retrieval operating tables\n\n' + '\n'.join(lines[start:end]) + '\n'
    lines[start:end] = ['## Retrieval operating tables', 'Complete threshold/gate/bonus tables: retrieval-tables.md; raw queries and CIs: results.json.']
    return '\n'.join(lines) + '\n'
