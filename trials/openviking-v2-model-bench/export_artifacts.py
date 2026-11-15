"""Archive trial evidence in this worktree; no credential or request-body export."""
import hashlib
import json
import platform
from pathlib import Path

ROOT = Path('/tmp/ov-v2-model-bench')
DEST = Path(__file__).resolve().parent


def main():
    dest = DEST/'artifacts'
    dest.mkdir(exist_ok=True)
    names = ['cases.json', 'plan.json', 'scores.json', 'metrics.json', 'attempts.jsonl',
             'safety-attempts.jsonl', 'blind-key.json', 'blind-grades.json', 'semantic-metrics.json',
             'final-check.md', 'lead-ruling.md', 'review-audit.json']
    for name in names:
        p = ROOT/name
        if p.exists():
            (dest/name).write_bytes(p.read_bytes())
    results = [json.loads(p.read_text()) for p in sorted((ROOT/'results').glob('*.json'))]
    (dest/'responses.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in results))
    for p in (ROOT/'blind').glob('*.json'):
        out = dest/'blind'/p.name
        out.parent.mkdir(exist_ok=True)
        out.write_bytes(p.read_bytes())
    qa_root = Path('/home/shinelay/qa-lab/ov-v2-model-bench')
    for name in ['freeze.txt','plant-freeze.txt','rubric.md','rubric.sha256','plant-compare.txt',
                 'plants.json','plants-key.json','plant-grades.json',
                 'qa_artifacts.py','qa_packet.py','qa_plants.py']:
        p = qa_root/name
        if p.exists():
            out = dest/'qa'/(name+'.txt' if name.endswith('.py') else name)
            out.parent.mkdir(exist_ok=True)
            out.write_bytes(p.read_bytes())
    safety = [json.loads(v) for v in (ROOT/'safety-attempts.jsonl').read_text().splitlines()]
    sample = json.loads((ROOT/'cases.json').read_text())
    manifest = {'created_at': max(r['finished_at'] for r in results),
                'export_python': platform.python_version(), 'n_cases': len(sample['cases']),
                'n_results': len(results),
                'date_range_utc': [min(r['started_at'] for r in results), max(r['finished_at'] for r in results)],
                'unique_source_files': len({n['source'] for c in sample['cases'] for n in c['notes']+c['canonical_evidence']}),
                'largest_case_input_tokens': max(r['input_tokens'] for r in results),
                'attempt_rows': len((ROOT/'attempts.jsonl').read_text().splitlines()),
                'safety_receipts': len(safety),
                'port1933_attempts': sum(s['port_1933_attempts'] for s in safety),
                'denied_live_write_attempts': sum(s['live_writes'] for s in safety),
                'resume_complete_no_network': any(s['mode']=='all' and not s['events'] for s in safety),
                'artifacts_sha256': {str(p.relative_to(DEST)):hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted(dest.rglob('*')) if p.is_file()}}
    (DEST/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps({k:v for k,v in manifest.items() if k!='artifacts_sha256'},indent=2))


if __name__ == '__main__':
    main()
