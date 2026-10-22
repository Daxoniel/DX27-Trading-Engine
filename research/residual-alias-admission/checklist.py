"""Create pending identity-review templates; never issues an approval."""
from hashlib import sha256
import json
from pathlib import Path
from gate import admission,canonical,require


def prepare(capture,output):
    capture=Path(capture);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    blob=(capture/'manifest.json').read_bytes();manifest=json.loads(blob)
    require(manifest['version']=='RC1','RC1_REQUIRED')
    capture_hash=sha256(blob).hexdigest();pending=[]
    action_hashes=[r['response_sha256'] for r in manifest['action_refs']]
    for binding in manifest['metadata_bindings']:
        row=dict(canonical=binding['canonical'],metadata_lookup=binding['metadata_lookup'],asset_id=binding['asset_id'],
                 capture_manifest_sha256=capture_hash,cohort_sha256=manifest['cohort_sha256'],
                 action_response_hashes=action_hashes,status='PENDING_NOT_APPROVED',instrument_type=None,
                 reviewer=None,reviewed_at=None,continuity_reason='',action_accounting_reason='',
                 unmodeled_actions=None,sources=[])
        name=binding['canonical']+'.pending.json'
        with (output/name).open('xb') as stream:stream.write(canonical(row)+b'\n')
        pending.append(name)
    result=dict(status='PENDING_NOT_APPROVED',capture_manifest_sha256=capture_hash,pending_templates=pending,
                approved_reviews=0,execution_enabled=False,orders=0)
    (output/'checklist.json').write_bytes(canonical(result)+b'\n')
    return result


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    print(json.dumps(prepare(a.capture,a.output),indent=2))
