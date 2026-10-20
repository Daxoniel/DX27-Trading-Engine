"""Offline, dated SOXX earnings blackout; original SOXL rules are unchanged."""
from copy import deepcopy
from datetime import date

from soxl_reversal import require


MODES = ('ANNOUNCEMENT_AND_NEXT_SESSION', 'ANNOUNCEMENT_ONLY', 'NEXT_SESSION_ONLY')


def latest_snapshot(snapshots, day):
    eligible = [s for s in snapshots if s['filing_date'] < day]
    require(bool(eligible), 'UNKNOWN_HOLDINGS_COVERAGE:' + day)
    # A later amendment of an older portfolio does not roll holdings backwards.
    result = max(eligible, key=lambda s: (s['asof'], s['filing_date'], s['accession']))
    require(result['asof'] <= result['filing_date'], 'FUTURE_PORTFOLIO_DATE')
    require(len(result['top5']) == 5 and len({r['symbol'] for r in result['top5']}) == 5,
            'FIVE_DISTINCT_EQUITY_ISSUERS_REQUIRED')
    return result


def blackout_dates(events, snapshots, calendar, mode):
    require(mode in MODES, 'UNKNOWN_BLACKOUT_MODE')
    require(calendar == sorted(set(calendar)), 'SORTED_UNIQUE_CALENDAR_REQUIRED')
    calendar_set = set(calendar)
    excluded, evidence = set(), []
    seen = set()
    for e in events:
        require(e.get('verified') is True and e.get('source_url') and e.get('source_sha256'),
                'VERIFIED_EVENT_REQUIRED')
        day = e['announcement_date']
        date.fromisoformat(day)
        key = (e['symbol'], day)
        require(key not in seen, 'DUPLICATE_ISSUER_EVENT_DAY')
        seen.add(key)
        snapshot = latest_snapshot(snapshots, day)
        if e['symbol'] not in {r['symbol'] for r in snapshot['top5']}:
            continue
        dates = []
        if mode != 'NEXT_SESSION_ONLY' and day in calendar_set:
            dates.append(day)
        if mode != 'ANNOUNCEMENT_ONLY':
            following = next((d for d in calendar if d > day), None)
            if following is not None:
                dates.append(following)
        excluded.update(dates)
        evidence.append(dict(symbol=e['symbol'], announcement_date=day,
             blackout_dates=dates, holdings_asof=snapshot['asof'],
             holdings_filing_date=snapshot['filing_date'], holdings_accession=snapshot['accession'],
             source_url=e['source_url']))
    return excluded, evidence


def apply_blackout(ledger, dates):
    """Retain every original session for paired cash/equity accounting."""
    result = []
    for row in ledger:
        r = deepcopy(row)
        r['earnings_blackout'] = row['date'] in dates
        if r['earnings_blackout']:
            r.update(side=0, trade_return=0., gross_trade_return=0., portfolio_return=0., mae=0., mfe=0.)
        result.append(r)
    return result
