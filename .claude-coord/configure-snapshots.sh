#!/bin/bash
# Configure snapshot interval

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Select snapshot interval:"
echo ""
echo "  1) Every 30 minutes (48 snapshots/day)"
echo "  2) Every hour (24 snapshots/day)"
echo "  3) Every 2 hours (12 snapshots/day)"
echo "  4) Every 4 hours (6 snapshots/day)"
echo "  5) Disable automatic snapshots"
echo ""

read -p "Choice: " choice

case $choice in
    1) INTERVAL="*/30 * * * *"; DESC="30 minutes" ;;
    2) INTERVAL="0 * * * *"; DESC="1 hour" ;;
    3) INTERVAL="0 */2 * * *"; DESC="2 hours" ;;
    4) INTERVAL="0 */4 * * *"; DESC="4 hours" ;;
    5) 
        echo "Removing snapshot cron job..."
        crontab -l 2>/dev/null | grep -v ".snapshot-state.sh" | crontab -
        echo "✓ Automatic snapshots disabled"
        exit 0
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

CRON_CMD="$INTERVAL $COORD_DIR/.snapshot-state.sh >> $COORD_DIR/snapshot.log 2>&1"

# Remove old snapshot job
crontab -l 2>/dev/null | grep -v ".snapshot-state.sh" | crontab -

# Add new snapshot job
(crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -

echo "✓ Snapshots configured: every $DESC"
echo ""
echo "Verify with: crontab -l | grep snapshot"
