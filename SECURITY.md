# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Temper AI, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please email: **shine@wai2shine.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

## Response Timeline

- **Acknowledgment:** Within 48 hours
- **Initial assessment:** Within 5 business days
- **Fix timeline:** Depends on severity, typically within 30 days for critical issues

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Current |

## Current Security Status

Temper AI v0.1.0 is designed for **local development and self-hosted use only**. It is not production-ready.

**Known limitations (planned for future releases):**
- No API authentication — all endpoints are open
- No rate limiting on API endpoints
- No sandboxing of agent tool execution
- LLM agents can execute arbitrary shell commands within safety policy bounds

**Do not expose the server to the public internet.**

## Built-in Protections

The following protections are enforced by default to guard against LLM agents performing unintended actions:

**Bash tool:**
- Command allowlist — only approved commands can execute (configurable per agent)
- Multi-line and chained commands (`&&`, `||`, `;`, `|`) are each checked against the allowlist
- Environment sanitization — all `*_API_KEY`, `*_SECRET`, `*_TOKEN`, and `*_PASSWORD` variables are stripped from the subprocess environment, preventing agents from exfiltrating credentials

**File tools (FileWriter, FileEdit, FileAppend):**
- Forbidden system path blocking — writes to `/etc`, `/sys`, `/proc`, `/dev`, `/boot`, `/sbin` are rejected
- Workspace root enforcement — when `allowed_root` or `workspace_root` is set, all file operations are restricted to that directory tree
- Null byte injection prevention
- Path traversal prevention via `Path.resolve()`

**Safety policies (opt-in via workflow YAML):**
- `BudgetPolicy` — caps total LLM spending per workflow run
- `FileAccessPolicy` — blocks access to specific paths or patterns
- `ForbiddenOpsPolicy` — blocks dangerous shell commands (rm -rf, mkfs, dd, etc.)

## Security Best Practices for Users

- Never commit `.env` files or API keys to version control
- Use environment variables for all secrets
- Always include `safety:` policies in workflow configs — without them, only the built-in tool protections apply
- Run agents with appropriate safety policies (`ForbiddenOpsPolicy`, `FileAccessPolicy`, `BudgetPolicy`)
- Review agent YAML configs before running untrusted workflows
- Use the `--workspace` flag or `workspace_path` input to restrict agent file system access to a specific directory
- Set `TEMPER_DASHBOARD_TOKEN` in `.env` if you need basic API authentication
