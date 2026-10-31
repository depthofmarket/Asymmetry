# Pre-Registration: Late-Day `VX`-Crush & Cross-Asset Power-Hour Long Drive (`H13`, `14:45–15:30 ET`)

- **Date:** `2026-10-30`
- **Status:** `PRE-REGISTERED (LOCKED BEFORE EXECUTION)`
- **Candidate ID:** `H13` (`late_day_vx_crush_power_hour_long_h13`)
- **Target Window:** `14:45–15:30 ET` (Final 45-minute institutional MOC accumulation & Power-Hour window; all 30-bar horizons exit at or before `16:00 ET` RTH close)
- **Direction:** `Long-Only` (`signal = +1`)
- **Evaluation Horizons:** `6`, `12`, `24`, `30` bars (1-minute bars, next-bar open execution `entry_lag_bars=1`)

---

## 1. Structural Mechanism & Motivation

1. **Asymmetric Late-Day Vanna/Charm & Leveraged Rebalancing Flow:**
   - As trading approaches the `16:00 ET` cash close on a positive trend day where implied volatility (`VX`) is compressing, two institutional flows act strictly in the **Long** direction:
     1. **Dealer Vanna & Charm Hedging:** As intraday implied volatility crushes (`vx_change_30m <= -0.05` / `vx_change_from_open <= -0.05`) and time-to-expiration decays toward `16:00 ET`, options market makers holding short OTM/ATM call gamma/vanna must buy index futures (`ES` and `NQ`) to remain delta-neutral.
     2. **Leveraged ETF & MOC Pre-Positioning (`14:45–15:30 ET`):** Ahead of the `15:50 ET` NYSE/Nasdaq MOC cutoff, closing basket flows concentrate between `14:45` and `15:30 ET`.
2. **Empirical Basis from Prior Falsifications (`H11` & `2026-05-21 Power Hour`):**
   - `H11` failed in the aggregate (`+0.19` pts net) for three structural reasons: (a) opening at `14:00 ET` caused `81.4%` of trades to fire an hour before Power Hour; (b) shorting at the lows (`-3.97` pts net) fought dealer short-covering; and (c) allowing flat/expanding `VX` (`-3.02` pts net) diluted the `VX`-crush regime (`+8.60` pts net at 30 bars).
   - `H13` isolates the exact structural mechanism: **Long-only `14:45–15:30 ET` trend acceptance across `NQ` and `ES`, paired with active `VX` volatility compression and positive NYSE `$TICK` breadth**.

---

## 2. Point-in-Time Data Inputs & Alignment Rules (Zero Lookahead)

1. **`NQ` 1-Minute Bars (`data/raw/nq_1m_2014_2026_merged.parquet`):** Continuous front-month 1-minute RTH bars (`09:30–16:00 ET`).
2. **`ES` 1-Minute Bars (`data/raw/es_1m_2014_2026_et.parquet`):** Continuous front-month 1-minute RTH bars aligned to `NQ` timestamps.
3. **NYSE `$TICK` 5-Minute Bars (`data/processed/macro_context/nyse_tick_5m_et.parquet`):** Completed at `completion_time = bar_start + 4 minutes`, aligned via backward `merge_asof` (`completion_time <= t`) within the same session date.
4. **VIX Futures (`VX`) 5-Minute Bars (`data/processed/macro_context/vix_futures_5m_et.parquet`):** Completed at `completion_time = bar_start + 4 minutes`, aligned via backward `merge_asof` (`completion_time <= t`) within the same session date.

---

## 3. Exact Signal Rules (`H13`)

Evaluated on 1-minute RTH bars `t` within `14:45 <= time <= 15:30 ET`:

1. **Scale-Invariant `NQ` Intraday Trend Acceptance:**
   - Cumulative session return from `09:30 ET` open: `nq_session_ret_pct = (nq_close - nq_rth_open) / nq_rth_open >= +0.0035` (`+0.35%`).
   - Session directional efficiency: `nq_move_to_range = (nq_close - nq_rth_open) / (nq_session_high - nq_session_low) >= 0.45`.
   - Session close location: `nq_close_pos = (nq_close - nq_session_low) / (nq_session_high - nq_session_low) >= 0.78` (top 22% of session range).
   - Above RTH VWAP: `nq_vwap_dist_pct = (nq_close - nq_vwap) / nq_close >= +0.0005` (`+0.05%`).
   - Trailing 30-minute `NQ` momentum: `nq_ret_30m_pct = (nq_close / nq_close[t-30]) - 1.0 >= +0.0006` (`+0.06%`).
2. **Cross-Asset `ES` Lockstep Confirmation:**
   - `ES` cumulative session return: `es_session_ret_pct = (es_close - es_rth_open) / es_rth_open >= +0.0020` (`+0.20%`).
   - `ES` session close location: `es_close_pos = (es_close - es_session_low) / (es_session_high - es_session_low) >= 0.70`.
   - `ES` trailing 30-minute momentum: `es_ret_30m_pct = (es_close / es_close[t-30]) - 1.0 >= +0.0004` (`+0.04%`).
3. **Active `VX` Volatility Compression & NYSE `$TICK` Breadth Support:**
   - Completed 5-minute `VX`: `vx_change_30m <= 0.0` AND (`vx_change_30m <= -0.05` OR `vx_change_from_open <= -0.05`).
   - Completed 5-minute `$TICK`: `tick_15m_mean >= +50.0` and `tick_5m_close >= -100.0`.
4. **One-Signal-Per-Session & Structural Barrier Parameters:**
   - Maximum **1 signal per RTH session** (first qualifying bar in `14:45–15:30 ET`).
   - Structural stop: `stop_points = clip(nq_30m_range_points, 20.0, 60.0)`.
   - Structural target: `target_points = stop_points * 1.50` (`1.50x` R:R).

---

## 4. Pre-Registered Falsification Criteria

1. **Temporal Signal Research Gate (`2016–2020` and `2021–2024`):**
   - Minimum `100` active signals in `2021–2024` and `100` active signals in `2016–2020`.
   - Positive net mean signed return (`> +2.00` pts net after `1.50`pt cost) in `2021–2024` at `12`, `24`, or `30` bars, positive bootstrap CI lower bound, positive placebo edge ($p \le 0.05$), and $\ge 55\%$ positive periods.
   - Supporting split (`2016–2020`) net mean signed return $> 0.0$ pts after `1.50`pt cost.
2. **Barrier-Managed Strategy Backtest Gate:**
   - Must also achieve Profit Factor $\ge 1.25$ and positive net expectancy in the bar-by-bar stop/target-managed strategy backtest before any holdout or forward-test consideration.
