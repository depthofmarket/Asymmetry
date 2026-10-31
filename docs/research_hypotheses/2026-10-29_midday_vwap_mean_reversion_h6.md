# Mid-Day VWAP Mean Reversion Scalp (H6)

Date: 2026-10-29

Status: Pre-registered hypothesis; awaiting temporal signal gate validation.

---

## 1. Hypothesis & Market Microstructure Rationale

In index futures trading, the trading day exhibits three distinct structural liquidity phases:
1. **The Opening Momentum Drive (`09:30–10:30 ET`):** Dominated by initiative institutional price discovery, macro rebalancing, and high directional momentum. (Harvested by Strategy 1).
2. **The Mid-Day Lunch Lull (`11:30–13:30 ET`):** Initiated by the European cash market close (`11:30 ET` / `16:30 London`) and the New York institutional lunch period. Directional volume declines by 60%–70%.
3. **The Power Hour / Cash Close (`15:00–16:00 ET`):** Market-on-close (MOC) imbalance execution and day-trader position squaring.

During the **Mid-Day Lunch Lull (`11:30–13:30 ET`)**, the market transitions from an initiative orderflow regime into a **passive liquidity regime**. Without institutional directional commitment, price discovery pauses, and order books are governed by statistical arbitrageurs and high-frequency market-making algorithms.

**The Economic Mechanism:**
Session RTH VWAP (anchored to 09:30:00 ET) and its volume-weighted standard deviation bands represent dynamic fair value and dispersion. When price extends $\ge 2.0$ Standard Deviations ($+2.0\sigma$ or $-2.0\sigma$) away from VWAP during the low-volume mid-day window, the extension is caused by temporary liquidity voids rather than fundamental institutional buying/selling. As directional pressure halts and price confirms rejection back inside the $2.0\sigma$ band, resting two-sided market-maker quotes pull price back toward fair value ($\mu = \text{VWAP}$).

---

## 2. Orthogonality to Strategy 1

This strategy is **100% time-orthogonal and regime-orthogonal to Strategy 1 (`morning_value_area_breakout_h4`)**:
- Strategy 1 triggers strictly between `09:45` and `10:15 ET` and exits by `10:45 ET` (capturing morning initiative breakout momentum).
- Candidate 2 (H6) triggers strictly between `11:30` and `13:30 ET` (capturing mid-day passive mean reversion).
- Because their execution windows are completely non-overlapping, **the two strategies never hold simultaneous positions**.
- Return correlation is expected to be near-zero ($\text{Corr} \approx 0.00$), providing pure portfolio diversification.

---

## 3. Academic & Theoretical Foundations

1. **Madhavan, Richardson, & Roomans (1997)** — *Why Do Security Prices Change? A Transaction-Level Analysis of NYSE Stocks* (*Review of Financial Studies*): Intraday volume and volatility exhibit a pronounced U-shaped curve; the mid-day trough is characterized by elevated transitory order imbalances and high reversion probability.
2. **Biais, Hillion, & Spatt (1995)** — *An Empirical Analysis of the Limit Order Book and the Order Flow in the Paris Bourse* (*Journal of Finance*): Outside peak liquidity hours, aggressive orders exhaust the top of book, creating temporary price impacts that rapidly mean-revert as liquidity providers replenish depth.
3. **Berkowitz, Logue, & Noser (1988)** — *The Total Cost of Transactions on the NYSE*: Establishes VWAP as the standard benchmark of fair value across institutional execution desks.

---

## 4. Fixed Pre-Run Assumptions & Point-in-Time Signal Definition

- **Timeframe:** 1-minute continuous NQ OHLCV bars (`nq_1m_2014_2026_merged.parquet`).
- **Anchor Session:** Cash RTH open (`09:30:00 ET`).
- **RTH VWAP & Dispersion Formula:**
  - Typical Price: $P_t = (High_t + Low_t + Close_t) / 3.0$
  - Volume-weighted mean:
    $$VWAP_t = \frac{\sum_{i=09:30}^t P_i \cdot V_i}{\sum_{i=09:30}^t V_i}$$
  - Volume-weighted standard deviation:
    $$\sigma_t = \sqrt{\max\left(0.0, \frac{\sum_{i=09:30}^t P_i^2 \cdot V_i}{\sum_{i=09:30}^t V_i} - VWAP_t^2\right)}$$
  - Upper Band $+2.0\sigma$: $VWAP_t + 2.0 \cdot \sigma_t$
  - Lower Band $-2.0\sigma$: $VWAP_t - 2.0 \cdot \sigma_t$
  - Minimum dispersion gate: $\sigma_t \ge 10.0$ points (prevents tight bands in dead chop).
- **Active Execution Window:** `11:30:00 ET` to `13:30:00 ET`.
- **Short Setup (Upper $2.0\sigma$ Rejection):**
  - High of current bar extends above upper band: $High_t \ge VWAP_t + 2.0 \cdot \sigma_t$.
  - Rejection confirmation: Current bar closes back strictly below upper band: $Close_t < VWAP_t + 2.0 \cdot \sigma_t$.
  - Upper wick dominance / lower-half close: $(Close_t - Low_t) / (High_t - Low_t) \le 0.45$.
  - Direction: Short (`-1.0`).
  - Entry: Next bar open (`entry_lag_bars = 1`).
  - Target: Dynamic $VWAP_t$ (or minimum 15.0 pts).
  - Stop loss: $High_t + 6.0$ pts beyond extension high (clamped between 15.0 and 45.0 pts).
- **Long Setup (Lower $2.0\sigma$ Rejection):**
  - Low of current bar extends below lower band: $Low_t \le VWAP_t - 2.0 \cdot \sigma_t$.
  - Rejection confirmation: Current bar closes back strictly above lower band: $Close_t > VWAP_t - 2.0 \cdot \sigma_t$.
  - Lower wick dominance / upper-half close: $(Close_t - Low_t) / (High_t - Low_t) \ge 0.55$.
  - Direction: Long (`+1.0`).
  - Entry: Next bar open (`entry_lag_bars = 1`).
  - Target: Dynamic $VWAP_t$ (or minimum 15.0 pts).
  - Stop loss: $Low_t - 6.0$ pts below extension low (clamped between 15.0 and 45.0 pts).
- **Deduplication:** Maximum of 1 trade per session (first qualifying mid-day setup only).
- **Point-in-Time Safety:** All rolling sums and variance calculations reset daily at 09:30:00 ET and use strictly completed bars. Entry is strictly on the next bar open (`entry_lag_bars = 1`).

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

`midday_vwap_mean_reversion_h6`
