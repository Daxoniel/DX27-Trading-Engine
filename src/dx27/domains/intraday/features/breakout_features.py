"""Completed-bar ORB, ATR, and ADX feature calculation."""

from datetime import time
from zoneinfo import ZoneInfo

from dx27.core.models.feature_snapshot import FeatureSnapshot


class IntradayBreakoutFeatureCalculator:
    """Calculate features from a chronological history prefix only.

    ATR and ADX use Wilder smoothing.  The opening range is independently
    scoped to the current New York session, so warm-up bars from a prior day
    can never affect it.
    """

    def __init__(self, atr_period: int = 14, adx_period: int = 14):
        if atr_period < 1 or adx_period < 1:
            raise ValueError("indicator periods must be positive")
        self.atr_period = atr_period
        self.adx_period = adx_period
        self._new_york = ZoneInfo("America/New_York")

    def calculate(self, bars) -> FeatureSnapshot:
        if not bars:
            raise ValueError("at least one completed bar is required")
        bars = tuple(bars)
        current_time = self._local_time(bars[-1].timestamp)
        current_date = current_time.date()
        opening_bars = [
            bar for bar in bars
            if self._local_time(bar.timestamp).date() == current_date
            and time(9, 30) <= self._local_time(bar.timestamp).time() < time(10, 0)
        ]
        opening_range_ready = current_time.time() >= time(10, 0)
        atr = self._atr(bars, self.atr_period)
        adx = self._adx(bars, self.adx_period)
        return FeatureSnapshot(
            opening_range_high=max((bar.high for bar in opening_bars), default=None),
            opening_range_low=min((bar.low for bar in opening_bars), default=None),
            opening_range_ready=opening_range_ready and bool(opening_bars),
            atr=atr,
            adx=adx,
            indicators_ready=atr is not None and adx is not None,
        )

    def _local_time(self, timestamp):
        # Historical fixtures may use naive New York timestamps; provider data
        # should be timezone-aware and is converted explicitly.
        return timestamp.replace(tzinfo=self._new_york) if timestamp.tzinfo is None else timestamp.astimezone(self._new_york)

    @staticmethod
    def _true_ranges(bars):
        return [max(bar.high - bar.low, abs(bar.high - previous.close), abs(bar.low - previous.close)) for previous, bar in zip(bars, bars[1:])]

    def _atr(self, bars, period):
        ranges = self._true_ranges(bars)
        if len(ranges) < period:
            return None
        value = sum(ranges[:period]) / period
        for true_range in ranges[period:]:
            value = (value * (period - 1) + true_range) / period
        return value

    def _adx(self, bars, period):
        if len(bars) < 2 * period:
            return None
        true_ranges = self._true_ranges(bars)
        plus = []
        minus = []
        for previous, bar in zip(bars, bars[1:]):
            up_move, down_move = bar.high - previous.high, previous.low - bar.low
            plus.append(up_move if up_move > down_move and up_move > 0 else 0.0)
            minus.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        smoothed_tr, smoothed_plus, smoothed_minus = (sum(values[:period]) for values in (true_ranges, plus, minus))
        dx_values = [self._dx(smoothed_plus, smoothed_minus, smoothed_tr)]
        for index in range(period, len(true_ranges)):
            smoothed_tr = smoothed_tr - smoothed_tr / period + true_ranges[index]
            smoothed_plus = smoothed_plus - smoothed_plus / period + plus[index]
            smoothed_minus = smoothed_minus - smoothed_minus / period + minus[index]
            dx_values.append(self._dx(smoothed_plus, smoothed_minus, smoothed_tr))
        if len(dx_values) < period:
            return None
        adx = sum(dx_values[:period]) / period
        for dx in dx_values[period:]:
            adx = (adx * (period - 1) + dx) / period
        return adx

    @staticmethod
    def _dx(plus, minus, true_range):
        if true_range == 0:
            return 0.0
        plus_di, minus_di = 100 * plus / true_range, 100 * minus / true_range
        total = plus_di + minus_di
        return 0.0 if total == 0 else 100 * abs(plus_di - minus_di) / total
