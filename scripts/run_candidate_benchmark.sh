#!/bin/bash
# Historical candidate launcher intentionally disabled while the validation
# queue is empty. Create a pre-candidate signal report and freeze one new
# candidate before re-enabling a benchmark command.

set -e

echo "No active validation candidate."
echo "Run scripts/run_signal_research_report.py on a prepared signal CSV before creating another benchmark."
exit 1
