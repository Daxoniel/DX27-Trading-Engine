"""Evidence-bound metadata lookup alias; never rewrites price/universe symbols."""
from datetime import date,datetime,timezone
from hashlib import sha256
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def validate(rows,cohort):
    if not isinstance(rows,list) or len(rows)>1: raise ValueError('UNREGISTERED_ALIAS')
    seen=set()
    for row in rows:
        if (row['canonical']!='VSCO' or row['lookup']!='VSXY' or row['effective_date']!='2026-06-02'
            or row['cusip']!='926400102' or not row.get('asset_id') or row['canonical'] not in cohort
            or row['lookup'] in cohort or row['lookup'] in seen):
            raise ValueError('ALIAS_SCOPE_OR_COLLISION')
        seen.add(row['lookup'])
    return {row['canonical']:row for row in rows}


def bind(symbol,asset,aliases,observed_date):
    row=aliases.get(symbol);lookup=symbol
    if row:
        if observed_date<date.fromisoformat(row['effective_date']): raise ValueError('ALIAS_NOT_YET_EFFECTIVE')
        lookup=row['lookup']
        if asset.get('id')!=row['asset_id']: raise ValueError('ALIAS_UUID_CHANGED')
    if (asset.get('symbol')!=lookup or asset.get('class')!='us_equity' or asset.get('status')!='active'
        or asset.get('tradable') is not True or not asset.get('id')):
        raise ValueError('ASSET_UNRESOLVED')
    return dict(canonical=symbol,metadata_lookup=lookup,asset_id=asset['id'],
                alias_used=row is not None,economic_identity_review_complete=False)


def build(output):
    """Bind the reviewed RI1 raw documentary case to one immutable private registry."""
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    case_root=ROOT/'work/residual-integration/identity-1'
    public=json.loads((ROOT/'docs/research/residual-integration/identity-case.json').read_bytes())
    blob=(case_root/'evidence.json').read_bytes()
    if sha256(blob).hexdigest()!=public['case_sha256']: raise ValueError('CASE_EVIDENCE_SEAL')
    evidence=json.loads(blob)
    for name in ('sec','issuer'):
        ref=next(r for r in public['source_receipts'] if r['source']==name)
        document=(case_root/f'{name}.html').read_bytes()
        if ref['status']!='OBSERVED' or sha256(document).hexdigest()!=ref['sha256']:
            raise ValueError('DOCUMENT_SEAL')
    ref=evidence['asset_receipt'];asset_blob=(case_root/'asset-current'/ref['path']).read_bytes()
    if sha256(asset_blob).hexdigest()!=public['asset_response_sha256'] or json.loads(asset_blob)!=evidence['current_asset']:
        raise ValueError('ASSET_EVIDENCE_SEAL')
    event=evidence['mapping'];asset=evidence['current_asset']
    if (event['old_symbol'],event['new_symbol'],event['old_cusip'],event['new_cusip'],event['process_date'])!=('VSCO','VSXY','926400102','926400102','2026-06-02'):
        raise ValueError('DOCUMENTED_MAPPING_MISMATCH')
    rows=[dict(canonical='VSCO',lookup='VSXY',effective_date='2026-06-02',cusip=event['old_cusip'],
               asset_id=asset['id'],case_sha256=public['case_sha256'])]
    aliases=validate(rows,{'VSCO'});bind('VSCO',asset,aliases,datetime.now(timezone.utc).date())
    registry=dict(version='RC1',cohort_asof='2025-04-25',aliases=rows)
    raw=json.dumps(registry,sort_keys=True,separators=(',',':')).encode()+b'\n'
    (output/'registry.json').write_bytes(raw)
    receipt=dict(version='RC1',registry_sha256=sha256(raw).hexdigest(),documentary_case_sha256=public['case_sha256'],
                 documentary_sources_checked=2,current_alias_asset_checked=True,metadata_aliases=1,
                 price_aliases=0,universe_additions=0,formation_ready_identities=0,
                 created_at=datetime.now(timezone.utc).isoformat(),orders=0)
    (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


def load(path,cohort):
    raw=Path(path).read_bytes()
    receipt=json.loads((ROOT/'docs/research/residual-capture/registry-receipt.json').read_bytes())
    if sha256(raw).hexdigest()!=receipt['registry_sha256']: raise ValueError('REGISTRY_SEAL')
    registry=json.loads(raw)
    if registry['version']!='RC1' or registry['cohort_asof']!='2025-04-25': raise ValueError('REGISTRY_SCHEMA')
    aliases=validate(registry['aliases'],cohort)
    for row in aliases.values():
        if row['case_sha256']!=receipt['documentary_case_sha256']: raise ValueError('REGISTRY_CASE_BINDING')
    return aliases


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    print(json.dumps(build(p.parse_args().output),indent=2))
