# Microstructure Liquidity-Taking Trend Probe

Date: 2026-05-20

Status: rejected after stopped development run

## Hypothesis

Short-horizon NQ trend signals are only viable if directional expectancy remains positive after conservative liquidity-taking penalties and stop-like adverse fills.

## Fixed Pre-Run Assumptions

- Do not use failed-auction filters.
- Use point-in-time features only.
- Do not run a broad parameter search. Walk-forward and sweep surfaces are fixed to one parameter point for this candidate.
- Treat TBBO as execution-realism evidence only, not edge-mining data.
- Treat prop-firm reports as research-only unless the candidate survives scoped OOS or lockbox evidence.
- Count this as multiple-testing debt even if result folders are later deleted.

## Candidate Scope

- Candidate family: `microstructure_execution_first`
- Candidate: `edge_microstructure_liquidity_taking_trend_probe`
- Setups: `trend_long`, `trend_short`
- Position sizing: fixed 1 NQ contract
- Fill model: target fills require trade-through by one tick
- Managed stops: activate no earlier than the next bar
- Maximum trades per day: 5
- Maximum hold: 6 completed 5-minute bars

## Rejection Rules

Reject without tuning if any broad failure appears in trade PF, bar PF, execution realism, or walk-forward evidence. A context slice that looks better after the run is a hypothesis for a future sample, not permission to mutate this candidate on the same sample.

## Outcome

Rejected on 2026-05-20. The stopped development run showed 0.0% eval pass probability, 0.0% eval-to-first-payout probability, weak trade PF, negative long-side contribution, and no statistically convincing random-walk/sign-flip evidence. See `docs/research_postmortems/2026-05-20_microstructure_liquidity_taking_trend_probe_rejection.md`.
