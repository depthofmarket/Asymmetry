# Signal Gate Rejection Map And Feature Inventory

Date: 2026-05-24

Status: active research queue empty

## Verdict

The current pre-candidate signal queue is empty.

Liquidity absorption, compression breakout, gap-and-go, power-hour continuation, and memory impulse all failed promotion evidence. Do not write a strategy candidate from any of these branches unless a real implementation or metric bug is found.

The best next work is not another time-of-day or horizon mutation. The next defensible step is an execution-realism/TBBO audit or a structurally new, pre-registered hypothesis with a separate exporter and temporal gate.

## Rejection Map

| Branch | Structure | Best-looking evidence | Rejection evidence | Decision |
| --- | --- | --- | --- | --- |
| Liquidity absorption / failed continuation | Sweep/absorption continuation after a failed liquidity expansion. | Hour 11 at 24 bars: +1.836 points after cost, 225 active rows. | Aggregate was negative at every horizon. Best aggregate was 1 bar at -1.378 points after cost, 49.65% hit rate, 18.18% positive signed-period share, IC 0.0007. | Rejected. Do not mine hour 11 / 24 bars from the same sample. |
| Opening compression breakout | Tight opening compression, then directional breakout continuation. | Short-side / below-VWAP 24-bar context: +5.002 points after cost, 101 rows. | Aggregate active sample was only 195 rows. Best aggregate 24-bar row had +1.287 points after cost but 49.74% hit rate, 54.55% positive signed-period share, IC 0.0009, below gate thresholds. | Rejected. Treat short-side slice as diagnostic only. |
| RTH gap-and-go | Gap holds, opening range breaks with gap direction. | Recent long-side 12-bar context: +0.868 points after cost, 219 rows. | Temporal gate rejected every row. Recent aggregate 24-bar was only +0.217 points after cost with IC 0.0011; transition was negative at every aggregate horizon, including -1.569 points at 24 bars. | Rejected. Do not convert recent long-only behavior into a candidate. |
| Power-hour accepted-trend continuation | Late-RTH continuation after accepted trend flow into the close. | Recent 24-bar event row: +4.114 points after cost, median +4.250, 58.58% hit rate, 75.0% positive signed-period share, bootstrap CI low +1.233. | Temporal event gate failed. Transition 24-bar mean was only +0.085 points after cost with median -0.500 and bootstrap CI low -1.954; legacy 12/24-bar rows were negative. | Rejected. Interesting recent behavior, but no transition support. |
| Memory impulse | CUSUM impulse continuation in prior persistent/low-complexity market-memory state. | Recent 6-bar row: +8.821 points after cost. | Recent split had only 28 active rows, below the 30-row floor. The same 6-bar row had median -1.250 and bootstrap CI low -4.441. Transition was negative at every horizon, including -4.489 at 6 bars and -8.714 at 24 bars. | Rejected. Do not tune memory thresholds on the same sample. |

## Repeated Failure Modes

- The profitable-looking rows are mostly context slices discovered after seeing the report.
- Recent-period positives are not surviving transition support.
- Aggregate IC is far below the 0.0200 threshold across these branches.
- Mean after cost often looks better than the median or bootstrap lower bound.
- Clock/session buckets keep appearing as the rescue path. That is time-of-day tweaking unless declared before looking.
- Price-only OHLCV event definitions are either too sparse, too unstable, or too weak after a 1.5-point round-trip cost.

## Feature Inventory

Already tested and rejected as candidate inputs:

- Failed auction / profile-derived branches.
- Liquidity absorption / failed continuation.
- Opening compression breakout.
- Gap-and-go opening-range continuation.
- Power-hour accepted-trend continuation.
- Memory impulse continuation.

Existing feature machinery that should not be run casually:

- `scripts/run_feature_research_lab.py` and `backtest/feature_research.py` can generate broad event/feature research output from the full historical frame. Treat this as a full-sample scan and testing debt, not as lightweight inspection.
- `backtest/market_structure.py`, `backtest/market_profile.py`, `backtest/market_memory.py`, `backtest/markov_regime.py`, and related candidate configs are available, but they do not by themselves justify more candidate mutations.

Non-OHLCV data currently available:

- Options-flow features: `data/processed/options_nq/options_flow_daily.csv`, 101 data rows from 2010-06-17 through 2026-03-19. This is sparse daily/expiry-like context. Use it as a pre-registered regime tag, not as an intraday entry-mining surface.
- Options strike levels: `data/processed/options_nq/options_flow_strike_levels.csv`, 10,304 data rows. Useful for wall/proximity context if a hypothesis is written first.
- TBBO execution stats: `data/processed/tbbo/tbbo_daily_execution_stats.csv` and `data/processed/tbbo/tbbo_minute_execution_stats.csv`, covering 2026-02-15 through 2026-05-07. This should be used for execution realism: spread, fill shortfall, depth, and time/session cost checks. Do not use the small 2026 TBBO sample to mine signal filters.

## Next Work

Recommended next step: use the TBBO execution-realism baseline before mining another signal.

Baseline report: `results/research_master/tbbo_execution_baseline/tbbo_execution_baseline.md`.

Current baseline verdict: 1.5 points is acceptable for typical active-contract spread, but too low for tail trade-vs-mid conditions.

Signal-gate tooling now supports cost-stress survival with `--stress-round-trip-cost-points 2.0,4.25`. A future signal that only passes at 1.5 points but fails configured stress costs should not be promoted.

Reason: the current signal queue is empty, and the repeated failure mode is not "we need one more time filter." The larger unresolved risk is whether our assumed 1.5-point round-trip cost and fill model are honest across the sessions where prop-firm candidates would actually trade.

Concrete scope:

1. Regenerate the baseline with `python3.12 scripts/audit_tbbo_execution_baseline.py` when TBBO stats change.
2. Use active-contract session/hour outputs to choose future cost-stress settings.
3. Use `scripts/audit_trades_with_tbbo.py` only when a saved run has enough trade overlap with the TBBO coverage window.
4. Run only syntax/unit checks from automation. A full candidate backtest remains user-run only.

Alternative next hypothesis if we choose signal mining instead: options-flow regime gating, written ex ante. The viable shape is not "find an options-flow threshold"; it is a specific market-mechanics claim such as "opening continuation behaves differently when price is inside a positive-gamma pinning wall versus outside it." That would need a new hypothesis doc before any export or temporal gate.
