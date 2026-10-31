# Pre-Registration: `ES` vs. `NQ` Intermarket SMT Divergence + `$TICK` Exhaustion Reversal (`H12`, `10:20–14:00 ET`)

- **Date:** `2026-10-30`
- **Status:** `PRE-REGISTERED (LOCKED BEFORE EXECUTION)`
- **Candidate ID:** `H12` (`es_nq_smt_tick_divergence_h12`)
- **Target Window:** `10:20–14:00 ET` (Post-opening-range morning and midday RTH auction; completely non-overlapping with Strategy 1's `09:45 ET` entry)
- **Evaluation Horizons:** `6`, `12`, `24`, `30` bars (1-minute bars, next-bar open execution `entry_lag_bars=1`)

---

## 1. Structural Mechanism & Motivation

1. **Empirical Finding from `H10`:**
   - In `H10`, chasing 30-minute breakouts on `NQ` and `ES` during `10:09–13:59 ET` produced `~0.0` pts gross forward drift (`-1.49` to `-1.89` pts net after `1.50`pt cost) because post-open / midday range extensions frequently represent **stop runs / liquidity sweeps** rather than genuine institutional trend initiation.
2. **Intermarket SMT Divergence (`ES` vs. `NQ`) + NYSE `$TICK` Breadth Non-Confirmation:**
   - Because `NQ` (Nasdaq-100) and `ES` (S&P 500) are tightly coupled via index-arbitrage baskets, a genuine institutional repricing breaks prior structural highs/lows on **both** indices simultaneously with strong NYSE cash-equity breadth (`$TICK`).
   - When one index (`NQ` or `ES`) sweeps its prior 45-minute RTH high or low (`[t-50 .. t-5]`) during the recent 5-minute window (`[t-4 .. t]`), **while the sister index fails to break its corresponding 45-minute high or low**, an **Intermarket SMT (Smart Money / Structural) Divergence** occurs.
   - If that single-index sweep is simultaneously unconfirmed by NYSE `$TICK` breadth (`tick_5m_close` failing to reach extreme territory) and VIX futures (`VX` failing to confirm the breakout), and `NQ` immediately rejects the sweep level (`nq_close` closing back inside the prior 45-minute range and in the rejection half of the 5-minute sweep range), trapped breakout chasers are forced to liquidate back across the range.

---

## 2. Point-in-Time Data Inputs & Alignment Rules (Zero Lookahead)

1. **`NQ` 1-Minute Bars (`data/raw/nq_1m_2014_2026_merged.parquet`):**
   - Continuous front-month 1-minute RTH bars (`09:30–16:00 ET`).
2. **`ES` 1-Minute Bars (`data/raw/es_1m_2014_2026_et.parquet`):**
   - Continuous front-month 1-minute RTH bars aligned to `NQ` timestamps.
3. **NYSE `$TICK` 5-Minute Bars (`data/processed/macro_context/nyse_tick_5m_et.parquet`):**
   - Completed at `completion_time = bar_start + 4 minutes`, aligned to 1-minute bar `t` via backward `merge_asof` (`completion_time <= t`) within the same session date.
4. **VIX Futures (`VX`) 5-Minute Bars (`data/processed/macro_context/vix_futures_5m_et.parquet`):**
   - Completed at `completion_time = bar_start + 4 minutes`, aligned to 1-minute bar `t` via backward `merge_asof` (`completion_time <= t`) within the same session date.

---

## 3. Exact Signal Rules (`H12`)

Let:
- `nq_prior45_high`, `nq_prior45_low`: rolling 45-bar RTH high and low of `NQ` over `[t-50 .. t-5]` (`shift(5).rolling(45, min_periods=45)` within the session).
- `es_prior45_high`, `es_prior45_low`: rolling 45-bar RTH high and low of `ES` over `[t-50 .. t-5]` (`shift(5).rolling(45, min_periods=45)` within the session).
- `nq_recent5_high`, `nq_recent5_low`: rolling 5-bar RTH high and low of `NQ` over `[t-4 .. t]`.
- `es_recent5_high`, `es_recent5_low`: rolling 5-bar RTH high and low of `ES` over `[t-4 .. t]`.
- `nq_5m_close_pos = (nq_close - nq_recent5_low) / (nq_recent5_high - nq_recent5_low)`.

Evaluated on 1-minute bars `t` in `10:20 <= time <= 14:00 ET`:

### A. Bullish SMT Divergence Reversal (`signal = +1`, Fading a False Breakdown)
1. **Intermarket Low Sweep Divergence:**
   - Either `NQ` swept its prior 45m low while `ES` held above its prior 45m low:
     `(nq_recent5_low < nq_prior45_low) & (es_recent5_low >= es_prior45_low)`
   - Or `ES` swept its prior 45m low while `NQ` held above its prior 45m low:
     `(es_recent5_low < es_prior45_low) & (nq_recent5_low >= nq_prior45_low)`
2. **`NQ` Price Rejection & Reclaim at Bar `t`:**
   - `nq_close >= nq_prior45_low` (reclaimed/held the prior 45-minute low)
   - `nq_5m_close_pos >= 0.55` (closed in the top 45% of the trailing 5-minute sweep range)
   - `nq_close > nq_open` (bullish 1-minute rejection bar)
3. **Cross-Asset `$TICK` & `VX` Non-Confirmation of Breakdown:**
   - Completed 5-minute `$TICK`: `tick_5m_close >= -150.0` and `tick_15m_mean >= -200.0` (cash equities are not panic-dumping).
   - Completed 5-minute `VX`: `vx_15m_change <= +0.05` (volatility futures are not spiking).

### B. Bearish SMT Divergence Reversal (`signal = -1`, Fading a False Breakout)
1. **Intermarket High Sweep Divergence:**
   - Either `NQ` swept its prior 45m high while `ES` held below its prior 45m high:
     `(nq_recent5_high > nq_prior45_high) & (es_recent5_high <= es_prior45_high)`
   - Or `ES` swept its prior 45m high while `NQ` held below its prior 45m high:
     `(es_recent5_high > es_prior45_high) & (nq_recent5_high <= nq_prior45_high)`
2. **`NQ` Price Rejection & Failure at Bar `t`:**
   - `nq_close <= nq_prior45_high` (failed to hold above the prior 45-minute high)
   - `nq_5m_close_pos <= 0.45` (closed in the bottom 45% of the trailing 5-minute sweep range)
   - `nq_close < nq_open` (bearish 1-minute rejection bar)
3. **Cross-Asset `$TICK` & `VX` Non-Confirmation of Breakout:**
   - Completed 5-minute `$TICK`: `tick_5m_close <= +150.0` and `tick_15m_mean <= +200.0` (cash equities are not broadly surging).
   - Completed 5-minute `VX`: `vx_15m_change >= -0.05` (volatility futures are not crushing).

### C. One-Signal-Per-Session Rule & Diagnostic Contexts
- Maximum **1 signal per RTH session** (first qualifying bar in `10:20–14:00 ET`).
- Diagnostic context columns:
  - `smt_leader`: `"nq_swept_es_held"` vs. `"es_swept_nq_held"`
  - `vwap_alignment`: `"with_vwap_trend"` vs. `"counter_vwap_fade"`
  - `smt_window`: `"morning_1020_1200"` vs. `"midday_1201_1400"`

---

## 4. Pre-Registered Falsification Criteria (Temporal Signal Research Gate)

Evaluated via `scripts/run_temporal_signal_research_report.py` across `transition:2016-01-01:2020-12-31` and `recent_development:2021-01-01:2024-12-31` with `entry_price_col="open"`, `entry_lag_bars=1`, base cost `1.50` NQ points (`$30/RT`), and stress costs `2.00` and `4.25` points:
1. **Minimum Sample Size:** $\ge 150$ active signals in `2021–2024` and $\ge 150$ active signals in `2016–2020`.
2. **Primary Split (`2021–2024`) Net Expectancy:** Positive net mean signed return (`> +1.50` pts net after `1.50`pt cost) at `12`, `24`, or `30` bars, positive bootstrap CI lower bound, positive placebo edge ($p \le 0.05$), and $\ge 55\%$ positive semi-annual periods.
3. **Supporting Split (`2016–2020`) Directionality:** Net mean signed return $> 0.0$ pts after `1.50`pt cost at the primary horizon.
4. **Automatic Rejection:** If either split fails net expectancy or placebo edge, reject `H12` and log a formal postmortem in `docs/research_postmortems/`.
