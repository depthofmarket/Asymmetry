# Overnight Gap Fade — RTH Morning Reversal

Date: 2026-10-22

Status: pre-registered hypothesis; no candidate backtest is authorized yet.

## Hypothesis

NQ overnight gaps larger than 0.50% of prior close, when also exceeding 0.20× the 20-day daily ATR, partially reverse during the first 30 minutes of RTH. Mechanism: retail sentiment overshoots fair value in pre-market; institutional traders fade the imbalance at the open.

## Academic & Theoretical Source

Lou, Polk, Skouras — "A Tug of War: Overnight Versus Intraday Expected Returns", Journal of Financial Economics Vol. 134(1), 2019, pp. 192–213. SSRN #2729591. (Verify exact pages before formal citation.)

## Fixed Pre-Run Assumptions & Signal Definition

- This is not a `CANDIDATE_CONFIGS` entry.
- Gap = (9:30 open − prior 15:59 close) / prior 15:59 close
- Qualifies if |gap| > 0.50% AND |gap in points| > 0.20 × ATR20 (20-day rolling daily ATR, computed from daily OHLCV, point-in-time: uses only completed prior sessions)
- Direction: Short if gap > +0.50% (gap up → fade); Long if gap < −0.50% (gap down → fade)
- Entry: 9:31 bar open (1 bar lag from signal; avoids first-print chaos)
- Profit target: 50% of gap in points (not points, fraction of gap magnitude)
- Stop: 100% of gap in points beyond entry (gap extends = hypothesis wrong)
- Hard time exit: 10:00 ET (30 minutes); whichever of target/stop/time triggers first
- One signal per session maximum; no re-entry

## Point-in-Time Safety

Prior close (15:59) must be from the previous calendar trading day. The date join must use prior business day, not a row shift, to avoid Friday→Monday carrying Thursday features. ATR20 uses only completed prior sessions.

## Falsification Criteria

- Mean signed return after 1.5pt round-trip cost ≤ 0 across full sample
- Bootstrap p-value on mean signed return > 0.10
- Period instability: opposite sign in 2024–2026 vs 2021–2023 subperiod
- Placebo test (random same-size gaps on non-signal days) shows same IC

## Data Required

1-minute OHLCV bars only (no orderflow, no options, no volume profile).

## Artifact Prefix

`gap_fade_overnight_h2`

## Promotion Rule

Do not create or run a strategy candidate from this branch unless the pre-candidate report passes all falsification gates first and the candidate is frozen before any broader historical run.
