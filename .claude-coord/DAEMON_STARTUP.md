# Daemon Startup Options

The coordination daemon can start automatically in two ways:

## Option 1: Auto-Start on First Use (Default) ✅

**How it works:**
- When you run any `coord` command, it checks if the daemon is running
- If not running, it automatically starts the daemon
- Then executes your command

**No configuration needed!** Just use:
```bash
coord status
coord task-list
coord register $CLAUDE_AGENT_ID $$
```

**Benefits:**
- ✅ Zero configuration
- ✅ Works immediately
- ✅ Starts only when needed
- ✅ Daemon per project (isolated)

**Example:**
```bash
$ coord status
Starting coordination daemon...
✓ Daemon started
Status: running
Agents: 0
Tasks:
  Pending: 64
  In Progress: 0
  Completed: 85
Locks: 0
```

---

## Option 2: Systemd Service (System Boot)

For users who want the daemon running all the time (starts on system boot).

### Installation

```bash
# 1. Create systemd user service directory
mkdir -p ~/.config/systemd/user/

# 2. Copy service file
cp .claude-coord/coordination-daemon.service \
   ~/.config/systemd/user/coordination-daemon@$(whoami).service

# 3. Edit service file to match your project path
# Update WorkingDirectory and ExecStart/ExecStop paths
nano ~/.config/systemd/user/coordination-daemon@$(whoami).service

# 4. Reload systemd
systemctl --user daemon-reload

# 5. Enable service (start on boot)
systemctl --user enable coordination-daemon@$(whoami).service

# 6. Start service now
systemctl --user start coordination-daemon@$(whoami).service
```

### Management

```bash
# Check status
systemctl --user status coordination-daemon@$(whoami).service

# View logs
journalctl --user -u coordination-daemon@$(whoami).service -f

# Restart
systemctl --user restart coordination-daemon@$(whoami).service

# Stop
systemctl --user stop coordination-daemon@$(whoami).service

# Disable (don't start on boot)
systemctl --user disable coordination-daemon@$(whoami).service
```

### Benefits

- ✅ Starts automatically on system boot
- ✅ Automatic restart on crashes
- ✅ System logging integration
- ✅ Clean shutdown on reboot

### Drawbacks

- ❌ Requires systemd setup
- ❌ Runs even when not needed
- ❌ More complex to debug
- ❌ One daemon for entire system (not per-project)

---

## Recommendation

**For most users:** Use **Option 1 (Auto-Start)** - it's simpler and works great.

**For always-on use:** Use **Option 2 (Systemd)** if you:
- Run coordination operations frequently
- Want instant response times (no startup delay)
- Have multiple projects sharing the daemon
- Need reliable daemon uptime

---

## Manual Daemon Management

You can also manage the daemon manually:

```bash
# Start daemon
python3 -m coord_service.daemon start

# Stop daemon
python3 -m coord_service.daemon stop

# Check status
python3 -m coord_service.daemon status

# Restart
python3 -m coord_service.daemon restart
```

**Note:** Run these from your project directory (where `.claude-coord` is located).

---

## Troubleshooting

### Daemon won't start

```bash
# Check logs
tail -f /tmp/coord-daemon.log

# Check if socket exists
ls -la /tmp/coord-*.sock

# Kill stale processes
killall -9 python3  # Use with caution!

# Remove stale socket
rm -f /tmp/coord-*.sock

# Try manual start
cd /path/to/project
python3 -m coord_service.daemon start --foreground
```

### Daemon crashes on startup

```bash
# Check Python path
python3 -c "import sys; print(sys.path)"

# Check coord_service module
python3 -c "import coord_service; print('OK')"

# Check database
sqlite3 .claude-coord/coordination.db ".schema"
```

### Multiple daemons running

```bash
# Each project gets its own daemon
# Socket path includes project hash: /tmp/coord-{hash}.sock

# List all coordination sockets
ls -la /tmp/coord-*.sock

# Check which project each daemon serves
ps aux | grep coord_service
```

---

## Current Status

✅ **Auto-start enabled** - No configuration needed!

Just run:
```bash
coord status
```

The daemon will automatically start if not running.
