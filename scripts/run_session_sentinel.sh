#!/bin/bash
# Wrapper to execute the Session Sentinel for a given mode
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:-all}"
python scripts/session_sentinel.py --mode "$MODE"
