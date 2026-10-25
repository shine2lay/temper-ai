"""DECISION-11 (#125, task #280): W1 for Project 3's WebKit rows from two plain webkit-reading/1 readings.

Every case is a fixed input with a known right answer: the readings, receipts and W1 records are fixed files under
tmp_path, in the record shape Ops' reading tool writes (agent-tools docs/ops-host-chromium-reading.md, "WebKit
readings", Ops #534). No browser, MCP service, network, docker or host action: admission and the engine probe (the
first WebKit MCP call) are fakes that count their calls, and any socket connection fails the test.
"""
import asyncio
import datetime
import hashlib
import importlib.util
import json
import os
import socket
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BIN = Path(__file__).resolve().parents[2] / 'configs/architecture/bin'
if 'first_app_p3' not in sys.modules:
    spec = importlib.util.spec_from_file_location('first_app_p3', BIN / 'first_app_p3.py')
    p3 = importlib.util.module_from_spec(spec)
    sys.modules['first_app_p3'] = p3
    spec.loader.exec_module(p3)
p3 = sys.modules['first_app_p3']
w1 = p3.w1
g = p3.guard

ID = 'c' * 64
OTHER = 'd' * 64
PIN = p3.hc.ENGINE_PIN
NEW_IMAGE = 'sha256:' + 'e' * 64
WK = 'http://playwright-mcp-webkit:8931/mcp'
START = '2026-10-25T10:00:00.000+00:00'  # the run's start, as the checker writes it
FINISH = '2026-10-25T10:20:00.000+00:00'
BEFORE_AT = '2026-10-25T09:59:00.000000Z'
AFTER_AT = '2026-10-25T10:21:00.000000Z'
STARTED = '2026-10-20T19:51:36.763227153Z'  # Docker's StartedAt, nine digits
RECREATED = '2026-10-25T10:10:00.123456789Z'


@pytest.fixture(autouse=True)
def forbid_real_operations(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('W1 stage tests must never connect to anything')

    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


def endpoint(**changes):
    ep = {'alias': 'playwright-mcp-webkit', 'count': 1, 'holders': [ID], 'network': 'temper-ai_default'}
    ep.update(changes)
    return ep


def reading(taken_at=BEFORE_AT, **changes):
    """A clean webkit-reading/1 record; changes replace top-level keys."""
    rec = {'schema': 'webkit-reading/1', 'status': 'OK', 'reason': None, 'taken_at': taken_at, 'id': ID,
           'image': PIN, 'started_at': STARTED, 'restart_count': 0, 'running': True, 'paused': False,
           'restarting': False, 'networks': ['temper-ai_default'], 'endpoint': endpoint(), 'limits': w1.LIMITS}
    rec.update(changes)
    return rec


def without(key):
    rec = reading()
    del rec[key]
    return rec


def unknown(reason='container-inspect-failed', taken_at=BEFORE_AT):
    """An UNKNOWN record as the tool writes it: the fields it could not read are null."""
    return reading(taken_at, status='UNKNOWN', reason=reason, image=None, started_at=None, restart_count=None,
                   running=None, paused=None, restarting=None, networks=None, endpoint=None)


def write(folder, rec, name='before.json'):
    """One reading file; returns its reference {path, sha256}. rec may be raw bytes."""
    folder.mkdir(parents=True, exist_ok=True)
    data = rec if isinstance(rec, bytes) else json.dumps(rec, indent=1, sort_keys=True).encode()
    (folder / name).write_bytes(data)
    return {'path': str(folder / name), 'sha256': hashlib.sha256(data).hexdigest()}


def refused_rule(fn, *args):
    with pytest.raises(w1.Refused) as caught:
        fn(*args)
    return caught.value.rule


# ---- rule 2: the pre-check on the before-reading (before the first WebKit MCP call) ----

PRECHECK_CATCHES = {
    'extra key': (dict(reading(), extra=1), 'bad-schema:before'),
    'missing key': (without('restart_count'), 'bad-schema:before'),
    'wrong type': (reading(restart_count='0'), 'bad-schema:before'),
    'boolean restart count': (reading(restart_count=True), 'bad-schema:before'),
    'holders unsorted': (reading(endpoint=endpoint(count=2, holders=[OTHER, ID])), 'bad-schema:before'),
    'count not the number of holders': (reading(endpoint=endpoint(count=2)), 'bad-schema:before'),
    'another alias': (reading(endpoint=endpoint(alias='playwright-mcp')), 'bad-schema:before'),
    'another network': (reading(endpoint=endpoint(network='bridge')), 'bad-schema:before'),
    'status unknown': (unknown(), 'unknown:before'),
    'image not the pin': (reading(image=NEW_IMAGE), 'image-not-pin:before'),
    'running false': (reading(running=False), 'not-running:before'),
    'paused true': (reading(paused=True), 'paused:before'),
    'restarting true': (reading(restarting=True), 'restarting:before'),
    'state missing': (without('paused'), 'bad-schema:before'),
    'state not boolean': (reading(restarting='false'), 'bad-schema:before'),
    'state null': (reading(running=None), 'bad-schema:before'),
    'count 0': (reading(endpoint=endpoint(count=0, holders=[])), 'count-not-1:before'),
    'count 2': (reading(endpoint=endpoint(count=2, holders=[ID, OTHER])), 'count-not-1:before'),
    'holder not the id': (reading(endpoint=endpoint(holders=[OTHER])), 'holder-not-id:before'),
    'taken at the start': (reading('2026-10-25T10:00:00.000000Z'), 'before-not-earlier'),
    'taken after the start': (reading('2026-10-25T10:00:00.000001Z'), 'before-not-earlier'),
    'another schema': (reading(schema='chromium-reading/1'), 'bad-schema:before'),
    'another limits line': (reading(limits='readings are endpoint samples'), 'bad-schema:before'),
    'short id': (reading(id='c' * 12), 'bad-schema:before'),
    'networks unsorted': (reading(networks=['temper-ai_default', 'bridge']), 'bad-schema:before'),
    'ok with a reason': (reading(reason='docker-not-found'), 'bad-schema:before'),
    'unknown with another reason': (unknown(reason='made-up'), 'bad-schema:before'),
    'taken_at without microseconds': (reading('2026-10-25T09:59:00Z'), 'bad-schema:before'),
}


@pytest.mark.parametrize('case', sorted(PRECHECK_CATCHES))
def test_precheck_catches(tmp_path, case):
    rec, rule = PRECHECK_CATCHES[case]
    ref = write(tmp_path, rec)
    assert refused_rule(w1.precheck, ref, START) == rule
    gate = w1.gate(ref, START, WK)
    assert gate['status'] == 'REFUSED' and gate['rule'] == rule, gate
    assert gate['reason'].startswith(f'W1 before-reading refused: {rule}: ')
    assert gate['before'] == ref  # only the named file, never a reading's facts


def test_precheck_catches_wrong_sha256_symlinks_and_files_that_are_not_regular(tmp_path):
    ref = write(tmp_path, reading())
    assert refused_rule(w1.precheck, dict(ref, sha256='0' * 64), START) == 'sha256:before'
    (tmp_path / 'link.json').symlink_to(ref['path'])
    assert refused_rule(w1.precheck, dict(ref, path=str(tmp_path / 'link.json')), START) == 'missing:before'
    (tmp_path / 'linked').symlink_to(tmp_path)
    assert refused_rule(w1.precheck, dict(ref, path=str(tmp_path / 'linked/before.json')), START) == 'missing:before'
    os.mkfifo(tmp_path / 'fifo.json')
    assert refused_rule(w1.precheck, dict(ref, path=str(tmp_path / 'fifo.json')), START) == 'missing:before'
    (tmp_path / 'folder.json').mkdir()
    assert refused_rule(w1.precheck, dict(ref, path=str(tmp_path / 'folder.json')), START) == 'missing:before'
    assert refused_rule(w1.precheck, dict(ref, path=str(tmp_path / 'absent.json')), START) == 'missing:before'
    big = write(tmp_path, b' ' * (w1.READING_MAX + 1), 'big.json')
    assert refused_rule(w1.precheck, big, START) == 'missing:before'
    twice = write(tmp_path, b'{"schema": "webkit-reading/1", "schema": "webkit-reading/1"}', 'twice.json')
    assert refused_rule(w1.precheck, twice, START) == 'bad-schema:before'
    assert refused_rule(w1.precheck, write(tmp_path, b'[]', 'list.json'), START) == 'bad-schema:before'
    assert refused_rule(w1.precheck, write(tmp_path, b'\xff', 'bytes.json'), START) == 'bad-schema:before'


@pytest.mark.parametrize('ref', [[], {'path': 'before.json', 'sha256': 'a' * 64},
                                 {'path': '/x/before.json', 'sha256': 'A' * 64},
                                 {'path': '/x/before.json', 'sha256': 'a' * 64, 'id': ID}, {'path': '/x/b.json'}])
def test_precheck_input_must_be_exactly_path_and_sha256(ref):
    assert w1.ref_problems(ref)
    assert refused_rule(w1.precheck, ref, START) == 'input'
    assert w1.gate(ref, START, WK)['status'] == 'REFUSED'


def test_clean_before_reading_is_provisional_with_its_facts(tmp_path):
    ref = write(tmp_path, reading())
    assert w1.ref_problems(ref) == [] and w1.precheck(ref, START) == reading()
    gate = w1.gate(ref, START, WK)
    assert gate['status'] == 'PROVISIONAL' and gate['rule'] is None and gate['reason'] is None
    assert gate['before'] == dict(ref, **{key: reading()[key] for key in w1.FACTS})
    assert gate['note'] == 'W1: provisional until the after-check' and gate['finalize'] == w1.FINALIZE
    assert w1.gate(ref, '2026-10-25T09:59:00.000001Z', WK)['status'] == 'PROVISIONAL'  # one microsecond later


def test_no_before_reading_is_not_given():
    gate = w1.gate(None, START, WK)
    assert gate['status'] == 'NOT GIVEN' and gate['before'] is None
    assert gate['reason'] == w1.MISSING == p3.W1_MISSING


def test_a_reader_bug_is_refused_never_provisional(monkeypatch, tmp_path):
    ref = write(tmp_path, reading())
    monkeypatch.setattr(w1, 'semantics', lambda rec, side: 1 / 0)
    gate = w1.gate(ref, START, WK)
    assert gate['status'] == 'REFUSED' and gate['rule'] == 'error' and 'ZeroDivisionError' in gate['reason']


# ---- rule 2 wired into the WebKit session start: no WebKit MCP call before the pre-check passes ----

@pytest.fixture
def webkit_calls(monkeypatch):
    """What _webkit_gate may call after the pre-check: admission (reads receipts) and the engine probe (the first
    WebKit MCP call). Both are fakes that count."""
    calls = []

    def admitted(r, latch, target, url, webkit):
        calls.append(('admitted', url, webkit, (r.get('w1') or {}).get('status')))
        return True

    async def probe(url, target, r, latch):
        calls.append(('probe', url))
        return {'type': 'webkit', 'version': 'fake-1'}

    monkeypatch.setattr(p3, 'admitted', admitted)
    monkeypatch.setattr(p3, 'engine_probe', probe)
    return calls


def run_gate(ref, start=START):
    """_webkit_gate on a fixed target; a live run has no invocation start (start None): its receipt's own counts."""
    target = {'engine_image': PIN, **({'w1_start': start} if start else {}), **({'w1_before': ref} if ref else {})}
    r, sess, latch = {'started_at': '2026-10-25T09:00:00.000+00:00', 'steps': [], 'sessions': {}}, {}, g.StopLatch()
    ok = asyncio.run(p3._webkit_gate(r, target, {}, latch, WK, sess, p3.ROW_IDS['webkit'] + ['PH-1']))
    return ok, r, sess, latch


def test_no_before_reading_leaves_webkit_not_run_with_no_mcp_call(webkit_calls):
    ok, r, sess, latch = run_gate(None)
    assert not ok and webkit_calls == [] and not latch.stopped
    assert sess == {'status': 'NOT RUN', 'why': w1.MISSING} and r['w1']['status'] == 'NOT GIVEN'
    assert len(r['steps']) == len(p3.ROW_IDS['webkit']) + 1
    assert all(s['status'] == 'NOT RUN' and s['reasons'] == [w1.MISSING] for s in r['steps'])


@pytest.mark.parametrize('case', ['paused true', 'holder not the id', 'taken at the start', 'status unknown',
                                  'count 2'])
def test_failing_precheck_leaves_webkit_not_run_with_the_first_failing_rule(tmp_path, webkit_calls, case):
    rec, rule = PRECHECK_CATCHES[case]
    ok, r, sess, latch = run_gate(write(tmp_path, rec))
    assert not ok and webkit_calls == []
    assert sess['status'] == 'NOT RUN' and sess['why'].startswith(f'W1 before-reading refused: {rule}: ')
    assert r['w1']['rule'] == rule and all(s['status'] == 'NOT RUN' for s in r['steps'])


def test_image_not_the_pin_blocks_and_names_the_image_for_security(tmp_path, webkit_calls):
    ok, r, sess, latch = run_gate(write(tmp_path, reading(image=NEW_IMAGE)))
    assert not ok and webkit_calls == [] and latch.blocked
    assert r['security_fyi']['new_image_id'] == NEW_IMAGE and 'image-not-pin:before' in sess['why']


def test_clean_precheck_comes_before_admission_and_the_first_webkit_mcp_call(tmp_path, webkit_calls):
    ref = write(tmp_path, reading())
    ok, r, sess, latch = run_gate(ref)
    assert ok and not latch.stopped
    assert webkit_calls == [('admitted', WK, True, 'PROVISIONAL'), ('probe', WK)]
    assert r['w1']['status'] == 'PROVISIONAL' and r['w1']['before']['sha256'] == ref['sha256']
    # A live run (no invocation start) is judged against its receipt's start, 09:00: 09:59 is too late.
    ok, r, sess, latch = run_gate(ref, start=None)
    assert not ok and r['w1']['rule'] == 'before-not-earlier'
    ok, r, sess, latch = run_gate(write(tmp_path, reading('2026-10-25T08:59:59.999999Z'), 'early.json'), start=None)
    assert ok and r['w1']['status'] == 'PROVISIONAL'


def test_profile_and_flag_name_the_before_reading_as_path_and_sha256():
    raw = g.snapshot(p3.FIXTURE, p3.CTYPES)
    profile = p3.default_p3_profile(pins={n: p3.fac.sha256(b) for n, b in raw.items()})
    ref = {'path': '/runs/w1/before.json', 'sha256': 'a' * 64}
    t, problems = p3.parse_p3_profile(json.dumps(dict(profile, w1_before=ref)))
    assert not problems and t['w1_before'] == ref
    t, problems = p3.parse_p3_profile(json.dumps(dict(profile, w1_before={'path': 'before.json'})))
    assert any('w1_before' in x for x in problems)
    target = {}  # the controls: --w1-before and the invocation's own start
    p3.bind_admission(target, SimpleNamespace(w1_before=ref, invocation_started_at=START))
    assert target == {'w1_before': ref, 'w1_start': START}


# ---- rule 3: every WebKit step names the before-reading and stays PROVISIONAL ----

def test_mark_steps_names_the_before_reading_on_every_webkit_step_and_never_passes():
    r = {'w1': {'status': 'PROVISIONAL', 'before': {'path': '/runs/before.json', 'sha256': 'f' * 64, 'id': ID}},
         'steps': [{'id': 'A', 'engine': 'webkit', 'status': 'PASS'}, {'id': 'B', 'engine': 'webkit', 'status': 'FAIL'},
                   {'id': 'C', 'engine': 'webkit', 'status': 'NOT RUN'},
                   {'id': 'D', 'engine': 'chromium', 'status': 'PASS'}]}
    w1.mark_steps(r)
    w1.mark_steps(r)  # idempotent: the controls finish a receipt twice
    named = {'before': {'path': '/runs/before.json', 'sha256': 'f' * 64},
             'note': 'W1: provisional until the after-check'}
    a, b, c, d = r['steps']
    assert a == {'id': 'A', 'engine': 'webkit', 'status': 'PROVISIONAL', 'measured': 'PASS', 'w1': named}
    assert b == {'id': 'B', 'engine': 'webkit', 'status': 'FAIL', 'w1': named}
    assert c == {'id': 'C', 'engine': 'webkit', 'status': 'NOT RUN', 'w1': named}
    assert d == {'id': 'D', 'engine': 'chromium', 'status': 'PASS'}
    assert [w1.measured(s) for s in r['steps']] == ['PASS', 'FAIL', 'NOT RUN', 'PASS']
    for status in ('REFUSED', 'NOT GIVEN'):
        r = {'w1': {'status': status}, 'steps': [{'id': 'A', 'engine': 'webkit', 'status': 'NOT RUN'}]}
        w1.mark_steps(r)
        assert r['steps'] == [{'id': 'A', 'engine': 'webkit', 'status': 'NOT RUN'}]


# ---- rule 5: finalize, files only, one new 0600 W1 record next to the receipt ----

def run_folder(tmp_path, before=None, *, w1_status='PROVISIONAL', name='receipt.json', **changes):
    """A finished run's receipt (journey p3, a PROVISIONAL W1 naming its before-reading) in its own folder."""
    ref = write(tmp_path / 'readings', before or reading())
    d = {'journey': 'p3', 'started_at': START, 'finished_at': FINISH, 'verdict': 'BLOCKED',
         'w1': {'service': WK, 'status': w1_status, 'before': dict(ref, id=ID), 'note': w1.NOTE}}
    d.update(changes)
    (tmp_path / 'run').mkdir(exist_ok=True)
    (tmp_path / 'run' / name).write_text(json.dumps(d))
    return tmp_path / 'run' / name, ref


def after(tmp_path, rec=None, name='after.json'):
    return write(tmp_path / 'readings', rec or reading(AFTER_AT), name)


def finalize(receipt, aft):
    return w1.finalize(str(receipt), aft['path'], aft['sha256'])


def saved(receipt):
    out = receipt.parent / 'w1.json'
    st = os.lstat(out)
    assert stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o600
    return json.loads(out.read_text())


def test_finalize_count_writes_one_new_closed_0600_record_and_changes_no_input(tmp_path):
    receipt, before = run_folder(tmp_path)
    aft = after(tmp_path)
    receipt_sha = hashlib.sha256(receipt.read_bytes()).hexdigest()
    code, record, text = finalize(receipt, aft)
    assert (code, text) == (0, 'COUNT')
    got = saved(receipt)
    assert got == record and sorted(got) == ['after', 'before', 'finalized_at', 'limits', 'receipt', 'result',
                                             'rule', 'schema']
    assert got['result'] == 'COUNT' and got['rule'] is None and got['schema'] == 'p3-w1/1'
    assert got['before'] == before and got['after'] == aft and got['limits'] == w1.LIMITS
    assert got['receipt'] == {'path': str(receipt), 'sha256': receipt_sha}
    assert datetime.datetime.fromisoformat(got['finalized_at']).utcoffset() == datetime.timedelta(0)
    # Read-only on its inputs: the receipt and both readings are unchanged, and only w1.json is new.
    assert hashlib.sha256(receipt.read_bytes()).hexdigest() == receipt_sha
    for ref in (before, aft):
        assert hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest() == ref['sha256']
    assert sorted(os.listdir(receipt.parent)) == ['receipt.json', 'w1.json']


def test_finalize_count_on_a_controls_summary(tmp_path):
    receipt, _ = run_folder(tmp_path, name='controls.json', mode='controls_p3',
                            w1={'status': 'PROVISIONAL', 'before': None, 'cases': {}, 'note': w1.NOTE})
    d = json.loads(receipt.read_text())
    d['w1']['before'] = write(tmp_path / 'readings', reading())
    receipt.write_text(json.dumps(d))
    assert finalize(receipt, after(tmp_path))[:1] == (0,) and saved(receipt)['result'] == 'COUNT'


FINALIZE_CATCHES = {
    'id differs': (None, reading(AFTER_AT, id=OTHER, endpoint=endpoint(holders=[OTHER])), 'field-differs:id'),
    'image differs': (None, reading(AFTER_AT, image=NEW_IMAGE), 'field-differs:image'),
    'started_at differs': (None, reading(AFTER_AT, started_at=RECREATED), 'field-differs:started_at'),
    'restart_count differs': (None, reading(AFTER_AT, restart_count=1), 'field-differs:restart_count'),
    'networks differ': (None, reading(AFTER_AT, networks=['bridge', 'temper-ai_default']), 'field-differs:networks'),
    'recreated with the same image': (None, reading(AFTER_AT, id=OTHER, started_at=RECREATED,
                                                    endpoint=endpoint(holders=[OTHER])), 'field-differs:id'),
    'restarted in place, same image': (None, reading(AFTER_AT, started_at=RECREATED, restart_count=1),
                                       'field-differs:started_at'),
    'after at the finish': (None, reading('2026-10-25T10:20:00.000000Z'), 'after-not-later'),
    'after before the finish': (None, reading('2026-10-25T10:19:59.999999Z'), 'after-not-later'),
    'before at the start': (reading('2026-10-25T10:00:00.000000Z'), None, 'before-not-earlier'),
    'before after the start': (reading('2026-10-25T10:05:00.000000Z'), None, 'before-not-earlier'),
    'after paused': (None, reading(AFTER_AT, paused=True), 'paused:after'),
    'after not running': (None, reading(AFTER_AT, running=False), 'not-running:after'),
    'after restarting': (None, reading(AFTER_AT, restarting=True), 'restarting:after'),
    'after second holder': (None, reading(AFTER_AT, endpoint=endpoint(count=2, holders=[ID, OTHER])),
                            'count-not-1:after'),
    'after holder not the id': (None, reading(AFTER_AT, id=ID, endpoint=endpoint(holders=[OTHER])),
                                'holder-not-id:after'),
    'after unknown': (None, unknown(taken_at=AFTER_AT), 'unknown:after'),
    'after extra key': (None, dict(reading(AFTER_AT), extra=1), 'bad-schema:after'),
    'after state missing': (None, {k: v for k, v in reading(AFTER_AT).items() if k != 'restarting'},
                            'bad-schema:after'),
}


@pytest.mark.parametrize('case', sorted(FINALIZE_CATCHES))
def test_finalize_catches(tmp_path, case):
    before, aft, rule = FINALIZE_CATCHES[case]
    receipt, _ = run_folder(tmp_path, before)
    code, record, text = finalize(receipt, after(tmp_path, aft))
    assert code == 1 and record['result'] == 'BLOCKED' and text == record['rule']
    assert record['rule'].startswith(rule + ': '), record['rule']
    assert saved(receipt) == record


def test_finalize_catches_wrong_after_hash_and_a_before_reading_changed_since_the_run(tmp_path):
    receipt, before = run_folder(tmp_path)
    aft = after(tmp_path)
    code, record, _ = w1.finalize(str(receipt), aft['path'], '0' * 64)
    assert code == 1 and record['rule'].startswith('sha256:after: ')
    receipt, before = run_folder(tmp_path / 'second')
    Path(before['path']).write_text(json.dumps(reading(paused=True)))
    code, record, _ = finalize(receipt, after(tmp_path / 'second'))
    assert code == 1 and record['rule'].startswith('sha256:before: ')


@pytest.mark.parametrize('fault', ['refused', 'not given', 'journey', 'no finish', 'not json', 'no before'])
def test_finalize_blocks_a_receipt_without_a_provisional_w1(tmp_path, fault):
    status = {'refused': 'REFUSED', 'not given': 'NOT GIVEN'}.get(fault, 'PROVISIONAL')
    receipt, _ = run_folder(tmp_path, w1_status=status)
    d = json.loads(receipt.read_text())
    if fault == 'journey':
        d['journey'] = 'p2'
    if fault == 'no finish':
        del d['finished_at']
    if fault == 'no before':
        d['w1']['before'] = None
    receipt.write_text('{"journey": "p3",' if fault == 'not json' else json.dumps(d))
    code, record, _ = finalize(receipt, after(tmp_path))
    assert code == 1 and record['result'] == 'BLOCKED' and record['rule'].startswith('receipt: ')
    assert saved(receipt)['result'] == 'BLOCKED'


def test_finalize_never_overwrites_an_existing_record(monkeypatch, tmp_path):
    receipt, _ = run_folder(tmp_path)
    aft = after(tmp_path)
    out = receipt.parent / 'w1.json'
    out.write_text('kept\n')
    out.chmod(0o644)
    code, record, text = finalize(receipt, aft)
    assert (code, record) == (2, None) and 'never overwritten' in text
    assert out.read_text() == 'kept\n' and stat.S_IMODE(os.lstat(out).st_mode) == 0o644
    out.unlink()
    assert finalize(receipt, aft)[0] == 0
    first = out.read_bytes()
    assert finalize(receipt, aft)[:2] == (2, None) and out.read_bytes() == first  # a second finalize
    out.unlink()
    out.symlink_to(tmp_path / 'elsewhere.json')  # a dangling link is never followed
    assert finalize(receipt, aft)[0] == 2 and not (tmp_path / 'elsewhere.json').exists()
    out.unlink()
    out.write_text('raced\n')  # a record that appears after the first look: the exclusive create refuses it
    monkeypatch.setattr(w1.os.path, 'lexists', lambda path: False)
    assert finalize(receipt, aft)[:2] == (2, None) and out.read_text() == 'raced\n'


def test_finalize_refuses_bad_input_and_an_unreadable_receipt_writing_nothing(tmp_path):
    receipt, _ = run_folder(tmp_path)
    aft = after(tmp_path)
    assert w1.finalize('receipt.json', aft['path'], aft['sha256'])[:2] == (2, None)
    assert w1.finalize(str(receipt), 'after.json', aft['sha256'])[:2] == (2, None)
    assert w1.finalize(str(receipt), aft['path'], 'A' * 64)[:2] == (2, None)
    (tmp_path / 'linked').mkdir()
    (tmp_path / 'linked' / 'receipt.json').symlink_to(receipt)
    assert w1.finalize(str(tmp_path / 'linked/receipt.json'), aft['path'], aft['sha256'])[:2] == (2, None)
    assert not (receipt.parent / 'w1.json').exists() and not (tmp_path / 'linked' / 'w1.json').exists()


def test_a_reader_bug_in_finalize_is_blocked_never_count(monkeypatch, tmp_path):
    receipt, _ = run_folder(tmp_path)
    monkeypatch.setattr(w1, 'semantics', lambda rec, side: 1 / 0)
    code, record, _ = finalize(receipt, after(tmp_path))
    assert code == 1 and record['rule'].startswith('error: ZeroDivisionError')


def test_finalize_command_line(tmp_path, capsys):
    receipt, _ = run_folder(tmp_path)
    aft = after(tmp_path)
    argv = ['finalize', '--receipt', str(receipt), '--after', aft['path'], '--after-sha256', aft['sha256']]
    assert w1.main(argv) == 0
    line, limits = capsys.readouterr().out.splitlines()
    assert json.loads(line) == {'record': str(receipt.parent / 'w1.json'), 'result': 'COUNT', 'rule': None}
    assert limits == w1.LIMITS
    assert w1.main(argv) == 2
    assert json.loads(capsys.readouterr().out.splitlines()[0])['result'] == 'NOT WRITTEN'
    receipt, _ = run_folder(tmp_path / 'blocked', reading('2026-10-25T10:00:00.000000Z'))
    assert w1.main(['finalize', '--receipt', str(receipt), '--after', aft['path'], '--after-sha256',
                    aft['sha256']]) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[0])['rule'].startswith('before-not-earlier: ')
