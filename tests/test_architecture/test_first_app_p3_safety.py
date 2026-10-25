"""#129 source-boundary stage: fixed files, EventEmitters and fake transports only; never qualification."""
import asyncio
import base64
import contextlib
import datetime
import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
import threading
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
g = p3.guard
ORIGIN = 'http://100.110.162.4:8962'
EXACT = 'https://outside.invalid/a?' + 'long=abcdef&' * 150 + 'literal=%22%3C%26&end=last'
NODE = Path(__file__).parent / 'fixtures/p3_fake_browser.cjs'


@pytest.fixture(autouse=True)
def forbid_real_operations(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('source-only tests must never connect/start a real service')

    @contextlib.asynccontextmanager
    async def no_session(*a, **kw):
        forbidden()
        yield

    monkeypatch.setattr(p3, 'open_session', no_session)
    monkeypatch.setattr(p3.http.server, 'ThreadingHTTPServer', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(p3.fs, 'serve_ip', lambda *a: '100.110.162.4')


def target():
    raw = g.snapshot(p3.FIXTURE, p3.CTYPES)
    t, problems = p3.parse_p3_profile(json.dumps(p3.default_p3_profile(
        pins={n: p3.fac.sha256(b) for n, b in raw.items()})))
    assert not problems
    return t


def node_case(code, engine='chromium', **kw):
    payload = dict(code=code, engine=engine, files={n: b.decode() for n, b in g.snapshot(p3.FIXTURE, p3.CTYPES).items()},
                   ctypes=p3.CTYPES, close=p3.CLOSE, url=EXACT, **kw)
    # Adapt the old fixed fake in memory to Page.close/Context.pages, without changing fixture bytes.
    harness = NODE.read_text().replace('.pages', '.items')
    harness = harness.replace('  async goto(url) {', '  async close() { this.closed = true; }\n  async goto(url) {')
    harness = harness.replace('  browser() { return browser; }',
                              '  pages() { return this.items.filter(p => !p.closed); }\n  browser() { return browser; }')
    harness = harness.replace('contexts.length - 1', 'contexts.filter(c => c !== rootCtx).length')
    harness = harness.replace("if (input.fault === 'close')", "if (input.fault === 'close' && !this.isRoot)")
    proc = subprocess.run(['node', '-e', harness], input=json.dumps(payload), text=True,
                          capture_output=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture
def chromium_ab(monkeypatch):
    """The R1 disposal fakes (R1_NODE, clean_close) make contexts A and B; these tests are about disposal, not
    the canonical six Chromium contexts, so Chromium expects A and B here."""
    monkeypatch.setitem(p3.ENGINES['chromium'], 'contexts', ('A', 'B'))


def clean_close(names, log=None):
    return {'contexts': {n: {'error': None, 'page_created': True, 'page_closed': True,
                            'context_still_in_browser': False} for n in names},
            'other_contexts_left': 0, 'guard_page_closed': True, 'guard_context_closed': True,
            'journal': {'status': 'complete', 'reasons': []}, 'log': log or {}}


def empty_receipts_root(t, tmp_path):
    """W1 admission (#125 4b) reads earlier receipts; these journeys start with none."""
    (tmp_path / 'receipts').mkdir()
    t['receipts_root'] = str(tmp_path / 'receipts')


def event(url=EXACT):
    return {'requests': [{'ctx': 'fake', 't': 'fixed', 'method': 'GET', 'url': url,
                          'type': 'script', 'navigation': False}]}


def passing(r):
    """A receipt whose rows all pass: every expected step PASS, both copies pinned, the W1 before-reading checked
    (PROVISIONAL, DECISION-11), cleanup confirmed. Its verdict is W1 pending, never PASS, until finalize."""
    r.update(pins={'ok': True}, pins_webkit={'ok': True}, reach={},
             steps=[{'id': i, 'engine': e, 'kind': 'browser', 'status': 'PASS', 'traffic': [], 'reasons': [],
                     'notes': []} for e, i in p3.EXPECTED_STEPS], steps_attempted=len(p3.EXPECTED_STEPS),
             sessions={e: {'status': 'RAN', 'before_first_navigation': True} for e in p3.ENGINES},
             cleanup={e: {'confirmed': True} for e in p3.ENGINES},
             w1={'service': p3.WEBKIT_URL, 'status': 'PROVISIONAL', 'rule': None, 'reason': None,
                 'before': {'path': '/runs/w1-before.json', 'sha256': 'c' * 64, 'id': 'c' * 64,
                            'image': p3.hc.ENGINE_PIN}, 'note': p3.w1.NOTE})
    return r


def w1_before(tmp_path):
    """A webkit-reading/1 before-reading (DECISION-11) that passes the pre-check, taken before any run here."""
    rec = {'schema': 'webkit-reading/1', 'status': 'OK', 'reason': None, 'taken_at': '2026-10-20T20:00:00.000000Z',
           'id': 'c' * 64, 'image': p3.hc.ENGINE_PIN, 'started_at': '2026-10-20T19:51:36.763227153Z',
           'restart_count': 0, 'running': True, 'paused': False, 'restarting': False,
           'networks': ['temper-ai_default'], 'endpoint': {'alias': 'playwright-mcp-webkit', 'count': 1,
                                                           'holders': ['c' * 64], 'network': 'temper-ai_default'},
           'limits': p3.w1.LIMITS}
    folder = tmp_path / 'w1-readings'
    folder.mkdir(exist_ok=True)
    data = json.dumps(rec).encode()
    (folder / 'before.json').write_bytes(data)
    return {'path': str(folder / 'before.json'), 'sha256': p3.fac.sha256(data)}


def assert_w1_pending(r):
    """DECISION-11 rule 3: rows that all pass leave the run BLOCKED (W1 pending), never PASS, with every WebKit
    step PROVISIONAL and naming the before-reading, until finalize says COUNT."""
    assert r['verdict'] == 'BLOCKED' and r['why'].startswith(p3.w1.PENDING) and r['exit_code'] == 3, r['why']
    assert r['w1']['status'] == 'PROVISIONAL' and r['w1']['on_count'] == 'PASS'
    named = {'path': r['w1']['before']['path'], 'sha256': r['w1']['before']['sha256']}
    webkit = [s for s in r['steps'] if s['engine'] == 'webkit']
    assert len(webkit) == len(p3.ROW_IDS['webkit']) + 1  # the rows and PH-1
    for s in webkit:
        assert s['status'] == 'PROVISIONAL' and s['measured'] == 'PASS', s
        assert s['w1'] == {'before': named, 'note': 'W1: provisional until the after-check'}
    assert all(s['status'] == 'PASS' and 'w1' not in s for s in r['steps'] if s['engine'] == 'chromium')


# Happy paths first, then the exact faults in the same event/lifetime boundaries.
@pytest.mark.parametrize('engine', ['chromium', 'webkit'])
@pytest.mark.parametrize('kind', ['setup', 'pins', 'engine'])
def test_generated_contexts_block_sw_and_observe_before_navigation(engine, kind):
    js = p3.setup_js(target(), engine) if kind == 'setup' else p3.probe_js(target(), kind, engine)
    data = node_case(js, engine)
    assert not data['error'] and not data['close_error']
    assert all(o['serviceWorkers'] == 'block' for o in data['options'])
    assert len(data['options']) == (len(p3.ENGINES[engine]['contexts']) if kind == 'setup' else 1)
    assert data['contexts_left'] == 0
    if kind != 'setup':
        assert data['result']['closed'] and data['result']['observers_at']
        assert data['result']['log']['requests'] == []


@pytest.mark.parametrize(('kind', 'phase'), [(kind, phase) for kind in ['pins', 'engine']
                                            for phase in ['newPage', 'goto', 'close']
                                            if (kind, phase) != ('engine', 'goto')])
def test_probe_event_witnesses_and_sw_failures_survive_terminal_paths(kind, phase):
    data = node_case(p3.probe_js(target(), kind), at=phase,
                     fault='navigation' if phase == 'goto' else '')
    result = data['result']
    log = result['log']
    assert log['requests'][0]['url'] == EXACT and log['failed'][0]['url'] == EXACT
    assert log['responses'][0]['url'] == EXACT and log['serviceworkers'][0]['url'] == EXACT
    assert 'registration' in log['pageerrors'][0]['message'] and log['console']
    assert log['websockets'][0]['url'] == EXACT
    if phase == 'goto':
        assert result['error'] == 'net::ERR_FIXED_NAVIGATION'
    if kind == 'pins' and phase != 'goto':
        assert result['root']['b64'] and result['files']['app.js']['b64']
    assert result['closed'] and data['contexts_left'] == 0


@pytest.mark.parametrize('fail_at', [1, 2])
def test_partial_setup_tracks_context_even_without_page_and_disposes(fail_at):
    data = node_case(p3.setup_js(target(), 'chromium'), fault='newPage', failAt=fail_at, at='newPage')
    assert data['error'] and 'newPage' in data['error']
    assert len(data['tracked']) == fail_at and data['contexts_left'] == 0
    assert len(data['close_result']['contexts']) == fail_at
    assert not list(data['close_result']['contexts'].values())[-1]['page_created']
    assert data['close_result']['log']['requests'][0]['url'] == EXACT


def test_js_close_failure_retains_final_events_not_just_route_or_dom_refs():
    data = node_case(p3.probe_js(target(), 'pins'), fault='close', at='close')
    assert data['result']['files']['app.js']['b64'] and not data['result']['closed']
    assert data['result']['log']['requests'][0]['url'] == EXACT
    assert data['close_result']['log']['requests'][0]['url'] == EXACT
    assert data['contexts_left'] == 1


def test_sticky_w4_exact_events_and_same_origin_are_distinct(tmp_path):
    latch = g.StopLatch()
    r = passing(p3.new_receipt('fake', target()))
    for url in [ORIGIN + '/unexpected?x=1', 'ws://100.110.162.4:8962/channel']:
        p3.collect(r, event(url), ORIGIN, latch, 'same-origin')
    assert not latch.stopped and p3.final_verdict(r)[0] == 'FAIL'
    p3.collect(r, event(), ORIGIN, latch, 'late-close')
    assert latch.tripped and p3.final_verdict(r)[0] == 'W4 TRIPPED'
    latch.observe(r, {}, ORIGIN, 'later-clean-case')
    p3.finish(r, tmp_path)
    assert r['exit_code'] == 4 and r['w4']['observations'][0]['url'] == EXACT
    for name in ['receipt.json', 'observations.json', 'summary.md']:
        f = tmp_path / name
        assert stat.S_ISREG(f.lstat().st_mode) and stat.S_IMODE(f.stat().st_mode) == 0o600
        assert EXACT in f.read_text()
    assert json.loads((tmp_path / 'observations.json').read_text())['requests'][-1]['url'] == EXACT
    hold = r['w4']['operator_hold']
    assert 'queue_blocked' in hold and 'Only Security' in hold and 'CLI invocation' in hold


@pytest.mark.parametrize('kind', ['requests', 'responses', 'failed', 'websockets', 'serviceworkers', 'popups'])
def test_w4_all_observed_destinations_no_expected_exception_list(kind):
    latch = g.StopLatch()
    latch.observe({}, {kind: [{'url': EXACT}]}, ORIGIN, kind)
    assert latch.tripped and latch.observations[0]['url'] == EXACT
    latch.bind({})
    assert latch.tripped
    # DOM references and abort-route descriptions are not independent event witnesses.
    control = g.StopLatch()
    control.observe({}, {'refs': [EXACT], 'api_blocked': [{'url': EXACT}]}, ORIGIN, 'not-witnesses')
    assert not control.stopped


@pytest.mark.parametrize(('verdict', 'code'), [('PASS', 0), ('FAIL', 1), ('BLOCKED', 3),
                                               ('REFUSED', 2), ('W4 TRIPPED', 4)])
def test_p3_exit_codes_reserve_four_for_w4_and_leave_blocked_and_legacy_unchanged(verdict, code):
    assert p3.exit_status({'verdict': verdict}) == code
    assert p3.fac.EXIT == {'PASS': 0, 'FAIL': 1, 'REFUSED': 2, 'BLOCKED': 3}


@pytest.mark.parametrize(('origin', 'url', 'outside'), [
    ('http://fixture.invalid', 'http://fixture.invalid:80/a', False),
    ('https://fixture.invalid', 'https://fixture.invalid:443/a', False),
    ('http://fixture.invalid:80', 'ws://fixture.invalid/a', False),
    ('https://fixture.invalid:443', 'wss://fixture.invalid/a', False),
    ('http://fixture.invalid', 'http://fixture.invalid:0/a', True),
    ('https://fixture.invalid', 'https://fixture.invalid:0/a', True),
    ('http://fixture.invalid:80', 'ws://fixture.invalid:81/a', True),
    ('https://fixture.invalid:443', 'wss://fixture.invalid:444/a', True),
])
def test_w4_origin_defaults_never_exempt_an_explicit_different_port(origin, url, outside):
    latch = g.StopLatch()
    latch.observe({}, event(url), origin, 'fixed-origin')
    assert latch.tripped == outside and not latch.blocked
    assert [x['url'] for x in latch.observations] == ([url] if outside else [])


# R1's five end-to-end fakes execute the actual guard on fixed EventEmitter objects.
# The only subprocess is Node; this harness has no browser/MCP/socket/HTTP dependency.
R1_NODE = r"""
const {EventEmitter} = require('node:events');
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const contexts = [], sequence = [];
class Page extends EventEmitter {
  constructor(ctx) { super(); this.ctx = ctx; this.closed = false; }
  context() { return this.ctx; }
  url() { return 'about:blank'; }
  isClosed() { return this.closed; }
  async close(options) {
    sequence.push('page-close:' + this.ctx.name + ':' + options.runBeforeUnload);
    if (this.ctx.name === 'guard') {
      if (input.fault === 'guard_alive') return;
      if (input.fault === 'guard_error') throw new Error('fixed guard close failure');
      if (input.fault === 'guard_event') this.ctx.emit('request', {method: () => 'GET', url: () => input.url,
        resourceType: () => 'script', isNavigationRequest: () => false});
    }
    if (this.ctx.name === 'A') {
      if (input.fault === 'F1') {
        const r = {method: () => 'GET', url: () => input.url, resourceType: () => 'script',
          isNavigationRequest: () => false};
        this.ctx.emit('request', r);
      }
      if (input.fault === 'F4') throw new Error('fixed escalation failure');
      if (['F2', 'F3'].includes(input.fault)) return;
    }
    this.closed = true;
  }
}
class Context extends EventEmitter {
  constructor(name) { super(); this.name = name; this.items = []; this.calls = 0; contexts.push(this); }
  browser() { return browser; }
  pages() { return this.items.filter(p => !p.closed); }
  async newPage() { const p = new Page(this); this.items.push(p); this.emit('page', p); return p; }
  async close() {
    sequence.push('context-close:' + this.name + ':' + ++this.calls);
    if (this.name === 'guard') {
      if (input.fault === 'carrier_context_error') throw new Error('fixed carrier context close failure');
      if (['carrier_context_alive', 'guard_alive'].includes(input.fault)) return;
    }
    if (this.name === 'A' && ['F1', 'F2', 'F3', 'F4'].includes(input.fault) &&
        (this.calls === 1 || ['F2', 'F3'].includes(input.fault)))
      throw new Error('fixed original CLOSE failure');
    this.items.forEach(p => { p.closed = true; });
    if (contexts.includes(this)) contexts.splice(contexts.indexOf(this), 1);
  }
}
const browser = {contexts: () => contexts.slice()};
const rootCtx = new Context('guard');
const root = new Page(rootCtx); rootCtx.items.push(root);
if (input.fault === 'untracked') rootCtx.items.push(new Page(rootCtx));
if (input.fault === 'other_context') { const c = new Context('unknown'); c.items.push(new Page(c)); }
(async () => {
  await eval('(async (page) => { const browser = page.context().browser();' + input.observers + `
    const drain = p3.drain;
    p3.drain = () => { sequence.push('drain'); return drain(); };
    for (const name of ['A', 'B']) {
      const u = p3.attach(new Context(name), name, false);
      u.p = await u.ctx.newPage(); u.attachPage(u.p);
    }
  })`)(root);
  let result = null, error = null;
  try { result = await eval('(' + input.close + ')')(root); } catch (e) { error = String(e); }
  console.log(JSON.stringify({result, error, sequence, guard_closed: root.isClosed(),
    live: contexts.flatMap(c => c.pages()).length, contexts_left: contexts.length}));
})().catch(e => { console.error(String(e)); process.exitCode = 1; });
"""


def r1_close_case(fault):
    proc = subprocess.run(['node', '-e', R1_NODE],
                          input=json.dumps(dict(observers=g.OBSERVERS, close=p3.CLOSE, fault=fault, url=EXACT)),
                          text=True, capture_output=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert not data['error'], data['error']
    return data


class FakeTransport:
    def __init__(self, kind, fail_close=False):
        self.kind = kind
        self.browser_closes = 0
        self.fail_close = fail_close

    async def initialize(self):
        assert not self.browser_closes

    async def call_tool(self, name, args):
        assert not self.browser_closes, 'MCP call after browser_close'
        assert name == 'browser_close'
        self.browser_closes += 1
        if self.fail_close == 'timeout':
            raise TimeoutError('fixed fallback timeout')
        if self.fail_close == 'cancel':
            raise asyncio.CancelledError
        if self.fail_close == 'unknown':
            return None
        if self.fail_close == 'error_result':
            return SimpleNamespace(content=[SimpleNamespace(type='text', text='fixed fallback MCP error')], isError=True)
        if self.fail_close:
            raise RuntimeError('fixed browser fallback failure')
        return SimpleNamespace(content=[], isError=False)


@pytest.mark.usefixtures('chromium_ab')
@pytest.mark.parametrize('fault', ['clean', 'CLOSE', 'DRAIN', 'browser_close', 'partial_setup'])
def test_independent_browser_fallback_even_after_close_or_partial_setup_fault(monkeypatch, fault):
    s = FakeTransport('chromium', fail_close=fault == 'browser_close')
    r, latch = p3.new_receipt('fake', target()), g.StopLatch()

    async def call(session, code):
        if code == p3.CLOSE:
            if fault == 'CLOSE':
                raise RuntimeError('fixed CLOSE failure')
            result = clean_close(['A'] if fault == 'partial_setup' else ['A', 'B'], event())
            if fault == 'DRAIN':
                result['journal'] = {'status': 'incomplete', 'reasons': ['fixed terminal observation failure']}
            return result
        raise AssertionError('cleanup addressed the carrier after terminal CLOSE')

    monkeypatch.setattr(p3, '_call', call)
    asyncio.run(p3.cleanup(s, r, 'chromium', 'fake', latch))
    assert s.browser_closes == 1
    assert r['cleanup']['chromium']['confirmed'] == (fault == 'clean')
    assert latch.blocked == (fault != 'clean')
    if fault != 'CLOSE':
        assert r['log']['requests'][0]['url'] == EXACT and latch.tripped


PIN_PHASE = 'chromium:pins-chromium-copy'  # the first MCP contact: the Chromium copy's pins probe


def install_journey(monkeypatch, tmp_path, fault='clean'):
    """Sessions in order: pins (Chromium copy), pins (WebKit copy), chromium rows, WebKit engine probe, webkit rows.
    Returns the target (naming a W1 before-reading that passes the pre-check), the sessions and empty hooks."""
    sessions, kinds = [], iter(['pins', 'pins', 'chromium', 'engine', 'webkit'])
    t = target()
    t['w1_before'] = w1_before(tmp_path)
    raw = g.snapshot(p3.FIXTURE, p3.CTYPES)

    @contextlib.asynccontextmanager
    async def open_fake(url):
        s = FakeTransport(next(kinds))
        sessions.append(s)
        yield s
        if fault == 'transport_exit' and s.kind == 'pins' and len(sessions) == 1:
            raise RuntimeError('fixed transport exit after pin data')

    async def call(s, code):
        assert not s.browser_closes, 'MCP call after browser_close'
        if code == p3.CLOSE:
            if fault == 'CLOSE' and s.kind == 'chromium':
                raise RuntimeError('fixed CLOSE failure')
            names = [s.kind] if s.kind in ('pins', 'engine') else list(p3.ENGINES[s.kind]['contexts'])
            if s.kind in ('pins', 'engine'):
                names = ['probe']
            return clean_close(names, event() if fault == 'late_close' and s.kind == 'chromium' else {})
        if code == p3.DRAIN:
            return event() if fault == 'late_drain' and s.kind == 'chromium' else {}
        assert s.kind in ('pins', 'engine')
        if s.kind == 'engine':
            return {'type': 'webkit', 'version': 'fake-1', 'log': {}}
        here = ORIGIN if sum(x.kind == 'pins' for x in sessions) == 1 else t['origin_webkit']  # copy a, then b
        files = {n: {'status': 200, 'content_type': p3.CTYPES[n], 'url': here + '/' + n,
                     'b64': base64.b64encode(b).decode()} for n, b in raw.items()}
        if fault == 'bad_pin':
            files['app.js']['b64'] = base64.b64encode(b'not the reviewed file').decode()
        return {'status': 200, 'closed': True, 'final_url': here + '/', 'root': files['index.html'],
                'files': files, 'log': event() if fault in ('stage_A', 'bad_pin', 'transport_exit') else {}}

    async def rows(s, r, engine, origin, target, label, deadline, hooks, latch, served_html):
        assert not latch.stopped
        r['sessions'][engine].update(status='RAN', before_first_navigation=True)
        r['steps'].extend({'id': i, 'engine': engine, 'kind': 'browser', 'status': 'PASS', 'traffic': [],
                           'reasons': [], 'notes': []}
                          for i in p3.ROW_IDS[engine] + (['PH-1'] if engine == 'webkit' else []))
        if fault == 'partial_setup':
            raise RuntimeError('newPage failed after context creation')
        return True  # regression: the pending True must not defeat a late final drain

    monkeypatch.setattr(p3, 'open_session', open_fake)
    monkeypatch.setattr(p3, '_call', call)
    monkeypatch.setattr(p3, '_section_rows', rows)
    return t, sessions, {}


@pytest.mark.usefixtures('chromium_ab')
@pytest.mark.parametrize('fault', ['F5', 'carrier_context_error', 'carrier_context_alive'])
def test_r1_followup_carrier_context(monkeypatch, tmp_path, fault):
    data = r1_close_case(fault)
    s, r, latch = FakeTransport('chromium'), passing(p3.new_receipt('R1', target())), g.StopLatch()

    async def call(session, code):
        assert not session.browser_closes
        if code == p3.DRAIN:  # unchanged base still uses the separate pre-fallback drain
            return {}
        assert code == p3.CLOSE
        return data['result']

    monkeypatch.setattr(p3, '_call', call)
    asyncio.run(p3.cleanup(s, r, 'chromium', 'R1', latch))
    p3.finish(r, tmp_path, persist=False)
    c = r['cleanup']['chromium']
    assert s.browser_closes == 1
    if fault == 'F5':
        assert_w1_pending(r)
        assert data['contexts_left'] == 0
        assert c['journal']['status'] == 'complete' and c['contexts']['guard_context_closed']
    else:
        assert r['exit_code'] == 3 and not c['confirmed']
        assert c['journal']['status'] == 'incomplete' and c['journal']['reasons']
        assert all(x.startswith('terminal observation not established: ') for x in c['journal']['reasons'])
        assert 'terminal observation not established: ' in json.dumps(r['invocation_stop'])
        assert r['traffic_gate']['status'] != 'PASS'
        assert data['sequence'][-1] == 'drain' and data['guard_closed']
    if fault == 'carrier_context_error':
        assert 'fixed carrier context close failure' in json.dumps(c['errors'])


@pytest.mark.usefixtures('chromium_ab')
@pytest.mark.parametrize('fault', ['error', 'error_result', 'timeout', 'cancel', 'unknown'])
def test_r1_followup_fallback_recreation(monkeypatch, tmp_path, fault):
    s, r, latch = FakeTransport('chromium', fail_close=fault), passing(p3.new_receipt('R1', target())), g.StopLatch()
    r['sessions']['chromium']['url'] = 'fake:affected-chromium-service'

    async def call(session, code):
        assert not session.browser_closes
        if code == p3.DRAIN:  # baseline compatibility, not a grant for calls after browser_close
            return {}
        assert code == p3.CLOSE
        return clean_close(['A', 'B'])

    monkeypatch.setattr(p3, '_call', call)
    if fault == 'cancel':
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(p3.cleanup(s, r, 'chromium', 'R1', latch))
    else:
        asyncio.run(p3.cleanup(s, r, 'chromium', 'R1', latch))
    p3.finish(r, tmp_path, persist=False)
    c = r['cleanup']['chromium']
    assert s.browser_closes == 1 and r['exit_code'] == 3 and not c['confirmed']
    assert c['browser_close'] in ('error', 'unknown')
    required = r['mcp_service_recreation_required'][0]
    assert required == c['mcp_service_recreation_required']
    assert required['service'] == 'fake:affected-chromium-service' and required['reason']
    assert 'Architecture' in required['enforcer'] and 'W2' in required['required_receipt']
    assert latch.blocked and r['traffic_gate']['status'] != 'PASS'
    assert all(x.startswith('terminal observation not established: ') for x in c['journal']['reasons'])


@pytest.mark.usefixtures('chromium_ab')
@pytest.mark.parametrize('fault', ['guard_event', 'guard_alive', 'guard_error', 'untracked', 'other_context', 'bad_close'])
def test_r1_carrier_and_unknown_lifetimes(monkeypatch, tmp_path, fault):
    s, r, latch = FakeTransport('chromium'), passing(p3.new_receipt('R1', target())), g.StopLatch()
    data = None if fault == 'bad_close' else r1_close_case(fault)

    async def call(session, code):
        assert code == p3.CLOSE  # never DRAIN/address the carrier after its terminal CLOSE
        return ['malformed terminal result'] if data is None else data['result']

    monkeypatch.setattr(p3, '_call', call)
    asyncio.run(p3.cleanup(s, r, 'chromium', 'R1', latch))
    p3.finish(r, tmp_path, persist=False)
    c = r['cleanup']['chromium']
    assert s.browser_closes == 1
    if fault == 'guard_event':
        assert r['exit_code'] == 4 and c['journal']['status'] == 'complete'
        assert r['w4']['observations'][0]['url'] == EXACT
        assert data['guard_closed'] and data['sequence'][-1] == 'drain'
    else:
        assert r['exit_code'] == 3 and not c['confirmed']
        assert c['journal']['status'] == 'incomplete' and c['journal']['reasons']
        assert r['traffic_gate']['status'] != 'PASS'
        assert all(v != 'PASS' for v in r['traffic_gate']['engines'].values())
    if fault == 'guard_error':
        assert 'fixed guard close failure' in json.dumps(c)
    if fault == 'untracked':
        assert c['contexts']['untracked']


@pytest.mark.usefixtures('chromium_ab')
@pytest.mark.parametrize('fault', ['F5', 'F1', 'F2', 'F3', 'F4'])
def test_r1_final_disposal_window(monkeypatch, tmp_path, fault):
    t, sessions, hooks = install_journey(monkeypatch, tmp_path)
    original_call, original_rows = p3._call, p3._section_rows
    data = r1_close_case(fault)
    fallback_events, started = [], []
    transport_close = FakeTransport.call_tool

    async def call(s, code):
        if s.kind == 'chromium' and code == p3.CLOSE:
            return data['result']
        return await original_call(s, code)

    async def rows(s, r, *args):
        started.append(s.kind)
        ok = await original_rows(s, r, *args)
        if s.kind == 'chromium':
            r.setdefault('probes', {})['R1-original'] = {'data': 'fixed probe data',
                                                       'error': 'fixed original probe error'}
            if fault == 'F3':
                p3.collect(r, event(), ORIGIN, args[-2], 'R1:earlier-case-event')
        return ok

    async def browser_close(s, name, args):
        if s.kind == 'chromium' and fault in ('F2', 'F3'):
            fallback_events.append(event())  # no transport channel to the now-terminal Node journal
        return await transport_close(s, name, args)

    monkeypatch.setattr(p3, '_call', call)
    monkeypatch.setattr(p3, '_section_rows', rows)
    monkeypatch.setattr(FakeTransport, 'call_tool', browser_close)
    latch = g.StopLatch()
    empty_receipts_root(t, tmp_path)
    r = asyncio.run(p3.check_target('fake:chromium', 'fake:webkit', t, tmp_path, 'R1', 900, hooks, latch=latch))
    c = r['cleanup']['chromium']
    assert all(s.browser_closes == 1 for s in sessions)
    assert r['pins']['ok'] and r['probes'][PIN_PHASE]['root']['b64']
    assert r['probes']['R1-original'] == {'data': 'fixed probe data', 'error': 'fixed original probe error'}
    if fault in ('F1', 'F3'):
        assert r['verdict'] == 'W4 TRIPPED' and r['exit_code'] == 4
        assert r['w4']['observations'][0]['url'] == EXACT
        assert EXACT in (tmp_path / 'observations.json').read_text()
    elif fault in ('F2', 'F4'):
        assert r['verdict'] == 'BLOCKED' and r['exit_code'] == 3 and not c['confirmed']
        assert c.get('journal', {}).get('status') == 'incomplete'
        assert c['journal']['reasons'] and not r['w4']['observations']
        assert r['traffic_gate']['status'] != 'PASS'
        assert EXACT not in (tmp_path / 'observations.json').read_text()
    else:
        assert_w1_pending(r)
        assert c['confirmed'] and c.get('journal', {}).get('status') == 'complete'
    if fault != 'F5':
        assert len(sessions) == 3 and started == ['chromium']  # no later engine/probe
        assert not c['confirmed']
        assert 'fixed original CLOSE failure' in json.dumps(c)
        attempted = []

        async def forbidden_case(*a):
            attempted.append(True)
            raise AssertionError('a stopped invocation started a later case')

        monkeypatch.setattr(p3, 'run_control', forbidden_case)
        monkeypatch.setattr(p3, 'CONTROLS', [dict(case='LATER')])
        monkeypatch.setattr(g, 'StopLatch', lambda: latch)  # controls owns a fresh latch in real invocations
        args = SimpleNamespace(only='', browser='fake:', browser_webkit='fake:webkit', serve_ip='100.110.162.4')
        assert asyncio.run(p3.controls(args, tmp_path / 'later')) == (4 if fault in ('F1', 'F3') else 1)
        assert not attempted
    if fault == 'F1':
        assert 'page-close:A:false' in data['sequence']
        assert data['sequence'][-1] == 'drain' and data['guard_closed'] and not data['live']
    if fault in ('F2', 'F3'):
        assert fallback_events == [event()] and data['live'] > 0
    if fault == 'F4':
        assert 'fixed escalation failure' in json.dumps(c)


@pytest.mark.parametrize('fault', ['clean', 'stage_A', 'bad_pin', 'transport_exit', 'late_drain', 'late_close',
                                   'CLOSE', 'partial_setup'])
def test_journey_waits_for_terminal_traffic_and_disposal_before_next_engine(monkeypatch, tmp_path, fault):
    t, sessions, hooks = install_journey(monkeypatch, tmp_path, fault)
    latch = g.StopLatch()
    empty_receipts_root(t, tmp_path)
    r = asyncio.run(p3.check_target('fake:chromium', 'fake:webkit', t, tmp_path, 'fake', 900, hooks, latch=latch))
    assert all(s.browser_closes == 1 for s in sessions)
    if fault == 'clean':
        assert_w1_pending(r)
        assert len(sessions) == 5 and not latch.stopped
        assert r['w1']['before'] == dict(t['w1_before'], **{k: v for k, v in json.loads(
            Path(t['w1_before']['path']).read_text()).items() if k in p3.w1.FACTS})
        receipt = json.loads((tmp_path / 'receipt.json').read_text())
        assert receipt['verdict'] == 'BLOCKED' and receipt['w1']['status'] == 'PROVISIONAL'
        assert 'W1: PROVISIONAL' in (tmp_path / 'summary.md').read_text()
        # The receipt this journey wrote is what finalize judges (DECISION-11 rule 5): an unchanged container read
        # after the run gives COUNT.
        later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
        after = dict(json.loads(Path(t['w1_before']['path']).read_text()),
                     taken_at=later.strftime('%Y-%m-%dT%H:%M:%S.%fZ'))
        data = json.dumps(after).encode()
        (tmp_path / 'after.json').write_bytes(data)
        code, record, _ = p3.w1.finalize(str(tmp_path / 'receipt.json'), str(tmp_path / 'after.json'),
                                         p3.fac.sha256(data))
        assert code == 0 and record['result'] == 'COUNT' and json.loads((tmp_path / 'w1.json').read_text()) == record
    elif fault in ('stage_A', 'bad_pin', 'transport_exit', 'late_drain', 'late_close'):
        assert r['verdict'] == 'W4 TRIPPED' and r['exit_code'] == 4 and latch.tripped
        assert len(sessions) == (1 if fault in ('stage_A', 'bad_pin', 'transport_exit') else 3)
        assert EXACT in (tmp_path / 'observations.json').read_text()
        assert r['probes'][PIN_PHASE]['root']['b64']  # pin/error evidence survives too
    else:
        assert r['verdict'] == 'BLOCKED' and len(sessions) == 3 and latch.blocked


@pytest.mark.parametrize('fault', ['none', 'paused', 'late'])
def test_journey_without_a_checked_before_reading_opens_no_webkit_session(monkeypatch, tmp_path, fault):
    """DECISION-11 rule 2: no W1 before-reading, or one the pre-check refuses, leaves WebKit NOT RUN with the first
    failing reason, and no WebKit MCP session (engine probe or rows) is ever opened."""
    t, sessions, hooks = install_journey(monkeypatch, tmp_path)
    if fault == 'none':
        del t['w1_before']
    else:
        rec = json.loads(Path(t['w1_before']['path']).read_text())
        change = {'paused': True} if fault == 'paused' else {'taken_at': '2099-01-01T00:00:00.000000Z'}
        data = json.dumps(dict(rec, **change)).encode()
        Path(t['w1_before']['path']).write_bytes(data)
        t['w1_before']['sha256'] = p3.fac.sha256(data)
    empty_receipts_root(t, tmp_path)
    r = asyncio.run(p3.check_target('fake:chromium', 'fake:webkit', t, tmp_path, 'fake', 900, hooks,
                                    latch=g.StopLatch()))
    assert [s.kind for s in sessions] == ['pins', 'pins', 'chromium']  # both pin reads go through Chromium
    why = {'none': p3.w1.MISSING, 'paused': 'W1 before-reading refused: paused:before: ',
           'late': 'W1 before-reading refused: before-not-earlier: '}[fault]
    assert r['sessions']['webkit']['status'] == 'NOT RUN' and r['sessions']['webkit']['why'].startswith(why)
    webkit = [s for s in r['steps'] if s['engine'] == 'webkit']
    assert len(webkit) == len(p3.ROW_IDS['webkit']) + 1
    assert all(s['status'] == 'NOT RUN' and s['reasons'][0].startswith(why) and 'w1' not in s for s in webkit)
    # The verdict names the first NOT RUN row and the first failing W1 reason.
    assert r['verdict'] == 'BLOCKED' and r['why'].startswith(f"{len(webkit)} row(s) NOT RUN (J-1 webkit): {why}")
    assert r['w1']['status'] == ('NOT GIVEN' if fault == 'none' else 'REFUSED')


def test_a6_journey_writes_its_marker_and_its_own_marker_never_blocks_its_webkit(monkeypatch, tmp_path):
    """#279 (Security #105 A6): the run folder sits in the receipts root, so the WebKit admission (asked after the
    Chromium rows) sees this unit's own unfinished marker; it is not an earlier run and must not refuse it."""
    t, sessions, hooks = install_journey(monkeypatch, tmp_path, 'clean')
    root = tmp_path / 'receipts'
    out = root / 'run1' / 'check'
    out.mkdir(parents=True)
    t['receipts_root'], t['receipts_out_name'] = str(root), 'check'
    r = asyncio.run(p3.check_target('fake:chromium', 'fake:webkit', t, out, 'fake', 900, hooks, latch=g.StopLatch()))
    assert_w1_pending(r)
    assert len(sessions) == 5
    assert r['admission']['fake:webkit']['status'] == 'ADMITTED'
    assert r['admission']['fake:webkit']['own_marker'] == str(out / 'started.json') == r['started_marker']['path']
    marker = json.loads((out / 'started.json').read_text())
    assert set(marker['services']) == {'fake:chromium', 'fake:webkit'}
    after = p3.admission.admit(root, 'fake:chromium')  # the marker now has its final receipt beside it
    assert after['status'] == 'ADMITTED' and after['unfinished_markers'] == [] and after['p3_receipts'] == 1


@pytest.mark.parametrize('fault', ['clean', 'off_origin', 'error'])
def test_probe_keeps_observations_through_navigation_and_transport_error(monkeypatch, fault):
    s, r, latch = FakeTransport('probe'), p3.new_receipt('fake', target()), g.StopLatch()

    @contextlib.asynccontextmanager
    async def transport(url):
        yield s
        if fault == 'error':
            raise RuntimeError('fixed terminal transport error')

    async def call(session, code):
        if code == p3.CLOSE:
            return clean_close(['probe'])
        if code == p3.DRAIN:
            return {}
        return {'error': 'net::ERR_CONNECTION_REFUSED', 'log': event(ORIGIN + '/' if fault == 'clean' else EXACT)}

    monkeypatch.setattr(p3, 'open_session', transport)
    monkeypatch.setattr(p3, '_call', call)
    got = asyncio.run(p3.probe_session('fake:', p3.probe_js(target(), 'pins'), r=r, latch=latch, phase=PIN_PHASE))
    assert got['error'] and r['probes'][PIN_PHASE]['error'] and s.browser_closes == 1
    assert r['log']['requests'][0]['url'] == (ORIGIN + '/' if fault == 'clean' else EXACT)
    assert latch.tripped == (fault != 'clean') and latch.blocked  # a probe that did not complete blocks


@pytest.mark.parametrize('fault', ['clean', 'W4', 'cleanup', 'NOT RUN', 'unmatched', 'empty', 'none', 'subset'])
def test_batch_invocation_latch_and_incomplete_selections(monkeypatch, tmp_path, fault):
    cases = [dict(case=n, expect=('PASS', None)) for n in ['CLEAN', 'SECOND']]
    calls = []

    async def control(args, case, out, tmp, ip, latch):
        assert not latch.stopped
        calls.append(case['case'])
        if fault == 'W4':
            latch.observe({}, event(), ORIGIN, 'close')
        elif fault == 'cleanup':
            latch.block('cleanup unresolved')
        return {'case': case['case'], 'status': 'NOT RUN' if fault == 'NOT RUN' else 'OK'}

    monkeypatch.setattr(p3, 'CONTROLS', [] if fault == 'none' else cases)
    monkeypatch.setattr(p3, 'run_control', control)
    only = {'unmatched': 'MISSING', 'empty': ', ,', 'subset': 'CLEAN'}.get(fault, '')
    args = SimpleNamespace(only=only, browser='fake:', serve_ip='100.110.162.4')
    code = asyncio.run(p3.controls(args, tmp_path))
    data = json.loads((tmp_path / 'controls.json').read_text())
    assert code == (4 if fault == 'W4' else 0 if fault in ('clean', 'subset') else 1)
    assert data['all_ok'] == (fault in ('clean', 'subset'))
    assert data['full_qualification'] == (fault == 'clean')
    if fault in ('W4', 'cleanup'):
        assert calls == ['CLEAN'] and data['not_reached'] == ['SECOND']
    if fault in ('unmatched', 'empty', 'none'):
        assert calls == [] and data['selection_error']
    assert stat.S_IMODE((tmp_path / 'controls.json').stat().st_mode) == 0o600


def test_clean_materialization_variants_captured_pins_and_literal_serve_map(tmp_path):
    source = g.snapshot(p3.FIXTURE, p3.CTYPES)
    route_map = {'/': 'index.html', '/index.html': 'index.html', '/style.css': 'style.css',
                 '/app.js': 'app.js', '/favicon.svg': 'favicon.svg'}
    assert {url: v[0] for url, v in p3.fs.STATIC.items()} == route_map
    for variant in {c['variant'] for c in p3.CONTROLS}:
        site = p3.materialize(variant, tmp_path / variant)
        got = g.snapshot(site, p3.CTYPES)
        assert got == dict(source, **{'app.js': source['app.js'].replace(
            b'const VARIANT = "clean";', f'const VARIANT = {json.dumps(variant)};'.encode())})
    server = p3.P3Server(site, tmp_path / 'data')
    before = dict(server.files)
    (site / 'index.html').unlink()
    (site / 'index.html').symlink_to('/nonexistent-outside-fixture')
    (site / 'app.js').write_bytes(b'substituted after verified capture')
    sent = []
    handler = object.__new__(p3.P3Handler)
    handler.server = server
    handler._send = lambda code, body, ctype: sent.append((code, body))
    for route, name in route_map.items():
        handler.path = route
        handler.do_GET()
        assert sent[-1] == (200, before[name])
    for route in ['/index.html?x=1', '/%69ndex.html', '/x/../index.html']:
        handler.path = route
        handler.do_GET()
        assert sent[-1][0] == 404
    assert server.files == before  # pins are derived from this exact same captured mapping


@pytest.mark.parametrize('fault', ['leaf_link', 'parent_link', 'fifo', 'replacement'])
def test_fixture_snapshot_rejects_links_nonregular_and_substitution(monkeypatch, tmp_path, fault):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'a').write_bytes(b'verified')
    if fault == 'leaf_link':
        (source / 'a').unlink()
        (source / 'a').symlink_to(tmp_path / 'outside')
    elif fault == 'parent_link':
        alias = tmp_path / 'alias'
        alias.symlink_to(source, target_is_directory=True)
        source = alias
    elif fault == 'fifo':
        (source / 'a').unlink()
        os.mkfifo(source / 'a')
    else:
        original = os.read
        changed = False

        def swap(fd, size):
            nonlocal changed
            data = original(fd, size)
            if not changed:
                changed = True
                (source / 'replacement').write_bytes(b'outside')
                (source / 'replacement').replace(source / 'a')
            return data
        monkeypatch.setattr(g.os, 'read', swap)
    with pytest.raises((OSError, ValueError)):
        g.snapshot(source, ['a'])


@pytest.mark.parametrize('parent', [False, True])
def test_private_output_never_follows_links_or_overwrites(tmp_path, parent):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'receipt.json').write_text('unchanged')
    if parent:
        dest = tmp_path / 'alias'
        dest.symlink_to(outside, target_is_directory=True)
        path = dest / 'receipt.json'
    else:
        path = tmp_path / 'receipt.json'
        path.symlink_to(outside / 'receipt.json')
    with pytest.raises(OSError):
        g.write_json(path, {'bad': 'not written'})
    assert (outside / 'receipt.json').read_text() == 'unchanged'
    g.write_private(tmp_path / 'regular', 'first')
    with pytest.raises(FileExistsError):
        g.write_private(tmp_path / 'regular', 'second')
    assert (tmp_path / 'regular').read_text() == 'first'


@pytest.mark.parametrize('fault', ['clean', 'start', 'host', 'cancel', 'shutdown'])
def test_control_lifetime_always_stops_server_and_blocks_unresolved(monkeypatch, tmp_path, fault):
    seen = []

    class FakeServer:
        port, hits, starts = 8962, [], 1

        def __init__(self, site, data, variant, *, bind_address):
            assert bind_address == '0.0.0.0'  # container control caller retains its explicit existing bind
            self.files = g.snapshot(site, p3.CTYPES)
            seen.append('create')

        def start(self):
            seen.append('start')
            if fault == 'start':
                raise RuntimeError('fixed partial start failure')

        def retire(self):
            seen.append('retire')

        def shutdown(self):
            seen.append('shutdown')
            if fault == 'shutdown':
                raise RuntimeError('fixed shutdown failure')

        def host_action(self, kind):
            seen.append('host:' + kind)
            if fault == 'host':
                raise RuntimeError('fixed host exception')
            return {'action': kind, 'done': True}

    async def check(*a, **kw):
        await asyncio.sleep(0)
        if fault == 'cancel':
            raise asyncio.CancelledError
        a[6]['fake_host']('restart')  # the fake controller acts on copy a, never a real host
        return passing(kw['receipt'])

    monkeypatch.setattr(p3, 'P3Server', FakeServer)
    monkeypatch.setattr(p3, 'check_target', check)
    case = dict(p3.CONTROLS[0], case='FAKE')
    assert p3.CONTROLS[0]['case'] == 'P3-CLEAN'
    args = SimpleNamespace(browser='fake:', browser_webkit='fake:')
    latch = g.StopLatch()
    invocation = p3.run_control(args, case, tmp_path / 'out', tmp_path / 'tmp', '100.110.162.4', latch)
    if fault == 'cancel':
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(invocation)
    else:
        result = asyncio.run(invocation)
        assert result['status'] == ('OK' if fault == 'clean' else 'BLOCKED')
        # The rows are measured, W1 stays provisional (the fake check sets it only when it gets that far).
        assert result['w1'] == ('PROVISIONAL' if fault in ('clean', 'shutdown') else None)
    assert seen.count('shutdown') == (1 if fault == 'start' else 2)  # every created server, once
    assert seen.index('retire') < seen.index('shutdown')
    assert latch.stopped == (fault != 'clean')
    receipt = json.loads((tmp_path / 'out/FAKE/receipt.json').read_text())
    assert receipt['verdict'] == 'BLOCKED'  # never PASS before finalize (DECISION-11 rule 3)
    assert receipt['why'].startswith(p3.w1.PENDING) == (fault == 'clean')
    if fault in ('clean', 'shutdown'):
        assert receipt['w1']['on_count'] == ('PASS' if fault == 'clean' else 'BLOCKED')


def test_threaded_host_action_cannot_restart_after_retirement(monkeypatch, tmp_path):
    site = p3.materialize('clean', tmp_path / 'fixture')
    server = p3.P3Server(site, tmp_path / 'data')
    entered, release = threading.Event(), threading.Event()
    results = []

    def action(self, kind):
        entered.set()
        assert release.wait(2)
        try:
            self.start()  # the real P3 boundary refuses before any socket/server operation
        except RuntimeError:
            return {'action': kind, 'done': False}
        raise AssertionError('retired server restarted')

    monkeypatch.setattr(p3.fs.SyntheticServer, 'host_action', action)
    thread = threading.Thread(target=lambda: results.append(server.host_action('restart')))
    thread.start()
    assert entered.wait(2)
    server.retire()
    release.set()
    server.shutdown()
    thread.join(2)
    assert not thread.is_alive() and results[0]['done'] is False
    assert server.host_action('start')['done'] is False
    with pytest.raises(RuntimeError, match='retired'):
        server.start()


@pytest.mark.parametrize('bind_address', [None, '0.0.0.0', '127.0.0.1'])
def test_server_partial_thread_start_owns_and_closes_resource(monkeypatch, tmp_path, bind_address):
    site = p3.materialize('clean', tmp_path / 'fixture')
    kw = {} if bind_address is None else {'bind_address': bind_address}
    server = p3.P3Server(site, tmp_path / 'data', **kw)
    want_address = '0.0.0.0' if bind_address is None else bind_address
    assert server.bind_address == want_address
    closed, bindings = [], []
    dummy = SimpleNamespace(server_address=('fake', 8962), server_close=lambda: closed.append('closed'),
                            serve_forever=lambda: None)

    def fake_http(address, handler):
        bindings.append((address, handler))
        return dummy

    monkeypatch.setattr(p3.http.server, 'ThreadingHTTPServer', fake_http)

    class NoThread:
        def __init__(self, **kw):
            pass

        def start(self):
            raise RuntimeError('fixed Thread.start failure')

    monkeypatch.setattr(p3.threading, 'Thread', NoThread)
    with pytest.raises(RuntimeError, match='Thread.start'):
        server.start()
    server.shutdown()
    assert closed == ['closed'] and server.srv is None
    assert bindings == [((want_address, 0), p3.P3Handler)]


@pytest.mark.parametrize('address', [None, '', 'localhost', '127.0.0.2', '::1', '[::]',
                                     '0.0.0.0:0', '100.110.162.4', '127.0.0.1\n'])
def test_server_rejects_nonliteral_bind_before_any_fixture_read_or_listen(monkeypatch, tmp_path, address):
    def unexpected_read(*a, **kw):
        pytest.fail('invalid bind must be rejected before fixture reads')

    monkeypatch.setattr(g, 'snapshot', unexpected_read)
    with pytest.raises(ValueError, match='must be literal 0.0.0.0 or 127.0.0.1'):
        p3.P3Server(tmp_path / 'site', tmp_path / 'data', bind_address=address)


@pytest.mark.parametrize('fault', ['clean', 'off_origin', 'same_origin'])
def test_actual_section_rows_stops_immediately_on_observed_destination(monkeypatch, tmp_path, fault):
    t, r, latch = target(), p3.new_receipt('fake', target()), g.StopLatch()
    r['sessions']['chromium'] = {}
    calls = []
    monkeypatch.setitem(p3.ROW_IDS, 'chromium', ['J-1', 'J-2'])
    monkeypatch.setattr(p3.kit, 'judge', lambda row, res, engine, served=None: {'status': 'PASS', 'reasons': []})

    async def call(session, code):
        calls.append(code)
        if code == p3.DRAIN:
            return {}
        if 'const CTXS =' in code:
            return {'contexts': {n: {'first_url': 'about:blank'} for n in p3.ENGINES['chromium']['contexts']},
                    'browser_type': 'chromium', 'browser_version': 'fake-1', 'distinct_contexts': 6,
                    'observers_at': 'fixed', 'requests_before_navigation': 0}
        return {'obs': {'A': {}}, 'log': {} if fault == 'clean' else event(
            EXACT if fault == 'off_origin' else ORIGIN + '/unexpected')}

    monkeypatch.setattr(p3, '_call', call)
    ok = asyncio.run(p3.run_section(FakeTransport('chromium'), r, 'chromium', ORIGIN, t, tmp_path, 'fake',
                                    p3.time.monotonic() + 900, {}, latch))
    assert ok == (fault == 'clean')
    ran = [s for s in r['steps'] if s['status'] != 'NOT RUN']
    assert len(ran) == (2 if fault == 'clean' else 1)
    assert latch.tripped == (fault == 'off_origin')
    assert calls[-1] == p3.DRAIN


@pytest.mark.usefixtures('chromium_ab')
@pytest.mark.parametrize('fault', ['outer_cancel', 'CLOSE_cancel', 'bad_result'])
def test_cancellation_or_malformed_probe_cannot_skip_fallback(monkeypatch, fault):
    s, r, latch = FakeTransport('probe'), p3.new_receipt('fake', target()), g.StopLatch()
    reached, release = asyncio.Event(), asyncio.Event()

    @contextlib.asynccontextmanager
    async def transport(url):
        yield s

    async def call(session, code):
        if code == p3.CLOSE:
            if fault == 'CLOSE_cancel':
                raise asyncio.CancelledError
            if fault == 'outer_cancel':
                reached.set()
                await release.wait()
            return clean_close(['probe'], event())
        if code == p3.DRAIN:
            raise AssertionError('cleanup addressed the carrier after terminal CLOSE')
        return ['not an object'] if fault == 'bad_result' else {'type': 'webkit', 'log': event()}

    async def go():
        task = asyncio.create_task(p3.probe_session('fake:', 'fixed-probe', r=r, latch=latch, phase='probe'))
        if fault == 'outer_cancel':
            await reached.wait()
            task.cancel()
            release.set()
        if fault == 'bad_result':
            got = await task
            assert got['result_type'] == 'list'
        else:
            with pytest.raises(asyncio.CancelledError):
                await task

    monkeypatch.setattr(p3, 'open_session', transport)
    monkeypatch.setattr(p3, '_call', call)
    asyncio.run(go())
    assert s.browser_closes == 1 and latch.tripped
    assert r['log']['requests'][0]['url'] == EXACT
    if fault != 'outer_cancel':
        assert latch.blocked
