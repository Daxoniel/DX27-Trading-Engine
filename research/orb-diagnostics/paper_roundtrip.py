"""Explicitly authorized one-share PAPER execution smoke test, not R1 signals.

Fixed Paper host. One QQQ FOK limit buy, then sell only its confirmed one share.
Prepared mutations are never blindly resent after unknown outcomes or restart.
"""
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING
import json
import os
from pathlib import Path
from time import sleep
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from uuid import uuid4

from dx27.adapters.alpaca.paper_contract import PAPER_ENDPOINT, timestamp_revision
from dx27.adapters.alpaca.paper_recorder import RejectPaperRedirects, _pairs
from dx27.adapters.intraday.lifecycle_journal import LifecycleJournal
from market_capture import MarketCapture, inspect_entry
from paper_intents import require, utc_now

TERMINAL={'filled','canceled','expired','rejected'}


def buy_payload(cid,limit):
    price=Decimal(limit)
    require(price.is_finite() and 0<price<=1000 and price==price.quantize(Decimal('.01')),'PAPER_BUY_CAP')
    return dict(symbol='QQQ',qty='1',side='buy',type='limit',time_in_force='fok',
                limit_price=str(price),extended_hours=False,client_order_id=cid)


def sell_payload(cid):
    return dict(symbol='QQQ',qty='1',side='sell',type='market',time_in_force='day',
                extended_hours=False,client_order_id=cid)


class PaperRoundtrip:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.journal=LifecycleJournal(self.path,dict(contract='PAPER_ONE_SHARE_SMOKE:1',host=PAPER_ENDPOINT,
            symbol='QQQ',quantity=1,max_buy_notional='1000',purpose='EXECUTION_SMOKE_NOT_R1'),
            dict(legs={},requests=[],preflight=None,source=None))
        for p in (self.path,Path(str(self.path)+'.lease.sqlite3')):
            try:os.chmod(p,0o600)
            except OSError:pass
        self.opener=build_opener(RejectPaperRedirects())
        self.headers={'APCA-API-KEY-ID':os.environ['APCA_API_KEY_ID'],
            'APCA-API-SECRET-KEY':os.environ['APCA_API_SECRET_KEY'],'Accept':'application/json',
            'Content-Type':'application/json','Accept-Encoding':'identity'}

    def close(self):self.journal.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def save(self,state,kind):self.journal.save(state,dict(kind=kind,at=utc_now()))

    def request(self,method,path,payload=None):
        allowed_get={'/v2/account','/v2/clock','/v2/positions','/v2/orders?status=open&limit=10&nested=false'}
        owned=self.journal.state['legs']
        by_client={('/v2/orders:by_client_order_id?'+urlencode(dict(client_order_id=l['payload']['client_order_id'])))
                   for l in owned.values()}
        allowed=(method=='GET' and path in allowed_get|by_client)
        if method=='POST' and path=='/v2/orders':
            allowed=any(l['payload']==payload and l['status']=='ATTEMPTED' for l in owned.values())
        require(allowed,'PAPER_PATH_OR_UNREGISTERED_MUTATION_REJECTED')
        if method=='POST':
            s=deepcopy(self.journal.state)
            for leg in s['legs'].values():
                if leg['payload']==payload:leg['status']='DISPATCHED'
            self.save(s,'POST_DISPATCHED_NO_RESEND')
        url=PAPER_ENDPOINT+path
        data=None if payload is None else json.dumps(payload,allow_nan=False).encode()
        req=Request(url,method=method,data=data,headers=self.headers)
        with self.opener.open(req,timeout=10) as response:
            require(response.geturl()==url and response.status in (200,201),'UNEXPECTED_PAPER_ORDER_RESPONSE')
            raw=response.read(262145);require(len(raw)<=262144,'PAPER_ORDER_RESPONSE_TOO_LARGE')
        body=json.loads(raw,object_pairs_hook=_pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        s=deepcopy(self.journal.state);s['requests'].append(dict(method=method,path=path,at=utc_now(),body=body))
        self.save(s,'HTTP_OBSERVED');return body

    def preflight(self):
        a=self.request('GET','/v2/account');c=self.request('GET','/v2/clock')
        p=self.request('GET','/v2/positions');o=self.request('GET','/v2/orders?status=open&limit=10&nested=false')
        require(a['status']=='ACTIVE' and a['trading_blocked'] is False and a['account_blocked'] is False
                and a['currency']=='USD' and Decimal(a['buying_power'])>=1000,'PAPER_ACCOUNT_NOT_READY')
        require(c['is_open'] is True,'PAPER_REGULAR_SESSION_REQUIRED')
        require(p==[] and o==[],'SMOKE_REQUIRES_FLAT_ACCOUNT_AND_NO_OPEN_ORDERS')
        s=deepcopy(self.journal.state);s['preflight']=dict(checked_at=utc_now(),flat=True,open_orders=0,market_open=True)
        self.save(s,'PREFLIGHT_PASS')

    def observe(self,side,order):
        s=deepcopy(self.journal.state);leg=s['legs'][side];p=leg['payload']
        require(order['client_order_id']==p['client_order_id'] and order['symbol']=='QQQ'
            and order['side']==side and Decimal(order['qty'])==1,'PAPER_ORDER_OWNERSHIP_CONFLICT')
        require(Decimal(order['filled_qty']) in (0,1),'ONE_SHARE_EXECUTION_REQUIRES_REVIEW')
        if 'order' in leg:require(order['id']==leg['order']['id'],'PAPER_BROKER_ID_CHANGED')
        leg['order']=order;leg['status']='OBSERVED';self.save(s,'OWNED_ORDER_OBSERVED')
        return order

    def reconcile(self,side):
        cid=self.journal.state['legs'][side]['payload']['client_order_id']
        return self.observe(side,self.request('GET','/v2/orders:by_client_order_id?'+urlencode(dict(client_order_id=cid))))

    def submit_once(self,side,payload):
        s=deepcopy(self.journal.state)
        if side in s['legs']:return self.reconcile(side)
        require(payload==(buy_payload(payload['client_order_id'],payload['limit_price']) if side=='buy'
                          else sell_payload(payload['client_order_id'])),'EXACT_SMOKE_PAYLOAD_REQUIRED')
        if side=='buy':
            require(s['preflight'] is not None and s['source'] is not None,'BUY_PREFLIGHT_AND_SOURCE_REQUIRED')
            require(0<=timestamp_revision(utc_now())-timestamp_revision(s['source']['provider_event_at'])<=5_000_000_000,
                    'ENTRY_QUOTE_EXPIRED')
        else:
            require(s['legs']['buy']['order']['status']=='filled'
                    and Decimal(s['legs']['buy']['order']['filled_qty'])==1,'SELL_REQUIRES_OWN_FILLED_BUY')
            positions=self.request('GET','/v2/positions')
            require(len(positions)==1 and positions[0]['symbol']=='QQQ' and Decimal(positions[0]['qty'])==1,
                    'EXIT_POSITION_OWNERSHIP_REVIEW_REQUIRED')
            s=deepcopy(self.journal.state)
        s['legs'][side]=dict(payload=payload,status='ATTEMPTED',prepared_at=utc_now())
        self.save(s,'ORDER_ATTEMPT_DURABLE_BEFORE_POST')
        # Any network/HTTP/parse error leaves ATTEMPTED for GET-only recovery.
        return self.observe(side,self.request('POST','/v2/orders',payload))

    def poll(self,side):
        for _ in range(10):
            order=self.reconcile(side)
            if order['status'] in TERMINAL:return order
            sleep(1)
        raise ValueError('PAPER_ORDER_STILL_PENDING_REVIEW_REQUIRED')

    def run(self):
        if not self.journal.state['legs']:
            self.preflight()
            with MarketCapture(self.path.parent/'entry-quote.sqlite',self.headers['APCA-API-KEY-ID'],
                    self.headers['APCA-API-SECRET-KEY'],feed='iex',max_requests=1) as capture:
                e=capture.sample('quote');q=inspect_entry(e)
            require(q['status']=='INSPECTED' and q['event_age_at_http_receipt_ns']<=5_000_000_000,'FRESH_IEX_SMOKE_QUOTE_REQUIRED')
            ask,bid=Decimal(q['ask']),Decimal(q['bid'])
            require((ask-bid)/ask<=Decimal('.005'),'SMOKE_SPREAD_TOO_WIDE')
            limit=(ask*Decimal('1.001')).quantize(Decimal('.01'),rounding=ROUND_CEILING)
            payload=buy_payload('ppr-smoke-buy-'+uuid4().hex[:24],limit)
            s=deepcopy(self.journal.state);s['source']=q;self.save(s,'CURRENT_ENGINEERING_REFERENCE')
            self.submit_once('buy',payload)
        buy=self.poll('buy')
        if buy['status']=='filled':
            self.submit_once('sell',sell_payload('ppr-smoke-sell-'+uuid4().hex[:24]))
            self.poll('sell')
        positions=self.request('GET','/v2/positions')
        orders=self.request('GET','/v2/orders?status=open&limit=10&nested=false')
        return self.summary(positions,orders)

    def summary(self,positions,orders):
        legs=self.journal.state['legs'];b=legs.get('buy',{}).get('order',{});s=legs.get('sell',{}).get('order',{})
        filled=b.get('status')=='filled' and s.get('status')=='filled'
        gross=(Decimal(s['filled_avg_price'])-Decimal(b['filled_avg_price'])) if filled else None
        return dict(purpose='PAPER_EXECUTION_SMOKE_NOT_R1',paper_host=PAPER_ENDPOINT,
            buy_status=b.get('status'),sell_status=s.get('status'),quantity=1,
            buy_average_price=b.get('filled_avg_price'),sell_average_price=s.get('filled_avg_price'),
            gross_fill_price_difference=str(gross) if gross is not None else None,fees_verified=False,
            net_pnl=None,strategy_r1_pnl=None,positions_after=len(positions),open_orders_after=len(orders),
            roundtrip_complete=filled and positions==[] and orders==[],live_orders_enabled=False,
            automatic_strategy_trading_enabled=False)


if __name__=='__main__':
    import argparse
    from dx27.adapters.alpaca.paper_recorder import _write_new
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-paper-smoke',action='store_true',required=True)
    parser.parse_args()
    with PaperRoundtrip('work/paper-practical/roundtrip-private.sqlite') as test:
        result=test.run();_write_new(Path('work/paper-practical/result.json'),result)
        print(json.dumps(result,indent=2))
