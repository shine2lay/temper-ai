"""External tool wrappers — bandit, ruff, mypy, pip-audit.

Each wraps a CLI tool, parses its output, and produces Findings.
Gracefully skips if the tool isn't installed.
"""

import json
import subprocess

from scripts.code_quality_check.base import ExternalToolRule, Finding, ScanContext, Severity


class BanditRule(ExternalToolRule):
    key = "bandit"
    title = "Bandit Security Scanner"
    tool_name = "bandit"
    severity = Severity.HIGH
    tags = ["security"]

    def build_command(self, ctx: ScanContext) -> list[str]:
        return ["bandit", "-r", str(ctx.src_dir), "-f", "json", "-q"]

    def parse_output(self, result: subprocess.CompletedProcess, ctx: ScanContext) -> list[Finding]:
        findings = []
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            return []

        for item in data.get("results", []):
            sev = item.get("issue_severity", "").lower()
            severity = {
                "high": Severity.HIGH,
                "medium": Severity.MEDIUM,
                "low": Severity.LOW,
            }.get(sev, Severity.MEDIUM)

            filename = item.get("filename", "")
            try:
                rel = str(filename).split(str(ctx.src_dir.name) + "/", 1)[-1]
            except (IndexError, ValueError):
                rel = filename

            findings.append(Finding(
                rule=f"{self.key}_{sev}" if sev in ("high", "medium") else self.key,
                message=f"[{item.get('test_id', '')}] {item.get('issue_text', '')}",
                file=rel,
                line=item.get("line_number", 0),
                severity=severity,
            ))

        return findings


class RuffRule(ExternalToolRule):
    key = "ruff"
    title = "Ruff Linter"
    tool_name = "ruff"
    severity = Severity.LOW
    tags = ["lint"]

    def build_command(self, ctx: ScanContext) -> list[str]:
        return ["ruff", "check", str(ctx.src_dir), "--output-format", "json", "--quiet"]

    def parse_output(self, result: subprocess.CompletedProcess, ctx: ScanContext) -> list[Finding]:
        findings = []
        try:
            items = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            return []

        for item in items:
            code = item.get("code", "")
            # Categorize by ruff code prefix
            if code.startswith("S"):
                severity = Severity.MEDIUM
                rule_key = "ruff_security"
            elif code.startswith("F"):
                severity = Severity.LOW
                rule_key = "ruff_errors"
            else:
                continue  # Skip style warnings (E, W, I, etc.)

            filename = item.get("filename", "")
            try:
                rel = str(filename).split(str(ctx.src_dir.name) + "/", 1)[-1]
            except (IndexError, ValueError):
                rel = filename

            findings.append(Finding(
                rule=rule_key,
                message=f"[{code}] {item.get('message', '')}",
                file=rel,
                line=item.get("location", {}).get("row", 0),
                severity=severity,
            ))

        return findings


class MypyRule(ExternalToolRule):
    key = "mypy"
    title = "Mypy Type Checker"
    tool_name = "mypy"
    severity = Severity.LOW
    tags = ["types"]

    def build_command(self, ctx: ScanContext) -> list[str]:
        return ["mypy", str(ctx.src_dir), "--no-error-summary", "--no-color-output"]

    def parse_output(self, result: subprocess.CompletedProcess, ctx: ScanContext) -> list[Finding]:
        findings = []
        for line in result.stdout.strip().split("\n"):
            if not line or ": error:" not in line:
                continue

            # Format: file.py:line: error: message [code]
            parts = line.split(": error:", 1)
            if len(parts) != 2:
                continue

            loc = parts[0]
            message = parts[1].strip()

            file_parts = loc.rsplit(":", 1)
            file_path = file_parts[0]
            line_num = int(file_parts[1]) if len(file_parts) > 1 and file_parts[1].isdigit() else 0

            try:
                rel = str(file_path).split(str(ctx.src_dir.name) + "/", 1)[-1]
            except (IndexError, ValueError):
                rel = file_path

            findings.append(Finding(
                rule="mypy_errors",
                message=message,
                file=rel,
                line=line_num,
                severity=Severity.LOW,
            ))

        return findings


class PipAuditRule(ExternalToolRule):
    key = "pip_audit"
    title = "Pip-Audit Vulnerability Scanner"
    tool_name = "pip-audit"
    severity = Severity.HIGH
    tags = ["security"]

    def build_command(self, ctx: ScanContext) -> list[str]:
        return ["pip-audit", "--format", "json", "--progress-spinner", "off"]

    def parse_output(self, result: subprocess.CompletedProcess, ctx: ScanContext) -> list[Finding]:
        findings = []
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            return []

        deps = data if isinstance(data, list) else data.get("dependencies", [])
        for dep in deps:
            for vuln in dep.get("vulns", []):
                vuln_id = vuln.get("id", "")
                # pip-audit doesn't always provide severity, default to high
                severity = Severity.HIGH if "CVE" in vuln_id else Severity.MEDIUM
                rule_key = "pip_audit_high" if severity == Severity.HIGH else "pip_audit_other"

                findings.append(Finding(
                    rule=rule_key,
                    message=f"{dep.get('name', '')} {dep.get('version', '')}: {vuln_id} — {vuln.get('description', '')[:200]}",
                    severity=severity,
                    metadata={
                        "package": dep.get("name"),
                        "version": dep.get("version"),
                        "vuln_id": vuln_id,
                    },
                ))

        return findings
