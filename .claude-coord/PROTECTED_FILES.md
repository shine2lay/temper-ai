# Protected Files Configuration

This document explains how to protect critical files from accidental modification by Claude.

## Method 1: Claude Code Hooks (Recommended)

### Setup

1. **Configure BOTH hooks in project settings** (`.claude/settings.json`):

   ```json
   {
     "hooks": {
       "preToolUse": [
         {
           "command": ".claude-coord/protect-critical-files.sh",
           "description": "Blocks Edit/Write on protected files"
         },
         {
           "command": ".claude-coord/protect-critical-files-bash.sh",
           "description": "Blocks Bash commands writing to protected files"
         }
       ]
     }
   }
   ```

   **CRITICAL**: You MUST configure BOTH hooks:
   - `protect-critical-files.sh` - Blocks Edit/Write tools
   - `protect-critical-files-bash.sh` - Blocks bash redirection (>, >>, tee, sed -i, etc.)

   Without BOTH hooks, Claude can bypass protection using bash commands!

3. **Add files to protect** by editing `.claude-coord/protect-critical-files.sh`:

   ```bash
   PROTECTED_FILES=(
       ".claude-coord/claude-coord.sh"
       ".claude-coord/state.json"
       "your/critical/file.py"
   )
   ```

### How It Works

**Two-Layer Protection:**

1. **protect-critical-files.sh** - Blocks Edit/Write tools
   - Intercepts Edit and Write tool calls
   - Checks if target file is in protected list
   - Blocks operation with error message if protected

2. **protect-critical-files-bash.sh** - Blocks bash redirection
   - Intercepts Bash tool calls
   - Detects file redirection operators (`>`, `>>`, `tee`, `sed -i`, etc.)
   - Blocks bash commands that write to protected files
   - Prevents bypass via `echo > file`, `cat > file << EOF`, etc.

**Why Both Are Needed:**

Claude can write files using:
- Write/Edit tools → Blocked by first hook ✓
- Bash redirection → Blocked by second hook ✓

Without BOTH hooks, protection can be bypassed.

- **Requires explicit user permission** to modify protected files
- Works in **all modes** (single-agent, multi-agent, plan mode, etc.)

---

## Method 2: File System Permissions

### Make files read-only:

```bash
# Protect specific files
chmod 444 .claude-coord/claude-coord.sh
chmod 444 .claude-coord/state.json

# Protect entire directory
chmod -R 444 .claude-coord/
```

### Restore write access when needed:

```bash
chmod 644 .claude-coord/claude-coord.sh
```

**Note:** Claude can still overwrite with `Bash` commands using sudo, so combine with Method 1.

---

## Method 3: Git Protection

### Use .gitignore to prevent tracking changes:

```bash
# Add to .gitignore
.claude-coord/state.json
```

### Use git update-index to assume unchanged:

```bash
git update-index --assume-unchanged .claude-coord/claude-coord.sh
```

**Note:** This only prevents git commits, not file modifications.

---

## Method 4: Backup Critical Files

### Automatic backups before modifications:

Add to `.claude-coord/protect-critical-files.sh`:

```bash
# Create backup before allowing modification
BACKUP_DIR=".claude-coord/backups"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
cp "$FILE_PATH" "$BACKUP_DIR/$(basename $FILE_PATH).$TIMESTAMP.bak"
```

---

## Currently Protected Files

The following files are protected by the hook:

1. `.claude-coord/protect-critical-files.sh` - **The protection script itself** (self-protecting)
2. `.claude-coord/claude-coord.sh` - Coordination system core script
3. `.claude-coord/state.json` - Multi-agent state (locks, tasks, agents)
4. `.claude-coord/task-spec-helpers.sh` - Task specification helpers

**Important:** The protection script protects itself, so Claude cannot modify the protected files list without your explicit permission.

**To modify a protected file:**
1. Claude must ask you for explicit permission first
2. You manually edit the PROTECTED_FILES list (since the script protects itself)
3. Or you disable the hook in Claude Code settings

**Note:** Since `protect-critical-files.sh` protects itself, Claude cannot modify the PROTECTED_FILES list. Only you can do this manually.

---

## Testing Protection

Test that the hook works:

```bash
# This should be blocked:
echo "test" > .claude-coord/claude-coord.sh

# If not blocked, check:
# 1. Hook is executable: ls -l .claude-coord/protect-critical-files.sh
# 2. Hook is configured in settings
# 3. jq is installed: which jq
```

---

## Disabling Protection Temporarily

### Option 1: Remove from protected list

Edit `.claude-coord/protect-critical-files.sh` and comment out the file:

```bash
PROTECTED_FILES=(
    # ".claude-coord/claude-coord.sh"  # Temporarily unprotected
    ".claude-coord/state.json"
)
```

### Option 2: Disable the entire hook

Remove from `.claude/settings.json` or Claude Code settings.

---

## Best Practices

1. **Always protect:**
   - Coordination scripts (claude-coord.sh)
   - State files (state.json)
   - Configuration files with secrets
   - Critical business logic

2. **Review changes:**
   - Use git to track all modifications
   - Review diffs before committing

3. **Backup regularly:**
   - Keep backups of critical files
   - Version control everything

4. **Test protection:**
   - Periodically test that hooks work
   - Verify blocked files cannot be modified

---

## Recovery from Accidental Modification

If a protected file was modified:

1. **Check git history:**
   ```bash
   git log --all -- .claude-coord/claude-coord.sh
   git show <commit>:.claude-coord/claude-coord.sh
   ```

2. **Check backups:**
   ```bash
   ls -lt .claude-coord/backups/
   ```

3. **Check Claude Code file history:**
   ```bash
   find ~/.claude/projects -name "*.jsonl" | xargs grep -l "claude-coord.sh"
   ```

4. **Ask user for previous version:**
   - Request user to provide the last known good version
   - Document what customizations were made
