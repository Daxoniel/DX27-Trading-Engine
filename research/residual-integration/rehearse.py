"""Two nonempty synthetic cycles with real admission/accounting; aggregate receipt only."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import argparse

from fixture import Scenario
from transition import admission,apply,auditor


def verify_seals():
    import decision
    decision.verify_code()
    root=admission.ROOT/'docs/research/residual-integration'
    seal=json.loads((root/'code-seal.json').read_bytes())
    if sha256((root/'protocol.json').read_bytes()).hexdigest()!=seal['protocol_sha256']:
        raise ValueError('RI_PROTOCOL_SEAL')
    for name,h in seal['files'].items():
        if sha256((admission.ROOT/'research/residual-integration'/name).read_bytes()).hexdigest()!=h:
            raise ValueError('RI_EXECUTION_SEAL')


def run(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);verify_seals()
    scenario=Scenario(output/'SYNTHETIC');scenario.mark_until('2026-11-02')
    first=scenario.bundle(0)
    with scenario.cohort_boundary():
        first_result=apply(scenario.root,*first[:2],*first[2:4])
    previous={key:set(j.replay()[0]['units']) for key,j in scenario.journals.items()}
    scenario.mark_until('2026-12-01');second=scenario.bundle(1)
    exited=sum(len(names-{r['symbol'] for r in second[-1]['plans'][key.rsplit('-',1)[0]]}) for key,names in previous.items())
    if exited==0: raise ValueError('REHEARSAL_MUST_INCLUDE_EXITS')
    with scenario.cohort_boundary():
        second_result=apply(scenario.root,*second[:2],*second[2:4])
    checks={key:auditor.audit(scenario.root/key) for key in scenario.journals}
    if any(value['status']!='PASS' or value['halted'] for value in checks.values()):
        raise ValueError('FINAL_ACCOUNT_AUDIT')
    result=dict(version='RI1',status='NONEMPTY_SYNTHETIC_INTEGRATION_PASS',
        actual_rehearsal_completed_at=datetime.now(timezone.utc).isoformat(),data_origin='DETERMINISTIC_SYNTHETIC_NOT_MARKET_DATA',
        clock_origin='REGISTERED_FUTURE_DATES_USED_AS_TEST_CLOCKS_ONLY',
        synthetic_formations=2,synthetic_common_stock_peers=55,original_rules_and_rankings_used=True,
        eligible_features_checked=sum(x[-1]['independently_checked_features'] for x in (first,second)),
        unique_symbol_formation_score_checks=sum(x[-1]['independently_checked_scores'] for x in (first,second)),
        successful_transitions=2,case_transitions=first_result['cases']+second_result['cases'],
        name_slots_per_account_per_cycle=10,old_holdings_exited_across_selector_cost_cases=exited,
        final_account_audits=checks,independently_checked_daily_account_marks=sum(c['independently_checked_marks'] for c in checks.values()),
        cohort_hash_substitution='SYNTHETIC_COHORT_BOUNDARY_ONLY',other_positive_path_validators_mocked=False,
        live_prices_captured=False,real_formation_identities_approved=0,new_live_signals=0,
        prospective_observations=0,orders=0,automatic_promotion=False,prior_full_exposure_screen='FAIL_RETAINED')
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='final_account_audits'},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    run(p.parse_args().output)
