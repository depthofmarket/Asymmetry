# Prior Session POC/VAH/VAL Rejection Scalp (H3) Signal Gate Rejection

Date: 2026-10-22
Status: rejected; no candidate authorized

## Hypothesis

Pre-registered in `docs/research_hypotheses/2026-10-22_poc_rejection_scalp_h3.md`:
During the RTH morning window (`09:31–10:15 ET`), when NQ price approaches a prior-session RTH volume profile level (`POC`, `VAH`, or `VAL`), touches it within `8` points of the bar open, and the subsequent confirmation bar closes on the opposite side of the level from the approach direction, fading the move at the next bar open produces a positive mean-reversion edge over up to 45 minutes.

## Artifacts & Inputs

- **Signal export:** `results/research_master/signal_exports/poc_rejection_scalp_h3_dev_2021_2024.csv`
- **Research report:** `results/research_master/signal_research/poc_rejection_scalp_h3_dev_2021_2024.md`
- **Development sample:** `2021-01-03` to `2024-12-31` (`1,415,947` 1-minute bars, `678` deduplicated touch-and-reject events across `POC=255`, `VAH=229`, `VAL=194`)

## Gate Results (After 1.50-Point Round-Trip Cost)

| Horizon | Active ($n$) | Full-Sample `ic` | Conditional `active_ic` | Mean Return After Cost (pts) | Hit Rate | MFE / MAE (pts) | Barrier Net Return (pts) | Target / Stop Hit % | Clock-Matched Placebo Edge (pts) | Placebo $p$-value |
|---------|--------------|------------------|-------------------------|------------------------------|----------|-----------------|--------------------------|---------------------|----------------------------------|-------------------|
| 3 bar   | 678          | +0.0020          | +0.0438                 | -0.66                        | 53.1%    | 15.3 / 14.4     | -1.95                    | 61.1% / 29.5%       | +0.84                            | 0.133             |
| 6 bar   | 678          | -0.0005          | -0.0083                 | -1.77                        | 48.7%    | 20.7 / 20.5     | -1.81                    | 64.5% / 31.4%       | -0.25                            | 1.000             |
| 12 bar  | 678          | -0.0022          | -0.0500                 | -3.31                        | 49.0%    | 27.9 / 28.4     | -1.53                    | 66.7% / 32.6%       | -1.80                            | 1.000             |
| 24 bar  | 678          | -0.0011          | -0.0233                 | -2.79                        | 49.1%    | 38.3 / 39.5     | -1.53                    | 66.8% / 33.0%       | -1.34                            | 1.000             |
| 45 bar  | 678          | -0.0019          | -0.0448                 | -4.54                        | 50.0%    | 49.3 / 52.7     | -1.60                    | 66.8% / 33.2%       | -3.04                            | 1.000             |

## Level Disaggregation (12-Bar & 24-Bar Context Breakdown)

- **POC (`n = 255`):** `-2.96` pts at 12 bars (`51.0%` hit rate), `-3.44` pts at 24 bars (`49.8%` hit rate).
- **VAH (`n = 229`):** `-3.04` pts at 12 bars (`48.0%` hit rate), `-4.50` pts at 24 bars (`44.1%` hit rate).
- **VAL (`n = 194`):** `-4.09` pts at 12 bars (`47.4%` hit rate), `+0.09` pts at 24 bars (`54.1%` hit rate).

## Rejection Reasons

1. **Negative net expectancy at every horizon (`3, 6, 12, 24, 45` bars):** Even at the shortest 3-bar horizon where a minor bounce occurs (`53.1%` raw hit rate, `active_ic = +0.0438`), the gross bounce (`+0.84` pts) is smaller than the `1.50`-point round-trip friction (`-0.66` pts net).
2. **Sign flip after 3 bars (`active_ic = -0.0500` at 12 bars, `-0.0448` at 45 bars):** Morning directional orderflow breaks through prior-session reference levels rather than mean-reverting from them.
3. **Barrier structure remains negative (`-1.53` to `-1.95` pts net):** Despite a `66.8%` target hit rate at 24–45 bars, the tighter target (`0.5 * dist`, floored at `4` pts) vs wider structural stop (`dist + 5` pts, hit `33.2%` of the time) plus `1.50` pts cost yields negative net expectancy.
4. **All three levels (`POC`, `VAH`, `VAL`) fail individually at 6 and 12 bars.**

## Decision

Rejected. Do not create a strategy candidate from H3 (Prior Session POC/VAH/VAL Rejection Scalp).
