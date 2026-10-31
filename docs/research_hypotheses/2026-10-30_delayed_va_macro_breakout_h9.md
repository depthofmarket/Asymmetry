# Pre-Registration: Delayed Value-Area Escape & 10:00 ET Macro Impulse Breakout (H9)

**Date:** 2026-10-30  
**Status:** Pre-Registered — Pending Signal Research Gate  
**Candidate Slot:** Strategy 2 (Orthogonal / Session-Complement to Morning Value Area Breakout v2.0, H4)  
**Target Window:** `10:04 ET` signal bar close (`10:05 ET` open entry; evaluation horizons `6, 12, 24, 30` bars $\rightarrow$ `10:10–10:35 ET`)  

---

## 1. Market Microstructure Thesis & Structural Orthogonality

1. **Why Strategy 1 (`H4`) Leaves ~77% of Sessions Untraded**:
   - Strategy 1 (`Morning Value Area Breakout v2.0`, `H4`) evaluates only the `09:44 ET` bar close and requires price to already be accepted outside the prior session's RTH Value Area (`close_0944 > prior_rth_vah` or `close_0944 < prior_rth_val`) with gap alignment (`gap_pts > 0` for long, `< 0` for short).
   - Across `2021–2024`, Strategy 1 triggers on `238` of `1,032` sessions (~23%). On the remaining ~77% of sessions, institutional participants either open inside the prior day's Value Area (`[prior_rth_val, prior_rth_vah]`) or coil during the first 15 minutes (`09:30–09:44 ET`) while awaiting the **`10:00 AM ET` US macroeconomic release window** (ISM Manufacturing/Services PMI, JOLTS Job Openings, Consumer Confidence, New/Pending Home Sales, Factory Orders, UMich Sentiment) and the completion of the first half-hour auction.
2. **Why `H5`–`H8` Failed & What `H4` Context Diagnostics Proved**:
   - Our falsification of `H5` (VA Responsive Rotation), `H6` (Mid-Day VWAP Mean Reversion), `H7` (Overnight Sweep Fade), and `H8` (Afternoon VWAP Pullback) proved two fundamental properties of 1-minute NQ futures across `2016–2024`:
     1. **Momentum inside the prior Value Area fails**: In `H4` context diagnostics, trading breakouts while price remains *inside* `[prior_rth_val, prior_rth_vah]` produced `-7.09` pts net at 30 bars (`47.97%` hit rate) due to two-sided value-area absorption.
     2. **Initiative escape outside the prior Value Area during the `09:30–10:35 ET` morning volatility window succeeds**: Only morning directional expansions outside `[prior_rth_val, prior_rth_vah]` generate sufficient 24–30 bar excursion (`35–50` pts MFE) to clear `1.50`–`4.25` pts of institutional execution friction across both `2016–2020` and `2021–2024`.
3. **The `10:04 ET` Delayed Value-Area & Opening-Range Escape (`H9`)**:
   - At `10:04 ET` (the close of the first 5-minute candle `10:00–10:04 ET` following the `10:00 AM ET` macro release window), if a session that **did not trigger Strategy 1 at `09:44 ET`** has now:
     - Escaped and closed **outside** the prior session's RTH Value Area (`close_1004 > prior_rth_vah` for Long, `close_1004 < prior_rth_val` for Short), **AND**
     - Broken out beyond the `09:30–09:44 ET` 15-minute Opening Range (`close_1004 > or15_high` for Long, `close_1004 < or15_low` for Short), **AND**
     - Achieved strong cumulative morning directional impulse (`|or35_ret_pct| >= 0.10%`, positive second-wave expansion from `09:44` to `10:04 ET`, and top/bottom 35% range close location `>= 0.65` / `<= 0.35`),
   - Then institutional initiative flow has resolved the initial morning balance/coil into a directional trend expansion over the subsequent `15–30` minutes (`10:05–10:35 ET`).

---

## 2. Exact Point-in-Time Mathematical Specification

All parameters are inherited directly from frozen Strategy 1 (`H4`) with **zero newly tuned thresholds**:

### Step 1: Prior Session Volume Profile (`t - 1` RTH `09:30–16:00 ET`)
- `prior_rth_poc`, `prior_rth_vah`, `prior_rth_val` (`70%` Value Area, `1.0` pt bin size) and `prior_rth_close` computed strictly from the prior completed RTH session.

### Step 2: Strategy 1 (`H4`) Mutual Exclusivity Gate at `09:44 ET`
- Evaluate frozen Strategy 1 (`MorningValueAreaBreakoutConfig` default parameters) at `09:44 ET`.
- Define `h4_active_session = True` if Strategy 1 fired (`+1` or `-1`) at `09:44 ET` on session $d$, else `False`.
- **Hard Orthogonality Constraint**: `H9` is eligible **only** when `h4_active_session == False`. Strategy 1 and `H9` can never trade on the same day (`0.0%` session overlap).

### Step 3: `09:30–09:44 ET` (`OR15`) and `09:30–10:04 ET` (`OR35`) Features
At the close of the `10:04 ET` bar:
- `or15_high` $= \max(\text{high}_{09:30..09:44})$, `or15_low` $= \min(\text{low}_{09:30..09:44})$, `or15_close` $= \text{close}_{09:44}$
- `or35_open` $= \text{open}_{09:30}$, `or35_high` $= \max(\text{high}_{09:30..10:04})$, `or35_low` $= \min(\text{low}_{09:30..10:04})$, `or35_close` $= \text{close}_{10:04}$
- `or35_range` $= \text{or35\_high} - \text{or35\_low}$
- `or35_close_location` $= (\text{or35\_close} - \text{or35\_low}) / \text{or35\_range}$
- `or35_ret_pct` $= (\text{or35\_close} - \text{or35\_open}) / \text{or35\_open}$
- `wave2_ret_pct` $= (\text{or35\_close} - \text{or15\_close}) / \text{or15\_close}$ (impulse from `09:44` close to `10:04` close)

### Step 4: Entry Conditions at `10:04 ET` Close (Next-Bar Open Entry at `10:05 ET`)
- **Long (`candidate_signal = +1.0`)**:
  1. `not h4_active_session`
  2. `or35_close > prior_rth_vah` (accepted above prior Value Area High)
  3. `or35_close > or15_high` (broken out above 15-minute Opening Range High)
  4. `or35_ret_pct >= +0.0010` (`+0.10%`) AND `wave2_ret_pct > 0.0`
  5. `or35_close_location >= 0.65`
- **Short (`candidate_signal = -1.0`)**:
  1. `not h4_active_session`
  2. `or35_close < prior_rth_val` (accepted below prior Value Area Low)
  3. `or35_close < or15_low` (broken down below 15-minute Opening Range Low)
  4. `or35_ret_pct <= -0.0010` (`-0.10%`) AND `wave2_ret_pct < 0.0`
  5. `or35_close_location <= 0.35`

### Step 5: Continuous Signal Score & Structural Barrier
- `delayed_va_breakout_score`:
  $$\text{score}_t = \text{candidate\_signal}_t \times |\text{or35\_ret\_pct}_t| \times 100 \times \begin{cases} \text{or35\_close\_location}_t & \text{if } \text{candidate\_signal}_t > 0 \\ 1 - \text{or35\_close\_location}_t & \text{if } \text{candidate\_signal}_t < 0 \end{cases}$$
- `stop_points = clip(or35_range, 15.0, 60.0)`
- `target_points = 1.5 * stop_points`

---

## 3. Pre-Registered Falsification Criteria (Temporal Signal Research Gate)

Evaluated across `2021–2024` (`recent_development`) and `2016–2020` (`transition`) at horizons `6, 12, 24, 30` bars (`entry_lag_bars = 1`, `round_trip_cost_points = 1.50`, stress costs `2.00` and `4.25` points, `500` clock-matched placebo draws at `10:04 ET`):
1. **Minimum Sample Size**: `n_active >= 60` in `2021–2024` and `n_active >= 60` in `2016–2020`.
2. **Net Expectancy After Base Cost (`1.50` pts)**: `mean_signed_return_after_cost_points > 0.0` at 24 or 30 bars in `2021–2024`.
3. **Hit Rate & Period Stability**: `hit_rate_pct >= 52.0%` and `positive_signed_period_pct >= 55.0%`.
4. **Placebo Benchmark**: `placebo_edge_points > 0.0` with `placebo_p_value <= 0.10` against clock-matched `10:04 ET` entries.
5. **Multi-Era Temporal Stability**: Must remain net positive (`mean_signed_return_after_cost_points > 0.0`) in both `2016–2020` and `2021–2024` at the primary 24–30 bar horizon.
