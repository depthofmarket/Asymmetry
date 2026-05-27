from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DEFAULT_ACCOUNT_COUNTS = (1, 5, 10, 20, 40)


@dataclass(frozen=True)
class PropAttemptPortfolioPaths:
    summary_csv: Path
    samples_csv: Path
    report_md: Path


def export_prop_attempt_portfolio_report(
    summary: pd.DataFrame,
    *,
    out_dir: Path | str,
    artifact_name: str = "prop_attempt_portfolio",
    funded_simulations: pd.DataFrame | None = None,
    account_counts: Iterable[int] | None = None,
    bankroll: float | None = None,
    n_sims: int = 20_000,
    seed: int = 17,
) -> PropAttemptPortfolioPaths:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    portfolio_summary, samples = build_prop_attempt_portfolio(
        summary,
        funded_simulations=funded_simulations,
        account_counts=account_counts,
        bankroll=bankroll,
        n_sims=n_sims,
        seed=seed,
    )

    paths = PropAttemptPortfolioPaths(
        summary_csv=out_path / f"{artifact_name}_summary.csv",
        samples_csv=out_path / f"{artifact_name}_samples.csv",
        report_md=out_path / f"{artifact_name}.md",
    )
    portfolio_summary.to_csv(paths.summary_csv, index=False)
    samples.to_csv(paths.samples_csv, index=False)
    paths.report_md.write_text(
        render_prop_attempt_portfolio_markdown(portfolio_summary),
        encoding="utf-8",
    )
    return paths


def build_prop_attempt_portfolio(
    summary: pd.DataFrame,
    *,
    funded_simulations: pd.DataFrame | None = None,
    account_counts: Iterable[int] | None = None,
    bankroll: float | None = None,
    n_sims: int = 20_000,
    seed: int = 17,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if summary.empty:
        return pd.DataFrame(), pd.DataFrame()

    rng = np.random.default_rng(int(seed))
    funded = funded_simulations.copy() if funded_simulations is not None else pd.DataFrame()
    rows: list[dict[str, object]] = []
    sample_frames: list[pd.DataFrame] = []
    global_counts = _parse_account_counts(account_counts)

    for profile_idx, (_, raw_row) in enumerate(summary.iterrows()):
        row = raw_row.to_dict()
        profile = str(row.get("profile", f"profile_{profile_idx}"))
        counts = global_counts or _parse_account_counts(row.get("portfolio_account_counts")) or list(DEFAULT_ACCOUNT_COUNTS)
        max_accounts = max(1, _safe_int(row.get("max_accounts"), max(counts)))
        counts = [count for count in sorted(set(counts)) if count > 0]
        profile_funded = _profile_funded_frame(funded, profile)
        profile_rng = np.random.default_rng(int(rng.integers(0, 2**32 - 1)))

        for requested_accounts in counts:
            accounts = min(int(requested_accounts), int(max_accounts))
            scenario = _simulate_portfolio_scenario(
                row,
                profile_funded,
                account_count=accounts,
                requested_account_count=int(requested_accounts),
                bankroll=bankroll,
                n_sims=int(n_sims),
                rng=profile_rng,
            )
            samples = scenario.pop("_samples")
            rows.append(scenario)
            sample_frames.append(samples)

    portfolio_summary = pd.DataFrame(rows)
    if not portfolio_summary.empty:
        portfolio_summary["balanced_ev_score"] = (
            pd.to_numeric(portfolio_summary["expected_net_value"], errors="coerce")
            - pd.to_numeric(portfolio_summary["p05_net_value"], errors="coerce").clip(upper=0.0).abs() * 0.25
        )
        portfolio_summary["rank_balanced_ev"] = (
            portfolio_summary["balanced_ev_score"].rank(method="dense", ascending=False).astype(int)
        )
        portfolio_summary = portfolio_summary.sort_values(
            ["rank_balanced_ev", "profile", "account_count"],
            kind="stable",
        ).reset_index(drop=True)
    samples_df = pd.concat(sample_frames, ignore_index=True) if sample_frames else pd.DataFrame()
    return portfolio_summary, samples_df


def render_prop_attempt_portfolio_markdown(summary: pd.DataFrame) -> str:
    lines = [
        "# Prop Attempt Portfolio",
        "",
        "This report converts saved prop-firm summary artifacts into multi-account attempt economics. It does not run a backtest.",
        "",
        "The objective is attempt-level expected value: capped fees and resets on the downside, activation costs after passes, and payout distributions on the upside.",
        "",
    ]
    if summary.empty:
        lines.append("No portfolio rows were generated.")
        return "\n".join(lines) + "\n"

    display_cols = [
        "rank_balanced_ev",
        "profile",
        "trading_objective",
        "fill_model",
        "account_count",
        "expected_net_value",
        "median_net_value",
        "p05_net_value",
        "kelly_fraction_pct",
        "kelly_active_accounts",
        "kelly_account_gap",
        "probability_recover_all_costs_pct",
        "probability_at_least_one_payout_pct",
        "expected_total_cost",
        "expected_total_payout",
        "expected_passed_accounts",
        "expected_payout_accounts",
        "balanced_ev_score",
        "sample_size_warning",
    ]
    lines.extend(
        [
            "## Portfolio Comparison",
            "",
            summary.loc[:, [col for col in display_cols if col in summary.columns]].to_string(index=False),
            "",
            "## Guardrails",
            "",
            "- `prop_demo_fill_assumption` and `tbbo_realistic_fill_assumption` must stay separate; a prop-demo positive EV row is not live-edge evidence.",
            "- `trading_objective=prop_eval_flip` means fast resolution is the goal. It should not be promoted as a durable live strategy objective.",
            "- `sample_size_warning` means sizing and portfolio EV are unstable until more trades or forward evidence exist.",
            "- `rank_balanced_ev` penalizes weak downside tails; it is a triage score, not validation.",
        ]
    )
    return "\n".join(lines) + "\n"


def _simulate_portfolio_scenario(
    row: dict[str, object],
    funded: pd.DataFrame,
    *,
    account_count: int,
    requested_account_count: int,
    bankroll: float | None,
    n_sims: int,
    rng: np.random.Generator,
) -> dict[str, object]:
    profile = str(row.get("profile", "profile"))
    pass_probability = _pct(row.get("pass_probability_pct"))
    eval_cost = _safe_float(row.get("eval_cost"), 0.0)
    activation_fee = _safe_float(row.get("activation_fee"), 0.0)
    reset_fee = _safe_float(row.get("reset_fee"), 0.0)
    monthly_fee = _safe_float(row.get("monthly_fee"), 0.0)
    bundle_cost = _safe_float(row.get("account_bundle_cost"), 0.0)
    max_resets = max(0, _safe_int(row.get("max_resets_per_account"), 0))
    max_attempts = max(1, 1 + max_resets)
    kelly = _kelly_metrics(
        row,
        funded,
        pass_probability=pass_probability,
        cost_basis=eval_cost + monthly_fee + pass_probability * activation_fee,
        bankroll=bankroll,
    )

    passes_by_attempt = rng.random((n_sims, account_count, max_attempts)) < pass_probability
    has_pass = passes_by_attempt.any(axis=2)
    first_pass_idx = passes_by_attempt.argmax(axis=2)
    attempts_used = np.where(has_pass, first_pass_idx + 1, max_attempts)
    reset_attempts = attempts_used - 1
    passed_accounts = has_pass.sum(axis=1)
    reset_attempt_count = reset_attempts.sum(axis=1)

    payout_matrix = _sample_payout_matrix(
        rng,
        funded,
        row,
        shape=(n_sims, account_count),
    )
    payout_matrix = np.where(has_pass, payout_matrix, 0.0)
    payout_accounts = (payout_matrix > 0.0).sum(axis=1)
    total_payout = payout_matrix.sum(axis=1)
    total_cost = (
        account_count * (eval_cost + monthly_fee)
        + reset_attempt_count * reset_fee
        + passed_accounts * activation_fee
        + bundle_cost
    )
    net_value = total_payout - total_cost
    samples = pd.DataFrame(
        {
            "profile": profile,
            "sim_id": np.arange(n_sims, dtype=int),
            "requested_account_count": int(requested_account_count),
            "account_count": int(account_count),
            "attempts_per_account_cap": int(max_attempts),
            "passed_accounts": passed_accounts.astype(int),
            "payout_accounts": payout_accounts.astype(int),
            "reset_attempts": reset_attempt_count.astype(int),
            "attempts_used": attempts_used.sum(axis=1).astype(int),
            "total_cost": total_cost.astype(float),
            "total_payout": total_payout.astype(float),
            "net_value": net_value.astype(float),
            "recovered_all_costs": net_value >= 0.0,
        }
    )

    expected_cost = float(total_cost.mean())
    expected_net = float(net_value.mean())
    return {
        "profile": profile,
        "sample_scope": str(row.get("sample_scope", "")),
        "evidence_grade": str(row.get("evidence_grade", "")),
        "trading_objective": str(row.get("trading_objective", "prop_eval_flip")),
        "fill_model": str(row.get("fill_model", "prop_demo_fill_assumption")),
        "requested_account_count": int(requested_account_count),
        "account_count": int(account_count),
        "max_accounts": _safe_int(row.get("max_accounts"), account_count),
        "attempts_per_account_cap": int(max_attempts),
        "eval_cost": eval_cost,
        "activation_fee": activation_fee,
        "reset_fee": reset_fee,
        "monthly_fee": monthly_fee,
        "account_bundle_cost": bundle_cost,
        "expected_total_cost": expected_cost,
        "expected_total_payout": float(total_payout.mean()),
        "expected_net_value": expected_net,
        "median_net_value": float(np.median(net_value)),
        "p05_net_value": float(np.quantile(net_value, 0.05)),
        "p95_net_value": float(np.quantile(net_value, 0.95)),
        "expected_roi_pct": float(expected_net / expected_cost * 100.0) if expected_cost > 0 else np.nan,
        **kelly,
        "kelly_account_gap": (
            int(account_count - kelly["kelly_active_accounts"])
            if pd.notna(kelly["kelly_active_accounts"])
            else np.nan
        ),
        "probability_at_least_one_pass_pct": float((passed_accounts > 0).mean() * 100.0),
        "probability_at_least_one_payout_pct": float((payout_accounts > 0).mean() * 100.0),
        "probability_recover_all_costs_pct": float((net_value >= 0.0).mean() * 100.0),
        "expected_passed_accounts": float(passed_accounts.mean()),
        "expected_payout_accounts": float(payout_accounts.mean()),
        "expected_reset_attempts": float(reset_attempt_count.mean()),
        "expected_attempts_used": float(attempts_used.sum(axis=1).mean()),
        "trade_sample_size": _safe_int(row.get("trade_sample_size"), 0),
        "minimum_trade_sample": _safe_int(row.get("minimum_trade_sample"), 0),
        "sample_size_warning": str(row.get("sample_size_warning", "")),
        "_samples": samples,
    }


def _sample_payout_matrix(
    rng: np.random.Generator,
    funded: pd.DataFrame,
    row: dict[str, object],
    *,
    shape: tuple[int, int],
) -> np.ndarray:
    payout_cap = _safe_float(row.get("payout_cap"), 0.0)
    if not funded.empty and "net_payout" in funded.columns:
        values = pd.to_numeric(funded["net_payout"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        if values.size:
            sampled = rng.choice(values, size=shape, replace=True)
        else:
            sampled = np.zeros(shape, dtype=float)
    else:
        first_payout_probability = _pct(row.get("first_payout_probability_pct"))
        avg_payout = _safe_float(row.get("avg_net_payout_after_split"), 0.0)
        sampled = np.where(rng.random(shape) < first_payout_probability, avg_payout, 0.0)
    if payout_cap > 0:
        sampled = np.minimum(sampled, payout_cap)
    return np.maximum(sampled, 0.0)


def _kelly_metrics(
    row: dict[str, object],
    funded: pd.DataFrame,
    *,
    pass_probability: float,
    cost_basis: float,
    bankroll: float | None,
) -> dict[str, object]:
    payout_probability = _pct(row.get("probability_eval_to_first_payout_pct"))
    if payout_probability <= 0:
        payout_probability = pass_probability * _pct(row.get("first_payout_probability_pct"))
    payout_when_positive = _conditional_payout(row, funded)
    payoff_ratio = payout_when_positive / cost_basis if cost_basis > 0 else np.nan
    if np.isfinite(payoff_ratio) and payoff_ratio > 0:
        break_even_probability = 1.0 / payoff_ratio
        kelly_fraction = (payoff_ratio * payout_probability - (1.0 - payout_probability)) / payoff_ratio
        kelly_fraction = max(0.0, min(float(kelly_fraction), 1.0))
    else:
        break_even_probability = np.nan
        kelly_fraction = np.nan

    bankroll_value = _safe_float(bankroll, np.nan) if bankroll is not None else np.nan
    kelly_capital = bankroll_value * kelly_fraction if np.isfinite(bankroll_value) and np.isfinite(kelly_fraction) else np.nan
    kelly_accounts = (
        int(np.floor(kelly_capital / cost_basis))
        if np.isfinite(kelly_capital) and cost_basis > 0
        else np.nan
    )
    return {
        "kelly_cost_basis": float(cost_basis) if np.isfinite(cost_basis) else np.nan,
        "kelly_payout_probability_pct": float(payout_probability * 100.0),
        "kelly_payout_when_positive": float(payout_when_positive)
        if np.isfinite(payout_when_positive)
        else np.nan,
        "kelly_payoff_ratio": float(payoff_ratio) if np.isfinite(payoff_ratio) else np.nan,
        "kelly_break_even_probability_pct": float(break_even_probability * 100.0)
        if np.isfinite(break_even_probability)
        else np.nan,
        "kelly_fraction_pct": float(kelly_fraction * 100.0) if np.isfinite(kelly_fraction) else np.nan,
        "kelly_bankroll": float(bankroll_value) if np.isfinite(bankroll_value) else np.nan,
        "kelly_capital_deployed": float(kelly_capital) if np.isfinite(kelly_capital) else np.nan,
        "kelly_active_accounts": kelly_accounts,
    }


def _conditional_payout(row: dict[str, object], funded: pd.DataFrame) -> float:
    if not funded.empty and "net_payout" in funded.columns:
        payouts = pd.to_numeric(funded["net_payout"], errors="coerce").dropna()
        payouts = payouts.loc[payouts > 0.0]
        if not payouts.empty:
            return float(payouts.mean())
    explicit = _safe_float(row.get("avg_net_payout_when_positive"), np.nan)
    if np.isfinite(explicit) and explicit > 0:
        return explicit
    avg_payout = _safe_float(row.get("avg_net_payout_after_split"), 0.0)
    first_payout_probability = _pct(row.get("first_payout_probability_pct"))
    if avg_payout > 0 and first_payout_probability > 0:
        return avg_payout / first_payout_probability
    return avg_payout


def _profile_funded_frame(funded: pd.DataFrame, profile: str) -> pd.DataFrame:
    if funded.empty or "profile" not in funded.columns:
        return funded.copy()
    return funded.loc[funded["profile"].astype(str).eq(str(profile))].copy()


def _parse_account_counts(raw: object | None) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.replace(";", ",").split(",")]
    else:
        try:
            parts = list(raw)  # type: ignore[arg-type]
        except TypeError:
            parts = [raw]
    counts: list[int] = []
    for part in parts:
        if part is None:
            continue
        text = str(part).strip()
        if not text:
            continue
        try:
            value = int(float(text))
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in counts:
            counts.append(value)
    return counts


def _pct(raw: object) -> float:
    value = _safe_float(raw, 0.0)
    if value > 1.0:
        value /= 100.0
    return min(max(value, 0.0), 1.0)


def _safe_float(raw: object, default: float = 0.0) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(value):
        return default
    return value


def _safe_int(raw: object, default: int = 0) -> int:
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return default
    return value
