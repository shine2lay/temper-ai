#!/bin/bash
# Install coordination service as systemd service

set -e

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="coord-service.service"
SYSTEMD_DIR="/etc/systemd/system"

echo "========================================="
echo "Install Coordination Service (systemd)"
echo "========================================="
echo ""

# Check if running as root (needed for systemd)
if [ "$EUID" -eq 0 ]; then
    echo "✓ Running as root"
else
    echo "This script needs sudo access to install systemd service."
    echo "It will prompt for your password."
    echo ""
    sudo -v
fi

# Copy service file
echo "1. Installing service file..."
sudo cp "$COORD_DIR/$SERVICE_FILE" "$SYSTEMD_DIR/$SERVICE_FILE"
echo "   → $SYSTEMD_DIR/$SERVICE_FILE"

# Reload systemd
echo ""
echo "2. Reloading systemd daemon..."
sudo systemctl daemon-reload

# Enable service (auto-start on boot)
echo ""
echo "3. Enabling service (auto-start on boot)..."
sudo systemctl enable coord-service
echo "   ✓ Service will start automatically on boot"

# Start service now
echo ""
read -p "Start service now? (y/n): " start_now

if [ "$start_now" = "y" ]; then
    echo ""
    echo "4. Starting service..."
    sudo systemctl start coord-service

    echo ""
    echo "5. Checking status..."
    sudo systemctl status coord-service --no-pager
fi

echo ""
echo "========================================="
echo "Installation complete!"
echo "========================================="
echo ""
echo "Service commands:"
echo "  sudo systemctl status coord-service     # Check status"
echo "  sudo systemctl start coord-service      # Start manually"
echo "  sudo systemctl stop coord-service       # Stop service"
echo "  sudo systemctl restart coord-service    # Restart service"
echo "  sudo systemctl disable coord-service    # Disable auto-start"
echo ""
echo "Logs:"
echo "  sudo journalctl -u coord-service        # View all logs"
echo "  sudo journalctl -u coord-service -f     # Follow logs (tail)"
echo "  sudo journalctl -u coord-service --since today  # Today's logs"
echo ""
