"""One documentary ticker-change case; no price access or live admission mapping."""
from datetime import datetime,timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from urllib.request import build_opener,Request

ROOT=Path(__file__).resolve().parents[2]
SOURCES=[
 ('sec','https://www.sec.gov/Archives/edgar/data/1856437/000185643726000007/vsco-20260521.htm'),
 ('issuer','https://victoriassecret.gcs-web.com/news-releases/news-release-details/victorias-secret-co-change-ticker-symbol-vsxy-marking-next')]


def load_snapshot():
    spec=importlib.util.spec_from_file_location('ri_snapshots',ROOT/'research/residual-admission/snapshots.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def capture(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);s=load_snapshot();sources=[]
    for name,url in SOURCES:
        started=datetime.now(timezone.utc).isoformat()
        try:
            request=Request(url,headers={'User-Agent':'DX27-Trading-Engine research (https://github.com/Daxoniel/DX27-Trading-Engine)'},method='GET')
            with build_opener(s.NoRedirect()).open(request,timeout=30) as response:
                if response.status!=200 or response.geturl()!=url: raise ValueError('SOURCE_RESPONSE')
                blob=response.read(2_000_001)
            if len(blob)>2_000_000: raise ValueError('SOURCE_SIZE')
            (output/f'{name}.html').write_bytes(blob)
            sources.append(dict(source=name,url=url,status='OBSERVED',bytes=len(blob),sha256=sha256(blob).hexdigest(),
                                started_at=started,received_at=datetime.now(timezone.utc).isoformat()))
        except Exception as error:
            sources.append(dict(source=name,url=url,status='UNAVAILABLE',failure_type=type(error).__name__,
                                http_status=getattr(error,'code',None)))
    capture=s.Capture(output/'asset-current',{'VSXY'})
    blob,ref=capture.get('asset',dict(symbol='VSXY'));asset=json.loads(blob)
    if asset.get('symbol')!='VSXY' or not asset.get('id'): raise ValueError('ALIAS_ASSET_SCHEMA')
    prior=ROOT/'work/residual-admission/probe-1';m=json.loads((prior/'input-manifest.json').read_bytes());matches=[]
    for action_ref in m['actions']:
        action_blob=(prior/action_ref['path']).read_bytes()
        if sha256(action_blob).hexdigest()!=action_ref['response_sha256']: raise ValueError('OLD_ACTION_SEAL')
        for row in json.loads(action_blob)['corporate_actions'].get('name_changes',[]):
            if row.get('old_symbol')=='VSCO' and row.get('new_symbol')=='VSXY': matches.append(row)
    if len(matches)!=1 or matches[0]['old_cusip']!=matches[0]['new_cusip']: raise ValueError('MAPPING_UNRESOLVED')
    private=dict(sources=sources,asset_receipt=ref,mapping=matches[0],current_asset=asset)
    (output/'evidence.json').write_bytes(s.canonical(private)+b'\n')
    result=dict(version='RI1',status='DOCUMENTARY_TICKER_CHANGE_CASE_REVIEWED',
                case_sha256=sha256((output/'evidence.json').read_bytes()).hexdigest(),
                source_receipts=sources,vendor_name_change_records=1,cusip_unchanged=True,
                alias_asset_observed=asset.get('status')=='active' and asset.get('tradable') is True,
                asset_response_sha256=ref['response_sha256'],
                old_lookup_failure_explained_by_documented_ticker_change=True,
                identity_status='CASE_EXPLANATION_NOT_FORMATION_ADMISSION',
                archive_or_price_symbols_changed=False,formation_ready_identities=0,
                new_prices=0,orders=0,automatic_promotion=False)
    (output/'summary.json').write_bytes(s.canonical(result)+b'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    capture(p.parse_args().output)
