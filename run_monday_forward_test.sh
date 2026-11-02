#!/usr/bin/env bash
# ==============================================================================
# run_monday_forward_test.sh
# One-click Monday Morning Pre-Flight & Live Forward-Test Launcher
# Antiachismo Quant Research | LucidFlex 25K Evaluation Engine
# ==============================================================================

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "======================================================================"
echo "  INITIALIZING LUCIDFLEX 25K FORWARD-TEST LAUNCH CONTROL..."
echo "======================================================================"

# Check Python availability
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 could not be found. Please ensure Python 3 is installed."
    exit 1
fi

# Run pre-flight launcher script
exec python3 scripts/launch_monday_forward_test.py "$@"
