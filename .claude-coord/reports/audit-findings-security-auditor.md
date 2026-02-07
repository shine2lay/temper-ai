# Security Audit Findings

**Auditor:** Security Auditor Agent
**Date:** 2026-02-07 (Phase 1 -- Architecture Audit)
**Scope:** Full codebase security review (src/, configs/, .gitignore, requirements.txt)
**Context:** Architecture audit -- comprehensive security assessment across all modules
**Methodology:** Targeted pattern scanning (injection, auth, secrets, deserialization, input validation, dependencies) + manual code review of all security-critical modules

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 1     |
| HIGH     | 5     |
| MEDIUM   | 8     |
| LOW      | 4     |
| INFO     | 4     |
| **Total** | **22** |

The codebase demonstrates a **mature security posture** with extensive defense-in-depth measures. Jinja2 uses ImmutableSandboxedEnvironment, all YAML uses safe_load, the calculator avoids eval/exec, OAuth implements CSRF+PKCE+secure cookies, logging has 8-layer injection prevention with secret redaction, and checkpoint files use HMAC integrity verification.

The single CRITICAL finding is an SQL injection pattern in the observability database (f-string in `text()` call). The five HIGH findings cover: shell mode attack surface, in-memory-only token storage, ephemeral HMAC keys, unbounded dependency versions, and deprecated TOCTOU-vulnerable rate limiter methods.

---

## Findings

| # | Severity | Category | File:Line | Finding | Recommendation |
|---|----------|----------|-----------|---------|----------------|
| S-01 | CRITICAL | injection | `src/observability/database.py:192` | **SQL injection via f-string in isolation level SET.** `text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level.value}")` uses f-string interpolation inside a raw SQL `text()` call. While `isolation_level.value` comes from a `str` Enum (constrained to 4 valid values), this pattern is fragile: if someone adds a malformed Enum member or passes a raw string via a code change, it becomes exploitable. An attacker controlling the isolation_level parameter could inject arbitrary SQL. | Replace with SQLAlchemy's `execution_options(isolation_level=...)` API. Alternatively, add explicit whitelist validation: `if isolation_level.value not in ('READ UNCOMMITTED', 'READ COMMITTED', 'REPEATABLE READ', 'SERIALIZABLE'): raise ValueError(...)` before the `text()` call. |
| S-02 | HIGH | injection | `src/tools/bash.py:308-437` | **Shell mode (`shell_mode=True`) has a large attack surface.** Despite extensive validation (allowlist, sub-command splitting, path sandbox, substitution blocking, heredoc blocking, brace expansion blocking), `shell=True` with command string passing is inherently risky. The sub-command splitting relies on manual quote-state tracking (`_split_shell_commands`) which may have edge cases. Glob patterns (`*`, `?`) are not blocked and could cause information disclosure. Flag arguments starting with `-` skip path validation (line 416), so `node --output=/etc/shadow` could bypass sandbox checks for commands that accept flag-embedded paths. | (1) Add glob pattern blocking (`*`, `?`, `[`). (2) Parse flag values after `=` and validate them against sandbox. (3) Add fuzzing tests for edge cases: Unicode filenames, escaped quotes, extremely long commands. (4) Consider deprecating shell_mode in favor of structured command builders. |
| S-03 | HIGH | auth | `src/auth/oauth/token_store.py:236-237` | **In-memory-only token storage loses all OAuth tokens on restart.** `self._tokens: Dict[str, bytes] = {}` stores encrypted tokens only in RAM. A server restart loses all user sessions and there is no persistent backend option in `SecureTokenStore`. The audit log (deque) is also ephemeral. | Add a database-backed `PersistentTokenStore` implementation. Abstract storage to allow plugging in Redis or SQLModel-backed persistence. Mark in-memory mode as development-only with runtime warning in production. |
| S-04 | HIGH | secrets | `src/compiler/checkpoint_backends.py:210-220` | **Ephemeral HMAC key defeats checkpoint integrity.** When `CHECKPOINT_HMAC_KEY` env var is not set, a random key is generated per process with `secrets.token_bytes(32)`. This means: (1) checkpoints written by one process cannot be verified by another, (2) after restart, all existing checkpoints fail HMAC verification, (3) an attacker who modifies checkpoint files can wait for process restart to bypass verification. | Require `CHECKPOINT_HMAC_KEY` in production (fail startup if `ENVIRONMENT=production` and key is not set). Document the requirement. Consider deriving from a more stable secret. |
| S-05 | HIGH | dependency | `requirements.txt:13-53` | **All dependencies use `>=` minimum version pins without upper bounds.** `pydantic>=2.12.5`, `httpx>=0.28.1`, `cryptography>=41.0.0`, etc. allow arbitrary future major versions. A compromised future release of any dependency would be automatically installed. Supply chain attacks via unbounded versions are a known attack vector. | Pin exact versions or use bounded ranges (`>=2.12.5,<3.0`). Generate a `requirements.lock` with hashes via `pip-compile --generate-hashes`. Run `pip-audit` in CI. |
| S-06 | HIGH | auth | `src/security/llm_security.py:727-798` | **Deprecated TOCTOU-vulnerable `check_rate_limit()` + `record_call()` methods still exist and are callable.** While they emit deprecation warnings, they remain fully functional. If any code path (current or future) uses them instead of `check_and_record_rate_limit()`, rate limits can be bypassed by concurrent requests racing between check and record. No current callers found (confirmed via grep). | Remove the deprecated methods entirely or make them raise `NotImplementedError`. Since no callers exist, removal is safe. |
| S-07 | MEDIUM | input-validation | `src/security/llm_security.py:316-318` | **Entropy check skipped for inputs 10KB-100KB.** Inputs between `MAX_ENTROPY_LENGTH` (10KB) and `MAX_INPUT_LENGTH` (100KB) skip entropy analysis entirely. An attacker could craft an obfuscated injection payload in this size range that bypasses entropy-based detection. The comment says "acceptable tradeoff for performance." | Consider sampling-based entropy (compute on a random 10KB sample). Document the gap in the security model explicitly. |
| S-08 | MEDIUM | secrets | `src/observability/sanitization.py:152-161` | **HMAC key for observability data pseudonymization is ephemeral by default.** `OBSERVABILITY_HMAC_KEY` env var is optional; if not set, `os.urandom(32)` generates a per-process key. Pseudonymized identifiers cannot be correlated across process restarts, limiting forensic analysis. | Same as S-04: require in production environments. Document the env var requirement. |
| S-09 | MEDIUM | data-exposure | `src/agents/llm/base.py:584,590,637,643` | **`random.random()` used for retry jitter in LLM providers.** While `random.random()` is acceptable for non-security jitter, using the standard `random` module in security-adjacent code creates confusion. The experimentation module correctly uses `secrets.SystemRandom()` for A/B assignment (line 126). | Add comments documenting that standard `random` is intentional for jitter. Consider `secrets.SystemRandom().random()` for codebase consistency, though actual risk is negligible. |
| S-10 | MEDIUM | injection | `src/observability/database.py:56,192` | **IsolationLevel enum values contain raw SQL keywords directly interpolated.** `IsolationLevel.SERIALIZABLE = "SERIALIZABLE"`, `IsolationLevel.READ_COMMITTED = "READ COMMITTED"`. These values are directly interpolated into SQL `text()` calls. The pattern normalizes writing raw SQL via f-strings. | Use SQLAlchemy's `execution_options(isolation_level=level)` API which handles escaping. This is the recommended approach per SQLAlchemy docs. |
| S-11 | MEDIUM | deserialization | `src/compiler/checkpoint_backends.py:436-442` | **Legacy checkpoint files without HMAC accepted with only a warning.** Pre-HMAC checkpoint files are loaded without integrity verification (`logger.warning` only). An attacker with write access to the checkpoint directory could modify legacy checkpoint files to inject data into workflow state. | Add configuration flag `require_hmac=True` (default in production) that rejects legacy checkpoints. Provide a migration script to re-sign old checkpoints. |
| S-12 | MEDIUM | input-validation | `src/compiler/config_loader.py:512-516` | **JSON parsing uses `json.load()` without depth limiting.** While `yaml.safe_load` is used for YAML, JSON parsing has no recursion limit beyond Python's default (1000). A deeply nested JSON config could cause stack overflow. The post-parse `_validate_config_structure` has limits but runs after full parsing completes. | Accept risk since JSON bombs are less dangerous than YAML bombs and post-validation catches the issue. Alternatively, use a streaming JSON parser or validate pre-parse. Document the tradeoff. |
| S-13 | MEDIUM | secrets | `src/auth/oauth/config.py:123,261` | **OAuth client secrets loaded from env vars without keyring fallback.** `SecureTokenStore` provides OS keyring integration for token encryption keys, but OAuth client secrets (long-lived credentials) are loaded directly from environment variables with no keyring option. | Extend keyring integration to cover OAuth client secrets. At minimum, warn in production if secrets are loaded from env vars (similar to token_store.py:193-213). |
| S-14 | MEDIUM | input-validation | `src/compiler/checkpoint_backends.py:625` | **RedisCheckpointBackend crashes when `ttl=None`.** Line 625: `pipe.expire(index_key, self.ttl * 2)` raises `TypeError` when `self.ttl` is `None`. The constructor allows `ttl: Optional[int] = None`. This prevents checkpoint saves to Redis when TTL is not configured. | Guard with `if self.ttl is not None:` before the `expire()` call. |
| S-15 | LOW | secrets | `src/auth/oauth/state_store.py:119,311` | **State tokens partially logged.** `state[:8]` logged in debug messages. 8 chars of URL-safe base64 is ~48 bits, which narrows brute-force if debug logs are exposed. | Reduce to `state[:4]` or use `hashlib.sha256(state.encode()).hexdigest()[:8]` for log correlation without leaking token material. |
| S-16 | LOW | auth | `src/auth/session.py:480` | **`SessionStore = InMemorySessionStore` backward-compat alias.** Code importing `SessionStore` gets the in-memory implementation without explicit warning. | Add deprecation warning to alias or remove it. Users should explicitly import `InMemorySessionStore` or `RedisSessionStore`. |
| S-17 | LOW | input-validation | `src/tools/bash.py:336` | **Brace expansion blocking is overly broad.** `if '{' in command or '}' in command` also blocks legitimate uses like JSON strings in arguments. Not a security risk but reduces usability. | Allow braces inside quoted strings by checking quoting state, similar to operator splitting logic. |
| S-18 | LOW | data-exposure | `src/utils/logging.py:575` | **`log_function_call` decorator logs positional arguments without redaction.** While keyword arguments with sensitive names are redacted, positional args (`*func_args`) are logged as-is. Secrets passed as positional arguments appear in logs. | Add position-based redaction for security-sensitive functions, or log only arg count for positional args. |
| S-19 | INFO | secrets | `.gitignore:32-35` | **`.env` files properly excluded from git.** `.env`, `.env.*`, `.env.local`, `.env.*.local` all in `.gitignore`. Also excludes `.claude-coord/.auth_token` and database files. | No action needed. Positive finding. |
| S-20 | INFO | injection | `src/agents/prompt_engine.py:108,118` | **Jinja2 uses `ImmutableSandboxedEnvironment`.** Both inline and file-loaded templates use the immutable sandbox preventing SSTI. Variable validation with type allowlists (primitives only) and size limits (100KB) add defense-in-depth. Nesting depth limited to 20. | No action needed. Excellent defense-in-depth. |
| S-21 | INFO | auth | `src/auth/oauth/service.py:127,133` | **OAuth HTTP client enforces SSL verification and disables redirect following.** `verify=True` and `follow_redirects=False` explicitly set. Good practice for OAuth flows where redirect manipulation is an attack vector. | No action needed. Positive finding. |
| S-22 | INFO | injection | `src/compiler/config_loader.py:516` | **YAML uses `safe_load` exclusively.** `yaml.safe_load()` prevents unsafe YAML tag deserialization. Combined with file size limits (MAX_CONFIG_SIZE), nesting depth limits (50), node count limits (100K), and circular reference detection. | No action needed. Positive finding. |

---

## Positive Security Observations

The codebase demonstrates mature security practices:

1. **No SQL injection (ORM)** -- All database queries use SQLModel ORM with parameterized queries (except S-01).
2. **No `eval`/`exec`** -- Calculator uses AST-based safe evaluation with allowlisted operators, depth limits (10), and exponent limits (1000).
3. **No unsafe deserialization** -- Only JSON and `yaml.safe_load` used. No pickle, no `yaml.load` without SafeLoader.
4. **No SSL verification bypass** -- No `verify=False` found anywhere in the codebase.
5. **Credential masking in logs** -- Redis URLs use `mask_url_password()`. Centralized pattern-based redaction from `secret_patterns.py` with bounded quantifiers (ReDoS-safe).
6. **Path safety** -- Multiple layers: null byte detection, control character detection, `resolve()` + `relative_to()` containment checks, ID sanitization in checkpoint backends, workspace validation.
7. **Prompt injection detection** -- ReDoS-safe patterns (no nested quantifiers), entropy analysis, keyword detection, input size limits, length-limited evidence.
8. **Output sanitization** -- Longest-match-first secret redaction prevents partial leakage. Deduplication of overlapping matches.
9. **Rate limiting** -- Multi-tier (minute/hour/burst) with atomic check-and-record via Redis Lua scripts (TOCTOU-safe).
10. **Error message sanitization** -- `sanitize_error_message()` applied to all exception types, including `__repr__()` and `to_dict()`.
11. **Environment variable validation** -- Context-aware whitelist-based validation with 6 strictness levels in `EnvVarValidator`.
12. **Token encryption** -- Fernet (AES-128-CBC + HMAC-SHA256) with OS keyring integration, key rotation support, audit logging, bounded access log (10K entries).
13. **Checkpoint integrity** -- HMAC-SHA256 with constant-time comparison (`hmac.compare_digest`), atomic writes via `tempfile.mkstemp` + `os.replace`.
14. **Session security** -- Cryptographically secure session IDs (`secrets.token_urlsafe(32)`), LRU eviction, lazy cleanup.

---

## Priority Remediation Order

1. **S-01** (CRITICAL): SQL injection in isolation level -- quick fix, use `execution_options()` API
2. **S-05** (HIGH): Pin dependency versions -- quick fix with high supply chain impact
3. **S-06** (HIGH): Remove deprecated TOCTOU methods -- quick fix, no callers
4. **S-02** (HIGH): Harden shell mode -- medium effort, expand validation
5. **S-03, S-04** (HIGH): HMAC key management + token persistence -- medium effort
6. **S-11** (MEDIUM): Require HMAC for production checkpoints -- ties to S-04
7. **S-14** (MEDIUM): Fix Redis TTL crash -- one-line fix
8. **S-07, S-08, S-09, S-10, S-12, S-13** (MEDIUM): Incremental hardening

---

## Risk Assessment

**Overall Security Posture: GOOD**

The CRITICAL finding (S-01) is mitigated by the Enum constraint but represents a dangerous coding pattern. The HIGH findings represent defense-in-depth gaps rather than immediately exploitable vulnerabilities:

- **Shell mode (S-02)**: Mitigated by allowlist + sandbox + substitution blocking. Requires LLM output control AND shell_mode opt-in.
- **Token storage (S-03)**: Only affects durability, not confidentiality (tokens are encrypted).
- **HMAC keys (S-04)**: Affects integrity verification across restarts, not at runtime.
- **Dependencies (S-05)**: Standard supply chain risk; mitigated by pip-audit.
- **TOCTOU methods (S-06)**: No current callers; risk is future regression.

No remotely exploitable critical vulnerabilities were found. The auth/OAuth stack, SSRF protections, injection prevention, and prompt security are all well above average for a framework of this complexity.
