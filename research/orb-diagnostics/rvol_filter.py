"""One literature-motivated QQQ/R1 transfer hypothesis; exposed-data exploration.

No fitting or threshold search. Frozen fixture handles fills/risk/fees; only
entry eligibility changes. This is not the paper's stocks-in-play replication.
"""
from dataclasses import asdict
from decimal import Decimal

from dx27.research.opening_direction import OpeningDirectionFixture, MINUTE
from paper_intents import require


def opening_rvol(prior_volumes,current_volume):
    require(len(prior_volumes)>=14,'FOURTEEN_PRIOR_SESSIONS_REQUIRED')
    values=[Decimal(str(v)) for v in list(prior_volumes)[-14:]]
    current=Decimal(str(current_volume))
    require(all(v.is_finite() and v>0 for v in values+[current]),'POSITIVE_COMPLETE_OPENING_VOLUMES_REQUIRED')
    # Compare cross-products: the >=1 boundary has no rounding ambiguity.
    denominator=sum(values)
    return dict(rvol=str(current*14/denominator),eligible=current*14>=denominator,
                prior_sessions=14,current_volume=str(current),prior_volume_sum=str(denominator))


def replay_session(session,bars,starting_cash,*,entry_eligible):
    require(type(entry_eligible) is bool,'EXPLICIT_ENTRY_ELIGIBILITY_REQUIRED')
    expected=int((session.closes_at-session.opens_at)/MINUTE)
    require(len(bars)==expected,'FULL_SESSION_REQUIRED')
    model=OpeningDirectionFixture(session,'R1',starting_cash=starting_cash)
    gated_long=False
    for i,bar in enumerate(bars):
        model.on_closed_minute(session.opens_at+i*MINUTE,bar,as_of=session.opens_at+(i+1)*MINUTE)
        if i==4 and not entry_eligible:
            gated_long=model.direction==1
            model.direction=0
    report=model.report()
    require(report['status']=='COMPLETE_FIXTURE' and report['cash']>0,'INCOMPLETE_OR_NONPOSITIVE_SESSION')
    fills=[dict(asdict(f),at=f.at.isoformat(),session=session.session_id,
                cash_delta=(-1 if f.side=='buy' else 1)*f.quantity*f.price-f.commission) for f in model.fills]
    return dict(report=report,fills=fills,equity=model.equity,decisions=model.decisions,
                gated_long=gated_long,daily=dict(session=session.session_id,starting_equity=starting_cash,
                ending_equity=report['cash'],net_pnl=report['cash']-starting_cash,
                daily_return=report['cash']/starting_cash-1,closed_trades=report['closed_trades']))
