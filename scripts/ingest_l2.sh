#!/bin/bash
# L2 Parquet Quick Ingest Wrapper
# Usage: ./ingest_l2.sh --download-dir ~/Downloads/l2_data [--no-move] [--no-audit]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/ingest_l2_parquet_5year.py"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

usage() {
    cat <<EOF
L2 Parquet Quick Ingest Wrapper

Usage: $0 [OPTIONS]

Options:
  --download-dir DIR     Directory containing L2 zip files (required unless --help)
  --archive-root DIR     Where to organize (default: data/raw/l2_nq/zip_archives)
  --start-year YEAR      First year (default: 2021)
  --end-year YEAR        Last year (default: 2026)
  --no-move              Dry-run only, don't move archives
  --no-audit             Skip parquet audit
  --audit-files N        Files to sample in audit (default: 10)
  --audit-rows N         Rows per file in audit (default: 2000)
  --help                 Show this message

Examples:
  $0 --download-dir ~/Downloads/l2_data
  $0 --download-dir ~/Downloads/l2_data --no-move
  $0 --download-dir ~/tmp/l2 --archive-root /mnt/data/l2_archives --start-year 2020

EOF
    exit 0
}

# Parse arguments
DOWNLOAD_DIR=""
ARCHIVE_ROOT="data/raw/l2_nq/zip_archives"
START_YEAR="2021"
END_YEAR="2026"
NO_MOVE=""
NO_AUDIT=""
AUDIT_FILES="10"
AUDIT_ROWS="2000"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --download-dir)
            DOWNLOAD_DIR="$2"
            shift 2
            ;;
        --archive-root)
            ARCHIVE_ROOT="$2"
            shift 2
            ;;
        --start-year)
            START_YEAR="$2"
            shift 2
            ;;
        --end-year)
            END_YEAR="$2"
            shift 2
            ;;
        --no-move)
            NO_MOVE="--no-move"
            shift
            ;;
        --no-audit)
            NO_AUDIT="--no-audit"
            shift
            ;;
        --audit-files)
            AUDIT_FILES="$2"
            shift 2
            ;;
        --audit-rows)
            AUDIT_ROWS="$2"
            shift 2
            ;;
        --help)
            usage
            ;;
        *)
            print_error "Unknown option: $1"
            usage
            ;;
    esac
done

if [[ -z "$DOWNLOAD_DIR" ]]; then
    print_error "Missing required argument: --download-dir"
    echo ""
    usage
fi

# Validate Python script exists
if [[ ! -f "$SCRIPT" ]]; then
    print_error "Ingest script not found: $SCRIPT"
    exit 1
fi

print_header "L2 Parquet 5-Year Ingest"
echo "Repo root:       ${REPO_ROOT}"
echo "Download dir:    ${DOWNLOAD_DIR}"
echo "Archive root:    ${ARCHIVE_ROOT}"
echo "Year range:      ${START_YEAR}-${END_YEAR}"
echo "Dry-run:         ${NO_MOVE:-false}"
echo "Skip audit:      ${NO_AUDIT:-false}"
echo ""

# Run the Python coordinator
cd "$REPO_ROOT"
exec python3 "$SCRIPT" \
    --download-dir "$DOWNLOAD_DIR" \
    --archive-root "$ARCHIVE_ROOT" \
    --start-year "$START_YEAR" \
    --end-year "$END_YEAR" \
    --audit-files "$AUDIT_FILES" \
    --audit-rows "$AUDIT_ROWS" \
    ${NO_MOVE} \
    ${NO_AUDIT}
