"""
Strategy Registry & Quantitative Governance Module.

Defines:
1. StrategyTier enum: BASELINE, FORWARD_DEMO, CANDIDATE, REJECTED.
2. Canonical registry of authorized production baseline strategies.
3. Utility functions for tier inspection, baseline validation, and candidate registration.
4. Strict isolation guarantees ensuring research candidates cannot contaminate production baselines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class StrategyTier(str, Enum):
    """
    Quantitative strategy lifecycle tiers.

    BASELINE: Frozen production strategies running live/in-production with verified walkforward provenance.
    FORWARD_DEMO: Active live demo or paper trading parity ledgers.
    CANDIDATE: Research candidates undergoing empirical validation, walkforward, and red-team audits.
    REJECTED: Falsified hypotheses permanently retired to wiki/failed_ideas.md.
    """
    BASELINE = "BASELINE"
    FORWARD_DEMO = "FORWARD_DEMO"
    CANDIDATE = "CANDIDATE"
    REJECTED = "REJECTED"

    @classmethod
    def from_str(cls, val: str | StrategyTier) -> StrategyTier:
        if isinstance(val, StrategyTier):
            return val
        clean = str(val).strip().upper()
        if clean in cls.__members__:
            return cls[clean]
        for member in cls:
            if member.value == clean:
                return member
        raise ValueError(f"Unknown StrategyTier: '{val}'. Expected one of: {[m.value for m in cls]}")


@dataclass(frozen=True)
class StrategyMetadata:
    """Immutable metadata record for a registered strategy."""
    strategy_id: str
    name: str
    tier: StrategyTier
    instrument: str = ""
    timeframe: str = "1m"
    schedule: str = ""
    description: str = ""
    author: str = "LucidFlex Quantitative Team"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "tier": self.tier.value,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "schedule": self.schedule,
            "description": self.description,
            "author": self.author,
        }


# Canonical Production Baselines (Frozen Production Architecture)
AUTHORIZED_BASELINE_STRATEGIES: Dict[str, StrategyMetadata] = {
    "morning_va_breakout_s1": StrategyMetadata(
        strategy_id="morning_va_breakout_s1",
        name="Morning VA Breakout (09:45 ET)",
        tier=StrategyTier.BASELINE,
        instrument="MNQ/MES",
        timeframe="1m",
        schedule="09:45–10:15 ET",
        description="Dual-asset opening range breakout outside prior session Value Area with GARCH MVT exhaustion filter.",
    ),
    "macro_momentum_s2": StrategyMetadata(
        strategy_id="macro_momentum_s2",
        name="Macro Release Momentum (08:35 ET)",
        tier=StrategyTier.BASELINE,
        instrument="MNQ",
        timeframe="1m",
        schedule="08:35–09:00 ET",
        description="MNQ pre-market directional momentum following Tier-1 macro releases with Markov high-vol adaptive sizing.",
    ),
    "gold_london_fix_s3": StrategyMetadata(
        strategy_id="gold_london_fix_s3",
        name="Gold London Fix Breakout (10:15 ET)",
        tier=StrategyTier.BASELINE,
        instrument="MGC",
        timeframe="1m",
        schedule="10:15–11:00 ET",
        description="COMEX Micro Gold structural breakout following LBMA London PM bullion fix clearing.",
    ),
    "lucid_flex_ensemble": StrategyMetadata(
        strategy_id="lucid_flex_ensemble",
        name="LucidFlex Tri-Asset Ensemble",
        tier=StrategyTier.BASELINE,
        instrument="MNQ/MES/MGC",
        timeframe="1m",
        schedule="Multi-Session",
        description="Composite tri-asset multi-strategy portfolio coordinating S1, S2, and S3 under LucidFlex 25K risk limits.",
    ),
    "lucid_flex_forward_demo": StrategyMetadata(
        strategy_id="lucid_flex_forward_demo",
        name="LucidFlex Forward Demo Parity",
        tier=StrategyTier.FORWARD_DEMO,
        instrument="MNQ/MES/MGC",
        timeframe="1m",
        schedule="Live Forward",
        description="Live paper demo parity ledger tracking MotiveWave execution against backtest expectations.",
    ),
}

# Dynamic registry containing baseline strategies and registered candidates
_REGISTRY: Dict[str, StrategyMetadata] = dict(AUTHORIZED_BASELINE_STRATEGIES)

# Slug validation pattern: alphanumeric, underscores, hyphens, 2 to 64 chars
STRATEGY_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,62}[a-zA-Z0-9]$|^[a-zA-Z0-9]$")


def is_valid_strategy_id_format(strategy_id: str) -> bool:
    """Checks whether strategy_id satisfies syntactical naming conventions."""
    if not strategy_id or not isinstance(strategy_id, str):
        return False
    s = strategy_id.strip()
    return bool(STRATEGY_ID_PATTERN.match(s))


def validate_strategy_id(strategy_id: str, allow_valid_syntax: bool = False) -> bool:
    """
    Validates whether a strategy_id is registered in the strategy registry.
    If allow_valid_syntax is True, also accepts syntactically valid un-registered candidate IDs.
    """
    if not strategy_id or not isinstance(strategy_id, str):
        return False
    s = strategy_id.strip()
    if s in _REGISTRY:
        return True
    if allow_valid_syntax:
        return is_valid_strategy_id_format(s)
    return False


def is_registered(strategy_id: str) -> bool:
    """Returns True if strategy_id is registered in the registry."""
    return bool(strategy_id and isinstance(strategy_id, str) and strategy_id.strip() in _REGISTRY)


def get_strategy_metadata(strategy_id: str) -> Optional[StrategyMetadata]:
    """Returns metadata for a registered strategy, or None if unregistered."""
    if not strategy_id or not isinstance(strategy_id, str):
        return None
    return _REGISTRY.get(strategy_id.strip())


def get_strategy_tier(strategy_id: str) -> Optional[StrategyTier]:
    """Returns the StrategyTier for a registered strategy, or None if unregistered."""
    meta = get_strategy_metadata(strategy_id)
    return meta.tier if meta else None


def is_production_baseline(strategy_id: str) -> bool:
    """Returns True if strategy_id is an authorized production BASELINE strategy."""
    tier = get_strategy_tier(strategy_id)
    return tier == StrategyTier.BASELINE


def list_strategies_by_tier(tier: StrategyTier | str) -> List[str]:
    """Returns list of strategy IDs belonging to the given StrategyTier."""
    target_tier = StrategyTier.from_str(tier)
    return [s_id for s_id, meta in _REGISTRY.items() if meta.tier == target_tier]


def get_authorized_baseline_ids() -> List[str]:
    """Returns the immutable list of authorized baseline strategy IDs."""
    return list(AUTHORIZED_BASELINE_STRATEGIES.keys())


def register_strategy(
    strategy_id: str,
    tier: StrategyTier | str,
    name: str = "",
    instrument: str = "",
    timeframe: str = "1m",
    schedule: str = "",
    description: str = "",
    author: str = "LucidFlex Quantitative Team",
    allow_override_baseline: bool = False,
) -> StrategyMetadata:
    """
    Registers a strategy or research candidate into the runtime registry.

    Guards:
    - Protects production baselines from unauthorized reassignment.
    - Prevents research candidates from claiming BASELINE tier without explicit override.
    """
    if not is_valid_strategy_id_format(strategy_id):
        raise ValueError(f"Invalid strategy_id format: '{strategy_id}'. Must be 1-64 chars, alphanumeric with '_' or '-'.")

    s_id = strategy_id.strip()
    tier_enum = StrategyTier.from_str(tier)

    # Protection: Cannot demote or alter frozen production baselines unless explicitly permitted
    if s_id in AUTHORIZED_BASELINE_STRATEGIES and not allow_override_baseline:
        if tier_enum != AUTHORIZED_BASELINE_STRATEGIES[s_id].tier:
            raise ValueError(
                f"Cannot override frozen production baseline strategy '{s_id}' tier from "
                f"'{AUTHORIZED_BASELINE_STRATEGIES[s_id].tier.value}' to '{tier_enum.value}'."
            )

    # Protection: Only authorized baseline strategies can claim BASELINE tier
    if tier_enum == StrategyTier.BASELINE and s_id not in AUTHORIZED_BASELINE_STRATEGIES and not allow_override_baseline:
        raise ValueError(
            f"Strategy '{s_id}' cannot be registered with tier BASELINE. "
            f"Authorized baselines: {get_authorized_baseline_ids()}."
        )

    meta = StrategyMetadata(
        strategy_id=s_id,
        name=name or s_id.replace("_", " ").title(),
        tier=tier_enum,
        instrument=instrument,
        timeframe=timeframe,
        schedule=schedule,
        description=description,
        author=author,
    )
    _REGISTRY[s_id] = meta
    return meta


def register_candidate(
    strategy_id: str,
    name: str = "",
    instrument: str = "NQ",
    timeframe: str = "1m",
    schedule: str = "",
    description: str = "",
    author: str = "Research Candidate",
) -> StrategyMetadata:
    """Convenience helper to register an experimental research candidate."""
    return register_strategy(
        strategy_id=strategy_id,
        tier=StrategyTier.CANDIDATE,
        name=name or strategy_id.replace("_", " ").title(),
        instrument=instrument,
        timeframe=timeframe,
        schedule=schedule,
        description=description,
        author=author,
    )


def reset_registry() -> None:
    """Resets the dynamic registry back to the default authorized production baseline."""
    global _REGISTRY
    _REGISTRY = dict(AUTHORIZED_BASELINE_STRATEGIES)
