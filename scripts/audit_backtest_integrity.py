#!/usr/bin/env python3
"""
Independent integrity audit of the 3-strategy ensemble and the prop-eval Monte Carlo.

Rebuilds Strategy 1 (MNQ/MES 09:45 VA breakout), Strategy 2 (MGC 10:15 gold fix) and
Strategy 3 (MNQ 08:35 macro momentum) from raw 1-minute bars with strict point-in-time
rules, then compares against the research datasets used by the prop dashboard.

Checks:
  1. Bar timestamp convention (start-stamped vs end-stamped).
  2. Unadjusted continuous-contract roll gaps contaminating "prior session" levels.
  3. Fill realism: signal-close vs next-open entry, touch vs trade-through targets,
     stop slippage, same-bar stop/target ambiguity.
  4. Post-hoc filters (GARCH "Candidate A", Markov sizing) and their in-sample contribution.
  5. Prop simulation: bootstrap vs chronological replay, live 2-micro sizing,
     EOD vs intraday trailing drawdown.

Outputs: results/audit/*.csv and a printed summary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.poc_rejection_signal import _compute_prior_session_profiles  # noqa: E402

OUT = ROOT / "results" / "audit"
OUT.mkdir(parents=True, exist_ok=True)

SPEC = {
    "NQ": dict(micro="MNQ", pv=2.0, tick=0.25, comm=1.40),
    "ES": dict(micro="MES", pv=5.0, tick=0.25, comm=1.40),
    "GC": dict(micro="MGC", pv=10.0, tick=0.10, comm=1.50),
}
START = "2021-01-01"

STARTING_CAPITAL = 25_000.0
PROFIT_TARGET = 1_250.0
MAX_DD = 1_000.0
FLOOR_LOCK = 25_100.0
PEAK_FOR_LOCK = 26_100.0


# ───────────────────────────────────────────────────────────────────────────────
# Data
# ───────────────────────────────────────────────────────────────────────────────
def load(name: str) -> pd.DataFrame:
    df = pd.read_parquet(ROOT / f"data/raw/{name}.parquet", columns=["time", "open", "high", "low", "close", "volume"])
    df = df[df["time"] >= "2020-09-01"].sort_values("time").reset_index(drop=True)
    df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["time"].dt.strftime("%H:%M")
    return df


def detect_roll_sessions(df: pd.DataFrame, pct_threshold: float) -> set[str]:
    """Return RTH dates whose prior-session levels come from the previous contract.

    A roll in unadjusted continuous data appears as a large jump across the weekday
    17:00-18:00 maintenance break. The first RTH session after that jump is contaminated.
    """
    gap_s = df["time"].diff().dt.total_seconds()
    is_break = (gap_s >= 2700) & (gap_s <= 4 * 3600)  # weekday maintenance break only
    jumps = (df["open"] - df["close"].shift(1)).abs() / df["close"].shift(1)
    roll_idx = df.index[is_break & (jumps > pct_threshold)]
    # The 18:00 bar belongs to the next trading day's session
    sessions = set()
    dates_sorted = np.array(sorted(df["date"].unique()))
    for i in roll_idx:
        d = df.at[i, "date"]
        pos = np.searchsorted(dates_sorted, d, side="right")
        if pos < len(dates_sorted):
            sessions.add(str(dates_sorted[pos]))
    return sessions


def prior_profile_maps(df: pd.DataFrame, start: str, end: str, bin_size: float):
    rth = df[(df["hhmm"] >= start) & (df["hhmm"] <= end)][["time", "open", "high", "low", "close", "volume"]]
    prof = _compute_prior_session_profiles(rth, bin_size=bin_size, value_area_pct=0.70)
    prof["date"] = prof["session"].astype(str)
    prof = prof.set_index("date")
    rth_dates = rth["time"].dt.strftime("%Y-%m-%d")
    prior_close = rth.groupby(rth_dates)["close"].last().shift(1)
    return prof, prior_close


# ───────────────────────────────────────────────────────────────────────────────
# Execution model
# ───────────────────────────────────────────────────────────────────────────────
def simulate(
    path: pd.DataFrame,
    *,
    d: int,
    signal_price: float,
    stop_pts: float,
    rr: float,
    tick: float,
    mode: str,
) -> dict | None:
    """Simulate one bracket trade over `path` (bars strictly after the signal, ending
    with the last bar before the flat time).

    mode="baseline":     fill at signal close, target fills on touch, stop/time exit at price
                          minus 1 tick, stop checked first on ambiguous bars.
    mode="conservative": fill at next bar open + 1 tick, bracket placed off the fill,
                          target requires a 1-tick trade-through, stops slip 1 tick and
                          gap-through stops fill at the bar open.
    """
    if path.empty:
        return None
    o = path["open"].to_numpy(float)
    h = path["high"].to_numpy(float)
    lo = path["low"].to_numpy(float)
    c = path["close"].to_numpy(float)

    if mode == "baseline":
        entry = signal_price
        through = 0.0
    else:
        entry = o[0] + d * tick
        through = tick
    stop = entry - d * stop_pts
    target = entry + d * stop_pts * rr

    exit_p, reason, ambiguous = c[-1] - d * tick, "time", False
    mae = 0.0
    for k in range(len(o)):
        adverse = (lo[k] - entry) if d == 1 else (entry - h[k])
        mae = min(mae, adverse)
        stop_hit = lo[k] <= stop if d == 1 else h[k] >= stop
        tgt_hit = (h[k] >= target + through) if d == 1 else (lo[k] <= target - through)
        if stop_hit and tgt_hit:
            ambiguous = True
        if stop_hit:
            gap_through = (o[k] < stop) if d == 1 else (o[k] > stop)
            if mode == "conservative" and gap_through:
                exit_p = o[k] - d * tick
            else:
                exit_p = stop - d * tick
            reason = "stop"
            mae = min(mae, -stop_pts - tick)
            break
        if tgt_hit:
            exit_p = target
            reason = "target"
            break
    pts = (exit_p - entry) * d
    return dict(entry=entry, exit=exit_p, pts=pts, R=pts / stop_pts, mae_pts=mae, reason=reason, ambiguous=ambiguous)


def bars_between(g: pd.DataFrame, start_hhmm: str, flat_hhmm: str) -> pd.DataFrame:
    """Bars starting at/after start_hhmm and strictly before flat_hhmm (flat at flat_hhmm:00)."""
    return g[(g["hhmm"] >= start_hhmm) & (g["hhmm"] < flat_hhmm)]


# ───────────────────────────────────────────────────────────────────────────────
# Strategies
# ───────────────────────────────────────────────────────────────────────────────
def strategy1(df: pd.DataFrame, sym: str, rolls: set[str]) -> list[dict]:
    bin_size = 1.0 if sym == "NQ" else 0.5
    min_stop, max_stop = (15.0, 60.0) if sym == "NQ" else (5.0, 35.0)
    prof, prior_close = prior_profile_maps(df, "09:30", "16:00", bin_size)
    out = []
    for d_str, g in df[df["date"] >= START].groupby("date", sort=True):
        m15 = g[(g["hhmm"] >= "09:30") & (g["hhmm"] <= "09:44")]
        if len(m15) < 10 or d_str not in prof.index:
            continue
        o, c = float(m15["open"].iloc[0]), float(m15["close"].iloc[-1])
        h, lo = float(m15["high"].max()), float(m15["low"].min())
        rng = h - lo
        if rng <= 0:
            continue
        ret, loc = (c - o) / o, (c - lo) / rng
        vah, val = prof.at[d_str, "prior_vah"], prof.at[d_str, "prior_val"]
        pc = prior_close.get(d_str, np.nan)
        if not (np.isfinite(vah) and np.isfinite(val) and np.isfinite(pc)):
            continue
        is_long = ret >= 0.0010 and loc >= 0.65 and c > vah and o > pc
        is_short = ret <= -0.0010 and loc <= 0.35 and c < val and o < pc
        if not (is_long or is_short):
            continue
        d = 1 if is_long else -1
        stop_pts = float(np.clip(rng, min_stop, max_stop))
        path = bars_between(g, "09:45", "10:15")
        row = dict(date=d_str, sym=sym, strategy="S1", direction="long" if d == 1 else "short",
                   stop_pts=stop_pts, roll_session=d_str in rolls, or15_dir=int(np.sign(c - o)))
        for mode in ("baseline", "conservative"):
            r = simulate(path, d=d, signal_price=c, stop_pts=stop_pts, rr=1.5, tick=SPEC[sym]["tick"], mode=mode)
            if r is None:
                break
            row.update({f"{k}_{mode}": v for k, v in r.items()})
        else:
            out.append(row)
    return out


def strategy2(df: pd.DataFrame, rolls: set[str]) -> list[dict]:
    prof, _ = prior_profile_maps(df, "08:20", "13:30", 0.50)
    out = []
    for d_str, g in df[df["date"] >= START].groupby("date", sort=True):
        fix = g[(g["hhmm"] >= "10:00") & (g["hhmm"] <= "10:14")]
        ib = g[(g["hhmm"] >= "08:20") & (g["hhmm"] <= "09:19")]
        lon = g[(g["hhmm"] >= "03:00") & (g["hhmm"] <= "08:19")]
        if len(fix) < 10 or ib.empty:
            continue
        fo, fc = float(fix["open"].iloc[0]), float(fix["close"].iloc[-1])
        fh, fl = float(fix["high"].max()), float(fix["low"].min())
        rng = fh - fl
        if rng <= 0 or fo <= 0:
            continue
        ret, loc = (fc - fo) / fo, (fc - fl) / rng
        ib_hi = float(ib["high"].max())
        lon_hi = float(lon["high"].max()) if not lon.empty else ib_hi
        vah = prof.at[d_str, "prior_vah"] if d_str in prof.index else np.nan
        va_ok = True if not np.isfinite(vah) else fc > vah
        if not (ret >= 0.001125 and loc >= 0.70 and fc > ib_hi and fc > lon_hi and va_ok):
            continue
        stop_pts = float(np.clip(rng, 3.0, 18.0))
        path = bars_between(g, "10:15", "11:00")
        row = dict(date=d_str, sym="GC", strategy="S2", direction="long", stop_pts=stop_pts, roll_session=d_str in rolls)
        for mode in ("baseline", "conservative"):
            r = simulate(path, d=1, signal_price=fc, stop_pts=stop_pts, rr=1.5, tick=SPEC["GC"]["tick"], mode=mode)
            if r is None:
                break
            row.update({f"{k}_{mode}": v for k, v in r.items()})
        else:
            out.append(row)
    return out


def strategy3(df: pd.DataFrame, rolls: set[str]) -> list[dict]:
    out = []
    for d_str, g in df[df["date"] >= START].groupby("date", sort=True):
        ovn = g[(g["hhmm"] >= "00:00") & (g["hhmm"] <= "08:29")]
        spike = g[(g["hhmm"] >= "08:30") & (g["hhmm"] <= "08:34")]
        if len(ovn) < 180 or len(spike) < 4:
            continue
        oh, ol = float(ovn["high"].max()), float(ovn["low"].min())
        if oh <= ol:
            continue
        if float(spike["volume"].sum()) < float(ovn["volume"].tail(30).mean()) * 5.0 * 2.5:
            continue
        sc, sh, sl = float(spike["close"].iloc[-1]), float(spike["high"].max()), float(spike["low"].min())
        srng = sh - sl
        loc = (sc - sl) / srng if srng > 0 else 0.5
        d = 1 if (sc > oh and loc >= 0.65) else (-1 if (sc < ol and loc <= 0.35) else 0)
        if d == 0:
            continue
        stop_pts = float(np.clip(srng * 0.5, 20.0, 50.0))
        path = bars_between(g, "08:35", "09:25")
        if path.empty or path["hhmm"].iloc[0] != "08:35":
            continue
        row = dict(date=d_str, sym="NQ", strategy="S3", direction="long" if d == 1 else "short",
                   stop_pts=stop_pts, roll_session=d_str in rolls)
        # Research dataset fills S3 at the 08:35 open, so "baseline" = next open, no slip
        for mode in ("baseline", "conservative"):
            r = simulate(path, d=d, signal_price=float(path["open"].iloc[0]), stop_pts=stop_pts, rr=1.5,
                         tick=SPEC["NQ"]["tick"], mode=mode)
            if r is None:
                break
            row.update({f"{k}_{mode}": v for k, v in r.items()})
        else:
            out.append(row)
    return out


# ───────────────────────────────────────────────────────────────────────────────
# Metrics
# ───────────────────────────────────────────────────────────────────────────────
def pf(x: pd.Series) -> float:
    pos, neg = x[x > 0].sum(), -x[x <= 0].sum()
    return float(pos / neg) if neg > 0 else np.nan


def summarize(df: pd.DataFrame, col: str, label: str) -> dict:
    return dict(label=label, n=len(df), wr=float((df[col] > 0).mean() * 100) if len(df) else np.nan,
                pf=pf(df[col]) if len(df) else np.nan, net=float(df[col].sum()), avg=float(df[col].mean()) if len(df) else np.nan)


# ───────────────────────────────────────────────────────────────────────────────
# Prop simulation
# ───────────────────────────────────────────────────────────────────────────────
def run_eval(daily_pnl: np.ndarray, daily_low: np.ndarray, intraday: bool) -> tuple[str, int]:
    bal = peak = STARTING_CAPITAL
    floor = STARTING_CAPITAL - MAX_DD
    for i, (p, low) in enumerate(zip(daily_pnl, daily_low)):
        if intraday and bal + low <= floor:
            return "fail", i + 1
        bal += p
        if bal <= floor:
            return "fail", i + 1
        if bal - STARTING_CAPITAL >= PROFIT_TARGET:
            return "pass", i + 1
        if bal > peak:
            peak = bal
            floor = max(floor, FLOOR_LOCK) if peak >= PEAK_FOR_LOCK else max(floor, peak - MAX_DD)
    return "open", len(daily_pnl)


def chronological_replay(daily: pd.DataFrame, intraday: bool) -> dict:
    """Start an evaluation on every trading day and replay real history forward."""
    p, lo = daily["pnl"].to_numpy(float), daily["low"].to_numpy(float)
    res = [run_eval(p[s:], lo[s:], intraday) for s in range(len(p))]
    done = [r for r in res if r[0] != "open"]
    passes = [r for r in done if r[0] == "pass"]
    return dict(starts=len(res), resolved=len(done), pass_rate=100 * len(passes) / max(len(done), 1),
                median_days_pass=float(np.median([r[1] for r in passes])) if passes else np.nan)


def block_bootstrap(daily: pd.DataFrame, intraday: bool, n_sims=10_000, block=5, seed=42) -> dict:
    rng = np.random.default_rng(seed)
    p, lo = daily["pnl"].to_numpy(float), daily["low"].to_numpy(float)
    n = len(p)
    out = []
    for _ in range(n_sims):
        idx = np.concatenate([np.arange(s, s + block) for s in rng.integers(0, n - block + 1, size=400 // block)])
        out.append(run_eval(p[idx], lo[idx], intraday))
    passes = [r for r in out if r[0] == "pass"]
    return dict(pass_rate=100 * len(passes) / n_sims, median_days_pass=float(np.median([r[1] for r in passes])) if passes else np.nan)


def research_method(daily_trading_only: pd.DataFrame, n_sims=10_000, block=5, seed=42) -> float:
    """Exact replica of generate_rational_edge_prop_dashboard.run_comprehensive_prop_simulation (eval part)."""
    rng = np.random.default_rng(seed)
    p = daily_trading_only["net_pnl"].to_numpy(float)
    n = len(p)
    passes = 0
    for _ in range(n_sims):
        bal = peak = STARTING_CAPITAL
        floor = STARTING_CAPITAL - MAX_DD
        done = False
        while not done:
            s = rng.integers(0, n - block + 1)
            for dp in p[s:s + block]:
                bal += max(dp, -600.0)
                if bal > peak:
                    peak = bal
                    floor = max(floor, FLOOR_LOCK) if peak >= PEAK_FOR_LOCK else max(floor, peak - MAX_DD)
                if bal <= floor:
                    done = True
                    break
                if bal - STARTING_CAPITAL >= PROFIT_TARGET:
                    passes += 1
                    done = True
                    break
    return 100 * passes / n_sims


def build_daily(trades: pd.DataFrame, all_dates: list[str], pnl_col: str, mae_col: str | None) -> pd.DataFrame:
    """Aggregate trades into a daily series over ALL trading days (zero-trade days included).
    `low` = worst intraday equity vs prior close, assuming windows run sequentially."""
    rows = {d: [0.0, 0.0] for d in all_dates}
    for d, g in trades.sort_values(["date", "order"]).groupby("date"):
        if d not in rows:
            continue
        realized, low = 0.0, 0.0
        for _, t in g.groupby("order"):
            mae = t[mae_col].sum() if mae_col else t[pnl_col].clip(upper=0).sum()
            low = min(low, realized + mae)
            realized += t[pnl_col].sum()
            low = min(low, realized)
        rows[d] = [realized, low]
    return pd.DataFrame([(d, v[0], v[1]) for d, v in rows.items()], columns=["date", "pnl", "low"])


# ───────────────────────────────────────────────────────────────────────────────
def main() -> int:
    print("Loading raw 1m bars...")
    nq, es, gc = load("nq_1m_2017_2026_cqg_et"), load("es_1m_2020_2026_cqg_et"), load("gc_1m_2020_2026_et")

    # 1. Timestamp convention
    v = nq[nq["time"].dt.year == 2025].groupby("hhmm")["volume"].median()
    print(f"\n[1] Timestamp convention: median vol 09:29={v['09:29']:.0f} 09:30={v['09:30']:.0f} | "
          f"17:00 bar present={'17:00' in v.index} 18:00 present={'18:00' in v.index} -> bars are START-stamped")

    # 2. Roll contamination
    rolls = {"NQ": detect_roll_sessions(nq, 0.006), "ES": detect_roll_sessions(es, 0.004), "GC": detect_roll_sessions(gc, 0.004)}
    for k, s in rolls.items():
        s2021 = sorted(x for x in s if x >= START)
        print(f"[2] {k}: {len(s2021)} roll-contaminated sessions since 2021 (e.g. {s2021[:3]})")

    print("\nRebuilding strategies from raw bars...")
    t1 = pd.DataFrame(strategy1(nq, "NQ", rolls["NQ"]) + strategy1(es, "ES", rolls["ES"]))
    t2 = pd.DataFrame(strategy2(gc, rolls["GC"]))
    t3 = pd.DataFrame(strategy3(nq, rolls["NQ"]))
    rebuilt = pd.concat([t1, t2, t3], ignore_index=True)
    rebuilt.to_csv(OUT / "rebuilt_trades.csv", index=False)

    # Compare with research datasets
    ds = pd.read_parquet(ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet")
    ds_base = pd.read_parquet(ROOT / "data/processed/unified_three_strategy_portfolio_trades_2021_2026.parquet")
    ds["S"] = np.where(ds["strategy"].str.contains("Strategy 1"), "S1", np.where(ds["strategy"].str.contains("Strategy 2"), "S2", "S3"))
    ds_base["S"] = np.where(ds_base["strategy"].str.contains("Strategy 1"), "S1", np.where(ds_base["strategy"].str.contains("Strategy 2"), "S2", "S3"))

    print("\n[3] Trade-set reconciliation (research dataset vs independent rebuild)")
    for s in ("S1", "S2", "S3"):
        a = set(map(tuple, ds_base[ds_base["S"] == s][["date_str", "sym", "direction"]].values))
        b = set(map(tuple, rebuilt[rebuilt["strategy"] == s][["date", "sym", "direction"]].values))
        print(f"    {s}: dataset={len(a):3d} rebuilt={len(b):3d} matched={len(a & b):3d} "
              f"only-in-dataset={len(a - b):3d} only-in-rebuild={len(b - a):3d}")

    # Per-strategy R metrics under both fill models
    print("\n[4] Edge per strategy in R-multiples (fill model sensitivity)")
    rows = []
    for s, g in rebuilt.groupby("strategy"):
        for mode in ("baseline", "conservative"):
            for per, sub in (("2021-24", g[g["date"] < "2025-01-01"]), ("2025-26", g[g["date"] >= "2025-01-01"]), ("ALL", g)):
                m = summarize(sub, f"R_{mode}", f"{s} {mode} {per}")
                rows.append(m)
        amb = g["ambiguous_baseline"].mean() * 100
        print(f"    {s}: same-bar stop+target ambiguity on {amb:.1f}% of trades")
    edge = pd.DataFrame(rows)
    edge.to_csv(OUT / "edge_by_strategy.csv", index=False)
    print(edge.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    # Roll-day attribution
    print("\n[5] Roll-contaminated sessions")
    for s, g in rebuilt.groupby("strategy"):
        r = g[g["roll_session"]]
        if len(r):
            print(f"    {s}: {len(r)} trades on roll sessions | dirs={r['direction'].value_counts().to_dict()} | "
                  f"sum R baseline={r['R_baseline'].sum():+.2f}")

    # Post-hoc filters
    print("\n[6] Post-hoc filters evaluated on the full sample (incl. 2025-26)")
    key = ["date_str", "sym", "direction"]
    garch = pd.read_parquet(ROOT / "data/processed/unified_three_strategy_garch_portfolio_trades_2021_2026.parquet")
    dropped = ds_base.merge(garch[key], on=key, how="left", indicator=True)
    dropped = dropped[dropped["_merge"] == "left_only"]
    print(f"    GARCH 'Candidate A' removed {len(dropped)} trades, net ${dropped['net_dollars_micro'].sum():+,.2f}: "
          f"{dropped[['date_str', 'sym', 'net_dollars_micro']].values.tolist()}")
    markov_uplift = (ds["pnl"] - ds["net_dollars_micro"]).sum()
    print(f"    Markov sizing uplift: ${markov_uplift:+,.2f} "
          f"(low_vol 1.25x on {int((ds['markov_sizing_mult'] == 1.25).sum())} trades, "
          f"0.5x S3 high_vol on {int((ds['markov_sizing_mult'] == 0.5).sum())} trades)")

    # S1 concurrent exposure
    s1 = ds[ds["S"] == "S1"]
    both = s1.groupby("date_str")["sym"].nunique()
    print(f"    S1 fires on BOTH MNQ and MES on {(both > 1).sum()} of {len(both)} S1 days; "
          f"dataset contracts mean MNQ={s1[s1.sym == 'NQ'].contracts.mean():.2f}, MES={s1[s1.sym == 'ES'].contracts.mean():.2f} "
          f"(live engine trades 2 micros total, split 1+1)")

    # 7. Prop simulation
    print("\n[7] Prop evaluation pass rate under different methods")
    all_dates = sorted(set(nq[(nq["date"] >= START) & (nq["hhmm"] == "09:30")]["date"]))

    daily_ds = ds.groupby("date_str").agg(net_pnl=("pnl", "sum")).reset_index()
    rep = research_method(daily_ds)
    print(f"    a) Replica of dashboard method on dashboard dataset:              {rep:5.1f}%")

    ds_tr = ds.rename(columns={"date_str": "date"}).copy()
    ds_tr["order"] = ds_tr["S"].map({"S3": 0, "S1": 1, "S2": 2})
    d_ds = build_daily(ds_tr, all_dates, "pnl", None)
    cr = chronological_replay(d_ds, intraday=False)
    print(f"    b) Same dataset, chronological replay from every start date:     {cr['pass_rate']:5.1f}% "
          f"(median {cr['median_days_pass']:.0f} days, {cr['resolved']} resolved starts)")

    # Live sizing: 2 micros per window; S1 split 1+1 when both indices fire
    def live_dollars(df: pd.DataFrame, mode: str) -> pd.DataFrame:
        df = df.copy()
        n_s1 = df[df["strategy"] == "S1"].groupby("date")["sym"].transform("count")
        df["contracts"] = 2
        df.loc[n_s1.index, "contracts"] = np.where(n_s1 > 1, 1, 2)
        pv = df["sym"].map(lambda s: SPEC[s]["pv"])
        comm = df["sym"].map(lambda s: SPEC[s]["comm"])
        df["pnl"] = df[f"pts_{mode}"] * pv * df["contracts"] - comm * df["contracts"]
        df["mae"] = df[f"mae_pts_{mode}"] * pv * df["contracts"] - comm * df["contracts"]
        df["order"] = df["strategy"].map({"S3": 0, "S1": 1, "S2": 2})
        return df

    results = []
    for mode in ("baseline", "conservative"):
        for excl_roll in (False, True):
            tr = live_dollars(rebuilt, mode)
            if excl_roll:
                tr = tr[~tr["roll_session"]]
            for intraday in (False, True):
                d = build_daily(tr, all_dates, "pnl", "mae")
                c = chronological_replay(d, intraday)
                b = block_bootstrap(d, intraday)
                results.append(dict(fills=mode, exclude_roll_days=excl_roll, dd_check="intraday" if intraday else "EOD",
                                    trades=len(tr), net=round(tr["pnl"].sum(), 2), pf=round(pf(tr["pnl"]), 3),
                                    chrono_pass=round(c["pass_rate"], 1), chrono_med_days=c["median_days_pass"],
                                    boot_pass=round(b["pass_rate"], 1), boot_med_days=b["median_days_pass"]))
    res = pd.DataFrame(results)
    res.to_csv(OUT / "prop_pass_rates.csv", index=False)
    print("    c) Independent rebuild with LIVE sizing (2 micros/window):")
    print(res.to_string(index=False))

    # Yearly view of conservative rebuild with live sizing
    tr = live_dollars(rebuilt, "conservative")
    yr = tr.groupby([tr["date"].str[:4], "strategy"])["pnl"].agg(["count", "sum", pf]).round(2)
    yr.to_csv(OUT / "yearly_conservative_live_sizing.csv")
    print("\n[8] Conservative fills, live sizing, by year & strategy:")
    print(yr.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
