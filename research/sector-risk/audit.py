"""Independent Decimal forecasts, selection and account-equation review.

Consumes the retained decoded prices, not an independent vendor or execution feed.
"""
from decimal import Decimal, localcontext


def d(value):
    return Decimal(str(value))


def close(actual, expected):
    if abs(d(actual)-expected) > Decimal('0.0000001') * max(Decimal(1), abs(expected)/100000):
        raise ValueError('INDEPENDENT_RECONCILIATION_FAILED')


def weights_for(formation, mode, original):
    key = 'relative' if mode == 'relative' else 'momentum'
    counts = {}; weights = {}
    for row in sorted(formation['eligible'], key=lambda r: (-r[key], r['symbol'])):
        if len(weights) == original['position_count']:
            break
        sector = row['sector']
        if counts.get(sector, 0) >= original['maximum_names_per_sector']:
            continue
        weights[row['symbol']] = d(original['weight_per_slot'])
        counts[sector] = counts.get(sector, 0)+1
    return weights


def independent_forecast(adj, calendar, asof, weights, rules):
    end = calendar.index(asof); count = rules['forecast_return_observations']
    days = calendar[max(0, end-count):end+1]
    if len(days) != count+1:
        raise ValueError('INDEPENDENT_WARMUP_MISSING')
    square = Decimal(0)
    for before, after in zip(days, days[1:]):
        r = sum((w*(d(adj[s][after])/d(adj[s][before])-1) for s, w in weights.items()), Decimal(0))
        square += r*r
    vol = (square/count*d(rules['annualization_sessions'])).sqrt()
    scale = min(d(rules['maximum_scale']), d(rules['annual_volatility_target'])/vol) if vol else Decimal(1)
    return vol, scale


def audit_case(case, adj, calendar, formations, mode, overlay, bps, original, rules):
    if case['summary']['halt']:
        raise ValueError('FULL_PERIOD_PATH_REQUIRED')
    with localcontext() as ctx:
        ctx.prec = 45
        plans = {}; first_scale = None
        for f in formations:
            weights = weights_for(f, mode, original)
            vol, candidate = independent_forecast(adj, calendar, f['asof'], weights, rules)
            if first_scale is None:
                first_scale = candidate
            scale = Decimal(1) if overlay == 'unmanaged' else first_scale if overlay == 'fixed_initial' else candidate
            day = calendar[calendar.index(f['asof'])+2]
            plans[day] = (f, vol, scale, {s: w*scale for s, w in weights.items()})
        events = {e['date']: e for e in case['events']}
        if len(events) != len(case['events']):
            raise ValueError('DUPLICATE_EVENT')
        units = {}; cash = d(original['initial_proxy_capital']); checked = 0; cost_total = Decimal(0)
        expected_days = [day for day in calendar if original['formation_start']<=day<=original['mark_end']]
        # Full-period audit deliberately refuses a halted path rather than certifying it.
        if case['summary']['halt'] or [n['date'] for n in case['nav']] != expected_days:
            raise ValueError('FULL_PERIOD_PATH_REQUIRED')
        peak = cash; dd = Decimal(0); turnover = Decimal(0)
        for day, nav in zip(expected_days, case['nav']):
            values = {s: q*d(adj[s][day]) for s, q in units.items()}
            if day in plans:
                f, vol, scale, weights = plans[day]; event = events[day]
                assert event['formation'] == f['asof']
                close(event['forecast_volatility'], vol); close(event['scale'], scale)
                if set(event['weights']) != set(weights):
                    raise ValueError('WRONG_TARGET_NAMES')
                for s, w in weights.items():
                    close(event['weights'][s], w)
                if set(event['old_values']) != set(values) or set(event['new_values']) != set(weights):
                    raise ValueError('WRONG_HOLDING_NAMES')
                for s, v in values.items():
                    close(event['old_values'][s], v)
                close(event['old_cash'], cash)
                before = cash+sum(values.values()); close(event['before'], before)
                cost = d(event['cost']); after = before-cost
                new = {s: w*after for s, w in weights.items()}
                trade = sum((abs(new.get(s, 0)-values.get(s, 0)) for s in set(new)|set(values)), Decimal(0))
                close(cost, trade*d(bps)/10000); close(event['turnover_notional'], trade)
                for s, v in new.items():
                    close(event['new_values'][s], v)
                cash = after-sum(new.values()); close(event['new_cash'], cash)
                if cash < Decimal('-0.0000001'):
                    raise ValueError('UNFUNDED_PATH')
                units = {s: v/d(adj[s][day]) for s, v in new.items()}; values = new
                turnover += trade; cost_total += cost
            equity = cash+sum(values.values()); close(nav['equity'], equity)
            close(nav['cash'], cash); close(nav['gross'], sum(values.values()))
            peak = max(peak, equity); dd = max(dd, 1-equity/peak); checked += 1
        if set(events) != set(plans):
            raise ValueError('WRONG_REBALANCE_SCHEDULE')
        close(case['summary']['proxy_return'], equity/d(original['initial_proxy_capital'])-1)
        close(case['summary']['observed_drawdown'], dd)
        close(case['summary']['modeled_cost'], cost_total)
        close(case['summary']['turnover_over_initial_capital'], turnover/d(original['initial_proxy_capital']))
        return dict(status='PASS', independent_forecasts=len(plans), reconciled_daily_marks=checked,
                    source_authenticity_verified=False, executable_prices_verified=False)
