#!/usr/bin/env python3
"""Bulk import path rewriter for domain-based modular monolith migration.

Usage:
    python scripts/migrate_modules.py <wave> [--dry-run]

Waves: wave1, wave2, wave3, wave4, wave5, wave6_schemas, wave6_prefixes, wave7
"""

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = [ROOT / "src", ROOT / "tests", ROOT / "alembic", ROOT / "scripts"]


def find_py_files():
    """Yield all .py files under scan directories."""
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(scan_dir):
            dirnames[:] = [
                d for d in dirnames if d != "__pycache__" and not d.startswith(".")
            ]
            for fname in filenames:
                if fname.endswith(".py"):
                    yield Path(dirpath) / fname


def rewrite_prefixes(replacements, dry_run=False):
    """Replace module path prefixes in all Python files.

    replacements: list of (old_prefix, new_prefix) tuples.
    Order matters: more specific prefixes should come first.
    """
    # Compile patterns - order matters (specific before general)
    patterns = []
    for old, new in replacements:
        pat = re.compile(r"\b" + re.escape(old) + r"\b")
        patterns.append((pat, new))

    files_changed = 0
    total_count = 0

    for filepath in find_py_files():
        content = filepath.read_text(encoding="utf-8", errors="replace")
        new_content = content
        file_count = 0

        for pat, replacement in patterns:
            matches = len(pat.findall(new_content))
            if matches:
                new_content = pat.sub(replacement, new_content)
                file_count += matches

        if new_content != content:
            if not dry_run:
                filepath.write_text(new_content, encoding="utf-8")
            files_changed += 1
            total_count += file_count
            print(f"  {'[DRY] ' if dry_run else ''}{filepath.relative_to(ROOT)} ({file_count})")

    print(
        f"\n{'[DRY RUN] ' if dry_run else ''}"
        f"Changed {files_changed} files, {total_count} replacements"
    )
    return files_changed, total_count


# ── Schema class → target module mapping (Wave 6) ──

SCHEMA_CLASS_MAP = {
    # Stage schemas → src.stage._schemas
    "_validate_strategy_string": "src.stage._schemas",
    "StageExecutionConfig": "src.stage._schemas",
    "CollaborationConfig": "src.stage._schemas",
    "ConflictResolutionConfig": "src.stage._schemas",
    "StageSafetyConfig": "src.stage._schemas",
    "StageErrorHandlingConfig": "src.stage._schemas",
    "QualityGatesConfig": "src.stage._schemas",
    "StageConfigInner": "src.stage._schemas",
    "StageConfig": "src.stage._schemas",
    "AgentMetrics": "src.stage._schemas",
    "AggregateMetrics": "src.stage._schemas",
    "MultiAgentStageState": "src.stage._schemas",
    # Workflow schemas → src.workflow._schemas
    "WorkflowStageReference": "src.workflow._schemas",
    "BudgetConfig": "src.workflow._schemas",
    "WorkflowConfigOptions": "src.workflow._schemas",
    "WorkflowSafetyConfig": "src.workflow._schemas",
    "OptimizationConfig": "src.workflow._schemas",
    "WorkflowObservabilityConfig": "src.workflow._schemas",
    "WorkflowErrorHandlingConfig": "src.workflow._schemas",
    "WorkflowConfigInner": "src.workflow._schemas",
    "WorkflowConfig": "src.workflow._schemas",
    # Workflow triggers → src.workflow._triggers
    "EventSourceConfig": "src.workflow._triggers",
    "EventFilterCondition": "src.workflow._triggers",
    "EventFilter": "src.workflow._triggers",
    "ConcurrencyConfig": "src.workflow._triggers",
    "TriggerRetryConfig": "src.workflow._triggers",
    "TriggerMetadata": "src.workflow._triggers",
    "EventTriggerInner": "src.workflow._triggers",
    "CronTriggerInner": "src.workflow._triggers",
    "MetricConfig": "src.workflow._triggers",
    "CompoundCondition": "src.workflow._triggers",
    "CompoundConditions": "src.workflow._triggers",
    "ThresholdTriggerInner": "src.workflow._triggers",
    "EventTrigger": "src.workflow._triggers",
    "CronTrigger": "src.workflow._triggers",
    "ThresholdTrigger": "src.workflow._triggers",
    "TriggerConfig": "src.workflow._triggers",
    # Tool schemas → src.tools._schemas
    "SafetyCheck": "src.tools._schemas",
    "RateLimits": "src.tools._schemas",
    "ToolErrorHandlingConfig": "src.tools._schemas",
    "ToolObservabilityConfig": "src.tools._schemas",
    "ToolRequirements": "src.tools._schemas",
    "ToolConfigInner": "src.tools._schemas",
    "ToolConfig": "src.tools._schemas",
    # Agent schemas (re-exported, canonical in storage after Wave 2)
    "AgentConfig": "src.storage.schemas.agent_config",
    "AgentConfigInner": "src.storage.schemas.agent_config",
    "ErrorHandlingConfig": "src.storage.schemas.agent_config",
    "InferenceConfig": "src.storage.schemas.agent_config",
    "MemoryConfig": "src.storage.schemas.agent_config",
    "MeritTrackingConfig": "src.storage.schemas.agent_config",
    "MetadataConfig": "src.storage.schemas.agent_config",
    "ObservabilityConfig": "src.storage.schemas.agent_config",
    "PreCommand": "src.storage.schemas.agent_config",
    "PromptConfig": "src.storage.schemas.agent_config",
    "RetryConfig": "src.storage.schemas.agent_config",
    "SafetyConfig": "src.storage.schemas.agent_config",
    "ToolReference": "src.storage.schemas.agent_config",
}


def rewrite_schema_imports(dry_run=False):
    """Rewrite `from src.workflow._schemas import X, Y` into domain-specific imports.

    Handles single-line and multi-line (parenthesized) imports.
    """
    # Match: from src.workflow._schemas import ... OR from src.workflow._schemas import X, Y
    pattern = re.compile(
        r"from\s+src\.compiler\.schemas\s+import\s+"
        r"("
        r"\([^)]*\)"  # Multi-line with parens (parens included)
        r"|"
        r"[^\n]+"  # Single-line (rest of line)
        r")",
        re.DOTALL,
    )

    files_changed = 0

    for filepath in find_py_files():
        content = filepath.read_text(encoding="utf-8", errors="replace")
        matches = list(pattern.finditer(content))
        if not matches:
            continue

        new_content = content
        for match in reversed(matches):
            import_text = match.group(1)

            # Strip parens if multi-line
            if import_text.startswith("("):
                import_text = import_text[1:-1]

            # Parse individual names, collecting noqa comments
            names = []
            noqa_comments = []
            for token in re.split(r"[\n,]+", import_text):
                token = token.strip()
                if not token:
                    continue
                # Split off inline comments
                if "#" in token:
                    name_part, comment = token.split("#", 1)
                    name_part = name_part.strip()
                    comment = comment.strip()
                    if "noqa" in comment:
                        noqa_comments.append("# " + comment)
                    if name_part:
                        names.append(name_part)
                else:
                    names.append(token)

            # Group by target module
            groups = defaultdict(list)
            for name in names:
                target = SCHEMA_CLASS_MAP.get(name)
                if target:
                    groups[target].append(name)
                else:
                    print(f"  WARNING: Unknown class '{name}' in {filepath}")
                    groups["src.workflow._schemas"].append(name)

            # Build replacement import lines
            noqa_suffix = "  " + noqa_comments[0] if noqa_comments else ""
            import_lines = []
            for module in sorted(groups):
                cls_names = sorted(groups[module])
                if len(cls_names) > 4:
                    inner = ",\n    ".join(cls_names) + ","
                    import_lines.append(
                        f"from {module} import (\n    {inner}\n){noqa_suffix}"
                    )
                else:
                    import_lines.append(
                        f"from {module} import "
                        + ", ".join(cls_names)
                        + noqa_suffix
                    )
                noqa_suffix = ""  # Only first import gets the noqa

            replacement = "\n".join(import_lines)
            new_content = (
                new_content[: match.start()] + replacement + new_content[match.end() :]
            )

        if new_content != content:
            if not dry_run:
                filepath.write_text(new_content, encoding="utf-8")
            files_changed += 1
            print(
                f"  {'[DRY] ' if dry_run else ''}"
                f"Schema imports updated: {filepath.relative_to(ROOT)}"
            )

    print(
        f"\n{'[DRY RUN] ' if dry_run else ''}"
        f"Schema import files updated: {files_changed}"
    )
    return files_changed


# ── Wave definitions ──

WAVES = {
    "wave1": [
        ("src.shared.constants", "src.shared.constants"),
        ("src.shared.utils", "src.shared.utils"),
        ("src.shared.core", "src.shared.core"),
    ],
    "wave2": [
        ("src.storage.database", "src.storage.database"),
        ("src.storage.schemas", "src.storage.schemas"),
    ],
    "wave3": [
        ("src.llm.cache", "src.llm.cache"),
        ("src.llm.prompts", "src.llm.prompts"),
    ],
    "wave4": [
        ("src.safety.security", "src.safety.security"),
    ],
    "wave5": [
        ("src.agent", "src.agent"),
        ("src.agent.strategies", "src.agent.strategies"),
    ],
    # Wave 6: specific prefixes first, then catch-all
    "wave6_prefixes": [
        ("src.stage.executors", "src.stage.executors"),
        ("src.stage.stage_compiler", "src.stage.stage_compiler"),
        ("src.workflow", "src.workflow"),
    ],
    "wave7": [
        ("src.interfaces.cli", "src.interfaces.cli"),
        ("src.interfaces.dashboard", "src.interfaces.dashboard"),
        ("src.interfaces.server", "src.interfaces.server"),
    ],
}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/migrate_modules.py <wave> [--dry-run]")
        print(f"Available waves: {', '.join(sorted(WAVES))} | wave6_schemas")
        sys.exit(1)

    wave = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    if wave == "wave6_schemas":
        rewrite_schema_imports(dry_run=dry_run)
    elif wave in WAVES:
        rewrite_prefixes(WAVES[wave], dry_run=dry_run)
    else:
        print(f"Unknown wave: {wave}")
        sys.exit(1)
