"""Shared long-only quantity/risk budget for immediate and clocked replay."""

from math import floor

from dx27.core.models.trade_intent import TradeSide


def plan_quantity(config, *, cash, equity, open_risk, reference, atr, prior_volume,
                  maximum_entry_price=None):
    costs = config.costs
    entry = costs.price(reference, TradeSide.BUY) if maximum_entry_price is None else maximum_entry_price
    stop = entry - atr * config.stop_atr
    if stop <= 0:
        return 0, 0.0
    loss_per_share = entry - costs.price(stop, TradeSide.SELL)
    available_risk = min(equity * config.risk_per_trade, equity * config.max_open_risk - open_risk)
    upper = max(0, floor(min(cash / entry, equity * config.max_position_fraction / entry,
                             prior_volume * config.max_volume_participation)))
    low, high = 0, upper
    while low < high:
        mid = (low + high + 1) // 2
        risk = mid * loss_per_share + 2 * costs.commission(mid)
        needed_cash = mid * entry + costs.commission(mid)
        if risk <= available_risk and needed_cash <= cash:
            low = mid
        else:
            high = mid - 1
    return low, low * loss_per_share + 2 * costs.commission(low) if low else 0.0
