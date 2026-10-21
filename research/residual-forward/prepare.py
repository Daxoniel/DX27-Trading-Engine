"""Read-only French factor receipt and fixed-budget preparation; never emits orders."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import urllib.request
import zipfile

URL = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip'
ROOT = Path(__file__).resolve().parents[2]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('REDIRECT_REJECTED')


def factor_months(blob):
    rows = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        files = archive.namelist()
        if len(files) != 1 or archive.getinfo(files[0]).file_size > 2_000_000:
            raise ValueError('UNEXPECTED_ARCHIVE')
        for line in archive.read(files[0]).decode('utf-8-sig').splitlines():
            fields = [x.strip() for x in line.split(',')]
            if not re.fullmatch(r'\d{6}', fields[0]):
                continue
            month = datetime.strptime(fields[0], '%Y%m').strftime('%Y-%m')
            if month in rows or len(fields) != 5:
                raise ValueError('DUPLICATE_OR_INVALID_MONTH')
            values = [Decimal(x) for x in fields[1:]]
            if any(not x.is_finite() or x in (Decimal('-99.99'), Decimal('-999')) for x in values):
                raise ValueError('INVALID_FACTOR')
            rows[month] = values
    if not rows:
        raise ValueError('EMPTY_FACTORS')
    return set(rows)


def required_months():
    return [f'{(2023*12+9+i)//12:04d}-{(2023*12+9+i)%12+1:02d}' for i in range(36)]


def allocation(equity, candidates):
    """Target-only budget: no leverage, no redistribution of unused slots."""
    equity = Decimal(str(equity))
    if not equity.is_finite() or equity <= 0:
        raise ValueError('INVALID_EQUITY')
    if len(candidates) > 10 or len({x['symbol'] for x in candidates}) != len(candidates):
        raise ValueError('INVALID_TARGETS')
    sectors = {}
    for row in candidates:
        if not row['symbol'] or row['symbol'] == 'SOXL' or not row['sector']:
            raise ValueError('INVALID_IDENTITY')
        sectors[row['sector']] = sectors.get(row['sector'], 0) + 1
    if any(n > 2 for n in sectors.values()):
        raise ValueError('SECTOR_CAP')
    # Each occupied slot is 1% of account; costs must fit inside stock budget.
    name = equity * Decimal('.01')
    return dict(stock_budget_usd=str(equity * Decimal('.10')),
                target_notional_per_name_before_costs_usd=str(name),
                target_stock_notional_before_costs_usd=str(name * len(candidates)),
                cash_before_costs_usd=str(equity - name * len(candidates)),
                costs_included=False, executable=False)


def calendar_window():
    import exchange_calendars as xc
    if xc.__version__ != '4.13.2':
        raise ValueError('UNPINNED_CALENDAR')
    cal = xc.get_calendar('XNYS')
    sessions = cal.sessions_in_range('2026-10-01', '2026-11-06')
    formation = [x for x in sessions if x.month == 10][-1]
    later = [x for x in sessions if x > formation]
    return dict(formation=str(formation.date()), execution=str(later[1].date()),
                formation_close=cal.session_close(formation).isoformat(),
                execution_open=cal.session_open(later[1]).isoformat(),
                calendar_version=xc.__version__)


def report(blob, observed_at, window, protocol_bytes):
    now = datetime.fromisoformat(observed_at)
    if now.tzinfo is None:
        raise ValueError('UTC_RECEIPT_REQUIRED')
    months = factor_months(blob)
    missing = sorted(set(required_months()) - months)
    blockers = ['FRESH_PRICES_NOT_CAPTURED', 'IDENTITIES_AND_ACTIONS_NOT_VERIFIED',
                'INDEPENDENT_RANK_AUDIT_NOT_RUN', 'SHADOW_LEDGER_NOT_IMPLEMENTED',
                'EVALUATION_PROTOCOL_NOT_REGISTERED']
    if now < datetime.fromisoformat(window['formation_close']):
        blockers.append('FORMATION_NOT_CLOSED')
    if now >= datetime.fromisoformat(window['execution_open']):
        blockers.append('CYCLE_DEADLINE_MISSED')
    if missing:
        blockers.append('FACTOR_MONTHS_MISSING')
    protocol = json.loads(protocol_bytes)
    if window['formation'] != protocol['first_formation'] or window['execution'] != protocol['expected_second_later_session']:
        raise ValueError('CALENDAR_PROTOCOL_MISMATCH')
    return dict(version='RF1', status='BLOCKED_PREPARATION_ONLY', observed_at=observed_at,
                protocol_sha256=sha256(protocol_bytes).hexdigest(), calendar=window,
                factor_receipt=dict(source=URL, sha256=sha256(blob).hexdigest(), bytes=len(blob),
                                    latest_month=max(months), missing_required_months=missing,
                                    receipt_is_not_original_publication_time=True),
                blockers=blockers, illustrative_budget=allocation(protocol['shadow_initial_equity_usd'], []),
                stock_budget_fraction=protocol['stock_budget_fraction'], prior_screen='FAIL_RETAINED',
                signal_computed=False, broker_accessed=False, orders_sent=0,
                persistent_scheduler_installed=False, performance_evaluated=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    # Refuse an existing run directory before any request; no overwrite/relabel.
    args.output.mkdir(parents=True, exist_ok=False)
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(URL, timeout=30) as response:
        if response.status != 200:
            raise ValueError('HTTP_STATUS')
        blob = response.read(2_000_001)
    if len(blob) > 2_000_000:
        raise ValueError('RESPONSE_TOO_LARGE')
    observed = datetime.now(timezone.utc).isoformat()
    (args.output/'ff3.zip').write_bytes(blob)
    protocol = (ROOT/'docs/research/residual-forward/protocol.json').read_bytes()
    result = report(blob, observed, calendar_window(), protocol)
    (args.output/'receipt.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
