"""W1 admission refusal for Project 3 browser services (#125 step 4b; Security #16 condition 4).

Hypothesis H-125-W1ADM-1 (rule 20), written before this code:
- What is wrong: #136 records mcp_service_recreation_required in a receipt when browser_close fails, but a
  later invocation never reads it, so a service left in an unknown state could be contacted again.
- The one change: before the first MCP call to a browser service, read the earlier Project 3 receipts in the
  same receipts root and refuse (BLOCKED, no MCP call) when the newest one that used the service says it needs
  recreation, unless the profile names Ops' W2 recreation receipt that shows a new container started after
  that receipt finished (and, for WebKit, the fresh W1 reading is that new container).
- Expected: fixed fake roots: no earlier recreation -> admitted; recreation and no W2 -> BLOCKED with zero MCP
  calls; same container id or an earlier StartedAt -> BLOCKED; hash mismatch -> BLOCKED; valid W2 plus a
  matching W1 reading -> admitted; malformed earlier receipt -> BLOCKED.
- Wrong if: a blocked case reaches an MCP call, a malformed receipt admits, or a clean root blocks.

Pure and fail-closed: it reads only regular files (no symlink is followed, at any component), never touches
the network or docker, keeps no store of its own and has no override. The receipts root is the parent of the
run's workspace (<root>/<run>/check/receipt.json and <root>/<run>/check/<case>/receipt.json, the workflow's
workspaces/first-app-check layout); history is per receipts root.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import stat
import urllib.parse

import first_app_p3_guard as guard
import ops_host_client as hc

RECEIPT_MAX = 64 << 20   # a P3 receipt carries its whole event log
W2_MAX = 1 << 20
MAX_RECEIPTS = 5000
HEX64 = re.compile(r"[0-9a-f]{64}")
W2_KEYS = {"path", "sha256"}


class Refused(Exception):
    """Admission cannot be established; the service is not contacted."""


def service_name(url: str) -> str:
    """The compose service a browser URL names (http://playwright-mcp-webkit:8931/mcp -> playwright-mcp-webkit)."""
    host = urllib.parse.urlsplit(url).hostname if isinstance(url, str) else None
    if not host:
        raise Refused(f"browser service URL has no host: {url!r}")
    return host


def _ref_problems(ref, where: str) -> list[str]:
    if not isinstance(ref, dict):
        return [f"{where} is not an object"]
    out = []
    extra = set(ref) - W2_KEYS - ({"before"} if where.endswith("]") else set())
    if extra:
        out.append(f"{where} has unknown keys {sorted(extra)}")
    path, digest = ref.get("path"), ref.get("sha256")
    if not (isinstance(path, str) and os.path.isabs(path) and "\x00" not in path):
        out.append(f"{where}.path must be an absolute path")
    if not (isinstance(digest, str) and HEX64.fullmatch(digest)):
        out.append(f"{where}.sha256 must be 64 lowercase hex characters")
    return out


def w2_problems(value) -> list[str]:
    """Shape of the profile's optional w2_recreation: {service URL: {path, sha256[, before: {path, sha256}]}}."""
    if not isinstance(value, dict):
        return ["w2_recreation is not an object"]
    out = []
    for url, ref in value.items():
        where = f"w2_recreation[{url}]"
        try:
            service_name(url)
        except Refused as exc:
            out.append(f"{where}: {exc}")
        out += _ref_problems(ref, where)
        if isinstance(ref, dict) and "before" in ref:
            out += _ref_problems(ref["before"], where + ".before")
    return out


def _leaf(fd: int, name: str, cap: int, where: str) -> bytes:
    st = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if not stat.S_ISREG(st.st_mode):
        raise Refused(f"{where} is not a regular file")
    if st.st_size > cap:
        raise Refused(f"{where} is larger than {cap} bytes")
    return guard.regular_bytes(fd, name)


def _subdir(fd: int, name: str, where: str) -> int | None:
    try:
        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode):
        raise Refused(f"{where} is a symlink")
    if not stat.S_ISDIR(st.st_mode):
        return None
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)


def _maybe_receipt(fd: int, where: str, found: list) -> None:
    try:
        st = os.stat("receipt.json", dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if len(found) >= MAX_RECEIPTS:
        raise Refused(f"more than {MAX_RECEIPTS} receipts under the receipts root")
    if not stat.S_ISREG(st.st_mode):
        raise Refused(f"{where}/receipt.json is not a regular file")
    found.append((where + "/receipt.json", _leaf(fd, "receipt.json", RECEIPT_MAX, where + "/receipt.json")))


def receipts(root: pathlib.Path, out_name: str = "check") -> list[tuple[str, bytes]]:
    """Every <root>/<run>/<out_name>/receipt.json and <root>/<run>/<out_name>/<case>/receipt.json, as bytes."""
    found: list[tuple[str, bytes]] = []
    with guard.directory_fd(root) as rfd:
        for run in sorted(os.listdir(rfd)):
            run_fd = _subdir(rfd, run, str(root / run))
            if run_fd is None:
                continue
            try:
                check_fd = _subdir(run_fd, out_name, str(root / run / out_name))
                if check_fd is None:
                    continue
                try:
                    base = str(root / run / out_name)
                    _maybe_receipt(check_fd, base, found)
                    for case in sorted(os.listdir(check_fd)):
                        case_fd = _subdir(check_fd, case, base + "/" + case)
                        if case_fd is None:
                            continue
                        try:
                            _maybe_receipt(case_fd, base + "/" + case, found)
                        finally:
                            os.close(case_fd)
                finally:
                    os.close(check_fd)
            finally:
                os.close(run_fd)
    return found


def _used(d: dict, where: str) -> tuple[set, list]:
    """The MCP services a P3 receipt contacted, and its recreation records. Malformed -> Refused."""
    used = set()
    probes = d.get("probe_services") or {}
    sessions = d.get("sessions") or {}
    cleanup = {**(d.get("cleanup") or {}), **(d.get("probe_cleanup") or {})} \
        if isinstance(d.get("cleanup") or {}, dict) and isinstance(d.get("probe_cleanup") or {}, dict) else None
    required = d.get("mcp_service_recreation_required") or []
    if not isinstance(probes, dict) or not isinstance(sessions, dict) or cleanup is None \
            or not isinstance(required, list):
        raise Refused(f"{where}: malformed P3 receipt (services/cleanup/recreation fields)")
    for url in probes.values():
        if not isinstance(url, str):
            raise Refused(f"{where}: malformed probe service")
        used.add(url)
    for engine, sess in sessions.items():
        if not isinstance(sess, dict) or not isinstance(sess.get("url", ""), str):
            raise Refused(f"{where}: malformed session record")
        if engine in cleanup or sess.get("status") in ("RAN", "ERROR"):
            used.add(sess.get("url"))
    for x in required:
        if not isinstance(x, dict) or not isinstance(x.get("service"), str):
            raise Refused(f"{where}: malformed mcp_service_recreation_required entry")
        used.add(x["service"])
    used.discard(None)
    return used, required


def _needs_recreation(required: list, used: set, url: str) -> bool:
    for x in required:
        if x["service"] == url:
            return True
        # An unnamed service ("unknown MCP service for ...") is held against every service the receipt used.
        if "://" not in x["service"] and url in used:
            return True
    return False


def _w1_ids(d: dict, url: str, where: str) -> set:
    """Container ids the earlier receipt's own W1 readings recorded for this service (WebKit only)."""
    ei = d.get("engine_image")
    if ei is None:
        return set()
    if not isinstance(ei, dict):
        raise Refused(f"{where}: malformed engine_image")
    if ei.get("service") != url:
        return set()
    ids = set()
    for side in ("before", "after"):
        facts = (ei.get(side) or {}).get("facts") if isinstance(ei.get(side) or {}, dict) else None
        if isinstance(facts, dict) and isinstance(facts.get("container_id"), str):
            ids.add(facts["container_id"])
    return ids


def _record(ref: dict, where: str) -> dict:
    path = pathlib.Path(ref["path"])
    try:
        with guard.directory_fd(path.parent) as fd:
            data = _leaf(fd, path.name, W2_MAX, where)
    except Refused:
        raise
    except (OSError, ValueError) as exc:
        raise Refused(f"{where}: unreadable ({exc.__class__.__name__}: {exc})") from exc
    got = hashlib.sha256(data).hexdigest()
    if got != ref["sha256"]:
        raise Refused(f"{where}: sha256 {got} is not the named {ref['sha256']}")
    try:
        rec = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refused(f"{where}: not JSON") from exc
    if not isinstance(rec, dict) or not isinstance(rec.get("containers"), dict):
        raise Refused(f"{where}: not a recreation record (#124 shape: mode, at, containers)")
    return rec


def _container(rec: dict, svc: str, where: str) -> dict:
    c = rec["containers"].get(svc)
    if not isinstance(c, dict) or not (isinstance(c.get("id"), str) and HEX64.fullmatch(c["id"])):
        raise Refused(f"{where}: no full container id for {svc}")
    try:
        started = hc.instant(c.get("started_at"), where + ".started_at")
    except hc.Blocked as exc:
        raise Refused(str(exc)) from exc
    return {"id": c["id"], "started_at": c["started_at"], "started": started, "running": c.get("running")}


def _w2(ref, url: str, failed: dict, w1_before: dict | None, need_w1: bool) -> dict:
    if ref is None:
        raise Refused(f"{failed['path']} lists mcp_service_recreation_required for {url}; no Ops W2 recreation "
                      "receipt is named in the profile (w2_recreation)")
    problems = _ref_problems(ref, f"w2_recreation[{url}]")
    if isinstance(ref, dict) and "before" in ref:
        problems += _ref_problems(ref["before"], f"w2_recreation[{url}].before")
    if problems:
        raise Refused("; ".join(problems))
    svc = service_name(url)
    after_rec = _record(ref, "W2 recreation receipt")
    if after_rec.get("mode") != "after":
        raise Refused("W2 recreation receipt is not an after-recreation record")
    new = _container(after_rec, svc, "W2 recreation receipt")
    if new["running"] is not True:
        raise Refused(f"W2 recreation receipt: {svc} is not running")
    if not new["started"] > failed["finished"]:
        raise Refused(f"W2 recreation receipt: {svc} StartedAt {new['started_at']} is not later than "
                      f"{failed['path']} finished_at {failed['finished_at']}")
    old = set(failed["w1_ids"])
    evidence = {"after": {"path": ref["path"], "sha256": ref["sha256"], "container_id": new["id"],
                          "started_at": new["started_at"]}}
    if "before" in ref:
        before_rec = _record(ref["before"], "W2 before-recreation record")
        if before_rec.get("mode") != "before":
            raise Refused("W2 before-recreation record is not a before record")
        try:
            at = hc.instant(before_rec.get("at"), "W2 before-recreation record at")
        except hc.Blocked as exc:
            raise Refused(str(exc)) from exc
        if not at >= failed["finished"]:
            raise Refused("W2 before-recreation record was taken before the failing receipt finished")
        prior = _container(before_rec, svc, "W2 before-recreation record")
        old.add(prior["id"])
        evidence["before"] = {"path": ref["before"]["path"], "sha256": ref["before"]["sha256"],
                              "container_id": prior["id"]}
    if not old:
        raise Refused(f"no recorded container id for {svc} at the failing receipt (no W1 reading there and no "
                      "W2 before-recreation record): a new container cannot be shown")
    if new["id"] in old:
        raise Refused(f"W2 recreation receipt: {svc} has the same container id {new['id']} (not recreated)")
    if need_w1:
        facts = (w1_before or {}).get("facts") if isinstance(w1_before, dict) else None
        if not isinstance(facts, dict) or (w1_before or {}).get("status") != "PASS":
            raise Refused("WebKit: no judged fresh W1 before-reading to match the recreated container")
        try:
            same_start = hc.instant(facts.get("container_started_at"), "W1 container_started_at") == new["started"]
        except hc.Blocked as exc:
            raise Refused(str(exc)) from exc
        if facts.get("container_id") != new["id"] or not same_start or facts.get("running") is not True:
            raise Refused("WebKit: the fresh W1 before-reading is not the recreated container "
                          f"({facts.get('container_id')} {facts.get('container_started_at')})")
        evidence["w1_before"] = {"container_id": facts["container_id"],
                                 "container_started_at": facts["container_started_at"]}
    return evidence


def admit(root: pathlib.Path, url: str, *, out_name: str = "check", w2: dict | None = None,
          w1_before: dict | None = None, need_w1: bool = False) -> dict:
    """ADMITTED or BLOCKED for one browser service, before any MCP call to it. Never raises."""
    result = {"service": url, "receipts_root": str(root), "status": "BLOCKED", "reasons": [],
              "receipts_read": 0, "p3_receipts": 0, "newest_use": [], "recreation_required": False, "w2": None}
    try:
        try:
            found = receipts(root, out_name)
        except Refused:
            raise
        except (OSError, ValueError) as exc:
            raise Refused(f"receipts root unreadable: {exc.__class__.__name__}: {exc}") from exc
        result["receipts_read"] = len(found)
        uses = []
        for where, data in found:
            try:
                d = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise Refused(f"{where}: not JSON (malformed or partial receipt)") from exc
            if not isinstance(d, dict):
                raise Refused(f"{where}: not a JSON object")
            if d.get("journey") != "p3":
                continue
            result["p3_receipts"] += 1
            used, required = _used(d, where)
            try:
                finished = hc.instant(d.get("finished_at"), where + ".finished_at")
            except hc.Blocked as exc:
                raise Refused(str(exc)) from exc
            if url in used:
                uses.append({"path": where, "finished": finished, "finished_at": d["finished_at"],
                             "recreation": _needs_recreation(required, used, url),
                             "w1_ids": _w1_ids(d, url, where)})
        if uses:
            newest = max(x["finished"] for x in uses)
            tied = [x for x in uses if x["finished"] == newest]
            result["newest_use"] = [x["path"] for x in tied]
            failing = [x for x in tied if x["recreation"]]
            if failing:
                result["recreation_required"] = True
                failed = {**failing[0], "w1_ids": set().union(*(x["w1_ids"] for x in failing))}
                result["w2"] = _w2((w2 or {}).get(url), url, failed, w1_before, need_w1)
        result["status"] = "ADMITTED"
    except Refused as exc:
        result["reasons"].append(str(exc))
    except Exception as exc:  # never let a reader bug turn into an admission
        result["reasons"].append(f"admission check failed: {exc.__class__.__name__}: {exc}")
    return result
