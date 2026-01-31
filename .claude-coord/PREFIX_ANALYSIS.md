# Task Prefix Analysis & Prioritization Guide

**Date:** 2026-01-30
**Total Tasks:** 295

---

## 📊 Task Prefix Categories

### **1. Milestone Tasks (59 tasks)**

| Prefix | Count | Description | Current Status |
|--------|-------|-------------|----------------|
| **m1** | 8 | Milestone 1 - Foundation | Base infrastructure |
| **m2** | 8 | Milestone 2 - Core Features | Agent runtime, LLM providers |
| **m2.5** | 5 | Milestone 2.5 - Engine Abstraction | Execution engine interface |
| **m3** | 11 | Milestone 3 - Multi-Agent | Collaboration strategies |
| **m3.1** | 6 | M3.1 - Type Safety & Cleanup | Type improvements |
| **m3.2** | 14 | M3.2 - Compiler Refactoring | LangGraph compiler work |
| **m3.3** | 6 | M3.3 - Performance | Async LLM, benchmarks |
| **m4** | 15 | Milestone 4 - Safety System | Policy engine, safety gates |

**Recommended Priority Order:**
1. **m1** (Priority: 5) - Foundation tasks (should be complete)
2. **m2** (Priority: 5) - Core features (should be complete)
3. **m2.5** (Priority: 4) - Engine abstraction
4. **m3** (Priority: 3) - Multi-agent core
5. **m3.1** (Priority: 3) - Type safety cleanup
6. **m3.2** (Priority: 2) - Compiler refactor (important)
7. **m3.3** (Priority: 2) - Performance improvements
8. **m4** (Priority: 1) - Safety critical (HIGHEST)

---

### **2. Code Tasks (49 tasks)**

| Prefix | Count | Description | Priority Level |
|--------|-------|-------------|----------------|
| **code-crit** | 8 | Critical security/bugs | P1 - CRITICAL |
| **code-high** | 2 | High priority fixes | P2 - HIGH |
| **code-med** | 19 | Medium code quality | P3 - NORMAL |
| **code-low** | 20 | Low priority cleanup | P4 - LOW |

**Breakdown:**

**code-crit (8 tasks - P1 CRITICAL):**
- SSRF DNS rebinding vulnerability
- Command injection sanitization
- Path traversal vulnerabilities
- Cache collision vulnerability
- Template injection (Jinja2)
- Dynamic tool loading security
- ReDoS pattern vulnerabilities
- Sensitive data logging

**code-high (2 tasks - P2 HIGH):**
- Execution timeouts (unbounded loops)
- HTTP client memory leak

**code-med (19 tasks - P3):**
- God class refactoring
- Long parameter lists
- Magic numbers extraction
- MD5 hash replacement
- Rate limiting for LLM
- Thread pool leak fixes
- Type hint improvements

**code-low (20 tasks - P4):**
- Type hints completion
- Naming consistency
- Unused imports
- Magic strings to enums
- Logging standardization
- Health check endpoints

**Recommended Priority Order:**
1. **code-crit** (Priority: 1) - SECURITY CRITICAL
2. **code-high** (Priority: 2) - Important fixes
3. **code-med** (Priority: 3) - Quality improvements
4. **code-low** (Priority: 4) - Nice to have

---

### **3. Documentation Tasks (85 tasks)**

| Prefix | Count | Description | Priority Level |
|--------|-------|-------------|----------------|
| **doc-crit** | 8 | Critical doc errors | P1 - CRITICAL |
| **doc-high** | 16 | High priority fixes | P2 - HIGH |
| **doc-med** | 20 | Medium importance | P3 - NORMAL |
| **doc-low** | 20 | Low priority cleanup | P4 - LOW |
| **doc-guide** | 7 | User guides | P3 - NORMAL |
| **doc-consolidate** | 4 | Doc consolidation | P3 - NORMAL |
| **doc-archive** | 3 | Archive old docs | P4 - LOW |
| **doc-reorg** | 3 | Reorganization | P3 - NORMAL |
| **doc-adr** | 2 | Architecture decisions | P3 - NORMAL |
| **doc-api** | 1 | API reference | P3 - NORMAL |
| **doc-update** | 1 | General updates | P3 - NORMAL |

**doc-crit Issues (8 tasks - P1):**
- AgentResponse output type mismatch
- ExecutionContext field names wrong
- Multiple ExecutionContext classes undocumented
- init_config_loader doesn't exist (remove from docs)
- AgentFactory method names incorrect
- ExecutionEngine.execute() mode parameter missing
- execute() return structure unclear
- LLM provider method name wrong

**Recommended Priority Order:**
1. **doc-crit** (Priority: 1) - Blocks understanding/usage
2. **doc-high** (Priority: 2) - Important corrections
3. **doc-guide** (Priority: 3) - User onboarding
4. **doc-api** (Priority: 3) - Reference material
5. **doc-med** (Priority: 4) - Improvements
6. **doc-consolidate** (Priority: 4) - Organization
7. **doc-low** (Priority: 5) - Polish
8. **doc-archive** (Priority: 6) - Cleanup

---

### **4. Test Tasks (71 tasks)**

| Prefix | Count | Description | Priority Level |
|--------|-------|-------------|----------------|
| **test-crit** | 15 | Critical test gaps | P1 - CRITICAL |
| **test-high** | 10 | High priority tests | P2 - HIGH |
| **test-med** | 4 | Medium importance | P3 - NORMAL |
| **test-low** | 2 | Low priority tests | P4 - LOW |
| **test-security** | 8 | Security-specific | P1-P2 |
| **test-tool** | 5 | Tool execution tests | P2-P3 |
| **test-perf** | 4 | Performance tests | P3 |
| **test-workflow** | 3 | Workflow tests | P3 |
| **test-llm** | 3 | LLM integration tests | P2-P3 |
| **test-integration** | 2 | Integration tests | P2 |
| **test-fix-failures** | 4 | Fix failing tests | P2 |
| **test-error** | 2 | Error handling tests | P2-P3 |
| **test-agent** | 2 | Agent-specific tests | P3 |
| **Others** | 7 | Misc test categories | P3-P4 |

**test-crit (15 tasks - P1 CRITICAL):**
- Agent error recovery
- Checkpoint rollback failures
- Database transaction violations
- M3+M4 integration E2E
- Parallel execution race conditions
- Security circuit breaker tests
- SQL injection pattern coverage
- Security concurrency tests
- OWASP LLM Top 10 (LLM02, LLM04, LLM08/09)
- Rollback idempotency
- Concurrent tool execution
- Tool timeout cleanup

**Recommended Priority Order:**
1. **test-crit** (Priority: 1) - Critical coverage gaps
2. **test-security** (Priority: 1) - Security validation
3. **test-high** (Priority: 2) - Important coverage
4. **test-fix-failures** (Priority: 2) - Fix broken tests
5. **test-integration** (Priority: 2) - E2E validation
6. **test-llm** (Priority: 3) - LLM testing
7. **test-tool** (Priority: 3) - Tool validation
8. **test-med** (Priority: 4) - Additional coverage
9. **test-perf** (Priority: 4) - Performance validation
10. **test-workflow** (Priority: 4) - Workflow testing
11. **test-low** (Priority: 5) - Nice to have

---

### **5. Code Quality Tasks (4 tasks)**

| Prefix | Count | Description | Priority Level |
|--------|-------|-------------|----------------|
| **cq-p0** | 3 | Critical quality | P3 (already P0 named) |
| **cq-p1** | 1 | High quality | P3 (already P1 named) |

**cq-p0 Tasks:**
- Fix SSRF Vulnerability in WebScraper
- Implement Secrets Management
- Fix N+1 Database Query Problem

**cq-p1 Tasks:**
- Refactor LangGraphCompiler (Extract Stage Executors)

**Recommended Priority:**
- **cq-p0** (Priority: 2) - Critical quality issues
- **cq-p1** (Priority: 3) - Important refactoring

---

## 🎯 Recommended Prefix Priority Configuration

### **Quick Setup Commands**

```bash
# CRITICAL - Must do first (Priority 1)
./.claude-coord/claude-coord.sh task-prefix-set code-crit 1
./.claude-coord/claude-coord.sh task-prefix-set doc-crit 1
./.claude-coord/claude-coord.sh task-prefix-set test-crit 1
./.claude-coord/claude-coord.sh task-prefix-set test-security 1
./.claude-coord/claude-coord.sh task-prefix-set m4 1

# HIGH PRIORITY (Priority 2)
./.claude-coord/claude-coord.sh task-prefix-set code-high 2
./.claude-coord/claude-coord.sh task-prefix-set doc-high 2
./.claude-coord/claude-coord.sh task-prefix-set test-high 2
./.claude-coord/claude-coord.sh task-prefix-set test-fix 2
./.claude-coord/claude-coord.sh task-prefix-set test-integration 2
./.claude-coord/claude-coord.sh task-prefix-set m3.2 2
./.claude-coord/claude-coord.sh task-prefix-set m3.3 2
./.claude-coord/claude-coord.sh task-prefix-set cq-p0 2

# NORMAL PRIORITY (Priority 3)
./.claude-coord/claude-coord.sh task-prefix-set code-med 3
./.claude-coord/claude-coord.sh task-prefix-set doc-med 3
./.claude-coord/claude-coord.sh task-prefix-set doc-guide 3
./.claude-coord/claude-coord.sh task-prefix-set doc-api 3
./.claude-coord/claude-coord.sh task-prefix-set test-med 3
./.claude-coord/claude-coord.sh task-prefix-set test-llm 3
./.claude-coord/claude-coord.sh task-prefix-set test-tool 3
./.claude-coord/claude-coord.sh task-prefix-set m3 3
./.claude-coord/claude-coord.sh task-prefix-set m3.1 3
./.claude-coord/claude-coord.sh task-prefix-set cq-p1 3

# LOW PRIORITY (Priority 4)
./.claude-coord/claude-coord.sh task-prefix-set code-low 4
./.claude-coord/claude-coord.sh task-prefix-set doc-low 4
./.claude-coord/claude-coord.sh task-prefix-set doc-consolidate 4
./.claude-coord/claude-coord.sh task-prefix-set test-low 4
./.claude-coord/claude-coord.sh task-prefix-set test-perf 4
./.claude-coord/claude-coord.sh task-prefix-set test-workflow 4
./.claude-coord/claude-coord.sh task-prefix-set m2.5 4

# BACKLOG (Priority 5)
./.claude-coord/claude-coord.sh task-prefix-set doc-archive 5
./.claude-coord/claude-coord.sh task-prefix-set m1 5
./.claude-coord/claude-coord.sh task-prefix-set m2 5
```

---

## 📋 Complete Prefix Priority Table

| Priority | Prefixes | Rationale |
|----------|----------|-----------|
| **1 - CRITICAL** | `code-crit`, `doc-crit`, `test-crit`, `test-security`, `m4` | Security issues, critical bugs, safety system |
| **2 - HIGH** | `code-high`, `doc-high`, `test-high`, `test-fix`, `test-integration`, `m3.2`, `m3.3`, `cq-p0` | Important fixes, performance, compiler work |
| **3 - NORMAL** | `code-med`, `doc-med`, `doc-guide`, `doc-api`, `test-med`, `test-llm`, `test-tool`, `m3`, `m3.1`, `cq-p1` | Regular development, documentation, testing |
| **4 - LOW** | `code-low`, `doc-low`, `doc-consolidate`, `test-low`, `test-perf`, `test-workflow`, `m2.5` | Code quality, polish, organization |
| **5 - BACKLOG** | `doc-archive`, `m1`, `m2` | Old milestones (should be done), archive work |

---

## 🚀 Execution Order Recommendation

### **Phase 1: Security & Critical Bugs** (Priority 1)
1. All `code-crit` tasks (8 tasks) - Fix security vulnerabilities
2. All `test-security` tasks (8 tasks) - Security test coverage
3. All `m4` tasks (15 tasks) - Safety system implementation
4. All `test-crit` critical security tests (relevant subset)

**Estimated:** 31 critical tasks

### **Phase 2: Documentation & Testing Foundation** (Priority 1-2)
1. All `doc-crit` tasks (8 tasks) - Fix critical doc errors
2. Remaining `test-crit` tasks (15 tasks) - Fill test gaps
3. All `test-fix` tasks (4 tasks) - Fix broken tests
4. All `doc-high` tasks (16 tasks) - Important doc fixes

**Estimated:** 43 tasks

### **Phase 3: Quality & Performance** (Priority 2-3)
1. All `code-high` tasks (2 tasks) - Important bug fixes
2. All `test-high` tasks (10 tasks) - High priority coverage
3. All `test-integration` tasks (2 tasks) - E2E validation
4. All `m3.2` tasks (14 tasks) - Compiler refactoring
5. All `m3.3` tasks (6 tasks) - Performance improvements
6. All `cq-p0` tasks (3 tasks) - Critical quality issues

**Estimated:** 37 tasks

### **Phase 4: Regular Development** (Priority 3)
1. All `m3` core tasks (11 tasks)
2. All `m3.1` tasks (6 tasks)
3. All `doc-guide` tasks (7 tasks) - User guides
4. All `code-med` tasks (19 tasks) - Code quality
5. All `test-med` tasks (4 tasks)

**Estimated:** 47 tasks

### **Phase 5: Polish & Cleanup** (Priority 4-5)
1. All `code-low` tasks (20 tasks)
2. All `doc-low` tasks (20 tasks)
3. All `test-low` tasks (2 tasks)
4. All `doc-consolidate` tasks (4 tasks)
5. All `doc-archive` tasks (3 tasks)
6. Remaining tasks

**Estimated:** Remaining tasks

---

## 🔍 Current Prefix Priorities

**Check current settings:**
```bash
./.claude-coord/claude-coord.sh task-prefix-list
```

**Clear all prefix priorities (if needed):**
```bash
# Get list of all prefixes
jq -r '.prefix_priorities | keys[]' .claude-coord/state.json | while read prefix; do
    ./.claude-coord/claude-coord.sh task-prefix-clear "$prefix"
done
```

---

## 📊 Task Distribution by Prefix (Top 20)

| Rank | Prefix | Count | Category |
|------|--------|-------|----------|
| 1 | doc-med | 20 | Documentation |
| 2 | doc-low | 20 | Documentation |
| 3 | code-low | 20 | Code Quality |
| 4 | code-med | 19 | Code Quality |
| 5 | doc-high | 16 | Documentation |
| 6 | test-crit | 15 | Testing |
| 7 | test-high | 10 | Testing |
| 8 | test-security | 8 | Testing |
| 9 | doc-crit | 8 | Documentation |
| 10 | code-crit | 8 | Code |
| 11 | doc-guide | 7 | Documentation |
| 12 | test-tool | 5 | Testing |
| 13 | test-perf | 4 | Testing |
| 14 | test-med | 4 | Testing |
| 15 | test-fix | 4 | Testing |
| 16 | doc-consolidate | 4 | Documentation |
| 17 | test-workflow | 3 | Testing |
| 18 | test-llm | 3 | Testing |
| 19 | doc-reorg | 3 | Documentation |
| 20 | doc-archive | 3 | Documentation |

---

## 💡 Usage Tips

1. **Set prefix priorities** to control which types of tasks agents pick up first
2. **task-next** command respects prefix priorities (lower number = higher priority)
3. **Within same prefix**, task priority (P1-P4) is used as tiebreaker
4. **Clear prefix priorities** if you want to use only task-level priorities

---

**Generated:** 2026-01-30
**Total Unique Prefixes:** 50+
**Total Tasks:** 295
