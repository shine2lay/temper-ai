"""T9-R2 / T19 / P14: enumerate writers, then check their narrow contracts.

This is a source proof, not a production-lane/deploy receipt. Scan *all* temper_ai,
not just runner/: SQL values, ORM attributes (even unknown aliases), constructors,
dynamic setters and raw SQL. Non-run status attributes have an explicit separate
inventory, never an inference from a variable's spelling. A new candidate must be
reviewed; no directory/name exclusion can silently bless a new writer.

Known-answer bites change source strings in memory and invoke the same checks as
the combined happy path. They neither edit production files nor run a workflow.
Inherited G/C1/C2/R/X/D/F behavioral/race tests remain the execution proof.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIELDS = frozenset({"status", "attempts", "spawner_metadata", "spawner_kind", "spawner_handle"})
PARKED = "temper_ai/runner/parked.py"
BOX = "temper_ai/cli/run_workflow.py"
QUEUE = "temper_ai/runner/queue.py"
WATCH = "temper_ai/cli/watch_queue.py"
ROUTES = "temper_ai/api/routes.py"
GENERATION = "temper_ai/runner/row_generation.py"
LANE = "temper_ai/runner/pi_lane.py"


@dataclass(frozen=True, order=True)
class Site:
    path: str
    scope: str
    form: str
    field: str


def _sources() -> dict[str, str]:
    return {str(p.relative_to(ROOT)): p.read_text() for p in sorted((ROOT / "temper_ai").rglob("*.py"))}


class Module:
    def __init__(self, path: str, source: str):
        self.path = path
        self.tree = ast.parse(source, filename=path)
        self.parents = {child: parent for parent in ast.walk(self.tree)
                        for child in ast.iter_child_nodes(parent)}
        self.names: dict[str, str] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    self.names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.names[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else alias.name.split(".")[0])
        # Resolve imported aliases, local constants and function aliases, without executing code.
        for _ in range(3):
            for node in ast.walk(self.tree):
                if isinstance(node, ast.Assign):
                    value = self.name(node.value)
                    if value:
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                self.names[target.id] = value

    def name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return self.names.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return f"{self.name(node.value)}.{node.attr}"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return repr(node.value)
        return ""

    def scope(self, node: ast.AST) -> str:
        parts = []
        while node in self.parents:
            node = self.parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                parts.append(node.name)
        return ".".join(reversed(parts))

    def function(self, scope: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
        return next(n for n in ast.walk(self.tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and self.scope(n) + ("." if self.scope(n) else "") + n.name == scope)

    def calls(self, name: str) -> list[ast.Call]:
        return [n for n in ast.walk(self.tree) if isinstance(n, ast.Call)
                and (self.name(n.func) == name or self.name(n.func).endswith("." + name))]


def _modules(sources: dict[str, str]) -> dict[str, Module]:
    return {p: Module(p, s) for p, s in sources.items()}


def _writes(modules: dict[str, Module]) -> Counter[Site]:
    """Over-approximate mutations: all matching attributes, even without a row type.

    Also enumerate every keyword SQL .values(**mapping): an opaque mapping is a
    candidate, not an exemption. Ignore ordinary dict.values(), which has no args.
    """
    found: Counter[Site] = Counter()
    for path, mod in modules.items():
        def add(node: ast.AST, form: str, field: str) -> None:
            found[Site(path, mod.scope(node), form, field)] += 1

        for node in ast.walk(mod.tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
                targets = (node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target])
                for target in targets:
                    for part in ast.walk(target):
                        if isinstance(part, ast.Attribute) and part.attr in FIELDS:
                            add(node, "attribute", part.attr)
                        elif isinstance(part, ast.Subscript) and isinstance(part.slice, ast.Constant):
                            if part.slice.value == "container_id":
                                add(node, "identity-element", "spawner_metadata")
            if not isinstance(node, ast.Call):
                continue
            name = mod.name(node.func)
            if name.endswith(".WorkflowRun") or name == "WorkflowRun":
                # Defaults are writes too: attempts=0, queued, null handle/kind, empty metadata.
                for field in FIELDS:
                    add(node, "insert", field)
            elif (name in {"setattr", "builtins.setattr"} or name.endswith(".__setattr__")) and len(node.args) >= 2:
                field = node.args[1]
                if not isinstance(field, ast.Constant):
                    add(node, "setattr", "**")
                elif field.value in FIELDS:
                    add(node, "setattr", str(field.value))
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "values":
                for keyword in node.keywords:
                    if keyword.arg is None or keyword.arg in FIELDS:
                        add(node, "values", keyword.arg or "**")
                if node.args:
                    add(node, "values", "**")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in {"update", "pop", "clear"}:
                if isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "spawner_metadata":
                    add(node, "metadata-method", "spawner_metadata")
            sql_text = name in {"sqlalchemy.text", "sqlalchemy.sql.text"}
            driver_sql = isinstance(node.func, ast.Attribute) and node.func.attr in {"execute", "exec_driver_sql"}
            if sql_text or driver_sql:
                # SQLAlchemy text(), including dynamic SQL, fails closed. Direct
                # driver SQL with a literal workflow_runs mutation is a candidate too.
                arg = node.args[0] if node.args else None
                if sql_text and not isinstance(arg, ast.Constant):
                    add(node, "raw-sql", "**")
                elif isinstance(arg, ast.Constant) and re.search(
                        r"\b(?:update|insert\s+into|delete\s+from)\s+[\"`]?workflow_runs\b",
                        str(arg.value), re.IGNORECASE):
                    add(node, "raw-sql", "**")
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"bulk_update_mappings", "bulk_insert_mappings"}:
                add(node, "bulk-mapping", "**")
    return found


# Actual run-row writes. The value is the safety argument, not a permission to add
# another write in that function: multiplicities and fields must match exactly.
RUN_WRITERS: dict[tuple[str, str, str, tuple[str, ...]], str] = {
    (ROUTES, "_start_run_subprocess", "insert", tuple(sorted(FIELDS))):
        "Fresh dispatch insert before spawn; attempts default 0. Unique execution id.",
    (ROUTES, "_start_run_subprocess", "attribute", ("status", "spawner_kind", "spawner_handle", "spawner_metadata")):
        "One direct spawn owner: fail before start, or stamp its new dispatch; GL2/GL5 required.",
    (ROUTES, "_cancel_unclaimed_pi_run", "values", ("status",)):
        "UPDATE only queued, unclaimed, Pi-lane row.",
    (WATCH, "_mark_cancelled_unclaimed", "values", ("status",)):
        "UPDATE only queued and still unclaimed.",
    (WATCH, "_claim_row", "values", ("spawner_kind", "spawner_handle")):
        "Conditional still-unclaimed UPDATE plus lane; Pi also queued and no busy peer; GL2.",
    (WATCH, "_unclaim", "values", ("spawner_kind", "spawner_handle")):
        "Conditional execution id + queued + CLAIMING, one watcher per kind/lane (GL2).",
    (WATCH, "_stamp_handle", "attribute", ("spawner_handle", "spawner_metadata")):
        "Behind watcher's won CLAIMING claim; merges metadata and fresh dispatch id (GL2).",
    (WATCH, "_mark_spawn_failed", "attribute", ("status",)):
        "Behind won claim; spawn failed before any box runs (GL2/GL5).",
    (BOX, "_update_run_row", "setattr", ("**",)):
        "Explicit caller inventory below. U7: one box per generation (GL2/GL5), not a row CAS.",
    (QUEUE, "queue_run_in", "insert", tuple(sorted(FIELDS))):
        "Unique fresh row within caller transaction; attempts default 0.",
    (QUEUE, "queue_run_in", "attribute", ("status", "spawner_kind", "spawner_handle", "spawner_metadata")):
        "FOR UPDATE, refuse queued/running; clear handle+old identity together, preserve attempts.",
    (GENERATION, "end_row_if_same_generation", "values", ("**",)):
        "One SQL UPDATE on judged status+attempts and queued dispatch; rowcount exactly 1.",
    (LANE, "_requeue_unstarted", "values", ("spawner_kind", "spawner_handle")):
        "Startup: queued + kind present + Pi lane. Null handle prevents matching the retained old id.",
    (LANE, "record_commit", "attribute", ("spawner_metadata",)):
        "Read/merge; box calls before its start, Pi worker source-restricts spawner to subprocess; GL4.",
    ("temper_ai/pi_agent/accounts.py", "record_account", "attribute", ("spawner_metadata",)):
        "Read/merge existing metadata under FOR UPDATE; container id unchanged.",
    ("temper_ai/spawner/box_profile.py", "DbProfileStore.save", "attribute", ("spawner_metadata",)):
        "Read/merge existing metadata under FOR UPDATE; only box_profile entry changes.",
}

# Non-run candidates are still exact sites, with the different model/object named.
# A fourth status assignment at one of these sites changes the count and fails.
OTHER_WRITERS: dict[tuple[str, str, str, str], tuple[int, str]] = {
    ("temper_ai/api/team_routes.py", "TeamRefusal.__init__", "attribute", "status"): (1, "HTTP refusal"),
    ("temper_ai/cli/run_on_server.py", "Refused.__init__", "attribute", "status"): (1, "HTTP refusal"),
    ("temper_ai/integrations/inbox/store.py", "fail", "attribute", "status"): (2, "InboxEvent"),
    ("temper_ai/integrations/inbox/store.py", "finish", "attribute", "status"): (1, "InboxEvent"),
    ("temper_ai/integrations/inbox/store.py", "give_up", "attribute", "status"): (1, "InboxEvent"),
    ("temper_ai/integrations/inbox/store.py", "verified", "attribute", "status"): (1, "InboxEvent"),
    ("temper_ai/integrations/inbox/store.py", "replay", "attribute", "status"): (1, "InboxEvent"),
    ("temper_ai/integrations/inbox/store.py", "claim", "values", "status"): (1, "InboxEvent"),
    ("temper_ai/integrations/notion/client.py", "NotionError.__init__", "attribute", "status"): (1, "HTTP error"),
    ("temper_ai/integrations/slack/door.py", "DoorError.__init__", "attribute", "status"): (1, "HTTP error"),
    ("temper_ai/integrations/slack/ops.py", "OpsError.__init__", "attribute", "status"): (1, "HTTP error"),
    ("temper_ai/integrations/telegram/store.py", "save_chat", "attribute", "status"): (1, "TelegramChat"),
    ("temper_ai/integrations/telegram/store.py", "settle_pending", "values", "status"): (1, "TelegramPending"),
    ("temper_ai/integrations/notify/store.py", "rekey_question", "attribute", "status"): (1, "NotifyCopy"),
    ("temper_ai/llm/single_send.py", "SingleSendError.__init__", "attribute", "status"): (1, "HTTP status"),
    ("temper_ai/observability/reconcile.py", "settle_run_event", "attribute", "status"): (1, "Event; no run-row update"),
    ("temper_ai/observability/reconcile.py", "reconcile_and_report", "attribute", "status"): (1, "Event; interrupted, never carried-on"),
    ("temper_ai/observability/recorder.py", "update_event._do_update", "attribute", "status"): (1, "Event generic wrapper; P14 checks callers"),
    ("temper_ai/observability/recorder.py", "decide_event_in", "values", "status"): (1, "Event CAS; P14 checks callers"),
    ("temper_ai/pi_agent/turn.py", "run_turn", "attribute", "status"): (3, "TurnOutcome"),
    ("temper_ai/runner/holds.py", "record", "attribute", "status"): (1, "CleanupHold, not WorkflowRun"),
    ("temper_ai/runner/holds.py", "end", "attribute", "status"): (1, "CleanupHold, not WorkflowRun"),
    (QUEUE, "AlreadyQueued.__init__", "attribute", "status"): (1, "exception's observed status"),
    ("temper_ai/stage/executor.py", "_execute_single_node", "attribute", "status"): (2, "NodeResult"),
    ("temper_ai/stage/executor.py", "_handle_loop", "attribute", "status"): (1, "NodeResult"),
    ("temper_ai/tools/mcp_auth.py", "DatabaseTokenStore._write", "setattr", "**"): (1, "McpOAuthToken"),
    ("temper_ai/agent/single_call_agent.py", "_Attempt.close", "setattr", "**"): (1, "SingleCallAttempt"),
    ("temper_ai/llm/providers/base.py", "BaseLLM.__init_subclass__", "setattr", "**"): (1, "provider class methods"),
    ("temper_ai/observability/usage_reconcile.py", "drain_pending", "attribute", "status"): (1, "Event interrupted"),
    ("temper_ai/observability/trim.py", "vacuum", "raw-sql", "**"): (1, "VACUUM table from trim policy"),
    ("temper_ai/observability/usage_rows.py", "", "raw-sql", "**"): (1, "usage pending drain SQL, not workflow_runs"),
    ("temper_ai/pi_agent/ledger.py", "_add_flow", "raw-sql", "**"): (1, "ALTER pi_participants columns"),
}

# Opaque SQL mappings are enumerated too. Every one below targets the named
# *other* table, not WorkflowRun; the exact multiplicity remains part of T9.
for _path, _scope, _count, _table in [
    ("integrations/notify/store", "mark", 1, "notify_copies"),
    ("observability/recorder", "record._write", 1, "events"),
    ("observability/usage_feed_epochs", "append_prepared_epoch", 2, "usage feed epochs"),
    ("observability/usage_feed_epochs", "append_ready_epoch", 2, "usage feed epochs"),
    ("observability/usage_reconcile", "mark_ready", 1, "usage_writer_ready"),
    ("observability/usage_reconcile", "drain_pending", 1, "usage reconciliation cursor"),
    ("observability/usage_rows", "_append_final", 1, "usage_rows"),
    ("observability/usage_rows", "_queue_pending", 1, "usage_pending"),
    ("pi_agent/ledger", "Ledger._attach", 1, "pi_participants"),
    ("pi_agent/ledger", "Ledger._admit", 1, "pi_turns"),
    ("pi_agent/ledger", "Ledger._take", 1, "pi_turns"),
    ("pi_agent/ledger", "Ledger._open_wait", 1, "pi_waits"),
    ("pi_agent/ledger", "Ledger.open_review", 1, "pi_reviews"),
    ("pi_agent/ledger", "Ledger.post", 1, "pi_messages"),
    ("pi_agent/ledger", "Ledger.decide_wait", 1, "pi_participants"),
    ("pi_agent/ledger", "Ledger._fenced", 1, "pi_turns"),
    ("pi_agent/ledger", "Ledger.update_review", 1, "pi_reviews"),
    ("pi_agent/ledger", "Ledger._release", 1, "pi_turns"),
    ("pi_agent/ledger", "Ledger.start_outcome", 2, "pi_outcomes"),
    ("pi_agent/ledger", "Ledger.write_outcome", 2, "pi_outcomes"),
    ("pi_agent/team_leader", "LeaderTeam._settle_act", 1, "pi_team_acts"),
    ("pi_agent/team_trials", "save", 1, "pi_team_trials"),
    ("pi_agent/team_versions", "store", 1, "pi_team_versions"),
]:
    OTHER_WRITERS[(f"temper_ai/{_path}.py", _scope, "values", "**")] = (_count, _table)


def _expected() -> Counter[Site]:
    expected: Counter[Site] = Counter()
    for (path, scope, form, fields), reason in RUN_WRITERS.items():
        assert reason
        for field in fields:
            expected[Site(path, scope, form, field)] += 1
    for (path, scope, form, field), (count, reason) in OTHER_WRITERS.items():
        assert reason
        expected[Site(path, scope, form, field)] += count
    return expected


def _exprs(node: ast.AST) -> set[str]:
    return {ast.unparse(n) for n in ast.walk(node)}


def _require(mod: Module, scope: str, expression: str, check: str) -> None:
    target = ast.parse(expression).body[0]
    if isinstance(target, ast.Expr):
        target = target.value
    wanted = ast.dump(target)
    count = sum(ast.dump(n) == wanted for n in ast.walk(mod.function(scope)))
    needed = 2 if (mod.path, scope, expression) == (
        GENERATION, "_queued_dispatch", "col(WorkflowRun.spawner_handle) == judged.handle") else 1
    assert count >= needed, f"{check}: {mod.path}:{scope}: missing {expression} ({count}/{needed})"


# The indirect writers are part of the surface too; listing only the final SQL
# primitive would hide a new unsafe caller. Each tuple names its exact caller.
CALLERS = {
    "end_row_if_same_generation": [(PARKED, "_end_row_in"), ("temper_ai/spawner/reaper.py", "Reaper._mark_status")],
    "_end_row_in": [(PARKED, "cancel_parked")],
    "_mark_status": [("temper_ai/spawner/reaper.py", f"Reaper.{scope}") for scope in
                     ("_let_go_parked", "_mark_orphaned", "_honor_cancel", "_end_unstarted", "_end_unstarted")],
    "queue_run_in": [(QUEUE, "queue_run"), (PARKED, "claim_and_queue"), (PARKED, "claim_and_requeue_row")],
    "queue_run": [(ROUTES, "_queue_run"), (LANE, "resume_in_the_lane")],
    "_queue_run": [(ROUTES, scope) for scope in
                   ("_start_run_external", "_queue_cleanup_pass", "_fork_run", "_start_resume")],
}


# Each conditional safety argument has an executable source check and an
# automatically paired scope-removal bite below. Unconditional U7/dispatch paths
# retain their written GL2/GL5 preconditions instead of pretending to have a CAS.
ROW_SCOPES = [
    (ROUTES, "_cancel_unclaimed_pi_run", "WorkflowRun.execution_id == execution_id"),
    (ROUTES, "_cancel_unclaimed_pi_run", "WorkflowRun.status == 'queued'"),
    (ROUTES, "_cancel_unclaimed_pi_run", "col(WorkflowRun.spawner_kind).is_(None)"),
    (ROUTES, "_cancel_unclaimed_pi_run", "lane_clause(col(WorkflowRun.spawner_metadata), PI_LANE)"),
    (WATCH, "_mark_cancelled_unclaimed", "WorkflowRun.execution_id == execution_id"),
    (WATCH, "_mark_cancelled_unclaimed", "WorkflowRun.status == 'queued'"),
    (WATCH, "_mark_cancelled_unclaimed", "WorkflowRun.spawner_kind.is_(None)"),
    (WATCH, "_claim_row", "WorkflowRun.execution_id == execution_id"),
    (WATCH, "_claim_row", "WorkflowRun.spawner_kind.is_(None)"),
    (WATCH, "_claim_row", "lane_clause(col(WorkflowRun.spawner_metadata), lane)"),
    (WATCH, "_claim_row", "conditions.append(WorkflowRun.status == 'queued')"),
    (WATCH, "_unclaim", "WorkflowRun.execution_id == execution_id"),
    (WATCH, "_unclaim", "WorkflowRun.status == 'queued'"),
    (WATCH, "_unclaim", "WorkflowRun.spawner_handle == CLAIMING"),
    (LANE, "_requeue_unstarted", "col(WorkflowRun.status) == 'queued'"),
    (LANE, "_requeue_unstarted", "col(WorkflowRun.spawner_kind).is_not(None)"),
    (LANE, "_requeue_unstarted", "lane_clause(col(WorkflowRun.spawner_metadata), PI_LANE)"),
    (GENERATION, "end_row_if_same_generation", "col(WorkflowRun.execution_id) == execution_id"),
    (GENERATION, "end_row_if_same_generation", "col(WorkflowRun.status) == judged.status"),
    (GENERATION, "end_row_if_same_generation", "col(WorkflowRun.attempts) == judged.attempts"),
    (GENERATION, "end_row_if_same_generation", "judged.status == QUEUED"),
    (GENERATION, "_queued_dispatch", "col(WorkflowRun.spawner_handle) == judged.handle"),
    (GENERATION, "_queued_dispatch", "_ROW_CONTAINER_ID == judged.container_id"),
    (QUEUE, "queue_run_in", "row.status in ('queued', 'running')"),
]


def _assert_t9(modules: dict[str, Module]) -> None:
    actual, expected = _writes(modules), _expected()
    assert actual == expected, f"T9-R2/T19 unknown or missing writer: extra={actual - expected}; missing={expected - actual}"
    for path, scope, expression in ROW_SCOPES:
        _require(modules[path], scope, expression, "T9-R2 writer scope")
    for name, allowed in CALLERS.items():
        actual_calls = Counter((p, m.scope(c)) for p, m in modules.items() for c in m.calls(name))
        assert actual_calls == Counter(allowed), f"T9-R2 {name} callers: {actual_calls}"
    box = modules[BOX]
    calls = box.calls("_update_run_row")
    shapes = Counter((box.scope(c), tuple(sorted(k.arg or "**" for k in c.keywords))) for c in calls)
    assert shapes == Counter({
        ("cmd_run_workflow", ("attempts", "spawner_handle", "started_at", "status")): 2,
        ("cmd_run_workflow", ("completed_at", "error", "status")): 2,
        ("cmd_run_workflow", ("completed_at", "error", "result", "status")): 1,
        ("_safe_mark_failed", ("completed_at", "error", "status")): 1,
    }), f"T9-R2 _update_run_row callers changed: {shapes}"
    starts = [{k.arg: k.value for k in c.keywords} for c in calls if any(k.arg == "attempts" for k in c.keywords)]
    assert Counter(ast.unparse(kw["attempts"]) for kw in starts) == Counter({
        "run_row['attempts'] + 1": 1, "own_generation.attempts": 1,
    }), "T9-R2 attempts increment"
    for kw in starts:
        assert ast.unparse(kw["status"]) == "'running'", "T9-R2 attempts/start same write"
    _require(box, "cmd_run_workflow", "own_generation = RowGeneration.from_snapshot({"
             "**run_row, 'status': 'running', 'attempts': run_row['attempts'] + 1, "
             "'spawner_handle': os.environ.get('TEMPER_RUN_CONTAINER') or str(os.getpid()), "
             "'container_id': meta.get('container_id')})", "T9-R2 boxed generation increment")
    # Imported/aliased calls anywhere else must not open this dynamic setter.
    assert [(p, m.scope(c)) for p, m in modules.items() for c in m.calls("_update_run_row")
            if p != BOX] == [], "T9-R2 unknown box updater caller"
    # The only creation default; construction with a supplied attempts is not allowed.
    for mod in modules.values():
        for c in mod.calls("WorkflowRun"):
            assert not any(k.arg in (None, "attempts") for k in c.keywords), "T9-R2 insert attempts override"
    model = modules["temper_ai/runner/models.py"]
    default = next(n for n in ast.walk(model.tree) if isinstance(n, ast.ClassDef) and n.name == "WorkflowRun")
    attempts = next(n for n in default.body if isinstance(n, ast.AnnAssign)
                    and isinstance(n.target, ast.Name) and n.target.id == "attempts")
    assert ast.unparse(attempts.value) == "Field(default=0)", "T9-R2 attempts creation default"


MERGES = [(LANE, "record_commit"), ("temper_ai/pi_agent/accounts.py", "record_account"),
          ("temper_ai/spawner/box_profile.py", "DbProfileStore.save")]
IDENTITY_SCOPES = [
    (path, scope, expression, "T19 merge identity") for path, scope in MERGES
    for expression in ("meta = dict(row.spawner_metadata or {})", "row.spawner_metadata = meta")
] + [
    (path, scope, "select(WorkflowRun).where(WorkflowRun.execution_id == execution_id).with_for_update()"
     + (".execution_options(populate_existing=True)" if path == QUEUE else ""), "T19 row lock")
    for path, scope in [*MERGES[1:], (QUEUE, "queue_run_in")]
] + [
    (WATCH, "_stamp_handle", "old = row.spawner_metadata or {}", "T19 stamp merge"),
    (WATCH, "_stamp_handle", "row.spawner_metadata = mark_lane({**old, **handle.metadata}, lane_of(old))", "T19 stamp merge"),
    (ROUTES, "_start_run_subprocess", "row.spawner_metadata = mark_lane(handle.metadata if kept is None else {'box_profile': kept, **handle.metadata}, lane_of(row.spawner_metadata))", "T19 direct fresh identity"),
    (QUEUE, "queue_run_in", "row.spawner_handle = None", "T19 queue identity clear"),
    (QUEUE, "queue_run_in", "row.spawner_kind = None", "T19 queue identity clear"),
    (QUEUE, "queue_run_in", "metadata: dict = {'start': start} if start else {}", "T19 queue identity clear"),
    (QUEUE, "queue_run_in", "metadata = {**metadata, **{k: old[k] for k in _WORKER_KEPT if old.get(k) is not None}}", "T19 queue identity clear"),
    (QUEUE, "queue_run_in", "row.spawner_metadata = mark_lane(metadata, lane_of(row.spawner_metadata) if lane is KEEP_LANE else lane)", "T19 queue identity clear"),
    (LANE, "worker_problem", "kind != 'subprocess'", "T19 Pi subprocess"),
    (WATCH, "cmd_watch_queue", "pi_lane.worker_problem(spawner)", "T19 Pi subprocess"),
    (LANE, "check_run", "record_commit(execution_id, start, commit, pins=seen.get('pins'), host_pi=seen.get('host_pi'))", "T19 Pi subprocess"),
    (BOX, "cmd_run_workflow", "pi_lane.check_run(execution_id, run_row, start=start, graph_loader=runner_ctx.graph_loader)", "T19 Pi subprocess"),
    ("temper_ai/spawner/docker_spawner.py", "DockerSpawner._handle", "container_id = result.stdout.strip()", "T19 Docker identity source"),
    ("temper_ai/spawner/docker_spawner.py", "DockerSpawner._handle", "metadata = {'execution_id': execution_id, 'container_id': container_id, 'image': image}", "T19 Docker identity source"),
    ("temper_ai/spawner/docker_spawner.py", "DockerSpawner._handle", "ProcessHandle(kind=SpawnerKind.docker, handle=name, metadata=metadata)", "T19 Docker identity source"),
    ("temper_ai/spawner/docker_spawner.py", "DockerSpawner.spawn", "self._handle(execution_id, result, self._image_override or template.image, record)", "T19 Docker identity source"),
    ("temper_ai/spawner/docker_spawner.py", "DockerSpawner._spawn_sealed", "self._handle(execution_id, result, template.image_id, record)", "T19 Docker identity source"),
    ("temper_ai/spawner/subprocess_spawner.py", "SubprocessSpawner.spawn", "ProcessHandle(kind=SpawnerKind.subprocess, handle=str(proc.pid), metadata={'execution_id': execution_id})", "T19 subprocess identity source"),
]


def _assert_t19(modules: dict[str, Module]) -> None:
    for path, scope, expression, check in IDENTITY_SCOPES:
        _require(modules[path], scope, expression, check)
    for path, scope in MERGES:
        fn = modules[path].function(scope)
        bindings = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "meta" for t in n.targets)]
        assert len(bindings) == 1, f"T19 merge identity rebound: {path}:{scope}"
        assert not any(isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name)
                       and c.func.value.id == "meta" and c.func.attr in {"clear", "pop", "update"}
                       for c in ast.walk(fn) if isinstance(c, ast.Call)), f"T19 merge identity mutated: {path}:{scope}"
    assert "_WORKER_KEPT = ('box_profile', LANE_RECORD_KEY)" in _exprs(modules[QUEUE].tree), "T19 queue kept identity"


def _assert_p14(modules: dict[str, Module]) -> None:
    parked = modules[PARKED]
    assert not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "claim"
                   for n in ast.walk(parked.tree)), "P14 legacy claim survived"
    claims = {"claim_and_queue", "claim_and_requeue_row", "claim_without_box_row"}
    assert Counter((p, m.scope(c)) for p, m in modules.items() for c in m.calls("_claim_in")) == Counter(
        (PARKED, scope) for scope in claims), "P14 fourth carried-on entry point"
    carried = []
    for path, mod in modules.items():
        for node in ast.walk(mod.tree):
            if isinstance(node, ast.Call):
                for k in node.keywords:
                    if k.arg == "status" and mod.name(k.value).split(".")[-1] in {"CARRIED_ON", "'parked'"}:
                        carried.append((path, mod.scope(node)))
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if isinstance(key, ast.Constant) and key.value == "status":
                        if mod.name(value).split(".")[-1] in {"CARRIED_ON", "'parked'"}:
                            carried.append((path, mod.scope(node)))
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Attribute) and t.attr == "status" for t in targets):
                    if mod.name(node.value).split(".")[-1] in {"CARRIED_ON", "'parked'"}:
                        carried.append((path, mod.scope(node)))
    assert carried == [(PARKED, "_claim_in")], f"P14 bare carried-on writer: {carried}"
    _require(parked, "_claim_in", "decide_event_in(session, attempt_id, expect=(WAITING,), status=CARRIED_ON, data={'parked': note})",
             "P14 CAS scope")
    _require(parked, "_claim_in", "latest_start_condition(Event.execution_id)", "P14 latest scope")
    for scope in claims:
        _require(parked, scope, "deciding_events()", "P14 claim transaction")
        claim = next(c for c in parked.calls("_claim_in") if parked.scope(c) == scope)
        ancestor: ast.AST = claim
        while ancestor in parked.parents:
            ancestor = parked.parents[ancestor]
            if isinstance(ancestor, ast.With):
                break
        assert isinstance(ancestor, ast.With) and any(ast.unparse(i.context_expr) == "deciding_events()"
                                                     for i in ancestor.items), "P14 claim outside transaction"
        if scope != "claim_without_box_row":
            queue = next(c for c in parked.calls("queue_run_in") if parked.scope(c) == scope)
            assert queue in set(ast.walk(ancestor)), "P14 queue outside claim transaction"
    releases = [(p, m.scope(c)) for p, m in modules.items()
                for c in m.calls("temper_ai.runner.parked.release")]
    assert releases == [(ROUTES, "_start_resume")], f"P14 forbidden release caller: {releases}"
    release = modules[ROUTES].calls("temper_ai.runner.parked.release")[0]
    guard = modules[ROUTES].parents[modules[ROUTES].parents[release]]
    assert isinstance(guard, ast.If) and ast.unparse(guard.test) == "parked_attempt is not None", (
        "P14 release requires its no-row attempt")
    _require(modules[ROUTES], "_start_resume", "pi_parked.claim_without_box_row(parked_attempt)",
             "P14 release requires no-row claim")
    handler = release
    while handler in modules[ROUTES].parents and not isinstance(handler, ast.ExceptHandler):
        handler = modules[ROUTES].parents[handler]
    assert isinstance(handler, ast.ExceptHandler), "P14 release outside thread-start failure"
    outer = modules[ROUTES].parents[handler]
    assert isinstance(outer, ast.Try) and [ast.unparse(n) for n in outer.body] == ["thread.start()"], (
        "P14 release may only handle thread.start failure")
    _require(parked, "release", "decide_event(str(attempt['id']), expect=(CARRIED_ON,), status=WAITING, data={'parked': note})",
             "P14 release CAS")
    # Catch imported aliases of the retired API in runtime AND direct tests.
    for path, mod in modules.items():
        assert not mod.calls("temper_ai.runner.parked.claim"), f"P14 legacy caller in {path}"
    for path in (ROOT / "tests").rglob("*.py"):
        if path != Path(__file__):
            assert not Module(str(path), path.read_text()).calls("temper_ai.runner.parked.claim"), (
                f"P14 legacy test caller in {path}")


@pytest.fixture(autouse=True)
def _file_sqlite_for_source_inventory(request, tmp_path):
    # Source checks have no live I/O. Their surrounding normal fixtures still use
    # the same file-SQLite/throwaway-PG tiers as the inherited producer tests.
    from temper_ai.database import init_database, reset_database
    from tests.conftest import TEST_DATABASE_URL

    if request.node.stash.get(TEST_DATABASE_URL, "").startswith("sqlite"):
        reset_database()
        init_database(f"sqlite:///{tmp_path / 'writers.db'}")


@pytest.fixture(scope="module")
def assembled():
    sources = _sources()
    return sources, _modules(sources)


def test_combined_writer_surface_happy_path(assembled):
    """T9-R2 + T19 + inherited P14: all exact shared paths on the assembled source."""
    _, modules = assembled
    _assert_t9(modules)
    _assert_t19(modules)
    _assert_p14(modules)


SCOPE_BITES = [(p, s, e, "T9-R2 writer scope", "t9") for p, s, e in ROW_SCOPES] + [
    (*entry, "t19") for entry in IDENTITY_SCOPES
] + [(PARKED, s, "deciding_events()", "P14 claim transaction", "p14") for s in
     ("claim_and_queue", "claim_and_requeue_row", "claim_without_box_row")]


@pytest.mark.parametrize(("path", "scope", "expression", "error", "check"), SCOPE_BITES,
                         ids=[f"scope-{p.split('/')[-1]}-{s}-{i}" for i, (p, s, *_rest) in enumerate(SCOPE_BITES)])
def test_each_writer_scope_removal_bites(assembled, path, scope, expression, error, check):
    sources, original = assembled
    wanted = ast.unparse(ast.parse(expression).body[0])
    node = next(n for n in ast.walk(original[path].function(scope)) if ast.unparse(n) == wanted)
    snippet = ast.get_source_segment(sources[path], node)
    assert snippet is not None
    # Replace only this scope's first matching subtree, preserving indentation.
    fn = original[path].function(scope)
    segment = ast.get_source_segment(sources[path], fn)
    assert segment is not None and snippet in segment
    changed = sources[path].replace(segment, segment.replace(snippet, "None", 1), 1)
    modules = {**original, path: Module(path, changed)}
    with pytest.raises(AssertionError, match=error):
        {"t9": _assert_t9, "t19": _assert_t19, "p14": _assert_p14}[check](modules)


@pytest.mark.parametrize(("case", "path", "old", "new", "check", "error"), [
    ("B-SCAN-status", QUEUE, "def queue_run_in(", "def unknown_status(row):\n    row.status = 'completed'\n\n\ndef queue_run_in(", "t9", "unknown or missing writer"),
    ("B-SCAN-attempts", QUEUE, "def queue_run_in(", "def unknown_attempts(row):\n    row.attempts += 1\n\n\ndef queue_run_in(", "t9", "unknown or missing writer"),
    ("B-SCAN-metadata", QUEUE, "def queue_run_in(", "def unknown_identity(row):\n    row.spawner_metadata = {}\n\n\ndef queue_run_in(", "t9", "unknown or missing writer"),
    ("B-SCAN-dynamic", QUEUE, "def queue_run_in(", "def unknown_dynamic(row, key):\n    setattr(row, key, 'completed')\n\n\ndef queue_run_in(", "t9", "unknown or missing writer"),
    ("B-SCAN-rawSQL", QUEUE, "def queue_run_in(", "def unknown_sql(conn):\n    conn.exec_driver_sql(\"UPDATE workflow_runs SET status='completed'\")\n\n\ndef queue_run_in(", "t9", "unknown or missing writer"),
    ("B-SCAN-SQL-values", QUEUE, "def queue_run_in(", "def unknown_sql_alias(table):\n    table.update().values(**{'status': 'completed'})\n\n\ndef queue_run_in(", "t9", "unknown or missing writer"),
    ("B-SCAN-fourth-updater", BOX, "def _update_run_row(", "def unknown_updater(execution_id):\n    _update_run_row(execution_id, status='completed')\n\n\ndef _update_run_row(", "t9", "_update_run_row callers changed"),
    ("B-SCAN-known-drop-id", LANE, "meta = dict(row.spawner_metadata or {})", "meta = {}", "t19", "T19 merge identity"),
    ("B5-bare-carried", PARKED, "def _claim_in(", "def fourth(attempt):\n    decide_event(attempt['id'], status=CARRIED_ON)\n\n\ndef _claim_in(", "p14", "bare carried-on writer"),
    ("B5-fourth-wrapper", PARKED, "def _claim_in(", "def fourth(session, attempt):\n    return _claim_in(session, attempt)\n\n\ndef _claim_in(", "p14", "fourth carried-on entry"),
    ("B5-dict-carried", PARKED, "def _claim_in(", "def fourth(attempt):\n    decide_event(attempt['id'], **{'status': CARRIED_ON})\n\n\ndef _claim_in(", "p14", "bare carried-on writer"),
    ("B5-legacy", PARKED, "def _claim_in(", "def claim(attempt):\n    return True\n\n\ndef _claim_in(", "p14", "legacy claim survived"),
    ("B5-forbidden-release", ROUTES, "def _start_resume(", "def forbidden(attempt):\n    pi_parked.release(attempt)\n\n\ndef _start_resume(", "p14", "forbidden release caller"),
    ("P14-no-expect", PARKED, "expect=(WAITING,), status=CARRIED_ON", "expect=(CARRIED_ON,), status=CARRIED_ON", "p14", "P14 CAS scope"),
    ("P14-no-latest", PARKED, "latest_start_condition(Event.execution_id)", "True", "p14", "P14 latest scope"),
    ("T9-no-attempt-increment", BOX, 'attempts=run_row["attempts"] + 1', 'attempts=run_row["attempts"]', "t9", "attempts increment"),
    ("T9-no-generation-increment", BOX, '"attempts": run_row["attempts"] + 1', '"attempts": run_row["attempts"]', "t9", "boxed generation increment"),
    ("T19-no-handle-clear", QUEUE, "row.spawner_handle = None", "row.spawner_handle = 'old'", "t19", "queue identity clear"),
    ("T19-new-stamp-drops-old", WATCH, "mark_lane({**old, **handle.metadata}, lane_of(old))", "mark_lane(handle.metadata, lane_of(old))", "t19", "stamp merge"),
    ("T19-Pi-docker", LANE, 'kind != "subprocess"', 'kind != "docker"', "t19", "Pi subprocess"),
    ("T19-rebind-merge", LANE, "meta = dict(row.spawner_metadata or {})", "meta = dict(row.spawner_metadata or {}); meta = {}", "t19", "merge identity rebound"),
    ("T19-clear-merge", LANE, "meta = dict(row.spawner_metadata or {})", "meta = dict(row.spawner_metadata or {}); meta.clear()", "t19", "merge identity mutated"),
    ("P14-release-guard", ROUTES, "if parked_attempt is not None:\n            _state().running.pop", "if True:\n            _state().running.pop", "p14", "release requires its no-row attempt"),
    ("P14-release-wider-except", ROUTES, "        thread.start()\n    except BaseException:", "        thread.start()\n        work_after_start()\n    except BaseException:", "p14", "may only handle thread.start failure"),
])
def test_source_mutations_bite(assembled, case, path, old, new, check, error):
    sources, original = assembled
    assert old in sources[path], f"{case}: mutation did not touch source"
    changed = sources[path].replace(old, new, 1)
    checks = {"t9": _assert_t9, "t19": _assert_t19, "p14": _assert_p14}
    with pytest.raises(AssertionError, match=error):
        checks[check]({**original, path: Module(path, changed)})
