# Global `coord` Command

## Overview

The `coord` command is now available **globally** - you can run it from any directory within a coordination-enabled project.

## How It Works

**Similar to git:** The `coord` wrapper automatically finds your project by walking up the directory tree looking for `.claude-coord/`.

```
Current directory: ~/project/src/deeply/nested/
                   └─ walks up ──┐
                                 ▼
Project root:      ~/project/.claude-coord/  ✓ Found!
```

## Usage

**From anywhere in your project:**

```bash
# In project root
~/meta-autonomous-framework$ coord status
Status: running

# In subdirectory - still works!
~/meta-autonomous-framework/src/agents$ coord status
Status: running

# In deeply nested directory - works!
~/meta-autonomous-framework/tests/integration$ coord task-list
```

**Outside project:**

```bash
# Somewhere else
/tmp$ coord status
Error: Not in a coordination-enabled project

Looking for .claude-coord/ directory...
Navigate to a project directory with coordination enabled.
```

## Installation

Already installed! The setup added:

1. **Wrapper script:** `~/.local/bin/coord`
   - Finds nearest `.claude-coord/` directory
   - Calls the real coord CLI from your project
   - Works like git (project-aware)

2. **PATH update:** Added to `~/.bashrc`
   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   ```

3. **For new shells:** Run `source ~/.bashrc` or restart your terminal

## Examples

```bash
# Navigate anywhere in your project
cd ~/meta-autonomous-framework/src/safety

# Register agent
coord register $CLAUDE_AGENT_ID $$

# List tasks
coord task-list

# Check status
coord status

# Get velocity metrics
coord velocity --period '1 hour'

# Work on a task
coord task-claim $CLAUDE_AGENT_ID test-crit-01
```

## Multiple Projects

If you have multiple coordination-enabled projects, `coord` automatically uses the correct one based on your current directory:

```bash
# Project A
cd ~/project-a/src
coord status  # Uses project-a's daemon

# Project B
cd ~/project-b/tests
coord status  # Uses project-b's daemon
```

Each project has its own:
- Daemon process
- Database
- Socket
- Tasks and state

## Comparison

**Before (project-specific):**
```bash
# Had to use full path or be in project root
~/meta-autonomous-framework/.claude-coord/bin/coord status

# Or relative path
./.claude-coord/bin/coord status
```

**After (global):**
```bash
# Works from anywhere in project
coord status
```

## Benefits

✅ **Convenience:** No more long paths or `cd` to project root
✅ **Git-like:** Familiar workflow (finds project automatically)
✅ **Multiple projects:** Switches automatically based on current directory
✅ **Shell integration:** Available in all new terminal sessions

## Troubleshooting

**`coord: command not found`**
```bash
# Update current session
source ~/.bashrc

# Or check PATH
echo $PATH | grep ".local/bin"

# Verify wrapper exists
ls -la ~/.local/bin/coord
```

**Wrong project**
```bash
# Check which project coord found
coord status

# If wrong, navigate to correct project first
cd ~/correct-project
coord status
```

## Technical Details

**Wrapper location:** `~/.local/bin/coord`
**Real CLI:** `<project>/.claude-coord/bin/coord`
**Search algorithm:** Walks up from `pwd` to find `.claude-coord/`

The wrapper is a thin Python script (50 lines) that:
1. Starts at current directory
2. Walks up looking for `.claude-coord/`
3. Executes the real coord CLI from that project
4. Passes through all arguments and exit codes

---

**Result:** `coord` now works like `git` - run it from anywhere in your project! 🎉
