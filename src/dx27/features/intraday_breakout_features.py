from dx27.core.models.feature_snapshot import FeatureSnapshot


class IntradayBreakoutFeatureCalculator:

    def calculate(self, bars) -> FeatureSnapshot:
        """
        bars:
            按时间顺序排列，最后一根为当前 bar。
            每个元素至少需要 high / volume / close 等属性。
        """

        if len(bars) < 21:
            raise ValueError("At least 21 bars are required")

        history = bars[-21:-1]
        current = bars[-1]

        previous_high_20 = max(bar.high for bar in history)

        average_volume_20 = (
            sum(bar.volume for bar in history) / len(history)
        )

        # ATR 暂时先留最简版本，下一步单独完善
        true_ranges = []

        previous_close = history[0].close

        for bar in history[1:] + [current]:
            true_range = max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )

            true_ranges.append(true_range)
            previous_close = bar.close

        atr_period = min(14, len(true_ranges))
        atr_14 = sum(true_ranges[-atr_period:]) / atr_period

        return FeatureSnapshot(
            previous_high_20=previous_high_20,
            average_volume_20=average_volume_20,
            atr_14=atr_14,
        )