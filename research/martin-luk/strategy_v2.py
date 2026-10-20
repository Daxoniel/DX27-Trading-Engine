"""MLP2 source-mapping correction. Research adaptation, never broker transport.

MLP1 remains frozen. Thresholds and execution conventions remain our choices.
"""
from dataclasses import asdict
from datetime import timedelta
from statistics import mean
from copy import deepcopy
from strategy import Rules, stamp, seal, validate_bars, ema
from strategy import entry_signal as legacy_entry_signal


def scan(snapshot, rules=Rules(version='MLP2')):
    """Premarket snapshot must include the complete input universe, not winners.

    A caller-provided exchange schedule is mandatory (includes early closes).
    Classifications and membership must have been known at snapshot time.
    Missing/delisted names must remain in historical input universes.
    """
    asof = stamp(snapshot['asof'])
    opening, closing = (stamp(snapshot[k]) for k in ('session_open', 'session_close'))
    if not asof < opening < closing or closing - opening > timedelta(hours=7):
        raise ValueError('PREMARKET_AND_EXCHANGE_SCHEDULE_REQUIRED')
    if snapshot['universe_kind'] not in ('POINT_IN_TIME', 'DIAGNOSTIC_SURVIVOR_BIASED', 'SYNTHETIC'):
        raise ValueError('UNIVERSE_PROVENANCE_REQUIRED')
    if (snapshot['price_basis'] != 'ASOF_SPLIT_ADJUSTED'
            or stamp(snapshot['adjustment_asof']) > asof):
        raise ValueError('POINT_IN_TIME_PRICE_BASIS_REQUIRED')
    eligible, audit, seen = [], [], set()
    leaders = {}
    for asset in snapshot['assets']:
        symbol = asset['symbol']
        if symbol in seen:
            raise ValueError('DUPLICATE_SYMBOL')
        seen.add(symbol)
        if not symbol or not asset['sector'] or stamp(asset['known_at']) > asof:
            raise ValueError('ASSET_METADATA_NOT_KNOWN')
        bars = asset['daily']
        validate_bars(bars, asof)
        if not bars or stamp(bars[-1]['end']) != stamp(snapshot['previous_session_close']):
            raise ValueError('STALE_DAILY_HISTORY')
        schedule=[tuple(x) for x in snapshot['history_schedule']]
        if len(bars)>len(schedule) or [(b['start'],b['end']) for b in bars] != schedule[-len(bars):]:
            raise ValueError('INCOMPLETE_DAILY_SCHEDULE')
        reason = None
        if asset['kind'] != 'US_COMMON_STOCK' or not asset['tradable']:
            reason = 'NOT_TRADABLE_COMMON_STOCK'
        elif len(bars) < rules.minimum_history:
            reason = 'INSUFFICIENT_HISTORY'
        if reason:
            audit.append(dict(symbol=symbol, reason=reason)); continue
        cs = [b['close'] for b in bars]
        e9, e21, e50 = (ema(cs, n) for n in (9,21,50))
        adr = mean((b['high']-b['low'])/b['close'] for b in bars[-20:])
        liquidity = mean(b['close']*b['volume'] for b in bars[-20:])
        momentum = max(cs[-1]/cs[-64]-1, cs[-1]/cs[-127]-1)
        # Five-session groups are a frozen rolling structure proxy, not calendar weeks.
        higher_low = min(b['low'] for b in bars[-5:]) > min(b['low'] for b in bars[-10:-5])
        if cs[-1] < rules.min_price or liquidity < rules.min_dollar_volume or adr < rules.min_adr:
            reason = 'PRICE_LIQUIDITY_OR_ADR'
        elif not (e9[-1] > e21[-1] > e50[-1] and e21[-1] > e21[-6] and cs[-1] > e21[-1]):
            reason = 'NOT_LEADING_UPTREND'
        elif momentum < rules.min_momentum or not higher_low:
            reason = 'MOMENTUM_OR_STRUCTURE'
        if reason:
            audit.append(dict(symbol=symbol, reason=reason)); continue
        # Sector leadership is measured BEFORE support proximity/entry setup.
        leaders[asset['sector']] = leaders.get(asset['sector'], 0) + 1
        anchor = max(range(len(bars)-60, len(bars)), key=lambda i: bars[i]['high'])
        anchored = bars[anchor:]
        avwap = sum((b['high']+b['low']+b['close'])/3*b['volume'] for b in anchored)/sum(b['volume'] for b in anchored)
        levels = dict(ema9=e9[-1], ema21=e21[-1], avwap=avwap)
        # Individual supports are alternatives; confluence is not mandatory.
        nearby = {k:v for k,v in levels.items() if v <= cs[-1] <= v*(1+adr)}
        if not nearby:
            audit.append(dict(symbol=symbol, reason='NO_NEARBY_SUPPORT')); continue
        support = max(nearby.values())
        eligible.append(dict(symbol=symbol, sector=asset['sector'], adr=adr,
            dollar_volume=liquidity, momentum=momentum, support=support,
            support_indicators=sorted(nearby), support_levels=nearby, anchor_start=bars[anchor]['start'], trail=e9[-1]))
    peers = leaders
    watchlist = []
    for c in eligible:
        if peers[c['sector']] >= rules.min_sector_peers:
            watchlist.append(c)
        else:
            audit.append(dict(symbol=c['symbol'], reason='NO_STRONG_SECTOR_PEERS'))
    watchlist.sort(key=lambda c:(-c['momentum'],-c['dollar_volume'],c['symbol']))
    return dict(version=rules.version, rules=asdict(rules), input_sha256=seal(snapshot),
        asof=snapshot['asof'], session_open=snapshot['session_open'],
        session_close=snapshot['session_close'], universe_kind=snapshot['universe_kind'],
        watchlist=watchlist, rejected=audit, sector_leaders=leaders, execution_enabled=False)


def entry_signal(plan, symbol, bars, asof):
    """Test each predetermined daily support, highest first; one intent per name.

    No support is chosen by future profitability. The existing recovery and risk
    checks remain unchanged, including the conservative one-intent/session cap.
    """
    candidate = next((c for c in plan['watchlist'] if c['symbol'] == symbol), None)
    if candidate is None:
        return legacy_entry_signal(plan, symbol, bars, asof)
    for name, level in sorted(candidate['support_levels'].items(), key=lambda x:(-x[1], x[0])):
        trial = deepcopy(plan)
        target = next(c for c in trial['watchlist'] if c['symbol'] == symbol)
        target['support'] = level
        signal = legacy_entry_signal(trial, symbol, bars, asof)
        if signal:
            signal['client_order_id'] = signal['client_order_id'].replace('mlp1-', 'mlp2-', 1)
            signal['plan_sha256'] = seal(plan)
            signal['selected_support'] = name
            return signal
    return None
