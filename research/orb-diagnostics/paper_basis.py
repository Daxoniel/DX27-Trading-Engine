"""Paper-scoped research summary; no network, strategy replay or order methods."""
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
import argparse
import json

from fixed_artifacts import diagnose, load, close, serialize, require


def fixed_fill_views(arm):
    gross = D(str(arm['gross_pnl']))
    commission = D(str(arm['commission']))
    spread = D(str(arm['spread_cost']))
    slippage = D(str(arm['slippage_cost']))
    original = D(str(arm['net_pnl']))
    turnover = D(str(arm['reference_turnover']))
    require(all(v.is_finite() for v in (gross,commission,spread,slippage,original,turnover)), 'NONFINITE_ACCOUNTING')
    require(min(commission,spread,slippage,turnover) >= 0,'NEGATIVE_COST_OR_TURNOVER')
    close(gross-commission-spread-slippage, original)
    zero_commission = gross-spread-slippage
    return dict(original_model_net_pnl=original,
        no_explicit_cost_reference_price_pnl=gross,
        no_broker_commission_with_old_price_friction_pnl=zero_commission,
        commission_credit=commission, old_spread_cost=spread,old_slippage_cost=slippage,
        fixed_fill_extra_friction=[dict(additional_bps=b,
            pnl=zero_commission-D(b)*turnover/10000) for b in (0,1,2,5)],
        model_rerun=False,capital_and_size_recomputed=False,
        actual_alpaca_paper_pnl=None,
        interpretation='FIXED_OLD_R1_FILLS_ACCOUNTING_SCENARIOS_NOT_BROKER_SIMULATOR_REPLICATION')


def operational_scope(sample):
    require(sample.get('mode')=='PAPER_GET_ONLY_SAMPLE' and sample.get('execution_enabled') is False
            and sample.get('real_orders_sent') is False,'GET_ONLY_PAPER_OBSERVATION_REQUIRED')
    require(sample.get('evidence_complete') is False and sample.get('history_complete') is False,
            'SAMPLE_IS_NOT_COMPLETE_EVIDENCE')
    endpoints=sample['endpoints']
    return dict(paper_endpoint='https://paper-api.alpaca.markets',
        sampling_complete=sample.get('sampling_complete') is True,
        endpoints_observed=sorted(k for k,v in endpoints.items() if v.get('status')=='OBSERVED'),
        history_complete=False,strategy_ownership_verified=False,
        actual_strategy_paper_pnl=None,verified_zero_fees=False,
        empty_or_missing_activity_is_not_fee_or_profit_evidence=True)


def run(root, sample_path):
    root=Path(root).resolve();stages={}
    sample=load(sample_path)
    observation=operational_scope(sample)
    for stage in ('A','B'):
        summary=diagnose(stage,root/f'work/orb-stage-{stage.lower()}/attempt-1',
                         root/f'docs/reports/orb-stage-{stage.lower()}')
        stages[stage]=fixed_fill_views(summary['arms']['R1']['all'])
    return dict(status='COMPLETE_PAPER_SCOPED_ENGINEERING_REFERENCE',
        created_at=datetime.now(timezone.utc).isoformat(),research_basis='ALPACA_PAPER',
        real_account_fee_calibration_required_for_paper_engineering=False,
        live_trading_effectiveness='NOT_EVALUATED',execution_enabled=False,
        strategy_replayed=False,new_market_data_downloaded=False,
        operational_observation=observation,exposed_historical_stages=stages)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--sample',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    result=run(args.root,args.sample)
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(result,f,default=serialize,indent=2,allow_nan=False);f.write('\n')
