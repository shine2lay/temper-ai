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


# ---------------------------------------------------------------------------
# v2.2.0: New Anti-Patterns
# ---------------------------------------------------------------------------

class TestNewAntiPatterns:

    def test_pickle_loads_detected(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/unsafe.py", """\
            import pickle
            data = pickle.loads(raw)
        """)
        result = scanner.scan_anti_patterns(tmp_path / "src", [fi])
        names = [d["pattern"] for d in result["details"]]
        assert "pickle_loads" in names

    def test_pickle_load_detected(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/unsafe.py", """\
            import pickle
            data = pickle.load(f)
        """)
        result = scanner.scan_anti_patterns(tmp_path / "src", [fi])
        names = [d["pattern"] for d in result["details"]]
        assert "pickle_loads" in names

    def test_os_system_detected(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/unsafe.py", """\
            import os
            os.system("rm -rf /")
        """)
        result = scanner.scan_anti_patterns(tmp_path / "src", [fi])
        names = [d["pattern"] for d in result["details"]]
        assert "os_system" in names

    def test_marshal_loads_detected(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/unsafe.py", """\
            import marshal
            obj = marshal.loads(data)
        """)
        result = scanner.scan_anti_patterns(tmp_path / "src", [fi])
        names = [d["pattern"] for d in result["details"]]
        assert "marshal_loads" in names

    def test_tempfile_mktemp_detected(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/unsafe.py", """\
            import tempfile
            name = tempfile.mktemp()
        """)
        result = scanner.scan_anti_patterns(tmp_path / "src", [fi])
        names = [d["pattern"] for d in result["details"]]
        assert "tempfile_mktemp" in names

    def test_mkstemp_not_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/safe.py", """\
            import tempfile
            fd, name = tempfile.mkstemp()
        """)
        result = scanner.scan_anti_patterns(tmp_path / "src", [fi])
        names = [d["pattern"] for d in result["details"]]
        assert "tempfile_mktemp" not in names

    def test_md5_detected(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/weak.py", """\
            import hashlib
            h = hashlib.md5(data)
        """)
        result = scanner.scan_anti_patterns(tmp_path / "src", [fi])
        names = [d["pattern"] for d in result["details"]]
        assert "md5_security" in names

    def test_sha1_detected(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/weak.py", """\
            import hashlib
            h = hashlib.sha1(data)
        """)
        result = scanner.scan_anti_patterns(tmp_path / "src", [fi])
        names = [d["pattern"] for d in result["details"]]
        assert "md5_security" in names

    def test_sha256_not_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/safe.py", """\
            import hashlib
            h = hashlib.sha256(data)
        """)
        result = scanner.scan_anti_patterns(tmp_path / "src", [fi])
        names = [d["pattern"] for d in result["details"]]
        assert "md5_security" not in names

    def test_assert_validation_detected(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/validate.py", """\
            def check(x):
                assert x > 0
                return x
        """)
        result = scanner.scan_anti_patterns(tmp_path / "src", [fi])
        names = [d["pattern"] for d in result["details"]]
        assert "assert_validation" in names

    def test_assert_with_noqa_not_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/ok.py", """\
            def check(x):
                assert x > 0  # noqa
                return x
        """)
        result = scanner.scan_anti_patterns(tmp_path / "src", [fi])
        names = [d["pattern"] for d in result["details"]]
        assert "assert_validation" not in names


# ---------------------------------------------------------------------------
# v2.2.0: File Cache
# ---------------------------------------------------------------------------

class TestFileCache:

    def test_cache_builds_correctly(self, tmp_path):
        fi1 = _make_file(tmp_path, "src/mod/a.py", """\
            x = 1
        """)
        fi2 = _make_file(tmp_path, "src/mod/b.py", """\
            class Foo:
                pass
        """)
        cache = scanner._build_file_cache([fi1, fi2])
        assert len(cache) == 2
        for abs_path, (source, tree) in cache.items():
            assert isinstance(source, str)
            assert tree is not None

    def test_cache_handles_syntax_errors(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/bad.py", """\
            def foo(
        """)
        cache = scanner._build_file_cache([fi])
        source, tree = cache[fi["abs_path"]]
        assert isinstance(source, str)
        assert tree is None

    def test_cached_results_match_uncached(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/example.py", """\
            import os
            import sys

            class Foo:
                pass

            def bar():
                try:
                    x = 1
                except Exception as e:
                    pass

            print(sys.argv)
        """)
        src = tmp_path / "src"
        (src / "mod" / "__init__.py").write_text("")
        files = [fi]

        r1 = scanner.scan_anti_patterns(src, files)
        r2 = scanner.scan_unused_imports(src, files)
        r3 = scanner.scan_missing_docstrings(src, files)
        r4 = scanner.scan_broad_try_blocks(src, files)

        cache = scanner._build_file_cache(files)
        c1 = scanner.scan_anti_patterns(src, files, file_cache=cache)
        c2 = scanner.scan_unused_imports(src, files, file_cache=cache)
        c3 = scanner.scan_missing_docstrings(src, files, file_cache=cache)
        c4 = scanner.scan_broad_try_blocks(src, files, file_cache=cache)

        assert r1["summary"] == c1["summary"]
        assert r2["summary"] == c2["summary"]
        assert r3["summary"] == c3["summary"]
        assert r4["summary"] == c4["summary"]

    def test_cache_handles_missing_file(self, tmp_path):
        fi = {"path": "src/mod/gone.py", "abs_path": str(tmp_path / "src/mod/gone.py"), "lines": 0}
        cache = scanner._build_file_cache([fi])
        source, tree = cache[fi["abs_path"]]
        assert source == ""
        assert tree is None


# ---------------------------------------------------------------------------
# v2.2.0: Scoring Gaps
# ---------------------------------------------------------------------------

class TestScoringGaps:

    def _minimal_inputs(self):
        return {
            "anti_patterns": {"summary": {"critical": 0, "high": 0, "medium": 0, "low": 0}, "details": []},
            "naming_collisions": {"summary": {"total_collisions": 0}},
            "god_objects": {"summary": {"god_classes": 0}},
            "layer_violations": {"summary": {"total_violations": 0}},
            "circular_deps": [],
            "static_analysis": {},
        }

    def test_radon_cc_deduction_present(self):
        inputs = self._minimal_inputs()
        inputs["static_analysis"] = {
            "radon_cc": {"available": True, "total_complex": 10},
        }
        result = scanner.compute_deterministic_score(**inputs)
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("radon complex" in r for r in reasons)
        assert result["score"] < 100

    def test_radon_cc_no_deduction_when_zero(self):
        inputs = self._minimal_inputs()
        inputs["static_analysis"] = {
            "radon_cc": {"available": True, "total_complex": 0},
        }
        result = scanner.compute_deterministic_score(**inputs)
        reasons = [d["reason"] for d in result["deductions"]]
        assert not any("radon complex" in r for r in reasons)

    def test_function_docstring_deduction(self):
        inputs = self._minimal_inputs()
        result = scanner.compute_deterministic_score(
            **inputs,
            missing_docstrings={"summary": {"missing_on_classes": 0, "missing_on_functions": 20}},
        )
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("public functions" in r for r in reasons)
        assert result["score"] < 100

    def test_coverage_gap_0pct_worse_than_49pct(self):
        inputs = self._minimal_inputs()
        result_0 = scanner.compute_deterministic_score(
            **inputs,
            test_coverage={
                "available": True,
                "low_coverage_count": 2,
                "low_coverage_modules": [
                    {"file": "a.py", "percent": 0},
                    {"file": "b.py", "percent": 0},
                ],
            },
        )
        result_49 = scanner.compute_deterministic_score(
            **inputs,
            test_coverage={
                "available": True,
                "low_coverage_count": 2,
                "low_coverage_modules": [
                    {"file": "a.py", "percent": 49},
                    {"file": "b.py", "percent": 49},
                ],
            },
        )
        assert result_0["score"] < result_49["score"]

    def test_no_coverage_gap_when_all_above_50(self):
        inputs = self._minimal_inputs()
        result = scanner.compute_deterministic_score(
            **inputs,
            test_coverage={
                "available": True,
                "low_coverage_count": 0,
                "low_coverage_modules": [],
            },
        )
        reasons = [d["reason"] for d in result["deductions"]]
        assert not any("coverage gap" in r for r in reasons)


# ---------------------------------------------------------------------------
# v2.2.0: Parallel Execution
# ---------------------------------------------------------------------------

class TestParallelExecution:

    def test_all_tool_keys_returned(self):
        """Parallel run_static_analysis returns all 8 expected keys."""
        mock_proc = MagicMock(returncode=0, stdout="[]", stderr="")
        with patch("architecture_scan.subprocess.run", return_value=mock_proc):
            result = scanner.run_static_analysis(Path("/tmp/src"))
        expected_keys = {"bandit", "radon_cc", "radon_mi", "pip_audit", "mypy", "ruff", "black", "vulture"}
        assert expected_keys == set(result.keys())

    def test_thread_error_handled(self):
        """A tool that raises an exception is caught gracefully."""
        with patch("architecture_scan._run_bandit", side_effect=RuntimeError("bandit crashed")):
            mock_proc = MagicMock(returncode=0, stdout="[]", stderr="")
            with patch("architecture_scan.subprocess.run", return_value=mock_proc):
                result = scanner.run_static_analysis(Path("/tmp/src"))
        assert "bandit" in result
        assert result["bandit"].get("available") is False or "error" in str(result["bandit"])

    def test_parallel_results_match_expectations(self, tmp_path):
        """Parallel AST scans produce consistent results."""
        fi = _make_file(tmp_path, "src/mod/test.py", """\
            import os

            class Foo:
                pass

            def bar():
                pass
        """)
        src = tmp_path / "src"
        (src / "mod" / "__init__.py").write_text("")
        files = [fi]
        cache = scanner._build_file_cache(files)

        ap = scanner.scan_anti_patterns(src, files, file_cache=cache)
        ui = scanner.scan_unused_imports(src, files, file_cache=cache)
        md = scanner.scan_missing_docstrings(src, files, file_cache=cache)
        bt = scanner.scan_broad_try_blocks(src, files, file_cache=cache)

        assert ap["summary"]["total"] >= 0
        unused_names = [d["name"] for d in ui["details"]]
        assert "os" in unused_names
        missing_names = [d["name"] for d in md["details"]]
        assert "Foo" in missing_names
        assert "bar" in missing_names
        assert bt["summary"]["total_broad_try"] == 0


# ---------------------------------------------------------------------------
# v2.3.0: Function Complexity
# ---------------------------------------------------------------------------

class TestFunctionComplexity:
    """Tests for scan_function_complexity."""

    def test_long_function_flagged(self, tmp_path):
        # Create a function with > 50 lines
        body = "\n".join(f"    x = {i}" for i in range(55))
        code = f"def long_func():\n{body}\n"
        fi = _make_file(tmp_path, "src/mod/long.py", code)
        result = scanner.scan_function_complexity(tmp_path / "src", [fi])
        assert result["summary"]["long_functions"] == 1
        assert len(result["details"]) == 1
        assert "long_function" in result["details"][0]["flags"]

    def test_short_function_ok(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/short.py", """\
            def short_func():
                return 1
        """)
        result = scanner.scan_function_complexity(tmp_path / "src", [fi])
        assert result["summary"]["long_functions"] == 0
        assert result["summary"]["total_functions"] == 1
        assert len(result["details"]) == 0

    def test_high_params_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/params.py", """\
            def many_params(a, b, c, d, e, f, g, h):
                pass
        """)
        result = scanner.scan_function_complexity(tmp_path / "src", [fi])
        assert result["summary"]["high_param_functions"] == 1
        assert "high_param_count" in result["details"][0]["flags"]

    def test_normal_params_ok(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/few.py", """\
            def few_params(a, b, c):
                pass
        """)
        result = scanner.scan_function_complexity(tmp_path / "src", [fi])
        assert result["summary"]["high_param_functions"] == 0
        assert len(result["details"]) == 0

    def test_self_cls_excluded(self, tmp_path):
        # self + 7 params = 8 args total, but self excluded so param_count = 7
        fi = _make_file(tmp_path, "src/mod/method.py", """\
            class Foo:
                def method(self, a, b, c, d, e, f, g):
                    pass
        """)
        result = scanner.scan_function_complexity(tmp_path / "src", [fi])
        # 7 params exactly == threshold, not > threshold
        assert result["summary"]["high_param_functions"] == 0

    def test_deep_nesting_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/nested.py", """\
            def deeply_nested():
                if True:
                    for x in range(10):
                        while True:
                            with open("f"):
                                if True:
                                    pass
        """)
        result = scanner.scan_function_complexity(tmp_path / "src", [fi])
        assert result["summary"]["deep_nesting_functions"] == 1
        assert "deep_nesting" in result["details"][0]["flags"]

    def test_shallow_nesting_ok(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/shallow.py", """\
            def shallow():
                if True:
                    for x in range(10):
                        pass
        """)
        result = scanner.scan_function_complexity(tmp_path / "src", [fi])
        assert result["summary"]["deep_nesting_functions"] == 0
        assert len(result["details"]) == 0

    def test_multiple_flags(self, tmp_path):
        # Long function + high params
        body = "\n".join(f"    x = {i}" for i in range(55))
        code = f"def multi_flag(a, b, c, d, e, f, g, h):\n{body}\n"
        fi = _make_file(tmp_path, "src/mod/multi.py", code)
        result = scanner.scan_function_complexity(tmp_path / "src", [fi])
        flags = result["details"][0]["flags"]
        assert "long_function" in flags
        assert "high_param_count" in flags

    def test_async_functions(self, tmp_path):
        body = "\n".join(f"    x = {i}" for i in range(55))
        code = f"async def async_long():\n{body}\n"
        fi = _make_file(tmp_path, "src/mod/async_fn.py", code)
        result = scanner.scan_function_complexity(tmp_path / "src", [fi])
        assert result["summary"]["long_functions"] == 1
        assert result["details"][0]["name"] == "async_long"

    def test_syntax_error_handled(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/bad.py", """\
            def broken(
                this is not valid python!!!
        """)
        result = scanner.scan_function_complexity(tmp_path / "src", [fi])
        assert result["summary"]["parse_errors"] == 1
        assert len(result["parse_errors"]) == 1


# ---------------------------------------------------------------------------
# v2.3.0: Magic Values
# ---------------------------------------------------------------------------

class TestMagicValues:
    """Tests for scan_magic_values."""

    def test_magic_number_detected(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/magic.py", """\
            x = 42
        """)
        result = scanner.scan_magic_values(tmp_path / "src", [fi])
        assert result["summary"]["total_magic_numbers"] >= 1
        values = [m["value"] for m in result["magic_numbers"]]
        assert 42 in values

    def test_whitelist_not_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/whitelist.py", """\
            a = 0
            b = 1
            c = 2
            d = -1
        """)
        result = scanner.scan_magic_values(tmp_path / "src", [fi])
        assert result["summary"]["total_magic_numbers"] == 0

    def test_bool_not_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/bools.py", """\
            a = True
            b = False
        """)
        result = scanner.scan_magic_values(tmp_path / "src", [fi])
        assert result["summary"]["total_magic_numbers"] == 0

    def test_repeated_string_detected(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/strings.py", """\
            a = "Hello World message"
            b = "Hello World message"
            c = "Hello World message"
        """)
        result = scanner.scan_magic_values(tmp_path / "src", [fi])
        assert result["summary"]["total_repeated_strings"] >= 1
        values = [s["value"] for s in result["repeated_strings"]]
        assert "Hello World message" in values

    def test_docstring_not_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/docs.py", """\
            \"\"\"Module docstring with number 42.\"\"\"

            class Foo:
                \"\"\"Class docstring.\"\"\"
                pass

            def bar():
                \"\"\"Function docstring.\"\"\"
                pass
        """)
        result = scanner.scan_magic_values(tmp_path / "src", [fi])
        assert result["summary"]["total_magic_numbers"] == 0

    def test_dunder_main_not_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/main_check.py", """\
            if __name__ == "__main__":
                pass
        """)
        result = scanner.scan_magic_values(tmp_path / "src", [fi])
        values = [s["value"] for s in result["repeated_strings"]]
        assert "__main__" not in values
        assert "__name__" not in values

    def test_annotation_not_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/typed.py", """\
            def foo(x: int) -> int:
                return x
            count: int = 5
        """)
        result = scanner.scan_magic_values(tmp_path / "src", [fi])
        values = [m["value"] for m in result["magic_numbers"]]
        # 5 is a value assignment, should be flagged
        assert 5 in values

    def test_syntax_error_handled(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/bad.py", """\
            x = !!!not valid python
        """)
        result = scanner.scan_magic_values(tmp_path / "src", [fi])
        assert result["summary"]["parse_errors"] == 1
        assert len(result["parse_errors"]) == 1

    def test_constants_in_nested_structures_not_flagged(self, tmp_path):
        """v2.4.2: Constants in dicts/lists/tuples assigned to UPPERCASE should be skipped."""
        fi = _make_file(tmp_path, "src/mod/nested_const.py", """\
            DEFAULT_THRESHOLDS = {
                "timeout": 5000.0,
                "retries": 3,
            }
            ALLOWED_PORTS = [80, 443, 8080]
            PYTHON_VERSION = (3, 9)
            config = {
                "timeout": 5000.0,
            }
        """)
        result = scanner.scan_magic_values(tmp_path / "src", [fi])
        magic_nums = result["magic_numbers"]
        values = [m["value"] for m in magic_nums]

        # Values in UPPERCASE assignments should NOT be flagged
        # Lines 2-3 are DEFAULT_THRESHOLDS dict
        # Line 5 is ALLOWED_PORTS list
        # Line 6 is PYTHON_VERSION tuple
        assert not any(m["line"] in (2, 3, 5, 6) for m in magic_nums)

        # But the one in lowercase 'config' SHOULD be flagged (line 8)
        assert any(m["value"] == 5000.0 and m["line"] == 8 for m in magic_nums)

        # Should only have 1 magic number (the one in config)
        assert len(magic_nums) == 1

    def test_suppression_comments_skip_magic_numbers(self, tmp_path):
        """v2.4.3: Magic numbers with suppression comments should be skipped."""
        fi = _make_file(tmp_path, "src/mod/suppressed.py", """\
            # Should be flagged
            timeout = 300

            # Should NOT be flagged (noqa)
            version = (3, 9)  # noqa

            # Should NOT be flagged (scanner: skip-magic)
            indent = 4  # scanner: skip-magic

            # Should be flagged
            retries = 5
        """)
        result = scanner.scan_magic_values(tmp_path / "src", [fi])
        magic_nums = result["magic_numbers"]

        # Should only flag lines without suppression comments
        assert len(magic_nums) == 2
        assert any(m["value"] == 300 and m["line"] == 2 for m in magic_nums)
        assert any(m["value"] == 5 and m["line"] == 11 for m in magic_nums)

        # Should NOT flag suppressed lines
        assert not any(m["line"] == 5 for m in magic_nums)  # noqa line
        assert not any(m["line"] == 8 for m in magic_nums)  # scanner: skip-magic line


# ---------------------------------------------------------------------------
# v2.3.0: Dead Code
# ---------------------------------------------------------------------------

class TestDeadCode:
    """Tests for scan_dead_code."""

    def test_after_return_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/dc.py", """\
            def foo():
                return 1
                x = 2
        """)
        result = scanner.scan_dead_code(tmp_path / "src", [fi])
        assert result["summary"]["unreachable_statements"] == 1
        assert any(d["type"] == "unreachable_statement" for d in result["details"])

    def test_after_raise_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/dc2.py", """\
            def foo():
                raise ValueError("err")
                x = 2
        """)
        result = scanner.scan_dead_code(tmp_path / "src", [fi])
        assert result["summary"]["unreachable_statements"] == 1
        assert any("raise" in d["description"].lower() for d in result["details"])

    def test_after_break_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/dc3.py", """\
            for i in range(10):
                break
                x = 2
        """)
        result = scanner.scan_dead_code(tmp_path / "src", [fi])
        assert result["summary"]["unreachable_statements"] == 1
        assert any("break" in d["description"].lower() for d in result["details"])

    def test_after_continue_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/dc4.py", """\
            for i in range(10):
                continue
                x = 2
        """)
        result = scanner.scan_dead_code(tmp_path / "src", [fi])
        assert result["summary"]["unreachable_statements"] == 1
        assert any("continue" in d["description"].lower() for d in result["details"])

    def test_normal_code_ok(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/dc5.py", """\
            def foo():
                x = 1
                y = 2
                return x + y
        """)
        result = scanner.scan_dead_code(tmp_path / "src", [fi])
        assert result["summary"]["unreachable_statements"] == 0
        assert result["summary"]["empty_branches"] == 0
        assert result["summary"]["constant_conditions"] == 0

    def test_empty_if_body_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/dc6.py", """\
            x = 1
            if x:
                pass
        """)
        result = scanner.scan_dead_code(tmp_path / "src", [fi])
        assert result["summary"]["empty_branches"] == 1
        assert any(d["type"] == "empty_branch" for d in result["details"])

    def test_always_true_condition_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/dc7.py", """\
            if True:
                x = 1
        """)
        result = scanner.scan_dead_code(tmp_path / "src", [fi])
        assert result["summary"]["constant_conditions"] == 1
        assert any(d["type"] == "constant_condition" for d in result["details"])

    def test_while_true_not_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/dc8.py", """\
            while True:
                break
        """)
        result = scanner.scan_dead_code(tmp_path / "src", [fi])
        assert result["summary"]["constant_conditions"] == 0


# ---------------------------------------------------------------------------
# v2.3.0: Import Density
# ---------------------------------------------------------------------------

class TestImportDensity:
    """Tests for compute_import_density."""

    def test_fan_out_calculated(self):
        import_data = {"module_graph": {"a": ["b", "c", "d"], "b": ["a"]}}
        result = scanner.compute_import_density(import_data)
        assert result["summary"]["total_modules"] == 2
        assert result["summary"]["avg_fan_out"] == 2.0

    def test_fan_in_calculated(self):
        import_data = {"module_graph": {"a": ["x"], "b": ["x"], "c": ["x"]}}
        result = scanner.compute_import_density(import_data)
        assert result["summary"]["avg_fan_in"] > 0

    def test_high_fan_out_flagged(self):
        imports = [f"mod{i}" for i in range(9)]
        import_data = {"module_graph": {"big_importer": imports}}
        result = scanner.compute_import_density(import_data)
        assert result["summary"]["high_fan_out_count"] == 1
        assert result["fan_out"][0]["module"] == "big_importer"
        assert result["fan_out"][0]["fan_out"] == 9

    def test_high_fan_in_flagged(self):
        graph = {f"mod{i}": ["popular"] for i in range(7)}
        import_data = {"module_graph": graph}
        result = scanner.compute_import_density(import_data)
        assert result["summary"]["high_fan_in_count"] == 1
        assert result["fan_in"][0]["module"] == "popular"
        assert result["fan_in"][0]["fan_in"] == 7

    def test_empty_graph(self):
        import_data = {"module_graph": {}}
        result = scanner.compute_import_density(import_data)
        assert result["summary"]["total_modules"] == 0
        assert result["summary"]["high_fan_out_count"] == 0
        assert result["summary"]["high_fan_in_count"] == 0
        assert result["summary"]["avg_fan_out"] == 0.0
        assert result["summary"]["avg_fan_in"] == 0.0
        assert result["fan_out"] == []
        assert result["fan_in"] == []
        assert result["high_coupling"] == []

    def test_single_module(self):
        import_data = {"module_graph": {"only": ["dep"]}}
        result = scanner.compute_import_density(import_data)
        assert result["summary"]["total_modules"] == 1
        assert result["summary"]["avg_fan_out"] == 1.0
        assert result["summary"]["high_fan_out_count"] == 0
        assert result["summary"]["high_fan_in_count"] == 0


# ---------------------------------------------------------------------------
# v2.3.0: Duplicate Code
# ---------------------------------------------------------------------------

class TestDuplicateCode:
    """Tests for scan_duplicate_code and _normalize_ast_body."""

    def test_identical_functions_detected(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/a.py", """\
            def foo():
                x = 1
                y = 2
                z = x + y
                w = z * 2
                v = w + 1
                return v

            def bar():
                x = 1
                y = 2
                z = x + y
                w = z * 2
                v = w + 1
                return v
        """)
        result = scanner.scan_duplicate_code(tmp_path / "src", [fi])
        assert result["summary"]["duplicate_groups"] == 1
        assert result["summary"]["total_duplicated_functions"] == 2

    def test_variable_renamed_detected(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/b.py", """\
            def alpha():
                a = 1
                b = 2
                c = a + b
                d = c * 2
                e = d + 1
                return e

            def beta():
                x = 1
                y = 2
                z = x + y
                w = z * 2
                v = w + 1
                return v
        """)
        result = scanner.scan_duplicate_code(tmp_path / "src", [fi])
        assert result["summary"]["duplicate_groups"] == 1
        assert result["summary"]["total_duplicated_functions"] == 2

    def test_short_function_not_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/c.py", """\
            def short_a():
                return 1

            def short_b():
                return 1
        """)
        result = scanner.scan_duplicate_code(tmp_path / "src", [fi])
        assert result["summary"]["total_functions_analyzed"] == 0
        assert result["summary"]["duplicate_groups"] == 0

    def test_no_duplicates_clean(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/d.py", """\
            def unique_one():
                a = 10
                b = 20
                c = a + b
                d = c - 1
                e = d * 3
                return e

            def unique_two():
                x = "hello"
                y = "world"
                z = x + " " + y
                w = z.upper()
                v = len(w)
                return v > 0
        """)
        result = scanner.scan_duplicate_code(tmp_path / "src", [fi])
        assert result["summary"]["duplicate_groups"] == 0
        assert result["summary"]["total_duplicated_functions"] == 0

    def test_all_locations_reported(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/e.py", """\
            def first():
                a = 1
                b = 2
                c = a + b
                d = c * 2
                e = d + 1
                return e

            def second():
                x = 1
                y = 2
                z = x + y
                w = z * 2
                v = w + 1
                return v
        """)
        result = scanner.scan_duplicate_code(tmp_path / "src", [fi])
        assert len(result["details"]) == 1
        group = result["details"][0]
        assert group["count"] == 2
        names = {loc["name"] for loc in group["locations"]}
        assert names == {"first", "second"}

    def test_different_logic_not_flagged(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/f.py", """\
            def compute_sum():
                a = 1
                b = 2
                c = a + b
                d = c + 10
                e = d + 20
                return e

            def compute_product():
                a = 1
                b = 2
                c = a * b
                d = c * 10
                e = d * 20
                return e
        """)
        result = scanner.scan_duplicate_code(tmp_path / "src", [fi])
        assert result["summary"]["duplicate_groups"] == 0

    def test_syntax_error_handled(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/broken.py", """\
            def foo(:
                pass
        """)
        result = scanner.scan_duplicate_code(tmp_path / "src", [fi])
        assert result["summary"]["parse_errors"] >= 1
        assert result["summary"]["skipped"] is False

    def test_deterministic_output(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/det.py", """\
            def dup_a():
                x = 1
                y = 2
                z = x + y
                w = z * 2
                v = w + 1
                return v

            def dup_b():
                a = 1
                b = 2
                c = a + b
                d = c * 2
                e = d + 1
                return e
        """)
        r1 = scanner.scan_duplicate_code(tmp_path / "src", [fi])
        r2 = scanner.scan_duplicate_code(tmp_path / "src", [fi])
        assert r1 == r2

    def test_skipped_when_too_many(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/many.py", """\
            def example():
                a = 1
                b = 2
                c = a + b
                d = c * 2
                e = d + 1
                return e
        """)
        with patch.object(scanner, "MAX_FUNCTIONS_FOR_DUPLICATE_SCAN", 0):
            result = scanner.scan_duplicate_code(tmp_path / "src", [fi])
        assert result["summary"]["skipped"] is True
        assert result["summary"]["duplicate_groups"] == 0

    def test_class_methods_included(self, tmp_path):
        fi = _make_file(tmp_path, "src/mod/cls.py", """\
            class MyClass:
                def method_a(self):
                    x = 1
                    y = 2
                    z = x + y
                    w = z * 2
                    v = w + 1
                    return v

            class OtherClass:
                def method_b(self):
                    a = 1
                    b = 2
                    c = a + b
                    d = c * 2
                    e = d + 1
                    return e
        """)
        result = scanner.scan_duplicate_code(tmp_path / "src", [fi])
        assert result["summary"]["duplicate_groups"] == 1
        assert result["summary"]["total_duplicated_functions"] == 2


# ---------------------------------------------------------------------------
# v2.3.0: Test Quality
# ---------------------------------------------------------------------------

class TestTestQuality:
    """Tests for scan_test_quality."""

    def _setup_project(self, tmp_path, src_content, test_content):
        """Helper to create src/ and tests/ dirs for test_quality tests."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text(textwrap.dedent(src_content), encoding="utf-8")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_app.py").write_text(textwrap.dedent(test_content), encoding="utf-8")
        src_lines = src_content.count("\n") + 1
        return src_dir, src_lines

    def test_assert_count_correct(self, tmp_path):
        src_dir, src_lines = self._setup_project(tmp_path, """\
            def add(a, b):
                return a + b
        """, """\
            def test_add():
                assert add(1, 2) == 3
                assert add(0, 0) == 0
                assert add(-1, 1) == 0
        """)
        result = scanner.scan_test_quality(src_dir, src_total_lines=src_lines)
        assert result["summary"]["available"] is True
        assert result["summary"]["total_test_functions"] == 1
        assert result["summary"]["zero_assert_tests"] == 0
        assert result["summary"]["avg_assert_density"] == 3.0

    def test_pytest_raises_counted(self, tmp_path):
        src_dir, src_lines = self._setup_project(tmp_path, """\
            def divide(a, b):
                return a / b
        """, """\
            import pytest
            def test_divide_error():
                with pytest.raises(ZeroDivisionError):
                    divide(1, 0)
        """)
        result = scanner.scan_test_quality(src_dir, src_total_lines=src_lines)
        assert result["summary"]["zero_assert_tests"] == 0
        assert result["summary"]["avg_assert_density"] == 1.0

    def test_mock_assert_counted(self, tmp_path):
        src_dir, src_lines = self._setup_project(tmp_path, """\
            def greet(name):
                return f"Hello, {name}"
        """, """\
            from unittest.mock import MagicMock
            def test_mock():
                m = MagicMock()
                m("hello")
                m.assert_called_once()
                m.assert_called_with("hello")
        """)
        result = scanner.scan_test_quality(src_dir, src_total_lines=src_lines)
        assert result["summary"]["zero_assert_tests"] == 0
        assert result["summary"]["avg_assert_density"] == 2.0

    def test_zero_assert_detected(self, tmp_path):
        src_dir, src_lines = self._setup_project(tmp_path, """\
            def noop():
                pass
        """, """\
            def test_noop():
                noop()
        """)
        result = scanner.scan_test_quality(src_dir, src_total_lines=src_lines)
        assert result["summary"]["zero_assert_tests"] == 1
        assert len(result["zero_assert_details"]) == 1
        assert result["zero_assert_details"][0]["name"] == "test_noop"

    def test_ratio_calculated(self, tmp_path):
        src_content = """\
            def foo():
                return 1
            def bar():
                return 2
        """
        test_content = """\
            def test_foo():
                assert foo() == 1
        """
        src_dir, src_lines = self._setup_project(tmp_path, src_content, test_content)
        result = scanner.scan_test_quality(src_dir, src_total_lines=src_lines)
        assert result["summary"]["test_to_code_ratio"] > 0
        assert isinstance(result["summary"]["test_to_code_ratio"], float)

    def test_no_tests_dir(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("x = 1\n", encoding="utf-8")
        result = scanner.scan_test_quality(src_dir, src_total_lines=100)
        assert result["summary"]["available"] is False
        assert result["summary"]["total_test_files"] == 0

    def test_avg_density_calculated(self, tmp_path):
        src_dir, src_lines = self._setup_project(tmp_path, """\
            def a(): pass
        """, """\
            def test_one():
                assert 1 == 1
                assert 2 == 2
            def test_two():
                assert True
        """)
        result = scanner.scan_test_quality(src_dir, src_total_lines=src_lines)
        assert result["summary"]["total_test_functions"] == 2
        assert result["summary"]["avg_assert_density"] == 1.5

    def test_syntax_error_handled(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("x = 1\n", encoding="utf-8")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_broken.py").write_text("def test_bad(:\n    pass\n", encoding="utf-8")
        result = scanner.scan_test_quality(src_dir, src_total_lines=10)
        assert result["summary"]["available"] is True
        assert result["summary"]["total_test_functions"] == 0


# ---------------------------------------------------------------------------
# v2.3.0: Scoring for new features
# ---------------------------------------------------------------------------

class TestScoringV230:
    """Tests for v2.3.0 scoring deductions."""

    def _minimal_inputs(self):
        return {
            "anti_patterns": {"summary": {"critical": 0, "high": 0, "medium": 0, "low": 0}, "details": []},
            "naming_collisions": {"summary": {"total_collisions": 0}},
            "god_objects": {"summary": {"god_classes": 0}},
            "layer_violations": {"summary": {"total_violations": 0}},
            "circular_deps": [],
            "static_analysis": {},
        }

    def test_function_complexity_deduction(self):
        inputs = self._minimal_inputs()
        result = scanner.compute_deterministic_score(
            **inputs,
            function_complexity={"summary": {"long_functions": 10, "high_param_functions": 5, "deep_nesting_functions": 3}},
        )
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("long functions" in r for r in reasons)
        assert any("high parameter" in r for r in reasons)
        assert any("deep nesting" in r for r in reasons)
        assert result["score"] < 100

    def test_dead_code_deduction(self):
        inputs = self._minimal_inputs()
        result = scanner.compute_deterministic_score(
            **inputs,
            dead_code={"summary": {"unreachable_statements": 5, "empty_branches": 3}},
        )
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("unreachable" in r for r in reasons)
        assert any("empty" in r for r in reasons)
        assert result["score"] < 100

    def test_import_density_deduction(self):
        inputs = self._minimal_inputs()
        result = scanner.compute_deterministic_score(
            **inputs,
            import_density={"summary": {"high_fan_out_count": 3, "high_fan_in_count": 2}},
        )
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("fan-out" in r for r in reasons)
        assert any("fan-in" in r for r in reasons)
        assert result["score"] < 100

    def test_magic_values_deduction(self):
        inputs = self._minimal_inputs()
        result = scanner.compute_deterministic_score(
            **inputs,
            magic_values={"summary": {"total_magic_numbers": 20, "total_repeated_strings": 5}},
        )
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("magic numbers" in r for r in reasons)
        assert any("repeated magic" in r for r in reasons)
        assert result["score"] < 100

    def test_duplicate_code_deduction(self):
        inputs = self._minimal_inputs()
        result = scanner.compute_deterministic_score(
            **inputs,
            duplicate_code={"summary": {"duplicate_groups": 3, "skipped": False}},
        )
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("duplicate" in r for r in reasons)
        assert result["score"] < 100

    def test_test_quality_deduction(self):
        inputs = self._minimal_inputs()
        result = scanner.compute_deterministic_score(
            **inputs,
            test_quality={"summary": {"available": True, "zero_assert_tests": 10}},
        )
        reasons = [d["reason"] for d in result["deductions"]]
        assert any("zero-assert" in r for r in reasons)
        assert result["score"] < 100

    def test_backward_compat_new_params(self):
        """Old call signature (without v2.3.0 params) still works."""
        inputs = self._minimal_inputs()
        result = scanner.compute_deterministic_score(**inputs)
        assert result["score"] == 100

    def test_cap_prevents_dominance(self):
        """Verify scoring caps prevent a single category from dominating."""
        inputs = self._minimal_inputs()
        result = scanner.compute_deterministic_score(
            **inputs,
            magic_values={"summary": {"total_magic_numbers": 1000, "total_repeated_strings": 1000}},
        )
        # Even with 1000 magic numbers, cap is 3+3=6 points max
        assert result["score"] >= 94
