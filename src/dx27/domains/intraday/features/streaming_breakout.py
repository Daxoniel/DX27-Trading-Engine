"""Incremental Wilder features with a complete, current-session opening range."""

from datetime import time, timedelta
from zoneinfo import ZoneInfo

from dx27.core.models.feature_snapshot import FeatureSnapshot
from dx27.domains.intraday.features.breakout_features import IntradayBreakoutFeatureCalculator


class StreamingBreakoutFeatures:
    """The batch calculator's ATR/ADX formulas, updated once per completed bar.

    Bars use aware interval-start timestamps; ``as_of`` is their completion
    time. Missing intraday bars are handled by resetting this state upstream.
    """

    def __init__(self, atr_period=14, adx_period=14):
        if atr_period < 1 or adx_period < 1:
            raise ValueError("indicator periods must be positive")
        self.atr_period, self.adx_period = atr_period, adx_period
        self.previous = None
        self.ranges = 0
        self.atr_sum = self.tr_sum = self.plus_sum = self.minus_sum = 0.0
        self.atr = self.adx = None
        self.dx_count, self.dx_sum = 0, 0.0
        self.session = None
        self.opening = {}
        self.ny = ZoneInfo("America/New_York")

    def add(self, bar, *, as_of):
        if bar.timestamp.tzinfo is None or as_of.tzinfo is None:
            raise ValueError("streaming bars require timezone-aware timestamps")
        if as_of != bar.timestamp + timedelta(minutes=5):
            raise ValueError("five-minute bar must be complete at as_of")
        previous = self.previous
        if previous is not None:
            if previous.symbol != bar.symbol or previous.timestamp >= bar.timestamp:
                raise ValueError("feature state requires one symbol in chronological order")
            tr = max(bar.high - bar.low, abs(bar.high - previous.close), abs(bar.low - previous.close))
            up, down = bar.high - previous.high, previous.low - bar.low
            plus = up if up > down and up > 0 else 0.0
            minus = down if down > up and down > 0 else 0.0
            self.ranges += 1
            if self.ranges <= self.atr_period:
                self.atr_sum += tr
                if self.ranges == self.atr_period:
                    self.atr = self.atr_sum / self.atr_period
            else:
                self.atr = (self.atr * (self.atr_period - 1) + tr) / self.atr_period
            if self.ranges <= self.adx_period:
                self.tr_sum += tr
                self.plus_sum += plus
                self.minus_sum += minus
            else:
                self.tr_sum = self.tr_sum - self.tr_sum / self.adx_period + tr
                self.plus_sum = self.plus_sum - self.plus_sum / self.adx_period + plus
                self.minus_sum = self.minus_sum - self.minus_sum / self.adx_period + minus
            if self.ranges >= self.adx_period:
                dx = IntradayBreakoutFeatureCalculator._dx(self.plus_sum, self.minus_sum, self.tr_sum)
                self.dx_count += 1
                if self.dx_count <= self.adx_period:
                    self.dx_sum += dx
                    if self.dx_count == self.adx_period:
                        self.adx = self.dx_sum / self.adx_period
                else:
                    self.adx = (self.adx * (self.adx_period - 1) + dx) / self.adx_period
        self.previous = bar
        local = bar.timestamp.astimezone(self.ny)
        if self.session != local.date():
            self.session, self.opening = local.date(), {}
        if time(9, 30) <= local.time() < time(10):
            self.opening[local.time()] = bar
        expected = {time(9, minute) for minute in (30, 35, 40, 45, 50, 55)}
        complete = set(self.opening) == expected and as_of.astimezone(self.ny).time() >= time(10)
        return FeatureSnapshot(
            max((b.high for b in self.opening.values()), default=None),
            min((b.low for b in self.opening.values()), default=None), complete,
            self.atr, self.adx, self.atr is not None and self.adx is not None,
        )
