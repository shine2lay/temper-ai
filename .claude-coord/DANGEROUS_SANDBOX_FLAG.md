# dangerouslyDisableSandbox Flag Guide

## Overview

The `dangerouslyDisableSandbox` parameter allows running Bash commands **outside the normal sandbox**, bypassing safety constraints.

## ⚠️ When to Use (Rare!)

**Only use when absolutely necessary:**

✅ **System administration tasks**
- Installing packages: `apt-get`, `yum`, `brew`
- System configuration: `/etc/` modifications
- Service management: `systemctl`, `service`

✅ **Build/deployment operations**
- Docker operations requiring privileged access
- CI/CD scripts that modify system state
- Cross-compilation requiring system tools

✅ **File operations outside project**
- Working with files in `/etc/`, `/usr/`, `/opt/`
- System-wide installations
- Global configuration changes

## ❌ When NOT to Use

**Don't use for normal operations:**

❌ File operations in your project (use Write/Edit tools)
❌ Reading files (use Read tool)
❌ Git operations (already unrestricted)
❌ Running tests (normal sandbox is fine)
❌ Building code (normal sandbox is fine)

## Syntax

In your message to Claude, you would request:

```
"Please install the required system package using:
bash command with dangerouslyDisableSandbox flag"
```

Claude will then invoke the Bash tool with this parameter set to true.

## Examples

### Example 1: System Package Installation

**Request:**
```
Install Python development headers needed for compilation
```

**What Claude does:**
```
Uses: Bash tool
Command: sudo apt-get install -y python3-dev
Flag: dangerouslyDisableSandbox=true
Reason: Requires system package manager access
```

### Example 2: Systemd Service Management

**Request:**
```
Restart the coordination daemon service
```

**What Claude does:**
```
Uses: Bash tool
Command: systemctl --user restart coordination-daemon
Flag: dangerouslyDisableSandbox=true
Reason: Requires systemd access
```

### Example 3: Global Binary Installation

**Request:**
```
Install the coord binary globally to /usr/local/bin
```

**What Claude does:**
```
Uses: Bash tool
Command: sudo cp ~/.local/bin/coord /usr/local/bin/
Flag: dangerouslyDisableSandbox=true
Reason: Writing to system directories
```

## What Gets Bypassed

**Normal sandbox restrictions:**
- File system access limits
- Process isolation
- Resource constraints
- Security policies

**Still enforced:**
- File operation rules (use Write/Edit, not bash redirection)
- Coordination system locks
- Input validation
- Error handling

## Safety Notes

1. **Use sparingly:** Most operations don't need this
2. **Be explicit:** Always describe what and why
3. **Review carefully:** These commands have full system access
4. **Prefer alternatives:** If Write/Edit/Read can do it, use those instead

## Alternatives to Consider First

| Instead of | Use this |
|------------|----------|
| `bash: echo > file` with flag | `Write(file_path, content)` |
| `bash: cat file` with flag | `Read(file_path)` |
| `bash: sed -i` with flag | `Edit(file_path, old, new)` |
| `bash: git push` with flag | Regular `Bash` (git is unrestricted) |
| `bash: python test.py` with flag | Regular `Bash` (tests are unrestricted) |

## Common Mistakes

### ❌ Wrong: Using for file operations
```
Don't: bash with dangerouslyDisableSandbox to write files
Do: Use Write() tool directly
```

### ❌ Wrong: Using for git operations
```
Don't: bash git push with dangerouslyDisableSandbox
Do: Regular bash git push (already works)
```

### ❌ Wrong: Using for project files
```
Don't: bash with dangerouslyDisableSandbox to modify src/
Do: Use Edit() for code changes
```

### ✅ Correct: Using for system operations
```
Do: bash apt-get install with dangerouslyDisableSandbox
Do: bash systemctl restart with dangerouslyDisableSandbox
Do: bash operations in /etc/ with dangerouslyDisableSandbox
```

## How to Request It

**To Claude, just ask naturally:**

```
"Install the redis package system-wide"
"Restart the nginx service"
"Copy the binary to /usr/local/bin"
```

Claude will determine if the dangerously disable sandbox flag is needed based on:
- Command requires system access
- Operations outside project directory
- Privileged operations (sudo, systemctl, etc.)
- Package management operations

## Default Behavior

**Without flag (normal mode):**
- ✅ Project directory operations
- ✅ Git operations
- ✅ Building/testing code
- ✅ Running scripts
- ✅ Most development tasks

**With flag (dangerous mode):**
- ✅ System administration
- ✅ Package installation
- ✅ Service management
- ✅ Global configuration

---

## Summary

- **Flag:** `dangerouslyDisableSandbox: true`
- **Use:** Rarely, only for system operations
- **Default:** false (sandboxed)
- **Request:** Just ask Claude naturally for system operations
- **Alternatives:** Prefer Write/Edit/Read tools for file operations

**Rule of thumb:** If you're working in your project directory, you probably don't need this flag!
