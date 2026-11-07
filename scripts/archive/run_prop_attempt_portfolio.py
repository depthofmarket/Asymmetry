#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.prop_attempt_portfolio import export_prop_attempt_portfolio_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build multi-account prop attempt portfolio economics from saved prop-firm artifacts."
    )
    parser.add_argument("--run-dir", default=None, help="Saved run directory. Defaults to results/latest.txt.")
    parser.add_argument("--summary-csv", default=None, help="Explicit prop summary CSV. Overrides --run-dir discovery.")
    parser.add_argument(
        "--funded-simulations-csv",
        default=None,
        help="Optional funded simulations CSV. If omitted, the report uses average payout fields from the summary.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory. Defaults to <run-dir>/research/prop_attempt_portfolio or results/research_master/prop_attempt_portfolio.",
    )
    parser.add_argument("--artifact-name", default="prop_attempt_portfolio")
    parser.add_argument("--account-counts", default=None, help="Comma-separated account counts, e.g. 1,5,10,20,40.")
    parser.add_argument("--bankroll", type=float, default=None, help="Optional bankroll for portfolio-level Kelly account sizing.")
    parser.add_argument("--n-sims", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=17)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else _default_run_dir(required=False)
    summary_csv = Path(args.summary_csv) if args.summary_csv else _discover_summary_csv(run_dir)
    funded_csv = Path(args.funded_simulations_csv) if args.funded_simulations_csv else _discover_funded_csv(run_dir, summary_csv)
    if not summary_csv.exists():
        raise FileNotFoundError(f"prop summary CSV not found: {summary_csv}")

    out_dir = (
        Path(args.out_dir)
        if args.out_dir
        else (run_dir / "research" / "prop_attempt_portfolio" if run_dir else Path("results/research_master/prop_attempt_portfolio"))
    )
    summary = pd.read_csv(summary_csv)
    funded = pd.read_csv(funded_csv) if funded_csv is not None and funded_csv.exists() else pd.DataFrame()
    paths = export_prop_attempt_portfolio_report(
        summary,
        funded_simulations=funded,
        out_dir=out_dir,
        artifact_name=str(args.artifact_name),
        account_counts=_parse_counts(args.account_counts),
        bankroll=args.bankroll,
        n_sims=int(args.n_sims),
        seed=int(args.seed),
    )

    print(f"prop summary: {summary_csv}")
    print(f"funded simulations: {funded_csv if funded_csv is not None and funded_csv.exists() else 'not used'}")
    print(f"summary: {paths.summary_csv}")
    print(f"samples: {paths.samples_csv}")
    print(f"report: {paths.report_md}")
    return 0


def _default_run_dir(*, required: bool = True) -> Path | None:
    latest = Path("results/latest.txt")
    if not latest.exists():
        if required:
            raise FileNotFoundError("results/latest.txt is missing; pass --run-dir or --summary-csv")
        return None
    label = latest.read_text(encoding="utf-8").strip()
    if not label:
        if required:
            raise ValueError("results/latest.txt is empty; pass --run-dir or --summary-csv")
        return None
    return Path("results/runs") / label


def _discover_summary_csv(run_dir: Path | None) -> Path:
    if run_dir is None:
        raise FileNotFoundError("pass --summary-csv when results/latest.txt is unavailable")
    candidates = [
        run_dir / "research" / "walkforward" / "prop_firm" / "walkforward_stitched_summary.csv",
        run_dir / "research" / "prop_firm" / "prop_firm_summary.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _discover_funded_csv(run_dir: Path | None, summary_csv: Path) -> Path | None:
    sibling = summary_csv.with_name(summary_csv.name.replace("_summary.csv", "_funded_simulations.csv"))
    if sibling.exists():
        return sibling
    if run_dir is None:
        return None
    candidates = [
        run_dir / "research" / "prop_firm" / "prop_firm_funded_simulations.csv",
        run_dir / "research" / "walkforward" / "prop_firm" / "walkforward_stitched_funded_simulations.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _parse_counts(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    counts: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        counts.append(int(part))
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
