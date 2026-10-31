# Pre-Registration: Cross-Asset Institutional Program Thrust ($TICK + VX + ES/NQ Lockstep, H10)

**Date:** 2026-10-30  
**Status:** Pre-Registered — Pending Multi-Era Temporal Signal Research Gate  
**Candidate Slot:** Strategy 2 (Orthogonal Cross-Asset Intraday Continuation)  
**Active Evaluation Window:** `10:09 ET` to `14:29 ET` (completed 5-minute bar boundaries `minute % 5 == 4`, entering at `10:10–14:30 ET` open; completely outside `08:30` and `10:00 AM` news release bars)

---

## 1. Market Microstructure Thesis & Why Price-Only NQ Signals Failed

1. **Why Single-Asset Price-Only Setups (`H5`–`H9`) Failed**:
   - Across `2016–2026`, intraday NQ breakouts and pullbacks measured solely from NQ 1-minute OHLCV bars fail to clear `1.50`–`4.25` points of execution friction because single-asset price movement cannot separate thin, noise-driven futures spikes from broad institutional program execution.
2. **The 4-Asset Institutional Program Footprint (`$TICK` + `VX` + `ES` + `NQ`)**:
   - When institutional index desks, CTAs, or systematic risk-parity / vol-targeting funds execute multi-billion-dollar basket programs during regular trading hours (`10:10–14:30 ET`), they leave a simultaneous, unmistakable footprint across four distinct markets:
     1. **NYSE Cash-Equity Basket Breadth (`$TICK`)**: Program buy/sell algorithms sweep NYSE cash stocks simultaneously, driving 5-minute `$TICK` extremes (`>= +500` high with `>= +200` close for buy programs; `<= -500` low with `<= -200` close for sell programs) and shifting the 15-minute rolling `$TICK` mean (`>= +100` or `<= -100`).
     2. **VIX Futures (`VX`) Volatility Hedging**: Genuine institutional equity accumulation is accompanied by volatility compression (`VX` declining over the last 15 minutes and holding at or below its `09:30 ET` open), whereas genuine institutional liquidation is accompanied by volatility expansion (`VX` rising over the last 15 minutes and holding at or above its `09:30 ET` open).
     3. **Cross-Index Futures Lockstep (`ES` + `NQ`)**: Both S&P 500 (`ES`) and Nasdaq-100 (`NQ`) futures simultaneously break out of their prior 30-minute range in lockstep, closing in the top/bottom 35% of their 15-minute impulse range on the same side of cumulative RTH `VWAP`.
3. **Prop-Firm & News-Rule Compliance**:
   - By starting evaluation at `10:09 ET` (the close of the `10:05–10:09 ET` 5-minute bar, entering at `10:10 ET` open) and ending at `14:29 ET`, the strategy **never enters during `08:30 AM` or `10:00 AM` macroeconomic data releases**.

---

## 2. Exact Point-in-Time Mathematical Specification

### Step 1: 5-Minute to 1-Minute Point-in-Time Alignment
- `nyse_tick_5m_et.parquet` and `vix_futures_5m_et.parquet` use bar-start timestamps $t_{5m} \in \{\text{09:30}, \text{09:35}, \dots, \text{15:55}\}$, covering $[t_{5m}, t_{5m} + 4\text{m }59\text{s}]$.
- Each 5-minute bar stamped $t_{5m}$ is **strictly completed only at the close of the 1-minute bar $t_{1m} = t_{5m} + 4\text{ minutes}$** (where `minute % 5 == 4`, e.g., `10:09`, `10:14`, `10:19`, ...).
- Signals are evaluated **only** on 1-minute bars where `minute % 5 == 4` within `[10:09, 14:29]`, with trade entry on the **next 1-minute bar open** (`entry_lag_bars = 1`, i.e., `10:10`, `10:15`, ..., `14:30 ET`).

### Step 2: Cross-Asset Features at Completed 5-Minute Boundary $t$ (`minute % 5 == 4`)
1. **NYSE `$TICK` Features**:
   - `tick_5m_high`, `tick_5m_low`, `tick_5m_close` from the just-completed 5-minute bar `[t-4..t]`.
   - `tick_15m_mean`: mean of the last 3 completed 5-minute `$TICK` closes (`[t-14..t]`).
2. **VIX Futures (`VX`) Features**:
   - `vx_open_930`: `VX` open at `09:30 ET` on the current RTH session.
   - `vx_close_t`: `VX` close of the just-completed 5-minute bar `[t-4..t]`.
   - `vx_15m_change = vx_close_t - vx_close_{t-15}` (change over the last 3 completed 5-minute bars).
3. **`NQ` and `ES` 1-Minute Lockstep Impulse Features**:
   - **15-Minute Impulse Window `[t-14 .. t]`** (last 15 1-minute bars):
     - `nq_15m_ret_pct = (nq_close_t - nq_open_{t-14}) / nq_open_{t-14}`
     - `nq_15m_close_loc = (nq_close_t - min(nq_low_{t-14..t})) / (max(nq_high_{t-14..t}) - min(nq_low_{t-14..t}))`
     - `es_15m_ret_pct = (es_close_t - es_open_{t-14}) / es_open_{t-14}`
     - `es_15m_close_loc = (es_close_t - min(es_low_{t-14..t})) / (max(es_high_{t-14..t}) - min(es_low_{t-14..t}))`
   - **Prior Consolidation Range `[t-34 .. t-5]`** (the 30 minutes immediately preceding the current 5-minute breakout bar):
     - `nq_prior30_high = max(nq_high_{t-34..t-5})`, `nq_prior30_low = min(nq_low_{t-34..t-5})`
     - `es_prior30_high = max(es_high_{t-34..t-5})`, `es_prior30_low = min(es_low_{t-34..t-5})`
   - **Cumulative RTH Session `VWAP` on `NQ`**: `nq_vwap_t`.

### Step 3: Entry Trigger Conditions (`10:09 <= t <= 14:29 ET`, `minute % 5 == 4`, Max 1 Trade/Session)

- **Long (`candidate_signal = +1.0`)**:
  1. **Lockstep Range Breakout**: `nq_close_t > nq_prior30_high` AND `es_close_t > es_prior30_high`
  2. **Lockstep Impulse & Close Location**: `nq_15m_ret_pct >= +0.0010` (`+0.10%`), `es_15m_ret_pct > 0.0`, `nq_15m_close_loc >= 0.65`, AND `es_15m_close_loc >= 0.65`
  3. **RTH VWAP Alignment**: `nq_close_t > nq_vwap_t`
  4. **NYSE `$TICK` Program Buying Thrust**: `tick_5m_high >= +500.0` AND `tick_5m_close >= +200.0` AND `tick_15m_mean >= +100.0`
  5. **VIX Futures (`VX`) Compression Confirmation**: `vx_15m_change <= 0.0` AND `vx_close_t <= vx_open_930`

- **Short (`candidate_signal = -1.0`)**:
  1. **Lockstep Range Breakdown**: `nq_close_t < nq_prior30_low` AND `es_close_t < es_prior30_low`
  2. **Lockstep Impulse & Close Location**: `nq_15m_ret_pct <= -0.0010` (`-0.10%`), `es_15m_ret_pct < 0.0`, `nq_15m_close_loc <= 0.35`, AND `es_15m_close_loc <= 0.35`
  3. **RTH VWAP Alignment**: `nq_close_t < nq_vwap_t`
  4. **NYSE `$TICK` Program Selling Liquidation**: `tick_5m_low <= -500.0` AND `tick_5m_close <= -200.0` AND `tick_15m_mean <= -100.0`
  5. **VIX Futures (`VX`) Expansion Confirmation**: `vx_15m_change >= 0.0` AND `vx_close_t >= vx_open_930`

### Step 4: Continuous Signal Score & Structural Barrier
- `program_thrust_score`:
  $$\text{score}_t = \text{candidate\_signal}_t \times |\text{nq\_15m\_ret\_pct}_t| \times 100 \times \left(\frac{|\text{tick\_15m\_mean}_t|}{200.0}\right)$$
- `stop_points = clip(max(nq_high_{t-14..t}) - min(nq_low_{t-14..t}), 15.0, 60.0)`
- `target_points = 1.5 * stop_points`

---

## 3. Pre-Registered Falsification Criteria (Temporal Signal Research Gate)

Evaluated across `transition` (`2016-01-01:2020-12-31`) and `recent_development` (`2021-01-01:2024-12-31`) at horizons `6, 12, 24, 30` bars (`entry_lag_bars = 1`, `round_trip_cost_points = 1.50`, stress costs `2.00` and `4.25` points, `1,000` clock-matched placebo draws):
1. **Minimum Sample Size**: `n_active >= 50` in `2021–2024` and `n_active >= 50` in `2016–2020`.
2. **Net Expectancy After Base Cost (`1.50` pts)**: `mean_signed_return_after_cost_points > 0.0` at 24 or 30 bars in `2021–2024`.
3. **Hit Rate & Period Stability**: `hit_rate_pct >= 52.0%` and `positive_signed_period_pct >= 55.0%`.
4. **Placebo Benchmark**: `placebo_edge_points > 0.0` with `placebo_p_value <= 0.10`.
5. **Multi-Era Temporal Stability**: Must remain net positive (`mean_signed_return_after_cost_points > 0.0`) in both `2016–2020` and `2021–2024` at the primary 24–30 bar horizon.
