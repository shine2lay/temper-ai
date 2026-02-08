"""Tests for ERC721 workflow quality scorer.

Tests cover:
- Project structure scoring
- Compilation scoring
- Test execution scoring
- Code quality checks
- Deployment scoring
- Path traversal prevention
- Metric collector integration
"""
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.self_improvement.metrics.erc721_quality import (
    EXPECTED_DIRECTORY_COUNT,
    ERC721QualityCollector,
    ERC721QualityScore,
    MAX_OUTPUT_LENGTH,
    REQUIRED_FILES,
    WEIGHT_CODE_QUALITY,
    WEIGHT_COMPILATION,
    WEIGHT_DEPLOYMENT,
    WEIGHT_PROJECT_STRUCTURE,
    WEIGHT_TESTS_PASS,
    WEIGHTS,
    _validate_workspace_path,
    score_code_quality,
    score_compilation,
    score_deployment,
    score_erc721_workflow,
    score_project_structure,
    score_tests,
)
from src.self_improvement.metrics.types import SIMetricType


class TestERC721QualityScore:
    """Tests for ERC721QualityScore dataclass."""

    def test_create_score(self):
        """Test creating quality score."""
        score = ERC721QualityScore(
            total_score=0.75,
            breakdown={"test": "data"}
        )

        assert score.total_score == 0.75
        assert score.breakdown == {"test": "data"}

    def test_score_clamping(self):
        """Test that scores are clamped to 0.0-1.0 range."""
        score_high = ERC721QualityScore(total_score=1.5, breakdown={})
        assert score_high.total_score == 1.0

        score_low = ERC721QualityScore(total_score=-0.5, breakdown={})
        assert score_low.total_score == 0.0

    def test_valid_score_range(self):
        """Test scores within valid range."""
        score = ERC721QualityScore(total_score=0.5, breakdown={})
        assert 0.0 <= score.total_score <= 1.0


class TestWeightConfiguration:
    """Tests for weight configuration."""

    def test_weights_sum_to_one(self):
        """Test that all weights sum to 1.0."""
        total = sum(WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=0.001)

    def test_weight_constants_match_dict(self):
        """Test that individual weight constants match WEIGHTS dict."""
        assert WEIGHTS["project_structure"] == WEIGHT_PROJECT_STRUCTURE
        assert WEIGHTS["compilation"] == WEIGHT_COMPILATION
        assert WEIGHTS["tests_pass"] == WEIGHT_TESTS_PASS
        assert WEIGHTS["code_quality"] == WEIGHT_CODE_QUALITY
        assert WEIGHTS["deployment"] == WEIGHT_DEPLOYMENT


class TestValidateWorkspacePath:
    """Tests for workspace path validation (M-12 fix)."""

    def test_validate_workspace_within_root(self, tmp_path):
        """Test validation of workspace within allowed root."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _validate_workspace_path(workspace, tmp_path)
        assert result == workspace.resolve()

    def test_validate_workspace_no_root(self, tmp_path):
        """Test validation with no specified root (uses cwd)."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Should validate against cwd
        with patch('os.getcwd', return_value=str(tmp_path)):
            result = _validate_workspace_path(workspace)
            assert result == workspace.resolve()

    def test_reject_path_traversal_outside_root(self, tmp_path):
        """Test rejection of path traversal attempts."""
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        with pytest.raises(ValueError, match="outside the allowed root"):
            _validate_workspace_path(outside, root)

    def test_reject_symlink_escape(self, tmp_path):
        """Test rejection of symlink escaping root."""
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        # Create symlink pointing outside root
        symlink = root / "escape"
        symlink.symlink_to(outside)

        with pytest.raises(ValueError, match="outside the allowed root"):
            _validate_workspace_path(symlink, root)

    def test_relative_path_resolution(self, tmp_path):
        """Test that relative paths are resolved correctly."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Use relative path with ..
        relative = workspace / ".." / "workspace"
        result = _validate_workspace_path(relative, tmp_path)
        assert result == workspace.resolve()


class TestScoreProjectStructure:
    """Tests for project structure scoring."""

    def test_nonexistent_workspace(self):
        """Test scoring nonexistent workspace."""
        result = score_project_structure(Path("/nonexistent/path"))

        assert result["score"] == 0.0
        assert "does not exist" in result["details"]

    def test_empty_workspace(self, tmp_path):
        """Test scoring empty workspace."""
        result = score_project_structure(tmp_path)

        assert result["score"] < 1.0
        assert len(result["details"]["missing"]) > 0

    def test_complete_project_structure(self, tmp_path):
        """Test scoring complete project structure."""
        # Create all required files
        (tmp_path / "package.json").touch()
        (tmp_path / "hardhat.config.js").touch()

        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()
        (contracts_dir / "SimpleNFT.sol").touch()

        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "SimpleNFT.test.js").touch()

        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "deploy.js").touch()

        (tmp_path / "node_modules").mkdir()

        result = score_project_structure(tmp_path, "SimpleNFT")

        assert result["score"] == 1.0
        assert len(result["details"]["missing"]) == 0
        assert len(result["details"]["found"]) > 0

    def test_partial_project_structure(self, tmp_path):
        """Test scoring partial project structure."""
        # Create only some files
        (tmp_path / "package.json").touch()
        (tmp_path / "hardhat.config.js").touch()

        result = score_project_structure(tmp_path)

        assert 0.0 < result["score"] < 1.0
        assert len(result["details"]["found"]) > 0
        assert len(result["details"]["missing"]) > 0

    def test_alternative_contract_name(self, tmp_path):
        """Test scoring with alternative contract name."""
        (tmp_path / "package.json").touch()
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()
        (contracts_dir / "MyToken.sol").touch()

        result = score_project_structure(tmp_path, "MyToken")

        assert "contracts/MyToken.sol" in result["details"]["found"]

    def test_fallback_to_any_sol_file(self, tmp_path):
        """Test fallback to any .sol file when specific contract not found."""
        (tmp_path / "package.json").touch()
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()
        (contracts_dir / "Other.sol").touch()

        result = score_project_structure(tmp_path, "SimpleNFT")

        assert any(".sol" in f for f in result["details"]["found"])


class TestScoreCompilation:
    """Tests for compilation scoring."""

    def test_no_hardhat_config(self, tmp_path):
        """Test compilation with missing hardhat config."""
        result = score_compilation(tmp_path)

        assert result["score"] == 0.0
        assert "No hardhat.config.js" in result["details"]

    @patch('subprocess.run')
    def test_successful_compilation(self, mock_run, tmp_path):
        """Test successful compilation."""
        (tmp_path / "hardhat.config.js").touch()

        mock_run.return_value = Mock(
            returncode=0,
            stdout="Compiled successfully",
            stderr=""
        )

        result = score_compilation(tmp_path)

        assert result["score"] == 1.0
        assert result["details"]["exit_code"] == 0
        assert "Compiled" in result["details"]["stdout"]
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_failed_compilation(self, mock_run, tmp_path):
        """Test failed compilation."""
        (tmp_path / "hardhat.config.js").touch()

        mock_run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="Compilation error"
        )

        result = score_compilation(tmp_path)

        assert result["score"] == 0.0
        assert result["details"]["exit_code"] == 1
        assert "error" in result["details"]["stderr"].lower()

    @patch('subprocess.run')
    def test_compilation_timeout(self, mock_run, tmp_path):
        """Test compilation timeout."""
        (tmp_path / "hardhat.config.js").touch()

        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["npx"], timeout=30)

        result = score_compilation(tmp_path)

        assert result["score"] == 0.0
        assert "timed out" in result["details"]

    @patch('subprocess.run')
    def test_npx_not_found(self, mock_run, tmp_path):
        """Test handling when npx not found."""
        (tmp_path / "hardhat.config.js").touch()

        mock_run.side_effect = FileNotFoundError()

        result = score_compilation(tmp_path)

        assert result["score"] == 0.0
        assert "npx not found" in result["details"]

    @patch('subprocess.run')
    def test_output_truncation(self, mock_run, tmp_path):
        """Test that long output is truncated."""
        (tmp_path / "hardhat.config.js").touch()

        long_output = "x" * (MAX_OUTPUT_LENGTH + 100)
        mock_run.return_value = Mock(
            returncode=0,
            stdout=long_output,
            stderr=""
        )

        result = score_compilation(tmp_path)

        assert len(result["details"]["stdout"]) <= MAX_OUTPUT_LENGTH


class TestScoreTests:
    """Tests for test execution scoring."""

    def test_no_hardhat_config(self, tmp_path):
        """Test with missing hardhat config."""
        result = score_tests(tmp_path)

        assert result["score"] == 0.0
        assert "No hardhat.config.js" in result["details"]

    @patch('subprocess.run')
    def test_all_tests_pass(self, mock_run, tmp_path):
        """Test all tests passing."""
        (tmp_path / "hardhat.config.js").touch()

        mock_run.return_value = Mock(
            returncode=0,
            stdout="5 passing\n",
            stderr=""
        )

        result = score_tests(tmp_path)

        assert result["score"] == 1.0
        assert result["details"]["passing"] == 5
        assert result["details"]["failing"] == 0

    @patch('subprocess.run')
    def test_all_tests_fail(self, mock_run, tmp_path):
        """Test all tests failing."""
        (tmp_path / "hardhat.config.js").touch()

        mock_run.return_value = Mock(
            returncode=1,
            stdout="0 passing\n3 failing\n",
            stderr=""
        )

        result = score_tests(tmp_path)

        assert result["score"] == 0.0
        assert result["details"]["passing"] == 0
        assert result["details"]["failing"] == 3

    @patch('subprocess.run')
    def test_partial_test_pass(self, mock_run, tmp_path):
        """Test partial test success."""
        (tmp_path / "hardhat.config.js").touch()

        mock_run.return_value = Mock(
            returncode=1,
            stdout="3 passing\n2 failing\n",
            stderr=""
        )

        result = score_tests(tmp_path)

        assert result["score"] == pytest.approx(0.6, abs=0.1)  # 3/(3+2)
        assert result["details"]["passing"] == 3
        assert result["details"]["failing"] == 2

    @patch('subprocess.run')
    def test_test_timeout(self, mock_run, tmp_path):
        """Test timeout handling."""
        (tmp_path / "hardhat.config.js").touch()

        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["npx"], timeout=30)

        result = score_tests(tmp_path)

        assert result["score"] == 0.0
        assert "timed out" in result["details"]


class TestScoreCodeQuality:
    """Tests for code quality scoring."""

    def test_no_contract_file(self, tmp_path):
        """Test with missing contract file."""
        result = score_code_quality(tmp_path)

        assert result["score"] == 0.0
        assert "No contracts/" in result["details"]

    def test_perfect_quality(self, tmp_path):
        """Test contract with all quality checks passing."""
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()

        contract_content = """
        // SPDX-License-Identifier: MIT
        pragma solidity ^0.8.0;

        import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
        import "@openzeppelin/contracts/access/Ownable.sol";

        contract SimpleNFT is ERC721, Ownable {
            constructor() ERC721("Simple", "SMP") {}

            function mint(address to, uint256 tokenId) public onlyOwner {
                _mint(to, tokenId);
            }
        }
        """

        (contracts_dir / "SimpleNFT.sol").write_text(contract_content)

        result = score_code_quality(tmp_path, "SimpleNFT")

        assert result["score"] == 1.0
        assert result["details"]["imports_erc721"] is True
        assert result["details"]["has_mint"] is True
        assert result["details"]["has_constructor"] is True
        assert result["details"]["has_spdx"] is True
        assert result["details"]["has_pragma"] is True
        assert result["details"]["imports_ownable"] is True

    def test_minimal_contract(self, tmp_path):
        """Test minimal contract with few quality features."""
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()

        contract_content = "contract Test {}"
        (contracts_dir / "SimpleNFT.sol").write_text(contract_content)

        result = score_code_quality(tmp_path, "SimpleNFT")

        assert 0.0 <= result["score"] < 1.0
        assert result["details"]["imports_erc721"] is False

    def test_fallback_to_any_sol_file(self, tmp_path):
        """Test fallback to any .sol file."""
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()

        (contracts_dir / "Other.sol").write_text("pragma solidity ^0.8.0;")

        result = score_code_quality(tmp_path, "SimpleNFT")

        assert result["score"] > 0.0  # Found pragma at least

    def test_safemint_alternative(self, tmp_path):
        """Test that safeMint is recognized as mint function."""
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()

        contract_content = """
        pragma solidity ^0.8.0;
        contract Test {
            function safeMint(address to) public {}
        }
        """
        (contracts_dir / "SimpleNFT.sol").write_text(contract_content)

        result = score_code_quality(tmp_path)

        assert result["details"]["has_mint"] is True


class TestScoreDeployment:
    """Tests for deployment scoring."""

    def test_no_deploy_script(self, tmp_path):
        """Test with missing deploy script."""
        result = score_deployment(tmp_path)

        assert result["score"] == 0.0
        assert "No deploy script" in result["details"]

    @patch('subprocess.run')
    def test_successful_deployment(self, mock_run, tmp_path):
        """Test successful deployment."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "deploy.js").touch()

        mock_run.return_value = Mock(
            returncode=0,
            stdout="Deployed to: 0x123...",
            stderr=""
        )

        result = score_deployment(tmp_path)

        assert result["score"] == 1.0
        assert result["details"]["exit_code"] == 0

    @patch('subprocess.run')
    def test_failed_deployment(self, mock_run, tmp_path):
        """Test failed deployment."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "deploy.js").touch()

        mock_run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="Deployment failed"
        )

        result = score_deployment(tmp_path)

        assert result["score"] == 0.0
        assert result["details"]["exit_code"] == 1


class TestScoreERC721Workflow:
    """Tests for complete workflow scoring."""

    def test_empty_workspace(self, tmp_path):
        """Test scoring empty workspace."""
        result = score_erc721_workflow(
            str(tmp_path),
            run_commands=False,
            allowed_root=str(tmp_path.parent)
        )

        assert 0.0 <= result.total_score < 1.0
        assert "project_structure" in result.breakdown
        assert "compilation" in result.breakdown
        assert "tests_pass" in result.breakdown
        assert "code_quality" in result.breakdown
        assert "deployment" in result.breakdown

    def test_workflow_path_validation(self, tmp_path):
        """Test path validation in workflow scoring."""
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        with pytest.raises(ValueError, match="outside the allowed root"):
            score_erc721_workflow(str(outside), allowed_root=str(root))

    @patch('src.self_improvement.metrics.erc721_quality.score_compilation')
    @patch('src.self_improvement.metrics.erc721_quality.score_tests')
    @patch('src.self_improvement.metrics.erc721_quality.score_deployment')
    def test_skip_commands_when_disabled(self, mock_deploy, mock_tests, mock_compile, tmp_path):
        """Test that commands are skipped when run_commands=False."""
        (tmp_path / "package.json").touch()
        (tmp_path / "hardhat.config.js").touch()

        result = score_erc721_workflow(
            str(tmp_path),
            run_commands=False,
            allowed_root=str(tmp_path.parent)
        )

        # Should not call subprocess commands
        mock_compile.assert_not_called()
        mock_tests.assert_not_called()
        mock_deploy.assert_not_called()

    @patch('src.self_improvement.metrics.erc721_quality.score_compilation')
    @patch('src.self_improvement.metrics.erc721_quality.score_tests')
    @patch('src.self_improvement.metrics.erc721_quality.score_deployment')
    def test_skip_tests_if_compilation_fails(self, mock_deploy, mock_tests, mock_compile, tmp_path):
        """Test that tests are skipped if compilation fails."""
        (tmp_path / "package.json").touch()
        (tmp_path / "hardhat.config.js").touch()

        # Compilation fails
        mock_compile.return_value = {"score": 0.0, "details": "Failed"}

        result = score_erc721_workflow(
            str(tmp_path),
            run_commands=True,
            allowed_root=str(tmp_path.parent)
        )

        # Should skip tests and deployment
        mock_compile.assert_called_once()
        mock_tests.assert_not_called()
        mock_deploy.assert_not_called()

        assert result.breakdown["tests_pass"]["score"] == 0.0
        assert "Skipped" in result.breakdown["tests_pass"]["details"]

    def test_weighted_total_calculation(self, tmp_path):
        """Test that weighted total is calculated correctly."""
        # Create minimal structure for known scores
        (tmp_path / "package.json").touch()
        (tmp_path / "hardhat.config.js").touch()

        result = score_erc721_workflow(
            str(tmp_path),
            run_commands=False,
            allowed_root=str(tmp_path.parent)
        )

        # Verify weighted sum
        expected_total = sum(
            result.breakdown[metric]["score"] * weight
            for metric, weight in WEIGHTS.items()
        )

        assert result.total_score == pytest.approx(expected_total, abs=0.001)


class TestERC721QualityCollector:
    """Tests for ERC721QualityCollector integration."""

    def test_create_collector(self):
        """Test creating collector."""
        collector = ERC721QualityCollector()

        assert collector.metric_name == "erc721_quality"
        assert collector.metric_type == SIMetricType.CUSTOM

    def test_collector_with_workspace_root(self):
        """Test collector with workspace root."""
        collector = ERC721QualityCollector(workspace_root="/tmp/workspace")

        assert collector._workspace_root == "/tmp/workspace"

    def test_is_applicable_for_erc721_workflow(self):
        """Test is_applicable returns True for ERC721 workflows."""
        collector = ERC721QualityCollector()

        execution = Mock()
        execution.metadata = {"workflow_type": "erc721_generator"}

        assert collector.is_applicable(execution) is True

    def test_is_applicable_for_other_workflows(self):
        """Test is_applicable returns False for other workflows."""
        collector = ERC721QualityCollector()

        execution = Mock()
        execution.metadata = {"workflow_type": "other"}

        assert collector.is_applicable(execution) is False

    def test_is_applicable_no_metadata(self):
        """Test is_applicable with missing metadata."""
        collector = ERC721QualityCollector()

        execution = Mock(spec=[])  # No metadata attribute

        assert collector.is_applicable(execution) is False

    @patch('src.self_improvement.metrics.erc721_quality.score_erc721_workflow')
    def test_collect_from_execution(self, mock_score, tmp_path):
        """Test collecting metric from execution."""
        mock_score.return_value = ERC721QualityScore(total_score=0.85, breakdown={})

        collector = ERC721QualityCollector()

        execution = Mock()
        execution.metadata = {
            "workflow_type": "erc721_generator",
            "workspace_path": str(tmp_path),
            "contract_name": "MyNFT"
        }

        score = collector.collect(execution)

        assert score == 0.85
        mock_score.assert_called_once_with(
            workspace_path=str(tmp_path),
            contract_name="MyNFT",
            run_commands=True
        )

    def test_collect_no_workspace_path(self):
        """Test collect returns None when no workspace path."""
        collector = ERC721QualityCollector()

        execution = Mock()
        execution.metadata = {}

        score = collector.collect(execution)

        assert score is None

    def test_collect_uses_default_workspace_root(self):
        """Test collect uses default workspace root."""
        collector = ERC721QualityCollector(workspace_root="/tmp/default")

        execution = Mock()
        execution.metadata = {}

        with patch('src.self_improvement.metrics.erc721_quality.score_erc721_workflow') as mock_score:
            mock_score.return_value = ERC721QualityScore(total_score=0.5, breakdown={})

            score = collector.collect(execution)

            if score is not None:  # Only if workspace exists
                mock_score.assert_called()

    @patch('src.self_improvement.metrics.erc721_quality.score_erc721_workflow')
    def test_collect_handles_exceptions(self, mock_score):
        """Test collect handles exceptions gracefully."""
        mock_score.side_effect = Exception("Scoring failed")

        collector = ERC721QualityCollector()

        execution = Mock()
        execution.metadata = {"workspace_path": "/tmp/test"}

        score = collector.collect(execution)

        assert score is None


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_unicode_in_contract_path(self, tmp_path):
        """Test handling of Unicode in file paths."""
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()

        # Unicode filename
        unicode_file = contracts_dir / "Tëst.sol"
        unicode_file.write_text("pragma solidity ^0.8.0;")

        # Should handle gracefully
        result = score_code_quality(tmp_path, "SimpleNFT")
        assert result["score"] >= 0.0

    def test_very_large_output(self, tmp_path):
        """Test handling of very large command output."""
        (tmp_path / "hardhat.config.js").touch()

        huge_output = "x" * (MAX_OUTPUT_LENGTH * 10)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout=huge_output,
                stderr=""
            )

            result = score_compilation(tmp_path)

            # Should truncate
            assert len(result["details"]["stdout"]) <= MAX_OUTPUT_LENGTH

    def test_missing_test_output_numbers(self, tmp_path):
        """Test parsing test output without clear numbers."""
        (tmp_path / "hardhat.config.js").touch()

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="Tests completed",
                stderr=""
            )

            result = score_tests(tmp_path)

            # Should handle gracefully
            assert result["details"]["passing"] == 0
            assert result["details"]["failing"] == 0
