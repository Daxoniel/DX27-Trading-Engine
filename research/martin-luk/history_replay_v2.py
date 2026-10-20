"""Chronological, shared-cash MLP2 OHLC replay; never sends broker orders.

Bar-open entries are conditional execution proxies. Accounting completeness is
separate from whether the cohort, data or fill model establish investment edge.
"""
from copy import deepcopy
from datetime import timedelta
import math

from strategy import Rules, allocate, manage, stamp, validate_bars
from strategy_v2 import entry_signal


class Replay:
    def __init__(self, cash=100_000, rules=Rules(version='MLP2'), gap_policy='HALT'):
        if not math.isfinite(cash) or cash<=0:raise ValueError('INVALID_INITIAL_CASH')
        if gap_policy not in ('HALT','OBSERVED_ONLY'):raise ValueError('INVALID_GAP_POLICY')
        self.gap_policy=gap_policy
        self.rules=rules;self.initial_cash=cash;self.cash=cash
        self.positions={};self.pending={};self.receivables=[]
        self.fills=[];self.closed=[];self.nav=[];self.events=[]
        self.seen=set();self.action_ids=set();self.halt=None
        self.last_session=None;self.trade_number=0

    def equity(self):
        return self.cash+sum(p['quantity']*p['mark'] for p in self.positions.values())+sum(r['amount'] for r in self.receivables)

    def stop(self,code,**details):
        self.halt=dict(code=code,**details)
        self.events.append(dict(kind='HALT',**self.halt))

    def sell(self,symbol,fill,at):
        p=self.positions[symbol];q=fill['quantity'];proceeds=q*fill['price']
        self.cash+=proceeds;p['proceeds']+=proceeds
        self.fills.append(dict(symbol=symbol,trade_id=p['trade_id'],at=at,**fill))

    def actions(self,day,actions):
        """Mechanical entitlements only; never filter trades using future actions."""
        for a in actions:
            if a['date']!=day or a['id'] in self.action_ids:continue
            self.action_ids.add(a['id']);symbol=a['symbol'];p=self.positions.get(symbol)
            if not p:continue
            if a['kind']=='split':
                ratio=a['ratio'];q=p['quantity']*ratio;iq=p['initial_quantity']*ratio
                if not math.isfinite(ratio) or ratio<=0:raise ValueError('INVALID_SPLIT')
                if abs(q-round(q))>1e-8 or abs(iq-round(iq))>1e-8:
                    self.stop('UNRESOLVED_FRACTIONAL_ENTITLEMENT',symbol=symbol,date=day);return
                p['quantity']=round(q);p['initial_quantity']=round(iq)
                for key in ('entry','initial_stop','stop_price','mark'):p[key]/=ratio
                self.events.append(dict(kind='SPLIT',symbol=symbol,date=day,ratio=ratio,trade_id=p['trade_id']))
            elif a['kind']=='cash_dividend':
                amount=p['quantity']*a['rate'];p['dividends']+=amount
                self.receivables.append(dict(amount=amount,payable_date=a['payable_date'],trade_id=p['trade_id']))
                self.events.append(dict(kind='DIVIDEND_ACCRUED',symbol=symbol,date=day,amount=amount,trade_id=p['trade_id']))
            else:
                self.stop('UNRESOLVED_CORPORATE_ACTION',symbol=symbol,date=day,action_kind=a['kind']);return
        payable=[r for r in self.receivables if r['payable_date']<=day]
        self.cash+=sum(r['amount'] for r in payable)
        self.events.extend(dict(kind='DIVIDEND_PAID',date=day,amount=r['amount'],trade_id=r['trade_id']) for r in payable)
        self.receivables=[r for r in self.receivables if r['payable_date']>day]

    def session(self,plan,bars,daily_exit,actions=()):
        if self.halt:raise ValueError('HALTED_REPLAY_CANNOT_CONTINUE')
        opening,closing=stamp(plan['session_open']),stamp(plan['session_close'])
        day=opening.date().isoformat()
        if self.last_session and day<=self.last_session:raise ValueError('SESSION_ORDER_REQUIRED')
        if plan['rules']!=self.rules.__dict__:raise ValueError('FROZEN_RULES_MISMATCH')
        self.last_session=day
        self.actions(day,actions)
        if self.halt:return
        for symbol,p in self.positions.items():
            if symbol not in daily_exit:
                self.stop('HELD_POSITION_DAILY_HISTORY_MISSING',symbol=symbol,date=day);return
            # A previously triggered liquidation persists through a whole day
            # with no observable bars; a later EMA recovery cannot cancel it.
            p['exit_pending']=p.get('exit_pending',False) or bool(daily_exit[symbol])
        universe=set(c['symbol'] for c in plan['watchlist'])|set(self.positions)
        indexed={};prefix={s:[] for s in universe};prefix_valid={s:True for s in universe}
        for s in universe:
            rows=bars.get(s,[])
            if any(not opening<=stamp(b['start'])<stamp(b['end'])<=closing for b in rows):
                raise ValueError('BAR_OUTSIDE_REGULAR_SESSION')
            indexed[s]={stamp(b['start']):b for b in rows}
            if len(indexed[s])!=len(rows):raise ValueError('DUPLICATE_SESSION_BAR')
        t=opening
        while t<closing:
            # First resolve already-reserved entries, using only an observable open
            # strictly after the completed signal became available.
            for s,intent in list(self.pending.items()):
                if t>=stamp(intent['expires_at']):
                    self.events.append(dict(kind='ENTRY_EXPIRED',symbol=s,at=t.isoformat()))
                    del self.pending[s];continue
                if t<=stamp(intent['signal_at']):continue
                b=indexed[s].get(t)
                if b is None:continue
                if not math.isfinite(b['open']) or b['open']<=0:
                    self.stop('ENTRY_OPEN_INVALID',symbol=s,at=t.isoformat());return
                price=b['open']*(1+self.rules.adverse_bps/10_000)
                del self.pending[s]
                if price>intent['limit_price']:
                    self.events.append(dict(kind='NO_OPEN_FILL_WITHIN_LIMIT',symbol=s,at=t.isoformat()));continue
                q=intent['quantity'];notional=q*price
                if notional>self.cash+1e-8:raise ValueError('CASH_ACCOUNTING_OVERRUN')
                self.cash-=notional;self.trade_number+=1
                p=dict(entry=price,initial_stop=intent['stop_price'],stop_price=intent['stop_price'],
                    quantity=q,initial_quantity=q,partial_taken=False,exit_pending=False,
                    filled_at=t.isoformat(),mark=price,sector=intent['sector'],
                    trade_id=self.trade_number,entry_notional=notional,proceeds=0.,dividends=0.)
                self.positions[s]=p
                self.fills.append(dict(symbol=s,trade_id=p['trade_id'],at=t.isoformat(),
                    side='buy',quantity=q,price=price,reason='NEXT_OBSERVABLE_OPEN_PROXY',
                    signal_at=intent['signal_at'],expires_at=intent['expires_at'],
                    limit_price=intent['limit_price'],reference_open=b['open']))
                # A gap already below protection is an immediate roundtrip, not an
                # optimistic cancellation after learning the opening price.
                if price<=p['stop_price']:
                    self.sell(s,dict(side='sell',quantity=q,price=b['open']*(1-self.rules.adverse_bps/10_000),
                        reason='ENTRY_ALREADY_BELOW_PROTECTION'),t.isoformat())
                    self.close_trade(s,t.isoformat())
            for s in sorted(universe):
                b=indexed[s].get(t)
                if b is None:
                    prefix_valid[s]=False
                    if s in self.positions:
                        if self.gap_policy=='HALT':
                            self.stop('HELD_POSITION_BAR_MISSING',symbol=s,at=t.isoformat());return
                        self.events.append(dict(kind='HELD_BAR_UNOBSERVED',symbol=s,at=t.isoformat()))
                    continue
                try:
                    validate_bars([b],t+timedelta(minutes=5,seconds=1),minutes=5)
                except ValueError:
                    prefix_valid[s]=False
                    if s in self.positions:
                        self.stop('HELD_POSITION_BAR_INVALID',symbol=s,at=t.isoformat());return
                    self.events.append(dict(kind='INVALID_CANDIDATE_BAR',symbol=s,at=t.isoformat()))
                    continue
                prefix[s].append(b)
                if s not in self.positions:continue
                p=self.positions[s]
                result=manage(p,b,1e-300,plan['session_close'],self.rules)
                # Frozen manage() uses adverse OHLC prices and stop-first ordering.
                for fill in result['fills']:
                    at=b['start'] if fill['reason']=='TRAIL_NEXT_OPEN' else b['available_at']
                    self.sell(s,fill,at)
                if result['position'] is None:self.close_trade(s,at)
                else:
                    updated=result['position'];updated['proceeds']=p['proceeds']
                    updated['mark']=b['close'];self.positions[s]=updated
            # Batch simultaneous signals in frozen watchlist order; no bar t+1
            # enters position sizing, screening or current-bar signal formation.
            signals=[]
            now=t+timedelta(minutes=5,seconds=1)
            for c in plan['watchlist']:
                s=c['symbol'];key=(day,s)
                if key in self.seen or s in self.positions or s in self.pending or not prefix_valid[s]:continue
                signal=entry_signal(plan,s,prefix[s],now.isoformat())
                if signal:self.seen.add(key);signals.append(signal)
            if signals:
                reservations=[dict(symbol=s,sector=p['sector'],quantity=p['quantity'],
                    mark=p['mark'],stop_price=p['stop_price']) for s,p in self.positions.items()]
                reservations.extend(dict(symbol=s,sector=p['sector'],quantity=p['quantity'],
                    mark=p['limit_price'],stop_price=p['stop_price'],pending=True) for s,p in self.pending.items())
                allocated=allocate(signals,self.equity(),self.cash,reservations,self.rules)
                for intent in allocated['intents']:self.pending[intent['symbol']]=intent
                for rejected in allocated['rejected']:self.events.append(dict(kind='CAPACITY_REJECTED',date=day,**rejected))
            self.nav.append(dict(at=now.isoformat(),equity=self.equity(),cash=self.cash,
                gross=sum(p['quantity']*p['mark'] for p in self.positions.values()),positions=len(self.positions)))
            t+=timedelta(minutes=5)
        if self.pending:
            # No overnight entries; a terminal order remains explicitly unfilled.
            self.events.extend(dict(kind='SESSION_END_UNFILLED',symbol=s,date=day) for s in self.pending)
            self.pending.clear()

    def close_trade(self,symbol,at):
        p=self.positions.pop(symbol)
        self.closed.append(dict(symbol=symbol,trade_id=p['trade_id'],entry_at=p['filled_at'],exit_at=at,
            entry_notional=p['entry_notional'],proceeds=p['proceeds'],dividends=p['dividends'],
            pnl=p['proceeds']+p['dividends']-p['entry_notional']))

    def report(self):
        gains=sum(max(t['pnl'],0) for t in self.closed);losses=-sum(min(t['pnl'],0) for t in self.closed)
        peak=self.initial_cash;drawdown=0
        for n in self.nav:
            peak=max(peak,n['equity']);drawdown=max(drawdown,1-n['equity']/peak)
        return dict(status='HALTED_INCOMPLETE_ACCOUNTING' if self.halt else 'CONDITIONAL_OHLC_REPLAY',
            initial_cash=self.initial_cash,last_known_equity=self.equity(),
            terminal_equity=None if self.halt else self.equity(),cash=self.cash,
            closed_trades=len(self.closed),open_positions=len(self.positions),
            closed_trade_pnl=sum(t['pnl'] for t in self.closed),
            open_trade_marked_pnl_including_partials=sum(p['proceeds']+p['quantity']*p['mark']+
                p['dividends']-p['entry_notional'] for p in self.positions.values()),
            receivables=sum(r['amount'] for r in self.receivables),
            net_return=None if self.halt else self.equity()/self.initial_cash-1,
            closed_trade_win_rate=sum(t['pnl']>0 for t in self.closed)/len(self.closed) if self.closed else None,
            profit_factor=gains/losses if losses else None,max_observed_bar_close_drawdown=drawdown,
            fills=len(self.fills),halt=self.halt,actual_orders=0,
            explicit_broker_fees_verified=False,promotable=False, gap_policy=self.gap_policy,
            held_unobserved_bars=sum(e['kind']=='HELD_BAR_UNOBSERVED' for e in self.events),
            nav_certified=False)
