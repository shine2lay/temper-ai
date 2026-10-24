"""P3-only observation, invocation stop and regular-file boundary; no authority persisted here."""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import stat
import urllib.parse
from dataclasses import dataclass, field

W4_EXIT = 4
HOLD = ("Stop and park the caller with native queue_blocked on Security; carry this unresolved receipt/run, "
        "source/import/fixture and browser pins across restart and later invocations. Only Security's explicit "
        "reply bound to that receipt, pins and scope releases it. No timeout, restart, earlier GO, new case or "
        "CLI invocation releases it. No clearance file or automatic resume.")


def _origin(url: str) -> tuple:
    p = urllib.parse.urlsplit(url)
    scheme = {"ws": "http", "wss": "https"}.get(p.scheme.lower(), p.scheme.lower())
    return scheme, p.hostname, p.port if p.port is not None else (443 if scheme == "https" else 80)


def exact_key(url: str) -> tuple:
    """Security G3: a plant URL matches only exactly: scheme, host, port (defaults filled in), path and query
    (a planted URL has none; an added query is not the plant). The fragment is never sent."""
    try:
        p = urllib.parse.urlsplit(url)
        scheme = p.scheme.lower()
        port = p.port if p.port is not None else {"http": 80, "ws": 80, "https": 443, "wss": 443}.get(scheme)
    except (ValueError, TypeError, AttributeError):
        return None  # never equal to a plant's key: an unreadable URL is never a catch
    return scheme, p.hostname, port, p.path or "/", p.query


@dataclass
class StopLatch:
    """One sticky latch shared by every case, probe, section and cleanup of an invocation."""
    tripped: bool = False
    blocked: bool = False
    observations: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def stopped(self) -> bool:
        return self.tripped or self.blocked

    def observe(self, receipt: dict, log: dict, origin: str, phase: str, allowed=()) -> None:
        """Every off-origin event trips W4, except, in a control run, the exact URLs of that case's own gate
        plant (allowed; builds and plants without a list pass none): those are recorded in the receipt's
        gate_catches, the gate's own event-based record that G2 counts."""
        keys = set()
        for x in allowed or ():
            keys.add(exact_key(x))
        for kind in ("requests", "responses", "failed", "websockets", "serviceworkers", "popups"):
            for event in log.get(kind) or []:
                url = event.get("url")
                if not isinstance(url, str):
                    continue
                try:
                    parsed = urllib.parse.urlsplit(url)
                    outside = parsed.scheme in ("http", "https", "ws", "wss") and _origin(url) != _origin(origin)
                except ValueError:
                    # Invalid event URLs are retained, not treated as a grant or proof of a destination.
                    self.block("malformed event URL: " + url)
                    continue
                if outside and keys and exact_key(url) in keys:
                    receipt.setdefault("gate_catches", []).append({"phase": phase, "kind": kind, "ctx": event.get("ctx"),
                                                                   "url": url})
                    continue
                if outside:
                    self.tripped = True
                    self.observations.append({"phase": phase, "kind": kind, **event})
        self.bind(receipt)

    def block(self, reason: str) -> None:
        self.blocked = True
        self.reasons.append(reason)

    def bind(self, receipt: dict) -> None:
        receipt["w4"] = {"status": "TRIPPED" if self.tripped else "NOT TRIPPED",
                         "observations": list(self.observations), "operator_hold": HOLD if self.tripped else None}
        receipt["invocation_stop"] = {"blocked": self.blocked, "reasons": list(self.reasons)}


@contextlib.contextmanager
def directory_fd(path: pathlib.Path, *, create: bool = False):
    """Walk literal absolute components without resolving/following any symlink (Linux dir_fd)."""
    absolute = pathlib.Path(os.path.abspath(path))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _identity(st) -> tuple:
    return st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def regular_bytes(fd: int, name: str) -> bytes:
    if pathlib.PurePath(name).name != name or name in (".", ".."):
        raise ValueError("not a literal file name: " + name)
    leaf = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
    try:
        before = os.fstat(leaf)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("not a regular file: " + name)
        chunks = []
        while chunk := os.read(leaf, 65536):
            chunks.append(chunk)
        after = os.fstat(leaf)
        linked = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(linked):
            raise ValueError("file substituted or modified during capture: " + name)
        data = b"".join(chunks)
        if len(data) != after.st_size:
            raise ValueError("short regular-file capture: " + name)
        return data
    finally:
        os.close(leaf)


def snapshot(path: pathlib.Path, names) -> dict[str, bytes]:
    with directory_fd(path) as fd:
        return {name: regular_bytes(fd, name) for name in names}


def write_private(path: pathlib.Path, data: bytes | str) -> None:
    """Create once, regular 0600; no leaf/parent symlink following or overwrite."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    with directory_fd(path.parent, create=True) as parent:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent)
        try:
            os.fchmod(fd, 0o600)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("not a regular output file: " + str(path))
            with os.fdopen(fd, "wb", closefd=False) as out:
                out.write(data)
                out.flush()
                os.fsync(fd)
        finally:
            os.close(fd)


def write_json(path: pathlib.Path, value) -> None:
    write_private(path, json.dumps(value, indent=1, ensure_ascii=False))


# Used verbatim in every P3 page-bearing probe and journey SETUP. Context listeners precede newPage;
# the page event installs page listeners even if newPage later raises. Exact URLs are never shortened.
OBSERVERS = r"""
  const t = () => new Date().toISOString();
  const log = {requests: [], responses: [], failed: [], pageerrors: [], console: [], dialogs: [], websockets: [],
    popups: [], crashes: [], serviceworkers: []};
  const p3 = {log, seen: {}, users: {}}; page.__p3 = p3;
  p3.drain = () => { const out = {}; for (const [k, v] of Object.entries(log)) { const from = p3.seen[k] || 0;
    out[k] = v.slice(from); p3.seen[k] = v.length; } return out; };
  p3.attach = (ctx, name, touch) => {
    const u = {name, ctx, touch: !!touch, p: null, inflight: 0, pages: new Set(), closeErrors: []}; p3.users[name] = u;
    ctx.on('request', r => { u.inflight++; log.requests.push({t: t(), ctx: name, method: r.method(), url: r.url(),
      type: r.resourceType(), navigation: r.isNavigationRequest()}); });
    ctx.on('requestfinished', () => { u.inflight = Math.max(0, u.inflight - 1); });
    ctx.on('requestfailed', r => { u.inflight = Math.max(0, u.inflight - 1); log.failed.push({t: t(), ctx: name,
      method: r.method(), url: r.url(), error: (r.failure() || {}).errorText || null}); });
    ctx.on('response', r => log.responses.push({t: t(), ctx: name, method: r.request().method(), url: r.url(),
      status: r.status()}));
    ctx.on('serviceworker', w => log.serviceworkers.push({t: t(), ctx: name, url: w.url()}));
    u.attachPage = pg => { if (u.pages.has(pg)) return; u.pages.add(pg);
      if (u.p && pg !== u.p) log.popups.push({t: t(), ctx: name, url: pg.url()});
      pg.on('pageerror', e => log.pageerrors.push({t: t(), ctx: name, message: String(e && e.message || e)}));
      pg.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') log.console.push({t: t(), ctx: name,
        type: m.type(), text: m.text()}); });
      pg.on('dialog', d => { log.dialogs.push({t: t(), ctx: name, type: d.type(), message: d.message()});
        d.dismiss().catch(() => {}); });
      pg.on('websocket', w => log.websockets.push({t: t(), ctx: name, url: w.url()}));
      pg.on('crash', () => log.crashes.push({t: t(), ctx: name}));
    };
    ctx.on('page', u.attachPage); return u;
  };
  // The carrier is a Node-side Page object: its journal remains readable after page.close().
  const carrier = p3.attach(page.context(), '__guard', false); delete p3.users.__guard;
  carrier.p = page; carrier.attachPage(page);
  p3.close = async (terminal = false) => {
    const out = {contexts: {}, errors: [], untracked: false}, reasons = [];
    const fail = (errors, step, e) => errors.push({step, error: String(e)});
    const pages = u => { const current = u.ctx.pages();
      if (current.some(pg => !u.pages.has(pg))) out.untracked = true;
      return [...new Set([...u.pages, ...current])]; };
    try {
      for (const [name, u] of Object.entries(p3.users)) {
        const errors = u.closeErrors; let escalated = false;
        const state = out.contexts[name] = {page_created: !!u.p, page_closed: false,
          context_still_in_browser: true, errors};
        try {
          pages(u); // detect an untracked page even if the first close disposes it
          let failed = false;
          try { await u.ctx.close(); } catch (e) { failed = true; fail(errors, 'context-close', e); }
          if (failed || pages(u).some(pg => !pg.isClosed())) {
            escalated = true;
            for (const pg of pages(u)) { if (!pg.isClosed()) {
              try { await pg.close({runBeforeUnload: false}); } catch (e) { fail(errors, 'page-close', e); }
            } }
            try { await u.ctx.close(); } catch (e) { fail(errors, 'context-retry', e); }
          }
          state.page_closed = pages(u).every(pg => pg.isClosed());
          state.context_still_in_browser = browser.contexts().includes(u.ctx);
        } catch (e) { fail(errors, 'escalation', e); }
        state.error = errors.length ? errors[0].error : null; state.escalated = escalated;
        if (!state.page_closed || state.context_still_in_browser) reasons.push(name + ': page/context still live');
        if (errors.some(e => e.step !== 'context-close')) reasons.push(name + ': escalation raised');
      }
    } catch (e) { fail(out.errors, 'disposal', e); reasons.push('disposal raised'); }
    finally {
      if (terminal) {
        try { pages(carrier); await page.close({runBeforeUnload: false}); }
        catch (e) { fail(out.errors, 'guard-page-close', e); reasons.push('guard page close raised'); }
        try { await carrier.ctx.close(); }
        catch (e) { fail(out.errors, 'guard-context-close', e); reasons.push('guard context close raised'); }
        try {
          out.guard_page_closed = page.isClosed();
          out.guard_context_closed = !browser.contexts().includes(carrier.ctx);
          if (!out.guard_context_closed) reasons.push('guard context still live');
          if (!out.guard_page_closed) reasons.push('guard page still live');
          if (pages(carrier).some(pg => !pg.isClosed())) reasons.push('guard context has live pages');
          out.other_contexts_left = browser.contexts().length;
          if (out.other_contexts_left) reasons.push('other contexts still live');
        } catch (e) { fail(out.errors, 'terminal-state', e); reasons.push('terminal state unreadable'); }
        if (out.untracked) reasons.push('untracked page');
        out.journal = {status: reasons.length ? 'incomplete' : 'complete',
          reasons: reasons.map(x => 'terminal observation not established: ' + x),
          boundary: 'terminal CLOSE; subsequent MCP browser_close is unobserved'};
      } else out.other_contexts_left = browser.contexts().filter(c => c !== carrier.ctx).length;
      // No P3 disposal after this drain, and no later call may address the closed carrier.
      out.at = t(); out.log = p3.drain();
    }
    return out;
  };
"""

CLOSE = r"""async (page) => {
  if (!page.__p3) {
    const out = {contexts: {}, log: {}, untracked: true, errors: [],
      journal: {status: 'incomplete', reasons: ['terminal observation not established: P3 journal missing'],
        boundary: 'terminal CLOSE; subsequent MCP browser_close is unobserved'}};
    const ctx = page.context(), browser = ctx.browser();
    try { await page.close({runBeforeUnload: false}); out.guard_page_closed = page.isClosed(); }
    catch (e) { out.errors.push({step: 'guard-page-close', error: String(e)}); }
    try { await ctx.close(); out.guard_context_closed = !browser.contexts().includes(ctx); }
    catch (e) { out.errors.push({step: 'guard-context-close', error: String(e)}); }
    return out;
  }
  return await page.__p3.close(true);
}"""
DRAIN = "async (page) => page.__p3 ? page.__p3.drain() : {}"
