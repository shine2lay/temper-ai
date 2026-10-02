# The signed-in browser

Some runs need pages behind a login — the owner's own accounts. Those runs get
a *signed-in browser*, which is not the same thing as the anonymous
`playwright-mcp` container (that one stays logged out on purpose, so a run can
never inherit an account by accident).

There are two signed-in browsers, and a run gets the better one:

| | where | kept up by |
|---|---|---|
| **box** (first choice) | a real Chrome on spark, with a profile of its own | `box-browser.target` (user units, start at boot) |
| **mac** (fallback) | the owner's laptop Chrome | a LaunchAgent holding an ssh tunnel |

Both connect to the same Bridge on spark (`pi-chrome-bridge.service`,
127.0.0.1:17318). Runs never talk to the Bridge directly: they go through the
token-locked proxy (`local/chrome-mcp/proxy.py`, `temper-chrome-mcp.service`),
which is what keeps the per-run fences — read any tab, change only a tab you
opened yourself, and your tabs close when your session ends.

## What a run sees

The first tool result of a session carries one extra line, after the answer:

```
signed-in browser: box - the box's own Chrome on spark (the box's own, healthy)
```

so the run (and whoever reads it afterwards) knows which browser answered.
`browser_status` and `browser_targets` repeat it.

Being listed by the Bridge is not proof a browser is there — a websocket
nobody closed can keep a dead browser "ready" for minutes — so the proxy asks
each candidate in turn, best first, and only opens the session on one that
actually answers.

When neither answers, the session offers no tools at all and every call comes
back with **"no signed-in browser"** in words, telling the run to say so and
stop rather than retry. Nothing hangs.

## Signing the box's Chrome in

The box's Chrome has no screen of its own, so you look at it over the tailnet:

- In a browser: `https://spark.tailbb5055.ts.net:6090/vnc.html`
- From macOS Screen Sharing: `vnc://spark.tailbb5055.ts.net:5901`

Both ask for a password (kept in `~/.local/state/box-browser/view-password.txt`
on the box, mode 600, never in any repo). Neither is reachable off the
tailnet: x11vnc and noVNC listen on loopback only, and the tailscale serves
are tailnet-only — no Funnel.

Then just sign in the way you would on your own machine: open the site, enter
the password, answer the code it texts you. The profile lives in
`~/opt/box-browser/profile` and survives `systemctl --user restart
box-browser-chrome` and a reboot.

Rules of thumb while you are in there: leave the extension alone (it is what
the Bridge talks to), and don't log into anything you would mind a run
reading — every run that gets the box's Chrome can read every tab in it.

## When a site signs it out

`box-browser-watch.timer` looks every 10 minutes and DMs you **once per
problem** — once when it breaks, once when it is back, never a stream:

- *unreachable*: the box's Chrome or the Bridge has been gone for 20 minutes,
  so runs are falling back to the laptop or getting nothing.
- *signed out*: the browser is healthy but a watched page no longer shows its
  signed-in marker.

Which pages count as signed-in is a file outside any repo,
`~/.temper/box-browser/signed-in.json`:

```json
{"pages": [{"name": "example", "url": "https://example.com/account",
            "signed_in_marker": "Sign out"}],
 "unreachable_minutes": 20}
```

With no such file only reachability is watched. The DM names the page, never
anything read from it.

To fix a signed-out site: open the view, sign in again. Nothing needs
restarting.

## Running it by hand

```
systemctl --user status box-browser-chrome      # the browser itself
systemctl --user restart box-browser-chrome     # a stuck browser
systemctl --user status pi-chrome-bridge        # what both browsers connect to
local/box-browser/watch.py --once --dry-run     # what the watcher would say now
local/box-browser/identify.py                   # re-learn which target is the box's
```

`local/box-browser/setup.sh` builds the whole thing from nothing (screen,
window manager, browser, viewer, Bridge, watcher) and is safe to run again.

The checks that prove the fences still hold, from inside a container:

```
docker exec -e CHROME_MCP_TOKEN=... temper-ai-server-1 \
    /app/.venv/bin/python /app/local/chrome-mcp/check.py all
```
