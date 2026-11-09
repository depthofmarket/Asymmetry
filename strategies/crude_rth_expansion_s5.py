"""
Candidate Strategy S5: Crude Oil Post-Fix Range Expansion (10:15 ET).
Primary Instrument: Micro WTI Crude Oil (MCL / CME NYMEX; $100.00/point, tick size 0.01 pt / $1.00/tick).

Hypothesis & Microstructure:
Exploits structural post-fix range expansion following the 10:00–10:14 ET London Gold PM Fix
and morning US macroeconomic survey release clearing into the 11:30 ET European cash equity close.
Measures the 09:30–10:14 ET consolidation range (H_cons, L_cons), filtered by daily ATR(14) >= 2.00,
daily RVOL(20) >= 1.25, and daily SMA20 > SMA50 macro trend alignment.
Enforces strict 45-cent stop loss ($45), 90-cent target (2.0R / $90), +1.0R breakeven ratchet
locking +2 ticks, and mandatory 12:30 ET session flatten.

Governing Rules:
- Rule 1: One source of truth (quarantined under StrategyTier.CANDIDATE).
- Rule 2: No naked numbers (complete provenance metadata, date ranges, data hash).
- Rule 3: Standardized provenance footers.
- Rule 4: Warnings travel with the number.
- Rule 5: Automatic recording into results/backtest_provenance.db.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class CrudeRthExpansionParams:
    """Quantitative parameters for Candidate S5 Crude Oil Post-Fix Range Expansion."""

    # Strategy Identification
    strategy_id: str = "crude_rth_expansion_s5"
    strategy_name: str = "Crude Oil Post-Fix Range Expansion (10:15 ET)"
    instrument: str = "MCL"
    asset_class: str = "COMMODITY_ENERGY"

    # Contract Specifications & Transaction Costs
    contract_value: float = 100.0        # $100.00 per full point on MCL ($1.00/cent/tick)
    tick_size: float = 0.01              # $0.01 tick size ($1.00 per tick)
    commission_round_trip: float = 3.50  # $3.50 per round turn ($1.75/side micro energy)
    slippage_limit_pts: float = 0.01     # 1 tick adverse on limit target fills ($1.00)
    slippage_stop_pts: float = 0.02      # 2 ticks adverse on market/stop/flatten fills ($2.00)
    slippage_entry_pts: float = 0.01     # 1 tick adverse on breakout entry stop-limit fills ($1.00)

    # Session Timing (Eastern Time, in minutes from midnight)
    consolidation_start_m: int = 570     # 09:30 ET
    consolidation_end_m: int = 614       # 10:14 ET
    entry_start_m: int = 615             # 10:15 ET
    entry_end_m: int = 675               # 11:15 ET
    session_flatten_m: int = 750         # 12:30 ET

    # Regime Conditioning Gates
    min_atr14: float = 2.00              # Daily ATR(14) >= 2.00 points (lagged)
    min_rvol20: float = 1.25             # Daily RVOL(20) >= 1.25 (lagged baseline)
    min_consolidation_range: float = 0.30 # Min consolidation range ($0.30 / 30 ticks)
    max_consolidation_range: float = 1.20 # Max consolidation range ($1.20 / 120 ticks)
    min_consolidation_bars: int = 35     # Min bars in consolidation window to ensure data completeness
    min_trade_bars: int = 30             # Min bars in trade window
    warmup_rth_sessions: int = 50        # Number of initial RTH sessions for indicator warmup

    # Bracket Risk Management
    stop_loss_pts: float = 0.45          # Stop loss distance 45 cents ($45.00 / 1.0R)
    profit_target_pts: float = 0.90      # Profit target distance 90 cents ($90.00 / 2.0R)
    breakeven_trigger_pts: float = 0.45  # Excursion to trigger breakeven (+1.0R / 45 cents)
    breakeven_lock_pts: float = 0.02     # Locked profit at breakeven (+2 ticks / +$2.00)
    max_trades_per_session: int = 1      # Strict 1 trade per session limit


def calculate_crude_rth_features(
    df: pd.DataFrame,
    params: CrudeRthExpansionParams,
) -> Tuple[pd.DataFrame, Dict[str, Dict[str, Any]]]:
    """
    Computes daily regime features (ATR14, RVOL20, SMA20, SMA50, MacroTrend) and
    extracts RTH 1-minute bars with strict point-in-time causality.
    """
    out = df.copy()
    if "time" not in out.columns:
        raise ValueError("DataFrame must contain 'time' column.")

    out.sort_values("time", inplace=True)
    out.reset_index(drop=True, inplace=True)

    out["time"] = pd.to_datetime(out["time"])
    out["m"] = out["time"].dt.hour * 60 + out["time"].dt.minute
    out["date_str"] = out["time"].dt.strftime("%Y-%m-%d")

    # 1. Compute Daily Statistics with Shift(1) for strict point-in-time integrity
    daily_stats = (
        out.groupby("date_str")
        .agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        })
        .reset_index()
    )

    daily_stats["atr14"] = (
        (daily_stats["high"] - daily_stats["low"]).rolling(14).mean().shift(1)
    )
    daily_stats["vol20"] = daily_stats["volume"].rolling(20).mean().shift(1)
    daily_stats["rvol"] = daily_stats["volume"].shift(1) / daily_stats["vol20"].clip(lower=1.0)
    daily_stats["sma20"] = daily_stats["close"].rolling(20).mean().shift(1)
    daily_stats["sma50"] = daily_stats["close"].rolling(50).mean().shift(1)
    daily_stats["macro_trend"] = np.where(
        daily_stats["sma20"] > daily_stats["sma50"], 1, -1
    )

    daily_map = daily_stats.set_index("date_str").to_dict("index")

    # 2. Extract RTH bars (09:00 to 12:30 ET / minutes 540 to 750)
    rth_df = out[(out["m"] >= 540) & (out["m"] <= params.session_flatten_m)].copy()
    rth_df.reset_index(drop=True, inplace=True)

    return rth_df, daily_map


def generate_signals(
    rth_df: pd.DataFrame,
    daily_map: Dict[str, Dict[str, Any]],
    params: CrudeRthExpansionParams,
) -> pd.DataFrame:
    """
    Evaluates daily regime conditioning gates and consolidation bounds to detect
    bar-close breakouts occurring in the 10:15–11:15 ET window.
    """
    signals = pd.DataFrame(index=rth_df.index)
    signals["time"] = rth_df["time"]
    signals["date_str"] = rth_df["date_str"]
    signals["m"] = rth_df["m"]
    signals["close"] = rth_df["close"]
    signals["signal"] = 0
    signals["signal_type"] = ""
    signals["entry_price"] = np.nan
    signals["stop_price"] = np.nan
    signals["target_price"] = np.nan
    signals["h_cons"] = np.nan
    signals["l_cons"] = np.nan
    signals["atr14"] = np.nan
    signals["rvol"] = np.nan
    signals["macro_trend"] = np.nan

    day_groups = {d: g for d, g in rth_df.groupby("date_str")}
    sorted_dates = sorted(day_groups.keys())

    # Skip initial warmup sessions for indicator stabilization
    active_dates = sorted_dates[params.warmup_rth_sessions :]

    for d in active_dates:
        d_info = daily_map.get(d)
        day_df = day_groups.get(d)

        if not d_info or day_df is None:
            continue
        if pd.isna(d_info.get("atr14")) or pd.isna(d_info.get("rvol")) or pd.isna(d_info.get("sma50")):
            continue

        # Regime Gate 1: Volatility runway (ATR14 >= 2.00)
        # Regime Gate 2: Institutional volume participation (RVOL20 >= 1.25)
        if d_info["atr14"] < params.min_atr14 or d_info["rvol"] < params.min_rvol20:
            continue

        # Consolidation Window: 09:30 to 10:14 ET [570, 614]
        cons = day_df[(day_df["m"] >= params.consolidation_start_m) & (day_df["m"] <= params.consolidation_end_m)]
        trade_bars = day_df[(day_df["m"] >= params.entry_start_m) & (day_df["m"] <= params.session_flatten_m)]

        if len(cons) < params.min_consolidation_bars or len(trade_bars) < params.min_trade_bars:
            continue

        h_cons = float(cons["high"].max())
        l_cons = float(cons["low"].min())
        cons_range = h_cons - l_cons

        # Consolidation Validity Gate: $0.30 <= Range <= $1.20
        if cons_range < params.min_consolidation_range or cons_range > params.max_consolidation_range:
            continue

        macro_trend = int(d_info["macro_trend"])

        # Check entry triggers in [10:15, 11:15 ET]
        for idx, row in trade_bars.iterrows():
            if row["m"] > params.entry_end_m:
                break

            close_p = float(row["close"])
            sig = 0
            sig_type = ""
            entry_p = 0.0
            stop_p = 0.0
            target_p = 0.0

            # Long breakout: close > H_cons and macro_trend == +1
            if close_p > h_cons and macro_trend == 1:
                sig = 1
                sig_type = "crude_rth_expansion_long"
                entry_p = close_p + params.slippage_entry_pts
                stop_p = entry_p - params.stop_loss_pts
                target_p = entry_p + params.profit_target_pts

            # Short breakout: close < L_cons and macro_trend == -1
            elif close_p < l_cons and macro_trend == -1:
                sig = -1
                sig_type = "crude_rth_expansion_short"
                entry_p = close_p - params.slippage_entry_pts
                stop_p = entry_p + params.stop_loss_pts
                target_p = entry_p - params.profit_target_pts

            if sig != 0:
                signals.loc[idx, "signal"] = sig
                signals.loc[idx, "signal_type"] = sig_type
                signals.loc[idx, "entry_price"] = entry_p
                signals.loc[idx, "stop_price"] = stop_p
                signals.loc[idx, "target_price"] = target_p
                signals.loc[idx, "h_cons"] = h_cons
                signals.loc[idx, "l_cons"] = l_cons
                signals.loc[idx, "atr14"] = d_info["atr14"]
                signals.loc[idx, "rvol"] = d_info["rvol"]
                signals.loc[idx, "macro_trend"] = macro_trend
                break  # Max 1 trade per session

    return signals


def simulate_intrabar_execution(
    rth_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    params: CrudeRthExpansionParams,
) -> pd.DataFrame:
    """
    Simulates intrabar execution on 1-minute bars with conservative conflict resolution,
    breakeven ratcheting, and full friction accounting.
    """
    sig_indices = signals_df[signals_df["signal"] != 0].index
    trades: List[Dict[str, Any]] = []
    trade_counter = 1

    day_groups = {d: g for d, g in rth_df.groupby("date_str")}

    for idx in sig_indices:
        sig_row = signals_df.loc[idx]
        pos = int(sig_row["signal"])
        sig_type = str(sig_row["signal_type"])
        d = str(sig_row["date_str"])
        entry_time = sig_row["time"]
        ep = float(sig_row["entry_price"])
        sp = float(sig_row["stop_price"])
        tp = float(sig_row["target_price"])

        day_df = day_groups.get(d)
        if day_df is None:
            continue

        loc_in_day = day_df.index.get_loc(idx)
        be = False
        exit_price: Optional[float] = None
        exit_reason: Optional[str] = None
        exit_time: Optional[pd.Timestamp] = None
        hold_bars = 0
        slip_dollars = 0.0

        # Position is managed starting on subsequent bars until flatten at 12:30 ET
        for k in range(loc_in_day + 1, len(day_df)):
            hold_bars += 1
            bar = day_df.iloc[k]
            b_high = float(bar["high"])
            b_low = float(bar["low"])
            b_close = float(bar["close"])
            b_time = bar["time"]
            b_m = int(bar["m"])

            # 1. Conflict & Hit Evaluation against the stop price active at the start of bar k.
            # OHLC data does not establish intrabar sequencing; a breakeven ratchet triggered
            # during bar k cannot protect on the same bar k.
            hit_stop = (b_low <= sp) if pos == 1 else (b_high >= sp)
            hit_target = (b_high >= tp) if pos == 1 else (b_low <= tp)

            if hit_stop and hit_target:
                # Conservative resolution: Stop loss wins conflict
                hit_target = False

            if hit_stop:
                if be:
                    exit_price = sp
                    exit_reason = "breakeven"
                    # Entry slip ($1.00) already embedded in ep, breakeven fill at exact sp
                    slip_dollars = params.slippage_entry_pts * params.contract_value
                else:
                    exit_price = sp - params.slippage_stop_pts if pos == 1 else sp + params.slippage_stop_pts
                    exit_reason = "stop_loss"
                    slip_dollars = (params.slippage_entry_pts + params.slippage_stop_pts) * params.contract_value

                exit_time = b_time
                break

            elif hit_target:
                exit_price = tp - params.slippage_limit_pts if pos == 1 else tp + params.slippage_limit_pts
                exit_reason = "profit_target"
                slip_dollars = (params.slippage_entry_pts + params.slippage_limit_pts) * params.contract_value
                exit_time = b_time
                break

            elif b_m == params.session_flatten_m or k == len(day_df) - 1:
                # Hard session flatten at 12:30 ET (2 ticks adverse market slippage)
                exit_price = b_close - params.slippage_stop_pts if pos == 1 else b_close + params.slippage_stop_pts
                exit_reason = "time_flatten"
                slip_dollars = (params.slippage_entry_pts + params.slippage_stop_pts) * params.contract_value
                exit_time = b_time
                break

            # 2. Breakeven Ratchet at +1.0R (+45 cents) — activates for subsequent bars k + 1 onwards
            if not be:
                if (pos == 1 and b_high >= ep + params.breakeven_trigger_pts) or (
                    pos == -1 and b_low <= ep - params.breakeven_trigger_pts
                ):
                    sp = ep + params.breakeven_lock_pts if pos == 1 else ep - params.breakeven_lock_pts
                    be = True

        if exit_price is not None:
            gross_pts = (exit_price - ep) if pos == 1 else (ep - exit_price)
            gross_pnl = gross_pts * params.contract_value
            commission = params.commission_round_trip
            net_pnl = gross_pnl - commission

            trades.append({
                "trade_id": f"T_{trade_counter:05d}",
                "date": d,
                "symbol": params.instrument,
                "direction": "long" if pos == 1 else "short",
                "signal_type": sig_type,
                "entry_time": entry_time,
                "exit_time": exit_time,
                "entry_price": ep,
                "exit_price": exit_price,
                "contracts": 1,
                "gross_pnl": float(gross_pnl),
                "commission": float(commission),
                "slippage": float(slip_dollars),
                "net_pnl": float(net_pnl),
                "exit_reason": exit_reason,
                "hold_bars": hold_bars,
            })
            trade_counter += 1

    return pd.DataFrame(trades)


class CrudeRthExpansionS5:
    """
    Candidate S5: Crude Oil Post-Fix Range Expansion Strategy Engine.
    Encapsulates feature engineering, breakout signal evaluation, and intrabar backtest execution.
    """

    def __init__(self, params: Optional[CrudeRthExpansionParams] = None):
        self.params = params or CrudeRthExpansionParams()
        self.trades_df: pd.DataFrame = pd.DataFrame()
        self.metrics: Dict[str, Any] = {}

    def backtest(
        self,
        data: Path | str | pd.DataFrame,
        start_date: str = "2021-01-04",
        end_date: str = "2026-10-30",
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Runs the verified candidate backtest on continuous 1-minute CME NYMEX data.
        """
        if isinstance(data, (str, Path)):
            df = pd.read_parquet(data)
        else:
            df = data.copy()

        df["time"] = pd.to_datetime(df["time"])

        # Evaluation Window Filtering:
        # Note: To guarantee exact 50 RTH sessions of warmup from 2021-01-04,
        # we filter df to start from start_date (or 2021-01-01 if full year).
        if start_date:
            df = df[df["time"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["time"] <= pd.Timestamp(f"{end_date} 23:59:59")]

        df.reset_index(drop=True, inplace=True)

        # 1. Feature Engineering & Daily Regime Conditioning
        rth_df, daily_map = calculate_crude_rth_features(df, self.params)

        # 2. Signal Generation
        signals_df = generate_signals(rth_df, daily_map, self.params)

        # 3. Intrabar Execution Simulation
        trades_df = simulate_intrabar_execution(rth_df, signals_df, self.params)
        self.trades_df = trades_df

        # 4. Metric Computation
        if len(trades_df) > 0:
            total_trades = len(trades_df)
            wins = (trades_df["net_pnl"] > 0).sum()
            losses = (trades_df["net_pnl"] < 0).sum()
            win_rate = float((wins / total_trades) * 100.0)

            gross_profit = float(trades_df[trades_df["net_pnl"] > 0]["net_pnl"].sum())
            gross_loss = float(abs(trades_df[trades_df["net_pnl"] < 0]["net_pnl"].sum()))
            profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else 999.0
            net_profit = float(trades_df["net_pnl"].sum())

            # Trailing Drawdown calculation
            cumulative = trades_df["net_pnl"].cumsum()
            hwm = np.maximum.accumulate(np.maximum(cumulative, 0.0))
            drawdown = hwm - cumulative
            max_drawdown = float(drawdown.max()) if len(drawdown) > 0 else 0.0

            largest_win = float(trades_df["net_pnl"].max())
            largest_win_pct = float((largest_win / net_profit * 100.0)) if net_profit > 0 else 0.0

            # Daily Sharpe
            daily_pnl = trades_df.groupby("date")["net_pnl"].sum()
            if len(daily_pnl) > 1 and daily_pnl.std() > 0:
                sharpe = float((daily_pnl.mean() / daily_pnl.std()) * np.sqrt(252))
            else:
                sharpe = 0.0

            avg_win = float(trades_df[trades_df["net_pnl"] > 0]["net_pnl"].mean()) if wins > 0 else 0.0
            avg_loss = float(abs(trades_df[trades_df["net_pnl"] < 0]["net_pnl"].mean())) if losses > 0 else 0.0
            win_loss_ratio = float(avg_win / avg_loss) if avg_loss > 0 else 0.0

            self.metrics = {
                "total_trades": total_trades,
                "wins": int(wins),
                "losses": int(losses),
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "gross_profit": gross_profit,
                "gross_loss": gross_loss,
                "net_profit": net_profit,
                "max_drawdown": max_drawdown,
                "sharpe_ratio": sharpe,
                "largest_win": largest_win,
                "largest_win_pct_of_net": largest_win_pct,
                "win_loss_ratio": win_loss_ratio,
                "avg_trade_pnl": float(net_profit / total_trades),
            }
        else:
            self.metrics = {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "net_profit": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "largest_win": 0.0,
                "largest_win_pct_of_net": 0.0,
                "win_loss_ratio": 0.0,
                "avg_trade_pnl": 0.0,
            }

        return self.trades_df, self.metrics
