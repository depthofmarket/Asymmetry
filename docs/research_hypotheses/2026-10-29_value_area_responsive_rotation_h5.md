# Prior Session Value Area Responsive Rotation Scalp (H5)

Date: 2026-10-29

Status: Pre-registered hypothesis; awaiting temporal signal gate validation.

## 1. Hypothesis & Market Microstructure Rationale

In Auction Market Theory (Steidlmayer 1984, Dalton 1990), daily market activity is categorized into two mutually exclusive structural states:
1. **Initiative / Trend Days (~35–40% of sessions):** Price accepts outside the prior session's Value Area (`VAH` / `VAL`) during the opening drive. This is captured by Strategy 1 (`morning_value_area_breakout_h4`).
2. **Responsive / Balanced Days (~60–65% of sessions):** Price fails to accept outside the prior session's Value Area during the 09:30–09:44 Opening Range (`prior_val <= close_0944 <= prior_vah`). 

When an opening drive remains inside prior Value, the market is in an **equilibrium / rotational regime**. On these balanced days, directional momentum is absent; instead, liquidity providers and responsive participants absorb directional probes toward the perimeter of the Value Area (`VAH` or `VAL`) and push price back toward the session Point of Control (`POC`) or opposing Value Area boundary.

**The Economic Mechanism:**
When price probes the perimeter of value (`VAH` or `VAL`) during the post-opening window (`10:00–11:30 ET`), breakout-chasing retail traders enter late, expecting a breakout. In a balanced regime, institutional market makers use resting limit depth to absorb this late volume, creating an exhaustion wick. Once the sweep fails to follow through and price closes back inside the Value Area, trapped retail participants are forced to cover, initiating a mean-reverting rotation back toward fair value (`prior_poc` or session `VWAP`).

## 2. Orthogonality to Strategy 1

This strategy is **100% mutually exclusive and orthogonal to Strategy 1** by design:
- Strategy 1 requires `close_0944 > prior_vah` (Long) or `close_0944 < prior_val` (Short).
- Strategy 2 requires `prior_val <= close_0944 <= prior_vah` (Inside Prior Value Area).
- Therefore, on any single trading day, **only Strategy 1 or Strategy 2 can be active—never both**.
- Return correlation is expected to be near-zero or slightly negative ($\text{Corr} \in [-0.10, +0.10]$).

## 3. Academic & Theoretical Foundations

1. **Steidlmayer (1984) & Dalton (1990)** — *Mind Over Markets*: When market opens within value and remains within value, the odds favor rotation between VAH, POC, and VAL.
2. **Kavajecz & Odders-White (2004)** — *Review of Financial Studies*: Limit order book depth clusters at prior-session volume reference nodes, causing passive absorption in balanced market regimes.
3. **Falsification of H3 Synthesis:** In H3 (`2026-10-22`), fading levels between 09:31 and 10:15 failed because it fought aggressive morning initiative breakout flow. H5 resolves this structural failure by:
   - Restricting entries strictly to days proven to be in balance (09:44 close inside VA).
   - Shifting the entry window to `10:00–11:30 ET` (after the 10:00 AM macro news release and after initial morning volatility has settled).

## 4. Fixed Pre-Run Assumptions & Signal Definition

- **Timeframe:** 1-minute continuous NQ OHLCV bars.
- **Prior Reference Levels:** `prior_rth_poc`, `prior_rth_vah`, `prior_rth_val` computed strictly from completed prior RTH session (09:30–16:00 ET) using 1.0-point volume bins and 70% value area width.
- **Regime Gate (Day Filter):** At `09:44:00 ET`, `prior_val <= close_0944 <= prior_vah`.
- **Active Entry Window:** `10:00:00 ET` to `11:30:00 ET` (bars with minute $\ge 10:00$ and $\le 11:30$).
- **Short Setup (VAH Test & Rejection):**
  - High of the current or immediately preceding bar tests near VAH: `high >= prior_vah - 5.0 pts` and `high <= prior_vah + 25.0 pts`.
  - Rejection confirmation: bar closes back below `prior_vah` (`close < prior_vah`) with upper wick dominance: `(close - low) / (high - low) <= 0.45`.
  - Entry: Open of next 1-minute bar (`entry_lag_bars = 1`).
  - Direction: Short (`-1.0`).
- **Long Setup (VAL Test & Rejection):**
  - Low of the current or immediately preceding bar tests near VAL: `low <= prior_val + 5.0 pts` and `low >= prior_val - 25.0 pts`.
  - Rejection confirmation: bar closes back above `prior_val` (`close > prior_val`) with lower wick dominance: `(close - low) / (high - low) >= 0.55`.
  - Entry: Open of next 1-minute bar (`entry_lag_bars = 1`).
  - Direction: Long (`+1.0`).
- **Deduplication:** Maximum of 1 trade per session (first qualifying signal per day only).
- **Structural Barrier & Exits:**
  - **Stop Loss:** Invalidation level beyond the swept high/low:
    - Short: `high + 8.0 pts` (clamped between `15.0` and `45.0` pts).
    - Long: `low - 8.0 pts` (clamped between `15.0` and `45.0` pts).
  - **Profit Target:** Rotation to `prior_rth_poc` (or minimum 1.5R).
  - **Time Exit:** 45 minutes from entry or `12:15:00 ET` (before mid-day lunch lull), whichever occurs first.

## 5. Point-in-Time Safety

- All prior-session profile levels (`prior_rth_poc`, `prior_rth_vah`, `prior_rth_val`) use only completed prior RTH sessions shifted by 1 trading session.
- 09:44 Opening Range features use 09:30–09:44 bars only.
- 10:00–11:30 triggers use completed bars only with entry on next bar open (`entry_lag_bars = 1`).
- Zero lookahead.

## 6. Strict Falsification Criteria

The candidate will be immediately rejected if any of the following occur:
1. Mean return after `1.50` points round-trip transaction cost $\le 0$ across the 2021–2024 development sample.
2. Information Coefficient (conditional `active_ic`) at 12–24 bars $< +0.020$.
3. Clock-matched placebo test shows edge $\le 0$ or bootstrap placebo $p$-value $> 0.10$.
4. Signal fails under `2.00` points cost stress.
5. Transition era (2016–2020) shows negative expectancy across all multi-bar horizons.

## 7. Artifact Prefix

`value_area_responsive_rotation_h5`
