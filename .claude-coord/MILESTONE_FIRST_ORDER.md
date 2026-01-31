# Milestone-First Execution Order

**Date:** 2026-01-30
**Configuration:** ✅ Applied
**Priority Strategy:** Sequential milestone completion before tests/code/docs

---

## 🎯 Execution Order Configured

Your workflow is now set to complete **ALL** tasks in each prefix group before moving to the next:

```
m1 → m2 → m2.5 → m3 → m3.1 → m3.2 → m3.3 → m4 → tests → code → docs
```

---

## 📋 Detailed Execution Plan

### **Phase 1: Foundation (Priority 1-8)**

| Step | Prefix | Priority | Tasks | Description |
|------|--------|----------|-------|-------------|
| 1 | **m1** | 1 | 8 | Foundation - Project structure, config, basic tools |
| 2 | **m2** | 2 | 8 | Core Features - LLM providers, agents, tools |
| 3 | **m2.5** | 3 | 5 | Engine Abstraction - Execution engine interface |
| 4 | **m3** | 4 | 11 | Multi-Agent Core - Collaboration strategies |
| 5 | **m3.1** | 5 | 6 | Type Safety - Type improvements & cleanup |
| 6 | **m3.2** | 6 | 14 | Compiler Refactoring - LangGraph compiler work |
| 7 | **m3.3** | 7 | 6 | Performance - Async LLM, benchmarks |
| 8 | **m4** | 8 | 15 | Safety System - Policy engine, safety gates |

**Total Milestone Tasks:** 73 tasks

---

### **Phase 2: Testing (Priority 11-24)**

| Priority | Prefix | Tasks | Description |
|----------|--------|-------|-------------|
| 11 | **test-crit** | 15 | Critical test gaps (OWASP, security, E2E) |
| 12 | **test-security** | 8 | Security-specific tests |
| 13 | **test-high** | 10 | High priority test coverage |
| 14 | **test-fix** | 4 | Fix broken/failing tests |
| 15 | **test-integration** | 2 | Integration E2E tests |
| 16 | **test-med** | 4 | Medium priority tests |
| 17 | **test-llm** | 3 | LLM integration tests |
| 18 | **test-tool** | 5 | Tool execution tests |
| 19 | **test-perf** | 4 | Performance tests |
| 20 | **test-workflow** | 3 | Workflow tests |
| 21 | **test-agent** | 2 | Agent-specific tests |
| 22 | **test-error** | 2 | Error handling tests |
| 23 | **test-low** | 2 | Low priority tests |
| 24 | **test-*** (others) | 7 | Misc test categories |

**Total Test Tasks:** 71 tasks

---

### **Phase 3: Code Quality (Priority 31-36)**

| Priority | Prefix | Tasks | Description |
|----------|--------|-------|-------------|
| 31 | **code-crit** | 8 | CRITICAL security vulnerabilities |
| 32 | **code-high** | 2 | High priority bug fixes |
| 33 | **code-med** | 19 | Medium code quality improvements |
| 34 | **code-low** | 20 | Low priority code cleanup |
| 35 | **cq-p0** | 3 | Critical code quality issues |
| 36 | **cq-p1** | 1 | Important refactoring |

**Total Code Tasks:** 53 tasks (49 code + 4 cq)

---

### **Phase 4: Documentation (Priority 41-51)**

| Priority | Prefix | Tasks | Description |
|----------|--------|-------|-------------|
| 41 | **doc-crit** | 8 | Critical documentation errors |
| 42 | **doc-high** | 16 | High priority doc fixes |
| 43 | **doc-guide** | 7 | User guides |
| 44 | **doc-api** | 1 | API reference |
| 45 | **doc-med** | 20 | Medium doc improvements |
| 46 | **doc-adr** | 2 | Architecture Decision Records |
| 47 | **doc-reorg** | 3 | Documentation reorganization |
| 48 | **doc-consolidate** | 4 | Doc consolidation |
| 49 | **doc-low** | 20 | Low priority doc cleanup |
| 50 | **doc-archive** | 3 | Archive old documentation |
| 51 | **doc-update** | 1 | General updates |

**Total Doc Tasks:** 85 tasks

---

## 🚀 How Task Selection Works

When you run `task-next`, the system will:

1. **Check prefix priority first** (lower number = higher priority)
2. **Within same prefix**, use task priority (P1 > P2 > P3 > P4)
3. **Check dependencies** - skip tasks with unmet dependencies
4. **Check locks** - skip tasks with locked files
5. **Return highest priority available task**

### **Example Sequence:**

```bash
# First task will be from m1 (priority 1)
$ ./claude-coord.sh task-next my-agent
→ m1-00-structure

# After completing all m1 tasks, moves to m2 (priority 2)
$ ./claude-coord.sh task-next my-agent
→ m2-01-llm-providers

# After all milestones (m1→m4), moves to tests (priority 11)
$ ./claude-coord.sh task-next my-agent
→ test-crit-agents-recovery-01

# After all tests, moves to code (priority 31)
$ ./claude-coord.sh task-next my-agent
→ code-crit-ssrf-01

# Finally docs (priority 41)
$ ./claude-coord.sh task-next my-agent
→ doc-crit-01
```

---

## 📊 Progress Tracking

### **View Tasks by Prefix:**

```bash
# All m1 tasks
./claude-coord.sh task-list pending | grep "^P[0-9] m1"

# All m2 tasks
./claude-coord.sh task-list pending | grep "^P[0-9] m2-"

# All test tasks
./claude-coord.sh task-list pending | grep "^P[0-9] test-"

# Check what's next
./claude-coord.sh task-next my-agent
```

### **Monitor Progress:**

```bash
# Overall stats
./claude-coord.sh task-stats

# See completed tasks
./claude-coord.sh task-list all | grep "completed"

# Count tasks per prefix
jq -r '.tasks | to_entries[] | select(.value.status == "pending") | .key' \
  .claude-coord/state.json | cut -d'-' -f1-2 | sort | uniq -c
```

---

## 🔧 Workflow Commands

### **Start Working:**

```bash
# 1. Register your agent
./claude-coord.sh register my-agent

# 2. Get next task (will be from m1 first)
./claude-coord.sh task-next my-agent

# 3. Claim the task
./claude-coord.sh task-claim my-agent <task-id>

# 4. Work on it...

# 5. Mark complete
./claude-coord.sh task-complete my-agent <task-id>

# 6. Get next task (continues in order)
./claude-coord.sh task-next my-agent
```

### **Lock Files While Working:**

```bash
# Lock file before editing
./claude-coord.sh lock my-agent src/file.py

# Work on file...

# Unlock when done
./claude-coord.sh unlock my-agent src/file.py

# Or unlock all at once
./claude-coord.sh unlock-all my-agent
```

---

## ⚙️ Configuration Management

### **View Current Configuration:**

```bash
./claude-coord.sh task-prefix-list
```

### **Modify Priorities:**

```bash
# Change a specific prefix priority
./claude-coord.sh task-prefix-set m3.2 2  # Move m3.2 higher

# Clear a prefix priority (will use task priority only)
./claude-coord.sh task-prefix-clear m1

# Reapply entire configuration
./claude-coord/setup-milestone-first.sh
```

### **Reset to Different Strategy:**

```bash
# Security-first strategy
./claude-coord/setup-prefix-priorities.sh

# Back to milestone-first
./claude-coord/setup-milestone-first.sh
```

---

## 📈 Expected Timeline

Based on 295 total tasks:

### **Phase 1: Milestones (73 tasks)**
- **m1-m2:** ~16 tasks (foundation)
- **m2.5-m3.1:** ~22 tasks (abstraction & multi-agent)
- **m3.2-m3.3:** ~20 tasks (refactoring & performance)
- **m4:** 15 tasks (safety system)

### **Phase 2: Tests (71 tasks)**
- **Critical & Security:** ~23 tasks (high value)
- **Integration & High:** ~12 tasks
- **Medium & Tool:** ~12 tasks
- **Performance & Low:** ~24 tasks

### **Phase 3: Code (53 tasks)**
- **Critical & High:** ~10 tasks (security)
- **Medium:** ~19 tasks (quality)
- **Low & CQ:** ~24 tasks (cleanup)

### **Phase 4: Docs (85 tasks)**
- **Critical & High:** ~24 tasks (blocking issues)
- **Guides & API:** ~8 tasks (user-facing)
- **Medium & Cleanup:** ~53 tasks (polish)

---

## ✅ Benefits of This Order

1. **Sequential Milestone Completion**
   - Build on solid foundation
   - Each milestone enables the next
   - Clear progress milestones

2. **Features Before Tests**
   - Implement functionality first
   - Test comprehensively second
   - Easier to write tests for complete features

3. **Tests Before Cleanup**
   - Ensure correctness first
   - Clean up with confidence
   - Tests catch regressions

4. **Code Before Docs**
   - Document what exists
   - Accurate documentation
   - No need to update docs during code changes

5. **Clear Checkpoints**
   - Complete m1 → celebrate
   - Complete m2 → celebrate
   - Etc.

---

## 🎯 Current Status

**Configuration:** ✅ Applied (47 prefix priorities set)

**Next Task:** Will be from **m1** (Foundation)

**To Start:**
```bash
./claude-coord.sh register my-agent
./claude-coord.sh task-next my-agent
```

**You're ready to work through all 295 tasks in your preferred order!** 🚀

---

**Files:**
- **Config Script:** `.claude-coord/setup-milestone-first.sh`
- **Analysis:** `.claude-coord/PREFIX_ANALYSIS.md`
- **This Guide:** `.claude-coord/MILESTONE_FIRST_ORDER.md`
