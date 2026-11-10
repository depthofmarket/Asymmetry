# Java study to in-sample chart replay

The replay in `backtest/study_chart_replay.py` follows the current `calculate` methods. It stops at 2024-12-31. It is not a live-order backtest and it is not the frozen trade parquet.

| Java rule | Replay |
|---|---|
| S1 prior RTH 09:30–15:59 volume profile, 70% value area, signal on the first 09:45 bar | `replay_morning_va` |
| S1 long/short: 15-minute return, close location, outside prior VAH/VAL | Same thresholds as the study defaults: 0.10%, 0.60, 0.40 |
| S1 stop is the opening range clamped to 15–60 NQ points or 15–35 ES points; target is 1.5R | Same clamps. MNQ is $2/point and MES is $5/point |
| S1 fixed volatility input, not a fitted GARCH model: 1.25% NQ, 0.72% ES, exhaustion at 2.50 | Same constants. The study setting is a constant, not a model forecast |
| S1 news flatten uses `is10amNewsDay` weekday heuristics, then 10:15 flatten | `is_s1_news_day` and the same exit order |
| S1 chart checks target, then stop, then news, then time, only on a bar after the entry bar | `_walk_exit` |
| S2 08:35 only. Overnight high/low is 00:00–08:29 on the same calendar date. Volume baseline is 08:00–08:29 when at least 10 bars exist, otherwise the divisor is 1 | `replay_macro_0835` |
| S2 default high-vol gate is off. Stops are half the 08:30–08:34 range, clamped to 20–50 points. Flatten is entry plus 50 minutes | Same |
| S2 10:00 Tier-2 window | Not replayed. Live submission is fail-closed in `MacroTenAmOrderGate` |
| S3 long only at the first 10:15 bar. Fix window 10:00–10:14, London high 03:00–08:19, IB60 08:20–09:19, prior COMEX value area 08:20–13:30 | `replay_gold_fix` with the study defaults, including the 0.1125% return and 0.70 close location |
| Chart quantity when daemon state is unverified | 2 contracts. Live `resolveContracts` returns 0 without a verified state file, so these rows are chart marks, not broker orders |
| Chart dollars | `points * point value * 2`. Commission and slippage are 0 because the Java chart formula does not deduct them |
| Equal-volume POC | Lowest price. Java `HashMap` iteration does not define this tie |
| Signal bar | S1 uses the first 09:45–09:59 bar. S2 uses the first 08:35–08:59 bar and consumes the day even when the spike is incomplete. S3 uses the first bar at or after 10:15 on that calendar date |
| Flatten | Same calendar date only. S1 flattens at entry plus 30 minutes or 10:15. S2 flattens at entry plus 50 minutes. S3 flattens at entry plus 45 minutes or 11:00. A trade that never reaches that bar stays open in the study and is omitted here |
| S2 high-vol gate | Descriptor default is false. The `getBoolean` fallback of true applies only when the setting key is absent |
| S1 pair split | Descriptor default is false, so the unverified chart quantity stays at 2. The code fallback of true applies only when the setting key is absent |
| Missing account file | Circuit breaker is not hit and chart quantity is 2. Live order submission still returns 0 contracts |

The price files are timezone-naive and are read as ET wall time. Each file has one symbol and no roll calendar. CL gaps are left in place. Bars on or after 2025-01-01 are not loaded.

`python scripts/regenerate_insample_study_trades.py` prints the in-sample trade count, gross P&L, commission, slippage, net P&L, profit factor, drawdown, slice hash, parameter hash, trade-list hash, and full git SHA. `--record` inserts new provenance ids. It does not update `run_canonical_s5_crude_rth_expansion_2021_2026`.
