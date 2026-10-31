# Pre-Registration: Out-of-Sample Holdout Validation of Value Area Responsive Rotation (H5-OOS, 2025–2026)

**Date:** 2026-10-30  
**Status:** Pre-Registered Out-of-Sample Holdout Test — Unseen `2025-01-01` to `2026-04-28` Window  
**Parent Hypothesis:** [2026-10-29_value_area_responsive_rotation_h5.md](file:///Users/novo/trading_strategy/nq-scalper-backtest/docs/research_hypotheses/2026-10-29_value_area_responsive_rotation_h5.md)  
**Frozen Implementation:** [value_area_responsive_rotation_signal.py](file:///Users/novo/trading_strategy/nq-scalper-backtest/backtest/value_area_responsive_rotation_signal.py) (Zero code or parameter changes permitted)

---

## 1. Motivation & Methodological Disclosure

1. **Prior Development Findings (`2021–2024` vs. `2016–2020`)**:
   - In the `2021–2024` development sample (`n = 259`), `H5` (`ValueAreaResponsiveRotationConfig` default parameters) achieved **`+3.90` points net per trade** after `1.50`pt round-trip cost at the **24-bar horizon**, surviving `4.25`pt stress (`+1.15` pts net), with `53.67%` hit rate, `62.50%` positive quarters, `active_ic = +0.1188`, and a clock-matched placebo edge of **`+5.28` points ($p = 0.027$)**.
   - Within `2021–2024`, `VAL` Longs (`n = 130`) generated **`+5.89` pts net (`59.23%` hit rate)** and `VAH` Shorts (`n = 129`) generated **`+1.90` pts net (`48.06%` hit rate)**.
   - However, `H5` was rejected under its original pre-registration because it failed in the `2016–2020` transition era (`-1.25` pts net at 24 bars; `VAL` Longs `+0.18` pts, `VAH` Shorts `-2.42` pts), where NQ index levels (`4,500–9,000`) and value-area widths were a fraction of post-2021 levels (`12,000–21,000`).
2. **Corroborating Structural Evidence from `H9` (`10:04 ET` Breakout)**:
   - Testing `H9` (chasing `10:04 ET` breakouts outside `VAH`/`VAL` on inside-VA sessions) independently showed that in `2021–2024`, breakouts on inside-VA days snap back inside the Value Area by `-10.88` points between minute 6 and minute 30 (`-8.76` pts net at 30 bars), whereas in `2016–2020` they continued (`+2.01` pts net).
3. **Clean Out-of-Sample Test on Unseen `2025–2026` Data**:
   - Because `H5` has **never** been exported or evaluated on `2025-01-01` through `2026-04-28` (`~16` months of unseen out-of-sample data), `2025–2026` provides a true out-of-sample test of whether the `2021–2024` post-opening Value-Area responsive rotation edge is a genuine feature of the modern NQ microstructure or an in-sample artifact.

---

## 2. Frozen Specification (Zero Modifications)

- **Code & Parameters**: Exact default `ValueAreaResponsiveRotationConfig` in `backtest/value_area_responsive_rotation_signal.py`:
  - `or15_end = "09:44"` inside `[prior_rth_val, prior_rth_vah]` (100% mutually exclusive with Strategy 1 `H4`).
  - `signal_window = "10:00"` to `"11:30"`.
  - `touch_tolerance_points = 5.0`, `max_overshoot_points = 25.0`.
  - `max_short_close_location = 0.45`, `min_long_close_location = 0.55`.
  - Max 1 signal per session; `entry_lag_bars = 1` (next-bar open).
- **Out-of-Sample Window**: `2025-01-01` to `2026-04-28` on `data/raw/nq_1m_2014_2026_merged.parquet` (starting export from `2024-12-15` to ensure prior-session profile warmup for the first session of 2025, then evaluating strictly on `2025-01-01:2026-04-28`).
- **Primary Evaluation Horizon**: **24 bars** (with supporting diagnostics at `1, 3, 6, 12, 24, 30` bars).

---

## 3. Strict Out-of-Sample Falsification Criteria (`2025-01-01` to `2026-04-28`)

`H5-OOS` passes out-of-sample validation if and only if at the **24-bar horizon** in `2025-01-01:2026-04-28`:
1. **Net Expectancy After Base Cost (`1.50` pts)**: `mean_signed_return_after_cost_points > 0.0`.
2. **Cost Stress Survival**: Remains net positive under `2.00`pt and `4.25`pt round-trip stress costs (`stress_min_mean_signed_return_after_cost_points > 0.0`).
3. **Hit Rate & Period Stability**: `hit_rate_pct >= 52.0%` and `positive_signed_period_pct >= 55.0%`.
4. **Placebo Edge**: `placebo_edge_points > 0.0` against clock-matched `10:00–11:30 ET` entries.
5. **Directional Attribution Check**: Pre-registered inspection of `direction == long` (`VAL` rejection) vs. `direction == short` (`VAH` rejection) to verify whether both sides or only `VAL` Longs sustain positive net expectancy in `2025–2026`.
