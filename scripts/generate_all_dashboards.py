#!/usr/bin/env python3
"""
Master Dashboard Generation Suite.
Regenerates both:
1. Multi-Strategy Quantitative Performance Dashboard (results/strategy_dashboard/)
2. Prop Firm Mode Simulator Dashboard (results/prop_firm_dashboard/)
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

def run_script(script_path: Path):
    print("=" * 80)
    print(f"  RUNNING: {script_path.name}")
    print("=" * 80)
    res = subprocess.run([sys.executable, str(script_path)], cwd=str(REPO_ROOT))
    if res.returncode != 0:
        print(f"ERROR: {script_path.name} failed with return code {res.returncode}")
        sys.exit(res.returncode)
    print()

def main():
    run_script(REPO_ROOT / "scripts/generate_quant_strategy_dashboard.py")
    run_script(REPO_ROOT / "scripts/generate_rational_edge_prop_dashboard.py")
    print("=" * 80)
    print("  ALL DASHBOARDS SUCCESSFULLY GENERATED & PARITY-VERIFIED")
    print("=" * 80)
    print(f"  1. Normal Quant Dashboard: file://{REPO_ROOT}/results/strategy_dashboard/dashboard.html")
    print(f"  2. Prop Firm Dashboard:    file://{REPO_ROOT}/results/prop_firm_dashboard/dashboard.html")
    print(f"  3. Demo Parity Journal:    file://{REPO_ROOT}/results/forward_test/demo_parity_dashboard.html")
    print("=" * 80)

if __name__ == "__main__":
    main()
