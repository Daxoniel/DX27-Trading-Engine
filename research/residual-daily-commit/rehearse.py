"""Retained synthetic DC1 rehearsal; not real-source marks or Paper orders."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
import guard as g
from test_commit import CommitTests, CLOCK
from test_evidence import EvidenceTests, AliasScenario, DECISION


def rehearse(output):
    g.verify_code();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    case=EvidenceTests('test_native_preopen_to_daily_is_read_only_and_alias_preserved')
    case.root=output;case.f=AliasScenario(output/'SYNTHETIC');case.s=case.f.scenario;case.out=output/'entry'
    with patch.object(g.e.gate,'COHORT_HASH',case.s.cohort_hash):
        case.record=g.e.formation_seal(case.f.capture,case.f.reviews,case.f.aliases,DECISION);case.h=g.e.digest(case.record)
        case.capture();reviews=case.reviews();proposal=case.assess(reviews)
        (output/'formation-seal.json').write_bytes(g.e.canonical(case.record)+b'\n')
        first=g.commit(case.out,case.record,case.h,reviews,proposal,g.e.digest(proposal),lambda:CLOCK)
        (output/'entry-proposal.json').write_bytes(g.e.canonical(proposal)+b'\n')
        case.out=output/'held'
        case.capture('2026-11-04',g.e.legacy.utc('2026-11-04T21:25:00+00:00'))
        reviews=case.reviews('2026-11-04T21:26:00+00:00');proposal=case.assess(reviews,'2026-11-04T21:27:00+00:00')
        second=g.commit(case.out,case.record,case.h,reviews,proposal,g.e.digest(proposal),
                        lambda:g.e.legacy.utc('2026-11-04T21:28:00+00:00'))
        (output/'held-proposal.json').write_bytes(g.e.canonical(proposal)+b'\n')
        audits=[g.e.auditor.audit(j.root) for j in case.s.journals.values()]
        g.require(all(a['status']=='PASS' and not a['halted'] for a in audits),'REHEARSAL_AUDIT')
        summary=dict(status='SYNTHETIC_TWO_DAY_COMMIT_PASS',synthetic_accounts=8,synthetic_confirmed_appends=16,
                     synthetic_completed_operations=2,independent_audits=8,synthetic_evidence_retained_privately=True,
                     writer_lock_released=not (case.s.root/g.LOCK).exists(),real_source_requests=0,
                     real_journal_writes=0,orders=0,prospective_observations=0,atomic_multi_account_transaction=False,
                     clocks_and_prices='SYNTHETIC_FUTURE_NOT_ACTUAL_OBSERVATIONS')
        (output/'summary.json').write_bytes(g.e.canonical(summary)+b'\n');return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    print(json.dumps(rehearse(a.output),indent=2))
