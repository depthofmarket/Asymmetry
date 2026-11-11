"""
Authoritative LucidFlex 25K evaluation simulator (lucidflex_eval_v1).

Causal, event-ordered account simulation for frozen trade ledgers.
This is the repository's LucidFlex 25K *evaluation* source of truth.

Not interchangeable with:
- scripts/run_m3_portfolio_ratchet_and_correlations.py (legacy M3)
- backtest.dashboard_analytics.run_evaluation (sizing-grid / dashboard-era)
- backtest.prop_firm generic profile engine

Equity model limitation
-----------------------
S1–S3 canonical bundles do not contain intraday marks. DLL and floor checks
use realized-close P&L only (P&L is recognized at recorded exit_time).
This does not reproduce true mark-to-market DLL or drawdown breaches.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from config.prop_firm_registry import LUCID_FLEX_25K

SIMULATOR_ID = "lucidflex_eval_v1"
SIMULATOR_VERSION = "1.0.0"
EQUITY_MODEL = "realized_close_only"
MICRO_MAP = {
    "NQ": "MNQ",
    "MNQ": "MNQ",
    "ES": "MES",
    "MES": "MES",
    "GC": "MGC",
    "MGC": "MGC",
    "CL": "MCL",
    "MCL": "MCL",
}

KIND_EXIT = 0
KIND_ENTRY = 1
REPO_ROOT = Path(__file__).resolve().parents[1]


def s1_split_contracts(tier: int) -> tuple[int, int]:
    """Repository live S1 MNQ/MES split of an account-wide ratchet tier.

    Tier 2 -> 1 MNQ + 1 MES
    Tier 3 -> 1 MNQ + 2 MES
    Tier 4 -> 2 MNQ + 2 MES
    Matches dashboard_analytics.leg_contracts for s1_pair legs.
    """
    t = max(int(tier), 1)
    nq = max(1, t // 2)
    es = max(1, t - nq)
    return nq, es


def contracts_for_leg(tier: int, micro: str, s1_pair: bool) -> int:
    if s1_pair:
        nq, es = s1_split_contracts(tier)
        return nq if micro == "MNQ" else es
    return max(int(tier), 0)


def consistency_required_profit(
    profit_target: float,
    largest_day_profit: float,
    consistency_pct: float,
) -> float:
    """Smallest total profit that satisfies target and largest_day / total <= pct."""
    if largest_day_profit <= 0 or consistency_pct <= 0:
        return float(profit_target)
    return max(float(profit_target), float(largest_day_profit) / float(consistency_pct))


def meets_consistency(
    total_profit: float,
    largest_day_profit: float,
    consistency_pct: float,
) -> bool:
    if total_profit <= 0:
        return False
    return (largest_day_profit / total_profit) <= (consistency_pct + 1e-12)


def meets_evaluation_pass(
    total_profit: float,
    profit_target: float,
    largest_day_profit: float,
    consistency_pct: float,
) -> bool:
    return total_profit + 1e-12 >= consistency_required_profit(
        profit_target, largest_day_profit, consistency_pct
    )


@dataclass(frozen=True)
class LucidFlexEvalConfig:
    """LucidFlex 25K evaluation config. Portfolio policies are labeled separately."""

    starting_balance: float = LUCID_FLEX_25K.ACCOUNT_SIZE
    profit_target: float = LUCID_FLEX_25K.PROFIT_TARGET
    max_loss_limit: float = LUCID_FLEX_25K.MAX_TRAILING_DRAWDOWN
    initial_floor: float = LUCID_FLEX_25K.INITIAL_FLOOR
    locked_floor: float = LUCID_FLEX_25K.LOCKED_FLOOR_VALUE
    floor_lock_peak: float = LUCID_FLEX_25K.FLOOR_LOCK_PEAK_BALANCE
    consistency_pct: float = LUCID_FLEX_25K.CONSISTENCY_RULE_PCT / 100.0
    dll_enabled: bool = True
    daily_loss_limit: float = LUCID_FLEX_25K.DAILY_SOFT_STOP
    eval_ticket_cost: float = LUCID_FLEX_25K.EVAL_TICKET_COST
    official_firm_max_micros: int = LUCID_FLEX_25K.OFFICIAL_FIRM_MAX_MICROS
    official_firm_max_minis: int = LUCID_FLEX_25K.OFFICIAL_FIRM_MAX_MINIS
    internal_risk_cap_micros: int = LUCID_FLEX_25K.INTERNAL_RISK_CAP_MICROS
    # Optional portfolio sizing policy (not a Lucid firm rule)
    ratchet_t2: float = 200.0
    ratchet_t3: float = 550.0
    enable_safe_cppi: bool = True
    cppi_buffer: float = 400.0
    enable_finish_line_shield: bool = True
    finish_line_profit: float = 1150.0
    base_contracts: int = 2

    def ratchet_contracts(self, profit: float, cushion: float) -> int:
        if self.enable_safe_cppi and cushion < self.cppi_buffer:
            return 1
        if self.enable_finish_line_shield and profit >= self.finish_line_profit:
            return 1
        if profit >= self.ratchet_t3:
            return 4
        if profit >= self.ratchet_t2:
            return 3
        return self.base_contracts


@dataclass
class EvalOutcome:
    status: str  # pass | fail | unresolved
    sessions: int
    peak_eod: float
    final_balance: float
    largest_day_profit: float
    trades_taken: int
    entries_blocked_dll: int = 0
    entries_blocked_cap: int = 0
    max_concurrent_micros: int = 0
    fail_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompiledTrade:
    trade_id: int
    session: str
    entry_ns: int
    exit_ns: int
    strat: str
    micro: str
    unit_pnl: float
    s1_pair: bool


def normalize_micro(value: Any) -> str:
    return MICRO_MAP.get(str(value).upper(), str(value).upper())


def prepare_eval_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """Require unit-micro P&L. Never use already-sized research `pnl` as the unit."""
    df = trades.copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    if "per_contract_pnl" in df.columns:
        df["unit_micro_pnl"] = df["per_contract_pnl"].astype(float)
    elif "unit_micro_pnl" in df.columns:
        df["unit_micro_pnl"] = df["unit_micro_pnl"].astype(float)
    else:
        raise KeyError("Need per_contract_pnl or unit_micro_pnl; refusing to use sized pnl")
    if "strat" not in df.columns and "strategy_id" in df.columns:
        df["strat"] = df["strategy_id"].astype(str)
    if "micro" in df.columns:
        df["micro"] = df["micro"].map(normalize_micro)
    elif "sym" in df.columns:
        df["micro"] = df["sym"].map(normalize_micro)
    else:
        df["micro"] = df["symbol"].map(normalize_micro)
    if "date" not in df.columns:
        df["date"] = df["entry_time"].dt.strftime("%Y-%m-%d")
    else:
        df["date"] = df["date"].astype(str).str.slice(0, 10)
    if "s1_pair" not in df.columns:
        s1 = df["strat"].astype(str).isin(("S1", "morning_va_breakout_s1"))
        counts = df.loc[s1].groupby("date")["micro"].transform("nunique")
        df["s1_pair"] = False
        df.loc[counts.index, "s1_pair"] = counts.to_numpy() > 1
    df["s1_pair"] = df["s1_pair"].astype(bool)
    df["strat"] = df["strat"].astype(str)
    return df.sort_values(["entry_time", "strat", "micro"]).reset_index(drop=True)


def compile_trades(trades: pd.DataFrame) -> list[CompiledTrade]:
    df = prepare_eval_trades(trades)
    out: list[CompiledTrade] = []
    for i, r in enumerate(df.itertuples(index=False)):
        out.append(
            CompiledTrade(
                trade_id=i,
                session=str(r.date),
                entry_ns=int(pd.Timestamp(r.entry_time).value),
                exit_ns=int(pd.Timestamp(r.exit_time).value),
                strat=str(r.strat),
                micro=str(r.micro),
                unit_pnl=float(r.unit_micro_pnl),
                s1_pair=bool(r.s1_pair),
            )
        )
    return out


def build_session_index(
    compiled: Sequence[CompiledTrade],
    calendar: Sequence[str],
) -> tuple[list[str], list[list[tuple[int, int, int]]]]:
    """calendar dates -> event lists of (time_ns, kind, trade_id).

    Trade dates missing from the NQ 09:30 calendar are inserted in order so
    S4 evening dates are not dropped. Empty calendar sessions remain present.
    """
    by_date: dict[str, list[CompiledTrade]] = {}
    for tr in compiled:
        by_date.setdefault(tr.session, []).append(tr)
    extra = [d for d in by_date.keys() if d not in set(calendar)]
    sessions = sorted(set(calendar) | set(extra))
    events: list[list[tuple[int, int, int]]] = []
    for d in sessions:
        ev: list[tuple[int, int, int]] = []
        for tr in by_date.get(d, []):
            ev.append((tr.entry_ns, KIND_ENTRY, tr.trade_id))
            ev.append((tr.exit_ns, KIND_EXIT, tr.trade_id))
        ev.sort(key=lambda x: (x[0], x[1], x[2]))
        events.append(ev)
    return sessions, events


def simulate_evaluation(
    compiled: Sequence[CompiledTrade],
    session_events: Sequence[Sequence[tuple[int, int, int]]],
    config: LucidFlexEvalConfig | None = None,
    max_sessions: int | None = None,
) -> EvalOutcome:
    """Run one evaluation over a sequence of session event lists."""
    cfg = config or LucidFlexEvalConfig()
    n = len(session_events) if max_sessions is None else min(len(session_events), max_sessions)
    bal = cfg.starting_balance
    peak_eod = cfg.starting_balance
    floor = cfg.initial_floor
    locked = False
    largest_day = 0.0
    trades_taken = 0
    blocked_dll = 0
    blocked_cap = 0
    max_open = 0
    open_pos: dict[int, tuple[int, float]] = {}  # trade_id -> (contracts, unit_pnl)

    def maybe_pass() -> bool:
        return meets_evaluation_pass(
            bal - cfg.starting_balance, cfg.profit_target, largest_day, cfg.consistency_pct
        )

    def maybe_fail() -> bool:
        return bal <= floor + 1e-12

    for s_i in range(n):
        day_pnl = 0.0
        dll_halt = False
        ev = session_events[s_i]
        i = 0
        while i < len(ev):
            t_ns, kind, _tid = ev[i]
            j = i + 1
            while j < len(ev) and ev[j][0] == t_ns and ev[j][1] == kind:
                j += 1
            batch = ev[i:j]
            i = j
            if kind == KIND_EXIT:
                for _, _, tid in batch:
                    held = open_pos.pop(tid, None)
                    if held is None:
                        continue
                    contracts, unit = held
                    pnl = unit * contracts
                    bal += pnl
                    day_pnl += pnl
                if cfg.dll_enabled and day_pnl <= -cfg.daily_loss_limit:
                    dll_halt = True
                if maybe_fail():
                    return EvalOutcome(
                        "fail", s_i + 1, peak_eod, bal, largest_day, trades_taken,
                        blocked_dll, blocked_cap, max_open, "eod_trailing_floor",
                    )
                if maybe_pass():
                    return EvalOutcome(
                        "pass", s_i + 1, max(peak_eod, bal), bal, largest_day,
                        trades_taken, blocked_dll, blocked_cap, max_open,
                    )
                continue

            # ENTRY batch — size from one pre-entry snapshot
            if dll_halt:
                blocked_dll += len(batch)
                continue
            profit = bal - cfg.starting_balance
            cushion = bal - floor
            tier = cfg.ratchet_contracts(profit, cushion)
            open_now = sum(c for c, _ in open_pos.values())
            desired: list[tuple[int, int]] = []
            for _, _, tid in batch:
                tr = compiled[tid]
                c = contracts_for_leg(tier, tr.micro, tr.s1_pair)
                desired.append((tid, c))
            # Allocate without using any batch member's terminal P&L
            remaining_internal = cfg.internal_risk_cap_micros - open_now
            remaining_official = cfg.official_firm_max_micros - open_now
            remaining = min(remaining_internal, remaining_official)
            for tid, c in desired:
                if c <= 0:
                    blocked_cap += 1
                    continue
                if c > remaining:
                    blocked_cap += 1
                    continue
                tr = compiled[tid]
                open_pos[tid] = (c, tr.unit_pnl)
                remaining -= c
                trades_taken += 1
            cur_open = sum(c for c, _ in open_pos.values())
            if cur_open > max_open:
                max_open = cur_open

        if day_pnl > largest_day:
            largest_day = day_pnl
        if bal > peak_eod:
            peak_eod = bal
        if not locked and peak_eod + 1e-12 >= cfg.floor_lock_peak:
            floor = cfg.locked_floor
            locked = True
        elif not locked:
            floor = max(cfg.initial_floor, peak_eod - cfg.max_loss_limit)
        if maybe_fail():
            return EvalOutcome(
                "fail", s_i + 1, peak_eod, bal, largest_day, trades_taken,
                blocked_dll, blocked_cap, max_open, "eod_trailing_floor",
            )
        if maybe_pass():
            return EvalOutcome(
                "pass", s_i + 1, peak_eod, bal, largest_day, trades_taken,
                blocked_dll, blocked_cap, max_open,
            )

    return EvalOutcome(
        "unresolved", n, peak_eod, bal, largest_day, trades_taken,
        blocked_dll, blocked_cap, max_open, "horizon_censored",
    )


def sequential_campaigns(
    compiled: Sequence[CompiledTrade],
    calendar_events: Sequence[Sequence[tuple[int, int, int]]],
    config: LucidFlexEvalConfig | None = None,
) -> dict[str, Any]:
    cfg = config or LucidFlexEvalConfig()
    campaigns: list[dict[str, Any]] = []
    idx = 0
    n = len(calendar_events)
    while idx < n:
        res = simulate_evaluation(compiled, calendar_events[idx:], cfg)
        end = idx + res.sessions
        campaigns.append({
            "start_index": idx,
            "end_index": min(end, n) - 1,
            **res.to_dict(),
        })
        if res.status == "unresolved":
            break
        idx = end
    completed = [c for c in campaigns if c["status"] in ("pass", "fail")]
    passes = [c for c in completed if c["status"] == "pass"]
    fails = [c for c in completed if c["status"] == "fail"]
    return {
        "n_campaigns": len(campaigns),
        "n_pass": len(passes),
        "n_fail": len(fails),
        "n_unresolved": sum(1 for c in campaigns if c["status"] == "unresolved"),
        "pass_rate_among_resolved": (len(passes) / len(completed)) if completed else None,
        "median_sessions_pass": float(np.median([c["sessions"] for c in passes])) if passes else None,
        "median_sessions_fail": float(np.median([c["sessions"] for c in fails])) if fails else None,
        "campaigns": campaigns,
    }


def expected_otp_cost_from_failed_attempts(
    n_pass: int,
    n_fail: int,
    ticket: float,
) -> float | None:
    """Cost per funded account using only resolved failed attempts. Unresolved are not billed."""
    if n_pass <= 0:
        return None
    return ticket * (n_pass + n_fail) / n_pass


def monte_carlo_block_bootstrap(
    compiled: Sequence[CompiledTrade],
    base_events: Sequence[Sequence[tuple[int, int, int]]],
    *,
    n_paths: int = 10_000,
    block_size: int = 5,
    horizons: Sequence[int] = (252, 260, 750),
    seed: int = 42,
    config: LucidFlexEvalConfig | None = None,
) -> dict[str, Any]:
    cfg = config or LucidFlexEvalConfig()
    rng = np.random.default_rng(seed)
    n_sess = len(base_events)
    if n_sess < block_size:
        raise ValueError("calendar shorter than block_size")
    by_h: dict[str, Any] = {}
    max_h = max(horizons)
    n_blocks = (max_h // block_size) + 2
    starts = rng.integers(0, n_sess - block_size + 1, size=(n_paths, n_blocks))

    for h in horizons:
        n_pass = n_fail = n_open = 0
        pass_sess: list[int] = []
        fail_sess: list[int] = []
        for p in range(n_paths):
            path_events: list[Sequence[tuple[int, int, int]]] = []
            for b in starts[p]:
                for off in range(block_size):
                    path_events.append(base_events[int(b) + off])
                    if len(path_events) >= h:
                        break
                if len(path_events) >= h:
                    break
            res = simulate_evaluation(compiled, path_events, cfg, max_sessions=h)
            if res.status == "pass":
                n_pass += 1
                pass_sess.append(res.sessions)
            elif res.status == "fail":
                n_fail += 1
                fail_sess.append(res.sessions)
            else:
                n_open += 1
        resolved = n_pass + n_fail
        by_h[str(h)] = {
            "horizon_sessions": h,
            "n_paths": n_paths,
            "n_pass": n_pass,
            "n_fail": n_fail,
            "n_unresolved": n_open,
            "pass_div_all_paths_pct": round(100.0 * n_pass / n_paths, 2),
            "fail_div_all_paths_pct": round(100.0 * n_fail / n_paths, 2),
            "unresolved_div_all_paths_pct": round(100.0 * n_open / n_paths, 2),
            "pass_div_resolved_pct": round(100.0 * n_pass / resolved, 2) if resolved else None,
            "fail_div_resolved_pct": round(100.0 * n_fail / resolved, 2) if resolved else None,
            "median_sessions_pass": float(np.median(pass_sess)) if pass_sess else None,
            "median_sessions_fail": float(np.median(fail_sess)) if fail_sess else None,
            "expected_otp_cost_per_funded_resolved_only": expected_otp_cost_from_failed_attempts(
                n_pass, n_fail, cfg.eval_ticket_cost
            ),
            "lifetime_pass_probability": False,
            "label": (
                f"Censored at {h} exchange sessions. Unresolved are still active; "
                "not a lifetime pass probability and not a bust rate."
            ),
        }
    return {
        "seed": seed,
        "block_size": block_size,
        "n_paths": n_paths,
        "horizons": by_h,
    }


def filter_strats(trades: pd.DataFrame, strats: Iterable[str]) -> pd.DataFrame:
    s = set(strats)
    col = "strat" if "strat" in trades.columns else "strategy_id"
    return trades[trades[col].isin(s)].copy()
