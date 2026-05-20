# Failed-Auction Quality Branch Rejection

Date: 2026-05-20

## Verdict

Reject the failed-auction quality branch. Do not create more variants from the same historical sample unless a real implementation bug is found.

This is a process decision, not a claim that failed auctions can never matter. The current branch has consumed enough related tests that further tuning would be selection bias, not research.

## Trigger Run

Run folder:

`results/runs/20260520_152332_edge_vp_mr_trend_failed_auction_quality_no_mr_long_ib_cusum_wf_stable_managed_stop_next_bar_long_short_next_bar_open_hybrid`

The run was stopped before walk-forward output was produced. That does not weaken the rejection; the branch failed before it reached the stricter validation stage.

## Evidence

Partial saved-run artifacts showed:

- Trades: 157
- Net PnL: -2757.99
- Profit factor: 0.85
- Win rate: 37.58 percent
- Daily Sharpe: -1.30
- Max drawdown: 5.87 percent
- Prop expected net payout per eval attempt: -42.00
- Prop eval-to-first-payout probability: 0.00 percent

Setup contribution was broad, not isolated:

- `mr_short`: PF 0.55, PnL -419.00
- `trend_long`: PF 0.89, PnL -1087.00
- `trend_short`: PF 0.82, PnL -1251.99

Execution realism did not rescue the branch:

- Current fill assumption PF: 0.85
- Target default slippage PF: 0.85
- Target stop-like slippage PF: 0.84

## Decision Rules

- The active validation queue is cleared.
- Failed-auction quality is listed in `RESEARCH_CONFIG["rejected_research_families"]`.
- Saved-run discipline gates must fail promotion for this family.
- Old candidate definitions stay in the repo for reproducibility only.
- A revival requires a new ex-ante hypothesis, untouched holdout or paper evidence, and survival through execution realism plus purged/embargoed walk-forward validation.

## Next Research Direction

Move away from failed-auction salvage. The next work should test execution and microstructure assumptions first: spread, fill timing, adverse selection, and whether the signal survives realistic order placement.
