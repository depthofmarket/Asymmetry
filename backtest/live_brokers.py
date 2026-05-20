from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from backtest.live import PaperTradingEvent
from backtest.live_feeds import CqgWebApiConfig, CqgWebApiSetupError


@dataclass(frozen=True)
class OrderIntent:
    timestamp: pd.Timestamp
    action: str
    side: str
    quantity: int
    order_type: str = "MKT"
    symbol: str = ""
    strategy_tag: str = ""
    reason: str = ""
    reference_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        row = {
            "timestamp": self.timestamp,
            "action": self.action,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "symbol": self.symbol,
            "strategy_tag": self.strategy_tag,
            "reason": self.reason,
            "reference_price": self.reference_price,
        }
        for key, value in self.metadata.items():
            row[f"meta_{key}"] = value
        return row


class BrokerAdapter(Protocol):
    def connect(self) -> None:
        ...

    def place_order(self, order: OrderIntent) -> None:
        ...

    def close(self) -> None:
        ...


class NullBroker:
    """Drop order intents. Useful when only local paper fills are desired."""

    def connect(self) -> None:
        return None

    def place_order(self, order: OrderIntent) -> None:
        return None

    def close(self) -> None:
        return None


class CsvOrderAuditBroker:
    """
    Persist broker-bound order intents to CSV.

    This is the dry-run broker for validating that the live runtime would send
    the right BUY/SELL actions before CQG order routing is enabled.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.orders: list[OrderIntent] = []

    def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def place_order(self, order: OrderIntent) -> None:
        self.orders.append(order)
        pd.DataFrame([item.to_record() for item in self.orders]).to_csv(self.path, index=False)

    def close(self) -> None:
        if self.orders:
            pd.DataFrame([item.to_record() for item in self.orders]).to_csv(self.path, index=False)


class CqgWebApiBroker:
    """
    CQG order-router placeholder guarded by setup checks.

    Do not send live or paper exchange orders until account IDs, conformance,
    symbol mapping, and fill reconciliation are explicitly validated.
    """

    def __init__(self, config: CqgWebApiConfig):
        self.config = config

    def connect(self) -> None:
        self.config.validate_python_samples()
        raise CqgWebApiSetupError(
            "CQG order routing is scaffolded but intentionally disabled. "
            "Enable this only after AMP/CQG provides WebAPI order-routing "
            "access, account IDs, and any required conformance approval."
        )

    def place_order(self, order: OrderIntent) -> None:
        raise CqgWebApiSetupError("CQG broker is not connected.")

    def close(self) -> None:
        return None


class PaperEventOrderBridge:
    """
    Convert local paper fill events into broker order intents.

    This lets us dry-run the exact order stream now. Later the same bridge can
    point at a real CQG demo broker, though fill reconciliation should replace
    local simulated prices before going anywhere near production.
    """

    def __init__(self, broker: BrokerAdapter, *, symbol: str):
        self.broker = broker
        self.symbol = symbol

    def connect(self) -> None:
        self.broker.connect()

    def close(self) -> None:
        self.broker.close()

    def handle_event(self, event: PaperTradingEvent) -> OrderIntent | None:
        order = order_intent_from_event(event, symbol=self.symbol)
        if order is not None:
            self.broker.place_order(order)
        return order


def order_intent_from_event(event: PaperTradingEvent, *, symbol: str) -> OrderIntent | None:
    if event.event_type == "entry_filled":
        side = "BUY" if event.direction == "long" else "SELL"
        action = "OPEN"
    elif event.event_type == "exit_filled":
        side = "SELL" if event.direction == "long" else "BUY"
        action = "CLOSE"
    else:
        return None

    quantity = int(event.contracts or 0)
    if quantity <= 0:
        return None

    return OrderIntent(
        timestamp=pd.Timestamp(event.timestamp),
        action=action,
        side=side,
        quantity=quantity,
        order_type="MKT",
        symbol=symbol,
        strategy_tag=event.setup_tag or event.direction,
        reason=event.reason,
        reference_price=event.price,
        metadata={
            "event_type": event.event_type,
            "signal_time": event.signal_time,
        },
    )
