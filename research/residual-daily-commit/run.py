"""Actual-clock DC1 CLI: local proxy marks only, never broker orders."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
from guard import commit,verify_code,e,require


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['preflight','commit'])
    for name in ('capture','seal','reviews','proposal','registry'):p.add_argument('--'+name,type=Path)
    p.add_argument('--seal-sha256');p.add_argument('--proposal-sha256');p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();verify_code();clock=lambda:datetime.now(timezone.utc);now=clock()
    if now<e.legacy.utc(e.gate.collector.windows()[0]['formation_close']):
        result=dict(status='BLOCKED_FORMATION_NOT_CLOSED',observed_at=now.isoformat(),network_requests=0,
                    journal_writes=0,lock_created=False,orders=0)
    elif args.mode=='preflight':
        result=dict(status='EXPLICIT_EVIDENCE_REQUIRED_NO_AUTOMATIC_COMMIT',observed_at=now.isoformat(),
                    network_requests=0,journal_writes=0,lock_created=False,orders=0)
    else:
        if any(v is None for v in (args.capture,args.seal,args.reviews,args.proposal,args.registry,args.seal_sha256,args.proposal_sha256)):
            p.error('commit requires capture, seal/hash, reviews, proposal/hash, registry')
        record=json.loads(args.seal.read_bytes())
        require(e.digest(record)==args.seal_sha256,'FORMATION_SEAL_HASH')
        cohort=json.loads((Path(record['capture'])/'cohort.json').read_bytes())
        require(record['aliases']==e.gate.registry.load(args.registry,{r['symbol'] for r in cohort}),'PUBLISHED_REGISTRY_BINDING')
        manifest,_=e.validate_seal(record,args.seal_sha256)
        output=args.output.resolve()
        require(not any(output.is_relative_to(path) for path in (args.capture.resolve(),Path(record['capture']).resolve(),Path(manifest['ledgers']['root']).resolve()))
                and not output.exists(),'NEW_EXTERNAL_OUTPUT_REQUIRED')
        # Reserve the result filename before any account mutation; failure leaves an
        # empty output plus authoritative account-root operation/lock receipts.
        with args.output.open('xb') as stream:
            result=commit(args.capture,record,args.seal_sha256,json.loads(args.reviews.read_bytes()),
                          json.loads(args.proposal.read_bytes()),args.proposal_sha256,clock)
            stream.write(e.canonical(result)+b'\n')
        print(json.dumps(dict(status=result['status'],journal_writes=result['journal_writes'],orders=0),indent=2));return
    with args.output.open('xb') as stream:stream.write(e.canonical(result)+b'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
