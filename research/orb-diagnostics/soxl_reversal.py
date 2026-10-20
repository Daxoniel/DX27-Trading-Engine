"""Offline SOXL sign-rule diagnostics; no API, sizing intent or order transport.

Prices are revised historical trade-bar proxies, not executable quote evidence.
"""
from datetime import date
import math
import random
import statistics


ARMS = ('GAP_DOWN_LONG', 'ALWAYS_LONG', 'GAP_UP_SHORT', 'TWO_SIDED')
ENTRIES = ('09:30', '09:31', '09:32', '09:35')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def direction(gap, arm):
    require(math.isfinite(gap), 'NONFINITE_GAP')
    require(arm in ARMS, 'UNKNOWN_ARM')
    if arm == 'ALWAYS_LONG':
        return 1
    if arm == 'GAP_DOWN_LONG':
        return int(gap < 0)
    if arm == 'GAP_UP_SHORT':
        return -int(gap >= 0)
    return 1 if gap < 0 else -1


def trade_return(entry, exit_price, side, bps):
    require(side in (-1, 1) and 0 <= bps < 10000, 'INVALID_TRADE_PARAMETERS')
    require(all(math.isfinite(p) and p > 0 for p in (entry, exit_price)), 'INVALID_PRICE')
    b = bps / 10000
    if side == 1:
        return exit_price * (1 - b) / (entry * (1 + b)) - 1
    return (entry * (1 - b) - exit_price * (1 + b)) / entry


def wilson(wins, total):
    if not total:
        return None
    z = 1.959963984540054
    p = wins / total
    center = (p + z*z/(2*total)) / (1 + z*z/total)
    radius = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / (1 + z*z/total)
    return [center-radius, center+radius]


def quantile(values, q):
    if not values:
        return None
    values = sorted(values)
    x = (len(values)-1)*q
    lo = int(x)
    return values[lo] + (values[min(lo+1, len(values)-1)]-values[lo])*(x-lo)


def summarize(ledger):
    require(bool(ledger), 'EMPTY_LEDGER')
    trades = [r for r in ledger if r['side']]
    rets = [r['trade_return'] for r in trades]
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x < 0]
    daily = [r['portfolio_return'] for r in ledger]
    nav = peak = 1.
    max_dd = 0.
    streak = longest = 0
    for row in ledger:
        nav *= 1 + row['portfolio_return']
        require(nav > 0 and math.isfinite(nav), 'ACCOUNT_INSOLVENT')
        peak = max(peak, nav)
        max_dd = max(max_dd, 1-nav/peak)
        if row['side']:
            streak = streak + 1 if row['trade_return'] < 0 else 0
            longest = max(longest, streak)
    sd = statistics.stdev(daily) if len(daily) > 1 else 0
    elapsed_years = ((date.fromisoformat(ledger[-1]['date'])-
                      date.fromisoformat(ledger[0]['date'])).days+1)/365.25
    return dict(sessions=len(ledger), trades=len(trades), wins=len(wins), losses=len(losses),
        flat_trades=len(rets)-len(wins)-len(losses),
        net_trade_win_rate=len(wins)/len(rets) if rets else None,
        win_rate_wilson95_iid_only=wilson(len(wins), len(rets)),
        mean_trade_return_bps=statistics.mean(rets)*10000 if rets else None,
        average_win_bps=statistics.mean(wins)*10000 if wins else None,
        average_loss_bps=statistics.mean(losses)*10000 if losses else None,
        payoff_ratio=statistics.mean(wins)/-statistics.mean(losses) if wins and losses else None,
        profit_factor=sum(wins)/-sum(losses) if losses else None,
        median_trade_bps=quantile(rets, .5)*10000 if rets else None,
        p05_trade_bps=quantile(rets, .05)*10000 if rets else None,
        worst_trade_bps=min(rets)*10000 if rets else None,
        best_trade_bps=max(rets)*10000 if rets else None,
        longest_losing_trade_streak=longest,
        mean_portfolio_daily_bps=statistics.mean(daily)*10000,
        final_equity=100000*nav, compound_total_return=nav-1,
        observed_session_annualized_geometric_return=nav**(252/len(ledger))-1,
        elapsed_calendar_cagr=nav**(1/elapsed_years)-1,
        elapsed_calendar_years=elapsed_years,
        annualization_note='Only quality-selected sessions modeled; calendar CAGR assumes idle on excluded sessions, not implementable real-time exclusion evidence',
        annualized_zero_cash_sharpe=statistics.mean(daily)/sd*math.sqrt(252) if sd else None,
        end_of_trade_max_drawdown=max_dd,
        worst_gross_intratrade_mae_bps=min(r['mae'] for r in trades)*10000 if trades else None,
        average_gross_intratrade_mae_bps=statistics.mean(r['mae'] for r in trades)*10000 if trades else None,
        average_gross_intratrade_mfe_bps=statistics.mean(r['mfe'] for r in trades)*10000 if trades else None)


def simulate(sessions, *, arm, entry='09:32', bps=5, allocation=.25):
    require(arm in ARMS and entry in ENTRIES and 0 < allocation <= 1, 'INVALID_MODEL')
    ledger = []
    for row in sessions:
        side = direction(row['gap'], arm)
        px = row['minutes'][entry]['o']
        exit_price = row['minutes']['10:00']['o']
        path = [v for t, v in row['minutes'].items() if entry <= t < '10:00']
        # The entire exit minute is unavailable while holding; include only exit open.
        low = min([px, exit_price] + [v['l'] for v in path])
        high = max([px, exit_price] + [v['h'] for v in path])
        gross = trade_return(px, exit_price, side, 0) if side else 0.
        net = trade_return(px, exit_price, side, bps) if side else 0.
        mae = (low/px-1 if side == 1 else 1-high/px) if side else 0.
        mfe = (high/px-1 if side == 1 else 1-low/px) if side else 0.
        ledger.append(dict(date=row['date'], gap=row['gap'], side=side,
                           entry=entry, entry_price=px, exit_price=exit_price,
                           trade_return=net, gross_trade_return=gross,
                           portfolio_return=allocation*net, mae=mae, mfe=mfe,
                           ex_dividend=row.get('ex_dividend', False),
                           previous_20_session_vol=row.get('previous_20_session_vol')))
    return dict(summary=summarize(ledger), ledger=ledger)


def regression(sessions, lag=5):
    """OLS y=intercept+beta*x; Newey-West Bartlett HAC, explicit unscaled returns."""
    x = [r['gap'] for r in sessions]
    y = [r['minutes']['10:00']['o']/r['minutes']['09:30']['o']-1 for r in sessions]
    require(len(x) > lag + 2, 'INSUFFICIENT_REGRESSION_SESSIONS')
    xm, ym = statistics.mean(x), statistics.mean(y)
    dx = [v-xm for v in x]
    xx = sum(v*v for v in dx)
    require(xx > 0, 'CONSTANT_GAP')
    beta = sum(a*(b-ym) for a, b in zip(dx, y))/xx
    alpha = ym-beta*xm
    residual = [b-alpha-beta*a for a, b in zip(x, y)]
    score = [a*e for a, e in zip(dx, residual)]
    meat = sum(v*v for v in score)
    for k in range(1, lag+1):
        meat += 2*(1-k/(lag+1))*sum(score[t]*score[t-k] for t in range(k, len(x)))
    se = math.sqrt(max(meat, 0))/xx
    yy = sum((v-ym)**2 for v in y)
    return dict(n=len(x), intercept=alpha, beta=beta, beta_hac_se=se,
                beta_hac_t=beta/se if se else None, hac_lag=lag,
                r_squared=1-sum(v*v for v in residual)/yy if yy else None,
                note='Both returns in decimal units; no coefficient annualization; no causal identification')


def block_intervals(ledger, baseline, *, replicates=2000, block=20, seed=5807282):
    """Circular paired blocks of sessions, including the days with no trade."""
    require(len(ledger) == len(baseline) and len(ledger) > 0, 'UNPAIRED_LEDGER')
    require(all(a['date'] == b['date'] for a, b in zip(ledger, baseline)), 'UNPAIRED_DATES')
    n = len(ledger)
    vectors = [(r['trade_return'], int(bool(r['side'])), int(r['side'] != 0 and r['trade_return'] > 0),
                r['portfolio_return']-b['portfolio_return']) for r, b in zip(ledger, baseline)]
    def blocks(length):
        out = []
        for start in range(n):
            out.append(tuple(sum(vectors[(start+j) % n][k] for j in range(length)) for k in range(4)))
        return out
    full = blocks(block)
    tail = blocks(n % block) if n % block else None
    rng = random.Random(seed)
    means, rates, differences = [], [], []
    for _ in range(replicates):
        sums = [0., 0., 0., 0.]
        for _ in range(n//block):
            chosen = full[rng.randrange(n)]
            sums = [a+b for a, b in zip(sums, chosen)]
        if tail:
            sums = [a+b for a, b in zip(sums, tail[rng.randrange(n)])]
        if sums[1]:
            means.append(sums[0]/sums[1]*10000)
            rates.append(sums[2]/sums[1])
        differences.append(sums[3]/n*10000)
    ci = lambda values: [quantile(values, .025), quantile(values, .975)]
    return dict(method='CIRCULAR_PAIRED_VALID_SESSION_BLOCKS', replicates=replicates,
                block_sessions=block, seed=seed, net_mean_trade_bps95=ci(means),
                net_win_rate95=ci(rates),
                mean_portfolio_daily_excess_vs_always_long_bps95=ci(differences),
                independent_confirmation=False)


def break_even_bps(sessions, *, entry='09:32', arm='GAP_DOWN_LONG'):
    # Solve mean TRADE return ==0; no financing, commission, tax, or borrow costs.
    selected = [r for r in sessions if direction(r['gap'], arm)]
    if not selected:
        return None
    mean = lambda b: statistics.mean(trade_return(r['minutes'][entry]['o'],
                   r['minutes']['10:00']['o'], direction(r['gap'], arm), b) for r in selected)
    if mean(0) <= 0:
        return 0.
    lo, hi = 0., 1000.
    if mean(hi) > 0:
        return None
    for _ in range(60):
        mid = (lo+hi)/2
        if mean(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo+hi)/2


def groups(ledger):
    years = sorted({r['date'][:4] for r in ledger})
    result = {year: summarize([r for r in ledger if r['date'].startswith(year)]) for year in years}
    partitions = dict(EARLY=(2016, 2020), MIDDLE=(2021, 2023), LATE=(2024, 2025))
    for name, (start, end) in partitions.items():
        rows = [r for r in ledger if start <= int(r['date'][:4]) <= end]
        if rows:
            result[name] = summarize(rows)
    return result


def diagnostic_buckets(ledger):
    result = {}
    edges = [-math.inf, -.03, -.01, 0, .01, .03, math.inf]
    for lo, hi in zip(edges, edges[1:]):
        rows = [r for r in ledger if lo <= r['gap'] < hi]
        if rows:
            result[f'[{lo},{hi})'] = summarize(rows)
    return result
