// Fixed-input EventEmitter objects only. No Playwright, browser, MCP, server or networking modules.
const {EventEmitter} = require('node:events');
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const sequence = [], options = [], contexts = [];
const req = url => ({method: () => 'GET', url: () => url, resourceType: () => 'script',
  isNavigationRequest: () => false, failure: () => ({errorText: 'fixed navigation failure'})});
function emit(ctx, phase) {
  sequence.push(phase + ':emit');
  if (input.at !== phase) return;
  if (!ctx.listenerCount('request')) throw new Error('event witness installed too late');
  const r = req(input.url);
  ctx.emit('request', r); ctx.emit('response', {request: () => r, url: r.url, status: () => 302});
  ctx.emit('requestfailed', r);
  if (ctx.pages.length) {
    const pg = ctx.pages[0];
    pg.emit('websocket', {url: () => input.websocket || input.url});
    pg.emit('pageerror', new Error('observed service worker registration blocked'));
    pg.emit('console', {type: () => 'error', text: () => 'registration failed: fixed event'});
  }
  ctx.emit('serviceworker', {url: () => input.url});
}
class Page extends EventEmitter {
  constructor(ctx) { super(); this.ctx = ctx; this.closed = false; this.address = 'about:blank'; }
  context() { return this.ctx; }
  url() { return this.address; }
  viewportSize() { return this.ctx.opts.viewport; }
  isClosed() { return this.closed; }
  async goto(url) {
    sequence.push('goto'); this.address = url; emit(this.ctx, 'goto');
    if (input.fault === 'navigation') throw new Error('net::ERR_FIXED_NAVIGATION');
    return {status: () => 200, url: () => url, headers: () => ({'content-type': 'text/html'}),
      body: async () => Buffer.from(input.files['index.html'])};
  }
  async evaluate(fn, arg) {
    if (!Array.isArray(arg)) return [];
    return Object.fromEntries(arg.map(n => [n, {status: 200, content_type: input.ctypes[n],
      b64: Buffer.from(input.files[n]).toString('base64'), url: this.address + n}]));
  }
}
class Context extends EventEmitter {
  constructor(opts) { super(); this.opts = opts; this.pages = []; this.isRoot = false; }
  browser() { return browser; }
  async newPage() {
    sequence.push('newPage');
    if (input.fault === 'newPage' && contexts.length === (input.failAt || 1) + 1) {
      emit(this, 'newPage'); throw new Error('fixed partial newPage failure');
    }
    const pg = new Page(this); this.pages.push(pg); this.emit('page', pg); emit(this, 'newPage'); return pg;
  }
  async storageState() { return {cookies: [], origins: []}; }
  async route() { sequence.push('route'); }
  async close() {
    if (this.closed) return;
    sequence.push('close'); emit(this, 'close');
    if (input.fault === 'close') throw new Error('fixed close failure');
    this.closed = true;
    for (const pg of this.pages) pg.closed = true;
    contexts.splice(contexts.indexOf(this), 1);
  }
}
const browser = {
  contexts: () => contexts.slice(),
  browserType: () => ({name: () => input.engine}), version: () => 'fixed-fake-1',
  async newContext(opts) {
    if (opts.serviceWorkers !== 'block') throw new Error('missing explicit SW block');
    sequence.push('newContext'); options.push(opts);
    const ctx = new Context(opts); contexts.push(ctx); return ctx;
  }
};
const rootCtx = new Context({}); rootCtx.isRoot = true; contexts.push(rootCtx);
const root = new Page(rootCtx); rootCtx.pages.push(root);
(async () => {
  let result = null, error = null, close_result = null, close_error = null, drain = null;
  try { result = await eval('(' + input.code + ')')(root); } catch (e) { error = String(e); }
  if (input.close) {
    try { close_result = await eval('(' + input.close + ')')(root); } catch (e) { close_error = String(e); }
    drain = root.__p3 ? root.__p3.drain() : {};
  }
  console.log(JSON.stringify({result, error, close_result, close_error, drain, options, sequence,
    tracked: Object.keys(root.__p3 ? root.__p3.users : {}), contexts_left: contexts.length - 1}));
})().catch(e => { console.error(String(e)); process.exitCode = 1; });
