# Prior Session POC/VAH/VAL Touch-and-Reject Scalp

Date: 2026-10-22

Status: pre-registered hypothesis; no candidate backtest is authorized yet.

## Hypothesis

During the RTH morning window (9:31–10:15 ET), when NQ price touches a prior-session volume profile reference level (POC, VAH, or VAL) and the next bar closes on the opposite side of the level from approach, there is a mean-reversion edge in the fade direction. Mechanism: limit order book depth clusters at these levels (Kavajecz & Odders-White 2004); passive liquidity absorbs directional flow and creates short-term reversal.

## Academic & Theoretical Source

Kavajecz, Odders-White — "Technical Analysis and Liquidity Provision", Review of Financial Studies Vol. 17(4), 2004, pp. 1043–1071. (Verify exact pages before formal citation.) Supplementary theoretical basis: Steidlmayer Market Profile / TPO theory (1984).

## Fixed Pre-Run Assumptions & Signal Definition

- This is not a `CANDIDATE_CONFIGS` entry.
- Reference levels: prior RTH session POC, VAH, VAL (3 levels per session); built from `data/processed/location_context/` pipeline, which is already point-in-time safe
- Touch criterion: bar's low ≤ level ≤ bar's high (shadow touches the level)
- Approach direction: sign of move from 9:30 bar close to touch bar
- Reject criterion: bar immediately after touch bar closes on opposite side of level from approach (1-bar confirmation)
- Proximity filter: only activate if price is within 8 pts of level at touch bar open (tight zone)
- Time window: touch bar must occur between 9:31 and 10:15 ET
- Entry: open of the bar after the reject bar (2-bar lag from touch)
- Direction: against approach (fade); Long if approached from below (price came up, hit level, bounced down — wait, flip: if price approached from below = going up → hit VAH → rejected → go short); Short if approached from above
- Profit target: 50% of distance from entry to the reference level
- Stop: level breach by more than 5 pts (structural invalidation)
- Time exit: 45 minutes from entry, or 10:30 ET, whichever is earlier
- Deduplication: only first touch per level per session (no re-entries on same level same day)

## Point-in-Time Safety

Prior session levels come from `data/processed/location_context/` which uses only completed prior sessions. Verify date join uses prior business day.

## Falsification Criteria

- Touch-and-reject events: mean signed return ≤ 0 after costs AND hit rate ≤ stop rate
- IC of fade direction vs 45-minute forward return not significantly positive (bootstrap p > 0.10)
- Placebo test: same IC when using random price levels ±200 pts from true POC (no level specificity)
- Signal fires on fewer than 100 unique days over full sample (insufficient power)
- All three levels (POC, VAH, VAL) individually show negative expectancy

## Data Required

1-minute OHLCV + prior-session volume profile (already in `data/processed/location_context/`).

## Artifact Prefix

`poc_rejection_scalp_h3`

## Promotion Rule

Do not create or run a strategy candidate from this branch unless the pre-candidate report passes all falsification gates first and the candidate is frozen before any broader historical run.
