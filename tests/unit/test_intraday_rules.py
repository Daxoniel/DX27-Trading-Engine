"""The previous generic breakout and volume voting rules are retired by ORB."""

from dx27.domains.intraday.bots.intraday_breakout import IntradayBreakoutBot


def test_tanyuan_has_no_independent_volume_voting_rule():
    assert not hasattr(IntradayBreakoutBot(), "volume_rule")
