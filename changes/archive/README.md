# Change Log Archive

This directory contains archived change logs organized by milestone and category.

---

## Archive Structure

| Category | Files | Description |
|----------|-------|-------------|
| [Milestone 1](./milestone-1/) | 3 | Core Agent System |
| [Milestone 2](./milestone-2/) | 8 | Workflow Orchestration |
| [Milestone 2.5](./milestone-2.5/) | 5 | Execution Engine Abstraction |
| [Milestone 3](./milestone-3/) | 12 | Multi-Agent Collaboration |
| [Milestone 4](./milestone-4/) | 1 | Safety & Governance System (in progress) |
| [Code Quality](./code-quality/) | 28 | Bug fixes, refactoring, optimizations |
| [Testing](./testing/) | 9 | Test suites and test infrastructure |
| [Documentation](./documentation/) | 16 | Documentation guides and updates |

**Total:** 82 archived change logs

---

## Archive Policy

Change logs are archived when:
- Milestone is complete
- Task is fully implemented and tested
- Related work is merged and deployed
- Log is older than 30 days (for completed work)

---

## Finding Logs

### By Milestone
- **M1** tasks: `./milestone-1/`
- **M2** tasks: `./milestone-2/`
- **M2.5** tasks: `./milestone-2.5/`
- **M3** tasks: `./milestone-3/`
- **M4** tasks: `./milestone-4/`

### By Category
- **Code quality** (cq-*): `./code-quality/`
- **Testing** (test-*): `./testing/`
- **Documentation** (doc-*): `./documentation/`

### Search Example

```bash
# Find all security-related changes
grep -r "security\|SSRF\|injection" changes/archive/

# Find specific task
find changes/archive/ -name "*<task-id>*"

# List all M3 changes
ls changes/archive/milestone-3/
```

---

## Related Documentation

- **Milestone Reports**: `/docs/milestones/`
- **Current Change Logs**: `/changes/` (active work)
- **Project Roadmap**: `/docs/ROADMAP.md`

---

Last updated: 2026-01-27
