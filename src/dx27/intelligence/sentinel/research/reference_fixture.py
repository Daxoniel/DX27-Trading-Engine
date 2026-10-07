"""Synthetic, varying multi-sensor tape; never used to claim market effectiveness."""
from dataclasses import replace
from datetime import date, timedelta
from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.intelligence.sentinel.market_state import MarketStateBuilder
from dx27.intelligence.sentinel.models import ObservationWindow
import math
from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.research.state_fixture import synthetic_state_fixture


def reference_fixture(protocol, count=170):
    registry, calendar, bindings, points, builder, _, _ = synthetic_state_fixture(protocol, min(count, 251))
    if count > len(calendar.sessions):
        calendar=load_xnys_calendar(date(2025,1,1),date(2026,12,31))
        if count>len(calendar.sessions):raise ValueError('fixture exceeds pinned two-year calendar')
        bindings=tuple(replace(b,validated_at=calendar.sessions[0].opens_at-timedelta(days=1)) for b in bindings)
        examples={p.subject_ref.subject_id:p for p in points}
        points=tuple(replace(p,observation_window=ObservationWindow(s.opens_at,s.closes_at,'1d'),
                    published_at=s.closes_at+timedelta(minutes=10),first_seen_at=s.closes_at+timedelta(minutes=20),
                    source_record_id=s.session_id) for p in examples.values() for s in calendar.sessions[:count])
        builder=MarketStateBuilder(registry,calendar,bindings)
    indices = {s.session_id:i for i,s in enumerate(calendar.sessions)}
    changed=[]
    for point in points:
        i=indices[point.source_record_id]
        feed=point.subject_ref.subject_id.split(':')[1]
        if point.unit=='USD':
            amplitude={'spy':.04,'rsp':.08,'qqq':.06}.get(feed,.03)
            value=100*math.exp(.001*i+amplitude*math.sin(i/11+len(feed)))
        else:
            base={'vix':18,'hy_oas':320,'ust_2y':2.5,'ust_10y':4,'sofr':4.1,'effr':4}[feed]
            value=base*(1+.15*math.sin(i/13))
        changed.append(replace(point,value=value,payload_sha256=stable_content_hash({'fixture':feed,'index':i,'normalized_value':value})))
    return calendar, builder, tuple(changed)
