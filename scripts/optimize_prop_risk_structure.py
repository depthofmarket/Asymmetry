#!/usr/bin/env python3
"""
Prop Firm Risk Structure & Expected Value (EV) Optimization Engine.
Simulates 10,000 evaluation campaigns across 8 distinct risk and sizing architectures
on the 546-trade unified dataset (2021-2026).
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def simulate_eval_and_funded(
    daily_groups: list[list[float]],  # list of days, each day has list of trade 1-contract PnLs
    sizing_fn,
    n_sims: int = 10_000,
    seed: int = 42
):
    rng = np.random.default_rng(seed)
    n_days = len(daily_groups)
    
    # Trackers
    eval_passes = 0
    eval_fails = 0
    eval_timeouts = 0
    eval_days = []
    
    funded_payouts = []
    
    for _ in range(n_sims):
        # 1. EVALUATION ATTEMPT
        balance = 25_000.0
        peak = 25_000.0
        floor = 24_000.0
        passed = False
        failed = False
        days_taken = 0
        
        # Sample days with replacement
        day_indices = rng.choice(n_days, size=100, replace=True)
        
        for d_idx in day_indices:
            days_taken += 1
            day_trades_1c = daily_groups[d_idx]
            
            day_pnl = 0.0
            day_halted = False
            
            for t_1c in day_trades_1c:
                if day_halted:
                    break
                curr_profit = balance - 25_000.0
                size = sizing_fn(curr_profit, "eval")
                t_pnl = t_1c * size
                day_pnl += t_pnl
                balance += t_pnl
                
                # Check soft daily stop (-$600)
                if day_pnl <= -600.0:
                    day_halted = True
                    
                # Check pass target
                if balance >= 26_250.0:
                    passed = True
                    break
                    
            if passed:
                break
                
            # EOD Floor trailing
            if balance > peak:
                peak = balance
                if peak >= 26_100.0:
                    floor = 25_100.0
                else:
                    floor = peak - 1_000.0
                    
            if balance <= floor:
                failed = True
                break
                
        if passed:
            eval_passes += 1
            eval_days.append(days_taken)
            
            # 2. FUNDED STAGE SIMULATION
            # Start funded account with $25,000 balance
            f_balance = 25_000.0
            f_peak = 25_000.0
            f_floor = 24_000.0 # $1,000 buffer
            f_payout_total = 0.0
            f_payouts_count = 0
            
            f_day_indices = rng.choice(n_days, size=150, replace=True)
            for fd_idx in f_day_indices:
                f_trades_1c = daily_groups[fd_idx]
                f_day_pnl = 0.0
                f_day_halted = False
                
                for ft_1c in f_trades_1c:
                    if f_day_halted:
                        break
                    # In funded stage, risk management can be defensive
                    f_curr_profit = f_balance - 25_000.0
                    f_size = sizing_fn(f_curr_profit, "funded")
                    ft_pnl = ft_1c * f_size
                    f_day_pnl += ft_pnl
                    f_balance += ft_pnl
                    
                    if f_day_pnl <= -600.0:
                        f_day_halted = True
                        
                # Update funded floor
                if f_balance > f_peak:
                    f_peak = f_balance
                    f_floor = min(25_000.0, f_peak - 1_000.0)
                    
                if f_balance <= f_floor:
                    # Funded account blown
                    break
                    
                # Payout threshold: every time balance reaches $26,100 ($1,000 payout + $100 buffer)
                if f_balance >= 26_100.0 and f_payouts_count < 5:
                    payout_amt = 1_000.0
                    f_balance -= payout_amt
                    f_peak -= payout_amt # floor remains protected
                    f_payout_total += payout_amt
                    f_payouts_count += 1
                    
            funded_payouts.append(f_payout_total)
            
        elif failed:
            eval_fails += 1
        else:
            eval_timeouts += 1
            
    pass_rate = (eval_passes / n_sims) * 100.0
    fail_rate = (eval_fails / n_sims) * 100.0
    med_days = float(np.median(eval_days)) if eval_days else 0.0
    evals_per_pass = (n_sims / eval_passes) if eval_passes > 0 else 999.0
    cost_per_pass = evals_per_pass * 39.0
    
    # Expected payout across all passed accounts
    mean_funded_payout = float(np.mean(funded_payouts)) if funded_payouts else 0.0
    p_at_least_1_payout = float(np.mean([p > 0 for p in funded_payouts])) * 100.0 if funded_payouts else 0.0
    
    # Expected Value per $39 ticket:
    # EV = P(pass) * Mean(payout) - $39.0
    ev_per_ticket = (pass_rate / 100.0) * mean_funded_payout - 39.0
    
    return {
        "pass_rate": pass_rate,
        "fail_rate": fail_rate,
        "med_days": med_days,
        "evals_per_pass": evals_per_pass,
        "cost_per_pass": cost_per_pass,
        "p_payout": p_at_least_1_payout,
        "mean_payout": mean_funded_payout,
        "ev_per_ticket": ev_per_ticket,
    }


def main():
    p = ROOT / "data/processed/unified_three_strategy_portfolio_trades_2021_2026.parquet"
    df = pd.read_parquet(p)
    
    # 1-contract P&L
    df["pnl_1c"] = df["net_dollars_micro"] / df["contracts"]
    
    # Group by date_str preserving intra-day order
    daily_groups = []
    for d_str, g in df.groupby("date_str", sort=False):
        daily_groups.append(g["pnl_1c"].tolist())
        
    print(f"Total Trading Days in Ensemble: {len(daily_groups)}")
    
    # Define Sizing Architectures to Compare
    policies = [
        ("1. Static 1 Micro (Ultra Defensive)", lambda p, mode: 1),
        ("2. Static 2 Micros (Conservative Baseline)", lambda p, mode: 2),
        ("3. Static 3 Micros (Balanced Static)", lambda p, mode: 3),
        ("4. Static 4 Micros (Aggressive Flat)", lambda p, mode: 4),
        ("5. Canonical Ratchet: 2 -> 3 -> 4 Micros", lambda p, mode: (
            4 if p >= 500.0 else (3 if p >= 200.0 else 2)
        )),
        ("6. Dynamic Ratchet: 2 -> 4 -> 6 Micros", lambda p, mode: (
            6 if p >= 750.0 else (4 if p >= 350.0 else 2)
        )),
        ("7. Asymmetric Sprint: 2 -> 3 -> 5 Micros", lambda p, mode: (
            5 if p >= 750.0 else (3 if p >= 350.0 else 2)
        )),
        ("8. Overleveraged: Static 1 Mini (10 Micros)", lambda p, mode: 10),
    ]
    
    print("\n" + "=" * 92)
    print("      LUCID 25K RISK STRUCTURE & EXPECTED VALUE (EV) OPTIMIZATION MATRIX")
    print("=" * 92)
    print(f"{'POLICY':<38} | {'PASS %':>6} | {'FAIL %':>6} | {'DAYS':>4} | {'COST/PASS':>9} | {'PAYOUT %':>8} | {'AVG PAYOUT':>10} | {'EV / $39':>9}")
    print("-" * 92)
    
    results = []
    for name, s_fn in policies:
        res = simulate_eval_and_funded(daily_groups, s_fn, n_sims=10_000, seed=42)
        results.append((name, res))
        ev_str = f"+${res['ev_per_ticket']:,.2f}" if res['ev_per_ticket'] >= 0 else f"-${abs(res['ev_per_ticket']):,.2f}"
        print(f"{name:<38} | {res['pass_rate']:>5.1f}% | {res['fail_rate']:>5.1f}% | {res['med_days']:>3.0f}d | ${res['cost_per_pass']:>8.2f} | {res['p_payout']:>7.1f}% | ${res['mean_payout']:>9.2f} | {ev_str:>9}")
    print("=" * 92)

if __name__ == "__main__":
    main()
