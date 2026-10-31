# Postmortem: Late-Day Cross-Asset MOC Institutional Imbalance Drive (`H11`, `14:00–15:30 ET`) — Signal Gate Rejection

- **Date:** `2026-10-30`
- **Status:** `REJECTED AT TEMPORAL SIGNAL RESEARCH GATE`
- **Pre-Registration:** [`docs/research_hypotheses/2026-10-30_late_day_cross_asset_moc_drive_h11.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/docs/research_hypotheses/2026-10-30_late_day_cross_asset_moc_drive_h11.md)
- **Implementation:** [`backtest/late_day_cross_asset_moc_drive_signal.py`](file:///Users/novo/trading_strategy/nq-scalper-backtest/backtest/late_day_cross_asset_moc_drive_signal.py), [`scripts/export_late_day_cross_asset_moc_drive_signal_csv.py`](file:///Users/novo/trading_strategy/nq-scalper-backtest/scripts/export_late_day_cross_asset_moc_drive_signal_csv.py), [`tests/test_late_day_cross_asset_moc_drive_signal.py`](file:///Users/novo/trading_strategy/nq-scalper-backtest/tests/test_late_day_cross_asset_moc_drive_signal.py)
- **Gate Reports:**
  - [`results/research_master/signal_research/late_day_cross_asset_moc_drive_h11_gate_temporal.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/late_day_cross_asset_moc_drive_h11_gate_temporal.md)
  - [`results/research_master/signal_research/late_day_cross_asset_moc_drive_h11_gate_recent_development.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/late_day_cross_asset_moc_drive_h11_gate_recent_development.md)
  - [`results/research_master/signal_research/late_day_cross_asset_moc_drive_h11_gate_transition.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/late_day_cross_asset_moc_drive_h11_gate_transition.md)

---

## 1. Summary of Empirical Results

`H11` tested whether scale-invariant intraday trend acceptance on `NQ` ($\ge 0.40\%$ session move, $\ge 0.45$ move-to-range ratio, top/bottom $20\%$ close location, $\ge 0.08\%$ 30m return) confirmed by `ES` lockstep acceptance ($\ge 0.25\%$ session move, top/bottom $30\%$ close location, $\ge 0.05\%$ 30m return), NYSE `$TICK` 15m breadth ($\ge 0$ for Longs, $\le 0$ for Shorts), and VIX futures (`VX` 30m change $\le +0.05$ for Longs, $\ge -0.05$ for Shorts) during `14:00–15:30 ET` generates positive multi-bar continuation.

Across `2016–2024`, the signal fired `1,063` times (`516` in `2016–2020`, `547` in `2021–2024`, max 1 per session). It failed the pre-registered decision gate:

| Split Era | Active Signals (`n`) | Horizon | Gross Mean (pts) | Net Mean (`1.50`pt cost) | Net @ `2.00`pt | Hit Rate (Net) | Active IC | Placebo Edge / $p$-val |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`2021–2024` (`recent_development`)** | `547` | `6` bars | `-0.37` | `-1.87` | `-2.37` | `49.73%` | `-0.0187` | `-0.31` ($p=1.000$) |
| **`2021–2024` (`recent_development`)** | `547` | `12` bars | `+0.56` | `-0.94` | `-1.44` | `52.10%` | `+0.0192` | `+0.49` ($p=0.304$) |
| **`2021–2024` (`recent_development`)** | `547` | `24` bars | `+1.24` | `-0.26` | `-0.76` | `53.20%` | `+0.0294` | `+1.27` ($p=0.172$) |
| **`2021–2024` (`recent_development`)** | `547` | `30` bars | `+1.69` | `+0.19` | `-0.31` | `54.84%` | `+0.0340` | `+1.72` ($p=0.136$) |
| **`2016–2020` (`transition`)** | `516` | `6` bars | `-0.19` | `-1.69` | `-2.19` | `47.87%` | `-0.0209` | `-0.21` ($p=1.000$) |
| **`2016–2020` (`transition`)** | `516` | `12` bars | `-0.93` | `-2.43` | `-2.93` | `46.12%` | `-0.0692` | `-0.93` ($p=1.000$) |
| **`2016–2020` (`transition`)** | `516` | `24` bars | `-1.38` | `-2.88` | `-3.38` | `45.74%` | `-0.0721` | `-1.43` ($p=1.000$) |
| **`2016–2020` (`transition`)** | `516` | `30` bars | `-1.19` | `-2.69` | `-3.19` | `46.32%` | `-0.0565` | `-1.18` ($p=1.000$) |

---

## 2. Structural Diagnosis (`context_summary.csv`)

Inspecting [`late_day_cross_asset_moc_drive_h11_gate_recent_development_context_summary.csv`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/late_day_cross_asset_moc_drive_h11_gate_recent_development_context_summary.csv) and [`late_day_cross_asset_moc_drive_h11_gate_transition_context_summary.csv`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/late_day_cross_asset_moc_drive_h11_gate_transition_context_summary.csv) reveals four critical structural lessons:

1. **Opening the Window at `14:00 ET` Pre-Empted True `15:00 ET` Power-Hour Flow:**
   - Because the signal fired on the first qualifying bar in `14:00–15:30 ET`, **`445 / 547` (`81.4%`) of `2021–2024` signals fired in `hour == 14` (`14:00–14:59 ET`, mostly right at `14:00 ET`)**, leaving only `102` signals in `15:00–15:30 ET`.
   - At `14:00 ET`, pre-MOC institutional rebalancing has not yet locked in: `hour_14_pre_moc` lost `-2.06` pts net at 6 bars, `-1.54` pts at 12 bars, and `-0.16` pts at 30 bars, whereas `hour_15_power_hour` (`15:00–15:30 ET`) averaged `+1.68` pts net (`56.86%` hit rate) at 12 bars and `+1.72` pts net at 30 bars.
2. **Severe Long vs. Short Asymmetry in Late-Day Trend Continuation (`2021–2024`):**
   - **Longs (`n = 288`):** `+2.56` pts net (`56.94%` hit rate) at 24 bars and **`+3.93` pts net (`58.68%` hit rate) at 30 bars**.
   - **Shorts (`n = 259`):** `-3.39` pts net (`49.03%` hit rate) at 24 bars and **`-3.97` pts net (`50.58%` hit rate) at 30 bars**.
   - Shorting `NQ` at the bottom $20\%$ of the day's range after `14:00 ET` runs directly into late-day dealer short-gamma covering and Vanna/charm hedging flows, wiping out the positive Long edge.
3. **Active `VX` Volatility Crush (`vx_change_30m <= -0.10`) vs. Passive/Flat `VX`:**
   - Allowing passive `VX` (`vx_change_30m <= +0.05`) let in `265` `vx_flat` trades that lost `-2.56` pts net at 24 bars and `-3.02` pts net at 30 bars.
   - By contrast, when VIX futures were actively crushing (**`vx_crushing`, `vx_change_30m <= -0.10`, `n = 115`**), `2021–2024` averaged **`+4.07` pts net (`59.13%` hit rate) at 24 bars** and **`+8.60` pts net (`60.00%` hit rate) at 30 bars** (and even in `2016–2020`, `vx_crushing` achieved a `57.50%` hit rate at 30 bars vs. `41.30%` for `vx_flat`).
4. **Breadth Threshold (`abs(tick_15m_mean) >= 200` vs. `0..200`):**
   - `strong_breadth_200plus` (`n = 181`) averaged `+2.05` pts net at 24 bars and `+2.20` pts net (`55.80%` hit rate) at 30 bars in `2021–2024`, whereas `moderate_breadth_0_200` (`n = 366`) lost `-1.40` pts at 24 bars and `-0.81` pts at 30 bars.

---

## 3. Disposition

- **Verdict:** **FALSIFIED & ARCHIVED**. Do not promote `H11` to strategy candidate status.
- **Next Pre-Registered Cross-Asset Candidate:** Proceed to Option 2 from the Cross-Asset Menu (**`H12`: `ES` vs. `NQ` Intermarket SMT Divergence + `$TICK` Exhaustion Reversal**).
