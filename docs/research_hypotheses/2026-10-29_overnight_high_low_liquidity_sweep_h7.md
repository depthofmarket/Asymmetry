# Overnight High/Low Liquidity Sweep Scalp (H7)

Date: 2026-10-29

Status: Pre-registered hypothesis; awaiting temporal signal gate validation.

---

## 1. Hypothesis & Market Microstructure Rationale

In electronic index futures markets (NQ), the overnight (Globex / ETH) session establishes two primary structural reference boundaries:
- **Overnight High (`ONH`):** The absolute highest price printed between 18:00 ET (prior session) and 09:29 ET.
- **Overnight Low (`ONL`):** The absolute lowest price printed between 18:00 ET (prior session) and 09:29 ET.

These boundaries represent prominent, publicly visible liquidity pools where retail breakout-stop orders and trailing stop orders cluster. During the morning cash open window (`09:35–10:30 ET`):
1. **Liquidity Extraction:** Institutional market makers and execution algorithms frequently drive price momentarily beyond `ONH` or `ONL` to trigger resting stop-loss orders and source resting liquidity.
2. **Auction Failure:** When the probe beyond the overnight boundary fails to attract initiative institutional follow-through volume, aggressive absorption occurs. Price quickly falls back inside the overnight range, leaving an exhaustion wick.
3. **Trapped Participant Snapback:** Breakout-chasing traders who bought above `ONH` or sold below `ONL` are instantly trapped offside. As their market-stop orders trigger in reverse, a rapid mean-reverting liquidity cascade ensues toward the overnight equilibrium level: the **Overnight Midpoint (`ON_MID = (ONH + ONL) / 2`)**.

---

## 2. Orthogonality to Strategy 1

This strategy is structurally orthogonal to **Strategy 1 (`morning_value_area_breakout_h4`)**:
- Strategy 1 is a **continuation/momentum** strategy that trades acceptance *outside* the prior session RTH Value Area (`VAH`/`VAL`) at 09:44.
- Candidate 3 (H7) is an **exhaustion/fading** strategy that trades *failed breakouts* of the **Overnight ETH High/Low** (`ONH`/`ONL`), fading false breakouts back inside.
- Candidate 3 operates across all days where an overnight sweep occurs, regardless of whether Strategy 1 traded or stayed flat.
- When both trigger on the same session, they trade on completely different structural drivers: Strategy 1 follows RTH Value Area expansion, while Strategy 3 harvests overnight liquidity traps.

---

## 3. Academic & Theoretical Foundations

1. **Brogaard, Hendershott, & Riordan (2014)** — *High-Frequency Trading and Price Discovery* (*Journal of Finance*): Algorithmic market participants opportunistically consume resting liquidity pools around prominent historical extremes before prices revert.
2. **Harris (2003)** — *Trading and Exchanges: Market Microstructure for Practitioners*: Stop-loss clusters behind visible levels create localized order imbalances ("stop-running") followed by sharp mean-reversion once the stop cluster is exhausted.
3. **Dalton (1990)** — *Mind Over Markets*: "Look above the balance area and fail" / "Look below the balance area and fail" represents one of the highest-expectancy auction market setups.

---

## 4. Fixed Pre-Run Assumptions & Point-in-Time Signal Definition

- **Timeframe:** 1-minute continuous NQ OHLCV bars (`nq_1m_2014_2026_merged.parquet`).
- **Overnight Window:** 18:00 ET (prior day) to 09:29 ET (current day).
- **Overnight Levels:**
  - `onh = max(high)` across 18:00 to 09:29 ET.
  - `onl = min(low)` across 18:00 to 09:29 ET.
  - `on_mid = (onh + onl) / 2.0`.
  - Point-in-time guarantee: strictly frozen at 09:29:00 ET prior to cash open.
- **Active Execution Window:** `09:35:00 ET` to `10:30:00 ET` (allowing 5 minutes of opening price discovery before scanning).
- **Short Setup (ONH Sweep & Fail):**
  - High of current bar probes above `onh`: `high > onh`.
  - Sweep depth constraint: `1.0 pt <= high - onh <= 25.0 pts` (avoids runaway initiative trends).
  - Rejection confirmation: Current bar closes back strictly below `onh` (`close < onh`) with lower-half close location: `(close - low) / (high - low) <= 0.45`.
  - Entry: Next bar open (`entry_lag_bars = 1`).
  - Direction: Short (`-1.0`).
- **Long Setup (ONL Sweep & Fail):**
  - Low of current bar probes below `onl`: `low < onl`.
  - Sweep depth constraint: `1.0 pt <= onl - low <= 25.0 pts`.
  - Rejection confirmation: Current bar closes back strictly above `onl` (`close > onl`) with upper-half close location: `(close - low) / (high - low) >= 0.55`.
  - Entry: Next bar open (`entry_lag_bars = 1`).
  - Direction: Long (`+1.0`).
- **Deduplication:** Maximum of 1 trade per session (first qualifying signal per day only).
- **Barriers & Exits:**
  - Stop loss: Beyond the swept high/low:
    - Short: `high + 6.0 pts` (clamped between `15.0` and `45.0` pts).
    - Long: `low - 6.0 pts` (clamped between `15.0` and `45.0` pts).
  - Target: `on_mid` (clamped to minimum `15.0` pts).
  - Time exit: Fixed horizon (12, 24, 30 bars) or 11:30 ET.

---

## 5. Point-in-Time Safety

- All overnight levels (`onh`, `onl`, `on_mid`) use only completed bars up to 09:29:00 ET.
- Triggers use completed 1-minute bars with entry strictly on the next bar's open (`entry_lag_bars = 1`).
- Zero lookahead.

---

## 6. Strict Falsification Criteria

The candidate will be immediately rejected if any of the following occur:
1. Mean return after `1.50` points round-trip transaction cost $\le 0$ across the 2021–2024 development sample.
2. Information Coefficient (conditional `active_ic`) at multi-bar horizon (12–24 bars) $< +0.020$.
3. Clock-matched placebo test shows edge $\le 0$ or bootstrap placebo $p$-value $> 0.10$.
4. Signal fails under `2.00` points cost stress.
5. Transition era (2016–2020) shows negative expectancy across all multi-bar horizons.

---

## 7. Artifact Prefix

`overnight_liquidity_sweep_h7`
