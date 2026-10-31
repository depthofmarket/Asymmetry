# Postmortem: Delayed Value-Area Escape & 10:00 ET Macro Impulse Breakout (H9) — Signal Gate Rejection

**Date:** 2026-10-30  
**Hypothesis:** [2026-10-30_delayed_va_macro_breakout_h9.md](file:///Users/novo/trading_strategy/nq-scalper-backtest/docs/research_hypotheses/2026-10-30_delayed_va_macro_breakout_h9.md)  
**Signal Generator:** [delayed_va_macro_breakout_signal.py](file:///Users/novo/trading_strategy/nq-scalper-backtest/backtest/delayed_va_macro_breakout_signal.py)  
**Temporal Gate Report:** [delayed_va_macro_breakout_h9_gate_temporal.md](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/delayed_va_macro_breakout_h9_gate_temporal.md)  
**Decision:** **FALSIFIED & REJECTED** — Do not promote to `CANDIDATE_CONFIGS`.

---

## 1. Empirical Summary Across Temporal Splits (`2016–2024`)

Evaluated on `data/raw/nq_1m_2014_2026_merged.parquet` (`3,142,047` bars, `384` active `10:04 ET` signals on sessions where Strategy 1 `H4` was flat at `09:44 ET`, `entry_lag_bars = 1` at `10:05 ET` open, `1.50`pt base round-trip cost, `2.00`pt and `4.25`pt stress costs, `1,000` clock-matched placebo draws):

| Horizon | Split Era | Active Signals ($n$) | Conditional `active_ic` (`score`) | Gross Mean Return (pts) | Net Mean Return (`1.50`pt cost) | Net @ `2.00`pt Stress | Net @ `4.25`pt Stress | Hit Rate | Mean MFE / MAE (pts) | Gate Verdict |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **6 bars** | `2021–2024` | 171 | `+0.1522` | `+1.94` | `+0.44` | `-0.06` | `-2.31` | `52.63%` | `19.4 / 18.6` | **FAIL** (stress & $p=0.160$) |
| **12 bars** | `2021–2024` | 171 | `+0.0144` | `-0.91` | `-2.41` | `-2.91` | `-5.16` | `49.71%` | `26.6 / 27.4` | **FAIL** |
| **24 bars** | `2021–2024` | 171 | `+0.0157` | `-1.61` | `-3.11` | `-3.61` | `-5.86` | `45.61%` | `34.5 / 38.1` | **FAIL** |
| **30 bars** | `2021–2024` | 171 | `+0.0017` | `-1.14` | `-2.64` | `-3.14` | `-5.39` | `49.12%` | `38.1 / 43.2` | **FAIL** |
| **6 bars** | `2016–2020` | 213 | `-0.0812` | `-0.87` | `-2.37` | `-2.87` | `-5.12` | `40.38%` | `7.0 / 7.6` | **FAIL** |
| **12 bars** | `2016–2020` | 213 | `+0.0098` | `+0.71` | `-0.79` | `-1.29` | `-3.54` | `47.89%` | `11.1 / 10.7` | **FAIL** |
| **24 bars** | `2016–2020` | 213 | `+0.0299` | `+0.82` | `-0.68` | `-1.18` | `-3.43` | `48.83%` | `15.8 / 14.3` | **FAIL** |
| **30 bars** | `2016–2020` | 213 | `+0.0284` | `+1.59` | `+0.09` | `-0.41` | `-2.66` | `49.77%` | `17.3 / 16.0` | **FAIL** |

### Sub-Regime Context Attribution (30-Bar Horizon, Net After `1.50`pt Cost)
- **`or15_inside_va` (`09:44` closed inside `[VAL, VAH]`, then `10:04` broke outside `[VAL, VAH]`)**:
  - `2016–2020` (`n = 81`): **`+2.01` pts net** (`inside_va_to_above_vah`: **`+6.83` pts net**, `n = 42`).
  - `2021–2024` (`n = 73`): **`-8.76` pts net** (`inside_va_to_above_vah`: **`-10.85` pts net**, `n = 36`; `inside_va_to_below_val`: **`-6.72` pts net**, `n = 37`), despite being **`+2.12` pts net (`61.64%` hit rate) at 6 bars**!
- **`or15_outside_va_coiled` (`09:44` already outside `[VAL, VAH]` but coiled, then `10:04` broke `OR15`)**:
  - `2016–2020` (`n = 132`): `-1.09` pts net.
  - `2021–2024` (`n = 98`): `+1.92` pts net (`coiled_outside_va_up`: `+2.97` pts net, `n = 58`).

---

## 2. Structural Root Cause Analysis: The `H5` / `H9` Mirror Regime Shift

Combining the empirical results of **Candidate 1 (`H5`: Value Area Responsive Rotation)** and **Candidate 5 (`H9`: Delayed Value-Area Macro Breakout)** reveals why post-`10:00 AM` Value-Area boundary setups cannot pass a multi-era (`2016–2020` + `2021–2024`) gate:

1. **Short 6-Minute Macro Impulse vs. 24–30 Minute Mean-Reversion Snapback in `2021–2024`**:
   - In `2021–2024`, `10:04 ET` breakouts on `or15_inside_va` sessions follow through for only **6 minutes** (`10:05–10:10 ET`: `+2.12` pts net, `61.64%` hit rate, `active_ic = +0.1522`).
   - Between `10:10` and `10:34 ET` (bars 6 to 30), those breakouts violently reverse back inside the prior Value Area by **`-10.88` points** (`-8.76` pts net at 30 bars).
2. **Exact Mirror of `H5` Across the 2021 Structural Regime Boundary**:
   - In **`2016–2020`** (pre-0DTE daily index options era), when an inside-VA session broke above `prior_rth_vah` around `10:00 AM`, it continued upward (`+6.83` pts net at 30 bars in `H9`), which caused `H5` (`VAH` responsive short fade) to lose `-2.42` pts.
   - In **`2021–2024`** (post-0DTE daily index options dealer gamma era), when an inside-VA session breaks outside `VAH`/`VAL` around `10:00 AM`, dealer gamma hedging pins price back to value (`-10.85` pts at 30 bars in `H9`), which is why `H5` (fading `VAH`/`VAL` back to `POC`) made `+3.90` pts net ($p = 0.027$) in `2021–2024`.
3. **Why Strategy 1 (`H4`, `09:44 ET`) Is Uniquely Regime-Invariant**:
   - Only when the session opens with an overnight gap AND achieves acceptance outside `[prior_rth_val, prior_rth_vah]` during the initial `09:30–09:44 ET` institutional discovery drive does directional flow overwhelm passive value-area/gamma liquidity across **both** `2016–2020` and `2021–2024`.
