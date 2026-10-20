"""Matched 1m/5m signal × same-day reentry experiment; never broker transport."""
from collections import deque
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
import math

from history_replay_quote import Replay as BaseReplay
from quote_history_v2 import quote_fill
from strategy import Rules, allocate, manage, seal, stamp, validate_bars


def signal_for(plan,candidate,window,now,minutes,since,rules):
    opening,closing=stamp(plan['session_open']),stamp(plan['session_close'])
    if stamp(plan['asof'])>=now:raise ValueError('PLAN_OR_SIGNAL_CLOCK_CONFLICT')
    if not opening<now<=min(opening+timedelta(hours=2),closing) or len(window)!=3:return None
    validate_bars(window,now,minutes)
    if (stamp(window[0]['start'])<since or
            any(stamp(window[i]['start'])!=stamp(window[i-1]['end']) for i in (1,2))):return None
    available=stamp(window[-1]['available_at'])
    if now<available or now-available>timedelta(seconds=60):return None
    last=window[-1];low=min(b['low'] for b in window[:2])
    for name,support in sorted(candidate['support_levels'].items(),key=lambda x:(-x[1],x[0])):
        if not (support*(1-rules.max_stop)<=low<=support*(1+rules.support_tolerance)
                and last['close']>max(support,window[-2]['high']) and last['close']>last['open']):continue
        stop=min(b['low'] for b in window)
        limit=float((Decimal(str(last['close']))*(1+Decimal(str(rules.adverse_bps))/10000))
                    .quantize(Decimal('.01'),rounding=ROUND_CEILING))
        if not rules.min_stop<=(limit-stop)/limit<=min(rules.max_stop,candidate['adr']/2):continue
        key=f"MLP3:{minutes}:{plan['session_open']}:{candidate['symbol']}:{last['end']}"
        return dict(signal_key=key,client_order_id='mlp3-'+sha256(key.encode()).hexdigest()[:32],
            symbol=candidate['symbol'],sector=candidate['sector'],side='buy',
            signal_at=last['available_at'],limit_price=limit,stop_price=stop,
            expires_at=(available+timedelta(minutes=5)).isoformat(),selected_support=name,
            evidence_sha256=seal(list(window)),execution_enabled=False)
    return None


class Replay(BaseReplay):
    def __init__(self,minutes=5,reentry=False,**kwargs):
        if minutes not in (1,5) or type(reentry) is not bool:raise ValueError('INVALID_FACTORIAL_CELL')
        super().__init__(**kwargs)
        self.minutes=minutes;self.reentry=reentry
        self.attempts={};self.since={};self.terminal_kind={};self.filled_today={}

    def terminal(self,symbol,at,kind):
        self.since[symbol]=stamp(at);self.terminal_kind[symbol]=kind

    def close_trade(self,symbol,at):
        p=self.positions[symbol]
        extra={k:p[k] for k in ('initial_dollar_risk','attempt_index','signal_minutes')}
        super().close_trade(symbol,at)
        self.closed[-1].update(extra)
        self.closed[-1]['realized_r']=self.closed[-1]['pnl']/extra['initial_dollar_risk']
        self.terminal(symbol,at,'EXIT')

    def manage_observed(self,symbol,b,now,minutes,closing):
        if b is None:
            if self.gap_policy=='HALT':self.stop('HELD_POSITION_BAR_MISSING',symbol=symbol,at=now.isoformat());return
            self.events.append(dict(kind='HELD_BAR_UNOBSERVED',symbol=symbol,at=now.isoformat(),minutes=minutes));return
        try:
            validate_bars([b],now,minutes)
            if b.get('invalid_components'):raise ValueError('INVALID_MINUTE_COMPONENT')
        except ValueError:
            self.stop('HELD_POSITION_BAR_INVALID',symbol=symbol,at=now.isoformat());return
        p=self.positions[symbol]
        result=manage(p,b,1e-300,closing,self.rules)
        for fill in result['fills']:
            # Recognize cash only after this complete bar is observable.
            self.sell(symbol,dict(fill,price_reference_at=b['start'] if fill['reason']=='TRAIL_NEXT_OPEN' else None),now.isoformat())
        if result['position'] is None:self.close_trade(symbol,now.isoformat())
        else:
            updated=result['position'];updated['proceeds']=p['proceeds'];updated['mark']=b['close']
            self.positions[symbol]=updated

    def session(self,plan,bars,daily_exit,actions=(),minute_bars=None):
        if self.halt:raise ValueError('HALTED_REPLAY_CANNOT_CONTINUE')
        opening,closing=stamp(plan['session_open']),stamp(plan['session_close'])
        day=opening.date().isoformat()
        if self.last_session and day<=self.last_session:raise ValueError('SESSION_ORDER_REQUIRED')
        if plan['rules']!=self.rules.__dict__:raise ValueError('FROZEN_RULES_MISMATCH')
        self.last_session=day
        self.attempts={};self.since={};self.terminal_kind={};self.filled_today={}
        self.actions(day,actions)
        if self.halt:return
        for symbol,p in self.positions.items():
            if symbol not in daily_exit:self.stop('HELD_POSITION_DAILY_HISTORY_MISSING',symbol=symbol,date=day);return
            p['exit_pending']=p.get('exit_pending',False) or bool(daily_exit[symbol])
        def index(source):
            out={}
            for symbol,rows in source.items():
                ix={stamp(b['end']):b for b in rows}
                if len(ix)!=len(rows):raise ValueError('DUPLICATE_BAR')
                if any(not opening<=stamp(b['start'])<stamp(b['end'])<=closing for b in rows):raise ValueError('BAR_OUTSIDE_SESSION')
                out[symbol]=ix
            return out
        five=index(bars);one=index(minute_bars or {})
        windows={c['symbol']:deque(maxlen=3) for c in plan['watchlist']}
        t=opening
        while t<=closing:
            # At the minute opening, only events available BEFORE t may fund or
            # trigger entry. Bars ending at t are not known until t+1 second.
            for symbol,intent in list(self.pending.items()):
                if t>=stamp(intent['expires_at']):
                    del self.pending[symbol];self.terminal(symbol,t.isoformat(),'UNFILLED')
                    self.events.append(dict(kind='ENTRY_EXPIRED',symbol=symbol,at=t.isoformat()));continue
                if t<=stamp(intent['signal_at']) or t>=closing:continue
                execution,reason=quote_fill(self.quote_source(symbol,t.isoformat()),t.isoformat(),intent,self.rules.adverse_bps)
                del self.pending[symbol]
                if execution is None:
                    self.terminal(symbol,t.isoformat(),'UNFILLED')
                    self.events.append(dict(kind='QUOTE_ENTRY_REJECTED',symbol=symbol,at=t.isoformat(),reason=reason));continue
                q,price=execution['quantity'],execution['price'];notional=q*price
                if notional>self.cash+1e-8:raise ValueError('CASH_ACCOUNTING_OVERRUN')
                self.cash-=notional;self.trade_number+=1
                offset=int((t-opening).total_seconds()/60)
                bridge=t+timedelta(minutes=5-offset%5) if offset%5 else t
                p=dict(entry=price,initial_stop=intent['stop_price'],stop_price=intent['stop_price'],quantity=q,
                    initial_quantity=q,partial_taken=False,exit_pending=False,filled_at=t.isoformat(),mark=price,
                    sector=intent['sector'],trade_id=self.trade_number,entry_notional=notional,proceeds=0.,dividends=0.,
                    bridge_until=bridge.isoformat(),initial_dollar_risk=q*(price-intent['stop_price']),
                    attempt_index=intent['attempt_index'],signal_minutes=self.minutes)
                self.positions[symbol]=p
                self.filled_today[symbol]=self.filled_today.get(symbol,0)+1
                self.terminal_kind[symbol]='HELD'
                self.fills.append(dict(symbol=symbol,trade_id=p['trade_id'],at=t.isoformat(),side='buy',quantity=q,price=price,
                    reason='DISPLAYED_ASK_AT_MINUTE_OPEN',signal_at=intent['signal_at'],expires_at=intent['expires_at'],
                    limit_price=intent['limit_price'],stop_price=intent['stop_price'],attempt_index=intent['attempt_index'],
                    selected_support=intent['selected_support'],signal_evidence_sha256=intent['evidence_sha256'],
                    prior_terminal_kind=intent['prior_terminal_kind'],prior_fills_today=intent['prior_fills_today'],
                    **{k:v for k,v in execution.items() if k not in ('price','quantity')}))
            now=t+timedelta(seconds=1)
            # Observe the interval ending at t, after entries at t. Never apply
            # prefill OHLC to a position just entered at this opening.
            for symbol in sorted(list(self.positions)):
                if t==opening:continue
                p=self.positions[symbol]
                if stamp(p['filled_at'])>=t:continue
                if t<=stamp(p['bridge_until']):
                    self.manage_observed(symbol,one.get(symbol,{}).get(t),now,1,plan['session_close'])
                elif (t-opening).total_seconds()%300==0:
                    b=five.get(symbol,{}).get(t)
                    if b is not None and stamp(b['start'])<stamp(p['filled_at']):continue
                    self.manage_observed(symbol,b,now,5,plan['session_close'])
                if self.halt:return
            if opening<t and now<=min(opening+timedelta(hours=2),closing) and (t-opening).total_seconds()%(self.minutes*60)==0:
                signals=[];source=one if self.minutes==1 else five
                for c in plan['watchlist']:
                    symbol=c['symbol'];window=windows[symbol];b=source.get(symbol,{}).get(t)
                    if b is None or b.get('invalid_components'):
                        window.clear();self.events.append(dict(kind='SIGNAL_INTERVAL_UNOBSERVED',symbol=symbol,at=now.isoformat()));continue
                    try:validate_bars([b],now,self.minutes)
                    except ValueError:window.clear();continue
                    if window and stamp(window[-1]['end'])!=stamp(b['start']):window.clear()
                    window.append(b)
                    if symbol in self.positions or symbol in self.pending:continue
                    if not self.reentry and self.attempts.get(symbol,0):continue
                    signal=signal_for(plan,c,list(window),now,self.minutes,self.since.get(symbol,opening),self.rules)
                    if signal is None:continue
                    attempt=self.attempts.get(symbol,0)+1;self.attempts[symbol]=attempt
                    signal.update(attempt_index=attempt,prior_terminal_kind=self.terminal_kind.get(symbol,'START'),
                                  prior_fills_today=self.filled_today.get(symbol,0))
                    self.events.append(dict(kind='SIGNAL_ATTEMPT',symbol=symbol,at=now.isoformat(),
                        attempt_index=attempt,prior_terminal_kind=signal['prior_terminal_kind']))
                    self.terminal(symbol,now.isoformat(),'CAPACITY');signals.append(signal)
                if signals:
                    reservations=[dict(symbol=s,sector=p['sector'],quantity=p['quantity'],mark=p['mark'],stop_price=p['stop_price']) for s,p in self.positions.items()]
                    reservations.extend(dict(symbol=s,sector=p['sector'],quantity=p['quantity'],mark=p['limit_price'],stop_price=p['stop_price'],pending=True) for s,p in self.pending.items())
                    result=allocate(signals,self.equity(),self.cash,reservations,self.rules)
                    for intent in result['intents']:self.pending[intent['symbol']]=intent
                    for rejected in result['rejected']:self.events.append(dict(kind='CAPACITY_REJECTED',at=now.isoformat(),**rejected))
            self.nav.append(dict(at=now.isoformat(),equity=self.equity(),cash=self.cash,
                gross=sum(p['quantity']*p['mark'] for p in self.positions.values()),positions=len(self.positions)))
            t+=timedelta(minutes=1)
        for symbol in list(self.pending):self.events.append(dict(kind='SESSION_END_UNFILLED',symbol=symbol,date=day))
        self.pending.clear()

    def report(self):
        return dict(super().report(),signal_minutes=self.minutes,reentry=self.reentry,
            signal_attempts=sum(e['kind']=='SIGNAL_ATTEMPT' for e in self.events),
            held_unobserved_minutes=sum(e.get('minutes',0) for e in self.events if e['kind']=='HELD_BAR_UNOBSERVED'))
