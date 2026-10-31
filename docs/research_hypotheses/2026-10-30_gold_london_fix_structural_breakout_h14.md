# Pre-Registered Hypothesis `H14`: Gold (`GC` / `MGC`) `10:15 ET` Post-LBMA PM Fix Structural Breakout

- **Date**: `2026-10-30`
- **Status**: `PRE-REGISTERED`
- **Instrument**: COMEX Gold Futures (`GC` / Micro `MGC`, `$10.00`/pt per `MGC`, `$0.10` tick = `$1.00`)
- **Evaluation Dataset**: `data/raw/gc_1m_2020_2026_et.parquet` (`2,379,265` 1-minute CQG bars, `2020-01-29` to `2026-10-30`)
- **Signal Evaluation Bar**: `10:14:00 ET` bar close (completes at `10:15:00 ET`)
- **Execution Window**: Entry at `10:15:00 ET` open; hard time-exit at `11:00:00 ET` (`45` minutes, zero overlap with `09:45–10:15 ET` `MNQ`/`MES` Strategy 1 window)

---

## 1. Structural & Institutional Thesis

1. **Why Earlier Gold Windows (`08:20`, `08:35`, `09:20 ET`) Fail**:
   - In COMEX Gold (`GC`), the `08:20 ET` pit open sits 10 minutes before `08:30 AM ET` US macro releases (`CPI`, `NFP`, `Jobless Claims`, `PPI`, `Retail Sales`) and 100 minutes before the **`10:00 AM ET` (`15:00 London`) LBMA Gold PM Auction Fix** and `10:00 AM ET` US economic data (`ISM`, `JOLTS`, `Consumer Confidence`).
2. **Why `10:15:00 ET` Is the True Structural Inflection Point**:
   - Between `10:00:00` and `10:14:59 ET`, the LBMA Gold PM Auction Fix clears physical bullion bank imbalances and all `08:30 AM` / `10:00 AM` macro releases are fully absorbed.
   - When the `10:00–10:14 ET` Fix window drives price **above the 60-minute COMEX Initial Balance (`08:20–09:19 ET` `IB60_High`), above the London Session High (`03:00–08:19 ET` `Lon_High`), and outside the Prior Session RTH Value Area (`> Prior_VAH`)** with strong bar close location (`>= 0.70`), overhead bullion supply is cleared for continuation from `10:15–11:00 ET`.
   - Because Gold exhibits structural positive monetary drift (`$1,580` to `$3,905` over `2020–2026`) and post-Fix dip-buying squeezes shorts, primary deployment is **Long-Only** (`allow_short=False` by default, while logging `L+S` for comparison).

---

## 2. Point-in-Time Signal Specification (`10:14 ET` Bar Close)

At the close of the `10:14 ET` 1-minute bar (using only completed bars up to `10:14:59 ET`):
1. **Prior Session RTH Volume Profile (`08:20–13:30 ET`)**:
   - `prior_rth_poc`, `prior_rth_vah`, `prior_rth_val` computed from the prior completed session's 1-minute COMEX RTH bars (`bin_size = $0.50`, `value_area_pct = 0.70`).
2. **London Session Range (`03:00–08:19 ET`)**:
   - `lon_high = max(high)` and `lon_low = min(low)` over `03:00..08:19 ET` of the current session.
3. **COMEX 60-Minute Initial Balance (`08:20–09:19 ET`)**:
   - `ib60_high = max(high)` and `ib60_low = min(low)` over `08:20..09:19 ET` of the current session.
4. **LBMA PM Fix Window (`10:00–10:14 ET`, 15 minutes)**:
   - `fix_open = open(10:00)`, `fix_close = close(10:14)`, `fix_high = max(high, 10:00..10:14)`, `fix_low = min(low, 10:00..10:14)`
   - `fix_range = fix_high - fix_low`
   - `fix_return_pct = (fix_close - fix_open) / fix_open`
   - `fix_close_location = (fix_close - fix_low) / fix_range`
5. **Long Qualification (`candidate_signal = +1.0` at `10:14 ET`)**:
   - `fix_return_pct >= 0.001125` (`0.1125%`, ~`$3.00` on `$2,700` Gold)
   - `fix_close_location >= 0.70`
   - `fix_close > ib60_high`
   - `fix_close > lon_high`
   - `fix_close > prior_rth_vah`
6. **Risk & Exit Parameters**:
   - `stop_points = clip(fix_range, 3.0, 18.0)` (`$30` to `$180` per `MGC`)
   - `target_points = 1.50 * stop_points`
   - `time_exit = 11:00:00 ET` (`45` minutes max hold)
   - Friction: `$0.20`/oz slippage (2 ticks) + `$1.50`/RT commission per `MGC` (`$0.35`/oz total all-in cost).

---

## 3. Falsification Criteria

`H14` will be **rejected** if:
1. Net post-cost expectancy is $\le 0$ in either `2021–2024 (Core)` or `2025–2026 (OOS)` when evaluated with exact 1-minute Volume Profile (`_compute_prior_session_profiles`) and bar-by-bar stop/target execution.
2. Adding `H14` (`MGC` at `10:15 ET`) to the `MNQ + MES` (`09:45 ET`) portfolio degrades portfolio Profit Factor below `1.45` or increases portfolio Max Drawdown by more than `20%`.
