"""
Unit Test Suite for Declarative Confluence Scoring Cards & Decision Traces.
Verifies all composable operators, veto rules, score thresholds, and JSON serialization.
"""

from __future__ import annotations

import json
import pytest

from backtest.confluence import (
    AllOf,
    AnyOf,
    AtLeast,
    Condition,
    ConfluenceCard,
    DecisionTrace,
    EvaluationContext,
    Not,
    Operator,
    PrimaryGroup,
    ScoreRule,
    SecondaryGroup,
    VetoGroup,
    VetoRule,
)


def test_basic_condition_operators():
    ctx = EvaluationContext(
        values={"close": 21500.25, "vah": 21450.00, "val": 21300.00, "rvol": 1.45, "state": "BULLISH"},
        previous_values={"close": 21440.00, "vah": 21450.00},
    )

    # Greater than & Reference
    c_gt = Condition("close", Operator.GT, reference="vah")
    assert c_gt.evaluate(ctx) is True

    # Less than
    c_lt = Condition("close", Operator.LT, reference="val")
    assert c_lt.evaluate(ctx) is False

    # Between
    c_between = Condition("rvol", Operator.BETWEEN, value=(1.0, 2.0))
    assert c_between.evaluate(ctx) is True

    # String Equality
    c_eq = Condition("state", Operator.EQ, value="BULLISH")
    assert c_eq.evaluate(ctx) is True

    # Sequential Crossing
    c_cross = Condition("close", Operator.CROSS_ABOVE, reference="vah")
    assert c_cross.evaluate(ctx) is True


def test_composable_logic_expressions():
    ctx = EvaluationContext(
        values={"a": 10, "b": 20, "c": 30, "d": 40},
    )

    cond_a = Condition("a", Operator.EQ, 10)
    cond_b = Condition("b", Operator.EQ, 20)
    cond_c = Condition("c", Operator.GT, 100)  # False

    # AllOf
    all_pass = AllOf(cond_a, cond_b)
    all_fail = AllOf(cond_a, cond_c)
    assert all_pass.evaluate(ctx) is True
    assert all_fail.evaluate(ctx) is False

    # AnyOf
    any_pass = AnyOf(cond_a, cond_c)
    assert any_pass.evaluate(ctx) is True

    # Not
    not_c = Not(cond_c)
    assert not_c.evaluate(ctx) is True

    # AtLeast
    at_least_2 = AtLeast(2, cond_a, cond_b, cond_c)
    at_least_3 = AtLeast(3, cond_a, cond_b, cond_c)
    assert at_least_2.evaluate(ctx) is True
    assert at_least_3.evaluate(ctx) is False


def test_confluence_card_trade_allowed():
    card = ConfluenceCard(
        name="Morning_VA_Breakout_Long",
        direction="LONG",
        primary=PrimaryGroup(
            ScoreRule("breakout_above_vah", Condition("close", Operator.GT, reference="vah"), weight=40.0),
            minimum_matches=1,
        ),
        secondary=SecondaryGroup(
            ScoreRule("rvol_surge", Condition("rvol", Operator.GTE, 1.25), weight=30.0),
            ScoreRule("orderflow_delta_pos", Condition("delta", Operator.GT, 0.0), weight=20.0),
            ScoreRule("vwap_above", Condition("close", Operator.GT, reference="vwap"), weight=10.0),
            minimum_score=30.0,
        ),
        vetoes=VetoGroup(
            VetoRule("fomc_news_guard", Condition("minutes_to_fomc", Operator.BETWEEN, (-5, 5)), reason="FOMC release window"),
            VetoRule("circuit_breaker", Condition("daily_pnl", Operator.LTE, -600.0), reason="Daily soft-stop breached"),
        ),
        min_total_score=60.0,
    )

    ctx_allowed = EvaluationContext(
        values={
            "close": 21550.0,
            "vah": 21500.0,
            "vwap": 21510.0,
            "rvol": 1.60,
            "delta": 2500,
            "minutes_to_fomc": 120,
            "daily_pnl": 0.0,
        }
    )

    trace = card.evaluate(ctx_allowed)
    assert trace.trade_allowed is True
    assert trace.decision == "TRADE_ALLOWED"
    assert trace.total_score == 100.0  # 40 + 30 + 20 + 10
    assert trace.primary_passed is True
    assert trace.veto_fired is None
    assert len(trace.passed_rules) == 4

    # JSON roundtrip test
    dumped = trace.to_json()
    parsed = json.loads(dumped)
    assert parsed["decision"] == "TRADE_ALLOWED"
    assert parsed["card_name"] == "Morning_VA_Breakout_Long"


def test_confluence_card_veto_override():
    card = ConfluenceCard(
        name="Morning_VA_Breakout_Long",
        direction="LONG",
        primary=PrimaryGroup(
            ScoreRule("breakout_above_vah", Condition("close", Operator.GT, reference="vah"), weight=50.0),
        ),
        vetoes=VetoGroup(
            VetoRule("daily_stop_hit", Condition("daily_pnl", Operator.LTE, -600.0), reason="Daily -$600 floor reached"),
        ),
        min_total_score=50.0,
    )

    # Even though setup is perfect, daily_pnl = -650 triggers a hard veto
    ctx_veto = EvaluationContext(
        values={"close": 21550.0, "vah": 21500.0, "daily_pnl": -650.0}
    )

    trace = card.evaluate(ctx_veto)
    assert trace.trade_allowed is False
    assert trace.decision == "VETOED"
    assert trace.veto_fired == "daily_stop_hit"
    assert "Daily -$600 floor reached" in trace.veto_reason


def test_confluence_card_insufficient_score():
    card = ConfluenceCard(
        name="Morning_VA_Breakout_Long",
        direction="LONG",
        primary=PrimaryGroup(
            ScoreRule("breakout_above_vah", Condition("close", Operator.GT, reference="vah"), weight=30.0),
        ),
        secondary=SecondaryGroup(
            ScoreRule("rvol_surge", Condition("rvol", Operator.GTE, 2.0), weight=30.0),
        ),
        min_total_score=50.0,
    )

    # Primary matches (30 pts), but rvol = 1.1 fails (0 pts) -> Total = 30 < 50
    ctx_low_score = EvaluationContext(
        values={"close": 21550.0, "vah": 21500.0, "rvol": 1.1}
    )

    trace = card.evaluate(ctx_low_score)
    assert trace.trade_allowed is False
    assert trace.decision == "INSUFFICIENT_SCORE"
    assert trace.total_score == 30.0
    assert "breakout_above_vah" in trace.passed_rules
    assert "rvol_surge" in trace.failed_rules
