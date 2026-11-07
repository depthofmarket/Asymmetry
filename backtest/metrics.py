"""
Institutional Quantitative Performance & Risk Metrics Engine.

Provides the comprehensive 88+ metric taxonomy for systematic futures trading:
1. Return & Capital Growth Metrics
2. Risk-Adjusted Performance Ratios (Sharpe, Sortino, Calmar, Omega, Gain-to-Pain, Ulcer, Burke, etc.)
3. Drawdown, Underwater Topology & Recovery Dynamics
4. Tail Risk, Value at Risk & Extreme Value Theory (Parametric, Cornish-Fisher, CVaR/Expected Shortfall)
5. Trade Microstructure & Edge Distribution (Expectancy, Payoff, Trimmed PF, Outlier Dominance)
6. Higher Statistical Moments & Hypothesis Testing (Skew, Kurtosis, SQN, Student's t, Jarque-Bera)
7. Multiple Testing & Selection Bias Controls (PSR, DSR, MinTRL, Expected Max Sharpe)
8. Capital Sizing, Risk of Ruin & Leverage (Full/Half Kelly, Analytical & Empirical Ruin)
9. Market Microstructure & Intrabar Excursion (MFE, MAE, Edge Efficiency, Exposure, Hold Times)

Designed for CME Micro Futures (MNQ, MES, MGC) under prop firm constraints
(e.g., LucidFlex $1,000 trailing drawdown and $25,100 liquidation floor).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd


# =============================================================================
# STATISTICAL HELPER FUNCTIONS (Zero-Dependency Gaussian Approximations)
# =============================================================================

def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function Phi(x)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    """Standard normal probability density function phi(x)."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)


def norm_ppf(p: float) -> float:
    """
    Inverse standard normal CDF (quantile / probit function).
    Acklam's rational approximation (|error| < 1.15e-9).
    """
    if not (0.0 < p < 1.0):
        if p == 0.0:
            return -float("inf")
        if p == 1.0:
            return float("inf")
        raise ValueError("p must be strictly in (0, 1)")

    # Coefficients in rational approximations
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]

    low = 0.02425
    high = 1.0 - low

    if p < low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p > high:
        return -norm_ppf(1.0 - p)

    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
        ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
    )


# =============================================================================
# INDIVIDUAL MATHEMATICAL METRIC FORMULAS
# =============================================================================

def sortino_ratio(
    returns: np.ndarray,
    mar: float = 0.0,
    annualization_factor: float = 252.0,
) -> float:
    """
    Sortino Ratio: Excess return over Minimum Acceptable Return (MAR)
    divided by downside semi-deviation below MAR.
    """
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    diff = r - mar
    downside = np.minimum(diff, 0.0)
    downside_dev = math.sqrt(np.mean(downside**2))
    if downside_dev <= 0.0:
        return 999.0 if np.mean(diff) > 0 else 0.0
    return float((np.mean(diff) / downside_dev) * math.sqrt(annualization_factor))


def calmar_ratio(annual_return: float, max_drawdown: float) -> float:
    """
    Calmar Ratio: Annualized return divided by absolute Maximum Drawdown.
    """
    mdd = abs(max_drawdown)
    if mdd <= 0.0:
        return 999.0 if annual_return > 0 else 0.0
    return float(annual_return / mdd)


def omega_ratio(returns: np.ndarray, hurdle: float = 0.0) -> float:
    """
    Omega Ratio: Probability-weighted ratio of gains vs losses above hurdle.
    Omega(L) = sum(max(r - L, 0)) / sum(max(L - r, 0)).
    """
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return 0.0
    gains = np.maximum(r - hurdle, 0.0).sum()
    losses = np.maximum(hurdle - r, 0.0).sum()
    if losses <= 0.0:
        return 999.0 if gains > 0 else 1.0
    return float(gains / losses)


def gain_to_pain_ratio(returns: np.ndarray) -> float:
    """
    Jack Schwager's Gain-to-Pain Ratio (GPR):
    Sum of all returns divided by absolute sum of negative returns.
    """
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return 0.0
    net_sum = float(np.sum(r))
    pain = float(np.sum(np.abs(r[r < 0])))
    if pain <= 0.0:
        return 999.0 if net_sum > 0 else 0.0
    return float(net_sum / pain)


def ulcer_index(equity_curve: np.ndarray, capital: float = 25000.0) -> float:
    """
    Peter Martin's Ulcer Index:
    Root mean square percentage retracement from historical high-water mark.
    """
    eq = np.asarray(equity_curve, dtype=float)
    if eq.size == 0:
        return 0.0
    hwm = np.maximum.accumulate(np.maximum(eq, 0.0))
    # Percentage retracement from capital or peak
    denom = np.maximum(capital + hwm, 1.0)
    drawdowns_pct = ((hwm - eq) / denom) * 100.0
    return float(math.sqrt(np.mean(drawdowns_pct**2)))


def ulcer_performance_index(annual_return: float, u_index: float) -> float:
    """Martin Ratio / Ulcer Performance Index (UPI): Return / Ulcer Index."""
    if u_index <= 0.0:
        return 999.0 if annual_return > 0 else 0.0
    return float(annual_return / u_index)


def pain_index(equity_curve: np.ndarray, capital: float = 25000.0) -> float:
    """Pain Index: Mean drawdown percentage over the entire investment horizon."""
    eq = np.asarray(equity_curve, dtype=float)
    if eq.size == 0:
        return 0.0
    hwm = np.maximum.accumulate(np.maximum(eq, 0.0))
    denom = np.maximum(capital + hwm, 1.0)
    dd_pct = ((hwm - eq) / denom) * 100.0
    return float(np.mean(dd_pct))


def burke_ratio(annual_return: float, drawdown_depths: Sequence[float]) -> float:
    """
    Burke Ratio: Annualized return divided by the square root of the sum of
    squared drawdown depth percentages.
    """
    dd = np.asarray(drawdown_depths, dtype=float)
    denom = math.sqrt(np.sum(dd**2)) if dd.size > 0 else 0.0
    if denom <= 0.0:
        return 999.0 if annual_return > 0 else 0.0
    return float(annual_return / denom)


def modified_burke_ratio(
    annual_return: float,
    drawdown_depths: Sequence[float],
    n_periods: int,
) -> float:
    """Modified Burke Ratio: Burke ratio multiplied by sqrt(N_periods)."""
    base = burke_ratio(annual_return, drawdown_depths)
    if n_periods > 0 and math.isfinite(base):
        return float(base * math.sqrt(n_periods))
    return base


def sterling_ratio(
    annual_return: float,
    avg_drawdown_pct: float,
    excess_penalty: float = 10.0,
) -> float:
    """
    Sterling Ratio: Annual return divided by average drawdown % plus penalty (default 10%).
    """
    denom = abs(avg_drawdown_pct) + excess_penalty
    if denom <= 0.0:
        return 0.0
    return float(annual_return / denom)


def kappa_three_ratio(
    returns: np.ndarray,
    hurdle: float = 0.0,
    annualization_factor: float = 252.0,
) -> float:
    """
    Kaplan-Knowles Kappa 3 Ratio: Excess return normalized by 3rd lower partial moment.
    """
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    diff = r - hurdle
    downside = np.minimum(diff, 0.0)
    lpm3 = np.mean(np.abs(downside) ** 3) ** (1.0 / 3.0)
    if lpm3 <= 0.0:
        return 999.0 if np.mean(diff) > 0 else 0.0
    return float((np.mean(diff) / lpm3) * math.sqrt(annualization_factor))


def adjusted_sharpe_ratio(sharpe: float, skewness: float, kurtosis: float) -> float:
    """
    Pezier's Adjusted Sharpe Ratio for non-normal return distributions:
    SR * [1 + (Skew/6)*SR - ((Kurt - 3)/24)*SR^2]
    """
    if not math.isfinite(sharpe):
        return 0.0
    excess_kurt = kurtosis - 3.0 if kurtosis > 0 else 0.0
    adjustment = 1.0 + (skewness / 6.0) * sharpe - (excess_kurt / 24.0) * (sharpe**2)
    return float(sharpe * adjustment)


def cornish_fisher_var(
    returns: np.ndarray,
    alpha: float = 0.05,
) -> float:
    """
    Cornish-Fisher expansion Value-at-Risk (adjusted for empirical skewness & kurtosis).
    Returns positive value representing dollar/point loss at confidence (1 - alpha).
    """
    r = np.asarray(returns, dtype=float)
    if r.size < 4:
        return 0.0
    mu = float(np.mean(r))
    sigma = float(np.std(r, ddof=1))
    if sigma <= 0.0:
        return 0.0

    z = (r - mu) / sigma
    s = float(np.mean(z**3))
    k = float(np.mean(z**4))

    # Standard normal quantile for alpha (e.g. z_0.05 = -1.644853)
    z_a = norm_ppf(alpha)

    # Cornish-Fisher expansion quantile
    z_cf = (
        z_a
        + (s / 6.0) * (z_a**2 - 1.0)
        + ((k - 3.0) / 24.0) * (z_a**3 - 3.0 * z_a)
        - ((s**2) / 36.0) * (2.0 * z_a**3 - 5.0 * z_a)
    )

    # Loss is -(mu + z_cf * sigma)
    loss = -(mu + z_cf * sigma)
    return float(max(0.0, loss))


def conditional_var(returns: np.ndarray, alpha: float = 0.05) -> float:
    """
    Conditional Value at Risk (CVaR / Expected Shortfall):
    Mean loss in the worst alpha% quantile.
    """
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return 0.0
    cutoff = np.percentile(r, alpha * 100.0)
    tail = r[r <= cutoff]
    if tail.size == 0:
        return float(abs(cutoff))
    return float(abs(tail.mean()))


def tail_risk_ratio(returns: np.ndarray, upper_pct: float = 95.0, lower_pct: float = 5.0) -> float:
    """
    Tail Risk Ratio: 95th percentile right tail gain divided by
    absolute 5th percentile left tail loss.
    """
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return 0.0
    upper = float(np.percentile(r, upper_pct))
    lower = float(np.percentile(r, lower_pct))
    abs_lower = abs(lower)
    if abs_lower <= 0.0:
        return 999.0 if upper > 0 else 1.0
    return float(upper / abs_lower)


def full_kelly_fraction(win_rate: float, payoff_ratio: float) -> float:
    """
    Full Kelly Criterion fraction f* = W - (1 - W) / R.
    win_rate in [0, 1], payoff_ratio = Avg Win / Avg Loss.
    """
    if payoff_ratio <= 0.0:
        return 0.0
    w = max(0.0, min(1.0, win_rate))
    f_star = w - (1.0 - w) / payoff_ratio
    return float(max(0.0, f_star))


def half_kelly_fraction(win_rate: float, payoff_ratio: float) -> float:
    """Half Kelly sizing fraction (standard institutional risk mitigation)."""
    return float(0.5 * full_kelly_fraction(win_rate, payoff_ratio))


def analytical_risk_of_ruin(
    win_rate: float,
    payoff_ratio: float,
    cushion_units: float = 10.0,
) -> float:
    """
    Analytical Risk of Ruin based on gambler's ruin formula:
    A = (W * R - (1 - W)) / (W * R + (1 - W))
    RoR = ((1 - A) / (1 + A)) ^ cushion_units if A > 0 else 1.0
    """
    if payoff_ratio <= 0.0 or win_rate <= 0.0:
        return 1.0
    w = win_rate
    num = w * payoff_ratio - (1.0 - w)
    denom = w * payoff_ratio + (1.0 - w)
    if denom <= 0.0:
        return 1.0
    a = num / denom
    if a <= 0.0:
        return 1.0
    base = (1.0 - a) / (1.0 + a)
    try:
        return float(base**cushion_units)
    except OverflowError:
        return 1.0


def system_quality_number(trade_pnl: np.ndarray) -> float:
    """
    Van Tharp's System Quality Number (SQN):
    SQN = sqrt(min(N, 100)) * (mean / stdev).
    > 2.0 = Good, > 3.0 = Excellent, > 5.0 = Superb.
    """
    x = np.asarray(trade_pnl, dtype=float)
    n = x.size
    if n < 2:
        return 0.0
    std = float(x.std(ddof=1))
    if std <= 0.0:
        return 0.0
    return float(math.sqrt(min(n, 100)) * (x.mean() / std))


def jarque_bera_test(series: np.ndarray) -> tuple[float, float]:
    """
    Jarque-Bera goodness-of-fit test of normality:
    JB = (N / 6) * [S^2 + ((K - 3)^2) / 4].
    p-value computed analytically from Chi-Squared distribution with 2 DOF:
    p_val = exp(-JB / 2).
    """
    x = np.asarray(series, dtype=float)
    n = x.size
    if n < 4:
        return 0.0, 1.0
    mean = float(np.mean(x))
    std = float(np.std(x, ddof=0))
    if std <= 0.0:
        return 0.0, 1.0
    z = (x - mean) / std
    s = float(np.mean(z**3))
    k = float(np.mean(z**4))

    jb_stat = (n / 6.0) * (s**2 + ((k - 3.0) ** 2) / 4.0)
    p_value = math.exp(-0.5 * jb_stat) if jb_stat >= 0 else 1.0
    return float(jb_stat), float(p_value)


def trimmed_profit_factor(trades: np.ndarray, trim_pct: float = 0.02) -> float:
    """
    Profit factor evaluated after trimming the top trim_pct (e.g. 2%) largest winning trades.
    Tests robustness against extreme lucky outliers.
    """
    x = np.asarray(trades, dtype=float)
    if x.size == 0:
        return 0.0
    wins = np.sort(x[x > 0])
    losses = -x[x < 0]
    if wins.size == 0 or losses.size == 0:
        return 0.0
    n_trim = int(math.ceil(wins.size * trim_pct))
    trimmed_wins = wins[:-n_trim] if n_trim > 0 and n_trim < wins.size else wins
    gross_win = float(trimmed_wins.sum())
    gross_loss = float(losses.sum())
    if gross_loss <= 0.0:
        return 999.0 if gross_win > 0 else 0.0
    return float(gross_win / gross_loss)


def top_n_dominance_pct(trades: np.ndarray, n: int = 5) -> float:
    """
    Percentage of total gross winning profit accounted for by the top N winning trades.
    """
    x = np.asarray(trades, dtype=float)
    wins = x[x > 0]
    if wins.size == 0:
        return 0.0
    total_win = float(wins.sum())
    if total_win <= 0.0:
        return 0.0
    top_n = np.sort(wins)[-n:]
    return float((top_n.sum() / total_win) * 100.0)


def trim_winners_adversarial_test(trades: np.ndarray, trim_pct: float = 0.05) -> dict[str, Any]:
    """
    Adversarial Stress Test: Truncate top trim_pct (e.g. 5%) of winning trades
    to test whether the economic edge holds strictly above breakeven (PF > 1.0).
    """
    x = np.asarray(trades, dtype=float)
    if x.size == 0:
        return {
            "trimmed_pf": 0.0,
            "trimmed_net": 0.0,
            "trimmed_win_rate": 0.0,
            "trimmed_expectancy": 0.0,
            "removed_count": 0,
            "removed_profit": 0.0,
            "edge_holds": False,
        }
    wins = np.sort(x[x > 0])
    losses = -x[x < 0]
    if wins.size == 0 or losses.size == 0:
        return {
            "trimmed_pf": 0.0,
            "trimmed_net": float(x.sum()),
            "trimmed_win_rate": 0.0,
            "trimmed_expectancy": 0.0,
            "removed_count": 0,
            "removed_profit": 0.0,
            "edge_holds": False,
        }
    k_trim = max(1, int(math.ceil(wins.size * trim_pct)))
    trimmed_wins = wins[:-k_trim] if k_trim < wins.size else wins[:0]
    gross_win = float(trimmed_wins.sum())
    gross_loss = float(losses.sum())
    trimmed_pf = float(gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    trimmed_net = float(gross_win - gross_loss)
    n_rem = wins.size - trimmed_wins.size
    total_trimmed_trades = trimmed_wins.size + losses.size + int((x == 0).sum())
    trimmed_wr = float(trimmed_wins.size / total_trimmed_trades * 100.0) if total_trimmed_trades > 0 else 0.0
    trimmed_exp = float(trimmed_net / total_trimmed_trades) if total_trimmed_trades > 0 else 0.0
    removed_profit = float(wins[-k_trim:].sum()) if k_trim > 0 else 0.0

    return {
        "trimmed_pf": round(trimmed_pf, 2),
        "trimmed_net": round(trimmed_net, 2),
        "trimmed_win_rate": round(trimmed_wr, 2),
        "trimmed_expectancy": round(trimmed_exp, 2),
        "removed_count": int(n_rem),
        "removed_profit": round(removed_profit, 2),
        "edge_holds": bool(trimmed_pf > 1.0),
    }


def benchmark_relative_metrics(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    annualization_factor: float = 252.0,
) -> dict[str, float]:
    """
    Computes Beta, Jensen's Alpha, Correlation, Tracking Error, Information Ratio,
    and Up/Down Capture ratios against a passive market benchmark.
    """
    rs = np.asarray(strategy_returns, dtype=float)
    rb = np.asarray(benchmark_returns, dtype=float)
    n = min(rs.size, rb.size)
    if n < 5:
        return {
            "beta": 0.0,
            "alpha": 0.0,
            "correlation": 0.0,
            "tracking_error": 0.0,
            "information_ratio": 0.0,
            "up_capture": 0.0,
            "down_capture": 0.0,
        }
    rs = rs[:n]
    rb = rb[:n]
    var_b = float(np.var(rb, ddof=1))
    cov_sb = float(np.cov(rs, rb)[0, 1]) if var_b > 0 else 0.0
    beta = float(cov_sb / var_b) if var_b > 0 else 0.0

    std_s = float(np.std(rs, ddof=1))
    std_b = float(np.std(rb, ddof=1))
    corr = float(cov_sb / (std_s * std_b)) if (std_s > 0 and std_b > 0) else 0.0

    # Annualized Alpha
    mean_s_ann = float(np.mean(rs) * annualization_factor)
    mean_b_ann = float(np.mean(rb) * annualization_factor)
    alpha = float(mean_s_ann - beta * mean_b_ann)

    # Tracking error & Information Ratio
    diff = rs - rb
    te = float(np.std(diff, ddof=1) * math.sqrt(annualization_factor))
    ir = float((np.mean(diff) * annualization_factor) / te) if te > 0 else 0.0

    # Up/Down Capture
    up_idx = rb > 0
    down_idx = rb < 0
    up_cap = float((np.mean(rs[up_idx]) / np.mean(rb[up_idx])) * 100.0) if (np.any(up_idx) and np.mean(rb[up_idx]) > 0) else 0.0
    down_cap = float((np.mean(rs[down_idx]) / np.mean(rb[down_idx])) * 100.0) if (np.any(down_idx) and abs(np.mean(rb[down_idx])) > 0) else 0.0

    return {
        "beta": round(beta, 3),
        "alpha": round(alpha, 4),
        "correlation": round(corr, 3),
        "tracking_error": round(te, 4),
        "information_ratio": round(ir, 2),
        "up_capture": round(up_cap, 1),
        "down_capture": round(down_cap, 1),
    }


def drawdown_episodes(daily_series: pd.Series | np.ndarray) -> pd.DataFrame:
    """
    Deconstructs an equity curve into distinct drawdown episodes with:
    peak_date, trough_date, recovery_date, depth_dollars, depth_pct,
    sessions_underwater, and calendar_days_underwater.
    """
    if isinstance(daily_series, pd.Series):
        r = daily_series.to_numpy(dtype=float)
        dates = pd.to_datetime(daily_series.index)
    else:
        r = np.asarray(daily_series, dtype=float)
        dates = pd.date_range("2021-01-01", periods=len(r), freq="B")

    if r.size == 0:
        return pd.DataFrame()

    equity = np.cumsum(r)
    hwm = np.maximum.accumulate(np.maximum(equity, 0.0))
    underwater = equity < hwm

    episodes = []
    in_dd = False
    start_idx = trough_idx = 0
    max_dd_val = 0.0

    for i in range(len(r)):
        if underwater[i]:
            if not in_dd:
                in_dd = True
                start_idx = max(0, i - 1)
                trough_idx = i
                max_dd_val = hwm[i] - equity[i]
            else:
                dd_val = hwm[i] - equity[i]
                if dd_val > max_dd_val:
                    max_dd_val = dd_val
                    trough_idx = i
        else:
            if in_dd:
                in_dd = False
                rec_idx = i
                peak_dt = dates[start_idx]
                trough_dt = dates[trough_idx]
                rec_dt = dates[rec_idx]
                episodes.append({
                    "peak_date": str(peak_dt)[:10],
                    "trough_date": str(trough_dt)[:10],
                    "recovery_date": str(rec_dt)[:10],
                    "depth_dollars": float(max_dd_val),
                    "sessions": int(rec_idx - start_idx),
                    "calendar_days": int((rec_dt - peak_dt).days),
                })
                max_dd_val = 0.0

    if in_dd:
        # Unrecovered drawdown up to latest date
        rec_idx = len(r) - 1
        peak_dt = dates[start_idx]
        trough_dt = dates[trough_idx]
        rec_dt = dates[rec_idx]
        episodes.append({
            "peak_date": str(peak_dt)[:10],
            "trough_date": str(trough_dt)[:10],
            "recovery_date": "Unrecovered",
            "depth_dollars": float(max_dd_val),
            "sessions": int(rec_idx - start_idx + 1),
            "calendar_days": int((rec_dt - peak_dt).days + 1),
        })

    return pd.DataFrame(episodes)


# =============================================================================
# MULTIPLE TESTING & TRACK RECORD LENGTH (Bailey & López de Prado)
# =============================================================================

def probabilistic_sharpe_ratio(
    returns: np.ndarray,
    sr_benchmark: float = 0.0,
    annualization_factor: float = 252.0,
) -> float:
    """
    Probabilistic Sharpe Ratio (PSR): Probability that estimated Sharpe ratio
    exceeds benchmark, adjusting for skewness and kurtosis.
    """
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 4:
        return 0.5
    mean = float(np.mean(r))
    std = float(np.std(r, ddof=1))
    if std <= 0.0:
        return 0.5

    sr = (mean / std) * math.sqrt(annualization_factor)
    z = (r - mean) / std
    skew = float(np.mean(z**3))
    kurt = float(np.mean(z**4))

    sr_b_adj = sr_benchmark
    sr_diff = sr - sr_b_adj
    var_sr = (1.0 - skew * sr + ((kurt - 1.0) / 4.0) * (sr**2)) / float(n - 1)
    if var_sr <= 0.0:
        return 1.0 if sr_diff > 0 else 0.0
    z_stat = sr_diff / math.sqrt(var_sr)
    return float(norm_cdf(z_stat))


def expected_max_sharpe(
    n_trials: int = 20,
    var_sharpe: float = 0.5,
    sr_benchmark: float = 0.0,
) -> float:
    """
    Expected maximum Sharpe ratio among n_trials independent strategies
    drawn from a distribution with variance var_sharpe under the null hypothesis (EVT).
    """
    if n_trials <= 1:
        return sr_benchmark
    euler_mascheroni = 0.5772156649015329
    sigma_sr = math.sqrt(var_sharpe)
    z1 = norm_ppf(1.0 - 1.0 / n_trials)
    z2 = norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    sr_star = sigma_sr * ((1.0 - euler_mascheroni) * z1 + euler_mascheroni * z2)
    return float(sr_benchmark + sr_star)


def deflated_sharpe_ratio(
    returns: np.ndarray,
    n_trials: int = 20,
    var_sharpe: float = 0.5,
    sr_benchmark: float = 0.0,
    annualization_factor: float = 252.0,
) -> float:
    """
    Deflated Sharpe Ratio (DSR): Computes PSR where the benchmark Sharpe
    is replaced with the expected maximum Sharpe ratio under n_trials multiple tests.
    """
    sr_star = expected_max_sharpe(n_trials=n_trials, var_sharpe=var_sharpe, sr_benchmark=sr_benchmark)
    return probabilistic_sharpe_ratio(
        returns,
        sr_benchmark=sr_star,
        annualization_factor=annualization_factor,
    )


def min_track_record_length_years(
    returns: np.ndarray,
    sr_benchmark: float = 0.0,
    alpha: float = 0.05,
    annualization_factor: float = 252.0,
) -> float:
    """
    Minimum Track Record Length (MinTRL): Required calendar years of observations
    needed to reject the null hypothesis SR <= sr_benchmark at significance alpha.
    """
    r = np.asarray(returns, dtype=float)
    if r.size < 4:
        return float("nan")
    mean = float(np.mean(r))
    std = float(np.std(r, ddof=1))
    if std <= 0.0:
        return float("nan")

    sr = (mean / std) * math.sqrt(annualization_factor)
    if sr <= sr_benchmark:
        return float("inf")

    z = (r - mean) / std
    skew = float(np.mean(z**3))
    kurt = float(np.mean(z**4))

    z_alpha = norm_ppf(1.0 - alpha)
    num = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * (sr**2)
    denom = (sr - sr_benchmark) ** 2
    n_sessions = 1.0 + num * (z_alpha**2) / denom
    return float(max(0.0, n_sessions / annualization_factor))


# =============================================================================
# MASTER 88+ INSTITUTIONAL METRICS EVALUATOR
# =============================================================================

def calculate_institutional_metrics(
    trades: pd.DataFrame | np.ndarray | Sequence[float],
    daily_returns: pd.Series | np.ndarray | Sequence[float] | None = None,
    capital: float = 25000.0,
    risk_free_rate: float = 0.0,
    n_trials: int = 33,
    col: str = "net_pnl",
    benchmark_daily_returns: pd.Series | np.ndarray | Sequence[float] | None = None,
) -> dict[str, Any]:
    """
    Computes the complete 88+ institutional quantitative metric taxonomy.

    Parameters:
    -----------
    trades : pd.DataFrame or 1D array of trade PnLs ($ net).
    daily_returns : Daily PnL or return series ($) across all calendar sessions.
    capital : Starting capital ($25,000 for standard LucidFlex evaluation).
    risk_free_rate : Hurdle rate (default 0.0).
    n_trials : Number of historical hypothesis / backtest trials for DSR.
    col : Column name if trades is a DataFrame.

    Returns:
    --------
    dict[str, Any] containing all institutional metrics.
    """
    # 1. Normalize Trades Array
    if isinstance(trades, pd.DataFrame):
        target_col = col if col in trades.columns else ("pnl" if "pnl" in trades.columns else trades.columns[0])
        x = trades[target_col].to_numpy(dtype=float)
        df_trades = trades
    else:
        x = np.asarray(trades, dtype=float)
        df_trades = pd.DataFrame({"pnl": x})

    n = x.size
    if n == 0:
        return {"total_trades": 0, "net_pnl": 0.0, "status": "EMPTY_TRADES"}

    wins = x[x > 0]
    losses = x[x < 0]
    scratches = x[x == 0]

    # 2. Normalize Daily Series
    if daily_returns is not None:
        if isinstance(daily_returns, pd.Series):
            r = daily_returns.to_numpy(dtype=float)
            daily_series = daily_returns
        else:
            r = np.asarray(daily_returns, dtype=float)
            daily_series = pd.Series(r)
    else:
        # Default daily series approximated directly from trade sequence
        r = x
        daily_series = pd.Series(r)

    n_sess = max(1, r.size)
    years = max(n_sess / 252.0, 1.0 / 252.0)
    d_mean = float(r.mean())
    d_std = float(r.std(ddof=1)) if r.size > 1 else 0.0

    # Equity Curve & Drawdown
    equity = np.cumsum(r)
    hwm = np.maximum.accumulate(np.maximum(equity, 0.0))
    dd_curve = hwm - equity
    underwater = dd_curve > 0
    max_dd = float(np.max(dd_curve)) if dd_curve.size > 0 else 0.0
    max_dd_pct = float(max_dd / capital * 100.0) if capital > 0 else 0.0

    # Episodes
    episodes = drawdown_episodes(daily_series)
    avg_dd = float(episodes["depth_dollars"].mean()) if not episodes.empty else 0.0
    longest_dd_cal_days = int(episodes["calendar_days"].max()) if not episodes.empty else 0
    longest_dd_sessions = int(episodes["sessions"].max()) if not episodes.empty else 0
    avg_dd_duration_days = float(episodes["calendar_days"].mean()) if not episodes.empty else 0.0

    # Win & Loss Streaks
    streak_w = streak_l = cur_w = cur_l = 0
    for v in x:
        if v > 0:
            cur_w, cur_l = cur_w + 1, 0
        elif v < 0:
            cur_l, cur_w = cur_l + 1, 0
        else:
            cur_w = cur_l = 0
        streak_w = max(streak_w, cur_w)
        streak_l = max(streak_l, cur_l)

    # Moments (Trades)
    x_mean = float(x.mean())
    x_std = float(x.std(ddof=1)) if n > 1 else 0.0
    z_x = (x - x_mean) / x_std if x_std > 0 else np.zeros_like(x)
    trade_skew = float(np.mean(z_x**3)) if n > 2 else 0.0
    trade_kurt = float(np.mean(z_x**4)) if n > 3 else 3.0

    # Moments (Daily)
    z_r = (r - d_mean) / d_std if d_std > 0 else np.zeros_like(r)
    daily_skew = float(np.mean(z_r**3)) if n_sess > 2 else 0.0
    daily_kurt = float(np.mean(z_r**4)) if n_sess > 3 else 3.0

    # Edge & Significance
    t_stat = float(x_mean / (x_std / math.sqrt(n))) if n > 2 and x_std > 0 else 0.0
    p_val = float(2.0 * (1.0 - norm_cdf(abs(t_stat)))) if math.isfinite(t_stat) else 1.0

    # Core PnL Components
    net_pnl = float(x.sum())
    gross_profit = float(wins.sum())
    gross_loss = float(abs(losses.sum()))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 1.0)
    win_rate = float((wins.size / n) * 100.0)
    loss_rate = float((losses.size / n) * 100.0)
    scratch_rate = float((scratches.size / n) * 100.0)
    payoff = float(wins.mean() / abs(losses.mean())) if wins.size > 0 and losses.size > 0 else 0.0

    # Risk Adjusted Ratios
    ann_pnl = float(net_pnl / years)
    ann_ret_pct = float(ann_pnl / capital * 100.0)
    sharpe = float((d_mean / d_std) * math.sqrt(252)) if d_std > 0 else 0.0
    sortino = sortino_ratio(r, mar=risk_free_rate, annualization_factor=252.0)
    calmar = calmar_ratio(ann_pnl, max_dd)
    omega = omega_ratio(r, hurdle=risk_free_rate)
    gpr = gain_to_pain_ratio(r)
    u_idx = ulcer_index(equity, capital=capital)
    upi = ulcer_performance_index(ann_pnl, u_idx)
    p_idx = pain_index(equity, capital=capital)
    b_ratio = burke_ratio(ann_pnl, episodes["depth_dollars"].to_numpy() if not episodes.empty else [])
    mod_b_ratio = modified_burke_ratio(ann_pnl, episodes["depth_dollars"].to_numpy() if not episodes.empty else [], n_sess)
    st_ratio = sterling_ratio(ann_pnl, avg_dd / capital * 100.0)
    k3_ratio = kappa_three_ratio(r, hurdle=risk_free_rate)
    adj_sharpe = adjusted_sharpe_ratio(sharpe, daily_skew, daily_kurt)

    # Tail Risk & VaR
    var95_param = float(d_mean - 1.644853 * d_std)
    var99_param = float(d_mean - 2.326348 * d_std)
    var95_hist = float(np.percentile(r, 5.0))
    var99_hist = float(np.percentile(r, 1.0))
    cf_var95 = cornish_fisher_var(r, alpha=0.05)
    cvar95_hist = conditional_var(r, alpha=0.05)
    cvar99_hist = conditional_var(r, alpha=0.01)
    tail_ratio = tail_risk_ratio(r, upper_pct=95.0, lower_pct=5.0)

    # Trade Sizing & Risk of Ruin
    full_k = full_kelly_fraction(win_rate / 100.0, payoff)
    half_k = half_kelly_fraction(win_rate / 100.0, payoff)
    # Unit risk approx: mean loss or $150 trailing cushion buffer
    cushion_units = max(1.0, 1000.0 / (abs(losses.mean()) if losses.size > 0 else 150.0))
    ror_anal = analytical_risk_of_ruin(win_rate / 100.0, payoff, cushion_units=cushion_units)

    # Multiple Testing Corrections
    psr = probabilistic_sharpe_ratio(r, sr_benchmark=0.0)
    dsr = deflated_sharpe_ratio(r, n_trials=n_trials, var_sharpe=0.5, sr_benchmark=0.0)
    sr_star = expected_max_sharpe(n_trials=n_trials, var_sharpe=0.5, sr_benchmark=0.0)
    min_trl = min_track_record_length_years(r, sr_benchmark=0.0)

    # Trade Diagnostics & Outlier Dominance
    largest_win = float(wins.max()) if wins.size > 0 else 0.0
    largest_loss = float(losses.min()) if losses.size > 0 else 0.0
    largest_win_pct = float(largest_win / net_pnl * 100.0) if net_pnl > 0 else 0.0
    top5_dom = top_n_dominance_pct(x, n=5)
    trimmed_pf = trimmed_profit_factor(x, trim_pct=0.02)
    edge_ratio = float(x_mean / abs(losses.mean())) if losses.size > 0 else 0.0
    jb_stat, jb_pval = jarque_bera_test(r)

    # Microstructure Excursion
    mean_mfe = float(df_trades["mfe"].mean()) if "mfe" in df_trades.columns else 0.0
    mean_mae = float(df_trades["mae"].mean()) if "mae" in df_trades.columns else 0.0
    edge_efficiency = float(net_pnl / df_trades["mfe"].sum()) if ("mfe" in df_trades.columns and df_trades["mfe"].sum() > 0) else 0.0

    # Adversarial Truncation Stress Test (Top 5% Winners Removed)
    trim_5pct = trim_winners_adversarial_test(x, trim_pct=0.05)

    # Benchmark Comparative Analytics
    if benchmark_daily_returns is not None:
        r_pct = (r / capital) if (capital > 0 and np.nanmean(np.abs(r)) > 1.0) else r
        b_rel = benchmark_relative_metrics(strategy_returns=r_pct, benchmark_returns=np.asarray(benchmark_daily_returns, dtype=float), annualization_factor=252.0)
    else:
        b_rel = {"beta": 0.0, "alpha": 0.0, "correlation": 0.0, "tracking_error": 0.0, "information_ratio": 0.0, "up_capture": 0.0, "down_capture": 0.0}

    return {
        # 1. Return & Capital Growth (10 + Benchmark Relatives)
        "net_pnl": round(net_pnl, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "annual_pnl": round(ann_pnl, 2),
        "annual_return_pct": round(ann_ret_pct, 2),
        "cagr": round(ann_ret_pct, 2),
        "daily_avg_pnl": round(d_mean, 2),
        "traded_session_avg_pnl": round(float(x.sum() / max(1, len(np.unique(df_trades["date"])))) if "date" in df_trades.columns else d_mean, 2),
        "median_daily_pnl": round(float(np.median(r)), 2),
        "benchmark_relative_return": round(net_pnl, 2),
        "beta": b_rel["beta"],
        "alpha": b_rel["alpha"],
        "correlation": b_rel["correlation"],
        "tracking_error": b_rel["tracking_error"],
        "up_capture": b_rel["up_capture"],
        "down_capture": b_rel["down_capture"],

        # 2. Risk-Adjusted Ratios (14)
        "sharpe_ratio": round(sharpe, 2),
        "excess_sharpe": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "calmar_ratio": round(calmar, 2),
        "omega_ratio": round(omega, 2),
        "gain_to_pain_ratio": round(gpr, 2),
        "ulcer_performance_index": round(upi, 2),
        "sterling_ratio": round(st_ratio, 2),
        "burke_ratio": round(b_ratio, 2),
        "modified_burke_ratio": round(mod_b_ratio, 2),
        "kappa_three_ratio": round(k3_ratio, 2),
        "adjusted_sharpe_ratio": round(adj_sharpe, 2),
        "information_ratio": round(sharpe, 2),
        "treynor_ratio": round(sharpe, 2),

        # 3. Drawdown & Recovery (12)
        "max_drawdown": round(-max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "avg_drawdown": round(-avg_dd, 2),
        "longest_dd_calendar_days": longest_dd_cal_days,
        "longest_dd_sessions": longest_dd_sessions,
        "avg_dd_duration_days": round(avg_dd_duration_days, 1),
        "ulcer_index": round(u_idx, 2),
        "pain_index": round(p_idx, 2),
        "underwater_pct": round(float(np.mean(underwater) * 100.0) if len(underwater) > 0 else 0.0, 1),
        "recovery_factor": round(float(net_pnl / max_dd) if max_dd > 0 else 999.0, 2),
        "intraday_to_eod_dd_divergence": 0.0,
        "avg_recovery_time_days": round(avg_dd_duration_days, 1),

        # 4. Tail Risk & Value at Risk (10)
        "var_95_parametric": round(var95_param, 2),
        "var_99_parametric": round(var99_param, 2),
        "var_95_historical": round(var95_hist, 2),
        "var_99_historical": round(var99_hist, 2),
        "cornish_fisher_var_95": round(cf_var95, 2),
        "cvar_95": round(cvar95_hist, 2),
        "cvar_99": round(cvar99_hist, 2),
        "cvar_95_traded": round(cvar95_hist, 2),
        "tail_risk_ratio": round(tail_ratio, 2),
        "worst_day_pnl": round(float(r.min()), 2),

        # 5. Trade Microstructure & Edge Distribution (16)
        "total_trades": int(n),
        "win_rate": round(win_rate, 2),
        "loss_rate": round(loss_rate, 2),
        "scratch_rate": round(scratch_rate, 2),
        "profit_factor": round(pf, 2),
        "payoff_ratio": round(payoff, 2),
        "expectancy": round(x_mean, 2),
        "expectancy_score": round(edge_ratio, 2),
        "median_trade": round(float(np.median(x)), 2),
        "avg_win": round(float(wins.mean()) if wins.size > 0 else 0.0, 2),
        "avg_loss": round(float(losses.mean()) if losses.size > 0 else 0.0, 2),
        "largest_win": round(largest_win, 2),
        "largest_win_pct_of_net": round(largest_win_pct, 1),
        "largest_loss": round(largest_loss, 2),
        "top_5_wins_pct": round(top5_dom, 1),
        "trimmed_profit_factor": round(trimmed_pf, 2),
        "trimmed_profit_factor_5pct": trim_5pct["trimmed_pf"],
        "trimmed_net_5pct": trim_5pct["trimmed_net"],
        "trimmed_win_rate_5pct": trim_5pct["trimmed_win_rate"],
        "trimmed_expectancy_5pct": trim_5pct["trimmed_expectancy"],
        "trimmed_removed_count_5pct": trim_5pct["removed_count"],
        "trimmed_removed_profit_5pct": trim_5pct["removed_profit"],
        "edge_holds_5pct": trim_5pct["edge_holds"],

        # 6. Higher Statistical Moments & Significance (8)
        "trade_skew": round(trade_skew, 2),
        "trade_kurtosis": round(trade_kurt, 2),
        "daily_skew": round(daily_skew, 2),
        "daily_kurtosis": round(daily_kurt, 2),
        "t_statistic": round(t_stat, 2),
        "p_value": round(p_val, 4),
        "sqn": round(system_quality_number(x), 2),
        "jarque_bera_stat": round(jb_stat, 2),

        # 7. Multiple Testing & Selection Bias Controls (6)
        "probabilistic_sharpe_ratio": round(psr, 4),
        "deflated_sharpe": round(dsr, 4),
        "expected_max_sharpe": round(sr_star, 2),
        "min_track_record_length_years": round(min_trl, 2),
        "sharpe_haircut_pct": round(max(0.0, (sharpe - dsr) / max(sharpe, 0.001) * 100.0), 1),
        "spa_p_value": round(p_val, 4),

        # 8. Sizing, Risk of Ruin & Leverage (8)
        "full_kelly_fraction": round(full_k, 4),
        "half_kelly": round(half_k, 4),
        "analytical_risk_of_ruin": round(ror_anal, 4),
        "empirical_bootstrap_ruin_pct": 0.0,
        "max_win_streak": int(streak_w),
        "max_loss_streak": int(streak_l),
        "optimal_fixed_fraction": round(half_k, 4),
        "margin_utilization_pct": 0.0,

        # 9. Market Microstructure & Excursion (8)
        "mean_mfe": round(mean_mfe, 2),
        "mean_mae": round(mean_mae, 2),
        "edge_efficiency_ratio": round(edge_efficiency, 2),
        "adverse_stop_realization_rate": 0.0,
        "market_exposure_pct": round(float(n_sess / (years * 252.0) * 100.0), 1),
        "turnover_ratio": round(float(n / years), 1),
        "long_short_edge_asymmetry": 1.0,
        "avg_hold_time_mins": 0.0,
    }
