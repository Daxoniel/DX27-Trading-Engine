"""Actual read-only interface sample, never ranks or generates stock prices/orders."""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from snapshots import Capture, canonical

ROOT=Path(__file__).resolve().parents[2]


def load_preparation():
    spec=importlib.util.spec_from_file_location('ra_prepare',ROOT/'research/residual-forward/prepare.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();cohort_bytes=(ROOT/'work/mlp1-history/cohort.json').read_bytes()
    if sha256(cohort_bytes).hexdigest()!='eeadc8c0b4860640fd0a548301f9fb676cef7591168e04d10e98a479d6923d60':
        raise ValueError('COHORT_SEAL')
    allowed={r['symbol'] for r in json.loads(cohort_bytes)}
    old=json.loads((ROOT/'work/residual-validation/matched_residual-5bp.json').read_bytes())
    symbols=sorted({s for event in old['events'] for s in event['weights']})
    if not symbols or len(symbols)>40 or not set(symbols)<=allowed or 'SOXL' in symbols:
        raise ValueError('SAMPLE_SCOPE')
    capture=Capture(args.output,allowed); preparation=load_preparation(); assets=[]; failures=0
    factor_blob,factor_ref=capture.get('factors',{})
    months=preparation.factor_months(factor_blob); now=datetime.now(timezone.utc)
    for symbol in symbols:
        try:
            blob,ref=capture.get('asset',dict(symbol=symbol))
            row=json.loads(blob)
            if row.get('symbol')!=symbol or not row.get('id'): raise ValueError('ASSET_SCHEMA')
            assets.append(dict(symbol=symbol,id=row['id'],status=row.get('status'),tradable=row.get('tradable'),
                               asset_class=row.get('class'),receipt=ref))
        except Exception as error:
            # Sample failure is recorded; never promoted based on surviving symbols.
            failures+=1
    pages,action_refs=capture.pages('actions',dict(symbols=','.join(symbols),start='2025-04-25',
        end=now.date().isoformat(),data_quality='all',limit=1000))
    event_counts={}
    for page in pages:
        groups=page.get('corporate_actions')
        if not isinstance(groups,dict): raise ValueError('ACTION_SCHEMA')
        for kind,rows in groups.items():
            if not isinstance(rows,list): raise ValueError('ACTION_SCHEMA')
            event_counts[kind]=event_counts.get(kind,0)+len(rows)
    private=dict(assets=assets,actions=action_refs,pages=capture.refs)
    (args.output/'input-manifest.json').write_bytes(canonical(private)+b'\n')
    first=json.loads((ROOT/'docs/research/residual-shadow/calendar.json').read_bytes())['planned_cycles'][0]
    missing=sorted(set(preparation.required_months())-months)
    blockers=['FORMATION_NOT_CLOSED' if now<datetime.fromisoformat(first['formation_close']) else 'FORMATION_INPUTS_NOT_CAPTURED',
              'FULL_UNIVERSE_PRICES_NOT_CAPTURED','ECONOMIC_IDENTITY_REVIEW_NOT_COMPLETED',
              'ACTION_REVIEW_NOT_COMPLETED','NO_SEALED_FORMATION_RANK','NO_DAILY_ADMISSION_RUNNER']
    if missing: blockers.append('FACTOR_MONTHS_MISSING')
    if failures: blockers.append('ASSET_SAMPLE_FAILURES')
    report=dict(version='RA1',status='BLOCKED_OPERATIONAL_SAMPLE_ONLY',observed_at=datetime.now(timezone.utc).isoformat(),
        cohort_sha256=sha256(cohort_bytes).hexdigest(),protocol_sha256=sha256((ROOT/'docs/research/residual-admission/protocol.json').read_bytes()).hexdigest(),
        private_manifest_sha256=sha256((args.output/'input-manifest.json').read_bytes()).hexdigest(),
        factor_latest_month=max(months),missing_required_factor_months=missing,factor_sha256=factor_ref['response_sha256'],
        sampled_symbols=len(symbols),asset_responses=len(assets),asset_failures=failures,
        active_tradable_us_equity_count=sum(r['status']=='active' and r['tradable'] is True and r['asset_class']=='us_equity' for r in assets),
        action_pages=len(pages),action_counts=event_counts,pagination_exhausted=pages[-1].get('next_page_token') is None,
        verified_economic_identities=0,receipt_count=len(capture.refs),blockers=blockers,
        received_timestamps_not_original_publication_times=True,new_stock_prices_requested=False,
        new_signal_computed=False,account_accessed=False,asset_metadata_only=True,orders=0,
        prior_full_exposure_screen='FAIL_RETAINED',automatic_promotion=False)
    (args.output/'report.json').write_bytes(canonical(report)+b'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
