#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys
import threading
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.markov_regime import GaussianMarkovRegimeModel


@dataclass(frozen=True)
class RuntimeBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def volatility(self) -> float:
        if self.close <= 0:
            return 0.0
        return abs(self.high - self.low) / abs(self.close)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Interactive Brokers Markov regime monitor. This streams 5-second "
            "bars and classifies low/mid/high volatility regimes; it does not "
            "submit orders."
        )
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497, help="7497 is the usual TWS paper port.")
    parser.add_argument("--client-id", type=int, default=17)
    parser.add_argument("--symbol", default="NQ")
    parser.add_argument("--sec-type", default="FUT", choices=["STK", "FUT", "ETF", "CASH", "IND"])
    parser.add_argument("--exchange", default="CME")
    parser.add_argument("--primary-exchange", default="")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--last-trade-date-or-contract-month", default="", help="Required for many futures, e.g. 202606.")
    parser.add_argument("--use-rth", type=int, default=0)
    parser.add_argument("--calibration-bars", type=int, default=60)
    parser.add_argument("--min-calibration-bars", type=int, default=30)
    parser.add_argument("--recalibrate-every-bars", type=int, default=12)
    parser.add_argument("--smoothing", type=float, default=0.1)
    return parser.parse_args()


def _make_contract(Contract, args: argparse.Namespace):
    contract = Contract()
    contract.symbol = args.symbol.upper()
    contract.secType = args.sec_type
    contract.exchange = args.exchange
    contract.currency = args.currency
    if args.primary_exchange:
        contract.primaryExchange = args.primary_exchange
    if args.last_trade_date_or_contract_month:
        contract.lastTradeDateOrContractMonth = args.last_trade_date_or_contract_month
    return contract


def _build_app_class(EWrapper, EClient):
    class IBMarkovRegimeApp(EWrapper, EClient):
        def __init__(self, args: argparse.Namespace):
            EClient.__init__(self, self)
            self.args = args
            self.connected_event = threading.Event()
            self.historical_done = threading.Event()
            self.historical_bars: list[RuntimeBar] = []
            self.closed_bars: deque[RuntimeBar] = deque(maxlen=max(args.calibration_bars * 4, 200))
            self.model = GaussianMarkovRegimeModel(
                n_states=3,
                smoothing=args.smoothing,
                initial_prob_mode="uniform",
            )
            self.bars_since_fit = 0

        def nextValidId(self, orderId):  # noqa: N802 - IB callback name
            self.connected_event.set()
            print(f"Connected to IBKR. nextValidId={orderId}", flush=True)

        def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):  # noqa: N802
            if errorCode in {2104, 2106, 2158, 2176}:
                return
            if errorCode == 10167:
                print("IBKR note: using delayed market data.", flush=True)
                return
            print(f"IBKR error reqId={reqId} code={errorCode}: {errorString}", flush=True)

        def historicalData(self, reqId, bar):  # noqa: N802
            timestamp = _parse_ib_time(bar.date)
            self.historical_bars.append(
                RuntimeBar(
                    timestamp=timestamp,
                    open=float(bar.open),
                    high=float(bar.high),
                    low=float(bar.low),
                    close=float(bar.close),
                    volume=float(getattr(bar, "volume", 0.0) or 0.0),
                )
            )

        def historicalDataEnd(self, reqId, start, end):  # noqa: N802
            self.historical_done.set()
            self._recalibrate(self.historical_bars)
            self.closed_bars.extend(self.historical_bars)
            print(f"Historical calibration loaded {len(self.historical_bars)} bars.", flush=True)

        def realtimeBar(self, reqId, time_, open_, high, low, close, volume, wap, count):  # noqa: N802
            bar = RuntimeBar(
                timestamp=datetime.fromtimestamp(int(time_)),
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume or 0.0),
            )
            self.closed_bars.append(bar)
            self.bars_since_fit += 1

            if self.bars_since_fit >= max(1, self.args.recalibrate_every_bars):
                prior_bars = list(self.closed_bars)[:-1]
                self._recalibrate(prior_bars[-self.args.calibration_bars :])

            state, probabilities = self.model.update(bar.volatility)
            labels = ("low_vol", "mid_vol", "high_vol")
            prob_text = ", ".join(f"{labels[i]}={probabilities[i]:.2f}" for i in range(3))
            print(
                f"{bar.timestamp:%Y-%m-%d %H:%M:%S} "
                f"{self.args.symbol.upper()} close={bar.close:.2f} "
                f"vol={bar.volatility:.6f} regime={labels[state]} [{prob_text}]",
                flush=True,
            )

        def _recalibrate(self, bars: list[RuntimeBar]) -> None:
            if len(bars) < self.args.min_calibration_bars:
                return
            observations = [bar.volatility for bar in bars]
            if self.model.calibrate(observations):
                self.bars_since_fit = 0
                means = ", ".join(f"{x:.6f}" for x in self.model.calibration.emission_means)
                print(f"Recalibrated Markov emissions: {means}", flush=True)

    return IBMarkovRegimeApp


def _parse_ib_time(value) -> datetime:
    text = str(value)
    if text.isdigit():
        return datetime.fromtimestamp(int(text))
    for fmt in ("%Y%m%d %H:%M:%S", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.now()


def main() -> int:
    args = parse_args()
    try:
        from ibapi.client import EClient
        from ibapi.contract import Contract
        from ibapi.wrapper import EWrapper
    except ModuleNotFoundError:
        print("Missing optional dependency: install Interactive Brokers' ibapi package to use this runner.")
        return 2

    app_cls = _build_app_class(EWrapper, EClient)
    app = app_cls(args)
    contract = _make_contract(Contract, args)

    app.connect(args.host, args.port, clientId=args.client_id)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    if not app.connected_event.wait(timeout=15):
        print("Timed out waiting for IBKR connection. Check TWS/Gateway API settings.")
        app.disconnect()
        return 1

    duration_seconds = max(args.calibration_bars * 5, args.min_calibration_bars * 5)
    app.reqHistoricalData(
        1001,
        contract,
        "",
        f"{duration_seconds} S",
        "5 secs",
        "TRADES",
        args.use_rth,
        1,
        False,
        [],
    )
    if not app.historical_done.wait(timeout=60):
        print("Historical calibration timed out; continuing with live bars only.")

    app.reqRealTimeBars(2001, contract, 5, "TRADES", args.use_rth, [])
    print("Streaming 5-second bars. Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping IBKR Markov regime monitor.", flush=True)
    finally:
        try:
            app.cancelRealTimeBars(2001)
        finally:
            app.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
