"""Current-clock AA1 decision only. No network, journal mutation or order interface."""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path

import gate


def verify_code():
    gate.collector.verify_code()
    public=gate.ROOT/'docs/research/residual-alias-admission';seal=json.loads((public/'code-seal.json').read_bytes())
    gate.require(sha256((public/'protocol.json').read_bytes()).hexdigest()==seal['protocol_sha256'],'AA_PROTOCOL_SEAL')
    for name,h in seal['files'].items():
        gate.require(sha256((Path(__file__).parent/name).read_bytes()).hexdigest()==h,'AA_CODE_SEAL')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--formation',required=True)
    p.add_argument('--capture',type=Path);p.add_argument('--reviews',type=Path);p.add_argument('--registry',type=Path)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args();verify_code()
    window=next((r for r in gate.collector.windows() if r['formation']==args.formation),None)
    if window is None:p.error('unregistered formation')
    with args.output.open('xb') as stream:
        now=datetime.now(timezone.utc).isoformat();aliases={};reviews={}
        try:
            if gate.collector.window_state(window,gate.legacy.utc(now))=='IN_WINDOW':
                if None in (args.capture,args.reviews,args.registry):raise ValueError('FORMATION_EVIDENCE_REQUIRED')
                cohort=json.loads((args.capture/'cohort.json').read_bytes())
                aliases=gate.registry.load(args.registry,{r['symbol'] for r in cohort})
                reviews=json.loads(args.reviews.read_bytes())
            result=gate.assess(args.capture,window,reviews,aliases,now)
        except (ValueError,KeyError,TypeError,OSError,ArithmeticError) as error:
            result=dict(status='BLOCKED_EVIDENCE_INVALID_OR_INCOMPLETE',failure_type=type(error).__name__,
                failure_code=str(error) if isinstance(error,ValueError) else 'MISSING_OR_INVALID_EVIDENCE',
                execution_enabled=False,orders=0,automatic_promotion=False)
        result.update(decided_at=now,network_requests=0)
        stream.write(gate.canonical(result)+b'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
