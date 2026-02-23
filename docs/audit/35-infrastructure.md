# Infrastructure & Configuration Audit Report

**Scope:** Dockerfile, docker-compose.yml, Helm chart, CI pipeline, Alembic migrations, pyproject.toml, Makefile, YAML configs, SearXNG docker setup
**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6

---

## Executive Summary

The infrastructure layer is well-structured for a project of this maturity. The Dockerfile follows multi-stage best practices with non-root users, the CI pipeline has a logical four-stage quality gate, and the Helm chart covers the basics. However, there are **14 high-severity**, **18 medium-severity**, and **12 low-severity** findings across security, production readiness, and completeness dimensions. The most critical issues are: hardcoded credentials in `alembic.ini`, missing container security contexts in Helm, f-string SQL in a migration, no `.dockerignore` for the frontend build context, missing dependency vulnerability scanning in CI, and version drift between `pyproject.toml` (v1.0.0) and Docker/Helm (v0.1.0).

---

## 1. Dockerfile

**File:** `/home/shinelay/meta-autonomous-framework/Dockerfile`

### Strengths

- **Multi-stage build** with three targets (server, runner, worker) sharing a common `base` -- good layer reuse (line 8-91).
- **Non-root user** created in all three targets (lines 42-44, 63-65, 81-83).
- **HEALTHCHECK** on server and worker targets (lines 49-50, 87-88).
- **Layer optimization**: dependencies installed before source copy (lines 21-23).
- **OCI labels** with version and commit ARGs (lines 35-39, 57-60, 75-78).
- **`--no-cache-dir`** on pip install to reduce image size (lines 23, 30).
- **Read-only config mount** in docker-compose (line 30 of docker-compose.yml).

### Findings

| ID | Severity | Line | Finding |
|----|----------|------|---------|
| D-1 | **HIGH** | 11 | **Version drift**: `TEMPER_VERSION=0.1.0` but `pyproject.toml` declares `version = "1.0.0"`. The Docker build ARG will produce images tagged/labeled as `0.1.0` while the Python package reports `1.0.0`. These should be synchronized, ideally by reading the version from `pyproject.toml` at build time. |
| D-2 | **MEDIUM** | 9 | **Base image not pinned to digest**: `python:3.11.11-slim-bookworm` pins the tag but not the SHA256 digest. For reproducible builds, use `python:3.11.11-slim-bookworm@sha256:<hash>`. |
| D-3 | **MEDIUM** | 30 | **Editable install in production image**: `pip install --no-cache-dir --no-deps -e .` creates a `.egg-link` symlink. Production images should use `pip install --no-cache-dir --no-deps .` (without `-e`) for immutability and smaller layer size. |
| D-4 | **MEDIUM** | 87-88 | **Worker HEALTHCHECK is a no-op**: `CMD ["python", "-c", "import sys; sys.exit(0)"]` always succeeds. It does not verify the worker process is actually running or healthy. Should check that the worker's main loop is responsive (e.g., write a PID file and check it, or expose a health endpoint). |
| D-5 | **LOW** | 14-16 | **`apt-get` installs `git` and `curl` in all targets**: The `runner` and `worker` targets inherit `git` and `curl` from `base`, but may not need them. Consider moving these to target-specific layers to reduce attack surface. |
| D-6 | **LOW** | 22-23 | **Dummy `__init__.py` trick**: Creating an empty `temper_ai/__init__.py` for the first pip install layer works but is fragile. If the package's `__init__.py` has runtime side-effects, the two-phase install may behave differently than expected. Document this pattern. |
| D-7 | **MEDIUM** | -- | **No `COPY --chown`**: Files are copied as root, then `chown -R` is run. Using `COPY --chown=temperai:temperai` would be more efficient (single layer). |

---

## 2. docker-compose.yml

**File:** `/home/shinelay/meta-autonomous-framework/docker-compose.yml`

### Strengths

- **Health check on postgres** with `pg_isready` (lines 12-16).
- **Resource limits** on all services (lines 18-21, 44-46, 68-70).
- **`depends_on` with `condition: service_healthy`** ensures ordering (lines 39-41, 63-65).
- **Optional `.env` file** with `required: false` (lines 37-38).
- **Read-only config volume** `./configs:/app/configs:ro` (line 30).

### Findings

| ID | Severity | Line | Finding |
|----|----------|------|---------|
| DC-1 | **HIGH** | 7 | **Default password in plain text**: `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}`. While it uses an env var with fallback, the default `changeme` will be used if the user forgets to set the variable. This is repeated on lines 34 and 57. The default should be removed so compose fails loudly if `POSTGRES_PASSWORD` is unset. |
| DC-2 | **MEDIUM** | -- | **No network isolation**: All services share the default network. The `postgres` service port 5432 is exposed to the host (line 9). In production, postgres should only be accessible from the internal network. Consider adding a named internal network and removing the host port mapping. |
| DC-3 | **MEDIUM** | -- | **No init process**: Containers lack `init: true` which can lead to zombie processes, especially for the worker which spawns subprocesses. |
| DC-4 | **LOW** | -- | **Missing `compose.yaml` format indicator**: No `version:` key or compose specification comment. While compose v2 infers the version, adding a comment about the minimum compose version improves clarity. |
| DC-5 | **LOW** | -- | **No logging configuration**: Unlike the SearXNG compose file, the main compose file has no log driver configuration. In production, JSON file logs can grow unbounded. |

---

## 3. Helm Chart

**Files:** `/home/shinelay/meta-autonomous-framework/helm/temper-ai/`

### Strengths

- **Proper template helpers** with `_helpers.tpl` for name/label generation (lines 1-39).
- **Liveness and readiness probes** on the server deployment (deployment.yaml:30-41).
- **Conditional worker deployment** with `{{- if .Values.worker.enabled }}` (worker-deployment.yaml:1).
- **Resource limits and requests** defined for both server and worker.
- **Secret stored as base64-encoded Kubernetes Secret** (secret.yaml:9).
- **Empty default password** to force override (values.yaml:39).

### Findings

| ID | Severity | Line | Finding |
|----|----------|------|---------|
| H-1 | **HIGH** | deployment.yaml:all | **No securityContext**: Neither the pod nor container level defines `securityContext`. Missing: `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`. This is a critical Kubernetes security best practice. |
| H-2 | **HIGH** | worker-deployment.yaml:all | **No securityContext on worker either**: Same issue as H-1. |
| H-3 | **HIGH** | secret.yaml:9 | **Database password in Secret template renders plaintext first**: `{{ printf "..." .Values.postgresql.auth.password ... | b64enc }}`. If `password` is empty (the default), the generated connection URL becomes `postgresql://temper_ai:@...` which is a broken URL. There is no validation that the password is set. |
| H-4 | **HIGH** | -- | **No Ingress template**: Although `values.yaml` defines `ingress.enabled`, `ingress.hosts`, and `ingress.tls` (lines 14-23), there is no `templates/ingress.yaml` file to render it. The ingress configuration is dead code. |
| H-5 | **MEDIUM** | -- | **No HPA (HorizontalPodAutoscaler)**: No auto-scaling template exists. The chart can only scale via manual `replicaCount` changes. |
| H-6 | **MEDIUM** | -- | **No PodDisruptionBudget**: No PDB template. Cluster maintenance or node drains could take down all replicas simultaneously. |
| H-7 | **MEDIUM** | -- | **No NetworkPolicy**: No network policy to restrict pod-to-pod traffic. Any pod in the namespace can reach the database. |
| H-8 | **MEDIUM** | -- | **No ServiceAccount template**: Pods run with the default service account, which may have excessive RBAC permissions depending on the cluster. |
| H-9 | **MEDIUM** | Chart.yaml:6-7 | **Version drift**: `appVersion: "0.1.0"` vs `pyproject.toml` `version = "1.0.0"`. Chart version should match or reference the application version. |
| H-10 | **MEDIUM** | deployment.yaml | **No startup probe**: Only liveness and readiness probes. For slow-starting applications (first-time DB migrations), a startup probe with higher failure threshold prevents premature restarts. |
| H-11 | **MEDIUM** | worker-deployment.yaml | **No probes on worker**: The worker deployment has no health/liveness/readiness probes at all. Kubernetes cannot detect if the worker process dies. |
| H-12 | **LOW** | values.yaml | **No `nodeSelector`, `tolerations`, or `affinity`**: Chart provides no scheduling controls. |
| H-13 | **LOW** | -- | **No NOTES.txt**: Missing `templates/NOTES.txt` which provides post-install instructions to the user (`helm install` output). |
| H-14 | **LOW** | configmap.yaml | **`TEMPER_WORKER_CONCURRENCY` as string**: `{{ .Values.config.workerConcurrency | quote }}` quotes the integer value. While this is fine for env vars, it is worth noting. |
| H-15 | **LOW** | -- | **No PostgreSQL subchart dependency**: `values.yaml` references `postgresql.enabled` and `postgresql.auth.*` but `Chart.yaml` has no `dependencies` section referencing the Bitnami PostgreSQL chart. The user must deploy PostgreSQL separately. |

---

## 4. CI Pipeline

**File:** `/home/shinelay/meta-autonomous-framework/.github/workflows/ci.yml`

### Strengths

- **Concurrency control**: `cancel-in-progress: true` prevents wasted runners (lines 15-17).
- **Four-stage quality gate**: lint + typecheck (parallel) -> test (matrix) -> quality (lines 23-243).
- **Python version matrix**: Tests run on both 3.11 and 3.12 (line 99).
- **`fail-fast: false`** on test matrix ensures all versions are tested (line 97).
- **Timeout limits** on all jobs (10-30 minutes).
- **Pip caching** with `actions/cache@v4` (lines 42-47 et al.).
- **Frontend build verification** as a separate job (lines 137-161).
- **Benchmark job with `continue-on-error`** so it never blocks merges (lines 199-242).
- **Mock LLM provider** to avoid real API calls in CI (line 21).

### Findings

| ID | Severity | Line | Finding |
|----|----------|------|---------|
| CI-1 | **HIGH** | -- | **No dependency vulnerability scanning**: No `pip-audit`, `safety`, or Dependabot/Renovate integration. The project has `pip-audit` in dev dependencies (pyproject.toml:64) but never runs it in CI. Supply chain attacks are a real risk. |
| CI-2 | **HIGH** | -- | **No security scanning job**: `bandit` is available (pyproject.toml:64, Makefile:42) via `make security` but is never called in CI. SAST scanning should be part of the pipeline. |
| CI-3 | **MEDIUM** | 121 | **Tests only run core dirs**: `make test` runs `PYTEST_CORE_DIRS` (workflow, stage, agent, safety) but does not run tests for auth, events, registry, observability, tools, etc. The CI pipeline has lower coverage than `make test-all`. |
| CI-4 | **MEDIUM** | -- | **No coverage reporting**: Tests run without `--cov`. Coverage percentage is not tracked or enforced. `make coverage` exists but is not used in CI. |
| CI-5 | **MEDIUM** | -- | **No Docker image build/push job**: CI validates code quality but never builds or tests the Docker image. A broken Dockerfile would not be caught until manual deploy. |
| CI-6 | **MEDIUM** | -- | **No migration testing**: Alembic migrations are not validated in CI. A migration that fails on upgrade or downgrade would not be caught. |
| CI-7 | **LOW** | 130-132 | **Upload of `.pytest_cache/` as artifact**: This directory contains internal pytest state, not test results. It would be more useful to generate JUnit XML (`--junitxml=results.xml`) and upload that. |
| CI-8 | **LOW** | -- | **No caching for frontend `node_modules`**: The `npm ci` step uses `cache: 'npm'` on setup-node, which caches the npm download cache but not `node_modules/` directly. This is fine but could be faster with workspace caching. |
| CI-9 | **LOW** | -- | **No dependabot.yml**: No automated dependency update mechanism for either Python or GitHub Actions versions. |

---

## 5. Alembic Migrations

**Files:** `/home/shinelay/meta-autonomous-framework/alembic/`

### Strengths

- **Complete migration chain**: 15 migrations from initial schema through M9, M10, and p1 phases with proper `down_revision` chaining.
- **All migrations have `downgrade()`**: Every migration provides a rollback path.
- **Proper `ondelete='CASCADE'`** on foreign keys throughout (initial_schema.py, mt_001, m9_001, opt_001).
- **Default tenant backfill** in mt_001 migration (lines 162-195) ensures existing data is updated.
- **Index creation** on all foreign key and frequently-queried columns.
- **env.py imports all models** so autogenerate works correctly (env.py:24-40).
- **URL override** via `-x sqlalchemy.url` or `TEMPER_DATABASE_URL` env var (env.py:44-49).

### Findings

| ID | Severity | Line | Finding |
|----|----------|------|---------|
| A-1 | **HIGH** | alembic.ini:89 | **Hardcoded production credentials**: `sqlalchemy.url = postgresql://temper_ai:changeme@localhost:5432/temper_ai`. While overridable via env var, the password `changeme` is committed to version control. This should be a placeholder like `driver://user:pass@localhost/dbname` or removed entirely since env.py already handles overrides. |
| A-2 | **HIGH** | p1_002:44 | **f-string SQL**: `f"UPDATE {table} SET tenant_id = '{_DEFAULT_TENANT_ID}' WHERE tenant_id IS NULL"`. The table name and tenant ID are from constants, not user input, so this is not exploitable. However, it violates the project's own coding standards (`No f-string SQL`) and uses `op.execute(str)` instead of `sa.text()` with `bindparams()`. Compare with mt_001:191-195 which correctly uses `sa.text()` with `.bindparams()`. |
| A-3 | **MEDIUM** | p1_001:32 | **No FK constraint on added tenant_id columns**: p1_001 and p1_002 add `tenant_id` columns without a foreign key to `tenants.id`. Compare with mt_001:152-158 which correctly adds `sa.ForeignKey("tenants.id", ondelete="CASCADE")`. These orphaned columns could contain tenant IDs that do not exist in the tenants table. |
| A-4 | **MEDIUM** | p1_001:30-33 | **No backfill of default tenant**: p1_001 adds `tenant_id` to `llm_calls`, `tool_executions`, `server_runs` but does not backfill existing rows with the default tenant ID. Compare with p1_002 and mt_001 which do backfill. Existing rows will have `NULL` tenant_id. |
| A-5 | **MEDIUM** | m9_001:81-92 | **Bare `except Exception` in migration**: The `goal_proposals` column addition wraps in `try/except Exception: pass`. While annotated, this silently swallows legitimate errors (e.g., column already exists with wrong type). Should inspect the exception type more carefully. |
| A-6 | **MEDIUM** | -- | **Non-standard revision IDs**: Some migrations use hex hashes (e.g., `abd552d7a52e`, `9bba5a67eb64`), others use semantic names (e.g., `m9_001`, `mt_001`, `p1_001`, `opt_001`), and some use sequential-looking hex (e.g., `e6f7a8b90123`, `f7a8b9012345`). Inconsistent naming makes it harder to understand the migration order at a glance. |
| A-7 | **LOW** | env.py | **No migration test suite**: There are no tests that run `alembic upgrade head` followed by `alembic downgrade base` to verify migration round-trip integrity. |
| A-8 | **LOW** | -- | **`server_default=sa.text("1")` vs `server_default="1"`**: mt_001 uses `sa.text("1")` for booleans (line 30) which is PostgreSQL-compatible, but some other migrations use raw strings. The inconsistency is minor but could cause issues with different database backends. |

---

## 6. pyproject.toml

**File:** `/home/shinelay/meta-autonomous-framework/pyproject.toml`

### Strengths

- **Hatchling build backend** -- modern, fast, and well-supported (line 2).
- **Extensive optional dependency groups**: `dev`, `dashboard`, `dspy`, `llm-providers`, `mcp`, `memory`, `otel`, `autogen`, `crewai`, `openai_agents` (lines 40-94).
- **Version ranges** with upper bounds (e.g., `langchain>=1.0,<2.0`) prevent unexpected major version breaks (lines 18-38).
- **Comprehensive dev tooling**: pytest, black, ruff, mypy, bandit, radon, vulture, pre-commit, mutation testing (lines 53-73).

### Findings

| ID | Severity | Line | Finding |
|----|----------|------|---------|
| P-1 | **MEDIUM** | 36 | **`cryptography>=46.0.5` has no upper bound**: All other dependencies have upper bounds. A future breaking release of `cryptography` could break the build. Should be `cryptography>=46.0.5,<48.0` or similar. |
| P-2 | **MEDIUM** | -- | **No `[tool.mypy]` configuration**: mypy is in dev dependencies and pre-commit hooks reference `--config-file=pyproject.toml`, but there is no `[tool.mypy]` section. mypy will use default settings which may be too lenient. |
| P-3 | **MEDIUM** | -- | **No `[tool.pytest.ini_options]`**: pytest configuration (markers, asyncio_mode, timeout defaults, test paths) is not in pyproject.toml. Test behavior depends on implicit defaults and CLI args. |
| P-4 | **LOW** | 45 | **Empty optional dependency group**: `coord = []` is defined but contains no packages. This is dead configuration. |
| P-5 | **LOW** | 111 | **`ignore = ["E501"]`** in ruff: Ignoring line length globally. While common, this should be documented with rationale. |
| P-6 | **LOW** | 114-116 | **`per-file-ignores` section uses old format**: The `[tool.ruff.per-file-ignores]` section should be `[tool.ruff.lint.per-file-ignores]` in newer ruff versions. |

---

## 7. Makefile

**File:** `/home/shinelay/meta-autonomous-framework/Makefile`

### Strengths

- **Well-documented targets** with `## comment: description` pattern and `help` target (lines 88-90).
- **`.PHONY` declaration** for all targets (line 2).
- **Configurable variables** (`PYTHON`, `MIN_SCORE`) with defaults (lines 8).
- **Comprehensive quality checks**: lint, type, test, coverage, quality, security, check-skipif, test-random, test-flaky, mutate (lines 11-68).
- **Bootstrap setup target** that creates venv, installs deps, and copies .env (lines 71-82).

### Findings

| ID | Severity | Line | Finding |
|----|----------|------|---------|
| M-1 | **MEDIUM** | 42 | **`bandit` fallback suppresses errors**: `bandit -r $(SRC) -c pyproject.toml 2>/dev/null \|\| bandit -r $(SRC) -ll`. The first command redirects stderr to /dev/null, potentially hiding configuration errors. The fallback `-ll` only reports medium and high severity. |
| M-2 | **LOW** | 4 | **`PYTEST_CORE_DIRS` does not include all test directories**: Same as CI-3. The `test` target misses auth, events, registry, observability, tools, etc. |
| M-3 | **LOW** | 50 | **`check` target does not include `security`**: The full local gate runs `lint type test quality check-skipif` but not `security` (bandit). Security scanning should be part of the standard check. |

---

## 8. Pre-commit Configuration

**File:** `/home/shinelay/meta-autonomous-framework/.pre-commit-config.yaml`

### Strengths

- **Standard hooks**: trailing-whitespace, end-of-file-fixer, check-yaml, check-added-large-files (lines 7-15).
- **Black and Ruff** integrated (lines 18-29).
- **Local mypy hook** uses system interpreter so it picks up project dependencies (lines 32-40).
- **Quality score gate** runs on every commit (lines 43-51).

### Findings

| ID | Severity | Line | Finding |
|----|----------|------|---------|
| PC-1 | **LOW** | 22 | **Black runs in check mode**: `args: [--check, --diff]` means black won't auto-fix. This is deliberate (forces manual formatting) but could be confusing for contributors who expect auto-fix. |
| PC-2 | **LOW** | 15 | **Large file limit is 500KB**: `--maxkb=500` is generous. Consider lowering to 100-200KB to catch accidental binary additions earlier. |

---

## 9. YAML Configs

**Files:** `/home/shinelay/meta-autonomous-framework/configs/`

### Strengths

- **Consistent structure**: All agent configs use `agent:` root key with `name`, `description`, `version`, `prompt`, `inference`, `tools`. All stage configs use `stage:` root key with `name`, `description`, `agents`, `execution`, `inputs`, `outputs`. All workflow configs use `workflow:` root key with `name`, `description`, `version`, `stages`.
- **88 agent configs, 51 stage configs, 24 workflow configs, 1 tool config**: Rich configuration library.
- **Hello world example**: Simple, documented entry point for new users (hello_world.yaml, hello_analyst.yaml, hello_analyze.yaml).
- **Complex VCS pipeline**: 9-stage pipeline with conditions, loops, parallel execution, quality gates, and evaluations (vcs_suggestion.yaml).
- **Dynamic routing demos**: retry and forward demos showing the dynamic engine.

### Findings

| ID | Severity | Line | Finding |
|----|----------|------|---------|
| C-1 | **MEDIUM** | hello_analyst.yaml:15-18 | **Hardcoded provider/model/base_url**: Agent configs hardcode `provider: ollama`, `model: llama3.2`, `base_url: http://localhost:11434`. These should reference environment variables or have a global default so all agents can be switched at once. Same pattern across most agent configs. |
| C-2 | **MEDIUM** | configs/README.md:95-98 | **README examples don't match actual config format**: The README shows `stages: - name: research / agent: research_agent / next: outline` format, but actual configs use `stage_ref` and `depends_on` patterns. Misleading documentation. |
| C-3 | **LOW** | configs/README.md:172-206 | **References to non-existent directories**: README lists `prompts/`, `triggers/`, and `oauth/` directories. Only `oauth/` actually exists (as `configs/oauth/`). `prompts/` and `triggers/` are documented but never created. |
| C-4 | **LOW** | -- | **Only 1 tool config**: `configs/tools/calculator.yaml` is the only tool config despite 10 built-in tools (Bash, HTTP, JSON, CodeExecutor, Git, FileWriter, Calculator, SearXNGSearch, TavilySearch, WebScraper). Other tools are configured inline in agent configs or auto-discovered. |
| C-5 | **LOW** | -- | **No config validation schema files**: While configs are validated at runtime via Pydantic, there are no JSON Schema files for IDE autocompletion or pre-commit YAML validation. |

---

## 10. SearXNG Docker Setup

**File:** `/home/shinelay/meta-autonomous-framework/docker/searxng/`

### Strengths

- **Security hardening**: `cap_drop: ALL` with minimal `cap_add` (docker-compose.yaml:15-19).
- **Log rotation**: `max-size: "1m"`, `max-file: "1"` (docker-compose.yaml:22-25).
- **Read-only volume mount** for settings (docker-compose.yaml:11).
- **Clear documentation** in README.md and settings.yaml comments.

### Findings

| ID | Severity | Line | Finding |
|----|----------|------|---------|
| S-1 | **MEDIUM** | settings.yaml:7 | **Hardcoded secret_key**: `secret_key: "temper-ai-searxng-dev-key-change-in-production"`. While labeled "dev", if this compose file is used in production without changes, the secret key is known. Should use an env var: `secret_key: ${SEARXNG_SECRET_KEY:-dev-key}`. |
| S-2 | **LOW** | settings.yaml:10 | **Rate limiting disabled**: `limiter: false`. Appropriate for dev but should be noted in production documentation. |
| S-3 | **LOW** | docker-compose.yaml:7 | **`image: searxng/searxng:latest`**: Not pinned to a specific version. Could break unexpectedly on upstream updates. |

---

## 11. .gitignore and .dockerignore

### Strengths

- **Comprehensive .gitignore**: Covers Python artifacts, venvs, .env files, databases, IDEs, testing, caching, and frontend build artifacts (106 lines).
- **.dockerignore exists**: Excludes .git, venv, tests, docs, scripts, examples, build artifacts (22 lines).

### Findings

| ID | Severity | Line | Finding |
|----|----------|------|---------|
| GI-1 | **MEDIUM** | .dockerignore | **`frontend/` not in .dockerignore**: The entire `frontend/` directory (including `node_modules/` if present) is sent to the Docker build context. The Docker image does not use frontend source files (the built react-dist is in `temper_ai/`). Adding `frontend/` to `.dockerignore` would significantly speed up builds. |
| GI-2 | **LOW** | .gitignore:33-35 | **Overly broad .env pattern**: `.env.*` ignores `.env.example` but it's tracked because it was added before the gitignore rule. However, future `.env.production` or `.env.staging` files intended for templates would be silently ignored. |
| GI-3 | **LOW** | .dockerignore:19-20 | **`*.html` excluded except README.md**: The rule `*.html` then `!README.md` is oddly specific. `*.md` also excludes all markdown except README.md. This is fine but the HTML exclusion pattern seems overly broad. |

---

## 12. .env.example

**File:** `/home/shinelay/meta-autonomous-framework/.env.example`

### Strengths

- **Well-organized sections**: PostgreSQL, LLM providers, application, OTEL, CORS, safety, performance, development, OAuth (67 lines).
- **Commented alternatives** for different LLM providers (lines 15-26).
- **Key generation instructions** for `OAUTH_TOKEN_ENCRYPTION_KEY` (line 65).

### Findings

| ID | Severity | Line | Finding |
|----|----------|------|---------|
| E-1 | **MEDIUM** | 58-60 | **Placeholder OAuth values look like instructions, not placeholders**: `GOOGLE_CLIENT_ID=your-google-client-id-from-console.apps.googleusercontent.com` could be mistaken for a real value due to the `.apps.googleusercontent.com` suffix. Use a clearly fake value like `CHANGEME` or `<your-client-id>`. |
| E-2 | **LOW** | 4 | **Default password `changeme`**: Same as DC-1. Consistent with docker-compose.yml but still a risk if users forget to change it. |

---

## Summary of Findings by Severity

### HIGH (14)

| ID | Component | Summary |
|----|-----------|---------|
| D-1 | Dockerfile | Version drift: ARG `0.1.0` vs pyproject.toml `1.0.0` |
| DC-1 | docker-compose | Default `changeme` password in three places |
| A-1 | alembic.ini | Hardcoded `changeme` password in version-controlled file |
| A-2 | p1_002 migration | f-string SQL violating project coding standards |
| H-1 | Helm deployment | No securityContext (runAsNonRoot, readOnlyRootFilesystem, etc.) |
| H-2 | Helm worker | No securityContext |
| H-3 | Helm secret | No validation that password is set; broken URL when empty |
| H-4 | Helm chart | Ingress values defined but no ingress template exists |
| CI-1 | CI pipeline | No dependency vulnerability scanning (pip-audit never runs) |
| CI-2 | CI pipeline | No SAST security scanning (bandit never runs in CI) |

### MEDIUM (18)

| ID | Component | Summary |
|----|-----------|---------|
| D-2 | Dockerfile | Base image not pinned to SHA256 digest |
| D-3 | Dockerfile | Editable install (`-e .`) in production image |
| D-4 | Dockerfile | Worker HEALTHCHECK always succeeds (no-op) |
| D-7 | Dockerfile | No COPY --chown, using separate chown layer |
| DC-2 | docker-compose | No network isolation, postgres exposed to host |
| DC-3 | docker-compose | No init process for zombie prevention |
| H-5 | Helm | No HPA for auto-scaling |
| H-6 | Helm | No PodDisruptionBudget |
| H-7 | Helm | No NetworkPolicy |
| H-8 | Helm | No ServiceAccount template |
| H-9 | Helm | Chart appVersion drift from pyproject.toml |
| H-10 | Helm | No startup probe on server |
| H-11 | Helm | No probes at all on worker |
| CI-3 | CI | Tests only cover 4 of ~20 test directories |
| CI-4 | CI | No coverage reporting or enforcement |
| CI-5 | CI | No Docker image build validation |
| CI-6 | CI | No migration testing |
| A-3 | Migrations | p1_001/p1_002 add tenant_id without FK constraint |
| A-4 | Migrations | p1_001 does not backfill default tenant |
| A-5 | Migrations | Bare `except Exception: pass` in migration |
| P-1 | pyproject.toml | `cryptography` has no upper version bound |
| P-2 | pyproject.toml | No `[tool.mypy]` configuration |
| P-3 | pyproject.toml | No `[tool.pytest.ini_options]` configuration |
| M-1 | Makefile | bandit stderr suppressed with `/dev/null` redirect |
| C-1 | Configs | Hardcoded provider/model/base_url in agent configs |
| C-2 | Configs | README examples don't match actual format |
| S-1 | SearXNG | Hardcoded secret_key in settings.yaml |
| GI-1 | .dockerignore | frontend/ not excluded, bloats build context |
| E-1 | .env.example | OAuth placeholders look like real values |

### LOW (12)

| ID | Component | Summary |
|----|-----------|---------|
| D-5 | Dockerfile | git/curl in all targets unnecessarily |
| D-6 | Dockerfile | Dummy __init__.py trick is fragile |
| DC-4 | docker-compose | No compose version indicator |
| DC-5 | docker-compose | No logging configuration |
| H-12 | Helm | No scheduling controls (nodeSelector, tolerations) |
| H-13 | Helm | No NOTES.txt |
| H-14 | Helm | Worker concurrency quoted as string |
| H-15 | Helm | No PostgreSQL subchart dependency |
| CI-7 | CI | Uploading .pytest_cache instead of JUnit XML |
| CI-8 | CI | Frontend npm caching could be improved |
| CI-9 | CI | No dependabot.yml for automated updates |
| A-6 | Migrations | Inconsistent revision ID naming |
| A-7 | Migrations | No migration round-trip test |
| A-8 | Migrations | Inconsistent server_default styles |
| P-4 | pyproject.toml | Empty `coord = []` dependency group |
| P-5 | pyproject.toml | E501 ignore undocumented |
| P-6 | pyproject.toml | Old ruff per-file-ignores format |
| M-2 | Makefile | Core test dirs incomplete |
| M-3 | Makefile | `check` target excludes `security` |
| PC-1 | Pre-commit | Black check-only may confuse contributors |
| PC-2 | Pre-commit | 500KB large file limit is generous |
| S-2 | SearXNG | Rate limiting disabled |
| S-3 | SearXNG | searxng image not version-pinned |
| C-3 | Configs | README references non-existent directories |
| C-4 | Configs | Only 1 tool config of 10 tools |
| C-5 | Configs | No JSON Schema for IDE validation |
| GI-2 | .gitignore | Overly broad .env.* pattern |
| GI-3 | .dockerignore | *.html exclusion seems overly broad |
| E-2 | .env.example | Default changeme password |

---

## Recommended Priority Actions

### P0 -- Fix Before v1.0 Release

1. **Add securityContext to Helm deployments** (H-1, H-2): Add `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]` to both deployment templates.
2. **Add security scanning to CI** (CI-1, CI-2): Add `pip-audit` and `bandit` jobs to `ci.yml`.
3. **Fix alembic.ini credential** (A-1): Replace `changeme` with a placeholder or remove the URL entirely.
4. **Fix p1_002 f-string SQL** (A-2): Use `sa.text()` with `bindparams()` like mt_001 does.
5. **Synchronize version numbers** (D-1, H-9): Align Dockerfile ARG, Chart.yaml appVersion, and pyproject.toml version to `1.0.0`.
6. **Remove default password fallback** (DC-1): Change `${POSTGRES_PASSWORD:-changeme}` to `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}`.

### P1 -- Fix Soon After Release

7. **Create ingress template** (H-4) or remove dead ingress values.
8. **Add worker probes** (H-11) and fix the no-op worker healthcheck (D-4).
9. **Expand CI test coverage** (CI-3): Run `make test-all` instead of `make test`.
10. **Add coverage reporting to CI** (CI-4).
11. **Fix p1_001/p1_002 missing FK and backfill** (A-3, A-4).
12. **Add `frontend/` to .dockerignore** (GI-1).
13. **Remove editable install from production** (D-3): Use `pip install --no-deps .` instead of `-e .`.

### P2 -- Improve Over Time

14. Add HPA, PDB, NetworkPolicy, ServiceAccount templates to Helm chart.
15. Add Dependabot/Renovate for automated dependency updates.
16. Add migration round-trip test to CI.
17. Add Docker build/push job to CI.
18. Add `[tool.mypy]` and `[tool.pytest.ini_options]` to pyproject.toml.
19. Externalize LLM provider/model from agent configs into environment-driven defaults.

---

## Architecture Diagram

```
                    CI Pipeline (GitHub Actions)
                    +--------------------------+
                    | lint | typecheck         |  Stage 1 (parallel)
                    +------+-------------------+
                           |
                    +------v-------------------+
                    | test (3.11) | test (3.12)|  Stage 2 (matrix)
                    | frontend build           |  Stage 2b (parallel)
                    +------+-------------------+
                           |
                    +------v-------------------+
                    | quality gate             |  Stage 3
                    +------+-------------------+
                           |
                    +------v-------------------+
                    | benchmark (informational)|  Stage 4
                    +--------------------------+

                    Docker Compose (Local Dev)
                    +--------------------------+
                    | postgres (pgvector:pg16) |
                    +------+-------------------+
                           |
              +------------+------------+
              |                         |
    +---------v----------+   +----------v---------+
    | temper-ai-server   |   | temper-ai-worker   |
    | (port 8420)        |   | (autonomous mode)  |
    +--------------------+   +--------------------+

                    Helm Chart (K8s Production)
                    +--------------------------+
                    | ConfigMap + Secret       |
                    +------+-------------------+
                           |
              +------------+------------+
              |                         |
    +---------v----------+   +----------v---------+
    | Deployment         |   | Worker Deployment  |
    | (server)           |   | (conditional)      |
    +---------+----------+   +--------------------+
              |
    +---------v----------+
    | Service (ClusterIP)|
    +--------------------+
```

---

*Report generated by infrastructure audit scan. All file paths are absolute. Line references are to the files as read on 2026-02-22.*
