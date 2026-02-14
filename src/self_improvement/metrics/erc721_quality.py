"""
ERC721 workflow quality scorer for M5 self-improvement system.

Scores a workflow run output (0.0 - 1.0) based on:
- Project structure (20%): Required files exist
- Compilation (30%): npx hardhat compile exit code == 0
- Tests pass (30%): npx hardhat test exit code == 0
- Code quality (10%): Static checks on Solidity source
- Deployment (10%): Deploy script runs successfully
"""
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from src.constants.durations import TIMEOUT_VERY_LONG
from src.self_improvement.constants import (
    ERC721_CONTRACTS_PATH,
    ERC721_FILE_EXT_SOL,
    ERC721_FILE_EXT_TEST_JS,
    ERC721_SIMPLENFT,
    ERC721_TEST_PATH,
    ERROR_MSG_NPX_NOT_FOUND,
)
from src.self_improvement.metrics.collector import ExecutionProtocol, MetricCollector
from src.self_improvement.metrics.types import SIMetricType

logger = logging.getLogger(__name__)

# Scoring weight constants (must sum to 1.0)
WEIGHT_PROJECT_STRUCTURE = 0.20  # 20% - File structure completeness
WEIGHT_COMPILATION = 0.30  # 30% - Successful compilation
WEIGHT_TESTS_PASS = 0.30  # 30% - All tests passing
WEIGHT_CODE_QUALITY = 0.10  # 10% - Static analysis quality
WEIGHT_DEPLOYMENT = 0.10  # 10% - Deployment success

# Project structure constants
EXPECTED_DIRECTORY_COUNT = 4  # root files + contract + test + deploy + node_modules

# Output truncation limit (characters)
MAX_OUTPUT_LENGTH = 500  # Maximum length for stdout/stderr in details

# Result dictionary key constants
KEY_SCORE = "score"
KEY_DETAILS = "details"
KEY_EXIT_CODE = "exit_code"
KEY_STDOUT = "stdout"
KEY_STDERR = "stderr"


@dataclass
class ERC721QualityScore:
    """Quality score breakdown for an ERC721 workflow run.

    Attributes:
        total_score: Weighted total score from 0.0 to 1.0
        breakdown: Individual metric scores and details
    """
    total_score: float
    breakdown: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.total_score = max(0.0, min(1.0, self.total_score))


# Weight configuration for scoring
WEIGHTS = {
    "project_structure": WEIGHT_PROJECT_STRUCTURE,
    "compilation": WEIGHT_COMPILATION,
    "tests_pass": WEIGHT_TESTS_PASS,
    "code_quality": WEIGHT_CODE_QUALITY,
    "deployment": WEIGHT_DEPLOYMENT,
}

# Required project files (relative to workspace)
REQUIRED_FILES = [
    "package.json",
    "hardhat.config.js",
]

# Files that should exist under directories
REQUIRED_PATTERNS = {
    "contracts": ERC721_FILE_EXT_SOL,
    "test": ERC721_FILE_EXT_TEST_JS,
}


def _validate_workspace_path(workspace: Path, allowed_root: Optional[Path] = None) -> Path:
    """Validate that a workspace path does not escape the expected root.

    M-12: Prevents path traversal attacks by resolving symlinks and verifying
    the real path starts with the expected workspace root.

    Args:
        workspace: The workspace path to validate.
        allowed_root: The root directory that workspace must reside within.
                      If None, uses the current working directory.

    Returns:
        The resolved (real) workspace Path.

    Raises:
        ValueError: If the resolved path escapes the allowed root directory.
    """
    resolved = Path(os.path.realpath(workspace))
    root = Path(os.path.realpath(allowed_root)) if allowed_root else Path(os.path.realpath(os.getcwd()))

    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(
            f"Workspace path '{workspace}' resolves to '{resolved}' which is "
            f"outside the allowed root directory '{root}'. "
            "This may indicate a path traversal attempt."
        )

    return resolved


def score_project_structure(workspace: Path, contract_name: str = ERC721_SIMPLENFT) -> Dict[str, Any]:  # scanner: skip-radon
    """Score project structure by checking file existence.

    Args:
        workspace: Path to the workspace directory
        contract_name: Name of the contract

    Returns:
        Dict with 'score' (0.0-1.0) and 'details'
    """
    if not workspace.exists():
        return {KEY_SCORE: 0.0, KEY_DETAILS: "Workspace directory does not exist"}

    found = []
    missing = []

    # Check required root files
    for fname in REQUIRED_FILES:
        if (workspace / fname).exists():
            found.append(fname)
        else:
            missing.append(fname)

    # Check contract file
    contract_path = workspace / ERC721_CONTRACTS_PATH.rstrip("/") / f"{contract_name}{ERC721_FILE_EXT_SOL}"
    if contract_path.exists():
        found.append(f"{ERC721_CONTRACTS_PATH}{contract_name}{ERC721_FILE_EXT_SOL}")
    else:
        # Check for any .sol file
        sol_files = list((workspace / ERC721_CONTRACTS_PATH.rstrip("/")).glob(f"*{ERC721_FILE_EXT_SOL}")) if (workspace / ERC721_CONTRACTS_PATH.rstrip("/")).exists() else []
        if sol_files:
            found.append(f"{ERC721_CONTRACTS_PATH}{sol_files[0].name}")
        else:
            missing.append(f"{ERC721_CONTRACTS_PATH}{contract_name}{ERC721_FILE_EXT_SOL}")

    # Check test file
    test_path = workspace / ERC721_TEST_PATH.rstrip("/") / f"{contract_name}{ERC721_FILE_EXT_TEST_JS}"
    if test_path.exists():
        found.append(f"{ERC721_TEST_PATH}{contract_name}{ERC721_FILE_EXT_TEST_JS}")
    else:
        test_files = list((workspace / ERC721_TEST_PATH.rstrip("/")).glob(f"*{ERC721_FILE_EXT_TEST_JS}")) if (workspace / ERC721_TEST_PATH.rstrip("/")).exists() else []
        if test_files:
            found.append(f"{ERC721_TEST_PATH}{test_files[0].name}")
        else:
            missing.append(f"{ERC721_TEST_PATH}{contract_name}{ERC721_FILE_EXT_TEST_JS}")

    # Check deploy script
    if (workspace / "scripts" / "deploy.js").exists():
        found.append("scripts/deploy.js")
    else:
        missing.append("scripts/deploy.js")

    # Check node_modules
    if (workspace / "node_modules").exists():
        found.append("node_modules/")
    else:
        missing.append("node_modules/")

    total_expected = len(REQUIRED_FILES) + EXPECTED_DIRECTORY_COUNT
    score = len(found) / total_expected if total_expected > 0 else 0.0

    return {
        KEY_SCORE: min(1.0, score),
        KEY_DETAILS: {
            "found": found,
            "missing": missing,
        },
    }


def score_compilation(workspace: Path, timeout: int = TIMEOUT_VERY_LONG) -> Dict[str, Any]:
    """Score compilation by running npx hardhat compile.

    Args:
        workspace: Path to the workspace directory
        timeout: Timeout in seconds

    Returns:
        Dict with 'score' (0.0 or 1.0) and 'details'
    """
    if not workspace.exists() or not (workspace / "hardhat.config.js").exists():
        return {KEY_SCORE: 0.0, KEY_DETAILS: "No hardhat.config.js found"}

    try:
        result = subprocess.run(
            ["npx", "hardhat", "compile"],  # noqa: S607 — known CLI tool
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode == 0:
            return {
                KEY_SCORE: 1.0,
                KEY_DETAILS: {KEY_STDOUT: result.stdout[:MAX_OUTPUT_LENGTH], KEY_EXIT_CODE: 0},
            }
        else:
            return {
                KEY_SCORE: 0.0,
                KEY_DETAILS: {
                    KEY_STDOUT: result.stdout[:MAX_OUTPUT_LENGTH],
                    KEY_STDERR: result.stderr[:MAX_OUTPUT_LENGTH],
                    KEY_EXIT_CODE: result.returncode,
                },
            }
    except subprocess.TimeoutExpired:
        return {KEY_SCORE: 0.0, KEY_DETAILS: "Compilation timed out"}
    except FileNotFoundError:
        return {KEY_SCORE: 0.0, KEY_DETAILS: ERROR_MSG_NPX_NOT_FOUND}
    except Exception as e:
        return {KEY_SCORE: 0.0, KEY_DETAILS: f"Error: {e}"}


def score_tests(workspace: Path, timeout: int = TIMEOUT_VERY_LONG) -> Dict[str, Any]:  # scanner: skip-radon
    """Score tests by running npx hardhat test.

    Args:
        workspace: Path to the workspace directory
        timeout: Timeout in seconds

    Returns:
        Dict with 'score' (0.0-1.0) and 'details'
    """
    if not workspace.exists() or not (workspace / "hardhat.config.js").exists():
        return {KEY_SCORE: 0.0, KEY_DETAILS: "No hardhat.config.js found"}

    try:
        result = subprocess.run(
            ["npx", "hardhat", "test"],  # noqa: S607 — known CLI tool
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        stdout = result.stdout
        passing = 0
        failing = 0

        # Parse test output for passing/failing counts
        for line in stdout.split("\n"):
            line_stripped = line.strip()
            if "passing" in line_stripped.lower():
                try:
                    passing = int(line_stripped.split()[0])
                except (ValueError, IndexError):
                    pass
            if "failing" in line_stripped.lower():
                try:
                    failing = int(line_stripped.split()[0])
                except (ValueError, IndexError):
                    pass

        if result.returncode == 0:
            score = 1.0
        elif passing > 0 and failing > 0:
            score = passing / (passing + failing)
        else:
            score = 0.0

        return {
            KEY_SCORE: score,
            KEY_DETAILS: {
                "passing": passing,
                "failing": failing,
                KEY_EXIT_CODE: result.returncode,
                KEY_STDOUT: stdout[:MAX_OUTPUT_LENGTH],
                KEY_STDERR: result.stderr[:MAX_OUTPUT_LENGTH],
            },
        }
    except subprocess.TimeoutExpired:
        return {KEY_SCORE: 0.0, KEY_DETAILS: "Tests timed out"}
    except FileNotFoundError:
        return {KEY_SCORE: 0.0, KEY_DETAILS: "npx not found"}
    except Exception as e:
        return {KEY_SCORE: 0.0, KEY_DETAILS: f"Error: {e}"}


def score_code_quality(workspace: Path, contract_name: str = ERC721_SIMPLENFT) -> Dict[str, Any]:
    """Score code quality with static checks on Solidity source.

    Checks:
    - Imports OpenZeppelin ERC721
    - Has mint function
    - Has constructor
    - Has SPDX license identifier

    Args:
        workspace: Path to the workspace directory
        contract_name: Name of the contract

    Returns:
        Dict with 'score' (0.0-1.0) and 'details'
    """
    contract_path = workspace / ERC721_CONTRACTS_PATH.rstrip("/") / f"{contract_name}{ERC721_FILE_EXT_SOL}"
    if not contract_path.exists():
        # Try any .sol file
        contracts_dir = workspace / ERC721_CONTRACTS_PATH.rstrip("/")
        if contracts_dir.exists():
            sol_files = list(contracts_dir.glob(f"*{ERC721_FILE_EXT_SOL}"))
            if sol_files:
                contract_path = sol_files[0]
            else:
                return {KEY_SCORE: 0.0, KEY_DETAILS: f"No {ERC721_FILE_EXT_SOL} files found"}
        else:
            return {KEY_SCORE: 0.0, KEY_DETAILS: f"No {ERC721_CONTRACTS_PATH} directory"}

    try:
        content = contract_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {KEY_SCORE: 0.0, KEY_DETAILS: f"Cannot read contract: {e}"}

    checks = {
        "imports_erc721": "ERC721" in content,
        "has_mint": "function mint" in content or "function safeMint" in content,
        "has_constructor": "constructor" in content,
        "has_spdx": "SPDX-License-Identifier" in content,
        "has_pragma": "pragma solidity" in content,
        "imports_ownable": "Ownable" in content,
    }

    passed = sum(1 for v in checks.values() if v)
    score = passed / len(checks)

    return {
        KEY_SCORE: score,
        KEY_DETAILS: checks,
    }


def score_deployment(workspace: Path, timeout: int = TIMEOUT_VERY_LONG) -> Dict[str, Any]:
    """Score deployment by running the deploy script on local hardhat node.

    Args:
        workspace: Path to the workspace directory
        timeout: Timeout in seconds

    Returns:
        Dict with 'score' (0.0 or 1.0) and 'details'
    """
    if not workspace.exists() or not (workspace / "scripts" / "deploy.js").exists():
        return {KEY_SCORE: 0.0, KEY_DETAILS: "No deploy script found"}

    try:
        result = subprocess.run(
            ["npx", "hardhat", "run", "scripts/deploy.js"],  # noqa: S607 — known CLI tool
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        if result.returncode == 0:
            return {
                KEY_SCORE: 1.0,
                KEY_DETAILS: {KEY_STDOUT: result.stdout[:MAX_OUTPUT_LENGTH], KEY_EXIT_CODE: 0},
            }
        else:
            return {
                KEY_SCORE: 0.0,
                KEY_DETAILS: {
                    KEY_STDOUT: result.stdout[:MAX_OUTPUT_LENGTH],
                    KEY_STDERR: result.stderr[:MAX_OUTPUT_LENGTH],
                    KEY_EXIT_CODE: result.returncode,
                },
            }
    except subprocess.TimeoutExpired:
        return {KEY_SCORE: 0.0, KEY_DETAILS: "Deployment timed out"}
    except FileNotFoundError:
        return {KEY_SCORE: 0.0, KEY_DETAILS: "npx not found"}
    except Exception as e:
        return {KEY_SCORE: 0.0, KEY_DETAILS: f"Error: {e}"}


def score_erc721_workflow(
    workspace_path: str,
    contract_name: str = ERC721_SIMPLENFT,
    run_commands: bool = True,
    timeout: int = TIMEOUT_VERY_LONG,
    allowed_root: Optional[str] = None,
) -> ERC721QualityScore:
    """Score a complete ERC721 workflow run.

    Args:
        workspace_path: Path to the workspace directory
        contract_name: Name of the contract
        run_commands: Whether to run compile/test/deploy commands
        timeout: Timeout for each command
        allowed_root: Optional root directory to constrain workspace paths.
                      If provided, workspace_path must resolve within this root.

    Returns:
        ERC721QualityScore with total_score and breakdown

    Raises:
        ValueError: If workspace_path escapes the allowed root directory.
    """
    workspace = Path(workspace_path)

    # M-12: Validate workspace path does not escape expected boundaries
    root = Path(allowed_root) if allowed_root else None
    workspace = _validate_workspace_path(workspace, root)

    breakdown = {}

    # 1. Project structure (20%)
    structure = score_project_structure(workspace, contract_name)
    breakdown["project_structure"] = structure

    # 2. Compilation (30%)
    if run_commands:
        compilation = score_compilation(workspace, timeout)
    else:
        compilation = {KEY_SCORE: 0.0, KEY_DETAILS: "Skipped (run_commands=False)"}
    breakdown["compilation"] = compilation

    # 3. Tests (30%)
    if run_commands and compilation[KEY_SCORE] > 0:
        tests = score_tests(workspace, timeout)
    else:
        tests = {KEY_SCORE: 0.0, KEY_DETAILS: "Skipped (compilation failed or commands disabled)"}
    breakdown["tests_pass"] = tests

    # 4. Code quality (10%)
    quality = score_code_quality(workspace, contract_name)
    breakdown["code_quality"] = quality

    # 5. Deployment (10%)
    if run_commands and compilation[KEY_SCORE] > 0:
        deployment = score_deployment(workspace, timeout)
    else:
        deployment = {KEY_SCORE: 0.0, KEY_DETAILS: "Skipped (compilation failed or commands disabled)"}
    breakdown["deployment"] = deployment

    # Calculate weighted total
    total = sum(
        breakdown[metric][KEY_SCORE] * weight
        for metric, weight in WEIGHTS.items()
    )

    return ERC721QualityScore(total_score=total, breakdown=breakdown)


class ERC721QualityCollector(MetricCollector):
    """Metric collector for ERC721 workflow quality.

    Integrates with the M5 metric registry system to track
    ERC721 generation quality over time.
    """

    def __init__(self, workspace_root: Optional[str] = None):
        """Initialize collector.

        Args:
            workspace_root: Base workspace directory path
        """
        self._workspace_root = workspace_root

    @property
    def metric_name(self) -> str:
        """Metric name identifier."""
        return "erc721_quality"

    @property
    def metric_type(self) -> SIMetricType:
        """Metric type identifier."""
        return SIMetricType.CUSTOM

    def collect(self, execution: ExecutionProtocol) -> Optional[float]:
        """Collect quality score from an execution.

        Looks for workspace_path in execution metadata or uses default.

        Args:
            execution: Execution object

        Returns:
            Quality score (0.0-1.0) or None
        """
        # Try to get workspace path from execution metadata
        workspace_path = None
        if hasattr(execution, "metadata") and isinstance(execution.metadata, dict):
            workspace_path = execution.metadata.get("workspace_path")
        if not workspace_path and self._workspace_root:
            workspace_path = self._workspace_root

        if not workspace_path:
            logger.warning("No workspace_path available for ERC721 quality scoring")
            return None

        contract_name = ERC721_SIMPLENFT
        if hasattr(execution, "metadata") and isinstance(execution.metadata, dict):
            contract_name = execution.metadata.get("contract_name", ERC721_SIMPLENFT)

        try:
            result = score_erc721_workflow(
                workspace_path=workspace_path,
                contract_name=contract_name,
                run_commands=True,
            )
            return result.total_score
        except Exception as e:
            logger.error(f"Failed to score ERC721 quality: {e}")
            return None

    def is_applicable(self, execution: ExecutionProtocol) -> bool:
        """Check if this metric applies to the execution.

        Args:
            execution: Execution object

        Returns:
            True if execution is an ERC721 workflow run
        """
        if hasattr(execution, "metadata") and isinstance(execution.metadata, dict):
            return execution.metadata.get("workflow_type") == "erc721_generator"
        return False
