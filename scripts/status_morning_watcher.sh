#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# status_morning_watcher.sh — Check LucidFlex Morning Watcher Status & Logs
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_LABEL="com.lucidflex.morningwatcher"
PLIST_DST="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
LOG_FILE="$REPO_DIR/logs/morning_watcher.log"
PARITY_STATE="$REPO_DIR/results/forward_test/demo_parity_state.json"
UID_VAL="$(id -u)"
GUI_DOMAIN="gui/${UID_VAL}"

echo "=================================================================="
echo " LucidFlex 25K Morning Watcher Daemon Status"
echo "=================================================================="
echo " Timestamp:   $(date)"
echo " Repository:  $REPO_DIR"
echo " Plist:       $PLIST_DST"
echo " Log file:    $LOG_FILE"
echo "------------------------------------------------------------------"

IS_LOADED=0
PID=""
STATE="STOPPED"

if launchctl print "${GUI_DOMAIN}/${PLIST_LABEL}" >/dev/null 2>&1; then
    IS_LOADED=1
    PID=$(launchctl print "${GUI_DOMAIN}/${PLIST_LABEL}" 2>/dev/null | awk '/^[[:space:]]*pid = / {print $3}' || true)
    if [[ -n "$PID" && "$PID" -gt 0 ]]; then
        STATE="RUNNING"
    else
        STATE="LOADED_IDLE"
    fi
fi

# Fallback check process table if launchd didn't catch PID
if [[ -z "$PID" || "$PID" == "0" ]]; then
    EXT_PID=$(pgrep -f "[p]ython.*watch_morning_demo_alerts\.py" | head -n 1 || true)
    if [[ -n "$EXT_PID" ]]; then
        PID="$EXT_PID"
        if [[ $IS_LOADED -eq 1 ]]; then
            STATE="RUNNING"
        else
            STATE="RUNNING_EXTERNAL"
        fi
    fi
fi

case "$STATE" in
    RUNNING)
        echo " Status:      🟢 ACTIVE / RUNNING in launchd (PID: $PID)"
        ;;
    RUNNING_EXTERNAL)
        echo " Status:      🟡 RUNNING OUTSIDE LAUNCHD (PID: $PID)"
        ;;
    LOADED_IDLE)
        echo " Status:      🟡 LOADED IN LAUNCHD (Idle / Waiting for scheduled interval)"
        ;;
    *)
        echo " Status:      🔴 STOPPED / NOT LOADED"
        ;;
esac

# Account Parity State Summary (if available)
if [[ -f "$PARITY_STATE" ]]; then
    echo "------------------------------------------------------------------"
    echo " Account Parity State (demo_parity_state.json):"
    python3 -c "
import json
try:
    with open('$PARITY_STATE') as f:
        d = json.load(f)
    print(f'   Balance:      \${d.get(\"balance\", 0):,.2f}')
    print(f'   Peak Balance: \${d.get(\"peak_balance\", 0):,.2f}')
    print(f'   Floor:        \${d.get(\"trailing_floor\", 0):,.2f}')
    print(f'   Cushion:      \${d.get(\"trailing_cushion\", 0):,.2f}')
    print(f'   Sizing Tier:  {d.get(\"recommended_tier\", \"N/A\")}')
    print(f'   Eval Status:  {d.get(\"status\", \"N/A\")}')
except Exception as e:
    print(f'   (Could not parse JSON: {e})')
" || true
fi

# Recent Log Output
echo "------------------------------------------------------------------"
echo " Recent Logs (Last 25 lines of $LOG_FILE):"
echo "------------------------------------------------------------------"
if [[ -f "$LOG_FILE" ]]; then
    tail -n 25 "$LOG_FILE"
else
    echo " [INFO] Log file does not exist yet. Run 'scripts/start_morning_watcher.sh' to start daemon."
fi
echo "=================================================================="

if [[ "$STATE" == RUNNING* ]]; then
    exit 0
else
    exit 1
fi
