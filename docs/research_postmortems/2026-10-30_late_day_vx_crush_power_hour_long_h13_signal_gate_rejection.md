# Postmortem: Late-Day `VX`-Crush & Cross-Asset Power-Hour Long Drive (`H13`, `14:45–15:30 ET`) — Signal Gate Rejection

- **Date:** `2026-10-30`
- **Status:** `REJECTED AT TEMPORAL SIGNAL RESEARCH GATE`
- **Pre-Registration:** [`docs/research_hypotheses/2026-10-30_late_day_vx_crush_power_hour_long_h13.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/docs/research_hypotheses/2026-10-30_late_day_vx_crush_power_hour_long_h13.md)
- **Implementation:** [`backtest/late_day_vx_crush_power_hour_long_signal.py`](file:///Users/novo/trading_strategy/nq-scalper-backtest/backtest/late_day_vx_crush_power_hour_long_signal.py), [`scripts/export_late_day_vx_crush_power_hour_long_signal_csv.py`](file:///Users/novo/trading_strategy/nq-scalper-backtest/scripts/export_late_day_vx_crush_power_hour_long_signal_csv.py), [`tests/test_late_day_vx_crush_power_hour_long_signal.py`](file:///Users/novo/trading_strategy/nq-scalper-backtest/tests/test_late_day_vx_crush_power_hour_long_signal.py)
- **Gate Reports:**
  - [`results/research_master/signal_research/late_day_vx_crush_power_hour_long_h13_gate_temporal.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/late_day_vx_crush_power_hour_long_h13_gate_temporal.md)
  - [`results/research_master/signal_research/late_day_vx_crush_power_hour_long_h13_gate_recent_development.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/late_day_vx_crush_power_hour_long_h13_gate_recent_development.md)
  - [`results/research_master/signal_research/late_day_vx_crush_power_hour_long_h13_gate_transition.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/late_day_vx_crush_power_hour_long_h13_gate_transition.md)

---

## 1. Summary of Empirical Results

`H13` tested Long-only `14:45–15:30 ET` trend continuation when both `NQ` ($\ge +0.35\%$ session return, $\ge 0.45$ efficiency, $\ge 0.78$ close position, $\ge +0.06\%$ 30m return) and `ES` ($\ge +0.20\%$ session return, $\ge 0.70$ close position, $\ge +0.04\%$ 30m return) are in lockstep uptrends, confirmed by VIX futures compression (`vx_change_30m <= 0` and either `vx_change_30m <= -0.05` or `vx_change_from_open <= -0.05`) and positive NYSE `$TICK` breadth (`tick_15m_mean >= +50`).

Across `2016–2024`, the signal fired `416` times (`208` in `2016–2020`, `208` in `2021–2024`, max 1 per session). While `2021–2024` achieved positive net expectancy and statistically significant clock-matched placebo edge at `24` and `30` bars, the candidate failed period stability, bootstrap CI lower bound, barrier-managed return, and `2016–2020` transition support:

| Split Era | Active Signals (`n`) | Horizon | Gross Mean (pts) | Net Mean (`1.50`pt cost) | Barrier Net (pts) | Hit Rate (Net) | Positive Quarters % | Placebo Edge / $p$-val |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`2021–2024` (`recent_development`)** | `208` | `6` bars | `-0.94` | `-2.44` | `-2.26` | `50.96%` | `25.00%` | `-1.01` ($p=1.000$) |
| **`2021–2024` (`recent_development`)** | `208` | `12` bars | `+0.04` | `-1.46` | `-1.09` | `50.48%` | `43.75%` | `+0.07` ($p=0.464$) |
| **`2021–2024` (`recent_development`)** | `208` | `24` bars | `+2.60` | **`+1.10`** | `-0.16` | **`55.77%`** | `37.50%` | **`+3.22` ($p=0.072$)** |
| **`2021–2024` (`recent_development`)** | `208` | `30` bars | `+3.95` | **`+2.45`** | `+0.55` | **`54.33%`** | `43.75%` | **`+4.65` ($p=0.032$)** |
| **`2016–2020` (`transition`)** | `208` | `6` bars | `-0.85` | `-2.35` | `-2.35` | `42.31%` | `10.00%` | `-0.88` ($p=1.000$) |
| **`2016–2020` (`transition`)** | `208` | `12` bars | `-0.72` | `-2.22` | `-2.32` | `43.75%` | `20.00%` | `-0.80` ($p=1.000$) |
| **`2016–2020` (`transition`)** | `208` | `24` bars | `+0.20` | `-1.30` | `-1.31` | `49.52%` | `35.00%` | `+0.03` ($p=0.496$) |
| **`2016–2020` (`transition`)** | `208` | `30` bars | `+0.36` | `-1.14` | `-1.56` | `51.92%` | `50.00%` | `+0.03` ($p=0.488$) |

---

## 2. Structural Diagnosis

1. **Buying At Session Highs (`nq_close_pos >= 0.78`, `nq_ret_30m_pct >= +0.06%`) Suffers Immediate `6–12m` Mean-Reversion Pullback:**
   - Notice the path of returns in `2021–2024`: at `6` bars, the trade is down **`-2.44` pts net**; at `12` bars, it is still down **`-1.46` pts net**; and only between minute 12 and minute 30 does the late-day trend resume to reach **`+2.45` pts net** ($p = 0.032$).
   - Because of that initial `6–12` minute pullback after a 30-minute momentum burst at session highs, enforcing a stop/target barrier (`barrier_mean_signed_return_after_cost_points`) cuts the 30-bar net return from `+2.45` pts down to just **`+0.55` pts net** (`-0.16` pts net at 24 bars), and only `43.75%` of quarters are positive.
2. **Sub-Regime Concentration (`deep_30m_vx_crush` and `strong_tick_200plus`):**
   - Virtually all of the positive return in `2021–2024` came from the `95` trades with `deep_30m_vx_crush` (`vx_change_30m <= -0.10`, **`+9.58` pts net, `62.11%` hit rate at 30 bars**) and `47` trades with `strong_tick_200plus` (`tick_15m_mean >= 200`, **`+13.35` pts net at 24 bars, `+10.50` pts net at 30 bars**), while `steady_session_vx_crush` (`n = 113`) lost `-3.54` pts net.
   - However, in `2016–2020`, even `deep_30m_vx_crush` (`-1.26` pts net) and `strong_tick_200plus` (`-2.96` pts net) were negative.

---

## 3. Disposition

- **Verdict:** **FALSIFIED & ARCHIVED**. Do not promote `H13` to strategy candidate status.
