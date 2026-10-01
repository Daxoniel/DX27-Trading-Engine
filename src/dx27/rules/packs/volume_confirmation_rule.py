from dx27.core.models.rule_result import RuleResult


class VolumeConfirmationRule:

    rule_id = "volume_confirmation"

    def __init__(self, minimum_ratio: float = 1.5):
        self.minimum_ratio = minimum_ratio

    def evaluate(self, context, features) -> RuleResult:
        if features.average_volume_20 <= 0:
            return RuleResult(
                rule_id=self.rule_id,
                triggered=False,
                score=0.0,
                reason="invalid_average_volume",
            )

        volume_ratio = context.volume / features.average_volume_20
        triggered = volume_ratio >= self.minimum_ratio

        return RuleResult(
            rule_id=self.rule_id,
            triggered=triggered,
            score=volume_ratio,
            reason=(
                "volume_confirmation_passed"
                if triggered
                else "volume_confirmation_failed"
            ),
        )