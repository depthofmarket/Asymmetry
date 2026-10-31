# Postmortem: Cross-Asset Institutional Program Thrust (`H10`, `10:09–14:29 ET`) — Signal Gate Rejection

- **Date:** `2026-10-30`
- **Status:** `REJECTED AT TEMPORAL SIGNAL RESEARCH GATE`
- **Pre-Registration:** [`docs/research_hypotheses/2026-10-30_cross_asset_program_thrust_h10.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/docs/research_hypotheses/2026-10-30_cross_asset_program_thrust_h10.md)
- **Implementation:** [`backtest/cross_asset_program_thrust_signal.py`](file:///Users/novo/trading_strategy/nq-scalper-backtest/backtest/cross_asset_program_thrust_signal.py), [`scripts/export_cross_asset_program_thrust_signal_csv.py`](file:///Users/novo/trading_strategy/nq-scalper-backtest/scripts/export_cross_asset_program_thrust_signal_csv.py), [`tests/test_cross_asset_program_thrust_signal.py`](file:///Users/novo/trading_strategy/nq-scalper-backtest/tests/test_cross_asset_program_thrust_signal.py)
- **Gate Reports:**
  - [`results/research_master/signal_research/cross_asset_program_thrust_h10_gate_temporal.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/cross_asset_program_thrust_h10_gate_temporal.md)
  - [`results/research_master/signal_research/cross_asset_program_thrust_h10_gate_recent_development.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/cross_asset_program_thrust_h10_gate_recent_development.md)
  - [`results/research_master/signal_research/cross_asset_program_thrust_h10_gate_transition.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/cross_asset_program_thrust_h10_gate_transition.md)

---

## 1. Summary of Empirical Results

`H10` tested whether simultaneous lockstep momentum across `NQ` and `ES` (`15m` return $\ge +0.10\%$ or $\le -0.10\%$ on both indices, breaking the trailing `30m` high/low), confirmed by extreme NYSE `$TICK` breadth (`5m` close $\ge +500$ / $\le -500$ and `15m` mean $\ge +100$ / $\le -100$) and VIX futures (`VX`) inverse volatility confirmation (`15m` change $\le 0$ for Longs, $\ge 0$ for Shorts) during `10:09–14:29 ET`, produces positive multi-bar directional continuation.

Across `2016–2024`, the signal fired `1,435` times (`766` in `2016–2020`, `669` in `2021–2024`, max 1 per session). It failed the pre-registered decision gate across all horizons (`6, 12, 24, 30` bars) in both eras:

| Split Era | Active Signals (`n`) | Horizon | Gross Mean (pts) | Net Mean (`1.50`pt cost) | Net @ `2.00`pt | Hit Rate (Net) | Active IC | MFE / MAE (pts) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`2021–2024` (`recent_development`)** | `669` | `6` bars | `+0.01` | `-1.49` | `-1.99` | `49.78%` | `+0.0258` | `17.31 / 16.29` |
| **`2021–2024` (`recent_development`)** | `669` | `12` bars | `-0.22` | `-1.72` | `-2.22` | `50.07%` | `+0.0110` | `23.69 / 22.39` |
| **`2021–2024` (`recent_development`)** | `669` | `24` bars | `-0.39` | `-1.89` | `-2.39` | `49.03%` | `-0.0226` | `32.34 / 31.38` |
| **`2021–2024` (`recent_development`)** | `669` | `30` bars | `-0.12` | `-1.62` | `-2.12` | `51.27%` | `+0.0029` | `36.17 / 35.33` |
| **`2016–2020` (`transition`)** | `766` | `6` bars | `-0.64` | `-2.14` | `-2.64` | `46.08%` | `-0.1068` | `4.70 / 5.71` |
| **`2016–2020` (`transition`)** | `766` | `12` bars | `-0.03` | `-1.53` | `-2.03` | `48.43%` | `-0.0493` | `6.79 / 7.51` |
| **`2016–2020` (`transition`)** | `766` | `24` bars | `-0.25` | `-1.75` | `-2.25` | `49.09%` | `-0.0420` | `9.68 / 10.62` |
| **`2016–2020` (`transition`)** | `766` | `30` bars | `-0.49` | `-1.99` | `-2.49` | `49.61%` | `-0.0684` | `10.89 / 12.17` |

---

## 2. Structural Diagnosis: Why Chasing `$TICK >= +500 / <= -500` + `15m` Breakouts Fails

1. **Short-Term Program Exhaustion vs. Initiation:**
   - By the time `NQ` and `ES` have both displaced by $\ge 0.10\%$ over 15 minutes, broken their 30-minute high/low, and pushed the completed 5-minute NYSE `$TICK` bar above `+500` (or below `-500`), the initial institutional program basket wave has already completed its short-term execution burst.
   - Over the subsequent `6–30` minutes in `2021–2024`, gross forward drift is literally zero (`+0.01` pts at 6m, `-0.22` pts at 12m, `-0.39` pts at 24m, `-0.12` pts at 30m), with symmetrical MFE/MAE (`32.34` vs. `31.38` pts at 24 bars). Once `1.50` pts of round-trip friction is deducted, the strategy loses `-1.49` to `-1.89` pts per trade.
2. **Time-of-Day Anomaly (`hour == 14` vs. `10:09–13:59 ET`):**
   - In `2021–2024` [`context_summary.csv`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/cross_asset_program_thrust_h10_gate_recent_development/context_summary.csv), hours `10`, `11`, `12`, and `13` were all net negative across horizons (`-1.91` pts net in hour 10, `-1.46` pts in hour 11, `-0.22` pts in hour 12, `-4.76` pts in hour 13 at 6 bars).
   - Only `hour == 14` (`14:00–14:29 ET`, `n = 39`) was net positive across horizons (`+4.86` pts net at 6 bars with `53.85%` hit rate; `+0.78` pts net at 12 bars; `+0.72` pts net at 24 bars). This aligns with our earlier `2026-05-21` Power Hour finding that late-day (`14:00–15:50 ET`) institutional MOC/rebalancing flows sustain directional continuation, whereas morning/midday `$TICK` extremes mean-revert or stall.

---

## 3. Disposition

- **Verdict:** **FALSIFIED & ARCHIVED**. Do not promote `H10` to strategy backtesting or forward testing.
- **Research Implication:** Intraday `$TICK` extremes (`>= +500` / `<= -500`) paired with 15-minute price breakouts during `10:09–13:59 ET` represent short-term exhaustion rather than continuation. Cross-asset research should pivot to:
  1. **`H11` (`ES` vs. `NQ` Intermarket SMT Divergence + `$TICK` Exhaustion Reversal):** Fading false breakouts where one index sweeps a key high/low while the sister index (`ES` or `NQ`) and `$TICK` breadth fail to confirm.
  2. **`H12` (Late-Day MOC Institutional Imbalance Drive, `14:00–15:50 ET`):** Isolating late-day institutional closing flows where cross-asset lockstep (`ES` + `NQ` + `VX` + `$TICK`) exhibits genuine multi-bar follow-through into the `16:00 ET` cash close.
