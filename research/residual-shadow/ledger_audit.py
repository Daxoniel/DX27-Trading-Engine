"""Independent conservation/target audit: never calls ledger solver or advance."""
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from pathlib import Path


def audit(root):
    with localcontext() as ctx:
        ctx.prec = 65
        files = sorted(Path(root).glob('*.json'))
        if [x.name for x in files] != [f'{i:06d}.json' for i in range(len(files))] or not files:
            raise ValueError('AUDIT_SEQUENCE')
        first = json.loads(files[0].read_bytes()); config = first['state']
        cash = Decimal(config['initial']); units = {}; costs = Decimal(0); peak = cash; dd = Decimal(0)
        days = config['sessions']; schedule = config['rebalance_days']; previous = None
        marks = 0; rebalances = 0; halted = False
        def close(left, right):
            if abs(Decimal(str(left))-Decimal(str(right))) > Decimal('1e-20'):
                raise ValueError('INDEPENDENT_ACCOUNT_MISMATCH')
        for index,path in enumerate(files):
            event = json.loads(path.read_bytes()); seal = event.pop('sha256')
            encoded = json.dumps(event, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            if sha256(encoded).hexdigest() != seal or event['previous'] != previous:
                raise ValueError('AUDIT_HASH_CHAIN')
            previous = seal
            if index == 0:
                if event['operation'] != 'INIT' or config['units'] or Decimal(config['cash']) != cash:
                    raise ValueError('AUDIT_INITIAL_STATE')
                continue
            if halted or event['operation'] != 'ADVANCE':
                raise ValueError('AUDIT_AFTER_TERMINAL')
            request = event['request']; day = request['date']; state = event['state']; mark = event['mark']
            if marks >= len(days) or day != days[marks]:
                raise ValueError('AUDIT_CALENDAR')
            targets = request.get('targets'); scheduled = day in schedule
            if targets is not None and not scheduled:
                raise ValueError('AUDIT_UNSCHEDULED')
            names = set(units) | {r['symbol'] for r in targets or []}
            missing = []
            for symbol in sorted(names):
                try:
                    price = Decimal(str(request['closes'].get(symbol)))
                    if not price.is_finite() or price <= 0:
                        missing.append(symbol)
                except ArithmeticError:
                    missing.append(symbol)
            if missing or (scheduled and targets is None):
                code = 'PRICE_MISSING_OR_INVALID' if missing else 'RANK_PLAN_MISSING'
                if state['halt'] != dict(date=day, code=code, symbols=missing) or mark['nav'] is not None:
                    raise ValueError('AUDIT_INVALID_HALT')
                close(state['cash'], cash)
                if set(state['units']) != set(units):
                    raise ValueError('AUDIT_HALT_INVENTORY')
                for symbol,q in units.items(): close(state['units'][symbol], q)
                if state['cursor'] != marks: raise ValueError('AUDIT_HALT_CURSOR')
                halted = True
                continue
            values = {s:q*Decimal(str(request['closes'][s])) for s,q in units.items()}
            before = cash+sum(values.values()); cost = Decimal(mark['cost'])
            if scheduled:
                if len(targets)>10 or len({r['symbol'] for r in targets}) != len(targets):
                    raise ValueError('AUDIT_TARGET_COUNT')
                sector_counts = {}
                for row in targets:
                    sector_counts[row['sector']] = sector_counts.get(row['sector'],0)+1
                    if row['symbol']=='SOXL' or not row['sector'] or sector_counts[row['sector']] > 2:
                        raise ValueError('AUDIT_TARGET_SECTOR')
                # Independently infer post-cost equity from cash conservation.
                after = before-cost
                new_values = {r['symbol']:after/100 for r in targets}
                expected_cost = Decimal(config['bps'])/10000*sum(
                    abs(new_values.get(s,0)-values.get(s,0)) for s in set(values)|set(new_values))
                close(expected_cost,cost)
                cash = after-sum(new_values.values())
                units = {s:v/Decimal(str(request['closes'][s])) for s,v in new_values.items()}
                values = new_values; rebalances += 1; costs += cost
            elif cost != 0:
                raise ValueError('AUDIT_UNEXPECTED_COST')
            nav = cash+sum(values.values()); peak=max(peak,nav); dd=max(dd,1-nav/peak); marks+=1
            if cash<0 or state['cursor']!=marks or state['marks']!=marks or state['rebalances']!=rebalances:
                raise ValueError('AUDIT_FUNDING_OR_COUNT')
            if state['halt'] is not None or set(state['units']) != set(units):
                raise ValueError('AUDIT_INVENTORY')
            for s,q in units.items(): close(q,state['units'][s])
            for key,actual in [('cash',cash),('costs',costs),('peak',peak),('drawdown',dd),('last_nav',nav)]:
                close(state[key],actual)
            for key,actual in [('before',before),('nav',nav),('gross',sum(values.values())),('cash',cash)]:
                close(mark[key],actual)
        return dict(status='PASS', independently_checked_marks=marks,
                    rebalances=rebalances, halted=halted, complete=not halted and marks==len(days),
                    source_authenticity_verified=False, broker_accounting_verified=False, orders=0)
