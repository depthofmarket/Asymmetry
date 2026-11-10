"""CME gold dollars per 1.00 price move.

MGC is 10 troy ounces: $10 per 1.00 and $1 per 0.10 tick.
GC is 100 troy ounces: $100 per 1.00 and $10 per 0.10 tick.
An unrecognized symbol is not treated as MGC.
"""

from __future__ import annotations

import math
import re

MGC_POINT_VALUE_USD = 10.0
GC_POINT_VALUE_USD = 100.0
TICK_SIZE = 0.10

_MONTH = re.compile(r"^[FGHJKMNQUVXZ]\d{1,4}([._\s#-].*)?$")
_NUMERIC = re.compile(r"^\d{2,4}([._\s#-].*)?$")


def _strip_venue(raw: str | None) -> str | None:
    if raw is None:
        return None
    symbol = raw.strip().upper()
    if not symbol:
        return None
    if ":" in symbol:
        symbol = symbol.rsplit(":", 1)[-1].strip()
    if "/" in symbol:
        symbol = symbol.rsplit("/", 1)[-1].strip()
    return symbol or None


def _matches_root(symbol: str, root: str) -> bool:
    if not symbol.startswith(root):
        return False
    if len(symbol) == len(root):
        return True
    nxt = symbol[len(root)]
    if nxt in "#._- /":
        return True
    remainder = symbol[len(root):]
    return _MONTH.match(remainder) is not None or _NUMERIC.match(remainder) is not None


def contract_root(raw: str | None) -> str | None:
    symbol = _strip_venue(raw)
    if symbol is None:
        return None
    if _matches_root(symbol, "MGC"):
        return "MGC"
    if _matches_root(symbol, "GC"):
        return "GC"
    return None


def confirmed_point_value(
    symbol: str | None,
    exchange_symbol: str | None = None,
    underlying: str | None = None,
    sdk_point_value: float | None = None,
) -> float:
    found = [contract_root(symbol), contract_root(exchange_symbol), contract_root(underlying)]
    present = [item for item in found if item is not None]
    if present and any(item != present[0] for item in present):
        raise ValueError("Gold symbol fields identify different contracts.")
    if not present:
        raise ValueError(f"Unsupported gold symbol: {symbol!r}.")
    expected = MGC_POINT_VALUE_USD if present[0] == "MGC" else GC_POINT_VALUE_USD
    if sdk_point_value is not None and math.isfinite(sdk_point_value) and sdk_point_value > 0:
        if abs(sdk_point_value - expected) > 1e-6:
            raise ValueError("MotiveWave point value disagrees with the identified gold root.")
    return expected


def gross_pnl(price_move: float, point_value: float, contracts: int, long_position: bool) -> float:
    points = price_move if long_position else -price_move
    return points * point_value * contracts
