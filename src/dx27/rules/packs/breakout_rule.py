from dx27.core.models.rule_result import RuleResult


class BreakoutRule:

    rule_id = "breakout_above_previous_high_20"

    def evaluate(self, context, features) -> RuleResult:
        triggered = context.close > features.previous_high_20

        return RuleResult(
            rule_id=self.rule_id,
            triggered=triggered,
            score=1.0 if triggered else 0.0,
            reason=(
                "price_breakout_confirmed"
                if triggered
                else "price_has_not_broken_previous_high"
            ),
        )