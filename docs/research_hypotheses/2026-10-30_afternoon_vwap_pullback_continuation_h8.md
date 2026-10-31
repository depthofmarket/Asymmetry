# Afternoon Trend Continuation via Session VWAP Pullback Scalp (H8)

Date: 2026-10-30

Status: Pre-registered hypothesis; awaiting temporal signal gate validation.

---

## 1. Hypothesis & Market Microstructure Rationale

Empirical falsification of Candidates 1 (H5), 2 (H6), and 3 (H7) established a clear structural finding on 1-minute Nasdaq-100 (`NQ`) futures: mean-reversion / level-fading setups struggle to overcome institutional execution friction (`1.50`–`2.00` pts), whereas directional momentum aligned with institutional order flow (Strategy 1, H4) exhibits strong positive expectancy.

In the afternoon session (`13:30–15:15 ET`), following the European close and New York lunch lull (`11:30–13:30 ET`), US institutional execution desks re-engage to complete daily TWAP/VWAP benchmarked orders ahead of the `16:00 ET` cash close.

**The Economic Mechanism:**
1. **Trend Establishment (`09:30–13:30 ET`):** On directional trend days, the session establishes a clear bias relative to the opening print (`rth_open`) and Initial Balance (`09:30–10:30 ET`, `IB`), with cumulative session `VWAP` displaced in the trend direction (`vwap > rth_open` for uptrends, `vwap < rth_open` for downtrends).
2. **Institutional Value Pullback:** Institutional buy/sell programs are benchmarked against RTH `VWAP`. During the mid-day lull or early afternoon, counter-trend retracements that bring price back toward the `VWAP` value zone ($\pm 0.75\sigma_t$) offer institutional algorithms an opportunity to execute in the trend direction at prices near or better than the session volume-weighted average.
3. **Afternoon Trend Resumption (`13:30–15:15 ET`):** Once the pullback is absorbed near `VWAP` and a 1-minute bar breaks the prior bar's extreme with strong close location in the direction of the primary trend, institutional continuation flow drives a secondary afternoon trend leg into the close.

---

## 2. Scale-Invariance Design (2016–2024 Compatibility)

Prior afternoon tests (such as the rejected `15:00` Power Hour hypothesis) suffered from two structural flaws:
1. Buying/selling at the extreme high/low of the day (`close_position >= 0.80`) at `15:00 ET` after the move was already exhausted.
2. Hardcoding fixed point thresholds (`20` pts session move), which represented `0.45%` in 2016 (`NQ ~ 4,500`) vs `0.10%` noise in 2024 (`NQ ~ 20,000`).

H8 eliminates both flaws by:
- **Entering on pullbacks to `VWAP`** (`13:30–15:15 ET`) rather than chasing late-day extremes.
- **Using 100% scale-invariant thresholds**: percentage session return (`0.15%`), Initial Balance structure (`IB_MID`), and dimensionless `VWAP` dispersion bands ($\sigma_t$).

---

## 3. Orthogonality to Strategy 1

This strategy is **100% time-orthogonal to Strategy 1 (`morning_value_area_breakout_h4`)**:
- Strategy 1 enters exclusively at `09:45 ET` and is flat by `10:45 ET`.
- Candidate 4 (H8) enters exclusively between `13:30 ET` and `15:15 ET`.
- The two strategies **never hold concurrent positions**, eliminating intraday margin overlap.

---

## 4. Fixed Pre-Run Assumptions & Point-in-Time Signal Definition

- **Timeframe:** 1-minute continuous NQ OHLCV bars (`nq_1m_2014_2026_merged.parquet`).
- **Session References (Point-in-Time):**
  - `rth_open`: Opening price at `09:30:00 ET`.
  - `ib_high`, `ib_low`, `ib_mid`: Highest high, lowest low, and midpoint of the `09:30–10:30 ET` Initial Balance, frozen at `10:30:00 ET`.
  - `vwap_t`, `vwap_std_t` ($\sigma_t$): Cumulative RTH volume-weighted average price and standard deviation from `09:30:00 ET` through bar $t$.
  - `pullback_low_15`, `pullback_high_15`: Rolling 15-bar minimum low and maximum high over $[t-14, t]$.
- **Active Execution Window:** `13:30:00 ET` to `15:15:00 ET`.
- **Long Setup (Afternoon Uptrend VWAP Pullback & Resumption):**
  1. **Uptrend Regime:**
     - Session return from open: `(close_t - rth_open) / rth_open >= +0.0015` (`+0.15%`).
     - Structural trend alignment: `vwap_t > rth_open` and `close_t > ib_mid` and `close_t > vwap_t`.
  2. **Recent Pullback to VWAP Zone:**
     - Within the last 15 bars, price tested near `VWAP` without breaking trend structure:
       `vwap_t - 0.50 * sigma_t <= pullback_low_15 <= vwap_t + 0.75 * sigma_t`.
  3. **Resumption Trigger Bar:**
     - Current bar breaks above prior bar's high: `close_t > high_{t-1}`.
     - Strong bullish close location: `(close_t - low_t) / (high_t - low_t) >= 0.65`.
     - Not over-extended: `close_t <= vwap_t + 1.75 * sigma_t`.
  4. **Execution:** Direction = Long (`+1.0`), entry at next bar `open` (`entry_lag_bars = 1`).
- **Short Setup (Afternoon Downtrend VWAP Pullback & Resumption):**
  1. **Downtrend Regime:**
     - Session return from open: `(close_t - rth_open) / rth_open <= -0.0015` (`-0.15%`).
     - Structural trend alignment: `vwap_t < rth_open` and `close_t < ib_mid` and `close_t < vwap_t`.
  2. **Recent Pullback to VWAP Zone:**
     - Within the last 15 bars, price bounced near `VWAP` without breaking downtrend structure:
       `vwap_t - 0.75 * sigma_t <= pullback_high_15 <= vwap_t + 0.50 * sigma_t`.
  3. **Resumption Trigger Bar:**
     - Current bar breaks below prior bar's low: `close_t < low_{t-1}`.
     - Strong bearish close location: `(close_t - low_t) / (high_t - low_t) <= 0.35`.
     - Not over-extended: `close_t >= vwap_t - 1.75 * sigma_t`.
  4. **Execution:** Direction = Short (`-1.0`), entry at next bar `open` (`entry_lag_bars = 1`).
- **Deduplication:** Maximum 1 signal per RTH session (first qualifying setup per day).
- **Barriers:**
  - Stop distance: `max(close_t - pullback_low_15, 0.75 * sigma_t)` for longs (symmetric for shorts), clamped to `[12.0, 50.0]` pts.
  - Target distance: `1.5 * stop_points`.

---

## 5. Strict Falsification Criteria

The candidate will be immediately rejected if any of the following occur:
1. Mean return after `1.50` points round-trip transaction cost $\le 0$ across the 2021–2024 development sample.
2. Information Coefficient (conditional `active_ic`) at multi-bar horizon (12–24 bars) $< +0.020$.
3. Clock-matched placebo test shows edge $\le 0$ or bootstrap placebo $p$-value $> 0.10$.
4. Signal fails under `2.00` points cost stress.
5. Transition era (2016–2020) shows negative expectancy across all multi-bar horizons.

---

## 6. Artifact Prefix

`afternoon_vwap_pullback_continuation_h8`
