"""Actual-clock read-only preflight, no source access or journal writes."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research/residual-alias-admission'))
from decide import verify_code as parent_verify

def verify_code():
    parent_verify()
    seal=json.loads((ROOT/'docs/research/residual-daily/code-seal.json').read_bytes())
    for name,digest in seal['files'].items():
        if sha256((Path(__file__).parent/name).read_bytes()).hexdigest()!=digest:raise ValueError('RD1_CODE_SEAL')
    if sha256((ROOT/'docs/research/residual-daily/protocol.md').read_bytes()).hexdigest()!=seal['protocol_sha256']:raise ValueError('RD1_PROTOCOL_SEAL')

def preflight():
    verify_code();now=datetime.now(timezone.utc)
    first=json.loads((ROOT/'docs/research/residual-shadow/calendar.json').read_bytes())['planned_cycles'][0]
    before=now<datetime.fromisoformat(first['formation_close'].replace('Z','+00:00'))
    return dict(observed_at=now.isoformat(),status='BLOCKED_FORMATION_NOT_CLOSED' if before else 'BLOCKED_SYNTHETIC_ONLY_NO_PRODUCTION_ADAPTER',
                source_requests=0,journal_writes=0,orders=0,prospective_observations=0)

if __name__=='__main__': print(json.dumps(preflight(),indent=2))
