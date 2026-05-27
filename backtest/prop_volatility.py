from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


PROP_VOLATILITY_NOT_LIVE_EDGE_NOTE = "account_management_context_not_live_edge"


@dataclass(frozen=True)
class PropVolatilityControlConfig:
    """
    Account-management policy for prop attempts under volatile regimes.

    This is intentionally not an alpha filter. It decides whether the current
    volatility context should tighten or relax prop-attempt pacing.
    """

    enabled: bool = False
    high_vol_ratio: float = 1.35
    kill_switch_vol_ratio: float = 2.25
    jump_score_kill_threshold: float = 1.0
    high_vol_daily_loss_kill_fraction: float = 0.50
    opportunity_max_daily_loss_fraction: float = 0.25
    post_shock_cooldown_bars: int = 3
    normal_max_trades_per_day: int | None = None
    high_vol_opportunity_max_trades_per_day: int | None = None
    kill_switch_max_trades_per_day: int = 0
    cooldown_max_trades_per_day: int = 0
    opportunity_requires_nonnegative_daily_pnl: bool = True
    shock_triggers_kill_switch: bool = True
    flatten_on_kill_switch: bool = True
    block_entries_on_kill_switch: bool = True
    block_entries_on_cooldown: bool = True
    high_volatility_states: tuple[str, ...] = (
        "expanded_volatility_context",
        "high_markov_volatility_context",
    )
    shock_volatility_states: tuple[str, ...] = (
        "jump_volatility_context",
        "unstable_volatility_context",
    )


@dataclass(frozen=True)
class PropVolatilityDecision:
    state: str
    reason: str
    max_trades_today: int | None
    block_new_entries: bool
    flatten_open_position: bool
    cooldown_bars_remaining: int
    daily_loss_fraction: float
    high_volatility: bool
    volatility_shock: bool
    max_trades_reached: bool
    not_live_edge_note: str = PROP_VOLATILITY_NOT_LIVE_EDGE_NOTE


def evaluate_prop_volatility_control(
    context: Any,
    *,
    config: PropVolatilityControlConfig | None = None,
    current_cooldown_bars: int = 0,
    daily_pnl: float = 0.0,
    daily_loss_stop: float = 0.0,
    daily_entry_count: int = 0,
) -> PropVolatilityDecision:
    cfg = config or PropVolatilityControlConfig()
    _validate_config(cfg)
    cooldown = max(0, int(current_cooldown_bars or 0))
    loss_fraction = _daily_loss_fraction(daily_pnl, daily_loss_stop)

    if not cfg.enabled:
        return PropVolatilityDecision(
            state="disabled",
            reason="volatility_prop_control_disabled",
            max_trades_today=None,
            block_new_entries=False,
            flatten_open_position=False,
            cooldown_bars_remaining=0,
            daily_loss_fraction=loss_fraction,
            high_volatility=False,
            volatility_shock=False,
            max_trades_reached=False,
        )

    realized_ratio = _max_finite(
        _finite_float(_get(context, "realized_vol_ratio")),
        _finite_float(_get(context, "volatility_realized_vol_ratio")),
        _finite_float(_get(context, "volatility_range_ratio")),
    )
    jump_score = _finite_float(_get(context, "volatility_jump_score"))
    volatility_state = _text(_get(context, "volatility_state"))
    compression_state = _text(_get(context, "volatility_compression_state"))
    vol_of_vol_state = _text(_get(context, "volatility_vol_of_vol_state"))
    markov_state = _text(_get(context, "markov_state_label"))
    jump_event = _truthy(_get(context, "volatility_jump_event"))

    high_volatility = (
        realized_ratio >= float(cfg.high_vol_ratio)
        or volatility_state in set(cfg.high_volatility_states)
        or compression_state == "expanded_volatility"
        or markov_state == "high_vol"
    )
    volatility_shock = (
        jump_event
        or jump_score >= float(cfg.jump_score_kill_threshold)
        or volatility_state in set(cfg.shock_volatility_states)
        or vol_of_vol_state == "unstable_volatility_of_volatility"
    )
    kill_switch = (
        realized_ratio >= float(cfg.kill_switch_vol_ratio)
        or (cfg.shock_triggers_kill_switch and volatility_shock)
        or (high_volatility and loss_fraction >= float(cfg.high_vol_daily_loss_kill_fraction))
    )

    if kill_switch:
        state = "high_vol_kill_switch_day"
        reason = _kill_reason(
            realized_ratio=realized_ratio,
            volatility_shock=volatility_shock,
            loss_fraction=loss_fraction,
            cfg=cfg,
        )
        max_trades = _nonnegative_int_or_none(cfg.kill_switch_max_trades_per_day)
        block_new_entries = bool(cfg.block_entries_on_kill_switch)
        flatten_open_position = bool(cfg.flatten_on_kill_switch)
        next_cooldown = max(cooldown, int(cfg.post_shock_cooldown_bars))
    elif cooldown > 0:
        state = "post_shock_cooldown"
        reason = "post_volatility_shock_cooldown"
        max_trades = _nonnegative_int_or_none(cfg.cooldown_max_trades_per_day)
        block_new_entries = bool(cfg.block_entries_on_cooldown)
        flatten_open_position = False
        next_cooldown = max(0, cooldown - 1)
    elif _opportunity_allowed(high_volatility, loss_fraction, daily_pnl, cfg):
        state = "high_vol_opportunity_day"
        reason = "high_volatility_with_controlled_account_risk"
        max_trades = _resolve_max_trades(
            cfg.high_vol_opportunity_max_trades_per_day,
            cfg.normal_max_trades_per_day,
        )
        block_new_entries = False
        flatten_open_position = False
        next_cooldown = 0
    else:
        state = "normal"
        reason = "normal_prop_volatility_context"
        max_trades = _nonnegative_int_or_none(cfg.normal_max_trades_per_day)
        block_new_entries = False
        flatten_open_position = False
        next_cooldown = 0

    max_trades_reached = max_trades is not None and int(daily_entry_count) >= int(max_trades)
    if max_trades_reached:
        block_new_entries = True

    return PropVolatilityDecision(
        state=state,
        reason=reason,
        max_trades_today=max_trades,
        block_new_entries=block_new_entries,
        flatten_open_position=flatten_open_position,
        cooldown_bars_remaining=next_cooldown,
        daily_loss_fraction=loss_fraction,
        high_volatility=high_volatility,
        volatility_shock=volatility_shock,
        max_trades_reached=max_trades_reached,
    )


def _opportunity_allowed(
    high_volatility: bool,
    loss_fraction: float,
    daily_pnl: float,
    cfg: PropVolatilityControlConfig,
) -> bool:
    if not high_volatility:
        return False
    if bool(cfg.opportunity_requires_nonnegative_daily_pnl):
        pnl = _finite_float(daily_pnl)
        if not np.isfinite(pnl) or pnl < 0.0:
            return False
    return loss_fraction <= float(cfg.opportunity_max_daily_loss_fraction)


def _kill_reason(
    *,
    realized_ratio: float,
    volatility_shock: bool,
    loss_fraction: float,
    cfg: PropVolatilityControlConfig,
) -> str:
    if realized_ratio >= float(cfg.kill_switch_vol_ratio):
        return "realized_volatility_kill_threshold"
    if volatility_shock:
        return "volatility_shock"
    if loss_fraction >= float(cfg.high_vol_daily_loss_kill_fraction):
        return "high_volatility_daily_loss_acceleration"
    return "high_volatility_kill_switch"


def _resolve_max_trades(primary: int | None, fallback: int | None) -> int | None:
    resolved = _nonnegative_int_or_none(primary)
    if resolved is not None:
        return resolved
    return _nonnegative_int_or_none(fallback)


def _nonnegative_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, out)


def _daily_loss_fraction(daily_pnl: float, daily_loss_stop: float) -> float:
    stop = _finite_float(daily_loss_stop)
    if stop <= 0.0:
        return 0.0
    return max(0.0, -_finite_float(daily_pnl)) / stop


def _max_finite(*values: float) -> float:
    finite = [float(value) for value in values if np.isfinite(value)]
    return max(finite) if finite else float("nan")


def _finite_float(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out if np.isfinite(out) else float("nan")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = _text(value).lower()
    return text in {"1", "true", "yes", "y", "pass"}


def _get(context: Any, key: str) -> Any:
    if context is None:
        return None
    getter = getattr(context, "get", None)
    if callable(getter):
        return getter(key, None)
    return getattr(context, key, None)


def _validate_config(cfg: PropVolatilityControlConfig) -> None:
    if cfg.high_vol_ratio <= 0.0:
        raise ValueError("high_vol_ratio must be positive")
    if cfg.kill_switch_vol_ratio < cfg.high_vol_ratio:
        raise ValueError("kill_switch_vol_ratio must be >= high_vol_ratio")
    if cfg.jump_score_kill_threshold <= 0.0:
        raise ValueError("jump_score_kill_threshold must be positive")
    if not 0.0 <= cfg.high_vol_daily_loss_kill_fraction <= 1.0:
        raise ValueError("high_vol_daily_loss_kill_fraction must be between 0 and 1")
    if not 0.0 <= cfg.opportunity_max_daily_loss_fraction <= 1.0:
        raise ValueError("opportunity_max_daily_loss_fraction must be between 0 and 1")
    if cfg.post_shock_cooldown_bars < 0:
        raise ValueError("post_shock_cooldown_bars must be non-negative")
