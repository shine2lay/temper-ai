#!/bin/bash
# Installation script for coordination daemon

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Coordination Daemon Installation ==="
echo

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "✓ Python version: $PYTHON_VERSION"

# Create necessary directories
echo "Creating directories..."
mkdir -p coord_service/tests
mkdir -p bin
mkdir -p backups
mkdir -p task-specs

# Make executables
echo "Setting executable permissions..."
chmod +x bin/coord-daemon
chmod +x bin/coord-client

# Test daemon can start
echo
echo "Testing daemon..."
if bin/coord-daemon status &> /dev/null; then
    echo "✓ Daemon already running"
else
    echo "  Starting daemon..."
    bin/coord-daemon start
    sleep 2

    if bin/coord-daemon status &> /dev/null; then
        echo "✓ Daemon started successfully"
    else
        echo "✗ Failed to start daemon"
        exit 1
    fi
fi

# Test client
echo
echo "Testing client..."
if bin/coord-client status &> /dev/null; then
    echo "✓ Client can communicate with daemon"
else
    echo "✗ Client cannot communicate with daemon"
    exit 1
fi

# Migrate existing state if present
if [ -f "state.json" ]; then
    echo
    echo "Found existing state.json"
    read -p "Migrate to daemon? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Migrating state..."
        bin/coord-client import state.json
        echo "✓ State migrated"

        # Backup old state
        cp state.json state.json.pre-daemon-backup
        echo "✓ Backup created: state.json.pre-daemon-backup"
    fi
fi

echo
echo "=== Installation Complete ==="
echo
echo "Usage:"
echo "  Start daemon:  .claude-coord/bin/coord-daemon start"
echo "  Stop daemon:   .claude-coord/bin/coord-daemon stop"
echo "  Check status:  .claude-coord/bin/coord-daemon status"
echo
echo "  Create task:   .claude-coord/bin/coord-client task-add <id> <subject> --priority <1-5>"
echo "  List tasks:    .claude-coord/bin/coord-client task-list"
echo "  Get velocity:  .claude-coord/bin/coord-client velocity"
echo
echo "Documentation:"
echo "  User guide:    .claude-coord/DAEMON_USAGE.md"
echo "  Technical:     .claude-coord/coord_service/README.md"
echo "  Summary:       .claude-coord/COORDINATION_DAEMON_SUMMARY.md"
