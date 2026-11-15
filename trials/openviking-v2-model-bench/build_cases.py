"""Frozen, provenance-preserving real-memory sample; never reads sessions or services."""
import hashlib
import json
from pathlib import Path

SOURCE = Path('/home/shinelay/.openviking/data/viking/default/user')
ROOT = Path('/tmp/ov-v2-model-bench')


def excerpt(path, start=None, stop=None):
    p = SOURCE / path
    raw = p.read_bytes()
    text = raw.decode().split('<!-- MEMORY_FIELDS')[0].strip()
    if start:
        assert text.count(start) == 1, (path, start)
        text = text[text.index(start):]
    if stop:
        assert stop in text, (path, stop)
        text = text[:text.index(stop)].strip()
    return {'source': str(p), 'sha256': hashlib.sha256(raw).hexdigest(), 'text': text}


def line(path, contains):
    doc = excerpt(path)
    lines = [v for v in doc['text'].splitlines() if contains in v]
    assert len(lines) == 1, (path, contains, len(lines))
    return dict(doc, text=lines[0])


P = {
    'shared1': 'ops/memories/experiences/shared_changelog_replay_classification.md',
    'shared2': 'default/memories/experiences/shared_changelog_replay_classification.md',
    'sharedcase': 'ops/memories/cases/shared_changelog_health_fix.md',
    'isolate': 'ops/memories/cases/isolate_landing_model_calls.md',
    'test1': 'ops/memories/entities/checking_tool/test_check.md',
    'test2': 'default/memories/entities/tool/test_check.md',
    'pi1': 'default/memories/entities/software/pi_identity.md',
    'pi2': 'data/memories/entities/software_component/pi_identity.md',
    'badge': 'default/memories/entities/contract_field/dashboard_stale_badge.md',
    'observer': 'default/memories/entities/contract_field/observer_last_reachable_at.md',
    'entries': 'default/memories/entities/contract/dashboard_entries.md',
    'snapshot': 'default/memories/entities/contract/dashboard_entries_snapshot.md',
    'sync': 'default/memories/entities/contract/dashboard_resource_sync.md',
    'state': 'architecture/memories/entities/runtime_state/rollout_state.md',
    'post': 'default/memories/entities/contract/post_cutover_notebooks.md',
    'deploy': 'backend/memories/preferences/user/service_deployment_workflow.md',
    'timing': 'data/memories/preferences/owner/deployment_timing.md',
    'opsdeploy': 'ops/memories/preferences/user/service_deployment.md',
    'rm': 'default/memories/preferences/user/role_message_dedup.md',
    'ledger': 'default/memories/entities/contract/role_message_dedup.md',
    'idempotent': 'default/memories/preferences/user/processing_idempotency.md',
    'notebook': 'default/memories/preferences/user/notebook_maintenance.md',
    'retire': 'ops/memories/events/2026/11/11/notebook_retirement_approved.md',
    'restore': 'ops/memories/events/2026/11/15/notebook_restore_completed.md',
    'olddeploy': 'backend/memories/events/2026/11/12/staleness_fix_commitment.md',
    'showtell': 'ops/memories/entities/release_tool/showtell_deploy.md',
    'piweb': 'default/memories/entities/deployment_tool/pi_web_deploy.md',
    'hook': 'default/memories/entities/software/openviking_commit_hook.md',
}


def E(key, start=None, stop=None):
    return excerpt(P[key], start, stop)


def L(key, phrase):
    return line(P[key], phrase)


CASES = []


def case(cid, category, kind, notes, groups, keep=(), evidence=(), drop=(), subtype=''):
    notes = [dict(n, id=f'n{i+1}') for i, n in enumerate(notes)]
    assert sorted(x for g in groups for x in g) == sorted(n['id'] for n in notes if n['id'] not in drop)
    assert len(set(drop)) == len(drop)
    for fact in keep:
        assert any(fact in n['text'] for n in notes) or any(fact in e['text'] for e in evidence), (cid, fact)
    CASES.append({'id': cid, 'category': category, 'task': kind, 'subtype': subtype,
                  'notes': notes, 'canonical_evidence': list(evidence),
                  'expected': {'groups': groups, 'ejected': list(drop), 'verbatim': list(keep)}})


# 14 consolidation cases: exact-copy controls are explicitly constructed, not claimed natural.
case('D01', 'gotcha', 'dedup', [L('shared1', 'NEVER classify an entry'), L('shared1', 'NEVER classify an entry')], [['n1','n2']], subtype='constructed exact duplicate')
case('D02', 'gotcha', 'dedup', [E('shared1', '## Reflect'), E('shared2', '## Reflect')], [['n1','n2']], subtype='natural paraphrase overlap')
case('D03', 'gotcha', 'dedup', [L('shared1', 'NEVER add the shared'), L('shared2', 'NEVER introduce a second'), L('shared1', 'NEVER weaken unknown')], [['n1','n2','n3']], subtype='three-note complementary merge')
case('D04', 'gotcha', 'dedup', [L('shared1', 'NEVER edit, rewrite'), E('isolate', '## Task Signature', '## Input')], [['n1'],['n2']], subtype='same-repo unrelated negative')
case('D05', 'system', 'dedup', [E('pi1'), E('pi2')], [['n1','n2']], ['#612','7a362d6','240','Audit OK: 0 issues'], subtype='natural near-duplicate')
case('D06', 'system', 'dedup', [E('test1', '## Contract', '## Implementation constraints'), E('test2', '## Implementation', '## Workspace expansion')], [['n1','n2']], ['19','500','60,000','lib/wt.mjs','seam: 2'], subtype='partial-overlap system merge')
case('D07', 'system', 'dedup', [L('state', 'two cooperating writers'), L('state', 'pi-openviking `src/migration'), L('state', 'agent-tools `lib/wt')], [['n1','n2','n3']], ['src/migration-verifier.ts:230','lib/wt-openviking-sync.mjs:64-75','bin/wt:25'], subtype='three-note system merge')
case('D08', 'system', 'dedup', [E('observer', '## Contract', '## Display rules'), E('sync', '## Values', '## Specification')], [['n1'],['n2']], ['30','1933','number | null','pending_wt_land_syncs.length'], subtype='same-repo unrelated negative')
case('D09', 'decision', 'dedup', [L('badge', 'Backend #143 landed'), L('badge', 'Backend #143 landed')], [['n1','n2']], ['#143','2ed35cdc','#531','beef2019'], subtype='constructed exact duplicate')
case('D10', 'decision', 'dedup', [L('snapshot', 'R-SNAPSHOT-STALE-1 ('), L('badge', 'Architecture ruling R-SNAPSHOT-STALE-1')], [['n1','n2']], ['R-SNAPSHOT-STALE-1','15','5'], subtype='natural cross-note ruling overlap')
case('D11', 'decision', 'dedup', [L('showtell', 'Ops #898 landed implementation'), L('piweb', 'Ops #916 landed as')], [['n1'],['n2']], ['7d38d65','273-1e1414','7a6acb9','2026-11-14'], subtype='same-tooling-repo unrelated releases')
case('D12', 'preference', 'dedup', [E('deploy'), E('timing')], [['n1','n2']], ['pi-web-deploy','temper-deploy','--when-idle'], subtype='natural partial overlap')
case('D13', 'preference', 'dedup', [E('rm'), E('idempotent')], [['n1'],['n2']], ['~/.pi/openviking/seen-role-messages.json','rm-<id>'], subtype='related vocabulary different scope negative')
case('D14', 'preference', 'dedup', [L('deploy', 'For pi-web-ui'), L('timing', 'Requires pi-web-ui'), L('timing', 'Wants pending idle-wait')], [['n1','n2','n3']], ['pi-web-deploy','--when-idle'], subtype='three-note preference merge')

# 10 canonical-change sweeps. Excerpts are verbatim; assertions target active claims,
# never erase a historical record merely because the policy changed.
case('S01', 'system', 'sweep', [L('pi1', 'scope automatic attachment'), L('pi1', 'Audit OK: 0 issues')], [['n2']], ['Audit OK: 0 issues'], [E('retire', '# Summary', '# 2026-11-11')], ['n1'], 'retired automatic note attachment; keep unrelated audit fact')
case('S02', 'preference', 'sweep', [L('olddeploy', 'On 2026-11-12'), L('deploy', 'Install or restart')], [['n1'],['n2']], ['#157','9e138b48','pi-web-deploy'], [E('timing')], [], 'historical deployment assignment is not an active policy; retain history')
case('S03', 'preference', 'sweep', [L('notebook', 'For the requested Rule 34 cleanup'), L('notebook', 'Make each notebook rule')], [['n2']], ['240'], [E('post', '## Frozen backups and implementation')], ['n1'], 'retired notebook cleanup instruction superseded; preserve format constraint')
case('S04', 'decision', 'sweep', [E('retire', '# Summary', '# 2026-11-11')], [['n1']], ['#802','2026-11-11','notebook_retired','fallback_roles'], [E('restore', '# Summary', '# 2026-11-15'), E('post', '## Frozen backups and implementation')], [], 'restoration of frozen backups does not reverse retirement')
case('S05', 'system', 'sweep', [L('olddeploy', '2. Failing-first tests'), L('test2', 'No network, model calls')], [['n2']], ['60,000'], [E('snapshot', '## Health and freshness', '## Rationale and implementation')], ['n1'], 'code drift: obsolete 31-minute in-flight acceptance instruction superseded by 5-minute ruling')
case('S06', 'system', 'sweep', [L('entries', 'Architecture #537 requires every /entries response'), L('entries', 'This historical pi-web-ui contract')], [['n2']], ['#164','rm-a8311b06'], [E('entries', '# OpenViking dashboard entries contract', '## Listing fields')], ['n1'], 'code drift: retired endpoint active rule versus explicitly historical summary')
case('S07', 'decision', 'sweep', [L('snapshot', 'Backend #155 deployed'), L('snapshot', 'This historical /entries contract')], [['n1'],['n2']], ['7c38790','7acf602e','2026-11-12','#164'], [E('entries', '# OpenViking dashboard entries contract', '## Listing fields')], [], 'code drift negative: deployed-SHA historical fact survives endpoint removal')
case('S08', 'gotcha', 'sweep', [L('state', 'resource-sync-state.json never existed'), L('sync', 'Never derive synced_at')], [['n1'],['n2']], ['resource-sync-state.json','synced_at','updated_at'], [L('state', 'Live shape at 2026-11-11')], [], 'code drift negative: unrelated newer state cannot revoke absent-writer or timestamp guards')
case('S09', 'decision', 'sweep', [L('ledger', 'existed with 624 entries'), L('ledger', 'was genuinely absent before that')], [['n1'],['n2']], ['624','2026-11-11T23:50Z','#826'], [L('ledger', '200914 bytes')], [], 'code drift negative: successive dated counts and once-absent store are compatible')
case('S10', 'preference', 'sweep', [L('olddeploy', '6. `pi-web-deploy'), L('opsdeploy', 'Before restarting Temper')], [['n2']], ['Temper','pi-web-deploy'], [E('timing'), E('deploy')], ['n1'], 'non-code obsolete --when-idle action fragment versus current never-use guidance')


def build():
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    doc = {'version': 1, 'source_root': str(SOURCE), 'sampling': 'purposive stratified fixed excerpts, not random population sample',
           'cases': CASES}
    payload = json.dumps(doc, ensure_ascii=False, indent=2) + '\n'
    p = ROOT / 'cases.json'
    if p.exists() and p.read_text() != payload:
        raise ValueError('frozen cases id has different content; refuse')
    if not p.exists():
        p.write_text(payload)
    print(json.dumps({'cases': len(CASES), 'dedup': sum(c['task']=='dedup' for c in CASES),
                      'sweep': sum(c['task']=='sweep' for c in CASES),
                      'sha256': hashlib.sha256(payload.encode()).hexdigest()}))


if __name__ == '__main__':
    build()
