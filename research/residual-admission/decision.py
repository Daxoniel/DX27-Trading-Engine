"""On-demand, current-clock input decision receipt; never submits or marks trades."""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path

import admission
from snapshots import canonical


def verify_code():
    groups=[('residual-admission','code-seal.json'),('residual-admission','integration-seal.json'),
            ('residual-shadow','code-seal.json'),('residual-momentum','code-seal-v2.json'),
            ('sector-momentum','code-seal.json')]
    for group,name in groups:
        public=admission.ROOT/'docs/research'/group
        seal=json.loads((public/name).read_bytes())
        for filename,expected in seal.get('files',seal).items():
            if sha256((admission.ROOT/'research'/group/filename).read_bytes()).hexdigest()!=expected:
                raise ValueError('EXECUTION_CODE_SEAL')
        if 'protocol_sha256' in seal and sha256((public/'protocol.json').read_bytes()).hexdigest()!=seal['protocol_sha256']:
            raise ValueError('PROTOCOL_SEAL')
        if 'amendment_sha256' in seal and sha256((public/'input-amendment.json').read_bytes()).hexdigest()!=seal['amendment_sha256']:
            raise ValueError('AMENDMENT_SEAL')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    # Reserve output before reading inputs; no overwriting or backdated --asof option.
    with args.output.open('xb') as stream:
        now=datetime.now(timezone.utc).isoformat();manifest_bytes=args.manifest.read_bytes()
        manifest=json.loads(manifest_bytes)
        try:
            verify_code()
            result=admission.admit(args.manifest.parent,manifest,now)
        except (ValueError,KeyError,TypeError,OSError,ArithmeticError) as error:
            result=dict(status='BLOCKED',blockers=['INVALID_OR_INCOMPLETE_EVIDENCE'],failure_type=type(error).__name__,
                        execution_enabled=False,orders=0,automatic_promotion=False)
        result.update(decided_at=now,manifest_sha256=sha256(manifest_bytes).hexdigest(),
                      economic_or_source_authenticity_attested=False)
        stream.write(canonical(result)+b'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
