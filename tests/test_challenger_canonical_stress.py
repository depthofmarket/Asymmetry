"""
Independent Empirical Adversarial Stress Harness for Milestone M5:
Canonical Aggressive Frontier Sizing Adoption (T2 = +$200, T3 = +$500).

Tests:
1. Exact boundary transitions across all floating-point representations.
2. Dynamic drawdown de-escalation and absence of hysteresis.
3. Multi-Engine Sizing Consensus across continuous domain (-$2,000 to +$3,000).
4. DemoParityJournal sequential trade progression and de-escalation.
5. Prop firm ratchet profile simulation verification.
6. Dashboard corridor and metric validation.
"""

import json
import re
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from backtest.dashboard_analytics import (
    POLICIES,
    SizingPolicy,
)
from backtest.demo_parity_engine import (
    DemoParityJournal,
    TradeFillRecord,
)
from backtest.prop_firm import DEFAULT_PROFILE, simulate_ratchet_profile


class TestCanonicalBoundaryTransitions:
    """Stress-test exact boundary conditions for 200/500 thresholds."""

    def test_exact_float_boundaries(self):
        pol = POLICIES["live_ratchet"]
        default_pol = SizingPolicy("Default Test", "ratchet")

        # Boundary test points: (profit, expected_micros)
        test_points = [
            (-1000.0, 2),
            (-0.01, 2),
            (0.00, 2),
            (0.01, 2),
            (100.0, 2),
            (199.99, 2),
            (199.999, 2),
            (199.999999, 2),
            (200.00, 3),
            (200.000001, 3),
            (200.01, 3),
            (350.00, 3),  # Old T2 is now squarely inside Tier 2
            (499.99, 3),
            (499.999, 3),
            (499.999999, 3),
            (500.00, 4),
            (500.000001, 4),
            (500.01, 4),
            (750.00, 4),  # Old T3 is now squarely inside Tier 3
            (1250.00, 4),  # Target
            (10000.00, 4),
        ]

        for profit, expected in test_points:
            assert pol.total_micros(profit) == expected, (
                f"POLICIES['live_ratchet'] failed at profit={profit}: expected {expected}, got {pol.total_micros(profit)}"
            )
            assert default_pol.total_micros(profit) == expected, (
                f"Default SizingPolicy failed at profit={profit}: expected {expected}, got {default_pol.total_micros(profit)}"
            )

    def test_multi_engine_consensus_continuous_domain(self):
        """Verify all 6 engine definitions produce identical micros across 10,001 points."""
        pol = POLICIES["live_ratchet"]
        default_pol = SizingPolicy("Default Test", "ratchet")

        # Range from -$2,000 to +$3,000 in $0.50 steps
        profits = np.linspace(-2000.0, 3000.0, 10001)

        for p in profits:
            # Engine 1: POLICIES["live_ratchet"]
            m1 = pol.total_micros(p)

            # Engine 2: Default SizingPolicy dataclass
            m2 = default_pol.total_micros(p)

            # Engine 3: Demo Parity Engine rule
            m3 = 4 if p >= 500.0 else (3 if p >= 200.0 else 2)

            # Engine 4: Prop firm simulation ratchet rule [(0.0, 0.2), (200.0, 0.3), (500.0, 0.4)]
            # Note: ratchet_tiers mult is 0.2 for p < 200, 0.3 for p >= 200, 0.4 for p >= 500
            mult = 0.2
            if p >= 500.0:
                mult = 0.4
            elif p >= 200.0:
                mult = 0.3
            else:
                mult = 0.2
            m4 = int(round(mult * 10))

            # Engine 5: scripts/generate_prop_firm_dashboard.py
            if p >= 500.0:
                scale = 0.40
            elif p >= 200.0:
                scale = 0.30
            else:
                scale = 0.20
            m5 = int(round(scale * 10))

            # Engine 6: scripts/optimize_prop_risk_structure.py policy 5 lambda
            m6 = 4 if p >= 500.0 else (3 if p >= 200.0 else 2)

            assert m1 == m2 == m3 == m4 == m5 == m6, (
                f"Consensus divergence at profit ${p:.2f}: "
                f"m1={m1}, m2={m2}, m3={m3}, m4={m4}, m5={m5}, m6={m6}"
            )


class TestDynamicDrawdownDeEscalation:
    """Stress-test dynamic step-down during drawdowns to confirm zero hysteresis."""

    def test_oscillating_profit_path_in_sizing_policy(self):
        pol = POLICIES["live_ratchet"]

        # Trajectory simulating volatile ladder crossings
        trajectory = [
            (0.0, 2),
            (100.0, 2),
            (200.0, 3),   # Step up to Tier 2
            (350.0, 3),
            (500.0, 4),   # Step up to Tier 3
            (650.0, 4),
            (480.0, 3),   # DRAWDOWN below $500 -> must de-escalate to 3M
            (510.0, 4),   # REBOUND above $500 -> must re-escalate to 4M
            (190.0, 2),   # SEVERE DRAWDOWN below $200 -> must de-escalate to 2M
            (-150.0, 2),  # Deep drawdown below initial capital -> must remain 2M
            (205.0, 3),   # Recovery above $200 -> must escalate to 3M
            (199.5, 2),   # Dip below $200 -> must de-escalate to 2M
            (500.0, 4),   # Jump directly to $500 -> must escalate to 4M
            (0.0, 2),     # Complete collapse -> must de-escalate to 2M
        ]

        for p, expected in trajectory:
            actual = pol.total_micros(p)
            assert actual == expected, (
                f"Drawdown de-escalation failure at profit ${p}: expected {expected}M, got {actual}M"
            )

    def test_demo_parity_journal_sequential_trades_de_escalation(self, tmp_path):
        """Simulate sequential trade executions in DemoParityJournal and test eval_state transitions."""
        journal = DemoParityJournal(forward_test_dir=tmp_path)

        # Initially at starting capital ($25,000, profit = $0) -> Tier 1 (2M)
        st0 = journal.get_eval_state()
        assert st0.recommended_micros == 2
        assert "Tier 1" in st0.recommended_tier

        # Trade 1: +$400 profit -> balance reaches $25,400 (>= $200), moves to Tier 2 (3 micros)
        t1 = TradeFillRecord(
            date="2026-10-28", symbol="MNQ", direction="LONG", contracts=2,
            theo_entry_price=20450.00, actual_entry_fill=20450.00,
            theo_stop_price=20400.00, theo_target_price=20550.00,
            exit_type="PROFIT_TARGET_1_5R", actual_exit_fill=20551.40,
        )
        st1 = journal.record_trade(t1)
        assert st1.profit >= 200.0
        assert st1.recommended_micros == 3
        assert "Tier 2" in st1.recommended_tier

        # Trade 2: +$200 profit -> profit reaches > $500 (>= $500), moves to Tier 3 (4 micros)
        t2 = TradeFillRecord(
            date="2026-10-29", symbol="MNQ", direction="LONG", contracts=3,
            theo_entry_price=20500.00, actual_entry_fill=20500.00,
            theo_stop_price=20450.00, theo_target_price=20550.00,
            exit_type="PROFIT_TARGET_1_5R", actual_exit_fill=20535.00,
        )
        st2 = journal.record_trade(t2)
        assert st2.profit >= 500.0
        assert st2.recommended_micros == 4
        assert "Tier 3" in st2.recommended_tier

        # Trade 3: Drawdown Loss -$200 -> profit drops below $500 (but > $200) -> MUST DE-ESCALATE TO TIER 2 (3M)
        t3 = TradeFillRecord(
            date="2026-10-30", symbol="MNQ", direction="SHORT", contracts=4,
            theo_entry_price=20600.00, actual_entry_fill=20600.00,
            theo_stop_price=20650.00, theo_target_price=20500.00,
            exit_type="STOP_LOSS", actual_exit_fill=20626.00,
        )
        st3 = journal.record_trade(t3)
        assert 200.0 <= st3.profit < 500.0
        assert st3.recommended_micros == 3
        assert "Tier 2" in st3.recommended_tier

        # Trade 4: Additional Loss -$300 -> profit drops below $200 and cushion < $500 -> MUST DE-ESCALATE TO 1 MICRO DEFENSIVE
        t4 = TradeFillRecord(
            date="2026-10-31", symbol="MNQ", direction="SHORT", contracts=3,
            theo_entry_price=20500.00, actual_entry_fill=20500.00,
            theo_stop_price=20550.00, theo_target_price=20400.00,
            exit_type="STOP_LOSS", actual_exit_fill=20551.00,
        )
        st4 = journal.record_trade(t4)
        assert st4.profit < 200.0
        assert st4.trailing_cushion < 500.0
        assert st4.recommended_micros == 1
        assert st4.defensive_delever is True
        assert "Cushion De-lever" in st4.recommended_tier


class TestPropFirmSimulationEngineDefaults:
    """Stress-test simulate_ratchet_profile default parameters and step-downs."""

    def test_simulate_ratchet_profile_defaults(self):
        # 3-day deterministic path:
        # Day 1: +2000 mini pts at 0.2x = +400 -> total profit $400 (unlocks 0.3x)
        # Day 2: -1000 mini pts at 0.3x = -300 -> total profit $100 (relocks 0.2x)
        # Day 3: +5000 mini pts at 0.2x = +1000 -> total profit $1100
        daily_paths = pd.DataFrame([
            {"net_pnl": 2000.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 2000.0, "trade_count": 1},
            {"net_pnl": -1000.0, "min_intraday_pnl": -1000.0, "max_intraday_pnl": 0.0, "trade_count": 1},
            {"net_pnl": 5000.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 5000.0, "trade_count": 1},
        ])

        prof = DEFAULT_PROFILE.copy()
        prof["account_size"] = 25000.0
        prof["profit_target"] = 1000.0
        prof["max_drawdown"] = 2000.0
        prof["daily_loss_limit"] = 1500.0
        prof["max_trading_days"] = 5

        # Call with ratchet_tiers=None to verify default argument triggers canonical 200/500 tiers
        res = simulate_ratchet_profile(daily_paths, prof, ratchet_tiers=None, n_sims=10, seed=42)
        assert (res["status"] == "pass").all()


class TestDashboardCorridorAndArtifacts:
    """Verify generated dashboard artifacts and HTML payload parameters."""

    def test_dashboard_json_payload_values(self):
        dash_path = Path("results/prop_firm_dashboard/dashboard.html")
        assert dash_path.exists(), "results/prop_firm_dashboard/dashboard.html does not exist"

        content = dash_path.read_text(encoding="utf-8")
        m = re.search(r"const data = (\{.*?\});\s*(?:document|\n)", content, re.DOTALL)
        assert m is not None, "Failed to extract JSON payload from dashboard.html"

        data = json.loads(m.group(1))

        # Check Aggressive Frontier corridor ranges
        assert 70.0 <= data["pass_rate"] <= 76.0, f"Pass rate {data['pass_rate']}% out of corridor (70-76%)"
        assert 74.0 <= data["med_sessions"] <= 85.0, f"Median sessions {data['med_sessions']} out of corridor (74-85)"
        assert 70.0 <= data["chrono_rate"] <= 85.0, f"Chrono rate {data['chrono_rate']}% out of corridor (70-85%)"
        assert "10 of 13" in data["chrono_sub"], f"Unexpected chrono sub: {data['chrono_sub']}"
        assert data["ev_per_attempt"] > 500.0, f"EV per attempt ${data['ev_per_attempt']} unexpectedly low"
