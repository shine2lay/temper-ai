# Coordination Daemon Documentation Index

**Purpose:** Central navigation for all daemon-related documentation.

---

## Quick Start (Start Here)

### For Developers Using the System

**👉 Start:** [DAEMON_QUICK_START.md](./DAEMON_QUICK_START.md)
- Get up and running in 5 minutes
- Basic commands
- Common workflows

**Next:** [README.md](./README.md)
- Complete command reference
- Task management
- File locking

### For Skill Developers

**👉 Start:** [DAEMON_FOR_SKILLS.md](./DAEMON_FOR_SKILLS.md)
- How to use coordination from skills
- API examples
- Best practices

---

## Documentation by Purpose

### 1. Using the Daemon

| Document | Purpose | Audience |
|----------|---------|----------|
| [DAEMON_QUICK_START.md](./DAEMON_QUICK_START.md) | 5-minute getting started | All users |
| [DAEMON_QUICK_REFERENCE.md](./DAEMON_QUICK_REFERENCE.md) | Command cheat sheet | All users |
| [DAEMON_USAGE.md](./DAEMON_USAGE.md) | Detailed usage guide | Regular users |
| [README.md](./README.md) | Complete command reference | All users |

**When to use:**
- Starting a new project → DAEMON_QUICK_START.md
- Forgot a command → DAEMON_QUICK_REFERENCE.md
- Need detailed examples → DAEMON_USAGE.md
- Looking up specific command → README.md

### 2. Understanding the Architecture

| Document | Purpose | Audience |
|----------|---------|----------|
| [SERVICE_ARCHITECTURE.md](./SERVICE_ARCHITECTURE.md) | Current architecture | Architects, advanced users |
| [COORDINATION_DAEMON_SUMMARY.md](./COORDINATION_DAEMON_SUMMARY.md) | High-level overview | Project managers, new devs |
| [DAEMON_DESIGN.md](./DAEMON_DESIGN.md) | Implementation details | Core contributors |

**When to use:**
- Need architectural overview → SERVICE_ARCHITECTURE.md
- Explaining to stakeholders → COORDINATION_DAEMON_SUMMARY.md
- Contributing to daemon code → DAEMON_DESIGN.md

### 3. Development & Integration

| Document | Purpose | Audience |
|----------|---------|----------|
| [DAEMON_FOR_SKILLS.md](./DAEMON_FOR_SKILLS.md) | Skill integration guide | Skill developers |
| [DAEMON_STARTUP.md](./DAEMON_STARTUP.md) | Startup sequence details | Core contributors |
| [COORD_SERVICE_TEST_AUDIT.md](./COORD_SERVICE_TEST_AUDIT.md) | Test coverage report | QA, contributors |

**When to use:**
- Building a new skill → DAEMON_FOR_SKILLS.md
- Debugging startup issues → DAEMON_STARTUP.md
- Reviewing test coverage → COORD_SERVICE_TEST_AUDIT.md

---

## Documentation Hierarchy

```
Start Here
│
├─ Quick Start (5 min)
│  └─ DAEMON_QUICK_START.md
│
├─ Regular Usage
│  ├─ DAEMON_QUICK_REFERENCE.md (cheat sheet)
│  ├─ DAEMON_USAGE.md (detailed guide)
│  └─ README.md (complete reference)
│
├─ Architecture & Design
│  ├─ SERVICE_ARCHITECTURE.md (current system)
│  ├─ COORDINATION_DAEMON_SUMMARY.md (overview)
│  └─ DAEMON_DESIGN.md (implementation)
│
└─ Advanced Topics
   ├─ DAEMON_FOR_SKILLS.md (skill integration)
   ├─ DAEMON_STARTUP.md (startup details)
   ├─ DEPENDENCY_GUIDE.md (task dependencies)
   └─ VALIDATION_SYSTEM.md (task validation)
```

---

## Common Scenarios

### "I want to start using multi-agent coordination"
1. Read: [DAEMON_QUICK_START.md](./DAEMON_QUICK_START.md)
2. Try: Example commands from [README.md](./README.md)
3. Reference: [DAEMON_QUICK_REFERENCE.md](./DAEMON_QUICK_REFERENCE.md)

### "I'm building a skill that uses coordination"
1. Read: [DAEMON_FOR_SKILLS.md](./DAEMON_FOR_SKILLS.md)
2. Reference: [README.md](./README.md) for commands
3. Check: [VALIDATION_SYSTEM.md](./VALIDATION_SYSTEM.md) for task specs

### "I need to understand how the daemon works"
1. Read: [COORDINATION_DAEMON_SUMMARY.md](./COORDINATION_DAEMON_SUMMARY.md)
2. Deep dive: [SERVICE_ARCHITECTURE.md](./SERVICE_ARCHITECTURE.md)
3. Implementation: [DAEMON_DESIGN.md](./DAEMON_DESIGN.md)

### "I'm troubleshooting an issue"
1. Check: [DAEMON_USAGE.md](./DAEMON_USAGE.md) troubleshooting section
2. Review: [DAEMON_STARTUP.md](./DAEMON_STARTUP.md) for startup issues
3. Inspect: Daemon logs at `.claude-coord/daemon.log`

---

## Document Status

| Document | Status | Last Updated | Notes |
|----------|--------|--------------|-------|
| SERVICE_ARCHITECTURE.md | ✅ Current | 2026-02-01 | Reflects implemented system |
| DAEMON_QUICK_START.md | ✅ Current | 2026-01-31 | |
| DAEMON_USAGE.md | ✅ Current | 2026-01-31 | |
| DAEMON_FOR_SKILLS.md | ✅ Current | 2026-01-31 | |
| README.md | ✅ Current | 2026-02-01 | Updated commands |
| DAEMON_DESIGN.md | ⚠️ Mixed | 2026-02-01 | Some proposal content |
| DAEMON_QUICK_REFERENCE.md | ✅ Current | 2026-01-30 | |
| COORDINATION_DAEMON_SUMMARY.md | ✅ Current | 2026-01-30 | |
| DAEMON_STARTUP.md | ✅ Current | 2026-01-29 | |

---

## Future Consolidation Plan

**Proposed simplified structure (M5+):**

```
.claude-coord/
├── README.md              # Quick start + command reference
├── ARCHITECTURE.md        # Combined architecture (SERVICE_ARCHITECTURE + DAEMON_DESIGN)
├── DAEMON_FOR_SKILLS.md   # Skill development guide (unchanged)
├── ADVANCED_TOPICS.md     # Combined advanced guides
└── archive/
    └── *.md               # Deprecated docs
```

**Benefits:**
- Fewer files to maintain
- Clearer navigation
- Reduced duplication
- Easier updates

**Migration:** Planned for M5 after documentation testing automation is in place.

---

## Contribution Guidelines

### Adding New Daemon Documentation

1. **Check existing docs first** - avoid duplication
2. **Use this index** - add your doc to the appropriate section
3. **Cross-link** - reference related docs
4. **Update status table** - mark last updated date

### Updating Existing Documentation

1. **Update the document**
2. **Update "Last Updated" in status table**
3. **Check for broken links**
4. **Update related docs** if needed

---

**Index Created:** 2026-02-01
**Maintained by:** Meta-Autonomous Framework Team

**Quick Links:**
- [Main README](./README.md)
- [Architecture](./SERVICE_ARCHITECTURE.md)
- [Quick Start](./DAEMON_QUICK_START.md)
- [For Skills](./DAEMON_FOR_SKILLS.md)
