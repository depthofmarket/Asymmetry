"""
Canonical Prop Firm Specifications & Invariant Rulebook.
========================================================
Single Source of Truth for Prop Firm Profiles (LucidFlex 25K, etc.).
All backtest engines, Monte Carlo simulators, live compliance watchdogs,
and AI agents MUST read from this registry.
No script or agent may invent, assume, or modify these rules without an explicit
rule change announced by Lucid Trading.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class LucidFlex25KProfile:
    """
    Official Canonical Specification for LucidFlex 25K Account.
    Verified with Lucid Trading compliance terms.
    """
    # ── Evaluation Phase ──
    ACCOUNT_SIZE: float = 25_000.0
    PROFIT_TARGET: float = 1_250.0
    TARGET_BALANCE: float = 26_250.0
    EVAL_TICKET_COST: float = 39.0             # One-Time Payment (OTP)
    MONTHLY_REBILL: float = 0.0                # STRICTLY $0.00 (Zero monthly subscription)
    TIME_LIMIT_DAYS: int = 0                   # No time expiration (trade at your own pace)
    MAX_TRAILING_DRAWDOWN: float = 1_000.0     # $1,000 trailing drawdown limit
    INITIAL_FLOOR: float = 24_000.0            # Starting floor ($25,000 - $1,000)
    DRAWDOWN_MODE: str = "eod_trailing"        # Trailing calculated on End-of-Day balance
    FLOOR_LOCK_PEAK_BALANCE: float = 26_100.0  # Peak EOD balance where floor locks permanently
    LOCKED_FLOOR_VALUE: float = 25_100.0       # Permanent locked floor (Base $25,000 + $100)
    DAILY_SOFT_STOP: float = 600.0             # -$600 halt for remainder of day (not account liquidation)
    MAX_MICRO_CONTRACTS: int = 10              # 1 Mini or 10 Micros max position limit
    CONSISTENCY_RULE_PCT: float = 40.0         # Max 40% of target profit from a single trading day

    # ── Funded Phase (Master / LiveSim) ──
    FUNDED_STARTING_BALANCE: float = 25_000.0  # Account resets to $25,000.00 on Day 1
    FUNDED_INITIAL_FLOOR: float = 24_000.0     # Drawdown floor resets to $24,000.00
    FUNDED_TRAILING_ALLOWANCE: float = 1_000.0 # Trails $1,000 behind peak EOD balance
    FUNDED_FLOOR_LOCK_PEAK: float = 26_100.0   # Trails up until peak reaches $26,100.00
    FUNDED_LOCKED_FLOOR: float = 25_100.0      # Once peak >= $26,100, floor locks at $25,100.00
    FUNDED_DAILY_SOFT_STOP: float = 600.0      # Same -$600 intraday halt

    # ── Payout Eligibility Requirements ──
    PAYOUT_MIN_PROFIT_DAYS: int = 5            # Minimum 5 separate days with >= min daily profit
    PAYOUT_MIN_DAILY_PROFIT: float = 100.0     # >= $100.00 net profit per qualifying day (not consecutive)
    PAYOUT_MIN_CYCLE_NET_PROFIT: float = 1.0   # >= $1.00 net cycle profit compared to previous payout
    PAYOUT_COUNTER_RESETS: bool = True         # 5-day profit counter resets to 0 after EVERY approved payout
    MAX_PAYOUTS_BEFORE_LIVE: int = 5           # Up to 5 payouts per account before transition to live brokerage

    # ── Payout Formula, Caps & Split ──
    PAYOUT_PCT_OF_PROFIT: float = 0.50         # Request 50% of accumulated profit above starting balance
    PAYOUT_MIN_REQUEST: float = 500.0          # $500.00 min gross request (Requires Balance >= $26,000.00)
    PAYOUT_MAX_REQUEST: float = 1_000.0        # $1,000.00 max gross request (Requires Balance >= $27,000.00)
    PROFIT_SPLIT_TRADER_PCT: float = 90.0      # Trader receives 90%
    PROFIT_SPLIT_PROP_PCT: float = 10.0        # Prop firm retains 10%
    MIN_NET_PAYOUT_TO_TRADER: float = 450.0    # 90% of $500.00 min request
    MAX_NET_PAYOUT_TO_TRADER: float = 900.0    # 90% of $1,000.00 max request
    BUFFER_BALANCE_MANDATE: float = 0.0        # LucidFlex does NOT mandate maintaining a static buffer balance

    @classmethod
    def get_eod_floor(cls, peak_balance: float) -> float:
        """
        Calculates trailing drawdown floor based on historical high-water mark.
        Trails $1,000 below peak EOD balance until peak reaches $26,100,
        then permanently locks at $25,100.
        """
        if peak_balance >= cls.FLOOR_LOCK_PEAK_BALANCE:
            return cls.LOCKED_FLOOR_VALUE
        return max(cls.INITIAL_FLOOR, peak_balance - cls.MAX_TRAILING_DRAWDOWN)

    @classmethod
    def get_remaining_cushion(cls, balance: float, peak_balance: float) -> float:
        """Calculates distance from current balance to the active liquidation floor."""
        floor = cls.get_eod_floor(peak_balance)
        return balance - floor

    @classmethod
    def is_payout_eligible(
        cls,
        balance: float,
        profitable_days_count: int,
        cycle_net_profit: float,
        payouts_completed: int,
    ) -> bool:
        """
        Evaluates whether an account qualifies for a payout request:
        1. Fewer than 5 payouts completed.
        2. At least 5 separate trading days with >= $100 daily profit.
        3. At least $1.00 net profit during this payout cycle.
        4. Balance >= $26,000 ($1,000 profit, so 50% profit >= $500 min payout).
        """
        if payouts_completed >= cls.MAX_PAYOUTS_BEFORE_LIVE:
            return False
        if profitable_days_count < cls.PAYOUT_MIN_PROFIT_DAYS:
            return False
        if cycle_net_profit < cls.PAYOUT_MIN_CYCLE_NET_PROFIT:
            return False
        profit = balance - cls.FUNDED_STARTING_BALANCE
        if profit * cls.PAYOUT_PCT_OF_PROFIT < cls.PAYOUT_MIN_REQUEST:
            return False
        return True

    @classmethod
    def get_required_post_payout_cushion(cls, gross_payout: float) -> float:
        """
        Dynamic post-payout cushion requirement:
        - Minimum payout ($500 gross): requires $400 remaining cushion
        - Maximum payout ($1,000 gross): requires $900 remaining cushion
        Linear interpolation: 400 + (gross_payout - 500), bounded between 400 and 900.
        """
        cush = 400.0 + (gross_payout - 500.0)
        return max(400.0, min(900.0, cush))

    @classmethod
    def calculate_payout(
        cls,
        balance: float,
        policy: str = "immediate_minimum",
        target_payout: float | None = None,
    ) -> tuple[float, float, float]:
        """
        Calculates payout amounts given current balance and policy:
        policy:
          - 'immediate' or 'immediate_minimum' (Policy A): Request as soon as eligible ($500 min)
          - 'patient' or 'patient_maximum' (Policy B): Wait until full $1,000 max payout is reachable (balance >= $27,000)
          - 'adaptive' (Policy C): Use target_payout threshold in [500, 1000]
        Returns: (gross_payout, trader_net_payout, post_payout_balance)
        """
        profit = max(0.0, balance - cls.FUNDED_STARTING_BALANCE)
        available_payout = min(cls.PAYOUT_MAX_REQUEST, profit * cls.PAYOUT_PCT_OF_PROFIT)

        if available_payout < cls.PAYOUT_MIN_REQUEST:
            return 0.0, 0.0, balance

        pol = policy.lower()
        if pol in ("patient", "patient_maximum") and available_payout < cls.PAYOUT_MAX_REQUEST:
            # Trader chooses to wait until reaching full $1,000 cap ($27,000 balance)
            return 0.0, 0.0, balance

        if pol == "adaptive" and target_payout is not None:
            if available_payout < target_payout:
                return 0.0, 0.0, balance
            gross_payout = min(available_payout, target_payout)
        elif pol in ("immediate", "immediate_minimum"):
            gross_payout = cls.PAYOUT_MIN_REQUEST
        else:
            gross_payout = available_payout

        trader_net = gross_payout * (cls.PROFIT_SPLIT_TRADER_PCT / 100.0)
        post_payout_balance = balance - gross_payout

        return gross_payout, trader_net, post_payout_balance


# Global Immutable Constant Instance
LUCID_FLEX_25K: Final[LucidFlex25KProfile] = LucidFlex25KProfile()
