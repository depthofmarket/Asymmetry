# Pre-Registration: Late-Day Cross-Asset MOC Institutional Imbalance Drive (`H11`, `14:00–15:30 ET`)

- **Date:** `2026-10-30`
- **Status:** `PRE-REGISTERED (LOCKED BEFORE EXECUTION)`
- **Candidate ID:** `H11` (`late_day_cross_asset_moc_drive_h11`)
- **Target Window:** `14:00–15:30 ET` (Final 90 minutes before the `15:30–16:00 ET` cash close settlement window; completely non-overlapping with Strategy 1's `09:45 ET` entry)
- **Evaluation Horizons:** `6`, `12`, `24`, `30` bars (1-minute bars, next-bar open execution `entry_lag_bars=1`; all 30-bar horizons complete at or before `16:00 ET` RTH close)

---

## 1. Structural Mechanism & Motivation

1. **Why Late-Day Institutional Closing Flow (`14:00–15:30 ET`) Is Structurally Distinct:**
   - Between `14:00 ET` and `15:30 ET`, institutional execution desks pre-position ahead of `15:50 ET` NYSE/Nasdaq Market-on-Close (MOC) imbalance cutoffs, leveraged/inverse ETF daily rebalancing (whose required delta hedging scales in the same direction as the session's cumulative return), and cash-close VWAP/TWAP completion benchmarks.
   - Prior single-asset research (`2026-05-21_power_hour_signal_gate.md`) showed that `15:00–15:30 ET` trend acceptance produced `+4.11` pts net at 24 bars (`58.58%` hit rate, `75.0%` positive periods, placebo $p = 0.0000$) in `2021–2024`, and `H10` diagnostics showed `hour == 14` (`14:00–14:29 ET`) was the sole net-positive intraday hour (`+4.86` pts net at 6 bars).
   - However, the earlier `2026-05-21` single-asset specification used hardcoded point thresholds (`20.0` pts session move, `8.0` pts 30m momentum, `3.0` pts VWAP distance) that were not scale-invariant across `2016–2020` (`NQ ~ 4,500–12,000`) vs. `2021–2024` (`NQ ~ 11,000–21,000`), and lacked cross-asset confirmation (`ES`, NYSE `$TICK`, and `VX` VIX futures) to filter out isolated tech-sector noise.
2. **Lesson Incorporated from `H10`:**
   - Requiring extreme `$TICK >= +500 / <= -500` spikes (`H10`) selects short-term program exhaustion climaxes. Instead, `H11` requires **scale-invariant percentage session & 30m acceptance on both `NQ` and `ES`**, paired with **supportive (non-contradictory) 15-minute NYSE `$TICK` breadth and 30-minute `VX` volatility behavior**.

---

## 2. Point-in-Time Data Inputs & Alignment Rules (Zero Lookahead)

1. **`NQ` 1-Minute Bars (`data/processed/nq_1m_2010_2026_et.parquet`):**
   - Standard 1-minute RTH bars (`09:30–16:00 ET`).
2. **`ES` 1-Minute Bars (`data/raw/es_1m_2014_2026_et.parquet`):**
   - Deduplicated front-month continuous `ES` 1-minute bars aligned to `NQ` 1-minute timestamps.
3. **NYSE `$TICK` 5-Minute Bars (`data/processed/macro_context/nyse_tick_5m_et.parquet`):**
   - 5-minute bar labeled at `bar_start` (`09:30, 09:35, ...`) completes at `completion_time = bar_start + 4 minutes` (`09:34, 09:39, ...`). Aligned to 1-minute bar `t` via backward `merge_asof` on `completion_time <= t` within the same session date.
4. **VIX Futures (`VX`) 5-Minute Bars (`data/processed/macro_context/vix_futures_5m_et.parquet`):**
   - Highest-volume front-month 5-minute bar completed at `completion_time = bar_start + 4 minutes`, aligned to 1-minute bar `t` via backward `merge_asof` on `completion_time <= t` within the same session date.

---

## 3. Exact Signal Rules (`H11`)

Evaluated on 1-minute RTH bars `t` within `14:00 <= time <= 15:30 ET` where all four cross-asset feeds are present:

### A. Long Signal (`signal = +1`)
1. **Scale-Invariant `NQ` Intraday Trend Acceptance:**
   - Cumulative session return from `09:30 ET` RTH open: `nq_session_ret = (nq_close - nq_rth_open) / nq_rth_open >= +0.0040` (`+0.40%`).
   - Session directional efficiency: `nq_move_to_range = abs(nq_close - nq_rth_open) / (nq_session_high - nq_session_low) >= 0.45`.
   - Session close location: `nq_close_pos = (nq_close - nq_session_low) / (nq_session_high - nq_session_low) >= 0.80` (top 20% of session range).
   - Above RTH VWAP: `nq_vwap_dist_pct = (nq_close - nq_vwap) / nq_close >= +0.0005` (`+0.05%`).
   - Trailing 30-minute `NQ` momentum: `nq_ret_30m = (nq_close / nq_close[t-30]) - 1.0 >= +0.0008` (`+0.08%`).
2. **Cross-Asset `ES` Lockstep Confirmation:**
   - `ES` cumulative session return: `es_session_ret = (es_close - es_rth_open) / es_rth_open >= +0.0025` (`+0.25%`).
   - `ES` session close location: `es_close_pos = (es_close - es_session_low) / (es_session_high - es_session_low) >= 0.70`.
   - `ES` trailing 30-minute momentum: `es_ret_30m = (es_close / es_close[t-30]) - 1.0 >= +0.0005` (`+0.05%`).
3. **Cross-Asset NYSE `$TICK` Breadth & `VX` Volatility Confirmation:**
   - Completed 5-minute `$TICK` 3-bar (15m) rolling mean: `tick_15m_mean >= 0.0` and most recent completed 5m `tick_close >= -200.0`.
   - Completed 5-minute `VX` 6-bar (30m) change: `vx_change_30m = vx_close - vx_close_lag6 <= +0.05`.

### B. Short Signal (`signal = -1`)
1. **Scale-Invariant `NQ` Intraday Trend Acceptance:**
   - `nq_session_ret <= -0.0040` (`-0.40%`).
   - `nq_move_to_range >= 0.45`.
   - `nq_close_pos <= 0.20` (bottom 20% of session range).
   - Below RTH VWAP: `nq_vwap_dist_pct <= -0.0005` (`-0.05%`).
   - `nq_ret_30m <= -0.0008` (`-0.08%`).
2. **Cross-Asset `ES` Lockstep Confirmation:**
   - `es_session_ret <= -0.0025` (`-0.25%`).
   - `es_close_pos <= 0.30`.
   - `es_ret_30m <= -0.0005` (`-0.05%`).
3. **Cross-Asset NYSE `$TICK` Breadth & `VX` Volatility Confirmation:**
   - `tick_15m_mean <= 0.0` and `tick_close <= +200.0`.
   - `vx_change_30m >= -0.05`.

### C. One-Signal-Per-Session Rule & Composite Score
- At most **1 signal per RTH session** (first bar in `14:00–15:30 ET` satisfying all conditions).
- Continuous signed feature `moc_drive_score` combining normalized `nq_move_to_range`, `es_close_pos`, `nq_ret_30m`, and `tick_15m_mean` alignment.

---

## 4. Pre-Registered Falsification Criteria (Temporal Signal Research Gate)

Evaluated via `scripts/run_temporal_signal_research_report.py` across `transition:2016-01-01:2020-12-31` and `recent_development:2021-01-01:2024-12-31` with `entry_price_col="open"`, `entry_lag_bars=1`, base cost `1.50` NQ points (`$30/RT`), and stress costs `2.00` and `4.25` points:
1. **Minimum Sample Size:** $\ge 150$ active signals in `2021–2024` and $\ge 150$ active signals in `2016–2020`.
2. **Primary Split (`2021–2024`) Net Expectancy:** Positive net mean signed return (`> +1.50` pts net after `1.50`pt cost) at `12`, `24`, or `30` bars, positive bootstrap CI lower bound, positive placebo edge ($p \le 0.05$), and $\ge 60\%$ positive semi-annual periods.
3. **Supporting Split (`2016–2020`) Directionality:** Net mean signed return $> 0.0$ pts after `1.50`pt cost at the primary horizon.
4. **Automatic Rejection:** If either split fails net expectancy or placebo edge, reject `H11` and log a formal postmortem in `docs/research_postmortems/`.
