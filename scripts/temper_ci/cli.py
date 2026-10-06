"""``temper-ci`` — the gate in front of temper-ai's master.

    temper-ci check <commit>     run the machine check here and now
    temper-ci ask <commit>       put a commit in the queue for the watcher
    temper-ci watch              the service: pushes in, statuses out, deploys after
    temper-ci status             what is being checked, the last deploy, the last good one
    temper-ci report <commit>    where that commit's report is
    temper-ci serve-reports      the little server the status links point at
    temper-ci deploy [<commit>]  make master live now (what the watcher does by itself)
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import sys

from . import deploy as deploy_mod
from . import gate, paths, report, stack
from .paths import REPORTS, log


def cmd_check(args) -> int:
    paths.ensure_dirs()
    sha = _resolve(args.commit)
    with gate.one_at_a_time():
        verdict = gate.check(sha, args.branch or "", post=not args.no_post)
    print(json.dumps({k: v for k, v in verdict.items() if k != "checks"}, indent=2))
    for c in verdict.get("checks", []):
        print(f"  {'ok  ' if c['ok'] else 'FAIL'} {c['name']:<24} {c['seconds']:>4.0f}s  {c['detail'][:110]}")
    print(f"\nreport: {report.folder(sha)}/index.html  ({report.url(sha)})")
    return 0 if verdict.get("ok") else 1


def cmd_ask(args) -> int:
    paths.ensure_dirs()
    sha = _resolve(args.commit)
    gate.ask_for(sha, args.branch or "", args.why or "asked by hand")
    print(f"{sha[:12]} is in the queue; `temper-ci status` shows it.")
    return 0


def cmd_watch(_args) -> int:
    return gate.watch_with_deploys()


def cmd_status(_args) -> int:
    paths.ensure_dirs()
    g, d = gate.state(), deploy_mod.state()
    waiting = gate.queued()
    running = paths.LOCK.exists() and _locked()
    print("temper-ci — the gate in front of temper-ai's master\n")
    print(f"  watching:   {paths.GH_REPO}, branches of the repo itself, pushed by "
          f"{', '.join(paths.ALLOWED_PUSHERS)}")
    print(f"  checking:   {'yes, one is running now' if running else 'nothing right now'}")
    if waiting:
        print(f"  queued:     {', '.join(w['sha'][:12] for w in waiting)}")
    last = g.get("last") or {}
    if last:
        print(f"  last check: {last.get('sha', '')[:12]} "
              f"{'passed' if last.get('ok') else 'FAILED'} at {last.get('at')}")
    recent = sorted((g.get("commits") or {}).items(),
                    key=lambda kv: kv[1].get("finished_at") or "", reverse=True)[:8]
    if recent:
        print("\n  recently checked:")
        for sha, row in recent:
            mark = "passed" if row.get("ok") else "FAILED"
            extra = " (at once)" if row.get("skipped") else f" in {row.get('seconds', 0):.0f}s"
            print(f"    {sha[:12]}  {mark}{extra}  {(row.get('subject') or '')[:56]}")
            if not row.get("ok") and row.get("reason"):
                print(f"                 {row['reason'][:100]}")
    print()
    dep = d.get("last_deploy") or {}
    if dep:
        verdict = ("live and well" if dep.get("ok")
                   else "temper never restarted onto it" if dep.get("restarted") is False
                   else "FAILED its live check")
        print(f"  last deploy: {dep.get('sha', '')[:12]} {verdict} ({dep.get('asked_at', '')})")
        for p in (dep.get("live") or {}).get("parts", []):
            # An information-only part (the Pi pins) never counts: its mark says so, and its
            # first line says what it found.
            said = str(p.get("detail") or "").splitlines()[:1] if p.get("info") else []
            found = f" \u2014 {said[0]}" if said else ""
            print(f"      {report.mark(p):<4} {p['name']}{found}")
        if dep.get("rollback"):
            r = dep["rollback"]
            print(f"      went back to {str(r.get('good'))[:12]}"
                  f"{' (revert ' + r['revert'][:12] + ')' if r.get('revert') else ''}"
                  f"{'' if r.get('ok') else ' — THE REVERT DID NOT GO THROUGH'}")
    print(f"  live now:    {str(d.get('deployed') or '?')[:12]}")
    print(f"  last good:   {str(d.get('last_good') or '?')[:12]}")
    master = deploy_mod.master_sha()
    print(f"  master:      {master[:12]}")
    if master and d.get("handled") == master and d.get("deployed") != master:
        print("  held back:   master went wrong once and the owner was told; it is not tried "
              "again until master moves (`temper-ci deploy` tries it now)")
    print(f"\n  reports:    {REPORTS}  (served at {paths.REPORT_BASE})")
    print(f"  log:        {paths.LOG}")
    return 0


def _locked() -> bool:
    import fcntl
    try:
        with paths.LOCK.open("r") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fh, fcntl.LOCK_UN)
                return False
            except BlockingIOError:
                return True
    except OSError:
        return False


def cmd_report(args) -> int:
    sha = _resolve(args.commit)
    d = report.folder(sha)
    print(f"{d}/index.html")
    print(report.url(sha))
    return 0 if (d / "index.html").exists() else 1


def cmd_serve(_args) -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(REPORTS))
    # Loopback only: the reports are for this machine and whoever is on it.
    server = http.server.ThreadingHTTPServer(("127.0.0.1", paths.REPORT_PORT), handler)
    log(f"serving the reports on {paths.REPORT_BASE} from {REPORTS}")
    server.serve_forever()
    return 0


def cmd_deploy(args) -> int:
    paths.ensure_dirs()
    sha = _resolve(args.commit) if args.commit else deploy_mod.master_sha()
    out = deploy_mod.deploy(sha)
    print(json.dumps(out, indent=2)[:4000])
    return 0 if out.get("ok") else 1


# The rule master is meant to live under. It is written down here, in code, because the
# emergency switch is "turn it off, push, put it back" \u2014 and "put it back" has to be one
# command at three in the morning, not a form filled in from memory.
PROTECTION = {
    "required_status_checks": {
        "strict": True,                       # the branch must be up to date with master
        # Exactly the names GitHub shows on a commit \u2014 a required check that nobody ever
        # posts is a branch that can never move, so these are copied from a real run and
        # the test in tests/test_ci/ checks them against ci.yml.
        "contexts": [
            "lint",
            "typecheck",
            "tests (python 3.11)",
            "tests (python 3.12)",
            "tests (postgres)",
            "frontend",
            "e2e",
            "temper/boxes",            # this machine: a whole temper, built from the commit
        ],
    },
    "enforce_admins": True,                   # the owner goes through it too
    "required_pull_request_reviews": None,    # a pull request needs checks, not a second person
    "restrictions": None,
    "allow_force_pushes": False,
    "allow_deletions": False,
}


def cmd_protect(args) -> int:
    """Put master's protection back the way it is meant to be (or just show it)."""
    now = paths.sh("gh", "api", f"repos/{paths.GH_REPO}/branches/master/protection", timeout=60)
    if args.show:
        print(now.stdout if now.returncode == 0 else "master is not protected at all.")
        return 0
    if now.returncode == 0:
        backup = paths.STATE / "protection-before.json"
        backup.write_text(now.stdout, encoding="utf-8")
        print(f"what it was is saved in {backup}")
    got = paths.sh("gh", "api", "-X", "PUT", f"repos/{paths.GH_REPO}/branches/master/protection",
                   "-H", "Accept: application/vnd.github+json", "--input", "-",
                   stdin=json.dumps(PROTECTION), timeout=60)
    if got.returncode:
        print(f"temper-ci: GitHub would not set it: {got.stderr.strip()[:400]}", file=sys.stderr)
        return 1
    print("master now requires lint, typecheck, test and temper/boxes, for everyone "
          "including you, with force pushes and deletions refused.")
    return 0


def _resolve(ref: str) -> str:
    """A branch name, a short sha or a full one — all end up a full sha."""
    stack.fetch()
    got = paths.sh("git", "-C", str(stack.mirror()), "rev-parse", f"{ref}^{{commit}}")
    if got.returncode == 0 and got.stdout.strip():
        return got.stdout.strip()
    got = paths.sh("git", "-C", str(paths.MAIN_REPO), "rev-parse", f"{ref}^{{commit}}")
    if got.returncode == 0 and got.stdout.strip():
        return got.stdout.strip()
    print(f"temper-ci: {ref} is not a commit this machine knows.", file=sys.stderr)
    raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="temper-ci", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="run the machine check on a commit now")
    c.add_argument("commit")
    c.add_argument("--branch", default="")
    c.add_argument("--no-post", action="store_true", help="don't put a status on GitHub")
    c.set_defaults(fn=cmd_check)

    a = sub.add_parser("ask", help="queue a commit for the watcher")
    a.add_argument("commit")
    a.add_argument("--branch", default="")
    a.add_argument("--why", default="")
    a.set_defaults(fn=cmd_ask)

    sub.add_parser("watch", help="the service loop").set_defaults(fn=cmd_watch)
    sub.add_parser("status", help="what the gate is doing").set_defaults(fn=cmd_status)
    sub.add_parser("serve-reports", help="serve the reports on loopback").set_defaults(fn=cmd_serve)

    r = sub.add_parser("report", help="where a commit's report is")
    r.add_argument("commit")
    r.set_defaults(fn=cmd_report)

    d = sub.add_parser("deploy", help="make master live now")
    d.add_argument("commit", nargs="?", default="")
    d.set_defaults(fn=cmd_deploy)

    pr = sub.add_parser("protect", help="put master's protection back as it should be")
    pr.add_argument("--show", action="store_true", help="only print what it is now")
    pr.set_defaults(fn=cmd_protect)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
