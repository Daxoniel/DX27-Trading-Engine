"""Prepare independent local proxy accounts; no Paper account/API or funding action."""
from datetime import datetime,timezone
from pathlib import Path
import json
import argparse
import exchange_calendars as xc

from collector import ROOT,admission,canonical,windows


def prepare(root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    if xc.__version__!='4.13.2':raise ValueError('CALENDAR_VERSION')
    ledger=admission.load('rc_seed_ledger','research/residual-shadow/ledger.py')
    registered=windows();protocol=json.loads((ROOT/'docs/research/residual-shadow/protocol.json').read_bytes())
    sessions=[d.date().isoformat() for d in xc.get_calendar('XNYS').sessions_in_range(registered[0]['formation'],
        protocol['prospective_evaluation_registration']['terminal_mark'])]
    heads={}
    for selector in ('parent_ordinary','matched_ordinary','matched_relative','matched_residual'):
        for bps in (5,25):
            key=f'{selector}-{bps}bp';journal=ledger.Journal(root/key)
            journal.create(ledger.initialize(sessions,[r['execution'] for r in registered],bps))
            state,head,_=journal.replay()
            if state['units'] or state['cursor']!=0:raise ValueError('INITIAL_ACCOUNT_NOT_EMPTY')
            heads[key]=dict(path=key,head_sha256=head)
    config=dict(root=str(root),heads=heads)
    (root/'ledger-heads.json').write_bytes(canonical(config)+b'\n')
    held=admission.verified_holdings(root,heads,datetime.now(timezone.utc),registered)
    if held:raise ValueError('INITIAL_HOLDINGS_NONEMPTY')
    result=dict(version='RC1',status='EMPTY_LOCAL_PROXY_JOURNALS_PREPARED',created_at=datetime.now(timezone.utc).isoformat(),
                journal_count=len(heads),initial_usd_per_independent_proxy='100000',held_names=0,
                journal_heads_independently_audited=True,existing_journals_modified=False,
                paper_account_accessed=False,real_funding_actions=0,orders=0,prospective_observations=0)
    (root/'preparation.json').write_bytes(canonical(result)+b'\n')
    return result


if __name__=='__main__':
    from collector import verify_code
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);args=p.parse_args()
    verify_code();print(json.dumps(prepare(args.root),indent=2))
