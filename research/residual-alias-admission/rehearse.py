"""Explicit synthetic alias path and pending-review checklist engineering receipt."""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path

from alias_fixture import AliasScenario
from checklist import prepare
from decide import verify_code
from gate import canonical


def run(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);verify_code()
    fixture=AliasScenario(output/'SYNTHETIC');heads=fixture.scenario.heads()
    original={p.name:sha256(p.read_bytes()).hexdigest() for p in (fixture.capture/'sources').glob('*.body')}
    pending=prepare(fixture.capture,output/'PENDING-SYNTHETIC-REVIEWS')
    result=fixture.assess()
    if heads!=fixture.scenario.heads():raise ValueError('JOURNAL_MUTATION')
    if original!={p.name:sha256(p.read_bytes()).hexdigest() for p in (fixture.capture/'sources').glob('*.body')}:
        raise ValueError('SOURCE_MUTATION')
    summary=dict(version='AA1',status='SYNTHETIC_ALIAS_ADMISSION_REHEARSAL_PASS',
                 actual_completed_at=datetime.now(timezone.utc).isoformat(),data_origin='SYNTHETIC_NOT_PROVIDER_OR_ISSUER_DATA',
                 test_clock='2026-11-03T13:10:00+00:00_USED_ONLY_AS_SYNTHETIC_TIME',
                 stock_peers=55,canonical_metadata_aliases_checked=result['metadata_aliases'],
                 independently_audited_scores=result['audited_scores'],synthetic_identity_reviews=result['reviewed_identities'],
                 original_source_bodies_unchanged=len(original),external_journals_unchanged=len(heads),
                 checklist_templates=len(pending['pending_templates']),checklist_approved_reviews=pending['approved_reviews'],
                 synthetic_decision_status=result['status'],execution_enabled=False,
                 real_identity_approvals=0,real_source_requests=0,prospective_observations=0,orders=0,
                 positive_path_validation='Actual RC1 source/model/identity/journal validators; synthetic transport and input registry seed; cohort hash boundary only',
                 production_registry_anchor='Separately verified against retained real RC1 registry; fixture seed is not production evidence')
    (output/'summary.json').write_bytes(canonical(summary)+b'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    run(p.parse_args().output)
