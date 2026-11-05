#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# sync_wiki.sh — Shell entry point for Karpathy LLM Wiki synchronization
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN=""

if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
else
    echo "ERROR: Python 3 executable not found in PATH or virtual environment." >&2
    exit 1
fi

WIKI_SYNC_SCRIPT="$REPO_DIR/scripts/wiki_sync.py"

if [[ ! -f "$WIKI_SYNC_SCRIPT" ]]; then
    echo "ERROR: Synchronization engine not found at $WIKI_SYNC_SCRIPT" >&2
    exit 1
fi

cd "$REPO_DIR"
exec "$PYTHON_BIN" "$WIKI_SYNC_SCRIPT" "$@"
