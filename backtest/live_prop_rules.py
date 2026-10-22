from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backtest.prop_firm import _normalize_profile
from backtest.prop_volatility import (
    PROP_VOLATILITY_NOT_LIVE_EDGE_NOTE,
    PropVolatilityControlConfig,
    evaluate_prop_volatility_control,
)


@dataclass(frozen=True)
class PropRuleDecision:
    reason: str
    message: str


@dataclass
class PropResearchGateCheck:
    name: str
    passed: bool
    value: Any
    threshold: str
    source: str


@dataclass
class PropResearchGateReport:
    run_dir: Path
    checks: list[PropResearchGateCheck]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def summary(self) -> str:
        lines = [f"Prop research gate: {'PASS' if self.passed else 'FAIL'} ({self.run_dir})"]
        for check in self.checks:
            status = "PASS" if check.passed else "FAIL"
            lines.append(
                f"- {status} {check.name}: value={check.value!r} "
                f"threshold={check.threshold} source={check.source}"
            )
        return "\n".join(lines)


@dataclass
class LivePropRuleConfig:
    profile: dict[str, Any]
    candidate: str
    phase: str = "eval"
    daily_loss_stop: float | None = None
    daily_profit_lock: float = 0.0
    protect_drawdown_floor_intraday: bool = True
    volatility_control: PropVolatilityControlConfig | None = None


@dataclass
class LivePropRuleGuard:
    config: LivePropRuleConfig
    rules: dict[str, Any] = field(init=False)
    status: str = "active"
    kill_reason: str = ""
    attempt_started_at: pd.Timestamp | None = None
    current_date: str = ""
    session_dates: list[str] = field(default_factory=list)
    active_trade_dates: set[str] = field(default_factory=set)
    closed_trades: int = 0
    eod_peak_equity: float = 0.0
    drawdown_floor: float = 0.0
    best_profit_day: float = 0.0
    last_daily_pnl: float = 0.0
    last_equity: float = 0.0
    last_timestamp: pd.Timestamp | None = None
    daily_entry_count: int = 0
    prop_volatility_state: str = "disabled"
    prop_volatility_reason: str = "volatility_prop_control_disabled"
    prop_volatility_adjusted_max_trades: int | None = None
    prop_volatility_block_entries: bool = False
    prop_volatility_flatten_open_position: bool = False
    prop_volatility_cooldown_bars_remaining: int = 0
    prop_volatility_daily_loss_fraction: float = 0.0
    prop_volatility_high_volatility: bool = False
    prop_volatility_shock: bool = False
    prop_volatility_max_trades_reached: bool = False
    ledger_rows: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rules = _normalize_profile(self.config.profile)
        self.config.phase = str(self.config.phase or "eval").lower()
        if self.config.phase not in {"eval", "funded"}:
            raise ValueError("prop rule phase must be 'eval' or 'funded'")
        account_size = float(self.rules["account_size"])
        max_drawdown = float(self.rules["max_drawdown"])
        self.eod_peak_equity = account_size
        self.drawdown_floor = account_size - max_drawdown if max_drawdown > 0 else float("-inf")
        self.last_equity = account_size

    @property
    def profile_name(self) -> str:
        return str(self.rules["name"])

    @property
    def daily_loss_stop(self) -> float:
        if self.config.daily_loss_stop is not None:
            return max(0.0, float(self.config.daily_loss_stop))
        return max(0.0, float(self.rules["daily_loss_limit"]))

    @property
    def daily_profit_lock(self) -> float:
        return max(0.0, float(self.config.daily_profit_lock or 0.0))

    @property
    def account_size(self) -> float:
        return float(self.rules["account_size"])

    @property
    def net_pnl(self) -> float:
        return float(self.last_equity - self.account_size)

    @property
    def day_count(self) -> int:
        return len(self.session_dates)

    @property
    def trading_day_count(self) -> int:
        return len(self.active_trade_dates)

    @property
    def target_reached(self) -> bool:
        target = float(self.rules["profit_target"])
        return target > 0 and self.net_pnl >= target

    @property
    def consistency_ok(self) -> bool:
        limit = float(self.rules["consistency_profit_limit"])
        if limit <= 0:
            return True
        if self.net_pnl <= 0:
            return True
        return self.best_profit_day <= self.net_pnl * limit

    @property
    def extra_profit_needed_for_consistency(self) -> float:
        limit = float(self.rules["consistency_profit_limit"])
        if limit <= 0 or self.net_pnl <= 0:
            return 0.0
        return max(0.0, self.best_profit_day / limit - self.net_pnl)

    @property
    def payout_available(self) -> float:
        payout_floor = self.account_size + float(self.rules["funded_buffer_target"])
        total_profit = max(0.0, self.last_equity - payout_floor)
        payout_pct = float(self.rules.get("payout_pct_of_profit", 100.0) or 100.0) / 100.0
        withdrawable = total_profit * payout_pct if payout_pct < 1.0 else total_profit
        payout_cap = float(self.rules.get("payout_cap", 0.0) or 0.0)
        if payout_cap > 0:
            withdrawable = min(withdrawable, payout_cap)
        return withdrawable
    @property
    def payout_eligible(self) -> bool:
        minimum = float(self.rules["minimum_payout"])
        return self.config.phase == "funded" and self.payout_available >= minimum and self.payout_available > 0

    def on_bar(
        self,
        *,
        timestamp: pd.Timestamp,
        equity: float,
        daily_pnl: float,
        has_open_position: bool,
        volatility_context: Any | None = None,
    ) -> None:
        ts = pd.Timestamp(timestamp)
        day = ts.strftime("%Y-%m-%d")
        if self.current_date and self.current_date != day:
            self._finalize_day(self.current_date, self.last_equity, self.last_timestamp)
            self.daily_entry_count = 0
        self.current_date = day
        if self.attempt_started_at is not None and day not in self.session_dates:
            self.session_dates.append(day)
        self.last_timestamp = ts
        self.last_equity = float(equity)
        self.last_daily_pnl = float(daily_pnl)
        self.best_profit_day = max(self.best_profit_day, float(daily_pnl))
        self._refresh_drawdown_floor()
        self._update_prop_volatility_context(volatility_context)
        self._evaluate_status(has_open_position=has_open_position)

    def entry_block_reason(self) -> PropRuleDecision | None:
        if self.status in {"fail", "timeout"}:
            reason = self.kill_reason or self.status
            return PropRuleDecision(reason, f"Prop guard blocked entry because the attempt is {self.status}: {reason}.")
        if self.status == "pass":
            return PropRuleDecision("prop_eval_complete", "Prop guard blocked entry because eval target is complete.")
        if self.status == "payout_ready":
            return PropRuleDecision("prop_payout_lockout", "Prop guard blocked entry because payout is available.")
        if self.daily_profit_lock > 0 and self.last_daily_pnl >= self.daily_profit_lock:
            return PropRuleDecision("prop_daily_profit_lock", "Prop guard blocked entry because the daily profit lock is reached.")
        if self.daily_loss_stop > 0 and self.last_daily_pnl <= -self.daily_loss_stop:
            return PropRuleDecision("prop_daily_loss_stop", "Prop guard blocked entry because the daily loss stop is reached.")
        if self._drawdown_floor_hit():
            return PropRuleDecision("prop_drawdown_floor", "Prop guard blocked entry because equity is at the drawdown floor.")
        volatility_decision = self._prop_volatility_entry_block_reason()
        if volatility_decision is not None:
            return volatility_decision
        if self.config.phase == "eval" and self.target_reached and bool(self.rules["stop_after_target_until_min_days"]):
            if not self.consistency_ok:
                return None
            return PropRuleDecision("prop_target_wait", "Prop guard blocked entry because target is reached and rules require waiting.")
        return None

    def exit_reason(self, *, has_open_position: bool) -> str | None:
        if not has_open_position:
            return None
        if self.status == "pass":
            return "prop_eval_complete"
        if self.status == "payout_ready":
            return "prop_payout_lockout"
        if self.status in {"fail", "timeout"}:
            return self.kill_reason or self.status
        if self.prop_volatility_flatten_open_position:
            return "prop_volatility_kill_switch"
        if self.daily_loss_stop > 0 and self.last_daily_pnl <= -self.daily_loss_stop:
            return "prop_daily_loss_stop"
        if self.daily_profit_lock > 0 and self.last_daily_pnl >= self.daily_profit_lock:
            return "prop_daily_profit_lock"
        if self._drawdown_floor_hit():
            return "prop_drawdown_floor"
        if self.config.phase == "eval" and self.target_reached and bool(self.rules["stop_after_target_until_min_days"]):
            return "prop_target_lock"
        return None

    def record_event(self, event: Any, *, equity: float) -> None:
        event_type = str(getattr(event, "event_type", ""))
        timestamp = pd.Timestamp(getattr(event, "timestamp", self.last_timestamp or pd.Timestamp.now(tz="UTC")))
        day = timestamp.strftime("%Y-%m-%d")
        if self.current_date and self.current_date != day:
            self._finalize_day(self.current_date, self.last_equity, self.last_timestamp)
            self.daily_entry_count = 0
        self.current_date = day
        self.last_equity = float(equity)
        self.last_timestamp = timestamp
        if event_type == "entry_filled":
            self.daily_entry_count += 1
            if self.attempt_started_at is None:
                self.attempt_started_at = timestamp
            if day not in self.session_dates:
                self.session_dates.append(day)
            self.active_trade_dates.add(day)
        elif event_type == "exit_filled":
            self.closed_trades += 1
        self._refresh_drawdown_floor()
        self._evaluate_status(has_open_position=False)
        self.ledger_rows.append(self._ledger_row(timestamp=timestamp, event_type=event_type))

    def snapshot(self) -> dict[str, Any]:
        ts = self.last_timestamp if self.last_timestamp is not None else pd.NaT
        return self._ledger_row(timestamp=ts, event_type="snapshot")

    def ledger_frame(self) -> pd.DataFrame:
        rows = list(self.ledger_rows)
        rows.append(self.snapshot())
        return pd.DataFrame(rows)

    def to_state(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "kill_reason": self.kill_reason,
            "attempt_started_at": self.attempt_started_at.isoformat() if self.attempt_started_at is not None else None,
            "current_date": self.current_date,
            "session_dates": list(self.session_dates),
            "active_trade_dates": sorted(self.active_trade_dates),
            "closed_trades": int(self.closed_trades),
            "eod_peak_equity": float(self.eod_peak_equity),
            "drawdown_floor": float(self.drawdown_floor),
            "best_profit_day": float(self.best_profit_day),
            "last_daily_pnl": float(self.last_daily_pnl),
            "last_equity": float(self.last_equity),
            "last_timestamp": self.last_timestamp.isoformat() if self.last_timestamp is not None else None,
            "daily_entry_count": int(self.daily_entry_count),
            "prop_volatility_state": self.prop_volatility_state,
            "prop_volatility_reason": self.prop_volatility_reason,
            "prop_volatility_adjusted_max_trades": self.prop_volatility_adjusted_max_trades,
            "prop_volatility_block_entries": bool(self.prop_volatility_block_entries),
            "prop_volatility_flatten_open_position": bool(self.prop_volatility_flatten_open_position),
            "prop_volatility_cooldown_bars_remaining": int(self.prop_volatility_cooldown_bars_remaining),
            "prop_volatility_daily_loss_fraction": float(self.prop_volatility_daily_loss_fraction),
            "prop_volatility_high_volatility": bool(self.prop_volatility_high_volatility),
            "prop_volatility_shock": bool(self.prop_volatility_shock),
            "prop_volatility_max_trades_reached": bool(self.prop_volatility_max_trades_reached),
            "ledger_rows": list(self.ledger_rows),
        }

    def load_state(self, state: dict[str, Any]) -> None:
        self.status = str(state.get("status", self.status))
        self.kill_reason = str(state.get("kill_reason", self.kill_reason))
        started = state.get("attempt_started_at")
        self.attempt_started_at = pd.Timestamp(started) if started else None
        self.current_date = str(state.get("current_date", self.current_date))
        self.session_dates = [str(item) for item in state.get("session_dates", self.session_dates)]
        self.active_trade_dates = {str(item) for item in state.get("active_trade_dates", [])}
        self.closed_trades = int(state.get("closed_trades", self.closed_trades))
        self.eod_peak_equity = float(state.get("eod_peak_equity", self.eod_peak_equity))
        self.drawdown_floor = float(state.get("drawdown_floor", self.drawdown_floor))
        self.best_profit_day = float(state.get("best_profit_day", self.best_profit_day))
        self.last_daily_pnl = float(state.get("last_daily_pnl", self.last_daily_pnl))
        self.last_equity = float(state.get("last_equity", self.last_equity))
        last_ts = state.get("last_timestamp")
        self.last_timestamp = pd.Timestamp(last_ts) if last_ts else None
        self.daily_entry_count = int(state.get("daily_entry_count", self.daily_entry_count))
        self.prop_volatility_state = str(state.get("prop_volatility_state", self.prop_volatility_state))
        self.prop_volatility_reason = str(state.get("prop_volatility_reason", self.prop_volatility_reason))
        max_trades = state.get("prop_volatility_adjusted_max_trades", self.prop_volatility_adjusted_max_trades)
        self.prop_volatility_adjusted_max_trades = None if max_trades is None else int(max_trades)
        self.prop_volatility_block_entries = bool(state.get("prop_volatility_block_entries", self.prop_volatility_block_entries))
        self.prop_volatility_flatten_open_position = bool(
            state.get("prop_volatility_flatten_open_position", self.prop_volatility_flatten_open_position)
        )
        self.prop_volatility_cooldown_bars_remaining = int(
            state.get("prop_volatility_cooldown_bars_remaining", self.prop_volatility_cooldown_bars_remaining)
        )
        self.prop_volatility_daily_loss_fraction = float(
            state.get("prop_volatility_daily_loss_fraction", self.prop_volatility_daily_loss_fraction)
        )
        self.prop_volatility_high_volatility = bool(
            state.get("prop_volatility_high_volatility", self.prop_volatility_high_volatility)
        )
        self.prop_volatility_shock = bool(state.get("prop_volatility_shock", self.prop_volatility_shock))
        self.prop_volatility_max_trades_reached = bool(
            state.get("prop_volatility_max_trades_reached", self.prop_volatility_max_trades_reached)
        )
        self.ledger_rows = [dict(row) for row in state.get("ledger_rows", [])]

    def _finalize_day(self, day: str, equity: float, timestamp: pd.Timestamp | None) -> None:
        if self.attempt_started_at is not None:
            self.eod_peak_equity = max(float(self.eod_peak_equity), float(equity))
            self._refresh_drawdown_floor()
            self.ledger_rows.append(
                self._ledger_row(
                    timestamp=timestamp if timestamp is not None else pd.Timestamp(day),
                    event_type="day_closed",
                )
            )

    def _refresh_drawdown_floor(self) -> None:
        max_drawdown = float(self.rules["max_drawdown"])
        account_size = self.account_size
        static_floor = account_size - max_drawdown if max_drawdown > 0 else float("-inf")
        drawdown_mode = str(self.rules["drawdown_mode"]).lower()
        trailing_lock_floor = float(self.rules.get("trailing_drawdown_lock_floor", 0.0) or 0.0)
        lock_cap = trailing_lock_floor if trailing_lock_floor > 0 else account_size
        if drawdown_mode in {"eod_trailing", "trailing", "trailing_eod", "eod_trailing_lock_at_initial", "eod_lock"} and max_drawdown > 0:
            floor = max(static_floor, float(self.eod_peak_equity) - max_drawdown)
            if bool(self.rules["trailing_drawdown_cap_at_initial"]):
                floor = min(floor, lock_cap)
            self.drawdown_floor = floor
        else:
            self.drawdown_floor = static_floor

    def _evaluate_status(self, *, has_open_position: bool) -> None:
        if self.status in {"fail", "timeout", "pass", "payout_ready"}:
            return
        if self.attempt_started_at is None:
            return
        if self.daily_loss_stop > 0 and self.last_daily_pnl <= -self.daily_loss_stop:
            self.status = "fail"
            self.kill_reason = "prop_daily_loss_stop"
            return
        if self._drawdown_floor_hit():
            self.status = "fail"
            self.kill_reason = "prop_drawdown_floor"
            return
        if self._extension_failed():
            self.status = "timeout"
            self.kill_reason = "extension_threshold_not_met"
            return
        if self.day_count > int(self.rules["max_trading_days"]):
            self.status = "timeout"
            self.kill_reason = "max_days_elapsed"
            return
        if self.config.phase == "eval":
            if self.target_reached and self.trading_day_count >= int(self.rules["min_trading_days"]) and self.consistency_ok:
                self.status = "pass"
                self.kill_reason = "profit_target"
            return
        if self.payout_eligible:
            self.status = "payout_ready"
            self.kill_reason = "minimum_payout_available"

    def _extension_failed(self) -> bool:
        initial_days = int(self.rules["initial_max_trading_days"])
        threshold = float(self.rules["extension_threshold"])
        return initial_days > 0 and threshold > 0 and self.day_count >= initial_days and self.net_pnl < threshold

    def _drawdown_floor_hit(self) -> bool:
        max_drawdown = float(self.rules["max_drawdown"])
        if max_drawdown <= 0:
            return False
        if self.config.protect_drawdown_floor_intraday:
            return self.last_equity <= self.drawdown_floor
        if str(self.rules["drawdown_check"]).lower() != "eod":
            return self.last_equity <= self.drawdown_floor
        return False

    def _ledger_row(self, *, timestamp: pd.Timestamp | Any, event_type: str) -> dict[str, Any]:
        payout_available = self.payout_available
        profit_split = float(self.rules["profit_split"])
        return {
            "timestamp": "" if pd.isna(timestamp) else pd.Timestamp(timestamp).isoformat(),
            "event_type": event_type,
            "profile": self.profile_name,
            "candidate": self.config.candidate,
            "phase": self.config.phase,
            "size_multiplier": float(self.rules["pnl_multiplier"]),
            "eval_cost": float(self.rules["eval_cost"]),
            "account_size": self.account_size,
            "profit_target": float(self.rules["profit_target"]),
            "max_drawdown": float(self.rules["max_drawdown"]),
            "daily_loss_stop": self.daily_loss_stop,
            "daily_profit_lock": self.daily_profit_lock,
            "day_count": int(self.day_count),
            "calendar_day_count": int(self.day_count),
            "trading_day_count": int(self.trading_day_count),
            "active_trade_days": int(self.trading_day_count),
            "closed_trades": int(self.closed_trades),
            "realized_pnl": self.net_pnl,
            "mtm_pnl": self.net_pnl,
            "current_equity": float(self.last_equity),
            "drawdown_floor": float(self.drawdown_floor),
            "eod_peak_equity": float(self.eod_peak_equity),
            "best_profit_day": float(self.best_profit_day),
            "consistency_limit_pct": float(self.rules["consistency_profit_limit_pct"]),
            "consistency_ok": bool(self.consistency_ok),
            "extra_profit_needed_for_consistency": float(self.extra_profit_needed_for_consistency),
            "target_reached": bool(self.target_reached),
            "payout_eligible": bool(self.payout_eligible),
            "gross_payout_available": float(payout_available),
            "net_payout_after_split": float(payout_available * profit_split),
            "status": self.status,
            "kill_reason": self.kill_reason,
            "daily_entry_count": int(self.daily_entry_count),
            "prop_volatility_state": self.prop_volatility_state,
            "prop_volatility_reason": self.prop_volatility_reason,
            "prop_volatility_adjusted_max_trades": self.prop_volatility_adjusted_max_trades,
            "prop_volatility_block_entries": bool(self.prop_volatility_block_entries),
            "prop_volatility_flatten_open_position": bool(self.prop_volatility_flatten_open_position),
            "prop_volatility_cooldown_bars_remaining": int(self.prop_volatility_cooldown_bars_remaining),
            "prop_volatility_daily_loss_fraction": float(self.prop_volatility_daily_loss_fraction),
            "prop_volatility_high_volatility": bool(self.prop_volatility_high_volatility),
            "prop_volatility_shock": bool(self.prop_volatility_shock),
            "prop_volatility_max_trades_reached": bool(self.prop_volatility_max_trades_reached),
            "prop_volatility_not_live_edge": PROP_VOLATILITY_NOT_LIVE_EDGE_NOTE,
        }

    def _update_prop_volatility_context(self, volatility_context: Any | None) -> None:
        cfg = self.config.volatility_control
        if cfg is None:
            return
        decision = evaluate_prop_volatility_control(
            volatility_context,
            config=cfg,
            current_cooldown_bars=self.prop_volatility_cooldown_bars_remaining,
            daily_pnl=self.last_daily_pnl,
            daily_loss_stop=self.daily_loss_stop,
            daily_entry_count=self.daily_entry_count,
        )
        self.prop_volatility_state = decision.state
        self.prop_volatility_reason = decision.reason
        self.prop_volatility_adjusted_max_trades = decision.max_trades_today
        self.prop_volatility_block_entries = decision.block_new_entries
        self.prop_volatility_flatten_open_position = decision.flatten_open_position
        self.prop_volatility_cooldown_bars_remaining = decision.cooldown_bars_remaining
        self.prop_volatility_daily_loss_fraction = decision.daily_loss_fraction
        self.prop_volatility_high_volatility = decision.high_volatility
        self.prop_volatility_shock = decision.volatility_shock
        self.prop_volatility_max_trades_reached = decision.max_trades_reached

    def _prop_volatility_entry_block_reason(self) -> PropRuleDecision | None:
        if self.config.volatility_control is None:
            return None
        if self.prop_volatility_state == "disabled":
            return None
        if self.prop_volatility_flatten_open_position or self.prop_volatility_state == "high_vol_kill_switch_day":
            return PropRuleDecision(
                "prop_volatility_kill_switch",
                "Prop volatility guard blocked entry because account-management risk is in kill-switch mode.",
            )
        if self.prop_volatility_state == "post_shock_cooldown" and self.prop_volatility_block_entries:
            return PropRuleDecision(
                "prop_volatility_cooldown",
                "Prop volatility guard blocked entry during post-shock cooldown.",
            )
        if self.prop_volatility_max_trades_reached:
            return PropRuleDecision(
                "prop_volatility_max_trades",
                "Prop volatility guard blocked entry because the volatility-adjusted trade limit is reached.",
            )
        if self.prop_volatility_block_entries:
            return PropRuleDecision(
                "prop_volatility_block",
                "Prop volatility guard blocked entry for account-management risk.",
            )
        return None


def profile_by_name(profiles: list[dict[str, Any]], name: str) -> dict[str, Any]:
    normalized = [_normalize_profile(profile) for profile in profiles]
    for profile in normalized:
        if str(profile["name"]) == name:
            return profile
    available = ", ".join(str(profile["name"]) for profile in normalized)
    raise ValueError(f"Unknown prop profile {name!r}. Available profiles: {available}")


def resolve_research_run_dir(path: str | Path | None = None) -> Path:
    if path:
        run_dir = Path(path)
    else:
        latest = Path("results/latest.txt")
        if not latest.exists():
            raise FileNotFoundError("results/latest.txt not found; pass --prop-research-run-dir")
        run_dir = Path("results/runs") / latest.read_text(encoding="utf-8").strip()
    if not run_dir.exists():
        raise FileNotFoundError(f"research run directory not found: {run_dir}")
    return run_dir


def validate_prop_research_gate(
    run_dir: str | Path | None = None,
    *,
    min_combined_mild_pf: float = 1.05,
) -> PropResearchGateReport:
    resolved = resolve_research_run_dir(run_dir)
    checks: list[PropResearchGateCheck] = []

    wf_summary_path = resolved / "research" / "walkforward" / "prop_firm" / "walkforward_stitched_summary.csv"
    if wf_summary_path.exists():
        wf_summary = pd.read_csv(wf_summary_path)
        row = wf_summary.iloc[0] if not wf_summary.empty else pd.Series(dtype=object)
        if "sample_scope" in wf_summary.columns:
            scope = str(row.get("sample_scope", ""))
            checks.append(PropResearchGateCheck("wf_sample_scope", scope == "walkforward_oos", scope, "walkforward_oos", str(wf_summary_path)))
        else:
            checks.append(PropResearchGateCheck("wf_sample_scope", False, "missing", "walkforward_oos", str(wf_summary_path)))
        ev = _finite_float(row.get("expected_net_payout_per_eval_attempt"))
        first_payout = _finite_float(row.get("probability_eval_to_first_payout_pct"))
        checks.append(PropResearchGateCheck("wf_prop_ev", ev > 0.0, ev, "> 0", str(wf_summary_path)))
        checks.append(PropResearchGateCheck("wf_first_payout_probability", first_payout > 0.0, first_payout, "> 0", str(wf_summary_path)))
    else:
        checks.append(PropResearchGateCheck("wf_prop_summary_exists", False, "missing", "file exists", str(wf_summary_path)))

    random_walk_path = resolved / "research" / "walkforward" / "prop_firm" / "walkforward_stitched_random_walk.csv"
    if random_walk_path.exists():
        random_walk = pd.read_csv(random_walk_path)
        row = random_walk.iloc[0] if not random_walk.empty else pd.Series(dtype=object)
        pnl_pass = _truthy(row.get("pnl_pass_5pct"))
        sharpe_pass = _truthy(row.get("sharpe_pass_5pct"))
        checks.append(PropResearchGateCheck("wf_random_walk_pnl", pnl_pass, _finite_float(row.get("pnl_p_value")), "p <= 0.05", str(random_walk_path)))
        checks.append(PropResearchGateCheck("wf_random_walk_sharpe", sharpe_pass, _finite_float(row.get("sharpe_p_value")), "p <= 0.05", str(random_walk_path)))
    else:
        checks.append(PropResearchGateCheck("wf_random_walk_exists", False, "missing", "file exists", str(random_walk_path)))

    stress_path = resolved / "simulations" / "stress_trade_stress_tests.csv"
    if stress_path.exists():
        stress = pd.read_csv(stress_path)
        row = stress.loc[stress["scenario"].eq("combined_mild")].head(1)
        if row.empty:
            checks.append(PropResearchGateCheck("combined_mild_exists", False, "missing", "scenario exists", str(stress_path)))
        else:
            item = row.iloc[0]
            pf = _finite_float(item.get("profit_factor"))
            pnl = _finite_float(item.get("total_pnl"))
            checks.append(PropResearchGateCheck("combined_mild_profit_factor", pf >= min_combined_mild_pf, pf, f">= {min_combined_mild_pf}", str(stress_path)))
            checks.append(PropResearchGateCheck("combined_mild_total_pnl", pnl > 0.0, pnl, "> 0", str(stress_path)))
    else:
        checks.append(PropResearchGateCheck("combined_mild_stress_exists", False, "missing", "file exists", str(stress_path)))

    return PropResearchGateReport(run_dir=resolved, checks=checks)


def _finite_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result if np.isfinite(result) else float("nan")


def _truthy(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "pass"}
