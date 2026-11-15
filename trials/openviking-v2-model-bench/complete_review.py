"""Post-freeze sensitivity and reproducibility audit. No model calls or live reads."""
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path('/tmp/ov-v2-model-bench')
HERE = Path(__file__).resolve().parent
GRADE_HASH = 'f9e6f681a2b8e49812935927e1186e3d00086e1e6544f8de68ed1864d1daf4d3'


def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE/(name+'.py'))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    evaluator = module('evaluate')
    runner = module('run_bench')
    assert sha(ROOT/'blind-grades.json')==GRADE_HASH, 'frozen grade hash mismatch'
    plan = json.loads((ROOT/'plan.json').read_text())
    instruction_hash = runner.digest(runner.INSTRUCTION)
    assert instruction_hash==plan['instruction_sha256'], 'instruction changed after run'
    cases = {c['id']:c for c in json.loads((ROOT/'cases.json').read_text())['cases']}
    results = {p.stem:json.loads(p.read_text()) for p in sorted((ROOT/'results').glob('*.json'))}
    # Canonical packet builder, same seed; write only into a new disposable directory.
    checks = {}
    with tempfile.TemporaryDirectory(prefix='ov-review-audit-') as temp:
        evaluator.ROOT = Path(temp)
        evaluator.packet(cases, results)
        for relative in ['blind/dedup-a.json','blind/dedup-b.json','blind/sweep.json','blind-key.json']:
            checks[relative] = {'sha256':sha(ROOT/relative), 'same_seed_byte_identical':sha(ROOT/relative)==sha(Path(temp)/relative)}
            assert checks[relative]['same_seed_byte_identical']
    grades = json.loads((ROOT/'blind-grades.json').read_text())
    key = json.loads((ROOT/'blind-key.json').read_text())
    scores = json.loads((ROOT/'scores.json').read_text())
    by_id = {s['id']:s for s in scores}
    criteria = ['topic_separation','fact_retention','no_invention','history_handling','concise']
    accepted = [g['blind_id'] for g in grades
                if g['blind_id'][:3] in {'S01','S03','S06'}
                and all(g[f] for f in criteria) and not by_id[key[g['blind_id']]]['correct']]
    assert len(accepted)==9, 'QA sensitivity subset changed'
    accepted_results = {key[x] for x in accepted}
    summary = {}
    for model in runner.MODELS:
        rows = [r for r in scores if r['model']==model]
        sweeps = [r for r in rows if r['case'].startswith('S')]
        additions = sum(r['id'] in accepted_results for r in rows)
        true_positive = sum(r['tp'] for r in sweeps)
        expected = sum(r['tp']+r['fn'] for r in sweeps)
        summary[model] = {'n_calls':len(rows), 'strict_exact':sum(r['correct'] for r in rows),
                          'strict_sweep_exact':sum(r['correct'] for r in sweeps),
                          'accepted_historical_answers':additions,
                          'sensitivity_exact':sum(r['correct'] or r['id'] in accepted_results for r in rows),
                          'sensitivity_sweep_exact':sum(r['correct'] or r['id'] in accepted_results for r in sweeps),
                          'strict_literal_ejection_recall':true_positive/expected,
                          'sensitivity_safe_resolution_recall':(true_positive+additions)/expected}
    receipt = {'grades_sha256':GRADE_HASH, 'instruction_sha256':instruction_hash,
               'instruction_matches_plan':True, 'packet_reproducibility':checks,
               'sensitivity_only_not_preregistered':True,
               'accepted_blind_ids':accepted,
               'accepted_result_ids':sorted(accepted_results), 'models':summary}
    (ROOT/'review-audit.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__ == '__main__':
    main()
