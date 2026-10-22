"""Explicit synthetic source-to-proposal rehearsal. No network or real ledger writes."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
from cli import verify_code
from evidence import canonical, inventory
from test_evidence import EvidenceTests, AliasScenario, DECISION, e


def rehearse(output):
    verify_code();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    case=EvidenceTests('test_native_preopen_to_daily_is_read_only_and_alias_preserved')
    case.root=output;case.f=AliasScenario(output/'SYNTHETIC');case.s=case.f.scenario;case.out=output/'daily'
    with patch.object(e.gate,'COHORT_HASH',case.s.cohort_hash):
        case.record=e.formation_seal(case.f.capture,case.f.reviews,case.f.aliases,DECISION);case.h=e.digest(case.record)
        before=case.bundle();formation_inventory=inventory(case.f.capture)
        case.capture();reviews=case.reviews();result=case.assess(reviews)
        if case.bundle()!=before or inventory(case.f.capture)!=formation_inventory:raise ValueError('READ_ONLY_REHEARSAL_MUTATION')
        (output/'formation-seal.json').write_bytes(canonical(case.record)+b'\n')
        (output/'daily-reviews.json').write_bytes(canonical(reviews)+b'\n')
        (output/'private-proposal.json').write_bytes(canonical(result)+b'\n')
        summary=dict(status='SYNTHETIC_SOURCE_TO_PROPOSAL_PASS',synthetic_formation_scores=case.record['decision']['audited_scores'],
            synthetic_daily_identities=result['reviewed_identities'],synthetic_source_bodies=len(case.m['source_refs']),
            synthetic_proposals=len(result['requests']),formation_seal_sha256=case.h,daily_proposal_sha256=result['proposal_sha256'],
            formation_evidence_unchanged=True,eight_synthetic_journal_heads_unchanged=True,synthetic_evidence_retained_privately=True,
            transport='SYNTHETIC_RC1_NOT_HTTP',clocks='SYNTHETIC_FUTURE_NOT_ACTUAL_OBSERVATIONS',
            real_source_requests=0,real_reviews_approved=0,real_journal_writes=0,orders=0,prospective_observations=0)
        (output/'summary.json').write_bytes(canonical(summary)+b'\n');return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    print(json.dumps(rehearse(a.output),indent=2))
