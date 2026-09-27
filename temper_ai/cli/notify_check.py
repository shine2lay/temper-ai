"""The notify part of ``temper slack check`` and ``temper telegram check``.

Is the notify file (where each run's notices and questions go) valid, what
does it say, does every workflow's own ``notify:`` name only places that
exist, and is the server's notify loop running and sending there?
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

Line = Callable[[bool | None, str], None]


def workflow_blocks(config_dir: Path) -> list[tuple[str, Path, Any]]:
    """(workflow name, file, raw notify value) for every workflow file that has one."""
    from temper_ai.config.importer import NON_CONFIG_DIRS

    out = []
    for path in sorted(config_dir.rglob("*.yaml")):
        rel = path.relative_to(config_dir).parts
        if any(part in NON_CONFIG_DIRS or part == "local" for part in rel):
            continue
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        body = raw.get("workflow") if isinstance(raw, dict) else None
        if isinstance(body, dict) and body.get("notify") is not None:
            out.append((str(body.get("name") or path.stem), path, body["notify"]))
    return out


def check_notify(line: Line, server_get: Callable[[str], Any], via: str,
                 config_dir: Path | None = None) -> None:
    from temper_ai.integrations.notify.config import (
        KINDS,
        NotifyConfigError,
        config_path,
        default_config_dir,
        load_config,
        parse_block,
    )

    config_dir = config_dir or default_config_dir()
    path = config_path(config_dir)
    try:
        cfg = load_config(config_dir)
    except NotifyConfigError as exc:
        line(False, f"notify: {exc}")
        return
    if path is None:
        line(None, "notify: no configs/notify/notify.yaml or configs/notify/local/notify.yaml, so nothing is sent")
        return
    line(True, f"notify: {path}")
    places = [p for p in cfg.places.values() if p.via == via]
    print(f"       {via} places: " + (", ".join(p.describe() for p in places) or "none"))
    for kind in KINDS:
        route = cfg.route(kind, None)
        fall = cfg.fallback.get(kind, ())
        print(f"       {kind}: {', '.join(route) or 'off'}" + (f" (no origin: {', '.join(fall)})" if fall else ""))
    quiet = cfg.quiet_hours(None)
    nudge = cfg.nudge(None)
    print(f"       quiet hours: {quiet.describe() if quiet else 'none'}; nudge: {nudge.describe() if nudge else 'none'}")
    print(f"       agents may send to: {', '.join(cfg.agents) or 'nowhere'} (and the run's own chat)")

    bad = 0
    for name, file, raw in workflow_blocks(config_dir):
        try:
            block = parse_block(raw, f"{name}: notify")
        except NotifyConfigError as exc:
            line(False, f"workflow {name} ({file.name}): {exc}")
            bad += 1
            continue
        missing = cfg.unknown_places(block)
        if missing:
            line(False, f"workflow {name} ({file.name}): notify names {', '.join(missing)}, "
                        "which the notify file has no place for")
            bad += 1
    if not bad:
        line(True, "notify: every workflow's own notify: names places that exist")

    try:
        status = server_get("/api/notify/status")
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        line(False, f"server: /api/notify/status: {exc}")
        return
    if not status.get("running"):
        line(False, f"server: the notify loop is not running ({status.get('reason')})")
        return
    senders = status.get("senders") or []
    line(via in senders, f"server: notify loop running; sends to {', '.join(senders) or 'nothing'}"
         + ("" if via in senders else f" (not {via})"))
    line(not status.get("last_error"), f"server: checked at {status.get('last_tick_at')}; "
         f"{status.get('sent', 0)} sent, {status.get('held', 0)} held for quiet hours"
         + (f"; last error: {status['last_error']}" if status.get("last_error") else ""))
    served = (status.get("config") or {})
    if served.get("error"):
        line(False, f"server: its notify file has a problem, so it keeps the last good one: {served['error']}")
