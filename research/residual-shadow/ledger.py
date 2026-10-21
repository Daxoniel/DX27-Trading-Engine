"""Offline fractional adjusted-price ledger. No network or broker-order interface."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from pathlib import Path
import re


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return sha256(canonical(value)).hexdigest()


def number(value, positive=False):
    result = Decimal(str(value))
    if not result.is_finite() or (result <= 0 if positive else result < 0):
        raise ValueError('INVALID_NUMBER')
    return result


def receipt(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('INVALID_RECEIPT_HASH')


def initialize(sessions, rebalance_days, bps, capital='100000'):
    if not sessions or sessions != sorted(set(sessions)) or not set(rebalance_days) <= set(sessions):
        raise ValueError('INVALID_SCHEDULE')
    for day in sessions:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError('INVALID_SESSION')
    if bps not in (5, 25):
        raise ValueError('UNREGISTERED_COST')
    capital = str(number(capital, True))
    return dict(version='RS1', mode='OFFLINE_REHEARSAL_ONLY', sessions=sessions,
                rebalance_days=sorted(set(rebalance_days)), bps=bps, cursor=0,
                cash=capital, units={}, initial=capital, peak=capital, drawdown='0',
                costs='0', last_nav=capital, halt=None, marks=0, rebalances=0)


def weights(targets):
    if not isinstance(targets, list) or len(targets) > 10:
        raise ValueError('INVALID_TARGETS')
    sectors = {}; result = {}
    for row in targets:
        symbol, sector = row['symbol'], row['sector']
        if not symbol or symbol == 'SOXL' or symbol in result or not sector:
            raise ValueError('INVALID_TARGET_IDENTITY')
        sectors[sector] = sectors.get(sector, 0) + 1
        if sectors[sector] > 2:
            raise ValueError('SECTOR_CAP')
        result[symbol] = Decimal('.01')
    return dict(sorted(result.items()))


def advance(previous, request):
    with localcontext() as context:
        context.prec = 45
        state = deepcopy(previous)
        if state['halt'] or state['cursor'] >= len(state['sessions']):
            raise ValueError('TERMINAL_LEDGER')
        day = request['date']
        if day != state['sessions'][state['cursor']]:
            raise ValueError('MISSING_OR_OUT_OF_ORDER_SESSION')
        receipt(request['source_sha256'])
        prices = request['closes']
        if 'SOXL' in prices:
            raise ValueError('RESERVED_SYMBOL')
        targets = request.get('targets')
        scheduled = day in state['rebalance_days']
        if targets is not None and not scheduled:
            raise ValueError('UNSCHEDULED_REBALANCE')
        if targets is not None:
            receipt(request['rank_plan_sha256'])
            target_weights = weights(targets)
        else:
            target_weights = {}
        required = set(state['units']) | set(target_weights)
        invalid = []
        for symbol in sorted(required):
            try:
                number(prices.get(symbol), True)
            except (ValueError, ArithmeticError):
                invalid.append(symbol)
        if invalid or (scheduled and targets is None):
            state['halt'] = dict(date=day, code='PRICE_MISSING_OR_INVALID' if invalid else 'RANK_PLAN_MISSING',
                                 symbols=invalid)
            return state, dict(date=day, status='HALTED', nav=None, cost='0')
        old_values = {s: Decimal(q)*number(prices[s], True) for s,q in sorted(state['units'].items())}
        cash = Decimal(state['cash']); before = cash + sum(old_values.values())
        cost = Decimal(0); values = old_values
        if scheduled:
            names = sorted(set(old_values) | set(target_weights))
            rate = Decimal(state['bps'])/10000
            lo, hi = Decimal(0), before
            for _ in range(180):
                after = (lo+hi)/2
                turnover = sum(abs(target_weights.get(s, 0)*after-old_values.get(s, 0)) for s in names)
                if after+rate*turnover > before:
                    hi = after
                else:
                    lo = after
            after = (lo+hi)/2
            values = {s:w*after for s,w in target_weights.items()}
            cost = rate*sum(abs(values.get(s, 0)-old_values.get(s, 0)) for s in names)
            cash = before-cost-sum(values.values())
            if cash < 0:
                raise ValueError('NEGATIVE_CASH')
            state['units'] = {s:str(v/number(prices[s], True)) for s,v in values.items()}
            state['rebalances'] += 1
        nav = cash+sum(values.values()); peak = max(Decimal(state['peak']), nav)
        state.update(cash=str(cash), costs=str(Decimal(state['costs'])+cost), peak=str(peak),
                     drawdown=str(max(Decimal(state['drawdown']), 1-nav/peak)),
                     last_nav=str(nav), cursor=state['cursor']+1, marks=state['marks']+1)
        return state, dict(date=day, status='MARKED', before=str(before), nav=str(nav),
                           gross=str(sum(values.values())), cash=str(cash), cost=str(cost))


class Journal:
    """A crash/partial write or concurrent append fails replay; never repairs history."""
    def __init__(self, root):
        self.root = Path(root)

    def _write(self, index, event):
        event['sha256'] = digest(event)
        with (self.root/f'{index:06d}.json').open('xb') as stream:
            stream.write(canonical(event)+b'\n')
        return event

    def create(self, state):
        self.root.mkdir(parents=True, exist_ok=False)
        # Validate no externally supplied holdings or altered initial state.
        expected = initialize(state['sessions'], state['rebalance_days'], state['bps'], state['initial'])
        if state != expected:
            raise ValueError('INVALID_INITIAL_STATE')
        return self._write(0, dict(previous=None, operation='INIT', state=state))

    def replay(self):
        files = sorted(self.root.iterdir())
        if not files or [p.name for p in files] != [f'{i:06d}.json' for i in range(len(files))]:
            raise ValueError('BROKEN_SEQUENCE')
        prior = None; state = None
        for i,path in enumerate(files):
            event = json.loads(path.read_bytes()); seal = event.pop('sha256')
            if digest(event) != seal or event['previous'] != prior:
                raise ValueError('BROKEN_HASH_CHAIN')
            if i == 0:
                s = event['state']
                expected = initialize(s['sessions'], s['rebalance_days'], s['bps'], s['initial'])
                if event['operation'] != 'INIT' or s != expected:
                    raise ValueError('INVALID_INITIAL_STATE')
                state = expected
            else:
                if event['operation'] != 'ADVANCE':
                    raise ValueError('INVALID_OPERATION')
                state, mark = advance(state, event['request'])
                if event['state'] != state or event['mark'] != mark:
                    raise ValueError('REPLAY_STATE_MISMATCH')
            prior = seal
        return state, prior, len(files)

    def append(self, request):
        state, prior, index = self.replay()
        state, mark = advance(state, request)
        return self._write(index, dict(previous=prior, operation='ADVANCE', request=request,
                                       mark=mark, state=state))
