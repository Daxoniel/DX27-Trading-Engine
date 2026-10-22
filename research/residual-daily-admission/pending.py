"""Daily documentary-review templates: deliberately no approval fields prefilled."""
from pathlib import Path
import json
from evidence import canonical,require,sha256


def prepare(capture,output):
    capture=Path(capture);blob=(capture/'manifest.json').read_bytes();m=json.loads(blob)
    require(m['version']=='DE1_DAILY','DAILY_MANIFEST_REQUIRED')
    output=Path(output);output.mkdir(parents=True,exist_ok=False);pending=[]
    for b in m['metadata_bindings']:
        row=dict(canonical=b['canonical'],metadata_lookup=b['metadata_lookup'],asset_id=b['asset_id'],
                 capture_manifest_sha256=sha256(blob).hexdigest(),cohort_sha256=m['cohort_sha256'],
                 action_response_hashes=[r['response_sha256'] for r in m['source_refs'] if r['request']['kind']=='actions'],
                 status='PENDING_NOT_APPROVED',instrument_type=None,reviewer=None,reviewed_at=None,
                 continuity_reason='',action_accounting_reason='',unmodeled_actions=None,sources=[])
        name=b['canonical']+'.pending.json'
        with (output/name).open('xb') as stream:stream.write(canonical(row)+b'\n')
        pending.append(name)
    result=dict(status='PENDING_NOT_APPROVED',pending_templates=pending,approved_reviews=0,orders=0,journal_writes=0)
    (output/'checklist.json').write_bytes(canonical(result)+b'\n');return result
