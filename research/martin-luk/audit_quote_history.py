"""Independent Decimal cash audit plus raw-quote entry evidence verification.

Does not import the strategy, replay, or quote-fill implementation.
"""
import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import gzip
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlencode

from audit_history import audit


def instant(s):
    s=s.replace('Z','+00:00')
    if '.' in s:
        base,rest=s.split('.',1);fraction,zone=rest.split('+',1)
        if zone!='00:00':raise ValueError('UTC_REQUIRED')
        return Decimal(int(datetime.fromisoformat(base+'+00:00').timestamp()))+Decimal('0.'+fraction)
    return Decimal(int(datetime.fromisoformat(s).timestamp()))


def audit_quotes(root,quotes):
    root,quotes=Path(root),Path(quotes)
    base=audit(root)
    summary=json.loads((root/'summary.json').read_text())
    fills=json.loads((root/'fills.json').read_text())
    expected_sources={x['sha256'] for x in summary['quote_sources']}
    buys=[f for f in fills if f['side']=='buy']
    for f in buys:
        at=datetime.fromisoformat(f['at'])
        params=dict(symbols=f['symbol'],start=(at-timedelta(seconds=60)).isoformat(),
            end=f['at'],feed='sip',asof='2025-04-25',sort='desc',limit=1)
        url='https://data.alpaca.markets/v2/stocks/quotes?'+urlencode(sorted(params.items()))
        key=sha256(url.encode()).hexdigest()
        raw=gzip.decompress((quotes/(key+'.json.gz')).read_bytes())
        meta=json.loads((quotes/(key+'.meta.json')).read_text())
        digest=sha256(raw).hexdigest()
        if meta['url']!=url or meta['sha256']!=digest or digest not in expected_sources:
            raise ValueError('QUOTE_SOURCE_BINDING_FAILED')
        rows=json.loads(raw)['quotes'][f['symbol']]
        if len(rows)!=1:raise ValueError('LATEST_QUOTE_NOT_UNIQUE')
        q=rows[0]
        if q['t']!=f['quote_at'] or not Decimal(0)<=instant(f['at'])-instant(q['t'])<=Decimal(60):
            raise ValueError('FUTURE_OR_STALE_EXECUTION_QUOTE')
        if q.get('c')!=['R'] or not 0<q['bp']<=q['ap']<=250 or q['as']<=0:
            raise ValueError('NONREGULAR_OR_INVALID_EXECUTION_QUOTE')
        if q['ap']!=f['reference_ask'] or int(q['as']*100)!=f['visible_ask_shares']:
            raise ValueError('QUOTE_PRICE_OR_SIZE_MISMATCH')
        if not 0<f['quantity']<=f['visible_ask_shares'] or f['unfilled_cancelled']<0:
            raise ValueError('DISPLAYED_CAPACITY_EXCEEDED')
        price=Decimal(str(q['ap']))*(1+Decimal(str(summary['adverse_bps_each_side']))/10000)
        if abs(price-Decimal(str(f['price'])))>Decimal('.00000001') or f['price']<=f['stop_price']:
            raise ValueError('EXECUTION_PRICE_OR_PROTECTION_MISMATCH')
    return dict(base,entry_quotes_checked=len(buys),quote_input_consistency_verified=True,
        exit_quote_execution_verified=False,model_fills_guaranteed=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--quotes',type=Path,required=True)
    a=p.parse_args();result=audit_quotes(a.report,a.quotes)
    (a.report/'independent-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
