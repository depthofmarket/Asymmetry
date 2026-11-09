"""
Dashboard analytics: performance metrics and LucidFlex 25K prop simulation.

Design rules (each fixes a defect in the previous dashboard generators):
  * Every daily statistic (Sharpe, Sortino, VaR, drawdown duration) is computed on the
    FULL session calendar, zero-trade sessions included. Using only days with trades and
    annualising with sqrt(252) overstated Sharpe by roughly 1/sqrt(exposure).
  * Time is measured in exchange sessions and calendar days, never in "trade days".
  * Prop simulations bootstrap whole sessions (including flat ones), so "days to pass"
    is real elapsed time.
  * Sizing is explicit: the research dataset sizing (risk-based contracts x Markov
    multiplier) is kept separate from the live anti-martingale ratchet (2/3/4 micros).
  * The daily soft stop halts the remaining windows of the day; it does not clip a loss
    that has already happened.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
import pandas as pd

from backtest.demo_parity_engine import (
    DAILY_SOFT_STOP_DOLLARS,
    MAX_TRAILING_DRAWDOWN,
    PEAK_FOR_FLOOR_LOCK,
    PROFIT_TARGET_DOLLARS,
    STARTING_CAPITAL,
    TRAILING_FLOOR_LOCK,
)
from config.prop_firm_registry import LUCID_FLEX_25K

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRADES_PATH = REPO_ROOT / "data/processed/unified_five_strategy_portfolio_trades_2021_2026.parquet"
DEFAULT_CALENDAR_SOURCE = REPO_ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet"

STRATEGY_META = {
    "S2": dict(name="S2 Macro Momentum", window="08:35-09:25 ET", instruments="MNQ", order=0, color="#d62728"),
    "S1": dict(name="S1 VA Breakout", window="09:45-10:15 ET", instruments="MNQ + MES", order=1, color="#ff7f0e"),
    "S3": dict(name="S3 Gold Fix", window="10:15-11:00 ET", instruments="MGC", order=2, color="#2ca02c"),
    "S5": dict(name="S5 Crude RTH Expansion", window="10:15-12:30 ET", instruments="MCL", order=3, color="#0D9488"),
    "S4": dict(name="S4 Asian Evening Reversion", window="21:00-23:00 ET", instruments="MNQ", order=4, color="#9467bd"),
}
STRATEGY_ORDER = ("S1", "S2", "S3", "S4", "S5")
TICK_VALUE = {"MNQ": 0.50, "MES": 1.25, "MGC": 1.00, "MCL": 1.00, "NQ": 0.50, "ES": 1.25, "GC": 1.00, "CL": 1.00}
DEV_END = "2024-12-31"  # 2021-2024 development, 2025-2026 holdout


# ───────────────────────────────────────────────────────────────────────────────
# Loading
# ───────────────────────────────────────────────────────────────────────────────
def _strategy_code(name: str) -> str:
    s = str(name).lower()
    if "morning" in s or "va breakout" in s or "va_breakout" in s:
        return "S1"
    if "macro" in s:
        return "S2"
    if "gold" in s:
        return "S3"
    if "asian" in s or "evening" in s:
        return "S4"
    if "crude" in s or "rth_expansion" in s:
        return "S5"
    for code in ("S1", "S2", "S3", "S4", "S5"):
        if f"Strategy {code[1]}" in str(name):
            return code
    raise ValueError(f"Unknown strategy label: {name}")


def load_trades(path: Path = DEFAULT_TRADES_PATH) -> pd.DataFrame:
    df = pd.read_parquet(path).copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["hold_minutes"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 60.0
    df["date"] = df["entry_time"].dt.strftime("%Y-%m-%d")
    df["date_str"] = df["date"]
    df["year"] = df["entry_time"].dt.year
    df["month"] = df["entry_time"].dt.month
    df["weekday"] = df["entry_time"].dt.day_name()
    df["strat"] = df["strategy"].map(_strategy_code)
    df["order"] = df["strat"].map(lambda s: STRATEGY_META[s]["order"])
    df["contracts"] = df["contracts"].astype(int).clip(lower=1)
    # Base P&L at research (risk-based) sizing, before the Markov multiplier
    df["base_pnl"] = df["net_dollars_micro"].astype(float)
    # Research P&L: risk-based sizing x Markov multiplier (what the old dashboards used)
    df["research_pnl"] = df["pnl"].astype(float)
    df["per_contract_pnl"] = df["base_pnl"] / df["contracts"]
    if "markov_state_label" not in df.columns:
        mult = df["pnl"] / df["net_dollars_micro"].replace(0, np.nan)
        df["markov_state_label"] = np.where(mult > 1.1, "low_vol", np.where(mult < 0.9, "high_vol", "mid_vol"))
    if "markov_sizing_mult" not in df.columns:
        df["markov_sizing_mult"] = (df["pnl"] / df["net_dollars_micro"].replace(0, np.nan)).fillna(1.0)
    s1_counts = df[df["strat"] == "S1"].groupby("date")["sym"].transform("nunique")
    df["s1_pair"] = False
    df.loc[s1_counts.index, "s1_pair"] = s1_counts.to_numpy() > 1
    return df.sort_values(["entry_time", "order"]).reset_index(drop=True)


def load_session_calendar(source: Path = DEFAULT_CALENDAR_SOURCE, start: str | None = None, end: str | None = None) -> list[str]:
    """Exchange sessions = dates that printed a 09:30 ET bar."""
    t = pd.read_parquet(source, columns=["time"])["time"]
    sess = sorted(set(t[(t.dt.hour == 9) & (t.dt.minute == 30)].dt.strftime("%Y-%m-%d")))
    if start:
        sess = [s for s in sess if s >= start]
    if end:
        sess = [s for s in sess if s <= end]
    return sess


def daily_series(trades: pd.DataFrame, calendar: Sequence[str], col: str) -> pd.Series:
    s = trades.groupby("date")[col].sum()
    return s.reindex(list(calendar), fill_value=0.0).astype(float)


# ───────────────────────────────────────────────────────────────────────────────
# Statistics helpers
# ───────────────────────────────────────────────────────────────────────────────
def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Acklam's rational approximation (|err| < 1.2e-9)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02, 1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02, 6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00, -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    lo, hi = 0.02425, 1 - 0.02425
    if p < lo:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > hi:
        return -norm_ppf(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def profit_factor(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    gl = -x[x < 0].sum()
    return float(x[x > 0].sum() / gl) if gl > 0 else np.nan


def max_drawdown(equity: np.ndarray) -> float:
    equity = np.asarray(equity, float)
    if equity.size == 0:
        return 0.0
    return float((equity - np.maximum.accumulate(np.maximum(equity, 0.0))).min())


def probabilistic_sharpe(returns: np.ndarray, sr_benchmark: float = 0.0) -> float:
    """Bailey & Lopez de Prado PSR on per-period returns (not annualised)."""
    r = np.asarray(returns, float)
    n = r.size
    if n < 3:
        return np.nan
    sd = r.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return np.nan
    sr = r.mean() / sd
    z = (r - r.mean()) / r.std(ddof=0)
    skew, kurt = float((z**3).mean()), float((z**4).mean())
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr**2))
    return norm_cdf((sr - sr_benchmark) * math.sqrt(n - 1) / denom)


def min_track_record_length(returns: np.ndarray, sr_benchmark: float = 0.0, confidence: float = 0.95) -> float:
    """Sessions needed for the observed Sharpe to beat the benchmark at `confidence`."""
    r = np.asarray(returns, float)
    if r.size < 3:
        return np.nan
    sd = r.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return np.nan
    sr = r.mean() / sd
    if sr <= sr_benchmark:
        return np.inf
    z = (r - r.mean()) / r.std(ddof=0)
    skew, kurt = float((z**3).mean()), float((z**4).mean())
    return float(1 + (1 - skew * sr + (kurt - 1) / 4 * sr**2) * (norm_ppf(confidence) / (sr - sr_benchmark)) ** 2)


def expected_max_sharpe(
    n_trials: int = 20,
    var_sharpe: float = 0.5,
    sr_benchmark: float = 0.0,
) -> float:
    """Expected maximum Sharpe ratio under EVT (Bailey & Lopez de Prado 2014).

    Parameters
    ----------
    n_trials : int, default 20
        Number of independent strategy / parameter trials.
    var_sharpe : float, default 0.5
        Variance of the Sharpe ratios across trials.
    sr_benchmark : float, default 0.0
        Base benchmark Sharpe ratio.

    Returns
    -------
    float
        Expected maximum Sharpe ratio under extreme value theory.
    """
    if n_trials <= 1:
        return float(sr_benchmark)
    euler_gamma = 0.57721566490153286
    p1 = min(1.0 - 1e-15, max(1e-15, 1.0 - 1.0 / n_trials))
    p2 = min(1.0 - 1e-15, max(1e-15, 1.0 - 1.0 / (n_trials * math.e)))
    sr_star = math.sqrt(max(0.0, var_sharpe)) * (
        (1.0 - euler_gamma) * norm_ppf(p1)
        + euler_gamma * norm_ppf(p2)
    )
    return float(sr_star)


def deflated_sharpe_ratio(
    returns: np.ndarray,
    n_trials: int = 20,
    var_sharpe: float = 0.5,
    sr_benchmark: float = 0.0,
    annualization_factor: float = 1.0,
) -> float:
    """Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio.

    Evaluates the probabilistic Sharpe ratio against the expected maximum
    Sharpe ratio under extreme value theory (EVT) to correct for data mining
    bias across `n_trials`.

    Parameters
    ----------
    returns : np.ndarray
        Array of per-period returns (e.g. daily PnL or percentage returns).
    n_trials : int, default 20
        Number of strategy / parameter trials tested.
    var_sharpe : float, default 0.5
        Variance of the Sharpe ratios across the n_trials.
    sr_benchmark : float, default 0.0
        Baseline benchmark Sharpe ratio (annualized if annualization_factor > 1).
    annualization_factor : float, default 1.0
        Periods per year (e.g. 252 for daily returns) to de-annualize sr_star.

    Returns
    -------
    float
        Deflated Sharpe Ratio (in [0, 1] for valid return series, or np.nan).
    """
    if n_trials <= 1:
        sr_star = sr_benchmark
    else:
        sr_star = expected_max_sharpe(n_trials=n_trials, var_sharpe=var_sharpe, sr_benchmark=sr_benchmark)

    scale = math.sqrt(annualization_factor) if annualization_factor > 0 else 1.0
    sr_star_period = sr_star / scale
    sr_bm_period = sr_benchmark / scale

    return probabilistic_sharpe(returns, sr_benchmark=max(sr_bm_period, sr_star_period))


def drawdown_episodes(daily_pnl: pd.Series) -> pd.DataFrame:
    """Drawdown episodes on the session calendar (depth in $, durations in sessions & days)."""
    eq = daily_pnl.cumsum()
    peak = np.maximum.accumulate(np.maximum(eq.to_numpy(), 0.0))
    dd = eq.to_numpy() - peak
    dates = pd.to_datetime(daily_pnl.index)
    rows, i, n = [], 0, len(dd)
    while i < n:
        if dd[i] < 0:
            start = i
            while i < n and dd[i] < 0:
                i += 1
            end = i  # first session back at a new high (or n if unrecovered)
            trough = start + int(np.argmin(dd[start:end]))
            rows.append(dict(
                start=dates[start - 1] if start > 0 else dates[start],
                trough=dates[trough],
                recovered=dates[end] if end < n else pd.NaT,
                depth=float(dd[trough]),
                sessions=int(end - start + 1) if end < n else int(n - start),
                calendar_days=int(((dates[end] if end < n else dates[-1]) - (dates[start - 1] if start > 0 else dates[start])).days),
                recovered_flag=end < n,
            ))
        else:
            i += 1
    return pd.DataFrame(rows).sort_values("depth").reset_index(drop=True) if rows else pd.DataFrame(
        columns=["start", "trough", "recovered", "depth", "sessions", "calendar_days", "recovered_flag"])


# ───────────────────────────────────────────────────────────────────────────────
# Performance metrics
# ───────────────────────────────────────────────────────────────────────────────
def performance_metrics(trades: pd.DataFrame, calendar: Sequence[str], col: str, capital: float = STARTING_CAPITAL,
                        n_boot: int = 2000, seed: int = 7,
                        n_trials: int = 20, var_sharpe: float = 0.5, sr_benchmark: float = 0.0) -> dict:
    x = trades[col].to_numpy(float)
    n = x.size
    if n == 0:
        return {"trades": 0}
    wins, losses = x[x > 0], x[x < 0]
    daily = daily_series(trades, calendar, col)
    r = daily.to_numpy()
    n_sess = r.size
    years = n_sess / 252.0
    d_sd = r.std(ddof=1)
    downside = math.sqrt(np.mean(np.minimum(r, 0.0) ** 2))
    equity = np.cumsum(r)
    mdd = max_drawdown(equity)
    episodes = drawdown_episodes(daily)
    underwater = float(np.mean((equity - np.maximum.accumulate(np.maximum(equity, 0.0))) < 0) * 100)
    ulcer = float(np.sqrt(np.mean(((equity - np.maximum.accumulate(np.maximum(equity, 0.0))) / capital * 100) ** 2)))
    traded = r[daily.index.isin(trades["date"].unique())]
    t_stat = float(x.mean() / (x.std(ddof=1) / math.sqrt(n))) if n > 2 and x.std(ddof=1) > 0 else np.nan

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot = x[idx]
    boot_exp = boot.mean(axis=1)
    gp = np.where(boot > 0, boot, 0).sum(axis=1)
    gl = -np.where(boot < 0, boot, 0).sum(axis=1)
    boot_pf = np.where(gl > 0, gp / np.where(gl > 0, gl, 1), np.nan)

    streak_w = streak_l = cur_w = cur_l = 0
    for v in x:
        if v > 0:
            cur_w, cur_l = cur_w + 1, 0
        elif v < 0:
            cur_l, cur_w = cur_l + 1, 0
        streak_w, streak_l = max(streak_w, cur_w), max(streak_l, cur_l)

    def side(d: str) -> dict:
        s = trades.loc[trades["direction"] == d, col].to_numpy(float)
        return dict(n=int(s.size), net=float(s.sum()), wr=float((s > 0).mean() * 100) if s.size else np.nan, pf=profit_factor(s) if s.size else np.nan)

    z = (x - x.mean()) / x.std(ddof=0) if x.std(ddof=0) > 0 else np.zeros_like(x)
    return dict(
        trades=n, wins=int(wins.size), losses=int(losses.size), scratches=int((x == 0).sum()),
        net=float(x.sum()), gross_profit=float(wins.sum()), gross_loss=float(-losses.sum()),
        pf=profit_factor(x), pf_ci=(float(np.nanpercentile(boot_pf, 2.5)), float(np.nanpercentile(boot_pf, 97.5))),
        win_rate=float(wins.size / n * 100), expectancy=float(x.mean()),
        exp_ci=(float(np.percentile(boot_exp, 2.5)), float(np.percentile(boot_exp, 97.5))),
        median_trade=float(np.median(x)), avg_win=float(wins.mean()) if wins.size else 0.0,
        avg_loss=float(losses.mean()) if losses.size else 0.0,
        payoff=float(wins.mean() / -losses.mean()) if wins.size and losses.size else np.nan,
        largest_win=float(x.max()), largest_loss=float(x.min()),
        trade_sd=float(x.std(ddof=1)), trade_skew=float((z**3).mean()), trade_kurt=float((z**4).mean()),
        sqn=float(math.sqrt(min(n, 100)) * x.mean() / x.std(ddof=1)) if x.std(ddof=1) > 0 else np.nan,
        t_stat=t_stat, p_value=float(2 * (1 - norm_cdf(abs(t_stat)))) if np.isfinite(t_stat) else np.nan,
        max_win_streak=streak_w, max_loss_streak=streak_l,
        sessions=n_sess, traded_sessions=int(traded.size), exposure_pct=float(traded.size / n_sess * 100),
        trades_per_month=float(n / (years * 12)),
        annual_pnl=float(r.sum() / years), annual_return_pct=float(r.sum() / years / capital * 100),
        annual_vol=float(d_sd * math.sqrt(252)),
        sharpe=float(r.mean() / d_sd * math.sqrt(252)) if d_sd > 0 else np.nan,
        sortino=float(r.mean() / downside * math.sqrt(252)) if downside > 0 else np.nan,
        max_dd=mdd, max_dd_pct=float(mdd / capital * 100),
        calmar=float((r.sum() / years) / -mdd) if mdd < 0 else np.nan,
        recovery_factor=float(x.sum() / -mdd) if mdd < 0 else np.nan,
        longest_dd_sessions=int(episodes["sessions"].max()) if len(episodes) else 0,
        longest_dd_days=int(episodes["calendar_days"].max()) if len(episodes) else 0,
        underwater_pct=underwater, ulcer_index=ulcer,
        var95=float(np.percentile(r, 5)), cvar95=float(r[r <= np.percentile(r, 5)].mean()),
        var95_traded=float(np.percentile(traded, 5)) if traded.size else np.nan,
        cvar95_traded=float(traded[traded <= np.percentile(traded, 5)].mean()) if traded.size else np.nan,
        worst_day=float(r.min()), best_day=float(r.max()),
        profitable_sessions_pct=float((traded > 0).mean() * 100) if traded.size else np.nan,
        psr=probabilistic_sharpe(r, sr_benchmark=sr_benchmark),
        dsr=deflated_sharpe_ratio(r, n_trials=n_trials, var_sharpe=var_sharpe, sr_benchmark=sr_benchmark, annualization_factor=252.0),
        sr_star=expected_max_sharpe(n_trials=n_trials, var_sharpe=var_sharpe, sr_benchmark=sr_benchmark),
        min_trl_years=float(min_track_record_length(r, sr_benchmark=sr_benchmark) / 252),
        long=side("long"), short=side("short"),
    )


def period_split(trades: pd.DataFrame, col: str) -> pd.DataFrame:
    rows = []
    for strat in ("ALL",) + STRATEGY_ORDER:
        sub = trades if strat == "ALL" else trades[trades["strat"] == strat]
        for label, part in (("2021-24 dev", sub[sub["date"] <= DEV_END]), ("2025-26 holdout", sub[sub["date"] > DEV_END])):
            v = part[col].to_numpy(float)
            rows.append(dict(strat=strat, period=label, n=v.size, pf=profit_factor(v) if v.size else np.nan,
                             expectancy=float(v.mean()) if v.size else np.nan, win_rate=float((v > 0).mean() * 100) if v.size else np.nan))
    return pd.DataFrame(rows)


def rolling_trade_stats(trades: pd.DataFrame, col: str, window: int = 50) -> pd.DataFrame:
    s = trades[col].astype(float).reset_index(drop=True)
    pos = s.clip(lower=0).rolling(window).sum()
    neg = (-s.clip(upper=0)).rolling(window).sum()
    return pd.DataFrame({"time": trades["entry_time"].to_numpy(), "pf": (pos / neg.replace(0, np.nan)).to_numpy(),
                         "expectancy": s.rolling(window).mean().to_numpy(), "win_rate": (s > 0).rolling(window).mean().to_numpy() * 100})


def rolling_sharpe(daily: pd.Series, window: int = 252) -> pd.Series:
    m, sd = daily.rolling(window).mean(), daily.rolling(window).std()
    return (m / sd * math.sqrt(252)).rename("rolling_sharpe")


def reshuffled_max_drawdowns(x: np.ndarray, n: int = 3000, seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = np.asarray(x, float)
    out = np.empty(n)
    for i in range(n):
        out[i] = max_drawdown(np.cumsum(rng.permutation(x)))
    return out


def slippage_curve(trades: pd.DataFrame, col: str, ticks: Sequence[int] = range(0, 9)) -> pd.DataFrame:
    """Extra adverse ticks per side (entry + exit) per contract, scaled with the position size used in `col`."""
    scale = trades[col] / trades["base_pnl"].replace(0, np.nan)
    scale = scale.fillna(1.0)
    tick_cost = trades["micro"].map(TICK_VALUE) * trades["contracts"] * scale
    rows = []
    for k in ticks:
        adj = trades[col] - 2 * k * tick_cost
        rows.append(dict(ticks=k, net=float(adj.sum()), pf=profit_factor(adj.to_numpy()), expectancy=float(adj.mean())))
    return pd.DataFrame(rows)


def monthly_matrix(trades: pd.DataFrame, col: str) -> pd.DataFrame:
    t = trades.assign(year=trades["entry_time"].dt.year, month=trades["entry_time"].dt.month)
    return t.pivot_table(index="year", columns="month", values=col, aggfunc="sum").reindex(columns=range(1, 13))


# ───────────────────────────────────────────────────────────────────────────────
# Prop simulation
# ───────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PropRules:
    start: float = STARTING_CAPITAL
    target: float = PROFIT_TARGET_DOLLARS
    max_dd: float = MAX_TRAILING_DRAWDOWN
    floor_lock: float = TRAILING_FLOOR_LOCK
    peak_for_lock: float = PEAK_FOR_FLOOR_LOCK
    soft_stop: float | None = DAILY_SOFT_STOP_DOLLARS  # halts later windows that day
    eval_fee: float = 39.0  # ASSUMPTION - verify current LucidFlex pricing


@dataclass(frozen=True)
class FundedRules:
    """Authoritative LucidFlex 25K funded-phase payout mechanics governed by config.prop_firm_registry."""
    cycle_sessions: int = 5
    min_profit_days: int = LUCID_FLEX_25K.PAYOUT_MIN_PROFIT_DAYS            # 5 qualifying days
    profit_day_threshold: float = LUCID_FLEX_25K.PAYOUT_MIN_DAILY_PROFIT    # $100.00
    min_cycle_net_profit: float = LUCID_FLEX_25K.PAYOUT_MIN_CYCLE_NET_PROFIT # $1.00
    max_payout: float = LUCID_FLEX_25K.PAYOUT_MAX_REQUEST                   # $1,000.00
    payout_fraction: float = LUCID_FLEX_25K.PAYOUT_PCT_OF_PROFIT           # 0.50 (50% of profit above base)
    min_payout: float = LUCID_FLEX_25K.PAYOUT_MIN_REQUEST                   # $500.00
    split: float = LUCID_FLEX_25K.PROFIT_SPLIT_TRADER_PCT / 100.0          # 0.90
    max_payouts: int = LUCID_FLEX_25K.MAX_PAYOUTS_BEFORE_LIVE              # 5
    post_payout_floor: float = LUCID_FLEX_25K.FUNDED_LOCKED_FLOOR           # $25,100.00
    start_balance: float = LUCID_FLEX_25K.FUNDED_STARTING_BALANCE           # $25,000.00
    max_trailing_dd: float = LUCID_FLEX_25K.FUNDED_TRAILING_ALLOWANCE       # $1,000.00
    floor_lock_peak: float = LUCID_FLEX_25K.FUNDED_FLOOR_LOCK_PEAK         # $26,100.00
    soft_stop: float = -LUCID_FLEX_25K.FUNDED_DAILY_SOFT_STOP               # -$600.00

    def required_post_payout_cushion(self, gross_payout: float) -> float:
        """
        Dynamic post-payout cushion requirement:
        Linear interpolation: 400 + (gross_payout - 500), bounded between 400 and 900.
        """
        return LUCID_FLEX_25K.get_required_post_payout_cushion(gross_payout)


@dataclass(frozen=True)
class SizingPolicy:
    name: str
    kind: str  # "research" | "ratchet" | "fixed" | "dynamic_cushion" | "staging"
    fixed: int = 2
    tiers: tuple[tuple[float, int], ...] = ((500.0, 4), (200.0, 3), (-np.inf, 2))
    cushion_floor_buffer: float = 0.0  # Optional buffer for dynamic de-leveraging
    dynamic_delever_contracts: int = 1  # Contracts when floor buffer is breached
    staging_cushion: float = 0.0  # Optional profit cushion before ratchet activates
    staging_contracts: int = 1  # Contracts during staging
    closeout_thresh: float = 0.0  # Optional profit threshold to de-lever near target ($1,150)
    closeout_contracts: int = 1  # Contracts during closeout shield
    use_cushion_metric: bool = False  # If True, tiers evaluate on (bal - floor)

    def total_micros(self, profit: float, cushion: float | None = None) -> int:
        if self.kind == "fixed":
            return self.fixed
        if self.closeout_thresh > 0.0 and profit >= self.closeout_thresh:
            return self.closeout_contracts
        if self.cushion_floor_buffer > 0.0 and cushion is not None and cushion < self.cushion_floor_buffer:
            return self.dynamic_delever_contracts
        if self.staging_cushion > 0.0 and profit < self.staging_cushion:
            return self.staging_contracts
        metric = cushion if (self.use_cushion_metric and cushion is not None) else profit
        for threshold, micros in self.tiers:
            if metric >= threshold:
                return micros
        return self.tiers[-1][1]


POLICIES = {
    "live_ratchet": SizingPolicy("Live ratchet 2/3/4", "ratchet", tiers=((500.0, 4), (200.0, 3), (-np.inf, 2))),
    "optimized_live_ratchet": SizingPolicy(
        "Optimized Live Ratchet 2/3/4 (+300, +600, Cush<500, Cl1150)", "ratchet",
        tiers=((600.0, 4), (300.0, 3), (-np.inf, 2)),
        cushion_floor_buffer=500.0,
        dynamic_delever_contracts=1,
        closeout_thresh=1150.0,
        closeout_contracts=1,
    ),
    "research": SizingPolicy("Research sizing (risk-based x Markov)", "research"),
    "fixed_2": SizingPolicy("Fixed 2 micros", "fixed", fixed=2),
    "fixed_1": SizingPolicy("Fixed 1 micro", "fixed", fixed=1),
}


@dataclass
class Leg:
    order: int
    sym: str
    micro: str
    per_contract: float
    research: float
    research_contracts: int
    s1_pair: bool


def build_session_legs(trades: pd.DataFrame, calendar: Sequence[str]) -> list[list[list[Leg]]]:
    """sessions -> ordered groups (S3, S1, S2) -> legs."""
    by_date: dict[str, list[list[Leg]]] = {}
    for d, g in trades.groupby("date"):
        groups = []
        for _, grp in g.sort_values("order").groupby("order"):
            groups.append([Leg(int(r.order), r.sym, r.micro, float(r.per_contract_pnl), float(r.research_pnl),
                               int(r.contracts), bool(r.s1_pair)) for r in grp.itertuples()])
        by_date[d] = groups
    return [by_date.get(d, []) for d in calendar]


def leg_contracts(leg: Leg, policy: SizingPolicy, profit: float, cushion: float | None = None) -> int:
    if policy.kind == "research":
        return leg.research_contracts
    tier = policy.total_micros(profit, cushion=cushion)
    if leg.s1_pair:  # live watcher split: c_nq = max(1, tier // 2), c_es = max(1, tier - c_nq)
        c_nq = max(1, tier // 2)
        return c_nq if leg.sym == "NQ" else max(1, tier - c_nq)
    return tier


def leg_pnl(leg: Leg, policy: SizingPolicy, profit: float, extra_ticks: float, cushion: float | None = None) -> float:
    if policy.kind == "research":
        scale = leg.research / (leg.per_contract * leg.research_contracts) if leg.per_contract else 1.0
        return leg.research - 2 * extra_ticks * TICK_VALUE[leg.micro] * leg.research_contracts * scale
    c = leg_contracts(leg, policy, profit, cushion=cushion)
    return c * (leg.per_contract - 2 * extra_ticks * TICK_VALUE[leg.micro])


@dataclass
class EvalResult:
    status: str  # pass | fail | open
    sessions: int
    peak: float
    path: list[float] = field(default_factory=list)


def run_evaluation(sessions: Sequence[list[list[Leg]]], policy: SizingPolicy, rules: PropRules = PropRules(),
                   extra_ticks: float = 0.0, keep_path: bool = False) -> EvalResult:
    bal = peak = rules.start
    floor = rules.start - rules.max_dd
    path = [bal] if keep_path else []
    for i, groups in enumerate(sessions):
        day = 0.0
        for legs in groups:
            profit_now = bal - rules.start
            cushion_now = bal - floor
            gpnl = sum(leg_pnl(l, policy, profit_now, extra_ticks, cushion=cushion_now) for l in legs)
            bal += gpnl
            day += gpnl
            if bal <= floor:
                if keep_path:
                    path.append(bal)
                return EvalResult("fail", i + 1, peak, path)
            if bal - rules.start >= rules.target:
                if keep_path:
                    path.append(bal)
                return EvalResult("pass", i + 1, max(peak, bal), path)
            if rules.soft_stop is not None and day <= rules.soft_stop:
                break
        # End of day: trail the floor on the EOD balance
        if bal > peak:
            peak = bal
            floor = max(floor, rules.floor_lock) if peak >= rules.peak_for_lock else max(floor, peak - rules.max_dd)
        if keep_path:
            path.append(bal)
    return EvalResult("open", len(sessions), peak, path)


def run_funded(
    sessions: Sequence[list[list[Leg]]],
    policy: SizingPolicy,
    rules: PropRules = PropRules(),
    funded: FundedRules = FundedRules(),
    extra_ticks: float = 0.0,
    keep_path: bool = False,
    withdrawal_policy: str = "immediate",  # "immediate" (Policy A) | "patient" (Policy B) | "adaptive" (Policy C)
    adaptive_threshold: float = 750.0,
    adaptive_mode: str = "two_stage",  # "two_stage" | "cushion_aware" | "fixed_target"
) -> dict:
    """
    Simulates a funded trading account under the authoritative LucidFlex 25K rulebook.
    Enforces:
      - 5 separate qualifying profit days (each >= $100 daily net profit).
      - Cycle net profit >= $1.00 compared to previous payout / cycle start.
      - Payout size = 50% of profit above $25,000 base, capped at $1,000 gross.
      - Minimum gross payout request: $500.00 (requires balance >= $26,000.00).
      - 90/10 profit split (90% to trader, 10% to firm). Full gross deducted from balance.
      - Post-payout dynamic cushion decay: remaining cushion >= 400 + (gross_payout - 500).
      - Maximum 5 approved payouts before live promotion (status='promoted_to_live').
      - End-of-day trailing floor: trails $1,000 behind peak balance until peak >= $26,100, then locks at $25,100.
    """
    bal = peak = funded.start_balance
    floor = funded.start_balance - funded.max_trailing_dd
    payouts: list[tuple[int, float]] = []
    payout_records: list[dict] = []
    cyc = 0
    pdays = 0
    cycle_start_balance = bal
    qualifying_days_to_p1 = 0
    sessions_to_p1: int | None = None
    path = [bal] if keep_path else []
    floor_path = [floor] if keep_path else []

    for i, groups in enumerate(sessions):
        day = 0.0
        breached = False
        for legs in groups:
            profit_now = bal - funded.start_balance
            cushion_now = bal - floor
            gpnl = sum(leg_pnl(l, policy, profit_now, extra_ticks, cushion=cushion_now) for l in legs)
            bal += gpnl
            day += gpnl
            if bal <= floor:
                breached = True
                break
            if rules.soft_stop is not None and day <= rules.soft_stop:
                break
        if keep_path:
            path.append(bal)
            floor_path.append(floor)
        if breached:
            res = dict(
                status="breach",
                sessions=i + 1,
                payouts=payouts,
                payout_records=payout_records,
                infant_mortality=(len(payouts) == 0),
                qualifying_days_to_p1=qualifying_days_to_p1,
                sessions_to_p1=sessions_to_p1,
                completed_payouts=len(payouts),
            )
            if keep_path:
                res["path"] = path
                res["floor_path"] = floor_path
            return res

        cyc += 1
        is_qualifying = (day >= funded.profit_day_threshold)
        if is_qualifying:
            pdays += 1
            if len(payouts) == 0:
                qualifying_days_to_p1 += 1

        # End of day: trail the floor on the EOD balance
        if bal > peak:
            peak = bal
            floor = max(floor, funded.post_payout_floor) if peak >= funded.floor_lock_peak else max(floor, peak - funded.max_trailing_dd)

        # Check payout eligibility
        cycle_net_profit = bal - cycle_start_balance
        if (
            len(payouts) < funded.max_payouts
            and pdays >= funded.min_profit_days
            and cycle_net_profit >= funded.min_cycle_net_profit
        ):
            profit_above_base = max(0.0, bal - funded.start_balance)
            available_payout = min(funded.max_payout, profit_above_base * funded.payout_fraction)

            if available_payout >= funded.min_payout:
                pol = withdrawal_policy.lower()
                gross_wd = 0.0

                if pol in ("immediate", "immediate_minimum"):
                    # Policy A — Immediate Harvest: Request minimum $500 gross as soon as eligible
                    gross_wd = funded.min_payout
                elif pol in ("patient", "patient_maximum"):
                    # Policy B — Patient Harvest: Wait until full $1,000 cap is reachable ($27,000 balance / $1,900 pre-cushion)
                    current_cushion = bal - floor
                    if available_payout >= funded.max_payout and current_cushion >= 1900.0:
                        gross_wd = funded.max_payout
                elif pol in ("adaptive", "adaptive_cushion"):
                    # Adaptive Cushion Harvest family
                    current_cushion = bal - floor
                    if adaptive_mode == "two_stage":
                        # Two-Stage: Payout 1 de-risks at $500; Payouts 2-5 wait for adaptive_threshold
                        if len(payouts) == 0:
                            gross_wd = funded.min_payout
                        else:
                            req_pre_cushion = 900.0 + (adaptive_threshold - 500.0) * 2.0
                            if available_payout >= adaptive_threshold and current_cushion >= req_pre_cushion:
                                gross_wd = adaptive_threshold
                    elif adaptive_mode == "cushion_aware":
                        # Policy C2 — Adaptive Cushion-Aware Dynamic:
                        # Payout 1: De-risk immediately at $500 minimum to suppress Infant Mortality.
                        # Payouts 2-5: Require pre-payout cushion >= $1,400 (balance >= $26,500, available >= $750).
                        # When cushion >= $1,400, harvest available 50% profit (up to $1,000 cap).
                        # This ensures post-payout cushion is always >= $650 (and up to $900+ at $27,000).
                        if len(payouts) == 0:
                            gross_wd = funded.min_payout
                        else:
                            if current_cushion >= 1400.0 and available_payout >= 750.0:
                                gross_wd = available_payout
                            else:
                                gross_wd = 0.0  # Withhold to build cushion
                    elif adaptive_mode in ("fixed_target", "fixed_threshold"):
                        # Fixed threshold benchmark (e.g. Policy D at $750)
                        req_pre_cushion = 900.0 + (adaptive_threshold - 500.0) * 2.0
                        if available_payout >= adaptive_threshold and current_cushion >= req_pre_cushion:
                            gross_wd = adaptive_threshold
                    else:
                        if available_payout >= adaptive_threshold:
                            gross_wd = adaptive_threshold
                else:
                    gross_wd = available_payout

                if gross_wd >= funded.min_payout:
                    req_cushion = funded.required_post_payout_cushion(gross_wd)
                    post_bal = bal - gross_wd
                    post_floor = max(floor, funded.post_payout_floor)
                    if (post_bal - post_floor >= req_cushion) and (post_bal > post_floor):
                        # Payout approved and executed
                        trader_net = round(gross_wd * funded.split, 2)
                        firm_share = round(gross_wd - trader_net, 2)
                        bal = post_bal
                        floor = post_floor
                        payout_idx = len(payouts) + 1
                        payouts.append((i + 1, trader_net))
                        payout_records.append({
                            "payout_number": payout_idx,
                            "session": i + 1,
                            "gross_payout": gross_wd,
                            "trader_net": trader_net,
                            "firm_share": firm_share,
                            "pre_balance": bal + gross_wd,
                            "post_balance": bal,
                            "floor": floor,
                            "post_cushion": bal - floor,
                            "qualifying_days": pdays,
                        })
                        # Reset cycle counters
                        cyc = 0
                        pdays = 0
                        cycle_start_balance = bal
                        if len(payouts) == 1:
                            sessions_to_p1 = i + 1
                        if keep_path:
                            path[-1] = bal
                            floor_path[-1] = floor
                        if len(payouts) >= funded.max_payouts:
                            res = dict(
                                status="promoted_to_live",
                                sessions=i + 1,
                                payouts=payouts,
                                payout_records=payout_records,
                                infant_mortality=False,
                                qualifying_days_to_p1=qualifying_days_to_p1,
                                sessions_to_p1=sessions_to_p1,
                                completed_payouts=len(payouts),
                            )
                            if keep_path:
                                res["path"] = path
                                res["floor_path"] = floor_path
                            return res

    res = dict(
        status="open",
        sessions=len(sessions),
        payouts=payouts,
        payout_records=payout_records,
        infant_mortality=False,
        qualifying_days_to_p1=qualifying_days_to_p1,
        sessions_to_p1=sessions_to_p1,
        completed_payouts=len(payouts),
    )
    if keep_path:
        res["path"] = path
        res["floor_path"] = floor_path
    return res


def block_bootstrap_sessions(n_sessions: int, length: int, block: int, rng: np.random.Generator) -> np.ndarray:
    starts = rng.integers(0, n_sessions - block + 1, size=length // block + 1)
    return (starts[:, None] + np.arange(block)[None, :]).ravel()[:length]


def bootstrap_prop(session_legs, policy: SizingPolicy, *, n_sims: int = 10_000, block: int = 10, horizon: int = 750,
                   rules: PropRules = PropRules(), extra_ticks: float = 0.0, n_paths: int = 0, seed: int = 42,
                   funded: FundedRules | None = None, funded_horizon: int = 252,
                   funded_policy: SizingPolicy | None = None) -> dict:
    rng = np.random.default_rng(seed)
    n = len(session_legs)
    status, sess, peaks, paths, funded_out = [], [], [], [], []
    f_policy = funded_policy if funded_policy is not None else policy
    for i in range(n_sims):
        idx = block_bootstrap_sessions(n, horizon, block, rng)
        res = run_evaluation([session_legs[j] for j in idx], policy, rules, extra_ticks, keep_path=i < n_paths)
        status.append(res.status)
        sess.append(res.sessions)
        peaks.append(res.peak)
        if i < n_paths:
            paths.append((res.status, res.path))
        if funded is not None and res.status == "pass":
            fidx = block_bootstrap_sessions(n, funded_horizon, block, rng)
            funded_out.append(run_funded([session_legs[j] for j in fidx], f_policy, rules, funded, extra_ticks))
    status, sess, peaks = np.array(status), np.array(sess), np.array(peaks)
    return dict(status=status, sessions=sess, peaks=peaks, paths=paths, funded=funded_out,
                pass_rate=float((status == "pass").mean() * 100), fail_rate=float((status == "fail").mean() * 100),
                open_rate=float((status == "open").mean() * 100))


def chronological_prop(session_legs, calendar: Sequence[str], policy: SizingPolicy, rules: PropRules = PropRules(),
                       extra_ticks: float = 0.0) -> dict:
    """(a) start an evaluation on every historical session; (b) back-to-back attempts from day one."""
    n = len(session_legs)
    every = [run_evaluation(session_legs[s:], policy, rules, extra_ticks) for s in range(n)]
    every_df = pd.DataFrame(dict(start=list(calendar), status=[r.status for r in every], sessions=[r.sessions for r in every]))
    attempts, s = [], 0
    while s < n:
        r = run_evaluation(session_legs[s:], policy, rules, extra_ticks)
        end = min(s + r.sessions - 1, n - 1)
        attempts.append(dict(start=calendar[s], end=calendar[end], status=r.status, sessions=r.sessions))
        if r.status == "open":
            break
        s = end + 1
    return dict(every_start=every_df, back_to_back=pd.DataFrame(attempts))


def summarize_prop(res: dict, calendar_days_per_session: float) -> dict:
    st, ss = res["status"], res["sessions"]
    p, f = ss[st == "pass"], ss[st == "fail"]
    pct = lambda a, q: float(np.percentile(a, q)) if a.size else np.nan  # noqa: E731
    return dict(pass_rate=res["pass_rate"], fail_rate=res["fail_rate"], open_rate=res["open_rate"],
                pass_p10=pct(p, 10), pass_p25=pct(p, 25), pass_med=pct(p, 50), pass_p75=pct(p, 75), pass_p90=pct(p, 90),
                fail_med=pct(f, 50), pass_med_cal_days=pct(p, 50) * calendar_days_per_session,
                pass_p90_cal_days=pct(p, 90) * calendar_days_per_session)


def funded_summary(funded_runs: list[dict], pass_rate_pct: float, fee: float) -> dict:
    if not funded_runs:
        return dict(n=0)
    counts = np.array([len(r["payouts"]) for r in funded_runs])
    nets = np.array([sum(p[1] for p in r["payouts"]) for r in funded_runs])
    ladder = {k: float((counts >= k).mean() * 100) for k in range(1, 6)}
    ev = pass_rate_pct / 100 * nets.mean() - fee
    return dict(n=len(funded_runs), counts=counts, nets=nets, ladder=ladder, mean_net=float(nets.mean()),
                median_net=float(np.median(nets)), zero_payout_pct=float((counts == 0).mean() * 100), ev_per_attempt=float(ev))


def sequential_attempt_economics(pass_rate_pct: float, fee: float, max_attempts: int = 10) -> pd.DataFrame:
    """Back-to-back retries (approximately independent). Parallel copy-traded accounts are NOT independent."""
    p = pass_rate_pct / 100
    k = np.arange(1, max_attempts + 1)
    return pd.DataFrame(dict(attempts=k, p_pass_within=(1 - (1 - p) ** k) * 100, worst_case_fees=k * fee))


# ───────────────────────────────────────────────────────────────────────────────
# Ratchet Grid Search & Funded Transition Experiments
# ───────────────────────────────────────────────────────────────────────────────
def compute_pareto_frontier(df: pd.DataFrame) -> pd.DataFrame:
    """Marks boolean `is_pareto` on the DataFrame trading off pass_rate (max) vs pass_med_sessions (min)."""
    is_pareto = []
    n = len(df)
    pass_rates = df["pass_rate"].to_numpy()
    med_sessions = df["pass_med_sessions"].to_numpy()
    for i in range(n):
        pr_i = pass_rates[i]
        med_i = med_sessions[i]
        dominated = False
        for j in range(n):
            if i == j:
                continue
            pr_j = pass_rates[j]
            med_j = med_sessions[j]
            if (pr_j >= pr_i and med_j <= med_i) and (pr_j > pr_i or med_j < med_i):
                dominated = True
                break
        is_pareto.append(not dominated)
    df["is_pareto"] = is_pareto
    return df


def compute_pareto_frontier_3d(
    df: pd.DataFrame,
    ev_col: str = "net_lifetime_ev",
    im_col: str = "infant_mortality_pct",
    promo_col: str = "live_promotion_pct",
    key_col: str = "policy_key",
    tol: float = 1e-9,
) -> pd.DataFrame:
    """
    Computes the mathematical 3D Pareto frontier across:
      1. Funded-Account Lifecycle Payout EV (`ev_col` — MAXIMIZE)
      2. Infant Mortality % (`im_col` — MINIMIZE)
      3. Live Promotion % (`promo_col` — MAXIMIZE)

    A candidate policy i is dominated by candidate policy j iff:
      - ev[j] >= ev[i] - tol
      - im[j] <= im[i] + tol
      - promo[j] >= promo[i] - tol
    AND at least one inequality is strict beyond `tol`.
    """
    out = df.copy()
    n = len(out)
    if n == 0:
        out["is_pareto_3d"] = []
        out["dominated_by"] = []
        return out

    evs = out[ev_col].to_numpy(dtype=float)
    ims = out[im_col].to_numpy(dtype=float)
    promos = out[promo_col].to_numpy(dtype=float)
    keys = out[key_col].astype(str).tolist() if key_col in out.columns else [str(k) for k in range(n)]

    is_pareto_3d = []
    dominated_by = []
    for i in range(n):
        dominators = []
        for j in range(n):
            if i == j:
                continue
            weak_dom = (
                (evs[j] >= evs[i] - tol)
                and (ims[j] <= ims[i] + tol)
                and (promos[j] >= promos[i] - tol)
            )
            strict_dom = (
                (evs[j] > evs[i] + tol)
                or (ims[j] < ims[i] - tol)
                or (promos[j] > promos[i] + tol)
            )
            if weak_dom and strict_dom:
                dominators.append(keys[j])
        is_pareto_3d.append(len(dominators) == 0)
        dominated_by.append(", ".join(dominators) if dominators else "None")

    out["is_pareto_3d"] = is_pareto_3d
    out["dominated_by"] = dominated_by
    return out


def _eval_ratchet_grid_point(t2: float, t3: float, legs: list[list[Leg]], precomputed_paths: list[np.ndarray],
                             rules: PropRules = PropRules(), extra_ticks: float = 0.0) -> dict:
    policy = SizingPolicy(name=f"Ratchet_{int(t2)}_{int(t3)}", kind="ratchet",
                          tiers=((float(t3), 4), (float(t2), 3), (-np.inf, 2)))
    status, sess = [], []
    for p in precomputed_paths:
        res = run_evaluation([legs[j] for j in p], policy, rules, extra_ticks)
        status.append(res.status)
        sess.append(res.sessions)
    status = np.array(status)
    sess = np.array(sess)
    p_mask = status == "pass"
    f_mask = status == "fail"
    pass_sess = sess[p_mask]
    fail_sess = sess[f_mask]
    pass_rate = float(p_mask.mean() * 100)
    fail_rate = float(f_mask.mean() * 100)
    pass_med = float(np.median(pass_sess)) if len(pass_sess) else np.nan
    pass_p90 = float(np.percentile(pass_sess, 90)) if len(pass_sess) else np.nan
    pass_mean = float(np.mean(pass_sess)) if len(pass_sess) else np.nan
    fail_med = float(np.median(fail_sess)) if len(fail_sess) else np.nan
    fail_mean = float(np.mean(fail_sess)) if len(fail_sess) else np.nan
    pass_p10 = float(np.percentile(pass_sess, 10)) if len(pass_sess) else np.nan
    pass_p25 = float(np.percentile(pass_sess, 25)) if len(pass_sess) else np.nan
    pass_p75 = float(np.percentile(pass_sess, 75)) if len(pass_sess) else np.nan

    return dict(
        t2=float(t2),
        t3=float(t3),
        pass_rate=pass_rate,
        fail_rate=fail_rate,
        pass_med_sessions=pass_med,
        pass_p90_sessions=pass_p90,
        pass_mean_sessions=pass_mean,
        fail_med_sessions=fail_med,
        fail_mean_sessions=fail_mean,
        pass_p10_sessions=pass_p10,
        pass_p25_sessions=pass_p25,
        pass_p75_sessions=pass_p75,
    )


def _eval_ratchet_grid_worker(args: tuple) -> dict:
    return _eval_ratchet_grid_point(*args)


def run_ratchet_grid_search(
    legs: list[list[Leg]],
    t2_range: tuple[float, float, float] = (200.0, 400.0, 25.0),
    t3_range: tuple[float, float, float] = (500.0, 850.0, 25.0),
    n_sims: int = 5000,
    seed: int = 42,
    block_size: int = 10,
    horizon: int = 750,
    extra_ticks: float = 0.0,
    rules: PropRules = PropRules(),
    n_jobs: int = -1,
) -> pd.DataFrame:
    t2_vals = np.arange(t2_range[0], t2_range[1] + 1e-6, t2_range[2])
    t3_vals = np.arange(t3_range[0], t3_range[1] + 1e-6, t3_range[2])
    grid_points = [(float(t2), float(t3)) for t2 in t2_vals for t3 in t3_vals if t3 > t2]

    # Pre-generate paths for Common Random Numbers (CRN)
    rng = np.random.default_rng(seed)
    n_sessions = len(legs)
    precomputed_paths = [
        block_bootstrap_sessions(n_sessions, horizon, block_size, rng)
        for _ in range(n_sims)
    ]

    records = []
    if n_jobs != 1 and len(grid_points) > 1:
        import os
        from concurrent.futures import ProcessPoolExecutor
        workers = os.cpu_count() or 4 if n_jobs < 0 else n_jobs
        args_list = [(t2, t3, legs, precomputed_paths, rules, extra_ticks) for t2, t3 in grid_points]
        with ProcessPoolExecutor(max_workers=min(workers, len(grid_points))) as executor:
            records = list(executor.map(_eval_ratchet_grid_worker, args_list))
    else:
        for t2, t3 in grid_points:
            records.append(_eval_ratchet_grid_point(t2, t3, legs, precomputed_paths, rules, extra_ticks))

    df = pd.DataFrame(records)
    df = compute_pareto_frontier(df)
    return df


def run_funded_transition_experiments(
    legs: list[list[Leg]],
    eval_policy: SizingPolicy,
    funded_policies: dict[str, SizingPolicy],
    n_sims: int = 5000,
    seed: int = 42,
    funded_horizon: int = 252,
    eval_horizon: int = 750,
    block_size: int = 10,
    extra_ticks: float = 0.0,
    rules: PropRules = PropRules(),
    funded_rules: FundedRules = FundedRules(),
) -> pd.DataFrame:
    rng_eval = np.random.default_rng(seed)
    rng_funded = np.random.default_rng(seed + 1000)
    n_sessions = len(legs)

    eval_paths = [
        block_bootstrap_sessions(n_sessions, eval_horizon, block_size, rng_eval)
        for _ in range(n_sims)
    ]
    funded_paths = [
        block_bootstrap_sessions(n_sessions, funded_horizon, block_size, rng_funded)
        for _ in range(n_sims)
    ]

    # Step 1: Run evaluation using eval_policy across all n_sims
    passed_sim_indices = []
    for i in range(n_sims):
        res = run_evaluation([legs[j] for j in eval_paths[i]], eval_policy, rules, extra_ticks)
        if res.status == "pass":
            passed_sim_indices.append(i)

    pass_rate_pct = len(passed_sim_indices) / n_sims * 100.0

    # Step 2: For each policy in funded_policies, simulate the passed accounts
    results = []
    for pol_name, pol in funded_policies.items():
        payout_counts = []
        net_extractions = []
        sessions_to_p1 = []
        statuses = []
        for sim_idx in passed_sim_indices:
            f_sess = [legs[j] for j in funded_paths[sim_idx]]
            f_res = run_funded(f_sess, pol, rules, funded_rules, extra_ticks)
            payouts = f_res["payouts"]
            statuses.append(f_res["status"])
            cnt = len(payouts)
            payout_counts.append(cnt)
            total_net = sum(p[1] for p in payouts)
            net_extractions.append(total_net)
            if cnt > 0:
                sessions_to_p1.append(payouts[0][0])

        payout_counts = np.array(payout_counts) if len(payout_counts) else np.array([0])
        net_extractions = np.array(net_extractions) if len(net_extractions) else np.array([0.0])
        sessions_to_p1 = np.array(sessions_to_p1) if len(sessions_to_p1) else np.array([])

        zero_payout_pct = float((payout_counts == 0).mean() * 100.0)
        mean_payouts = float(payout_counts.mean())
        median_payouts = float(np.median(payout_counts))
        mean_net = float(net_extractions.mean())
        median_net = float(np.median(net_extractions))
        p90_net = float(np.percentile(net_extractions, 90))
        mean_s_p1 = float(sessions_to_p1.mean()) if len(sessions_to_p1) else np.nan
        med_s_p1 = float(np.median(sessions_to_p1)) if len(sessions_to_p1) else np.nan

        net_lifetime_ev = float((pass_rate_pct / 100.0) * mean_net - rules.eval_fee)

        p1_rate = float((payout_counts >= 1).mean() * 100.0)
        p2_rate = float((payout_counts >= 2).mean() * 100.0)
        p3_rate = float((payout_counts >= 3).mean() * 100.0)
        p4_rate = float((payout_counts >= 4).mean() * 100.0)
        p5_rate = float((payout_counts >= 5).mean() * 100.0)

        results.append(dict(
            policy_name=pol_name,
            policy_desc=pol.name,
            zero_payout_pct=zero_payout_pct,
            mean_payouts=mean_payouts,
            median_payouts=median_payouts,
            mean_net_extraction=mean_net,
            median_net_extraction=median_net,
            p90_net_extraction=p90_net,
            mean_sessions_to_payout1=mean_s_p1,
            median_sessions_to_payout1=med_s_p1,
            net_lifetime_ev=net_lifetime_ev,
            payout_ge_1_pct=p1_rate,
            payout_ge_2_pct=p2_rate,
            payout_ge_3_pct=p3_rate,
            payout_ge_4_pct=p4_rate,
            payout_5_pct=p5_rate,
        ))

    return pd.DataFrame(results)


def run_withdrawal_policy_comparison(
    legs: list[list[Leg]],
    eval_policy: SizingPolicy,
    funded_policy: SizingPolicy,
    withdrawal_policies: dict[str, dict],
    n_sims: int = 10_000,
    seed: int = 42,
    funded_horizon: int = 252,
    eval_horizon: int = 750,
    block_size: int = 10,
    extra_ticks: float = 0.0,
    rules: PropRules = PropRules(),
    funded_rules: FundedRules = FundedRules(),
    path_gen_horizon: int | None = None,
) -> tuple[pd.DataFrame, dict[str, list[dict]]]:
    """
    Evaluates withdrawal policies (Policy A, Policy B, Policy C) under CRN block-bootstrap.
    Computes all Section 4 metrics across identical evaluation and funded simulation paths:
      - Probability of surviving to first payout
      - Infant mortality probability (account failure before first payout)
      - Average qualifying trading days before first payout
      - Average time to first payout
      - Average gross payout
      - Average trader net payout
      - Average cumulative trader net earnings
      - Average number of completed payouts
      - Probability of completing all five payouts / reaching live promotion
      - Account failure probability
      - Average terminal sessions
      - Average remaining cushion following each payout
      - Total Net Lifetime EV
    """
    rng_eval = np.random.default_rng(seed)
    rng_funded = np.random.default_rng(seed + 1000)
    n_sessions = len(legs)
    gen_h = max(funded_horizon, path_gen_horizon) if path_gen_horizon is not None else funded_horizon

    eval_paths = [
        block_bootstrap_sessions(n_sessions, eval_horizon, block_size, rng_eval)
        for _ in range(n_sims)
    ]
    funded_paths = [
        block_bootstrap_sessions(n_sessions, gen_h, block_size, rng_funded)[:funded_horizon]
        for _ in range(n_sims)
    ]

    # Pre-screen evaluation passes
    passed_sim_indices = []
    for i in range(n_sims):
        res = run_evaluation([legs[j] for j in eval_paths[i]], eval_policy, rules, extra_ticks)
        if res.status == "pass":
            passed_sim_indices.append(i)

    pass_rate_pct = len(passed_sim_indices) / n_sims * 100.0

    summary_records = []
    all_sim_runs: dict[str, list[dict]] = {}

    for pol_key, pol_cfg in withdrawal_policies.items():
        w_policy = pol_cfg.get("withdrawal_policy", "immediate")
        adapt_thresh = pol_cfg.get("adaptive_threshold", 750.0)
        adapt_mode = pol_cfg.get("adaptive_mode", "two_stage")
        pol_label = pol_cfg.get("label", pol_key)

        runs = []
        payout_counts = []
        cumulative_nets = []
        sessions_to_p1_list = []
        qualifying_days_to_p1_list = []
        terminal_sessions = []
        all_gross_payouts = []
        all_trader_nets = []
        post_cushions = []
        breach_count = 0
        infant_mortality_count = 0
        promoted_count = 0

        for sim_idx in passed_sim_indices:
            f_sess = [legs[j] for j in funded_paths[sim_idx]]
            res_f = run_funded(
                f_sess,
                policy=funded_policy,
                rules=rules,
                funded=funded_rules,
                extra_ticks=extra_ticks,
                withdrawal_policy=w_policy,
                adaptive_threshold=adapt_thresh,
                adaptive_mode=adapt_mode,
            )
            runs.append(res_f)

            cnt = res_f["completed_payouts"]
            payout_counts.append(cnt)
            tot_net = sum(p[1] for p in res_f["payouts"])
            cumulative_nets.append(tot_net)
            terminal_sessions.append(res_f["sessions"])

            if res_f["status"] == "breach":
                breach_count += 1
                if cnt == 0:
                    infant_mortality_count += 1
            elif res_f["status"] in ("promoted_to_live", "max_payouts") or cnt >= funded_rules.max_payouts:
                promoted_count += 1

            if cnt >= 1:
                if res_f["sessions_to_p1"] is not None:
                    sessions_to_p1_list.append(res_f["sessions_to_p1"])
                qualifying_days_to_p1_list.append(res_f["qualifying_days_to_p1"])

            for prec in res_f.get("payout_records", []):
                all_gross_payouts.append(prec["gross_payout"])
                all_trader_nets.append(prec["trader_net"])
                post_cushions.append(prec["post_cushion"])

        all_sim_runs[pol_key] = runs

        n_passed = len(passed_sim_indices)
        pc = np.array(payout_counts) if len(payout_counts) else np.array([0])
        cn = np.array(cumulative_nets) if len(cumulative_nets) else np.array([0.0])
        s_p1 = np.array(sessions_to_p1_list) if len(sessions_to_p1_list) else np.array([])
        q_p1 = np.array(qualifying_days_to_p1_list) if len(qualifying_days_to_p1_list) else np.array([])
        t_sess = np.array(terminal_sessions) if len(terminal_sessions) else np.array([])
        ag = np.array(all_gross_payouts) if len(all_gross_payouts) else np.array([])
        an = np.array(all_trader_nets) if len(all_trader_nets) else np.array([])
        cush = np.array(post_cushions) if len(post_cushions) else np.array([])

        survive_p1_pct = float((pc >= 1).mean() * 100.0) if n_passed else 0.0
        infant_mortality_pct = float(infant_mortality_count / n_passed * 100.0) if n_passed else 0.0
        account_failure_pct = float(breach_count / n_passed * 100.0) if n_passed else 0.0
        live_promotion_pct = float(promoted_count / n_passed * 100.0) if n_passed else 0.0
        p5_pct = float((pc >= 5).mean() * 100.0) if n_passed else 0.0

        # Additional failure & censoring metrics per Section 2 & 4
        post_p1_fail_count = breach_count - infant_mortality_count
        post_p1_fail_pct_funded = float(post_p1_fail_count / n_passed * 100.0) if n_passed else 0.0
        p1_survivor_count = int((pc >= 1).sum())
        post_p1_fail_rate_given_p1 = float(post_p1_fail_count / p1_survivor_count * 100.0) if p1_survivor_count else 0.0
        censored_alive_count = n_passed - breach_count - promoted_count
        censored_alive_pct = float(censored_alive_count / n_passed * 100.0) if n_passed else 0.0

        # Unconditional rates (per evaluation ticket started, denominator = n_sims)
        survive_p1_pct_uncond = float((pc >= 1).sum() / n_sims * 100.0)
        infant_mortality_pct_uncond = float(infant_mortality_count / n_sims * 100.0)
        overall_failure_pct_uncond = float(breach_count / n_sims * 100.0)
        live_promotion_pct_uncond = float(promoted_count / n_sims * 100.0)

        mean_cum_net = float(cn.mean()) if cn.size else 0.0
        median_cum_net = float(np.median(cn)) if cn.size else 0.0
        p90_cum_net = float(np.percentile(cn, 90)) if cn.size else 0.0

        mean_payout_count = float(pc.mean()) if pc.size else 0.0
        mean_gross_payout = float(ag.mean()) if ag.size else 0.0
        mean_trader_net = float(an.mean()) if an.size else 0.0
        mean_post_cushion = float(cush.mean()) if cush.size else 0.0

        mean_sessions_p1 = float(s_p1.mean()) if s_p1.size else np.nan
        median_sessions_p1 = float(np.median(s_p1)) if s_p1.size else np.nan
        mean_q_days_p1 = float(q_p1.mean()) if q_p1.size else np.nan
        mean_term_sess = float(t_sess.mean()) if t_sess.size else np.nan

        funded_lifecycle_payout_ev = float((pass_rate_pct / 100.0) * mean_cum_net - rules.eval_fee)

        summary_records.append({
            "policy_key": pol_key,
            "policy_label": pol_label,
            "pass_rate_pct": pass_rate_pct,
            "survive_first_payout_pct": survive_p1_pct,
            "survive_first_payout_pct_uncond": survive_p1_pct_uncond,
            "infant_mortality_pct": infant_mortality_pct,
            "infant_mortality_pct_uncond": infant_mortality_pct_uncond,
            "account_failure_pct": account_failure_pct,
            "account_failure_pct_uncond": overall_failure_pct_uncond,
            "post_first_payout_failure_pct": post_p1_fail_pct_funded,
            "post_p1_fail_rate_given_p1": post_p1_fail_rate_given_p1,
            "censored_alive_pct": censored_alive_pct,
            "live_promotion_pct": live_promotion_pct,
            "live_promotion_pct_uncond": live_promotion_pct_uncond,
            "five_payouts_pct": p5_pct,
            "mean_completed_payouts": mean_payout_count,
            "mean_gross_payout": mean_gross_payout,
            "mean_trader_net_payout": mean_trader_net,
            "mean_cumulative_net_earnings": mean_cum_net,
            "median_cumulative_net_earnings": median_cum_net,
            "p90_cumulative_net_earnings": p90_cum_net,
            "mean_qualifying_days_to_p1": mean_q_days_p1,
            "mean_sessions_to_p1": mean_sessions_p1,
            "median_sessions_to_p1": median_sessions_p1,
            "mean_terminal_sessions": mean_term_sess,
            "mean_post_payout_cushion": mean_post_cushion,
            "funded_lifecycle_payout_ev": funded_lifecycle_payout_ev,
            "net_lifetime_ev": funded_lifecycle_payout_ev,
        })

    out_df = pd.DataFrame(summary_records)
    out_df = compute_pareto_frontier_3d(out_df)
    return out_df, all_sim_runs
