# First-15-Minute Momentum Continuation

Date: 2026-10-22

Status: pre-registered hypothesis; no candidate backtest is authorized yet.

## Hypothesis

If NQ moves more than 0.10% (absolute) in the first 15 minutes of RTH (9:30–9:44 ET), that directional move continues through the next 30 minutes (9:46–10:16). Mechanism: informed institutional positioning early in session sustains directional pressure through herding and flow continuation.

## Academic & Theoretical Source

Gao, Han, Li, Zhou — "Intraday Momentum: The First Half-Hour Return Predicts the Last Half-Hour Return", Journal of Financial Economics Vol. 148, 2018, pp. 141–157. SSRN #2440866. (Verify exact pages before formal citation.) Original paper documents SPY; translated to NQ here.

## Fixed Pre-Run Assumptions & Signal Definition

- This is not a `CANDIDATE_CONFIGS` entry.
- Signal interval return: (9:44 bar close − 9:30 bar open) / 9:30 bar open
- Magnitude filter: |ret| > 0.10% (approx 20 pts at current prices; ~30th percentile of first-15-min returns)
- Direction: Long if ret > +0.10%; Short if ret < −0.10%
- Entry: 9:46 bar open (1-bar lag from 9:45 signal completion)
- Holding period: fixed 30 minutes (exit at 10:16 bar open)
- Stop: 2× ATR(14) of prior session's 1-minute bars, computed at close of prior RTH session
- One signal per session maximum

## Point-in-Time Safety

Signal uses 9:30–9:44 close which is fully observable at 9:45:00. ATR14 uses only prior-session bars. No forward look.

## Falsification Criteria

- IC of first-15-min return sign vs 30-minute forward return (9:46–10:16) not significantly positive
- Mean signed return after 1.5pt cost ≤ 0 across full sample
- Effect absent in 2021–2026 subperiod specifically (regime stability required)
- Placebo: random direction assignment on signal days shows same IC (signal adds nothing above base momentum)

## Data Required

1-minute OHLCV bars only.

## Artifact Prefix

`first30min_momentum_h1`

## Promotion Rule

Do not create or run a strategy candidate from this branch unless the pre-candidate report passes all falsification gates first and the candidate is frozen before any broader historical run.
