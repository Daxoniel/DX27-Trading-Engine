"""Bounded fixed-host latest QQQ HTTP capture. No trading or feed fallback."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import base64
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
from time import monotonic_ns
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from uuid import uuid4

from dx27.adapters.alpaca.paper_contract import timestamp_revision
from dx27.adapters.alpaca.paper_recorder import RejectPaperRedirects, _pairs, _write_new
from dx27.adapters.intraday.lifecycle_journal import LifecycleJournal
from execution_timing import positive_price
from paper_intents import require, utc_now

HOST='https://data.alpaca.markets'
CONTRACT='ORB_BOUNDED_MARKET_CAPTURE:1'
LIMIT=65536
SIZE_CHANGE=timestamp_revision('2025-11-03T00:00:00Z')


def decode(raw):
    def invalid(value):raise ValueError('NONFINITE_PROVIDER_JSON')
    return json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs,
                      parse_float=Decimal,parse_constant=invalid)


def inspect_entry(entry):
    """Preserve provider nanoseconds and original size; do not guess IEX units.

    Poll receipt is HTTP body completion, not original market-event receipt.
    This inspection never attests a fresh reference or full market sequence.
    """
    if entry['status']!='CAPTURED':return dict(status=entry['status'],code=entry.get('code'))
    raw=base64.b64decode(entry['raw_base64'],validate=True)
    require(hashlib.sha256(raw).hexdigest()==entry['raw_sha256'],'RAW_CAPTURE_SEAL_MISMATCH')
    body=decode(raw);kind=entry['kind'];key='quote' if kind=='quote' else 'bar'
    require(isinstance(body,dict) and body.get('symbol')=='QQQ' and isinstance(body.get(key),dict),
            'PROVIDER_QQQ_SHAPE_REQUIRED')
    row=body[key];event_ns=timestamp_revision(row['t'])
    receipt_ns=timestamp_revision(entry['received_at'])
    require(timestamp_revision(entry['started_at'])<=receipt_ns,'LOCAL_HTTP_CLOCK_REGRESSED')
    require(event_ns<=receipt_ns,'PROVIDER_EVENT_AFTER_HTTP_RECEIPT')
    result=dict(status='INSPECTED',kind=kind,feed=entry['feed'],provider_event_at=row['t'],
        provider_event_ns=event_ns,http_received_at=entry['received_at'],
        event_age_at_http_receipt_ns=receipt_ns-event_ns,
        event_exactly_representable_in_microseconds=event_ns%1000==0,
        original_market_receipt_verified=False,provider_completeness_verified=False)
    if kind=='quote':
        bid,ask=positive_price(row['bp']),positive_price(row['ap'])
        require(ask>=bid,'CROSSED_PROVIDER_QUOTE')
        require(all(type(row[n]) is int and row[n]>=0 for n in ('bs','as')),'INVALID_PROVIDER_SIZE')
        result.update(bid=str(bid),ask=str(ask),raw_bid_size=row['bs'],raw_ask_size=row['as'],
            size_unit=('SHARES' if entry['feed']=='sip' and event_ns>=SIZE_CHANGE else 'UNRESOLVED'),
            size_multiplier=None)
    else:
        values={n:positive_price(row[n]) for n in ('o','h','l','c')}
        require(values['l']<=min(values['o'],values['c'])<=max(values['o'],values['c'])<=values['h'],
                'INVALID_PROVIDER_OHLC')
        require(type(row['v']) in (int,Decimal) and Decimal(row['v']).is_finite() and row['v']>=0,
                'INVALID_PROVIDER_VOLUME')
        require(event_ns%60_000_000_000==0,'PROVIDER_BAR_NOT_MINUTE_ALIGNED')
        result['bar_complete_at_http_receipt']=event_ns+60_000_000_000<=receipt_ns
    return result


def project_quote(entry, *, receipt_sequence):
    """Lossless normalized quote only; existing journal still owns session/policy.

    No nanosecond rounding, IEX relabeling or implicit lot conversion.
    """
    require(type(receipt_sequence) is int and receipt_sequence>0,'POSITIVE_RECEIPT_SEQUENCE_REQUIRED')
    info=inspect_entry(entry)
    if info['status']!='INSPECTED':return dict(status='BLOCKED_CAPTURE_UNAVAILABLE',event=None)
    require(info['kind']=='quote','QUOTE_CAPTURE_REQUIRED')
    reasons=[]
    if info['feed']!='sip':reasons.append('FROZEN_R1_REQUIRES_SIP')
    if info['size_unit']!='SHARES':reasons.append('SIZE_UNIT_UNRESOLVED')
    if not info['event_exactly_representable_in_microseconds']:reasons.append('NANOSECOND_JOURNAL_ADAPTER_REQUIRED')
    if min(info['raw_bid_size'],info['raw_ask_size'])<=0:reasons.append('ZERO_DISPLAYED_SIZE')
    if reasons:return dict(status='BLOCKED_OBSERVATION_PROJECTION',reasons=reasons,event=None)
    # Conversion only after exact divisibility check; no precision is discarded.
    at=datetime.fromisoformat(info['provider_event_at'].replace('Z','+00:00'))
    event_at=at.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
    event=dict(event_id=entry['capture_id'],receipt_sequence=receipt_sequence,received_at=entry['received_at'],
        feed='sip',kind='QUOTE',payload=dict(symbol='QQQ',event_at=event_at,bid=info['bid'],ask=info['ask'],
            bid_size=info['raw_bid_size'],ask_size=info['raw_ask_size'],size_unit='SHARES'))
    return dict(status='NORMALIZED_QUOTE_NOT_A_SIGNAL',event=event)


class MarketCapture:
    """One declared feed, at most four GETs. Persist pending before network I/O.

    No retry after failure or unresolved pending request, including after restart.
    Raw bodies are private SQLite evidence. Credentials are never journaled.
    """
    def __init__(self,path,api_key,secret_key,*,feed,max_requests=2):
        require(feed in ('sip','iex'),'EXPLICIT_CAPTURE_FEED_REQUIRED')
        require(type(max_requests) is int and 1<=max_requests<=4,'BOUNDED_CAPTURE_LIMIT_REQUIRED')
        require(all(isinstance(v,str) and 0<len(v)<=4096 and '\n' not in v and '\r' not in v
                    for v in (api_key,secret_key)),'CAPTURE_CREDENTIALS_REQUIRED')
        self.feed=feed;self.max_requests=max_requests
        self.headers={'APCA-API-KEY-ID':api_key,'APCA-API-SECRET-KEY':secret_key,
                      'Accept':'application/json','Accept-Encoding':'identity'}
        self.opener=build_opener(RejectPaperRedirects())
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.journal=LifecycleJournal(path,dict(contract=CONTRACT,host=HOST,feed=feed,symbol='QQQ',
            max_requests=max_requests),dict(entries=[]))
        for p in (path,Path(str(path)+'.lease.sqlite3')):
            try:os.chmod(p,0o600)
            except OSError:pass

    def close(self):self.journal.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def sample(self,kind):
        require(kind in ('quote','bar'),'QUOTE_OR_BAR_ONLY')
        state=deepcopy(self.journal.state)
        require(all(e['status']=='CAPTURED' for e in state['entries']),'CAPTURE_FAILURE_OR_PENDING_REVIEW_REQUIRED')
        require(len(state['entries'])<self.max_requests,'CAPTURE_REQUEST_LIMIT')
        path=f'/v2/stocks/QQQ/{"quotes" if kind=="quote" else "bars"}/latest'
        url=HOST+path+'?feed='+self.feed
        entry=dict(capture_id='md-'+uuid4().hex,kind=kind,feed=self.feed,
            started_at=utc_now(),status='PENDING')
        state['entries'].append(entry)
        self.journal.save(state,dict(kind='GET_PENDING',capture_id=entry['capture_id']))
        start=monotonic_ns()
        try:
            request=Request(url,method='GET',headers=self.headers)
            with self.opener.open(request,timeout=10) as response:
                entry['http_status']=response.status
                require(response.status==200 and response.geturl()==url,'UNEXPECTED_CAPTURE_RESPONSE')
                require(response.headers.get_content_type()=='application/json','CAPTURE_RESPONSE_NOT_JSON')
                require(response.headers.get('Content-Encoding','identity').lower()=='identity','CAPTURE_ENCODING_REJECTED')
                length=response.headers.get('Content-Length')
                require(length is None or (length.isascii() and length.isdigit() and int(length)<=LIMIT),
                        'CAPTURE_RESPONSE_TOO_LARGE')
                raw=response.read(LIMIT+1)
                received=utc_now();elapsed=monotonic_ns()-start
                require(len(raw)<=LIMIT and (length is None or len(raw)==int(length)),
                        'CAPTURE_BODY_TOO_LARGE_OR_TRUNCATED')
            entry.update(status='CAPTURED',received_at=received,http_elapsed_ns=elapsed,
                raw_base64=base64.b64encode(raw).decode(),raw_sha256=hashlib.sha256(raw).hexdigest())
            inspect_entry(entry)
        except HTTPError as exc:
            entry.update(status='UNAVAILABLE',http_status=exc.code,code=f'MARKET_HTTP_STATUS_{exc.code}')
            try:
                raw=exc.read(LIMIT+1)
                entry.update(received_at=utc_now(),raw_base64=base64.b64encode(raw[:LIMIT]).decode(),
                    raw_sha256=hashlib.sha256(raw[:LIMIT]).hexdigest(),error_body_truncated=len(raw)>LIMIT)
            except (OSError,HTTPException):entry['error_body_read_failed']=True
            finally:exc.close()
        except (URLError,OSError,HTTPException,TimeoutError):
            entry.update(status='UNAVAILABLE',code='MARKET_NETWORK_UNAVAILABLE')
        except (ValueError,TypeError,KeyError,UnicodeError,RecursionError,OverflowError):
            entry.update(status='INVALID_RESPONSE',code='INVALID_MARKET_RESPONSE')
        entry['completed_at']=utc_now()
        self.journal.save(state,dict(kind='GET_COMPLETED',capture_id=entry['capture_id'],status=entry['status']))
        return deepcopy(entry)

    def summary(self):
        entries=self.journal.state['entries'];rows=[]
        for entry in entries:
            row={k:entry[k] for k in ('capture_id','kind','feed','status','code','started_at','received_at',
                'completed_at','http_status','http_elapsed_ns','raw_sha256') if k in entry}
            if entry['status']=='CAPTURED':
                info=inspect_entry(entry)
                row['event_age_at_http_receipt_ns']=info['event_age_at_http_receipt_ns']
                row['provider_event_ns_preserved']=True
                if entry['kind']=='quote':
                    projection=project_quote(entry,receipt_sequence=1)
                    row['projection_status']=projection['status'];row['projection_reasons']=projection.get('reasons',[])
                    row['size_unit']=info['size_unit']
                else:row['bar_complete_at_http_receipt']=info['bar_complete_at_http_receipt']
            rows.append(row)
        return dict(contract=CONTRACT,feed=self.feed,requests=len(entries),entries=rows,
            full_market_stream=False,original_market_receipt_verified=False,provider_completeness_verified=False,
            actual_paper_intents_created=0,actual_strategy_paper_pnl=None,execution_enabled=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--feed',choices=['sip','iex'],required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False,mode=0o700)
    with MarketCapture(a.output/'private-capture.sqlite',os.environ.get('APCA_API_KEY_ID'),
            os.environ.get('APCA_API_SECRET_KEY'),feed=a.feed) as capture:
        for kind in ('quote','bar'):
            if capture.sample(kind)['status']!='CAPTURED':break
        report=capture.summary()
        _write_new(a.output/'summary.json',report)
        print(json.dumps(report,indent=2))


if __name__=='__main__':main()
