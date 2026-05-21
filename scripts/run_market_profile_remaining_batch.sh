#!/usr/bin/env bash
set -u

if [[ "${ALLOW_BACKTEST_BATCH:-}" != "1" ]]; then
  echo "Refusing to run a broad historical candidate batch while the active validation queue is empty."
  echo "Set ALLOW_BACKTEST_BATCH=1 only for explicit reproduction work."
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 1

timestamp="$(date +%Y%m%d_%H%M%S)"
batch_dir="results/batches/market_profile_remaining_batch_${timestamp}"
mkdir -p "$batch_dir"

candidates=(
  "market_profile_cross_signal_probe"
  "market_profile_room_filter"
  "market_profile_target_probe"
)

summary_file="${batch_dir}/summary.txt"
run_labels_file="${batch_dir}/run_labels.txt"

{
  echo "Market-profile remaining batch"
  echo "Started: $(date)"
  echo "Root: ${ROOT_DIR}"
  echo "Candidates: ${candidates[*]}"
  echo
} | tee "$summary_file"

for candidate in "${candidates[@]}"; do
  log_file="${batch_dir}/${candidate}.log"
  echo "============================================================" | tee -a "$summary_file"
  echo "Starting candidate: ${candidate}" | tee -a "$summary_file"
  echo "Log: ${log_file}" | tee -a "$summary_file"
  echo "Started: $(date)" | tee -a "$summary_file"

  PYTHONUNBUFFERED=1 caffeinate -dimsu python3 -u main_backtest.py --candidate "$candidate" 2>&1 | tee "$log_file"
  status="${PIPESTATUS[0]}"

  latest_run=""
  if [[ -f results/latest.txt ]]; then
    latest_run="$(tr -d '\n' < results/latest.txt)"
  fi

  {
    echo "Finished: $(date)"
    echo "Exit status: ${status}"
    echo "Latest run label: ${latest_run}"
    echo
  } | tee -a "$summary_file"

  printf "%s,%s,%s\n" "$candidate" "$status" "$latest_run" >> "$run_labels_file"
done

{
  echo "============================================================"
  echo "Batch finished: $(date)"
  echo "Summary: ${summary_file}"
  echo "Run labels: ${run_labels_file}"
} | tee -a "$summary_file"
