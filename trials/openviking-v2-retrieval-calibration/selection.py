"""Preregistered retrieval policies and adapters; all raw search hits are retained."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATEGORIES = ('gotcha', 'system', 'decision', 'preference')
FOLLOWUPS = {'yes', 'y', 'no', 'n', 'ok', 'okay', 'k', 'sure', 'go', 'go ahead', 'do it', 'proceed', 'continue', 'sounds good', 'looks good', 'lgtm', 'ship it', 'thanks', 'thank you', 'done', 'ack'}


def gate_many(pairs):
    result = subprocess.run(['node', str(ROOT / 'gate_bridge.ts')], input=json.dumps(pairs), text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def visible(uri, role):
    if any(f'/{part}/' in uri for part in ('_legacy_v1', '_ejected')):
        return False
    if uri.startswith('viking://resources/'):
        return True
    return any(uri.startswith(f'viking://user/{owner}/memories/{cat}/') for owner in ('default', role) for cat in CATEGORIES)


def query_of(case, kind, candidate):
    if kind == 'worker':
        return ' '.join([case['taskPrompt'], *case['touches']])
    message = case['message'].strip()
    short = message.lower().rstrip('.!?,;:').strip() in FOLLOWUPS or not message
    if short:
        return f"{case['topic']} {message}" if candidate and case['topic'] else None
    return message


def unique(hits):
    best = {}
    for h in hits:
        if h['uri'] not in best or best[h['uri']]['score'] < h['score']:
            best[h['uri']] = h
    return sorted(best.values(), key=lambda h: (-h['score'], h['uri']))


def fetch_policy(server, case, kind, candidate, item_by_uri):
    query = query_of(case, kind, candidate)
    if query is None:
        return {'query': None, 'raw': [], 'hits': [], 'starved': False}
    role = case['role']
    if candidate:
        targets = [(f'viking://user/{owner}/memories/{cat}', owner) for owner in ('default', role) for cat in CATEGORIES]
        if case['project']:
            targets.insert(0, (f"viking://resources/{case['project']}", 'default'))
    elif kind == 'lead':
        targets = [('viking://resources', 'default'), ('viking://user/default/memories', 'default'), (f'viking://user/{role}/memories', role)]
    else:
        targets = [(f'viking://user/{role}/memories', role)]
        if case['project']:
            targets.insert(0, (f"viking://resources/{case['project']}", 'default'))
    batches = []
    for target, owner in targets:
        batches.append({'target': target, 'owner': owner,
                        'hits': server.find(query, target, limit=6 if not candidate and kind == 'worker' and owner == role else 8, owner=owner)})
    raw = unique([h for batch in batches for h in batch['hits']])
    if candidate:
        selected = raw
    elif kind == 'lead':
        selected = [h for h in raw if '/_ejected/' not in h['uri']][:8]
    else:
        selected = [h for h in raw if h['uri'].startswith('viking://resources/') or '/cases/' in h['uri'] or '/experiences/' in h['uri']]
    selected = [h for h in selected if visible(h['uri'], role) and h['uri'] in item_by_uri]
    gates = gate_many([{'a': query, 'b': f"{item_by_uri[h['uri']]['headline']}\n{item_by_uri[h['uri']]['body']}"} for h in selected])
    hits = [{**h, 'lexical': gate} for h, gate in zip(selected, gates, strict=True)]
    return {'query': query, 'batches': batches, 'raw': raw, 'hits': hits,
            'starved': bool(case['expected']) and not any(h['uri'] in case['expected'] for h in hits)}


def choose(policy, threshold, gate=False, bonus=False):
    eligible = [h for h in policy['hits'] if h['score'] >= threshold and (not gate or h['lexical']['pass'])]

    def ranking(h):
        lex = h['lexical']
        extra = min(0.30, 0.15*(lex['sharedIdentifiers'] + lex['sharedStems'])) if bonus else 0
        return -(h['score'] + extra), h['uri']

    return [h['uri'] for h in sorted(eligible, key=ranking)[:5]]
