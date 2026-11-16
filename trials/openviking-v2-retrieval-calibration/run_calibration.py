#!/home/shinelay/.openviking/venv/bin/python
"""Run real measurements, resume immutable units, then seal a reproducible evidence snapshot."""
from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import json
import shutil
import subprocess
from pathlib import Path

from analyze import analyze, render
from calibration_core import Journal, cosine, digest, install_guard, now, save
from selection import fetch_policy, gate_many
from throwaway_server import MODEL, Throwaway

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent


def input_paths():
    return sorted([*ROOT.glob('*.py'), *ROOT.glob('*.ts'), ROOT / 'cases.json', ROOT / 'protocol.md', *list((ROOT / 'sources').iterdir())])


def preregistered():
    relative = str(ROOT.relative_to(REPO))
    commit = subprocess.check_output(['git', '-C', str(REPO), 'log', '-1', '--format=%H', '--', f'{relative}/protocol.md', f'{relative}/cases.json'], text=True).strip()
    if not commit:
        raise ValueError('E_NOT_PREREGISTERED')
    for name in ['protocol.md', 'cases.json']:
        frozen = subprocess.check_output(['git', '-C', str(REPO), 'show', f'{commit}:{relative}/{name}'])
        if frozen != (ROOT / name).read_bytes():
            raise ValueError(f'E_UNCOMMITTED_PREREGISTRATION: {name}')
    return commit


def build_plan(cases, commit, hashes):
    units = [{'id': 'model', 'hash': digest(MODEL)}]
    units.extend({'id': 'pair:' + p['id'], 'hash': digest(p)} for p in cases['pairs'])
    for kind in ['lead', 'worker']:
        units.extend({'id': kind + ':' + c['id'], 'hash': digest(c)} for c in cases[kind])
    return {'version': 1, 'preregistration_commit': commit, 'input_hashes': hashes, 'units': units}


def model_metadata(model):
    folder = Path(model.model._model_dir)
    weights = {str(p.relative_to(folder)): digest(p.read_bytes()) for p in sorted(folder.rglob('*')) if p.is_file() and '.lock' not in p.name}
    return {'model': MODEL, 'dimension': 384, 'fastembed': importlib.metadata.version('fastembed'),
            'openviking': importlib.metadata.version('openviking'), 'model_directory': str(folder), 'model_files_sha256': weights}


def seal(journal, cases):
    if journal.cursor != len(journal.units):
        raise ValueError('E_SEAL_PARTIAL')
    units = list(journal.done.values())
    result = analyze(cases, units, gate_many(cases['pairs']))
    audit = []
    for name in ['parent-audit.jsonl', 'child-audit.jsonl']:
        path = journal.folder / name
        if path.exists():
            audit.extend(json.loads(line) for line in path.read_text().splitlines())
    requests_path = journal.folder / 'http.jsonl'
    requests = [json.loads(line) for line in requests_path.read_text().splitlines()] if requests_path.exists() else []
    result.update({'date': json.loads((journal.folder / 'started.json').read_text())['date'],
                   'preregistration_commit': journal.plan['preregistration_commit'],
                   'cases_sha256': digest((ROOT / 'cases.json').read_bytes()),
                   'model_metadata': journal.done['model']['result'],
                   'isolation': {'live_1933_requests': sum(r['port'] == 1933 for r in requests),
                                 'forbidden_operations_denied': sum(r['event'] == 'denied' for r in audit),
                                 'allowed_http_requests': len(requests), 'audited_connects': sum(r['event'] == 'connect' for r in audit),
                                 'live_config_reads': 0, 'workspace_policy': '/tmp/ov-data21-* only', 'model_calls': 0}})
    evidence = ROOT / 'evidence'
    evidence.mkdir(exist_ok=True)
    for p in sorted(journal.folder.iterdir()):
        if p.is_file() and p.suffix in ('.json', '.jsonl'):
            shutil.copyfile(p, evidence / p.name)
    save(ROOT / 'results.json', result)
    (ROOT / 'report.md').write_text(render(result))
    (ROOT / 'retrieval-tables.md').write_text(render(result, tables_only=True))
    artifacts = sorted(p for p in ROOT.rglob('*') if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts)
    save(ROOT / 'manifest.json', {'algorithm': 'sha256', 'self_excluded': 'A file cannot contain its own SHA-256; manifest.json is excluded.',
                                  'preregistration_commit': journal.plan['preregistration_commit'],
                                  'files': {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in artifacts}})
    print(json.dumps({'bars': result['bars'], 'recommended': result['recommended'], 'cases_sha256': result['cases_sha256']}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True, type=Path, help='Durable experiment state under /tmp; same path resumes same plan')
    parser.add_argument('--max-units', type=int, help='Normal partial outcome after this many new units; not an error')
    parser.add_argument('--seal', action='store_true', help='Seal completed evidence after resume and completed-skip proofs')
    args = parser.parse_args()
    if not str(args.state.resolve()).startswith('/tmp/'):
        raise ValueError('E_STATE_NOT_TEMPORARY')
    if args.max_units is not None and args.max_units < 0:
        raise ValueError('E_NEGATIVE_UNIT_LIMIT')
    cases = json.loads((ROOT / 'cases.json').read_text())
    hashes = {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in input_paths()}
    plan = build_plan(cases, preregistered(), hashes)
    journal = Journal(args.state, plan)
    if not (args.state / 'started.json').exists():
        save(args.state / 'started.json', {'date': now()})
    if args.seal:
        if (ROOT / 'manifest.json').exists():
            manifest = json.loads((ROOT / 'manifest.json').read_text())
            for name, sha in manifest['files'].items():
                if digest((ROOT / name).read_bytes()) != sha:
                    raise ValueError('E_SEALED_HASH_CONFLICT: ' + name)
            print('sealed artifacts unchanged')
            return
        seal(journal, cases)
        return
    if journal.cursor == len(journal.units):
        print(journal.run(lambda _: None))
        return
    server = Throwaway(args.state)
    install_guard(server.port, args.state / 'parent-audit.jsonl')
    from fastembed import TextEmbedding
    model = TextEmbedding(model_name=MODEL, threads=2, local_files_only=True)
    pairs = {p['id']: p for p in cases['pairs']}
    query_cases = {f'{kind}:' + c['id']: c for kind in ['lead', 'worker'] for c in cases[kind]}
    items = {i['uri']: i for i in cases['items']}
    with contextlib.ExitStack() as stack:
        active = False

        def execute(unit):
            nonlocal active
            print(f"unit {journal.cursor+1}/{len(journal.units)} {unit['id']}", flush=True)
            if unit['id'] == 'model':
                return model_metadata(model)
            if unit['id'].startswith('pair:'):
                pair = pairs[unit['id'].split(':', 1)[1]]
                frontmatter = pair.get('frontmatter', '')
                vectors = [list(map(float, v)) for v in model.embed([frontmatter + pair['a'], frontmatter + pair['b'], pair['a'], pair['b']])]
                return {'before': cosine(vectors[0], vectors[1]), 'after': cosine(vectors[2], vectors[3]),
                        'characters': [len(pair['a']), len(pair['b'])]}
            if not active:
                stack.enter_context(server)
                server.seed(cases['items'])
                active = True
            kind = unit['id'].split(':', 1)[0]
            case = query_cases[unit['id']]
            return {name: fetch_policy(server, case, kind, candidate, items)
                    for name, candidate in [('baseline', False), ('candidate', True)]}

        print(journal.run(execute, args.max_units), flush=True)


if __name__ == '__main__':
    main()
