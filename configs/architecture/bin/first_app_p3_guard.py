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

    def observe(self, receipt: dict, log: dict, origin: str, phase: str) -> None:
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
    const u = {name, ctx, touch: !!touch, p: null, inflight: 0, pages: new Set()}; p3.users[name] = u;
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
  p3.close = async () => { const out = {contexts: {}};
    for (const [name, u] of Object.entries(p3.users)) { let error = null;
      try { await u.ctx.close(); } catch (e) { error = String(e); }
      out.contexts[name] = {error, page_created: !!u.p, page_closed: [...u.pages].every(p => p.isClosed()),
        context_still_in_browser: browser.contexts().includes(u.ctx)};
    }
    out.at = t(); out.other_contexts_left = browser.contexts().filter(c => c !== page.context()).length;
    out.log = p3.drain(); return out;
  };
"""

CLOSE = r"""async (page) => {
  if (!page.__p3) return {contexts: {}, log: {}, untracked: true};
  return await page.__p3.close();
}"""
DRAIN = "async (page) => page.__p3 ? page.__p3.drain() : {}"
