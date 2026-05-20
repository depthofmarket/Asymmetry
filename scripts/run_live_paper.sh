#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Start the live paper-trading system using Yahoo Finance data.
#
# This starts two processes:
#   1. fetch_live_bars.py — polls Yahoo Finance for NQ 1m bars, writes to CSV.
#   2. run_amp_paper_trader.py — tails the CSV and runs the PaperTradingEngine.
#
# Usage:
#   bash scripts/run_live_paper.sh --candidate current
#   bash scripts/run_live_paper.sh current
#
# The default data path is results/live_bars.csv.
# All output (events, trades, orders) is written to results/paper_amp/<run_label>/.
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

BARS_CSV="${BARS_CSV:-$REPO_DIR/results/live_bars.csv}"
WARMUP_ROWS="${WARMUP_ROWS:-2500}"
CANDIDATE="edge_vp_mr_trend_failed_auction_quality_probe"
PROP_GUARD="${PROP_GUARD:-1}"
PROP_PROFILE="${PROP_PROFILE:-traders_launch_100k_nyc}"
PROP_PHASE="${PROP_PHASE:-eval}"
PROP_DAILY_PROFIT_LOCK="${PROP_DAILY_PROFIT_LOCK:-}"
COLLECTOR_PID=""
TRADER_PID=""

usage() {
    cat <<EOF
Usage:
  bash scripts/run_live_paper.sh [candidate]
  bash scripts/run_live_paper.sh --candidate current [--bars-csv results/live_bars.csv]

Environment overrides:
  BARS_CSV      CSV file used as the bar handoff path.
  WARMUP_ROWS   Historical 1-minute rows to emit and consume before trading.
  STOP_AFTER_BARS  Optional finite smoke-test bar count.
  MAX_DAILY_LOSS   Optional live paper daily loss guard in dollars.
  PROP_GUARD       1 to enable the prop-rule guard, 0 to disable.
  PROP_PROFILE     Prop profile name from config/backtest_config.py.
  PROP_PHASE       eval or funded. Funded mode requires saved research gates.
  PROP_DAILY_PROFIT_LOCK Optional prop daily profit lock in dollars.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --candidate)
            CANDIDATE="${2:-}"
            shift 2
            ;;
        --bars-csv)
            BARS_CSV="${2:-}"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            CANDIDATE="$1"
            shift
            ;;
    esac
done

cleanup() {
    local status="${1:-0}"
    echo ""
    echo "Shutting down..."
    [ -n "$TRADER_PID" ] && kill "$TRADER_PID" 2>/dev/null && echo "Trader stopped"
    [ -n "$COLLECTOR_PID" ] && kill "$COLLECTOR_PID" 2>/dev/null && echo "Collector stopped"
    exit "$status"
}
trap 'cleanup 130' INT TERM

echo "══════════════════════════════════════════════════════════════"
echo " NQ Live Paper Trading — Yahoo Finance Data"
echo "══════════════════════════════════════════════════════════════"
echo " Candidate: $CANDIDATE"
echo " Bar CSV:   $BARS_CSV"
echo " Warmup:    $WARMUP_ROWS rows"
echo " Stop file: $REPO_DIR/results/STOP_TRADING"
echo " Prop:      guard=$PROP_GUARD profile=$PROP_PROFILE phase=$PROP_PHASE"
echo ""

# Start the bar collector in the background.
echo ">> Starting bar collector (Yahoo Finance NQ=F) ..."
mkdir -p "$(dirname "$BARS_CSV")"
python3 "$REPO_DIR/scripts/fetch_live_bars.py" \
    --out "$BARS_CSV" \
    --poll-seconds 60 \
    --warmup-rows "$WARMUP_ROWS" \
    --debug &
COLLECTOR_PID=$!

# Give it time to fetch the initial warmup bars.
echo ">> Waiting for initial bar data (15s)..."
sleep 15

# Start the paper trader.
echo ">> Starting paper trader (tail mode) ..."
TRADER_ARGS=(
    "$REPO_DIR/scripts/run_amp_paper_trader.py"
    --candidate "$CANDIDATE" \
    --feed tail \
    --broker audit \
    --bar-file "$BARS_CSV" \
    --tail-from-start \
    --poll-seconds 1 \
    --warmup-bars "$WARMUP_ROWS" \
    --state-path "$REPO_DIR/results/live_paper_state_${CANDIDATE}.json" \
    --emergency-stop-file "$REPO_DIR/results/STOP_TRADING" \
    --heartbeat-seconds 60
)
if [[ "$PROP_GUARD" != "0" ]]; then
    TRADER_ARGS+=(
        --prop-guard
        --prop-profile "$PROP_PROFILE"
        --prop-phase "$PROP_PHASE"
    )
fi
if [[ -n "${STOP_AFTER_BARS:-}" ]]; then
    TRADER_ARGS+=(--stop-after-bars "$STOP_AFTER_BARS")
fi
if [[ -n "${MAX_DAILY_LOSS:-}" ]]; then
    TRADER_ARGS+=(--max-daily-loss "$MAX_DAILY_LOSS")
fi
if [[ -n "$PROP_DAILY_PROFIT_LOCK" ]]; then
    TRADER_ARGS+=(--prop-daily-profit-lock "$PROP_DAILY_PROFIT_LOCK")
fi

python3 "${TRADER_ARGS[@]}" &
TRADER_PID=$!

set +e
wait "$TRADER_PID"
TRADER_STATUS=$?
set -e
TRADER_PID=""
cleanup "$TRADER_STATUS"
