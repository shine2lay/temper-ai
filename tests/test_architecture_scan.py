"""Tests for scripts/architecture_scan.py — expanded scanner (v2.0.0)."""

import json
import re

# Import scanner module — it lives outside the src package
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import architecture_scan as scanner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(tmp_path: Path, rel: str, content: str) -> dict:
    """Create a file under tmp_path and return a file_info dict."""
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return {"path": rel, "abs_path": str(p), "lines": content.count("\n") + 1}


# ---------------------------------------------------------------------------
# Step 1: broad_except regex
# ---------------------------------------------------------------------------

class TestBroadExceptRegex:
    """Verify the broad_except anti-pattern regex."""

    @pytest.fixture
    def pattern(self):
        entry = next(p for p in scanner.ANTI_PATTERNS if p["name"] == "broad_except")
        return entry["pattern"]

    @pytest.mark.parametrize("line", [
        "    except Exception:",
        "    except Exception as e:",
        "except Exception:",
        "        except Exception as err:",
    ])
    def test_matches_broad_except(self, pattern, line):
        assert re.search(pattern, line), f"Should match: {line}"

    @pytest.mark.parametrize("line", [
        "    except ValueError:",
        "    except ValueError as e:",
        "    except (KeyError, TypeError):",
        "    except:",  # bare except, separate pattern
        "    except OSError as e:",
    ])
    def test_skips_specific_exceptions(self, pattern, line):
        assert not re.search(pattern, line), f"Should NOT match: {line}"


# ---------------------------------------------------------------------------
# Step 2a: Unused imports
# ---------------------------------------------------------------------------

class TestUnusedImports:

    def test_detects_unused_import(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/example.py", """\
            import os
            import sys

            print(sys.argv)
        """)
        result = scanner.scan_unused_imports(tmp_path / "src", [fi])
        names = [d["name"] for d in result["details"]]
        assert "os" in names
        assert "sys" not in names  # sys is used

    def test_skips_init_files(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/__init__.py", """\
            from .submod import Foo
            from .other import Bar
        """)
        result = scanner.scan_unused_imports(tmp_path / "src", [fi])
        assert result["summary"]["total_unused"] == 0

    def test_skips_type_checking_imports(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/typed.py", """\
            from __future__ import annotations
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                from collections import OrderedDict

            def foo() -> None:
                pass
        """)
        result = scanner.scan_unused_imports(tmp_path / "src", [fi])
        # OrderedDict is under TYPE_CHECKING — should not be flagged
        names = [d["name"] for d in result["details"]]
        assert "OrderedDict" not in names

    def test_handles_syntax_error(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/bad.py", """\
            def foo(
        """)
        result = scanner.scan_unused_imports(tmp_path / "src", [fi])
        assert len(result["parse_errors"]) >= 1


# ---------------------------------------------------------------------------
# Step 2b: Missing docstrings
# ---------------------------------------------------------------------------

class TestMissingDocstrings:

    def test_detects_missing_on_public_class(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/nodoc.py", """\
            class Foo:
                pass
        """)
        result = scanner.scan_missing_docstrings(tmp_path / "src", [fi])
        assert result["summary"]["missing_on_classes"] >= 1
        names = [d["name"] for d in result["details"]]
        assert "Foo" in names

    def test_skips_private(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/priv.py", """\
            class _Internal:
                pass

            def _helper():
                pass
        """)
        result = scanner.scan_missing_docstrings(tmp_path / "src", [fi])
        names = [d["name"] for d in result["details"]]
        assert "_Internal" not in names
        assert "_helper" not in names

    def test_not_flagged_when_docstring_present(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/good.py", """\
            class Documented:
                \"\"\"This class has a docstring.\"\"\"
                pass

            def documented_func():
                \"\"\"This function too.\"\"\"
                pass
        """)
        result = scanner.scan_missing_docstrings(tmp_path / "src", [fi])
        names = [d["name"] for d in result["details"]]
        assert "Documented" not in names
        assert "documented_func" not in names


# ---------------------------------------------------------------------------
# Step 2c: Broad try blocks
# ---------------------------------------------------------------------------

class TestBroadTryBlocks:

    def test_detects_broad_try(self, tmp_path):
        # Create a try block with body > 50 lines
        body_lines = "\n".join(f"        x{i} = {i}" for i in range(60))
        fi = _make_file(tmp_path, "src/mod/big_try.py", f"""\
def big():
    try:
{body_lines}
    except Exception:
        pass
""")
        result = scanner.scan_broad_try_blocks(tmp_path / "src", [fi])
        assert result["summary"]["total_broad_try"] >= 1

    def test_short_try_ok(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/short_try.py", """\
            def small():
                try:
                    x = 1
                    y = 2
                except Exception:
                    pass
        """)
        result = scanner.scan_broad_try_blocks(tmp_path / "src", [fi])
        assert result["summary"]["total_broad_try"] == 0


# ---------------------------------------------------------------------------
# Step 3a: pip-audit integration
# ---------------------------------------------------------------------------

class TestPipAudit:

    def test_not_installed(self):
        with patch("architecture_scan.subprocess.run", side_effect=FileNotFoundError):
            result = scanner._run_pip_audit()
        assert result["available"] is False
        assert "not installed" in result["reason"]

    def test_with_vulnerabilities(self):
        mock_output = json.dumps([
            {
                "name": "requests",
                "version": "2.25.0",
                "vulns": [
                    {"id": "GHSA-xxxx-yyyy", "description": "Critical vuln", "fix_versions": ["2.26.0"]}
                ],
            }
        ])
        mock_proc = MagicMock(returncode=1, stdout=mock_output, stderr="")
        with patch("architecture_scan.subprocess.run", return_value=mock_proc):
            result = scanner._run_pip_audit()
        assert result["available"] is True
        assert result["total"] == 1
        assert result["high"] >= 1

    def test_clean(self):
        mock_proc = MagicMock(returncode=0, stdout="[]", stderr="")
        with patch("architecture_scan.subprocess.run", return_value=mock_proc):
            result = scanner._run_pip_audit()
        assert result["available"] is True
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# Step 3b: mypy integration
# ---------------------------------------------------------------------------

class TestMypy:

    def test_not_installed(self):
        with patch("architecture_scan.subprocess.run", side_effect=FileNotFoundError):
            result = scanner._run_mypy(Path("/tmp/src"))
        assert result["available"] is False

    def test_with_errors(self):
        mock_stdout = (
            "src/foo.py:10: error: Incompatible types [assignment]\n"
            "src/bar.py:20: error: Missing return [return]\n"
            "Found 2 errors in 2 files\n"
        )
        mock_proc = MagicMock(returncode=1, stdout=mock_stdout, stderr="")
        with patch("architecture_scan.subprocess.run", return_value=mock_proc):
            result = scanner._run_mypy(Path("/tmp/src"))
        assert result["available"] is True
        assert result["total_errors"] == 2
        assert len(result["details"]) == 2


# ---------------------------------------------------------------------------
# Step 3c: Coverage
# ---------------------------------------------------------------------------

class TestCoverage:

    def test_parse_coverage_json(self, tmp_path):
        cov_data = {
            "meta": {"version": "7.0"},
            "totals": {"percent_covered": 72.5},
            "files": {
                "src/good.py": {"summary": {"percent_covered": 95.0, "missing_lines": 2}},
                "src/bad.py": {"summary": {"percent_covered": 30.0, "missing_lines": 50}},
            },
        }
        cov_file = tmp_path / "coverage.json"
        cov_file.write_text(json.dumps(cov_data))
        result = scanner._parse_coverage_json(cov_file)
        assert result["available"] is True
        assert result["overall_percent"] == 72.5
        assert result["low_coverage_count"] == 1
        assert result["low_coverage_modules"][0]["file"] == "src/bad.py"

    def test_fallback_no_file(self, tmp_path):
        """When no coverage.json exists and pytest not available, graceful."""
        src = tmp_path / "src"
        src.mkdir()
        with patch("architecture_scan.subprocess.run", side_effect=FileNotFoundError):
            result = scanner._run_test_coverage(src)
        assert result["available"] is False


# ---------------------------------------------------------------------------
# Step 4: Scoring
# ---------------------------------------------------------------------------

class TestScoring:

    def _minimal_inputs(self):
        """Return minimal valid inputs for compute_deterministic_score."""
        return {
            "anti_patterns": {"summary": {"critical": 0, "high": 0, "medium": 0, "low": 0}, "details": []},
            "naming_collisions": {"summary": {"total_collisions": 0}},
            "god_objects": {"summary": {"god_classes": 0}},
            "layer_violations": {"summary": {"total_violations": 0}},
            "circular_deps": [],
            "static_analysis": {},
        }

    def test_new_deductions_reduce_score(self):
        inputs = self._minimal_inputs()
        # Without new params: should be 100
        result_old = scanner.compute_deterministic_score(**inputs)
        assert result_old["score"] == 100

        # With unused imports
        result_new = scanner.compute_deterministic_score(
            **inputs,
            unused_imports={"summary": {"total_unused": 50}},
        )
        assert result_new["score"] < 100

    def test_backward_compatible(self):
        """Old call signature (without new params) still works."""
        inputs = self._minimal_inputs()
        result = scanner.compute_deterministic_score(**inputs)
        assert "score" in result
        assert "grade" in result
        assert "deductions" in result

    def test_pip_audit_deduction(self):
        inputs = self._minimal_inputs()
        inputs["static_analysis"] = {
            "pip_audit": {"available": True, "high": 3, "other": 2},
        }
        result = scanner.compute_deterministic_score(**inputs)
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("pip-audit HIGH" in r for r in reasons)
        assert any("pip-audit other" in r for r in reasons)

    def test_mypy_deduction(self):
        inputs = self._minimal_inputs()
        inputs["static_analysis"] = {
            "mypy": {"available": True, "total_errors": 100},
        }
        result = scanner.compute_deterministic_score(**inputs)
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("mypy" in r for r in reasons)

    def test_coverage_deduction(self):
        inputs = self._minimal_inputs()
        result = scanner.compute_deterministic_score(
            **inputs,
            test_coverage={"available": True, "low_coverage_count": 5},
        )
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("low coverage" in r for r in reasons)

    def test_broad_except_not_double_counted(self):
        """broad_except items should be separated from MEDIUM deduction."""
        inputs = self._minimal_inputs()
        inputs["anti_patterns"] = {
            "summary": {"critical": 0, "high": 0, "medium": 10, "low": 0},
            "details": [{"pattern": "broad_except"}] * 5 + [{"pattern": "bare_except"}] * 5,
        }
        result = scanner.compute_deterministic_score(**inputs)
        reasons = [d["reason"] for d in result["deductions"]]
        # Should have separate entries for MEDIUM (excl broad) and broad_except
        assert any("excl. broad_except" in r for r in reasons)
        assert any("broad_except" in r for r in reasons)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:

    def test_two_runs_identical(self, tmp_path):
        """Two runs on the same input produce identical output."""
        src = tmp_path / "src"
        mod = src / "example"
        mod.mkdir(parents=True)
        (mod / "__init__.py").write_text("")
        (mod / "main.py").write_text(textwrap.dedent("""\
            import os

            class Foo:
                pass

            def bar():
                try:
                    x = 1
                except Exception as e:
                    pass
        """))

        files1 = scanner.scan_files(src)
        files2 = scanner.scan_files(src)

        ap1 = scanner.scan_anti_patterns(src, files1["details"])
        ap2 = scanner.scan_anti_patterns(src, files2["details"])

        unused1 = scanner.scan_unused_imports(src, files1["details"])
        unused2 = scanner.scan_unused_imports(src, files2["details"])

        docs1 = scanner.scan_missing_docstrings(src, files1["details"])
        docs2 = scanner.scan_missing_docstrings(src, files2["details"])

        # Compare summaries (skip timestamps)
        assert ap1["summary"] == ap2["summary"]
        assert unused1["summary"] == unused2["summary"]
        assert docs1["summary"] == docs2["summary"]


# ---------------------------------------------------------------------------
# Syntax error handling
# ---------------------------------------------------------------------------

class TestSyntaxErrorGraceful:

    def test_unused_imports_handles_bad_syntax(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/broken.py", "def foo(\n")
        result = scanner.scan_unused_imports(tmp_path / "src", [fi])
        assert len(result["parse_errors"]) >= 1
        assert result["summary"]["total_unused"] == 0

    def test_missing_docstrings_handles_bad_syntax(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/broken.py", "class Incomplete(\n")
        result = scanner.scan_missing_docstrings(tmp_path / "src", [fi])
        assert len(result["parse_errors"]) >= 1

    def test_broad_try_handles_bad_syntax(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/broken.py", "try\n    pass\n")
        result = scanner.scan_broad_try_blocks(tmp_path / "src", [fi])
        assert len(result["parse_errors"]) >= 1


# ---------------------------------------------------------------------------
# Ruff integration
# ---------------------------------------------------------------------------

class TestRuff:

    def test_not_installed(self):
        with patch("architecture_scan.subprocess.run", side_effect=FileNotFoundError):
            result = scanner._run_ruff(Path("/tmp/src"))
        assert result["available"] is False
        assert "not installed" in result["reason"]

    def test_with_findings(self):
        mock_output = json.dumps([
            {
                "code": "F401",
                "message": "os imported but unused",
                "filename": "src/foo.py",
                "location": {"row": 1, "column": 1},
            },
            {
                "code": "S101",
                "message": "Use of assert detected",
                "filename": "src/bar.py",
                "location": {"row": 10, "column": 5},
            },
            {
                "code": "E711",
                "message": "Comparison to None",
                "filename": "src/baz.py",
                "location": {"row": 5, "column": 1},
            },
        ])
        mock_proc = MagicMock(returncode=1, stdout=mock_output, stderr="")
        with patch("architecture_scan.subprocess.run", return_value=mock_proc):
            result = scanner._run_ruff(Path("/tmp/src"))
        assert result["available"] is True
        assert result["total"] == 3
        assert result["errors"] == 1    # F401
        assert result["security"] == 1  # S101
        assert result["warnings"] == 1  # E711

    def test_clean(self):
        mock_proc = MagicMock(returncode=0, stdout="[]", stderr="")
        with patch("architecture_scan.subprocess.run", return_value=mock_proc):
            result = scanner._run_ruff(Path("/tmp/src"))
        assert result["available"] is True
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# Black integration
# ---------------------------------------------------------------------------

class TestBlack:

    def test_not_installed(self):
        with patch("architecture_scan.subprocess.run", side_effect=FileNotFoundError):
            result = scanner._run_black_check(Path("/tmp/src"))
        assert result["available"] is False
        assert "not installed" in result["reason"]

    def test_with_unformatted(self):
        mock_stderr = (
            "would reformat src/foo.py\n"
            "would reformat src/bar.py\n"
            "Oh no! 2 files would be reformatted.\n"
        )
        mock_proc = MagicMock(returncode=1, stdout="", stderr=mock_stderr)
        with patch("architecture_scan.subprocess.run", return_value=mock_proc):
            result = scanner._run_black_check(Path("/tmp/src"))
        assert result["available"] is True
        assert result["total_unformatted"] == 2
        assert len(result["files"]) == 2

    def test_clean(self):
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("architecture_scan.subprocess.run", return_value=mock_proc):
            result = scanner._run_black_check(Path("/tmp/src"))
        assert result["available"] is True
        assert result["total_unformatted"] == 0


# ---------------------------------------------------------------------------
# Vulture integration
# ---------------------------------------------------------------------------

class TestVulture:

    def test_not_installed(self):
        with patch("architecture_scan.subprocess.run", side_effect=FileNotFoundError):
            result = scanner._run_vulture(Path("/tmp/src"))
        assert result["available"] is False
        assert "not installed" in result["reason"]

    def test_with_findings(self):
        mock_stdout = (
            "src/foo.py:10: unused function 'old_func' (90% confidence)\n"
            "src/bar.py:25: unused class 'OldClass' (80% confidence)\n"
            "src/baz.py:5: unused variable 'x' (85% confidence)\n"
        )
        mock_proc = MagicMock(returncode=1, stdout=mock_stdout, stderr="")
        with patch("architecture_scan.subprocess.run", return_value=mock_proc):
            result = scanner._run_vulture(Path("/tmp/src"))
        assert result["available"] is True
        assert result["total_unused"] == 3
        assert result["details"][0]["name"] == "old_func"
        assert result["details"][0]["type"] == "function"
        assert result["details"][0]["confidence"] == 90
        assert result["details"][1]["type"] == "class"
        assert result["details"][2]["type"] == "variable"

    def test_clean(self):
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("architecture_scan.subprocess.run", return_value=mock_proc):
            result = scanner._run_vulture(Path("/tmp/src"))
        assert result["available"] is True
        assert result["total_unused"] == 0


# ---------------------------------------------------------------------------
# Scoring with new tools
# ---------------------------------------------------------------------------

class TestScoringNewTools:

    def _minimal_inputs(self):
        return {
            "anti_patterns": {"summary": {"critical": 0, "high": 0, "medium": 0, "low": 0}, "details": []},
            "naming_collisions": {"summary": {"total_collisions": 0}},
            "god_objects": {"summary": {"god_classes": 0}},
            "layer_violations": {"summary": {"total_violations": 0}},
            "circular_deps": [],
            "static_analysis": {},
        }

    def test_ruff_deduction(self):
        inputs = self._minimal_inputs()
        inputs["static_analysis"] = {
            "ruff": {"available": True, "errors": 10, "security": 5, "warnings": 20, "imports": 3},
        }
        result = scanner.compute_deterministic_score(**inputs)
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("ruff errors" in r for r in reasons)
        assert any("ruff security" in r for r in reasons)
        assert result["score"] < 100

    def test_black_deduction(self):
        inputs = self._minimal_inputs()
        inputs["static_analysis"] = {
            "black": {"available": True, "total_unformatted": 10},
        }
        result = scanner.compute_deterministic_score(**inputs)
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("black" in r for r in reasons)
        assert result["score"] < 100

    def test_vulture_deduction(self):
        inputs = self._minimal_inputs()
        inputs["static_analysis"] = {
            "vulture": {"available": True, "total_unused": 20},
        }
        result = scanner.compute_deterministic_score(**inputs)
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("vulture" in r for r in reasons)
        assert result["score"] < 100

    def test_unavailable_tools_no_deduction(self):
        inputs = self._minimal_inputs()
        inputs["static_analysis"] = {
            "ruff": {"available": False, "reason": "not installed"},
            "black": {"available": False, "reason": "not installed"},
            "vulture": {"available": False, "reason": "not installed"},
        }
        result = scanner.compute_deterministic_score(**inputs)
        assert result["score"] == 100
