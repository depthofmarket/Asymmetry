"""
Point-in-Time GARCH(1,1) / GJR-GARCH Volatility Modeling & MVT Band Generator.
Implements the econometric AntiAchismo framework inspired by Jeffy Motta:
- Conditional volatility forecasting sigma_t via recursive GARCH(1,1) / GJR-GARCH.
- Model Volatility Target (MVT 0) anchor: Session VWAP.
- Desvio Padrao (DP +/- 1, 2, 3) statistical envelope bands.
- Statistical exhaustion filter and sweet-spot runway gating.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class GarchCalibration:
    omega: float
    alpha: float
    beta: float
    gamma: float = 0.0  # Asymmetry parameter for GJR-GARCH
    unconditional_vol_pct: float = 1.0


class RecursiveGarchEngine:
    """
    Fast point-in-time GARCH(1,1) and GJR-GARCH recursive volatility engine.
    Designed for zero lookahead and zero runtime latency.
    """

    def __init__(
        self,
        omega: float = 0.05,
        alpha: float = 0.08,
        beta: float = 0.88,
        gamma: float = 0.0,
    ) -> None:
        self.omega = max(float(omega), 1e-6)
        self.alpha = max(float(alpha), 0.0)
        self.beta = max(float(beta), 0.0)
        self.gamma = max(float(gamma), 0.0)

        denom = 1.0 - (self.alpha + self.beta + 0.5 * self.gamma)
        if denom > 1e-4:
            self.unconditional_var = self.omega / denom
        else:
            self.unconditional_var = 1.0
        self.current_var = self.unconditional_var

    def update(self, return_pct: float) -> float:
        """Update conditional variance with completed return observation."""
        r = float(return_pct)
        eps2 = r ** 2
        leverage = self.gamma * eps2 if (r < 0.0 and self.gamma > 0.0) else 0.0
        self.current_var = self.omega + self.alpha * eps2 + leverage + self.beta * self.current_var
        self.current_var = max(self.current_var, 1e-6)
        return float(np.sqrt(self.current_var))

    def forecast_horizon(self, horizon_steps: int = 1) -> float:
        """Forecast cumulative conditional standard deviation over horizon steps."""
        persistent = self.alpha + self.beta + 0.5 * self.gamma
        if horizon_steps <= 1:
            return float(np.sqrt(self.current_var))
        
        # Mean-reverting multi-step variance forecast
        variances = []
        v = self.current_var
        for _ in range(horizon_steps):
            v = self.omega + persistent * v
            variances.append(v)
        return float(np.sqrt(np.mean(variances)))


def compute_mvt_envelope_at_bar(
    rth_bars: pd.DataFrame,
    cond_daily_vol_pct: float,
    *,
    intraday_window_minutes: float = 15.0,
    session_total_minutes: float = 390.0,
) -> dict[str, float]:
    """
    Computes Point-in-Time MVT (Model Volatility Target) and DP (Desvio Padrao) bands.

    Parameters:
    - rth_bars: DataFrame of 1-minute bars from session start (09:30 ET) up to evaluation bar.
    - cond_daily_vol_pct: GARCH 1-day conditional volatility in percent (strictly from prior day).
    - intraday_window_minutes: elapsed duration in minutes (e.g. 15.0 for 09:30-09:45).
    - session_total_minutes: total RTH duration (390 minutes).

    Returns dictionary containing:
    - mvt_0: Session VWAP
    - sigma_pts: Intraday conditional standard deviation in index points
    - dp_pos_1, dp_pos_2, dp_pos_3: Upper standard deviation bands
    - dp_neg_1, dp_neg_2, dp_neg_3: Lower standard deviation bands
    """
    if rth_bars.empty:
        raise ValueError("rth_bars cannot be empty")

    cum_vol = rth_bars["volume"].sum()
    if cum_vol > 0:
        vwap = float((rth_bars["close"] * rth_bars["volume"]).sum() / cum_vol)
    else:
        vwap = float(rth_bars["close"].mean())

    current_price = float(rth_bars.iloc[-1]["close"])
    sigma_daily_pts = current_price * (max(float(cond_daily_vol_pct), 0.05) / 100.0)
    scaling_factor = np.sqrt(max(float(intraday_window_minutes), 1.0) / float(session_total_minutes))
    sigma_intraday_pts = float(sigma_daily_pts * scaling_factor)

    return {
        "mvt_0": vwap,
        "current_price": current_price,
        "sigma_daily_pts": sigma_daily_pts,
        "sigma_intraday_pts": sigma_intraday_pts,
        "dp_pos_1": vwap + 1.0 * sigma_intraday_pts,
        "dp_pos_1_5": vwap + 1.5 * sigma_intraday_pts,
        "dp_pos_2": vwap + 2.0 * sigma_intraday_pts,
        "dp_pos_2_5": vwap + 2.5 * sigma_intraday_pts,
        "dp_pos_3": vwap + 3.0 * sigma_intraday_pts,
        "dp_neg_1": vwap - 1.0 * sigma_intraday_pts,
        "dp_neg_1_5": vwap - 1.5 * sigma_intraday_pts,
        "dp_neg_2": vwap - 2.0 * sigma_intraday_pts,
        "dp_neg_2_5": vwap - 2.5 * sigma_intraday_pts,
        "dp_neg_3": vwap - 3.0 * sigma_intraday_pts,
    }


def evaluate_garch_mvt_filter(
    current_price: float,
    mvt_dict: dict[str, float],
    direction: int,  # +1 for Long, -1 for Short
    *,
    sweet_spot_min_dp: float = 0.30,
    sweet_spot_max_dp: float = 2.20,
    hard_exhaustion_dp: float = 2.50,
) -> dict[str, bool | float | str]:
    """
    Evaluates whether an intended breakout entry passes the GARCH MVT statistical gates:
    - Extension Z-Score: signed distance from MVT 0 in trade direction.
    - is_exhausted: True if price is extended beyond hard exhaustion band (high failure rate).
    - is_sweet_spot: True if price has enough displacement (> 0.30 DP) but ample runway (< 2.20 DP).
    """
    vwap = mvt_dict["mvt_0"]
    sigma = max(mvt_dict["sigma_intraday_pts"], 1e-4)

    # Signed extension in trade direction
    diff = (current_price - vwap) * float(direction)
    z_score = float(diff / sigma)

    is_exhausted = bool(z_score > hard_exhaustion_dp)
    is_sweet_spot = bool(sweet_spot_min_dp <= z_score <= sweet_spot_max_dp)
    is_too_flat = bool(z_score < sweet_spot_min_dp)

    if is_exhausted:
        status = "EXHAUSTED"
        reason = f"Price extended {z_score:.2f} DP in trade direction (overextended exhaustion zone > {hard_exhaustion_dp:.2f} DP)"
    elif is_sweet_spot:
        status = "SWEET_SPOT"
        reason = f"Price extended {z_score:.2f} DP in trade direction (optimal breakout runway [0.30, 2.20] DP)"
    elif is_too_flat:
        status = "COMPRESSED_CHOP"
        reason = f"Price extended {z_score:.2f} DP (too close to VWAP, lacking directional impulse < {sweet_spot_min_dp:.2f} DP)"
    else:
        status = "NORMAL"
        reason = f"Price extension {z_score:.2f} DP"

    return {
        "z_score": z_score,
        "is_exhausted": is_exhausted,
        "is_sweet_spot": is_sweet_spot,
        "is_too_flat": is_too_flat,
        "status": status,
        "reason": reason,
    }
