"""Fresh GET-only daily source capture; never writes a journal or approves a review."""
from datetime import timedelta
import json
from pathlib import Path
import time
from evidence import Source, bounds, context, canonical, legacy, gate, require, read_ref


def collect(root,record,seal_hash,bundle,day,clock,source_factory=Source):
    status,_,_=bounds(day,clock())
    base=dict(orders=0,journal_writes=0,execution_enabled=False)
    if status!='IN_WINDOW':return dict(base,status=status,network_requests=0)
    c=context(record,seal_hash,bundle,day,clock());root=Path(root);root.mkdir(parents=True,exist_ok=False)
    aliases=record['aliases'];allowed=c['required']|{r['lookup'] for r in aliases.values()}
    transport=None
    try:
        transport=source_factory(root/'sources',allowed);bindings=[]
        def get(kind,params):
            require(bounds(day,clock())[0]=='IN_WINDOW','CAPTURE_DEADLINE')
            if source_factory is Source:time.sleep(.35)
            blob,ref=transport.get(kind,params)
            read_ref(root/'sources',ref,allowed,clock())
            require(c['close']+timedelta(minutes=20)<=legacy.utc(ref['request_started_at'])<=legacy.utc(ref['received_at'])<=clock()<c['deadline'],'SOURCE_CLOSE_WINDOW')
            return blob,ref
        def pages(kind,params):
            seen=set()
            for _ in range(1000):
                blob,_=get(kind,params);body=json.loads(blob)
                require('next_page_token' in body,'PAGE_TERMINATOR')
                token=body['next_page_token']
                if token is None:return
                require(isinstance(token,str) and token and token not in seen,'PAGE_TOKEN')
                seen.add(token);params=dict(params,page_token=token)
            raise ValueError('PAGE_LIMIT')
        names=sorted(c['required'])
        for offset in range(0,len(names),50):
            symbols=','.join(names[offset:offset+50])
            for adjustment in ('all','raw'):
                pages('bars',dict(symbols=symbols,start=c['start'],end=day,timeframe='1Day',adjustment=adjustment,
                                 asof='2025-04-25',feed='sip',sort='asc',limit=10000))
            pages('actions',dict(symbols=symbols,start=c['previous'],end=clock().date().isoformat(),data_quality='all',limit=1000))
        for symbol in names:
            lookup=aliases.get(symbol,{}).get('lookup',symbol)
            blob,ref=get('asset',dict(symbol=lookup))
            binding=gate.registry.bind(symbol,json.loads(blob),aliases,clock().date())
            bindings.append(dict(binding,source_path=ref['path'],source_response_sha256=ref['response_sha256']))
        require(bounds(day,clock())[0]=='IN_WINDOW','CAPTURE_DEADLINE')
        manifest=dict(version='DE1_DAILY',date=day,start=c['start'],action_start=c['previous'],
                      formation_seal_sha256=seal_hash,cohort_sha256=c['cohort_sha256'],ledgers=bundle,source_refs=transport.refs,metadata_bindings=bindings)
        with (root/'manifest.json').open('xb') as stream:stream.write(canonical(manifest)+b'\n')
        result=dict(base,status='CAPTURED_PENDING_DAILY_REVIEW',network_requests=len(transport.refs),required_names=len(names))
    except Exception as error:
        result=dict(base,status='BLOCKED_DAILY_CAPTURE',network_requests=len(transport.refs) if transport else 0,
                    failure_type=type(error).__name__,failure_code=str(error) if isinstance(error,ValueError) else 'SOURCE_OR_IO_FAILURE')
    with (root/'report.json').open('xb') as stream:stream.write(canonical(result)+b'\n')
    return result
