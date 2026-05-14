#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 1

timestamp="$(date +%Y%m%d_%H%M%S)"
batch_dir="results/batches/next_vp_candidates_${timestamp}"
mkdir -p "$batch_dir"

start_date="${START_DATE:-2021-01-01}"
end_date="${END_DATE:-}"

candidates=(
  "edge_vp_hf_gap_cusum_no_mr_long"
  "edge_vp_hf_gap_cusum_delay_1"
  "edge_vp_hf_gap_cusum_no_mr_long_delay_1"
  "edge_vp_hf_gap_cusum_trend_only"
  "edge_vp_hf_gap_cusum_trend_long_only"
  "edge_vp_scalp_frequency_gap_cusum_no_mr_long"
)

summary_file="${batch_dir}/summary.txt"
run_labels_file="${batch_dir}/run_labels.txt"

if command -v caffeinate >/dev/null 2>&1; then
  runner=(caffeinate -dimsu python3 -u main_backtest.py)
else
  runner=(python3 -u main_backtest.py)
fi

{
  echo "Next VP edge candidates batch"
  echo "Started: $(date)"
  echo "Root: ${ROOT_DIR}"
  echo "Candidates: ${candidates[*]}"
  echo "Start date: ${start_date}"
  if [[ -n "$end_date" ]]; then
    echo "End date: ${end_date}"
  fi
  echo "Runner: ${runner[*]}"
  echo
} | tee "$summary_file"

printf "candidate,status,run_label\n" > "$run_labels_file"

for candidate in "${candidates[@]}"; do
  log_file="${batch_dir}/${candidate}.log"
  echo "============================================================" | tee -a "$summary_file"
  echo "Starting candidate: ${candidate}" | tee -a "$summary_file"
  echo "Log: ${log_file}" | tee -a "$summary_file"
  echo "Started: $(date)" | tee -a "$summary_file"

  before_latest=""
  if [[ -f results/latest.txt ]]; then
    before_latest="$(tr -d '\n' < results/latest.txt)"
  fi

  args=(--candidate "$candidate")
  if [[ -n "$start_date" ]]; then
    args+=(--start "$start_date")
  fi
  if [[ -n "$end_date" ]]; then
    args+=(--end "$end_date")
  fi

  PYTHONUNBUFFERED=1 "${runner[@]}" "${args[@]}" 2>&1 | tee "$log_file"
  status="${PIPESTATUS[0]}"

  latest_run=""
  if [[ -f results/latest.txt ]]; then
    latest_run="$(tr -d '\n' < results/latest.txt)"
  fi

  if [[ "$latest_run" == "$before_latest" && "$status" -ne 0 ]]; then
    latest_run=""
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
