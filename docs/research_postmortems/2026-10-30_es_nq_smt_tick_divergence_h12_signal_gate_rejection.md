# Postmortem: `ES` vs. `NQ` Intermarket SMT Divergence + `$TICK` Exhaustion Reversal (`H12`, `10:20–14:00 ET`) — Signal Gate Rejection

- **Date:** `2026-10-30`
- **Status:** `REJECTED AT TEMPORAL SIGNAL RESEARCH GATE`
- **Pre-Registration:** [`docs/research_hypotheses/2026-10-30_es_nq_smt_tick_divergence_h12.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/docs/research_hypotheses/2026-10-30_es_nq_smt_tick_divergence_h12.md)
- **Implementation:** [`backtest/es_nq_smt_tick_divergence_signal.py`](file:///Users/novo/trading_strategy/nq-scalper-backtest/backtest/es_nq_smt_tick_divergence_signal.py), [`scripts/export_es_nq_smt_tick_divergence_signal_csv.py`](file:///Users/novo/trading_strategy/nq-scalper-backtest/scripts/export_es_nq_smt_tick_divergence_signal_csv.py), [`tests/test_es_nq_smt_tick_divergence_signal.py`](file:///Users/novo/trading_strategy/nq-scalper-backtest/tests/test_es_nq_smt_tick_divergence_signal.py)
- **Gate Reports:**
  - [`results/research_master/signal_research/es_nq_smt_tick_divergence_h12_gate_temporal.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/es_nq_smt_tick_divergence_h12_gate_temporal.md)
  - [`results/research_master/signal_research/es_nq_smt_tick_divergence_h12_gate_recent_development.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/es_nq_smt_tick_divergence_h12_gate_recent_development.md)
  - [`results/research_master/signal_research/es_nq_smt_tick_divergence_h12_gate_transition.md`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/es_nq_smt_tick_divergence_h12_gate_transition.md)

---

## 1. Summary of Empirical Results

`H12` tested whether fading 5-minute sweeps of a prior 45-minute RTH high or low (`[t-50 .. t-5]`) where `NQ` and `ES` diverge (one index breaks its 45-minute boundary while the sister index holds inside), combined with 1-minute rejection back inside the 45-minute boundary and non-confirming NYSE `$TICK` / `VX` volatility futures during `10:20–14:00 ET`, produces positive mean-reversion expectancy.

Across `2016–2024`, the signal fired `1,923` times (`1,083` in `2016–2020`, `840` in `2021–2024`, firing on ~85% of trading sessions). It failed the pre-registered decision gate across all horizons in both eras:

| Split Era | Active Signals (`n`) | Horizon | Gross Mean (pts) | Net Mean (`1.50`pt cost) | Net @ `2.00`pt | Hit Rate (Net) | Active IC | Placebo Edge / $p$-val |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`2021–2024` (`recent_development`)** | `840` | `6` bars | `-0.20` | `-1.70` | `-2.20` | `48.45%` | `-0.0129` | `-0.17` ($p=1.000$) |
| **`2021–2024` (`recent_development`)** | `840` | `12` bars | `+0.16` | `-1.34` | `-1.84` | `47.02%` | `+0.0069` | `+0.15` ($p=0.456$) |
| **`2021–2024` (`recent_development`)** | `840` | `24` bars | `-0.27` | `-1.77` | `-2.27` | `49.29%` | `-0.0054` | `-0.36` ($p=1.000$) |
| **`2021–2024` (`recent_development`)** | `840` | `30` bars | `-0.06` | `-1.56` | `-2.06` | `48.69%` | `-0.0015` | `-0.03` ($p=1.000$) |
| **`2016–2020` (`transition`)** | `1083` | `6` bars | `-0.52` | `-2.02` | `-2.52` | `47.83%` | `-0.0670` | `-0.49` ($p=1.000$) |
| **`2016–2020` (`transition`)** | `1083` | `12` bars | `-0.80` | `-2.30` | `-2.80` | `46.91%` | `-0.0720` | `-0.81` ($p=1.000$) |
| **`2016–2020` (`transition`)** | `1083` | `24` bars | `-0.53` | `-2.03` | `-2.53` | `48.29%` | `-0.0354` | `-0.54` ($p=1.000$) |
| **`2016–2020` (`transition`)** | `1083` | `30` bars | `-0.63` | `-2.13` | `-2.63` | `46.91%` | `-0.0368` | `-0.63` ($p=1.000$) |

---

## 2. Structural Diagnosis (`context_summary.csv`)

1. **Rolling 45-Minute Boundaries Are Ubiquitous Intraday Noise (`85%` Session Firing Rate):**
   - Firing on `1,923` of `~2,260` sessions (`85%` of days) proves that a rolling 45-minute high/low divergence between `ES` and `NQ` is not a rare structural event—it occurs almost daily during normal lead-lag oscillation between tech (`NQ`) and broad financials/industrials (`ES`).
2. **`es_swept_nq_held` Is Lead-Lag Continuation, Not Reversal:**
   - In [`es_nq_smt_tick_divergence_h12_gate_recent_development_context_summary.csv`](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/es_nq_smt_tick_divergence_h12_gate_recent_development_context_summary.csv), when `ES` broke its 45-minute boundary while `NQ` had not yet broken (`es_swept_nq_held`, `n = 322`), fading `NQ` lost **`-3.09` pts net at 6 bars** and **`-4.40` pts net at 30 bars**, because `ES` was leading a genuine directional move that `NQ` subsequently caught up to.
   - Even when `NQ` swept while `ES` held (`nq_swept_es_held`, `n = 518`), net expectancy was `-0.84` pts at 6 bars, `-0.61` pts at 12 bars, `-1.09` pts at 24 bars, and `+0.20` pts at 30 bars (`50.39%` hit rate)—statistically indistinguishable from zero before friction.

---

## 3. Disposition

- **Verdict:** **FALSIFIED & ARCHIVED**. Do not promote `H12` to strategy candidate status.
