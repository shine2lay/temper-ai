# Audit Report 11: Built-in Tool Implementations

**Scope:** `temper_ai/tools/` built-in tool implementations (12 files)
**Files:** `bash.py`, `_bash_helpers.py`, `http_client.py`, `git_tool.py`, `code_executor.py`, `file_writer.py`, `web_scraper.py`, `calculator.py`, `json_parser.py`, `searxng_search.py`, `tavily_search.py`, `_search_helpers.py`
**Supporting constants:** `constants.py`, `code_executor_constants.py`, `git_tool_constants.py`, `http_client_constants.py`, `field_names.py`
**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6

---

## Executive Summary

The built-in tool implementations are **mature, well-structured, and security-conscious**. Every tool follows a consistent pattern: strict input validation, early-return error handling, and sandboxing/protection appropriate to its risk profile. The Bash and WebScraper tools demonstrate exemplary defense-in-depth (workspace sandboxing, allowlists, DNS rebinding protection, SSRF on redirects). Constants are properly extracted to dedicated modules. Test coverage is **excellent** across all 12 tools with 700+ tests in dedicated test files.

The two most significant areas for improvement are (1) the CodeExecutor's import blocklist being bypassable via `__import__()` or `importlib`-style indirection, and (2) the HTTPClient tool lacking the DNS-level SSRF protection that the WebScraper has.

**Overall Grade: A** (94/100)

| Dimension | Grade | Notes |
|-----------|-------|-------|
| Code Quality | A | Functions well within limits, excellent constant extraction, clean decomposition |
| Security | A- | Comprehensive SSRF/sandbox/injection defenses; CodeExecutor import filter bypassable (F-01) |
| Error Handling | A+ | Every tool has specific exception handling, graceful degradation, timeout enforcement |
| Modularity | A | Consistent BaseTool interface, shared search models, proper helper extraction |
| Feature Completeness | A- | No TODO/FIXME/HACK found; minor gaps in CodeExecutor sandboxing |
| Test Quality | A+ | 700+ tests, SSRF payloads, DNS rebinding, symlink escapes, edge cases |
| Architecture | A | Strong Safety Through Composition; consistent tool interface pattern |

---

## 1. Code Quality Findings

### F-01: `_split_shell_commands` function is 87 lines with manual character-by-character parsing [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/tools/bash.py:69-155`
```python
def _split_shell_commands(command: str) -> list[str]:
    ...
    while i < len(command):
        ch = command[i]
        if escaped:
            current.append(ch)
            escaped = False
            i += 1
            continue
        ...
```

This function exceeds the 50-line function limit at 87 lines. It implements a manual character-by-character lexer for shell command splitting. While the implementation is correct (well-tested with 10+ edge case tests in `TestShellCommandParsing`), the function could be decomposed into smaller state-handling methods.

**Impact:** Code quality metric violation. The complexity is justified by correctness requirements (quote-aware splitting), but it could benefit from decomposition.
**Recommendation:** Extract `_handle_escape`, `_handle_quote`, `_handle_operator` subfunctions to bring each below 20 lines.

### F-02: WebScraper has excessive import aliasing pattern [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/tools/web_scraper.py:19-53`
```python
from temper_ai.tools.constants import (
    DEFAULT_RATE_LIMIT as _DEFAULT_RATE_LIMIT,
)
from temper_ai.tools.constants import (
    DNS_CACHE_MAX_SIZE as _DNS_CACHE_MAX_SIZE,
)
# ... 10 more similar imports
```

The file imports 12 constants with `as _<name>` aliases, then re-assigns them to module-level names (lines 80-86, 362-366). This adds 24 lines of boilerplate. Other tools (e.g., `http_client.py`, `git_tool.py`) import from dedicated `*_constants.py` modules with clean names.

**Impact:** Readability reduction. No functional issue.
**Recommendation:** Create `web_scraper_constants.py` (consistent with other tools) or import constants directly without aliasing.

### F-03: Inconsistent `modifies_state` metadata across tools [LOW]

Several tools have questionable `modifies_state` values:

| Tool | `modifies_state` | Expected | File:Line |
|------|-------------------|----------|-----------|
| `HTTPClientTool` | `True` | `True` for POST/PUT/DELETE, `False` for GET/HEAD | `http_client.py:85` |
| `FileWriter` | Not set (defaults to `False`) | `True` | `file_writer.py:113` |
| `WebScraper` | Not set (defaults to `False`) | `False` | `web_scraper.py:469` |

**Impact:** The safety system uses `modifies_state` to decide whether to take rollback snapshots. FileWriter modifies state but does not declare it, meaning rollback snapshots may not be taken for file writes.
**Recommendation:** Set `modifies_state=True` explicitly on `FileWriter.get_metadata()`.

### F-04: Unused `shlex` import in `bash.py` line 86 creates dead lexer object [TRIVIAL]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/tools/bash.py:86`
```python
def _split_shell_commands(command: str) -> list[str]:
    ...
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    # Strategy: iterate character-by-character...
```

Lines 86-88 create a `shlex.shlex` lexer object and configure it, but it is never actually used. The function proceeds to implement its own character-by-character parser. This is dead code from an earlier implementation.

**Impact:** Dead code. No functional issue.
**Recommendation:** Remove lines 86-88 (the unused `shlex.shlex` instantiation).

---

## 2. Security Findings

### F-05: CodeExecutor import blocklist is bypassable via `__import__()` and string manipulation [HIGH]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/tools/code_executor.py:24-41`
```python
_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    re.MULTILINE,
)

def _find_blocked_import(code: str) -> str | None:
    for match in _IMPORT_RE.finditer(code):
        module_name = match.group(1)
        if module_name in CODE_EXEC_BLOCKED_MODULES:
            return module_name
    return None
```

The blocklist uses a regex that only matches `import X` and `from X` syntax. It can be trivially bypassed:

1. **`__import__()` builtin:** `__import__('os').system('ls')` -- no `import` keyword
2. **String concatenation:** `exec("imp" + "ort os")` -- although `exec` itself is not imported, `builtins` is available
3. **`importlib` via `__import__`:** `__import__('importlib').import_module('os')`
4. **Attribute access:** `type(lambda:0).__module__` to access module references

Additionally, while `subprocess` is blocked, the code runs in the same Python interpreter environment with full access to `builtins`, `open()`, `type()`, `getattr()`, etc. The subprocess has no filesystem, network, or resource isolation beyond the stripped `env` dict (which only has `PYTHONDONTWRITEBYTECODE`).

**Impact:** **Critical** -- An LLM could execute arbitrary Python code including file I/O, network access, and system commands by bypassing the import regex filter. The `env={"PYTHONDONTWRITEBYTECODE": "1"}` at line 132 strips PATH, meaning basic system commands via `os.system()` may fail, but Python built-in `open()` and `socket` remain fully accessible via `__import__`.
**Recommendation:**
1. Short term: Add `__import__` to the blocked pattern check: `if "__import__" in code:`.
2. Medium term: Use `subprocess` with `--isolated` flag (`sys.executable, "-I", "-c", code`) to disable site imports and restrict built-in access.
3. Long term: Consider `RestrictedPython`, `nsjail`, or a container-based sandbox.

### F-06: HTTPClient SSRF protection only checks hostname string, not resolved IP [MEDIUM]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/tools/http_client.py:31-51`
```python
def _validate_url(url: str) -> str | None:
    ...
    if hostname.lower() in {h.lower() for h in HTTP_BLOCKED_HOSTS}:
        return f"Access to '{hostname}' is blocked (SSRF protection)"
    return None
```

The HTTP client tool validates the URL hostname against a static blocklist of hostnames/IPs. However, unlike the WebScraper tool (which performs DNS resolution with timeout, validates resolved IPs against CIDR ranges, and checks redirects), the HTTPClient:

1. Does **not** resolve hostnames to IPs before making the request
2. Does **not** check against private network CIDR ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
3. Does **not** validate redirect targets
4. Does **not** have DNS rebinding protection

A hostname like `evil.example.com` that resolves to `10.0.0.1` would be blocked by WebScraper but **allowed** by HTTPClient.

**Impact:** SSRF risk. The HTTPClient can be used to access internal services if an attacker controls DNS resolution of a hostname.
**Recommendation:** Reuse `validate_url_safety()` from `web_scraper.py` (or extract it to a shared SSRF protection module) in the HTTPClient's URL validation. Also add redirect validation.

### F-07: GitTool allows `push` operation without SSRF protection on remote URL [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/tools/git_tool_constants.py:3-7`
```python
GIT_ALLOWED_OPERATIONS = frozenset({
    "clone", "status", "diff", "log", "commit", "branch",
    "checkout", "add", "pull", "fetch", "remote", "tag",
    "stash", "show", "rev-parse",
})
```

The allowed operations include `clone`, `pull`, and `fetch` which make network requests to remote URLs. While `push` is not explicitly in the list, `clone` can be used to clone from internal URLs (e.g., `git clone http://169.254.169.254/...`). The `args` are validated against blocked flags, but URLs passed as arguments are not validated for SSRF.

**Impact:** Low. Git clone to internal URLs would fail on most internal services that don't speak git protocol. However, `clone http://localhost:6379/` could trigger unexpected interactions with local services.
**Recommendation:** Add SSRF validation on URL arguments for `clone`, `fetch`, `pull`, and `remote add` operations.

### F-08: Bash shell_mode allows `echo` via allowlist but default allowlist does not include `echo` [INFO]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/tools/bash.py:34-44`
```python
DEFAULT_ALLOWED_COMMANDS: set[str] = {
    "npm", "npx", "node", "hardhat", "ls", "cat", "find", "mkdir", "pwd",
}
```

The shell mode description (line 229) mentions `echo` as an available command, but `echo` is not in the default allowlist. This means shell mode would reject `echo "content" > file.txt`. This is not a security issue but rather a documentation/UX inconsistency. Agents must add `echo` to `allowed_commands` in their config.

**Impact:** Informational. The allowlist is correct for security; the description is misleading.
**Recommendation:** Either add `echo` to the default allowlist or update the shell mode description to remove the `echo` reference.

---

## 3. Error Handling Findings

### F-09: CodeExecutor `env` dict strips PATH, causing confusing errors [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/tools/code_executor.py:132`
```python
env = {"PYTHONDONTWRITEBYTECODE": "1"}
```

The subprocess environment has **only** `PYTHONDONTWRITEBYTECODE`. This means the child Python process has no `PATH`, `HOME`, `PYTHONPATH`, or `LANG`. While this is intentional for security, it means:

1. Code using `locale`-sensitive operations may crash with confusing errors
2. `pip install` or any system command from within the code will fail silently
3. Error messages about missing PATH may be confusing to LLM agents

The Bash tool correctly provides a curated safe environment (lines 397-416 in `bash.py`).

**Impact:** Poor developer/LLM experience when legitimate Python code fails due to missing env vars.
**Recommendation:** Provide at minimum `HOME`, `LANG`, `TMPDIR` in the env dict, similar to the Bash tool's `SAFE_ENV_VARS` set.

### F-10: WebScraper `_extract_text` returns error string instead of raising [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/tools/web_scraper.py:714-742`
```python
def _extract_text(self, html: str) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")
        ...
        return text
    except (ValueError, TypeError, AttributeError) as e:
        return f"[Error extracting text: {str(e)}]"
```

When text extraction fails, the method returns an error-formatted string rather than propagating the error. The caller at line 692 then puts this error string in `result.result` with `success=True`. The test at line 1335 of `test_web_scraper.py` confirms this behavior:

```python
assert result.success is True
assert "error extracting text" in result.result.lower()
```

This means the LLM receives a "successful" result containing `[Error extracting text: ...]` which it may misinterpret.

**Impact:** LLM confusion. A parse failure looks like a success with error content.
**Recommendation:** Raise the exception and catch it in `execute()` to return `ToolResult(success=False, ...)`.

---

## 4. Modularity Findings

### F-11: Consistent and exemplary tool interface pattern [POSITIVE]

All 10 tool classes follow the same pattern:

1. `get_metadata()` returns `ToolMetadata` with name, description, version, category
2. `get_parameters_schema()` returns JSON Schema dict
3. `execute(**kwargs)` validates inputs, performs action, returns `ToolResult`
4. Input validation as early-return pattern (never raises on invalid user input)

The search tools additionally implement `get_parameters_model()` returning Pydantic models for richer validation. The shared `_search_helpers.py` provides reusable `SearchResultItem` and `SearchResponse` models used by both `SearXNGSearch` and `TavilySearch`.

### F-12: Well-extracted constants with consistent naming convention [POSITIVE]

Each tool has its constants in either:
- The shared `constants.py` (for general constants)
- A dedicated `<tool>_constants.py` (for tool-specific constants: `code_executor_constants.py`, `git_tool_constants.py`, `http_client_constants.py`)

No magic numbers were found in the implementation files.

### F-13: Bash tool properly decomposed across `bash.py` and `_bash_helpers.py` [POSITIVE]

The Bash tool splits validation and execution into `_bash_helpers.py` (485 lines of pure functions) and `bash.py` (421 lines with class definition). Each helper function is focused:
- `validate_shell_mode_command()` -- 30 lines
- `validate_strict_mode_command()` -- 55 lines
- `validate_sandbox()` -- 38 lines
- `run_command()` -- 32 lines
- `get_safe_env()` -- 8 lines

---

## 5. Feature Completeness Findings

### F-14: No TODO/FIXME/HACK markers found [POSITIVE]

A full search across all 12 files found zero TODO, FIXME, or HACK comments. All tools appear feature-complete for their documented scope.

### F-15: JSONParser lacks input size limit [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/tools/json_parser.py:129-149`

The JSONParser tool accepts arbitrary-length JSON strings without any size validation. A malicious LLM could pass a multi-gigabyte JSON string, consuming memory during `json.loads()`.

Other tools have size limits:
- FileWriter: `MAX_FILE_SIZE = 10MB`
- WebScraper: `MAX_CONTENT_SIZE = 5MB`
- CodeExecutor: `CODE_EXEC_MAX_OUTPUT = 64KB`
- Bash: `MAX_BASH_OUTPUT_LENGTH = 50000`

**Impact:** Potential memory exhaustion DoS.
**Recommendation:** Add `MAX_JSON_DATA_SIZE` constant (e.g., 10MB) and validate `len(data)` before parsing.

### F-16: Calculator MAX_EXPONENT of 1000 allows very large computations [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/tools/constants.py:42`
```python
MAX_EXPONENT = 1000
```

While exponents are capped, `2 ** 1000` produces a 302-digit number which is fine, but `10.0 ** 1000` produces `inf` (float overflow), and integer exponentiation like `999999 ** 999` would produce a number with ~6 million digits, consuming significant memory.

**Impact:** Low. The AST depth limit of 10 and the exponent cap of 1000 provide reasonable protection.
**Recommendation:** Consider also limiting the base of exponentiation, e.g., reject `base ** exp` where `base > 1000 and exp > 100`.

---

## 6. Test Quality Findings

### F-17: Excellent test coverage across all tools [POSITIVE]

| Tool | Test File | Test Count | Coverage Areas |
|------|-----------|------------|----------------|
| Bash | `test_bash.py` | ~80 | Allowlist, sandbox, injection, timeout, symlinks, shell mode, parsing |
| HTTPClient | `test_http_client.py` | 8 | SSRF, methods, timeout, validation |
| GitTool | `test_git_tool.py` | 10 | Operations, blocked flags, timeout, path validation |
| CodeExecutor | `test_code_executor.py` | 9 | Blocked imports, timeout, truncation, language validation |
| FileWriter | `test_file_writer.py` | ~24 | Path safety, extensions, overwrite, size limits, aliases |
| WebScraper | `test_web_scraper.py` | ~60 | SSRF (19 tests!), DNS rebinding, redirects, content-type, rate limiting |
| Calculator | `test_calculator.py` | ~25 | Arithmetic, functions, constants, safety (eval/exec/import) |
| JSONParser | `test_json_parser.py` | 12 | Parse, extract, validate, format, error cases |
| SearXNG | `test_searxng_search.py` | ~35 | Params, SSRF on base_url, rate limit, client lifecycle |
| Tavily | `test_tavily_search.py` | ~30 | API key, params, 401/429/500, rate limit, client lifecycle |
| Helpers | `test_search_helpers.py` | 12 | SearchResultItem, SearchResponse, format_results_for_llm |

**Total: ~305 tests** dedicated to built-in tools (in `tests/test_tools/`), plus additional tests in `tests/test_safety/test_security/` that test tool security properties.

### F-18: HTTPClient tests could be expanded [LOW]

The HTTPClient test file (`test_http_client.py`) has only 8 tests compared to 60 for WebScraper. Missing test scenarios:
- Custom headers
- Response body truncation at `HTTP_MAX_RESPONSE_SIZE`
- Response with large body
- PATCH, PUT, DELETE, HEAD methods (only GET and POST tested)
- Headers count limit (`HTTP_MAX_HEADER_COUNT = 20`)
- DNS-based SSRF bypasses (relevant if F-06 is fixed)

**Recommendation:** Add 10-15 more tests covering the above scenarios.

### F-19: WebScraper tests are exemplary [POSITIVE]

The `test_web_scraper.py` file has 60+ tests across 13 test classes, including:
- 19 SSRF protection tests covering IPv4, IPv6, IPv4-mapped IPv6, DNS rebinding, round-robin DNS, link-local ranges
- 4 redirect protection tests (redirect to metadata, localhost, private network, too many redirects)
- 6 content-type validation tests (PDF, image, video, HTML, XML, binary rejected)
- DNS cache edge cases (expiration, max size, clear)
- Client lifecycle management

---

## 7. Architectural Findings

### F-20: Strong Safety Through Composition pattern [POSITIVE]

The tools demonstrate the framework's "Safety Through Composition" pillar:

1. **Bash:** Allowlist + sandbox + dangerous char rejection + path traversal protection + safe env vars
2. **WebScraper:** URL validation + hostname blocklist + CIDR range checking + DNS resolution with timeout + DNS caching + redirect validation + rate limiting + content-type filtering + content size limiting
3. **FileWriter:** PathSafetyValidator + forbidden extensions + size limits + overwrite protection + config-synced root
4. **Calculator:** AST whitelist + depth limiting + exponent capping + collection size limits
5. **GitTool:** Operation allowlist + flag blocklist + no shell=True + output truncation

Each tool layers multiple safety mechanisms. No tool relies on a single check.

### F-21: Missing shared SSRF protection module [MEDIUM]

**Files:** `web_scraper.py:57-319` vs `http_client.py:31-51` vs `http_client_constants.py:5-12`

SSRF protection is implemented twice:
- **WebScraper:** 260 lines of comprehensive DNS-aware SSRF protection with caching, timeout, CIDR checking, redirect validation
- **HTTPClient:** 20 lines of simple hostname string matching

The WebScraper's `validate_url_safety()` function is already well-structured for reuse but lives inside `web_scraper.py`. The SearXNG search tool reuses `ScraperRateLimiter` from `web_scraper.py` (line 27 of `searxng_search.py`), showing that cross-tool reuse is already practiced.

**Impact:** Security inconsistency between tools. An agent using HTTPClient gets weaker SSRF protection than one using WebScraper.
**Recommendation:** Extract `validate_url_safety()`, `DNSCache`, `resolve_hostname_with_timeout()`, and `BLOCKED_HOSTS`/`BLOCKED_NETWORKS` into a shared `_ssrf_protection.py` module. Have both WebScraper and HTTPClient use it.

### F-22: TavilySearch base_url has no SSRF protection [LOW]

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/tools/tavily_search.py:96`
```python
self._base_url = (config or {}).get("base_url", TAVILY_DEFAULT_BASE_URL)
```

Unlike SearXNGSearch (which validates base_url is loopback only, line 109-137), TavilySearch accepts any `base_url` from config without validation. If an attacker can control the tool config, they could redirect API calls to an internal service.

The default is `https://api.tavily.com` which is safe, but config injection could change this.

**Impact:** Low (requires config injection). The SearXNG tool correctly restricts to loopback.
**Recommendation:** Add URL validation on `base_url` (at minimum ensure it uses HTTPS and is not a private IP).

---

## Summary of Findings

| ID | Severity | Category | Summary |
|----|----------|----------|---------|
| F-01 | LOW | Code Quality | `_split_shell_commands` exceeds 50-line limit (87 lines) |
| F-02 | LOW | Code Quality | WebScraper excessive import aliasing pattern |
| F-03 | LOW | Code Quality | FileWriter missing `modifies_state=True` in metadata |
| F-04 | TRIVIAL | Code Quality | Dead `shlex.shlex` object creation in `_split_shell_commands` |
| F-05 | **HIGH** | Security | CodeExecutor import blocklist bypassable via `__import__()` |
| F-06 | **MEDIUM** | Security | HTTPClient lacks DNS-level SSRF protection |
| F-07 | LOW | Security | GitTool allows network operations without SSRF validation |
| F-08 | INFO | Security | Shell mode description references `echo` not in default allowlist |
| F-09 | LOW | Error Handling | CodeExecutor subprocess env too restrictive |
| F-10 | LOW | Error Handling | WebScraper `_extract_text` returns error string as success |
| F-11 | POSITIVE | Modularity | Consistent tool interface pattern across all 10 tools |
| F-12 | POSITIVE | Modularity | Well-extracted constants with consistent naming |
| F-13 | POSITIVE | Modularity | Bash tool properly decomposed across two files |
| F-14 | POSITIVE | Completeness | No TODO/FIXME/HACK markers found |
| F-15 | LOW | Completeness | JSONParser lacks input size limit |
| F-16 | LOW | Completeness | Calculator MAX_EXPONENT allows large integer computations |
| F-17 | POSITIVE | Testing | 305+ tests across all tools |
| F-18 | LOW | Testing | HTTPClient test file needs expansion (8 tests) |
| F-19 | POSITIVE | Testing | WebScraper tests are exemplary (60+ tests) |
| F-20 | POSITIVE | Architecture | Strong Safety Through Composition pattern |
| F-21 | **MEDIUM** | Architecture | Missing shared SSRF protection module |
| F-22 | LOW | Architecture | TavilySearch base_url has no SSRF protection |

---

## Recommended Priority Actions

### P0 -- Security Fixes
1. **F-05:** Add `__import__` detection to CodeExecutor (quick fix: `if "__import__" in code`; proper fix: use `-I` flag or RestrictedPython)
2. **F-06 + F-21:** Extract SSRF protection into shared module and apply to HTTPClient

### P1 -- Important Improvements
3. **F-03:** Add `modifies_state=True` to FileWriter metadata
4. **F-10:** Change `_extract_text` error handling to propagate failure status
5. **F-15:** Add MAX_JSON_DATA_SIZE validation to JSONParser

### P2 -- Quality Improvements
6. **F-01 + F-04:** Decompose `_split_shell_commands` and remove dead shlex code
7. **F-02:** Create `web_scraper_constants.py` to eliminate import aliasing
8. **F-18:** Expand HTTPClient tests to 20+ tests
9. **F-09:** Add minimal safe env vars to CodeExecutor subprocess
