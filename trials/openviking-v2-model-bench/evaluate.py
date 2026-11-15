"""Deterministic metrics and sealed, randomized, model-name-free review packets."""
import itertools
import json
import random
import re
import statistics
from pathlib import Path

ROOT = Path('/tmp/ov-v2-model-bench')
MODELS = ['gpt-6.1-sol', 'gpt-6.1-terra', 'gpt-6-luna']


def parse_output(text, ids, task):
    obj = json.loads(text)
    assert isinstance(obj, dict) and set(obj) == {'items', 'ejected'}
    assert isinstance(obj['items'], list) and isinstance(obj['ejected'], list)
    covered = []
    for item in obj['items']:
        assert isinstance(item, dict) and set(item) == {'source_ids', 'text'}
        assert isinstance(item['source_ids'], list) and item['source_ids']
        assert all(isinstance(v, str) for v in item['source_ids'])
        assert isinstance(item['text'], str) and item['text'].strip()
        covered += item['source_ids']
    for item in obj['ejected']:
        assert isinstance(item, dict) and set(item) == {'source_id', 'reason'}
        assert isinstance(item['source_id'], str)
        assert isinstance(item['reason'], str) and item['reason'].strip()
        covered.append(item['source_id'])
    assert sorted(covered) == sorted(ids), 'source coverage violation'
    assert task != 'dedup' or not obj['ejected'], 'dedup ejection forbidden'
    return obj


def grouping(obj):
    return sorted(sorted(item['source_ids']) for item in obj['items'])


def pairs(groups):
    return {tuple(sorted(p)) for g in groups for p in itertools.combinations(g, 2)}


def lexemes(text):
    # Inventory is a separate strict literal audit, not a semantic fact grader.
    found = set(re.findall(r'(?<!\w)\d+(?:[.,:]\d+)*(?!\w)', text))
    found |= set(re.findall(r'#[0-9]+|--[a-z][a-z-]+|\b[0-9a-f]{7,40}\b', text))
    for token in re.findall(r'`([^`\n]+)`', text):
        if '/' in token and ' ' not in token and not token.startswith(('http:', 'https:')):
            found.add(token)
    found |= set(re.findall(r'(?:~|/home|/tmp)/[^\s`<>),;]+', text))
    return sorted(found)


def kappa(a, b):
    if not a:
        return None
    po = sum(x == y for x, y in zip(a, b, strict=True)) / len(a)
    labels = set(a) | set(b)
    pe = sum(a.count(v) / len(a) * b.count(v) / len(b) for v in labels)
    return (po-pe)/(1-pe) if pe < 1 else None


def quantile(xs, q):
    xs = sorted(xs)
    p = (len(xs)-1)*q
    a = int(p)
    b = min(a+1, len(xs)-1)
    return xs[a] + (xs[b]-xs[a])*(p-a) if xs else None


def rate(n, d):
    return n/d if d else None


def score(case, result):
    ids = [n['id'] for n in case['notes']]
    expected = case['expected']
    row = {k: result[k] for k in ['id', 'case', 'model', 'repeat', 'ok', 'latency_s', 'input_tokens', 'output_tokens', 'total_tokens']}
    import hashlib
    row['response_hash'] = hashlib.sha256(result.get('output', '').encode()).hexdigest()
    truth = ([p in pairs(expected['groups']) for p in itertools.combinations(ids, 2)]
             if case['task']=='dedup' else [n in expected['ejected'] for n in ids])
    row.update(schema=False, correct=False, missing_sentinels=[], missing_lexemes=[],
               decisions=[], truth=truth, tp=0, fp=0, fn=sum(truth))
    try:
        obj = parse_output(result.get('output', ''), ids, case['task'])
    except (ValueError, AssertionError, TypeError):
        row['missing_sentinels'] = expected['verbatim']
        row['decisions'] = [None] * (len(list(itertools.combinations(ids, 2))) if case['task']=='dedup' else len(ids))
        return row
    row['schema'] = True
    row['groups'] = grouping(obj)
    row['ejected'] = sorted(n['source_id'] for n in obj['ejected'])
    row['correct'] = row['groups'] == sorted(sorted(g) for g in expected['groups']) and row['ejected'] == sorted(expected['ejected'])
    retained = '\n'.join(item['text'] for item in obj['items'])
    row['missing_sentinels'] = [s for s in expected['verbatim'] if s not in retained]
    expected_retained = '\n'.join(n['text'] for n in case['notes'] if n['id'] not in expected['ejected'])
    row['missing_lexemes'] = [s for s in lexemes(expected_retained) if s not in retained]
    expected_pairs = pairs(expected['groups'])
    actual_pairs = pairs(row['groups'])
    if case['task'] == 'dedup':
        row['decisions'] = [p in actual_pairs for p in itertools.combinations(ids, 2)]
        row['truth'] = [p in expected_pairs for p in itertools.combinations(ids, 2)]
        row['tp'] = len(expected_pairs & actual_pairs)
        row['fp'] = len(actual_pairs - expected_pairs)
        row['fn'] = len(expected_pairs - actual_pairs)
    else:
        exp, actual = set(expected['ejected']), set(row['ejected'])
        row['decisions'] = [n in actual for n in ids]
        row['truth'] = [n in exp for n in ids]
        row['tp'] = len(exp & actual)
        row['fp'] = len(actual-exp)
        row['fn'] = len(exp-actual)
    return row


def packet(cases, results):
    rng = random.Random(20261116)
    key, bundles = {}, []
    for cid, case in cases.items():
        for repeat in [1, 2]:
            options = [results[f'{cid}--{m}--r{repeat}'] for m in MODELS if f'{cid}--{m}--r{repeat}' in results]
            if len(options) != 3:
                continue
            rng.shuffle(options)
            choices = []
            for label, res in zip(['A', 'B', 'C'], options, strict=True):
                blind = f'{cid}-r{repeat}-{label}'
                key[blind] = res['id']
                choices.append({'blind_id': blind, 'response': res.get('output', ''), 'request_ok': res['ok']})
            bundles.append({'case': cid, 'repeat': repeat, 'task': case['task'],
                            'notes': [{'id': n['id'], 'text': n['text']} for n in case['notes']],
                            'canonical_evidence': [{'text': n['text']} for n in case['canonical_evidence']],
                            'choices': choices})
    out = ROOT / 'blind'
    out.mkdir(exist_ok=True)
    for prefix, selected in [('dedup-a', [v for v in bundles if v['case'] <= 'D07']),
                             ('dedup-b', [v for v in bundles if 'D08' <= v['case'] <= 'D14']),
                             ('sweep', [v for v in bundles if v['case'].startswith('S')])]:
        (out / (prefix+'.json')).write_text(json.dumps(selected, ensure_ascii=False, indent=2)+'\n')
    (ROOT/'blind-key.json').write_text(json.dumps(key, indent=2)+'\n')


def aggregate(rows):
    metrics = {}
    for model in MODELS:
        rs = [r for r in rows if r['model']==model]
        if not rs:
            continue
        entry = {'n_calls': len(rs), 'request_ok': sum(r['ok'] for r in rs),
                 'schema_ok': sum(r['schema'] for r in rs), 'exact_case_correct': sum(r['correct'] for r in rs),
                 'sentinel_omission_calls': sum(bool(r['missing_sentinels']) for r in rs),
                 'sentinel_omissions': sum(len(r['missing_sentinels']) for r in rs),
                 'lexical_omission_calls': sum(bool(r['missing_lexemes']) for r in rs),
                 'p50_s': quantile([r['latency_s'] for r in rs], .5),
                 'p90_s': quantile([r['latency_s'] for r in rs], .9)}
        for field in ['input_tokens', 'output_tokens', 'total_tokens']:
            vs = [r[field] for r in rs if r[field] is not None]
            entry[field] = {'sum_available': sum(vs) if vs else None, 'n_available': len(vs),
                            'mean': statistics.mean(vs) if vs else None}
        for task in ['dedup', 'sweep']:
            subset = [r for r in rs if r['case'].startswith('D' if task=='dedup' else 'S')]
            tp = sum(r.get('tp', 0) for r in subset)
            fp = sum(r.get('fp', 0) for r in subset)
            fn = sum(r.get('fn', 0) for r in subset)
            entry[task] = {'n_calls': len(subset), 'exact_case_correct': sum(r['correct'] for r in subset),
                           'tp': tp, 'fp': fp, 'fn': fn, 'precision': rate(tp, tp+fp), 'recall': rate(tp, tp+fn),
                           'note_or_pair_accuracy': rate(sum(x==y for r in subset for x,y in zip(r['decisions'], r.get('truth', [False]*len(r['decisions'])), strict=True)), sum(len(r['decisions']) for r in subset))}
        paired = []
        for cid in sorted(set(r['case'] for r in rs)):
            rr = [r for r in rs if r['case']==cid]
            if len(rr)==2:
                paired.append(rr)
        entry['repeat_binary_decision_agreement'] = sum(r[0]['decisions']==r[1]['decisions'] and r[0]['schema'] and r[1]['schema'] for r in paired)
        entry['repeat_exact_decision_agreement'] = sum(r[0].get('groups')==r[1].get('groups') and r[0].get('ejected')==r[1].get('ejected') and r[0]['schema'] and r[1]['schema'] for r in paired)
        entry['repeat_n_cases'] = len(paired)
        entry['repeat_pass_fail_agreement'] = sum(r[0]['correct']==r[1]['correct'] for r in paired)
        entry['repeat_wording_equality'] = sum(r[0]['response_hash']==r[1]['response_hash'] for r in paired)
        baseline = {(r['case'],r['repeat']): r for r in rows if r['model']==MODELS[0]}
        aa, bb = [], []
        for r in rs:
            base = baseline.get((r['case'], r['repeat']))
            if base:
                aa += r['decisions']
                bb += base['decisions']
        entry['kappa_vs_sol'] = kappa(aa, bb)
        entry['n_kappa_decisions'] = len(aa)
        for task in ['dedup', 'sweep']:
            subset = [r for r in rs if r['case'].startswith('D' if task=='dedup' else 'S')]
            a = [x for r in subset for x in r['decisions']]
            b = [x for r in subset for x in baseline.get((r['case'],r['repeat']), r)['decisions']]
            entry[task]['kappa_vs_sol'] = kappa(a, b)
        truth, decisions = [], []
        for r in rs:
            if 'truth' in r:
                truth += r['truth']
                decisions += r['decisions']
        entry['kappa_vs_labels'] = kappa(truth, decisions)
        # Case-cluster bootstrap, not a false n=48 independent Bernoulli CI.
        rng = random.Random(20261117)
        clusters = [[r for r in rs if r['case']==cid] for cid in sorted(set(r['case'] for r in rs))]
        rates, deltas, token_ratios, p90_ratios = [], [], [], []
        for _ in range(5000):
            draw = [r for cluster in rng.choices(clusters, k=len(clusters)) for r in cluster]
            rates.append(sum(r['correct'] for r in draw)/len(draw))
            bases = [baseline[(r['case'],r['repeat'])] for r in draw if (r['case'],r['repeat']) in baseline]
            if len(bases)==len(draw):
                deltas.append(sum(int(r['correct'])-int(b['correct']) for r,b in zip(draw,bases,strict=True))/len(draw))
                if all(r['total_tokens'] is not None for r in draw+bases):
                    token_ratios.append(sum(r['total_tokens'] for r in draw)/sum(r['total_tokens'] for r in bases))
                p90_ratios.append(quantile([r['latency_s'] for r in draw],.9)/quantile([r['latency_s'] for r in bases],.9))
        entry['paired_vs_sol_bootstrap_95'] = {name: [quantile(vs,.025),quantile(vs,.975)] if vs else None
            for name,vs in [('exact_case_accuracy_delta',deltas),('total_token_ratio',token_ratios),('p90_latency_ratio',p90_ratios)]}
        entry['exact_case_cluster_bootstrap_95'] = [quantile(rates, .025), quantile(rates, .975)]
        metrics[model] = entry
    return metrics


def main():
    cases = {c['id']: c for c in json.loads((ROOT/'cases.json').read_text())['cases']}
    results = {p.stem: json.loads(p.read_text()) for p in sorted((ROOT/'results').glob('*.json'))}
    rows = [score(cases[r['case']], r) for r in results.values()]
    metrics = aggregate(rows)
    (ROOT/'scores.json').write_text(json.dumps(rows, indent=2)+'\n')
    (ROOT/'metrics.json').write_text(json.dumps(metrics, indent=2)+'\n')
    packet(cases, results)
    print(json.dumps({'n_results': len(results), 'metrics': metrics}, indent=2))


if __name__ == '__main__':
    main()
