"""MLP1: cross-sectional, long-only pullback adaptation; no broker transport.

Every threshold is our frozen implementation choice, not a claimed Luk rule.
Inputs are completed, unadjusted bars in a single corporate-action regime.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from hashlib import sha256
import json
import math
from statistics import mean


def stamp(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.utcoffset() != timedelta(0):
        raise ValueError('UTC_TIMESTAMP_REQUIRED')
    return t


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def seal(value):
    return sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class Rules:
    version: str = 'MLP1'
    minimum_history: int = 160
    min_price: float = 5.0
    min_dollar_volume: float = 20_000_000
    min_adr: float = .05
    min_momentum: float = .30
    min_sector_peers: int = 2
    support_tolerance: float = .005
    max_stop: float = .025
    min_stop: float = .003
    risk_per_trade: float = .005
    max_position: float = .25
    max_sector: float = .50
    max_gross: float = 1.0
    max_open_risk: float = .02
    partial_r: float = 3.0
    partial_fraction: float = .15
    adverse_bps: float = 5.0

    def __post_init__(self):
        numbers = {k:v for k,v in asdict(self).items() if k != 'version'}
        if any(type(v) not in (int,float) or not math.isfinite(v) or v <= 0 for v in numbers.values()):
            raise ValueError('INVALID_RULES')
        if not (self.min_stop < self.max_stop < 1 and self.max_position <= self.max_sector <= self.max_gross <= 1
                and self.risk_per_trade <= self.max_open_risk < 1 and self.partial_fraction < 1):
            raise ValueError('INCONSISTENT_RISK_LIMITS')


def validate_bars(bars, asof, minutes=None):
    previous = None
    for b in bars:
        start, end, available = (stamp(b[k]) for k in ('start', 'end', 'available_at'))
        if not start < end <= available <= asof:
            raise ValueError('INCOMPLETE_OR_FUTURE_BAR')
        if previous is not None and start < previous:
            raise ValueError('OVERLAPPING_OR_UNSORTED_BARS')
        if minutes and end - start != timedelta(minutes=minutes):
            raise ValueError('WRONG_BAR_INTERVAL')
        previous = end
        o, h, l, c, v = (b[k] for k in ('open', 'high', 'low', 'close', 'volume'))
        if not all(type(x) in (int, float) and math.isfinite(x) and x > 0 for x in (o,h,l,c,v)):
            raise ValueError('INVALID_PRICE_OR_VOLUME')
        if not l <= min(o,c) <= max(o,c) <= h:
            raise ValueError('INVALID_OHLC')


def ema(values, period):
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + 2 / (period + 1) * (v - out[-1]))
    return out


def scan(snapshot, rules=Rules()):
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
        # Highest high of a fixed, already-known 60-session window. No future pivots.
        anchor = max(range(len(bars)-60, len(bars)), key=lambda i: bars[i]['high'])
        anchored = bars[anchor:]
        avwap = sum((b['high']+b['low']+b['close'])/3*b['volume'] for b in anchored)/sum(b['volume'] for b in anchored)
        levels = dict(ema9=e9[-1], ema21=e21[-1], avwap=avwap)
        # Cluster distinct indicators; retain a reproducible nearest pair.
        pairs = [(abs(a-b)/max(a,b), ka, kb, (a+b)/2)
                 for ka,a in levels.items() for kb,b in levels.items() if ka < kb]
        distance, a, b, support = min(pairs)
        if distance > rules.support_tolerance or cs[-1] < support or cs[-1]/support-1 > adr:
            audit.append(dict(symbol=symbol, reason='NO_NEARBY_SUPPORT_CONFLUENCE')); continue
        # Reset only after a completed close crosses above EMA21. Subsequent touches
        # are episodes, not every consecutive touch bar. V1 rejects a prior episode.
        crosses = [i for i in range(1,len(cs)) if cs[i-1] <= e21[i-1] and cs[i] > e21[i]]
        start = crosses[-1] if crosses else len(cs)-20
        touches = [bars[i]['low'] <= e21[i]*(1+rules.support_tolerance) for i in range(start+1,len(cs))]
        episodes = sum(t and (i == 0 or not touches[i-1]) for i,t in enumerate(touches))
        if episodes:
            audit.append(dict(symbol=symbol, reason='PRIOR_PULLBACK_EPISODE')); continue
        eligible.append(dict(symbol=symbol, sector=asset['sector'], adr=adr,
            dollar_volume=liquidity, momentum=momentum, support=support,
            support_indicators=[a,b], anchor_start=bars[anchor]['start'], trail=e9[-1]))
    peers = {c['sector']:sum(x['sector']==c['sector'] for x in eligible) for c in eligible}
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
        watchlist=watchlist, rejected=audit, execution_enabled=False)


def entry_signal(plan, symbol, bars, asof):
    """At a completed 5m close; intent can execute only AFTER available_at.

    Morning flush + recovery above the prior bar high. One intent/name/session;
    stop follows observed support failure, not a fabricated fixed-price fill.
    """
    rules = Rules(**plan['rules'])
    now, opening, closing = stamp(asof), stamp(plan['session_open']), stamp(plan['session_close'])
    validate_bars(bars, now, minutes=5)
    candidate = next((c for c in plan['watchlist'] if c['symbol']==symbol), None)
    if now <= opening or stamp(plan['asof']) >= now:
        raise ValueError('PLAN_OR_SIGNAL_CLOCK_CONFLICT')
    if not candidate or len(bars) < 3 or now > min(opening+timedelta(hours=2), closing):
        return None
    if stamp(bars[0]['start']) != opening:
        raise ValueError('OPENING_BARS_MISSING')
    if any(stamp(bars[i]['start']) != stamp(bars[i-1]['end']) for i in range(1,len(bars))):
        raise ValueError('INTRADAY_GAP')
    available=stamp(bars[-1]['available_at'])
    if now-available > timedelta(seconds=60) or now >= closing:
        return None
    last = bars[-1]
    support = candidate['support']
    prior = bars[-3:-1]
    if not (min(b['low'] for b in prior) <= support*(1+rules.support_tolerance)
            and min(b['low'] for b in prior) >= support*(1-rules.max_stop)
            and last['close'] > max(support,bars[-2]['high']) and last['close'] > last['open']):
        return None
    stop = min(b['low'] for b in bars[-3:])
    limit = math.ceil(last['close']*(1+rules.adverse_bps/10_000)*100)/100
    distance = (limit-stop)/limit
    if not rules.min_stop <= distance <= min(rules.max_stop,candidate['adr']/2):
        return None
    key = f"{rules.version}:{plan['session_open']}:{symbol}:FIRST_PULLBACK"
    return dict(signal_key=key, client_order_id='mlp1-'+sha256(key.encode()).hexdigest()[:32],
        symbol=symbol, sector=candidate['sector'], side='buy', signal_at=bars[-1]['available_at'],
        limit_price=limit, stop_price=stop, expires_at=(available+timedelta(minutes=5)).isoformat(),
        plan_sha256=seal(plan), evidence_sha256=seal(bars), execution_enabled=False)


def allocate(signals, equity, cash, positions, rules=Rules()):
    """Positions include outstanding reservations; caller reconciles broker fills.

    Enforce risk and concentration jointly, in deterministic watchlist order.
    Market values are current marks. Pending entries reserve limit * quantity.
    """
    if not all(math.isfinite(v) and v >= 0 for v in (equity,cash)) or equity <= 0:
        raise ValueError('INVALID_ACCOUNT')
    gross, risk, sectors, held = 0.,0.,{},set()
    for p in positions:
        q, mark, stop = p['quantity'], p['mark'], p['stop_price']
        if type(q) is not int or q <= 0 or not 0 < stop <= mark or not all(math.isfinite(x) for x in (mark,stop)):
            raise ValueError('INVALID_POSITION_OR_RESERVATION')
        gross += q*mark; risk += q*(mark-stop)
        if p.get('pending',False):
            cash -= q*mark
        sectors[p['sector']] = sectors.get(p['sector'],0)+q*mark
        held.add(p['symbol'])
    accepted, rejected, keys = [],[],set()
    for s in signals:
        price, stop = s['limit_price'],s['stop_price']
        if not all(math.isfinite(x) for x in (price,stop)) or not 0 < stop < price:
            raise ValueError('INVALID_SIGNAL_RISK')
        if s['signal_key'] in keys or s['symbol'] in held:
            rejected.append(dict(symbol=s['symbol'],reason='DUPLICATE_OR_HELD')); continue
        keys.add(s['signal_key'])
        per_share = price-stop
        capacities = [equity*rules.risk_per_trade/per_share, equity*rules.max_position/price,
            (equity*rules.max_gross-gross)/price,
            (equity*rules.max_sector-sectors.get(s['sector'],0))/price,
            (equity*rules.max_open_risk-risk)/per_share,cash/price]
        quantity = math.floor(min(capacities))
        if quantity <= 0:
            rejected.append(dict(symbol=s['symbol'],reason='PORTFOLIO_CAPACITY')); continue
        intent = dict(s,quantity=quantity,planned_risk=quantity*per_share,
            type='limit',time_in_force='day',extended_hours=False,
            protective_stop_required=True, endpoint='https://paper-api.alpaca.markets')
        accepted.append(intent)
        notional = quantity*price
        gross += notional; cash -= notional; risk += quantity*per_share
        sectors[s['sector']] = sectors.get(s['sector'],0)+notional
        held.add(s['symbol'])
    return dict(intents=accepted,rejected=rejected,reserved_gross=gross,
        reserved_risk=risk,remaining_cash=cash,execution_enabled=False)


def manage(position, bar, trail, session_close, rules=Rules()):
    """Replay fill convention, never a broker fill claim.

    Position = entry, initial_stop, stop_price, quantity, initial_quantity,
    partial_taken, exit_pending. Ambiguous stop/target bars process stop first.
    Updated completed-daily EMA supplied by caller; trailing exit is pending
    until next observed bar open, including overnight gaps.
    """
    p = dict(position)
    if not (0 < p['initial_stop'] < p['entry'] and 0 < p['stop_price']
            and type(p['quantity']) is int and 0 < p['quantity'] <= p['initial_quantity']
            and math.isfinite(trail) and trail > 0):
        raise ValueError('INVALID_MANAGED_POSITION')
    validate_bars([bar],stamp(bar['available_at']))
    if stamp(bar['start']) < stamp(p.get('last_bar_end',p['filled_at'])):
        raise ValueError('MANAGEMENT_BAR_PRECEDES_FILL_OR_WAS_ALREADY_APPLIED')
    p['last_bar_end']=bar['end']
    cost = rules.adverse_bps/10_000
    if p['exit_pending'] or bar['low'] <= p['stop_price']:
        price = bar['open'] if p['exit_pending'] else min(bar['open'],p['stop_price'])
        return dict(position=None, fills=[dict(side='sell',quantity=p['quantity'],
            price=price*(1-cost),reason='TRAIL_NEXT_OPEN' if p['exit_pending'] else 'STOP')])
    fills = []
    target = p['entry']+rules.partial_r*(p['entry']-p['initial_stop'])
    if not p['partial_taken'] and bar['high'] >= target:
        q = math.floor(p['initial_quantity']*rules.partial_fraction)
        if q and q < p['quantity']:
            fills.append(dict(side='sell',quantity=q,price=target*(1-cost),reason='PARTIAL_3R'))
            p['quantity'] -= q
        p['partial_taken'] = True
    p['exit_pending'] = stamp(bar['end']) == stamp(session_close) and bar['close'] < trail
    return dict(position=p,fills=fills)
