"""Shared one-minute OHLCV validation for files and event envelopes."""

import math
import re

from dx27.core.models.market_context import MarketContext


def validate_bar(bar: MarketContext) -> None:
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9./-]*", bar.symbol):
        raise ValueError("invalid symbol")
    if bar.timestamp.tzinfo is None or bar.timestamp.second or bar.timestamp.microsecond:
        raise ValueError("bars require aware, minute-aligned start timestamps")
    if bar.timeframe != "1m":
        raise ValueError("input must be one-minute OHLCV")
    if any(not math.isfinite(v) for v in (bar.open, bar.high, bar.low, bar.close, bar.volume)):
        raise ValueError("OHLCV must be finite")
    if min(bar.open, bar.high, bar.low, bar.close) <= 0 or bar.volume < 0:
        raise ValueError("prices must be positive and volume nonnegative")
    tolerance = max(bar.open, bar.high, bar.low, bar.close) * 1e-12
    if (bar.low - min(bar.open, bar.close) > tolerance or max(bar.open, bar.close) - bar.high > tolerance
            or bar.low - bar.high > tolerance):
        raise ValueError("inconsistent OHLC boundaries")

