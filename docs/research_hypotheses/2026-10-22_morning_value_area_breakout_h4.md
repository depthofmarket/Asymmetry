# Morning Value-Area & Opening Momentum Acceptance Breakout (H4)

Date: 2026-10-22

Status: pre-registered hypothesis; no candidate backtest is authorized yet.

## Hypothesis

When NQ establishes a directional drive in the first 15 minutes of RTH (`09:30–09:44 ET`, `|ret_15m| >= 0.10%`) that closes near the extreme of the 15-minute opening range (`close_location >= 0.65` for long, `<= 0.35` for short) AND achieves structural acceptance outside or across the prior RTH session's Volume Profile levels (`VAH`, `VAL`, `POC`), that directional move continues over the next 15–30 minutes (`09:45–10:15 ET`).

Mechanism: Informed institutional orderflow at the RTH open overwhelms passive limit-book liquidity clustered at prior-day reference levels (`VAH`, `VAL`, `POC`), trapping responsive fade traders and triggering stop-driven / gamma-hedging continuation. This directly synthesizes our empirical falsification of H2 (Gap Fade) and H3 (POC/VAH/VAL Fade) with the positive continuation found in H1 (First-15-Min Momentum).

## Academic & Theoretical Source

- Gao, Han, Li, Zhou (2018), *Journal of Financial Economics*: First half-hour return positively predicts subsequent intraday continuation via informed institutional flow.
- Steidlmayer (1984) Auction Market Theory & Crabel (1990): Initiative acceptance outside prior day's Value Area (`VAH` / `VAL`) produces directional expansion rather than mean reversion.

## Fixed Pre-Run Assumptions & Signal Definition

- This is not a `CANDIDATE_CONFIGS` entry.
- **Measurement window:** `09:30` bar open through `09:44` bar close (15 1-minute bars, fully observable at `09:45:00`).
- **Directional drive filter:** `|ret_15m_pct| = |(close_0944 - open_0930) / open_0930| >= 0.10%`.
- **Opening range acceptance filter:** `close_location = (close_0944 - low_0930_0944) / (high_0930_0944 - low_0930_0944)` must be `>= 0.65` for Long and `<= 0.35` for Short.
- **Prior-Session Value Area acceptance / breakout filter (strictly from prior completed RTH session):**
  - **Long (`+1`):** `close_0944 > prior_rth_vah` (accepted above prior Value Area High) OR `09:30–09:44` range broke upward through `prior_rth_poc` or `prior_rth_val` (`low_0930_0944 <= level < close_0944`).
  - **Short (`-1`):** `close_0944 < prior_rth_val` (accepted below prior Value Area Low) OR `09:30–09:44` range broke downward through `prior_rth_poc` or `prior_rth_vah` (`high_0930_0944 >= level > close_0944`).
- **Entry:** `09:45` bar open (`entry_lag_bars = 1` from `09:44` signal row).
- **Horizons evaluated:** `6, 12, 24, 30` bars (`09:51, 09:57, 10:09, 10:15 ET`).
- **Structural barrier:**
  - `stop_points = clip(high_0930_0944 - low_0930_0944, 15.0, 60.0)` (full invalidation of the 15-minute opening range).
  - `target_points = 1.5 * stop_points`.
- **One signal per session maximum.**

## Point-in-Time Safety

All prior-session profile levels (`prior_rth_poc`, `prior_rth_vah`, `prior_rth_val`) use only completed prior RTH sessions shifted by 1 trading session. All opening-drive features use `09:30–09:44` bars only.

## Falsification Criteria

- Conditional `active_ic` at 24–30 bars `< 0.020`.
- Mean signed return after `1.50` points round-trip cost `<= 0` across the `2021–2024` development sample.
- Clock-matched placebo edge `<= 0` or `placebo_p_value > 0.10`.
- Negative expectancy on both un-stopped fixed horizon and structural barrier evaluation.

## Artifact Prefix

`morning_value_area_breakout_h4`
