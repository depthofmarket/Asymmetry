---
name: adversarial-red-team
description: "Executes adversarial stress testing, ±25% parameter sensitivity plateau sweeps (Belfort Step 07), 10,000-path Monte Carlo corridor generation (Belfort Step 08), Deflated Sharpe Ratio (DSR), and lookahead bias falsification."
---

# Adversarial Red-Team Skill (`adversarial-red-team`)

Use this skill whenever evaluating a candidate strategy, auditing backtest robustness, running parameter sensitivity sweeps, or stress-testing against the 5th percentile Monte Carlo corridor.

## 1. Parameter Sensitivity Plateau Sweep (Belfort Step 07)
- Rule: Vary all core parameters by $\pm 25\%$ across 5 steps: `[-25%, -12.5%, 0%, +12.5%, +25%]`.
- Plateau Definition: Performance must remain stable across the sweep.
  $$\text{Stability Ratio} = \frac{\min(\text{PnL}_{\text{sweep}})}{\text{PnL}_{\text{base}}} \ge 0.70\text{x}$$
- Execution Command:
  ```bash
  python scripts/run_parameter_plateau_sweep.py
  ```
- Output Artifacts:
  - Report: `results/parameter_plateau_sweep/parameter_plateau_sensitivity_report.md`
  - Visual Overview: `results/parameter_plateau_sweep/composite_parameter_plateau_overview.png`
  - Per-Strategy Charts: `plateau_sweep_s1.png`, `plateau_sweep_s2.png`, `plateau_sweep_s3.png`

## 2. 10,000-Path Monte Carlo Corridor & Live Overlay (Belfort Step 08)
- Rule: Generate 10,000 block-bootstrap paths of length $T=30$ sessions incorporating LucidFlex ratchet sizing and Safe CPPI floor de-leveraging.
- Execution Command:
  ```bash
  python scripts/generate_monte_carlo_corridor.py
  ```
- Circuit Breaker Rule:
  If cumulative live equity drops below the 5th percentile ($P_{05}$), halt all trading immediately and diagnose regime break (`REGIME_STRESS_WARNING`).

## 3. Deflated Sharpe Ratio (DSR) & Multiple Testing Correction
- Evaluates the Bailey & López de Prado (2014) EVT adjustment for the number of tested trials $N$:
  ```python
  from backtest import dashboard_analytics as da
  sr_star = da.expected_max_sharpe(trials=20, var_sharpe=0.5)
  dsr = da.deflated_sharpe_ratio(annual_sharpe=1.65, trades=316, skewness=-0.2, kurtosis=3.5, trials=20, var_sharpe=0.5)
  ```
- If $DSR \le 0.0$, the apparent edge is consistent with random multiple testing noise and cannot be approved.
