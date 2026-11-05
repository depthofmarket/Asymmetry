#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# stop_morning_watcher.sh — Stop LucidFlex Morning Watcher macOS LaunchAgent
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_LABEL="com.lucidflex.morningwatcher"
PLIST_DST="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
UID_VAL="$(id -u)"
GUI_DOMAIN="gui/${UID_VAL}"

echo "=================================================================="
echo " Stopping Morning Forward-Test Watcher LaunchAgent"
echo "=================================================================="

STOPPED_SOMETHING=0

# 1. Unload from launchd
if launchctl print "${GUI_DOMAIN}/${PLIST_LABEL}" >/dev/null 2>&1; then
    echo ">> Unloading service ${PLIST_LABEL} via launchctl bootout..."
    launchctl bootout "${GUI_DOMAIN}/${PLIST_LABEL}" 2>/dev/null || \
    launchctl bootout "$GUI_DOMAIN" "$PLIST_DST" 2>/dev/null || \
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    STOPPED_SOMETHING=1
elif [[ -f "$PLIST_DST" ]]; then
    echo ">> Attempting fallback unload via plist path..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

# 2. Check for lingering python watcher processes
MATCHING_PIDS=$(pgrep -f "[p]ython.*watch_morning_demo_alerts\.py" || true)
if [[ -n "$MATCHING_PIDS" ]]; then
    echo ">> Terminating lingering watcher process(es): $MATCHING_PIDS..."
    kill $MATCHING_PIDS 2>/dev/null || true
    sleep 1
    REMAINING_PIDS=$(pgrep -f "[p]ython.*watch_morning_demo_alerts\.py" || true)
    if [[ -n "$REMAINING_PIDS" ]]; then
        echo ">> Force-killing remaining process(es): $REMAINING_PIDS..."
        kill -9 $REMAINING_PIDS 2>/dev/null || true
    fi
    STOPPED_SOMETHING=1
fi

if [[ $STOPPED_SOMETHING -eq 1 ]]; then
    echo ">> SUCCESS: Morning Watcher daemon stopped and unloaded cleanly."
    exit 0
else
    echo ">> Morning Watcher was not active."
    exit 0
fi
