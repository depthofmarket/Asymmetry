# NQ Morning Scalper — Signal Hypothesis Proposals
_Generated: 2026-10-22 | Data: 1-min NQ continuous, 2021-01-03 → 2026-04-28 (1,371 RTH sessions)_

---

## Hypothesis 1: First-30-Minute Momentum Continuation

### Source
**"Intraday Momentum: The First Half-Hour Return Predicts the Last Half-Hour Return"**
Gao, Han, Li, Zhou — *Journal of Financial Economics*, Vol. 148, 2018, pp. 141–157.

> Note: This is a well-established paper; the exact page range is from memory. Verify via SSRN Working Paper #2440866 or JFE directly before citing.

### Core Claim
The return of the S&P 500 ETF (SPY) during the first 30 minutes of RTH is a statistically significant predictor of the return during the last 30 minutes of the same session. The relationship is positive (momentum, not reversal). The mechanism proposed is informed institutional order-flow early in the session, with momentum sustained through herding and index rebalancing flows into the close. The paper documents an annualized Sharpe >1.0 for a pure SPY strategy. The effect was robust across the full sample (1993–2015) and stronger on high-volume, high-uncertainty days.

### NQ Translation
NQ tracks SPY closely but with higher beta (~1.05–1.15 vs SPX). The paper's full-session framing (9:30–4:00) exceeds our target window, but the **early-signal → sustained directional pressure** mechanism applies within the morning hour: if institutional positioning establishes a direction in the first 15–20 minutes, that directional pressure should persist through 10:00–10:30.

**Signal definition (fix before any data look):**

| Parameter | Proposed Value | Rationale |
|-----------|---------------|-----------|
| Signal interval | 9:30 open → 9:45 close (15 bars) | Half of the morning window; avoids using the full measurement as both signal and target |
| Signal magnitude filter | `\|ret_9:30–9:45\| > 0.10%` (~20 pts at current prices) | Excludes flat-open noise; ~30th percentile of first-15 returns |
| Entry bar | 9:46 open | Signal-bar close to execution-bar open lag of 1 bar |
| Holding period | Fixed 30 minutes (9:46 → 10:16) | Consistent, non-adaptive; avoids optimization surface |
| Exit | 10:16 market close; OR stop at 2× entry-bar ATR(14) | Risk control; the paper's result is about a signal, not a complete strategy |
| Direction | Long if 9:30–9:45 return > +threshold; Short if < −threshold |

**Key variables declared before data access:**
1. Threshold value (`0.10%` — must not be fit to outcome distribution)
2. Holding period (`30 min` — must not be selected after seeing return profiles)
3. Stop multiplier (`2.0× ATR` — must not be fit to loss histogram)
4. No regime conditioning in first test (apply uniformly)

### Falsification Criterion
**Reject if** the signal-bar `signal_research_report.py` shows:
- IC (Information Coefficient) of signed 30-minute forward return vs signal direction not significantly different from zero (bootstrap p > 0.10)
- Event-study mean forward return straddling zero within ±1 SD across bootstrap
- Placebo permutation test shows signal IC lies within the central 80% of the permuted IC distribution
- Mean round-trip edge after 1.5 points cost < 0.0 points

### Risks / Caveats
- **Temporal stability**: The original paper's sample (1993–2015) predates systematic trend-following and passive inflow dominance post-2020. Run a temporal subperiod check (2021–2023 vs 2024–2026).
- **Bar timing**: The 9:45 "close" is the `close` field of the 9:44 bar (1-minute close). Verify this precisely or use 9:45 bar's `open` to avoid the 1-minute hindsight in the last price. Use `entry_price_col=open, entry_lag_bars=1` in the signal research gate.
- **NQ vs SPY**: NQ has greater idiosyncratic vol than SPY; single-asset daily Sharpe will be materially lower than the paper's. Expect weak individual days, stronger aggregate IC.
- **Cost sensitivity**: At 1.5-point round-trip cost on a 30-minute holding period, edges < 5 points are likely noise after costs. Target a mean edge of 8–12 points gross before testing.
- **No look-ahead**: The signal (9:30–9:44 OHLCV) must be fully observable at 9:45:00. No issue with 1-minute bars as defined.

---

## Hypothesis 2: Overnight Gap Fade on High-ATR Sessions

### Source
**"A Tug of War: Overnight Versus Intraday Expected Returns"**
Lou, Polk, Skouras — *Journal of Financial Economics*, Vol. 134(1), 2019, pp. 192–213.

> Note: Author roster and JFE attribution are confident; confirm exact volume/page via SSRN #2729591 before citing formally.

### Core Claim
The paper documents a robust **negative serial correlation** between overnight returns and subsequent same-day intraday returns for equity indices and liquid ETFs. Stocks (and index ETFs) that gap up overnight tend to give back some or all of that gain during the regular session, and vice versa. The proposed mechanism is retail-investor sentiment driving after-hours/pre-market prices away from fair value, with institutional traders fading that imbalance at the RTH open. The reversal is stronger when the overnight move is large relative to recent volatility (the gap is "overshoot"), and stronger for high-retail-attention instruments (SPY, QQQ are among the most watched).

### NQ Translation
An overnight gap in NQ is defined as `9:30 open − prior 15:59 close`. Median abs gap in our sample is ~68 NQ points; 43% of days show a gap > 0.5% (~100 pts at current prices). The hypothesis is that **large gaps relative to recent ATR** fade (partially or fully) during the first hour.

**Signal definition (fix before any data look):**

| Parameter | Proposed Value | Rationale |
|-----------|---------------|-----------|
| Gap measurement | `(open_9:30 − close_15:59_prev) / close_15:59_prev` | Normalised; avoids price-level sensitivity as NQ has doubled |
| Large gap threshold | `\|gap_pct\| > 0.50%` | ~43% of sessions qualify; wide enough for sample size |
| ATR filter | 20-day daily ATR; only trade when `\|gap_pts\| > 0.20 × ATR20` | Ensures gap is nontrivial vs recent volatility |
| Direction | Short if gap > +threshold ("gap up → fade"); Long if gap < −threshold ("gap down → fade") |
| Entry bar | 9:31 open (1 bar after session open; avoids the chaos of the first print) | Execution realism: the 9:30 bar is often wide-spread |
| Profit target | 50% of the gap in points, capped at 30 pts | Partial fill thesis; full fill is a stretch |
| Stop | 100% of the gap in points (gap extends, hypothesis is wrong) | Asymmetric risk: 2:1 max adverse / expected adverse |
| Hard time exit | 10:00 (30 minutes) if neither target nor stop hit | Morning-specific; gap dynamics resolve quickly or not at all |

**Key variables declared before data access:**
1. Gap threshold (`0.50%`)
2. ATR filter (`0.20× ATR20`)
3. Profit target fraction (`0.50× gap`)
4. Stop fraction (`1.00× gap`)
5. Time exit (`10:00`)

### Falsification Criterion
**Reject if**:
- Mean 30-minute forward return (signed against gap direction) is not positive after costs across the full sample
- Bootstrap p-value on mean signed return > 0.10
- Profit target hit rate < stop hit rate on a per-dollar-risked basis (negative expectancy)
- The subperiod 2024–2026 shows the opposite sign from 2021–2023 (regime instability)
- Strategy drawdown in prop-firm simulation exceeds $800 (80% of max allowed) more than once per 50 sessions on average

### Risks / Caveats
- **Post-2020 pre-market liquidity**: QQQ pre-market volume has increased dramatically, meaning some gap "fade" may occur before 9:30. The 9:31 entry captures what remains; IC may be lower than in older studies.
- **Macro regime dependency**: On FOMC/CPI days, gaps carry information and fade less reliably. Consider adding a macro-event calendar exclusion (dates already available in session metadata; no data mining needed if declared upfront).
- **Asymmetric gap types**: Up-gaps driven by pre-market earnings (MSFT, AAPL, NVDA components) may not fade in the same way as sentiment-driven gaps. NQ has high mega-cap concentration; a single large-cap print can create a "structural" gap. No easy fix without fundamental data — treat as noise in a first test.
- **Stop placement**: A stop at 1× gap means on a 100-point gap day, the stop is 100 points away (~$2,000/contract). Size accordingly at the signal research stage; report per-point expectancy, not PnL absolute.
- **Future leak check**: Prior close (`15:59`) must be from the day before; confirm date-join logic before signal build. This is the most common implementation error for gap signals.

---

## Hypothesis 3: Prior Session POC Rejection Scalp

### Source
**"Technical Analysis and Liquidity Provision"**
Kavajecz, Odders-White — *Review of Financial Studies*, Vol. 17(4), 2004, pp. 1043–1071.

> Note: Confident in authors and RFS attribution. Exact volume/pages from memory; verify before formal citation.

### Core Claim
The paper provides direct microstructure evidence that **limit order book depth clusters at technical price levels** — specifically prior-day high/low, VWAP, and round numbers. This concentration of passive orders at known reference levels creates a **mean-reversion force**: when price approaches these levels, the waiting limit book absorbs directional flow, causing the price to stall or reverse. This is not curve-fitting; it is a structural liquidity effect. Market Profile / TPO theory (Steidlmayer 1984) independently predicts the same clustering at prior session Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL) because those levels represent price regions where the most time/volume was transacted and where participants calibrated their assessments of fair value.

While Kavajecz & Odders-White work at tick-level, the limit order concentration prediction is testable in aggregate via bar behavior: **price touching a prior-session POC/VAH/VAL and reversing within 2–3 bars** should show positive edge in the reversal direction.

### NQ Translation
The volume profile features are already built in `data/processed/`. The signal requires a **touch-and-reject** pattern at a prior-session reference level during the RTH morning window.

**Signal definition (fix before any data look):**

| Parameter | Proposed Value | Rationale |
|-----------|---------------|-----------|
| Reference levels | Prior RTH session POC, VAH, VAL (3 levels per day) | Highest time/volume acceptance zones; point-in-time safe (prior session only) |
| Touch criterion | `low ≤ level ≤ high` of a given 1-min bar | Bar shadows the level |
| Reject criterion | Subsequent bar closes on the opposite side of the level from approach direction | Confirms rejection; 1-bar confirmation to avoid false starts |
| Approach direction | Defined by the sign of the move from the first morning bar (9:30 close) to the touch bar | Ensures "approaching from a direction" not just random wandering |
| Time window | Touch bar must occur between 9:31 and 10:15 | Morning session; avoids open-bar chaos and 10:30 tail |
| Entry | Open of confirmation bar (bar after reject bar) | 1-bar lag from signal |
| Direction | Against the approach (fade); Long if approaching from below (price hit VAL/POC from above and bounced), Short if from above |
| Profit target | 50% of distance from entry to the reference level | Captures partial retest of the zone |
| Stop | Level breach by > 5 pts (level failed, no longer supportive) | Hard invalidation of the structural premise |
| Time exit | 45 minutes from entry, or 10:30, whichever comes first | Morning-bounded |
| Level proximity filter | Only trigger if price is within 8 pts of the level at touch bar open | Tight zone; avoids bars that merely "tag" the level at extreme wick |

**Key variables declared before data access:**
1. Touch criterion (bar shadow)
2. Reject criterion (close opposite side, 1-bar lag)
3. Proximity filter (8 pts)
4. Profit target fraction (50% of entry-to-level distance)
5. Stop definition (level breach + 5 pts buffer)
6. Time exit (45 min / 10:30)

### Point-in-Time Safety
Prior session POC/VAH/VAL must be built from bars where `date < current date`. The `data/processed/location_context/` pipeline already enforces this. Verify the join uses `date - 1 business day`, not a simple row shift, to avoid Friday→Monday carrying Thursday features.

### Falsification Criterion
**Reject if**:
- Touch-and-reject events with profit target hit rate < stop hit rate AND mean signed return ≤ 0 after 1.5-pt cost
- IC of touch-direction (against approach) vs 45-minute forward return not significantly positive (bootstrap p > 0.10)
- Aggregated across POC, VAH, VAL separately: all three levels show negative expectancy (if only 1–2 fail, level disaggregation finding is informative, not a wholesale rejection)
- The pattern fires on < 100 unique days over the sample (insufficient statistical power for the signal research gate)
- Placebo test (use random price levels within ±200 pts of true POC) shows the same IC (no level specificity)

### Risks / Caveats
- **Level staleness**: The prior RTH session's POC may not be relevant on days where overnight price has moved far from it. Add a "price proximity at 9:30" gate: only activate the level if the 9:30 open is within 1.5× yesterday's range of the reference level. Declare this upfront.
- **Multiple touches per day**: The same level may be touched 2–3 times on consolidation days. Each touch is a separate signal event; mark deduplicated by level per session (only take the first touch) to avoid autocorrelated event counts.
- **Constructed volume profile accuracy**: POC from 1-minute bar volume data is an approximation (volume-at-price within each bar's range is estimated uniformly). True POC from tick data would differ. This introduces noise but not bias.
- **Future regime**: If NQ adopts continuous 23-hour trading as primary market (rather than RTH dominance), prior-RTH levels may matter less. Monitor for structural breaks post-2025.
- **Cost sensitivity**: 5-pt stop with 1.5-pt cost means 30% of the stop is friction. Mean gross edge must exceed ~4 pts per trade to survive. Flag if distribution of winning edges is thin.

---

## Summary Comparison

| | H1: First-30-Min Momentum | H2: Gap Fade | H3: POC Rejection |
|---|---|---|---|
| **Academic basis** | Gao et al. 2018 JFE (high confidence) | Lou et al. 2019 JFE (high confidence) | Kavajecz & Odders-White 2004 RFS (high confidence) |
| **Mechanism** | Informed flow sustains direction | Retail sentiment overshoot, institutional fade | Limit book concentration at known levels |
| **Signal type** | Directional momentum | Counter-trend / fade | Mean-reversion at structure |
| **Signal frequency** | Daily (1 per day) | ~43% of days (gap > 0.5%) | ~1–2 per day (level touches) |
| **Data required** | 1-min OHLCV only | 1-min OHLCV + prior close | 1-min OHLCV + prior session volume profile |
| **Biggest risk** | Temporal decay post-2020 | Macro-event contamination | POC approximation quality |
| **Complementary?** | Yes (momentum signal) | Yes (gap filter) | Yes (structural context) |

**Recommended test order**: H2 → H3 → H1. Gap fade (H2) has the cleanest entry/exit logic and the most direct literature tie. POC rejection (H3) builds on the existing volume profile pipeline. First-30-min momentum (H1) requires careful bar-lag definition to avoid the most common hindsight errors.

All three are **non-correlated** with the discretionary edge (no live orderflow, no options data), fully implementable from saved OHLCV and pre-built volume features, and designed to hold distinct positions in the morning session rather than crowd the same entry bar.
