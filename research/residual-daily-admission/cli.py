"""DE1 actual-clock CLI. Read-only decisions and GET capture; no journal appends/orders."""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from evidence import ROOT, gate, bounds, formation_seal, assess, canonical, digest, require, verify_parent
from capture import collect


def verify_code():
    verify_parent();public=ROOT/'docs/research/residual-daily-admission'
    seal=json.loads((public/'code-seal.json').read_bytes())
    require(sha256((public/'protocol.md').read_bytes()).hexdigest()==seal['protocol_sha256'],'DE_PROTOCOL_SEAL')
    require(sha256((public/'data-availability.md').read_bytes()).hexdigest()==seal['data_availability_sha256'],'DE_AVAILABILITY_SEAL')
    for name,h in seal['files'].items():require(sha256((Path(__file__).parent/name).read_bytes()).hexdigest()==h,'DE_CODE_SEAL')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['preflight','seal','capture','assess','checklist'])
    for name in ('capture','reviews','registry','seal','ledgers'):p.add_argument('--'+name,type=Path)
    p.add_argument('--seal-sha256');p.add_argument('--day');p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();verify_code();clock=lambda:datetime.now(timezone.utc)
    now=clock();first=gate.collector.windows()[0]
    if now<gate.legacy.utc(first['formation_close']):
        result=dict(status='BLOCKED_FORMATION_NOT_CLOSED',observed_at=now.isoformat(),network_requests=0,journal_writes=0,orders=0)
    elif args.mode=='preflight':
        result=dict(status='EVIDENCE_ARGUMENTS_REQUIRED_NO_AUTOMATIC_ACTION',observed_at=now.isoformat(),network_requests=0,journal_writes=0,orders=0)
    elif args.mode=='seal':
        cohort=json.loads((args.capture/'cohort.json').read_bytes());aliases=gate.registry.load(args.registry,{r['symbol'] for r in cohort})
        result=formation_seal(args.capture,json.loads(args.reviews.read_bytes()),aliases,now.isoformat())
    else:
        record=json.loads(args.seal.read_bytes());require(digest(record)==args.seal_sha256,'FORMATION_SEAL_HASH')
        # Production CLI must use the published registry, including on later days.
        cohort=json.loads((Path(record['capture'])/'cohort.json').read_bytes())
        require(record['aliases']==gate.registry.load(args.registry,{r['symbol'] for r in cohort}),'PUBLISHED_REGISTRY_BINDING')
        if args.mode=='capture':
            result=collect(args.output,record,args.seal_sha256,json.loads(args.ledgers.read_bytes()),args.day,clock)
            print(json.dumps(result,indent=2));return
        if args.mode=='checklist':
            from pending import prepare
            # Templates deliberately remain pending, never approved.
            result=prepare(args.capture,args.output);print(json.dumps(result,indent=2));return
        result=assess(args.capture,record,args.seal_sha256,json.loads(args.reviews.read_bytes()),now.isoformat())
    with args.output.open('xb') as stream:stream.write(canonical(result)+b'\n')
    print(json.dumps(dict(status=result.get('status','FORMATION_SEALED_LOCAL_CLOCK'),output_sha256=digest(result),orders=0),indent=2))

if __name__=='__main__':main()
