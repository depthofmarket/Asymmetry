# Overnight Gap Fade (H2) Signal Gate Rejection

Date: 2026-10-22
Status: rejected; no candidate authorized

## Hypothesis

Pre-registered in `docs/research_hypotheses/2026-10-22_gap_fade_overnight_h2.md`:
NQ overnight gaps (`(09:30 open - prior 15:59 close) / prior 15:59 close`) larger than `0.50%` and exceeding `0.20x` of the 20-day daily ATR partially reverse during the first 30 minutes of RTH (`09:31` open entry to `10:00` exit, with target = `min(0.50 * gap, 30 pts)` and stop = `1.00 * gap`).

## Artifacts & Inputs

- **Signal export:** `results/research_master/signal_exports/gap_fade_overnight_h2_dev_2021_2024.csv`
- **Research report:** `results/research_master/signal_research/gap_fade_overnight_h2_dev_2021_2024.md`
- **Development sample:** `2021-01-03` to `2024-12-31` (`1,415,947` 1-minute bars, `405` qualifying gap sessions)

## Gate Results (After 1.50-Point Round-Trip Cost)

| Horizon | Active ($n$) | Full-Sample `ic` | Conditional `active_ic` | Mean Return After Cost (pts) | Hit Rate | MFE / MAE (pts) | Barrier Net Return (pts) | Target / Stop Hit % | Clock-Matched Placebo Edge (pts) | Placebo $p$-value |
|---------|--------------|------------------|-------------------------|------------------------------|----------|-----------------|--------------------------|---------------------|----------------------------------|-------------------|
| 1 bar   | 405          | +0.0079          | +0.1347                 | +0.93                        | 53.8%    | 14.0 / 12.7     | +0.59                    | 9.4% / 0.0%         | +2.44                            | 0.002             |
| 3 bar   | 405          | -0.0011          | -0.0212                 | -2.08                        | 50.4%    | 21.9 / 22.2     | -2.07                    | 25.9% / 0.0%        | -0.63                            | 1.000             |
| 6 bar   | 405          | +0.0014          | +0.0231                 | -0.42                        | 52.1%    | 30.2 / 29.4     | -1.64                    | 40.2% / 1.0%        | +1.06                            | 0.272             |
| 12 bar  | 405          | -0.0012          | -0.0282                 | -2.77                        | 47.2%    | 38.8 / 38.5     | -2.56                    | 49.4% / 2.2%        | -1.19                            | 1.000             |
| 24 bar  | 405          | -0.0011          | -0.0281                 | -3.16                        | 47.9%    | 51.4 / 50.8     | -3.47                    | 62.0% / 4.7%        | -1.62                            | 1.000             |
| 30 bar  | 405          | -0.0030          | -0.0708                 | -6.66                        | 46.2%    | 56.0 / 55.9     | -4.57                    | 63.0% / 6.7%        | -5.17                            | 1.000             |

## Rejection Reasons

1. **Negative expectancy across all multi-bar horizons (3–30 minutes):** While large gaps briefly tick back in the very first minute (`09:31`, `+0.93` pts), the 30-minute target horizon (`10:00 ET`) produces `-6.66` points net of cost with a `46.2%` hit rate.
2. **Negative conditional IC (`active_ic = -0.0708` at 30 bars):** In post-2021 NQ, large overnight gaps (`>0.50%`) exhibit **continuation/extension** over the first 30 minutes rather than mean-reversion.
3. **Asymmetric tail losses defeat the structural barrier:** Even with the pre-registered `min(0.50 * gap, 30 pts)` target and `1.00 * gap` stop (`63.0%` target hit rate at 30 bars), the `30` point cap vs uncapped `1.00 * gap` stop/timeout losses yields `-4.57` points per trade after costs.
4. **Fails clock-matched placebo (`-5.17` pts at 30 bars, `p = 1.000`):** Fading large gaps at `09:31` underperforms random `09:30` entries by more than 5 points over a 30-minute hold.

## Decision

Rejected. Do not create a strategy candidate from H2 (Overnight Gap Fade).
