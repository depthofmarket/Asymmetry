#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# start_morning_watcher.sh — Start LucidFlex Morning Watcher macOS LaunchAgent
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_LABEL="com.lucidflex.morningwatcher"
PLIST_DST="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
REPO_PLIST="$REPO_DIR/config/${PLIST_LABEL}.plist"
LOG_DIR="$REPO_DIR/logs"
LOG_FILE="$LOG_DIR/morning_watcher.log"
UID_VAL="$(id -u)"
GUI_DOMAIN="gui/${UID_VAL}"

echo "=================================================================="
echo " Starting Morning Forward-Test Watcher LaunchAgent"
echo "=================================================================="
echo " Repository:  $REPO_DIR"
echo " Plist:       $PLIST_DST"
echo " Logs:        $LOG_FILE"
echo " GUI Domain:  $GUI_DOMAIN"
echo "=================================================================="

# 1. Ensure logs and LaunchAgents directories exist
mkdir -p "$LOG_DIR"
mkdir -p "$HOME/Library/LaunchAgents"

# 2. Synchronize LaunchAgent plist if repo version exists
if [[ -f "$REPO_PLIST" ]]; then
    echo ">> Synchronizing LaunchAgent plist to $PLIST_DST..."
    cp "$REPO_PLIST" "$PLIST_DST"
    chmod 644 "$PLIST_DST"
elif [[ ! -f "$PLIST_DST" ]]; then
    echo "ERROR: Plist template not found at $REPO_PLIST or $PLIST_DST." >&2
    exit 1
fi

# 3. Validate plist XML syntax
if command -v plutil >/dev/null 2>&1; then
    plutil -lint "$PLIST_DST" >/dev/null || {
        echo "ERROR: Invalid XML syntax in $PLIST_DST" >&2
        exit 1
    }
fi

# 4. Check if already loaded in launchd
IS_LOADED=0
if launchctl print "${GUI_DOMAIN}/${PLIST_LABEL}" >/dev/null 2>&1; then
    IS_LOADED=1
fi

if [[ $IS_LOADED -eq 1 ]]; then
    EXISTING_PID=$(launchctl print "${GUI_DOMAIN}/${PLIST_LABEL}" 2>/dev/null | awk '/^[[:space:]]*pid = / {print $3}' || true)
    if [[ -n "$EXISTING_PID" && "$EXISTING_PID" -gt 0 ]]; then
        echo ">> Morning Watcher is already loaded and running (PID: $EXISTING_PID)."
        echo ">> Run 'scripts/status_morning_watcher.sh' for live status or 'scripts/stop_morning_watcher.sh' to restart."
        exit 0
    else
        echo ">> Morning Watcher is loaded in launchd but idle. Kickstarting service..."
        launchctl kickstart -k "${GUI_DOMAIN}/${PLIST_LABEL}" 2>/dev/null || true
    fi
else
    echo ">> Loading LaunchAgent into launchd (${GUI_DOMAIN})..."
    if launchctl bootstrap "$GUI_DOMAIN" "$PLIST_DST" 2>/dev/null; then
        echo ">> Successfully bootstrapped into $GUI_DOMAIN."
    else
        echo ">> Bootstrap returned non-zero; attempting fallback launchctl load..."
        launchctl load -w "$PLIST_DST" 2>/dev/null || true
    fi
    launchctl kickstart -k "${GUI_DOMAIN}/${PLIST_LABEL}" 2>/dev/null || true
fi

# 5. Wait up to 3 seconds for active PID
PID=""
for _ in {1..6}; do
    PID=$(launchctl print "${GUI_DOMAIN}/${PLIST_LABEL}" 2>/dev/null | awk '/^[[:space:]]*pid = / {print $3}' || true)
    if [[ -n "$PID" && "$PID" -gt 0 ]]; then
        break
    fi
    PID=$(pgrep -f "[p]ython.*watch_morning_demo_alerts\.py" | head -n 1 || true)
    if [[ -n "$PID" && "$PID" -gt 0 ]]; then
        break
    fi
    sleep 0.5
done

if [[ -n "$PID" && "$PID" -gt 0 ]]; then
    echo ">> SUCCESS: Morning Watcher running as PID $PID."
    echo ">> Logging to: $LOG_FILE"
    echo ">> Monitor logs with: tail -f $LOG_FILE"
    exit 0
else
    echo ">> WARNING: Daemon loaded, but active PID not yet detected."
    echo ">> Check status: scripts/status_morning_watcher.sh"
    echo ">> Check logs:   tail -n 20 $LOG_FILE"
    exit 1
fi
