"""Fixed-design accounting and descriptive uncertainty, with no parameter selection."""

from datetime import datetime
from math import ceil, isclose, isfinite

import numpy as np

from dx27.research.opening_direction import MINUTE


TOLERANCE = 1e-6


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)) or not isfinite(value):
        raise ValueError("NONFINITE_OR_INVALID_NUMBER")
    return float(value)


def _equal(a, b):
    if not isclose(_number(a), _number(b), rel_tol=0, abs_tol=TOLERANCE):
        raise ValueError("ACCOUNTING_MISMATCH")


def block_intervals(primary, baseline, *, block_sessions, resamples=10000, seed=20261015):
    """Compound paired circular daily blocks; no iid trade-level assumption."""
    a, b = np.asarray(primary, dtype=float), np.asarray(baseline, dtype=float)
    if (a.ndim != 1 or a.shape != b.shape or not 1 <= len(a) <= 1000
            or not np.all(np.isfinite(a)) or not np.all(np.isfinite(b))
            or np.any(a <= -1) or np.any(b <= -1)
            or type(block_sessions) is not int or not 1 <= block_sessions <= 1000
            or type(resamples) is not int or not 1 <= resamples <= 100000
            or type(seed) is not int or seed < 0):
        raise ValueError("INVALID_BLOCK_INPUT")
    if resamples * ceil(len(a)/block_sessions) * block_sessions > 10_000_000:
        raise ValueError("BLOCK_ALLOCATION_LIMIT")
    # Small synthetic examples may be shorter than L; circular wrapping is explicit.
    rng = np.random.Generator(np.random.PCG64(seed))
    starts = rng.integers(0, len(a), size=(resamples, ceil(len(a) / block_sessions)))
    indices = ((starts[:, :, None] + np.arange(block_sessions)) % len(a)).reshape(resamples, -1)[:, :len(a)]
    with np.errstate(over="ignore", invalid="ignore"):
        ar = np.prod(1 + a[indices], axis=1) - 1
        br = np.prod(1 + b[indices], axis=1) - 1
    if not np.all(np.isfinite(ar)) or not np.all(np.isfinite(br)):
        raise ValueError("NONFINITE_BLOCK_RESULT")
    def interval(values):
        return [float(v) for v in np.quantile(values, [.025, .975], method="linear")]
    return dict(R1_net_return=interval(ar), R1_minus_baseline_pp=interval((ar-br)*100))


def cost_sensitivity(net_pnl, fills):
    turnover = sum(_number(f["quantity"]) * _number(f.get("reference_price", f.get("reference"))) for f in fills)
    turnover = _number(turnover)
    pnl = _number(net_pnl)
    if turnover < 0 or any(_number(f["quantity"]) <= 0 or
            _number(f.get("reference_price", f.get("reference"))) <= 0 for f in fills):
        raise ValueError("INVALID_TURNOVER")
    return dict(reference_turnover=turnover,
                break_even_extra_bps=10000*pnl/turnover if turnover else None,
                cases=[dict(additional_bps=bps, extra_cost=bps*turnover/10000,
                            fixed_fill_net_pnl=pnl-bps*turnover/10000) for bps in (0, 1, 2, 5)],
                interpretation="FIXED_FILLS_NOT_RESIZED_OR_RESIMULATED")


def audit_result(result, sessions):
    s = result.summary
    if (s["status"] not in ("COMPLETE_RESEARCH_SEQUENCE", "COMPLETE_REPLAY")
            or s["open_positions"] or result.quality
            or [d["session"] for d in result.daily] != [v.session_id for v in sessions]):
        raise ValueError("INCOMPLETE_OR_MISMATCHED_PROFILE")
    initial = _number(s.get("initial_cash", s.get("config", {}).get("initial_cash")))
    if initial <= 0:
        raise ValueError("NONPOSITIVE_CAPITAL")
    previous, returns = initial, []
    for row in result.daily:
        if not row["data_complete"] or row["open_positions"] or row.get("admissible") is False:
            raise ValueError("INCOMPLETE_DAY")
        _equal(row["starting_equity"], previous)
        end = _number(row["ending_equity"])
        if end <= 0:
            raise ValueError("NONPOSITIVE_CAPITAL")
        returns.append(end/previous-1)
        previous = end
    _equal(previous, s["ending_equity"])
    _equal(previous, s["ending_cash"])
    _equal(previous-initial, s["net_pnl"])
    _equal(initial+sum(_number(f["cash_delta"]) for f in result.fills), previous)
    _equal(sum(_number(t["net_pnl"]) for t in result.trades), previous-initial)
    fees = sum(_number(f["commission"]) for f in result.fills)
    spread = sum(_number(f["spread_cost"]) for f in result.fills)
    slip = sum(_number(f["slippage_cost"]) for f in result.fills)
    # Independently reconstruct gross cash flows from references, not trade labels.
    inventory, gross_cash, at_cash = {}, initial, initial
    expected_minutes = ((v, v.opens_at + (i+1)*MINUTE) for v in sessions
                        for i in range(int((v.closes_at-v.opens_at)/MINUTE)))
    expected = list(expected_minutes)
    if len(result.equity) != len(expected):
        raise ValueError("MINUTE_COVERAGE_MISMATCH")
    peak, drawdown, exposed = initial, 0.0, 0
    daily_close = {}
    for row, (session, at) in zip(result.equity, expected):
        if row["session"] != session.session_id or datetime.fromisoformat(row.get("timestamp", row.get("at"))) != at:
            raise ValueError("MINUTE_CLOCK_MISMATCH")
        _equal(row["cash"]+row["holdings_value"], row["equity"])
        e = _number(row["equity"])
        peak = max(peak, e)
        drawdown = max(drawdown, (peak-e)/peak)
        exposed += abs(_number(row["holdings_value"])) > TOLERANCE
        daily_close[session.session_id] = e
    for row in result.daily:
        _equal(daily_close[row["session"]], row["ending_equity"])
    for f in result.fills:
        q = _number(f["quantity"])
        reference = _number(f.get("reference_price", f.get("reference")))
        price = _number(f["price"])
        if (q <= 0 or reference <= 0 or price <= 0 or f["side"] not in ("buy", "sell")
                or any(_number(f[k]) < 0 for k in ("commission", "spread_cost", "slippage_cost"))):
            raise ValueError("INVALID_FILL")
        signed = q if f["side"] == "buy" else -q
        symbol = f.get("symbol", "QQQ")
        inventory[symbol] = inventory.get(symbol, 0) + signed
        gross_cash -= signed*reference
        _equal(f["cash_delta"], -signed*price-f["commission"])
        _equal(abs(price-reference)*q, f["spread_cost"]+f["slippage_cost"])
        at_cash += f["cash_delta"]
    for quantity in inventory.values():
        _equal(quantity, 0)
    _equal(at_cash, previous)
    _equal(gross_cash-initial-fees-spread-slip, previous-initial)
    _equal(float(np.prod(1+np.asarray(returns)))-1, previous/initial-1)
    return dict(net_return=previous/initial-1, net_pnl=previous-initial, daily_returns=returns,
                maximum_drawdown=drawdown, closed_trades=len(result.trades),
                zero_return_days=sum(r == 0 for r in returns),
                zero_trade_days=len(sessions)-len({t["session"] for t in result.trades}),
                exposed_minute_fraction=exposed/len(expected),
                exposure_measure="MINUTE_END_NONZERO_HOLDINGS_FRACTION", gross_pnl=gross_cash-initial,
                commission=fees, spread_cost=spread, slippage_cost=slip,
                ambiguous_minutes=s.get("ambiguous_minutes", 0),
                cost_sensitivity=cost_sensitivity(previous-initial, result.fills))


def comparison_report(results, sessions):
    """Arithmetic-only report; registration/source admission is a separate layer."""
    if set(results) != {"R0", "R1", "baseline"}:
        raise ValueError("ALL_THREE_FIXED_PROFILES_REQUIRED")
    sessions = tuple(sessions)
    if not sessions or len({s.session_id for s in sessions}) != len(sessions):
        raise ValueError("INVALID_COMPARISON_CALENDAR")
    arms = {k: audit_result(v, sessions) for k, v in results.items()}
    a, b = arms["R1"]["daily_returns"], arms["baseline"]["daily_returns"]
    intervals = {str(length): block_intervals(a, b, block_sessions=length) for length in (5, 20)}
    return dict(status="COMPLETE_OFFLINE_ARITHMETIC", effectiveness="NOT_EVALUATED",
                execution_enabled=False, evaluation_registered=False,
                primary_R1_net_return=arms["R1"]["net_return"],
                secondary_R1_minus_baseline_pp=(arms["R1"]["net_return"]-arms["baseline"]["net_return"])*100,
                intervals_by_block_sessions=intervals, arms=arms,
                paired_daily=[dict(session=s.session_id, R1_return=x, baseline_return=y)
                              for s, x, y in zip(sessions, a, b)])
