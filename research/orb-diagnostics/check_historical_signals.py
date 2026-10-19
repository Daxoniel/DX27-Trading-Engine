"""Check all exposed A/B opening prefixes against sealed original R1 artifacts.

Requires the original local CSV/artifacts and pinned evaluation calendar runtime.
No downloads, orders, parameter search, full-session replay or new PnL estimate.
"""
import argparse
from collections import Counter
import csv
from datetime import date, datetime, timedelta
from importlib.metadata import version
import json
from pathlib import Path

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.core.models.market_context import MarketContext
from fixed_artifacts import REPORTS, EXPECTED
from historical_signals import record_historical_entry
from paper_intents import PaperIntentJournal, require
import hashlib


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def check(stage, csv_path, artifacts, output, *, root):
    root, artifacts, output = Path(root), Path(artifacts), Path(output)
    public = root/'docs/reports'/('orb-stage-'+stage.lower())
    require(digest(public/'report.json') == REPORTS[stage], 'SEALED_PUBLIC_REPORT_REQUIRED')
    report = read(public/'report.json')
    require(report['stage'] == stage and report['integrity_complete'], 'INCOMPLETE_OR_WRONG_STAGE')
    for name in ('report.json', 'completion.json'):
        require((artifacts/name).read_bytes() == (public/name).read_bytes(), 'PUBLIC_ARTIFACT_MISMATCH')
    manifest = read(public/'completion.json')['artifact_sha256']
    for name in ('R1-daily.json', 'R1-fills.json', 'R1-decisions.json'):
        require(digest(artifacts/name) == manifest[name], 'LOCAL_ARTIFACT_HASH_MISMATCH')
    for name, seal in report['source_files'].items():
        require(digest(root/name) == seal, 'FROZEN_SOURCE_CHANGED')
    require(digest(csv_path) == report['input']['csv_sha256'], 'SEALED_CSV_REQUIRED')
    require(version('exchange-calendars') == '4.13.2', 'PINNED_CALENDAR_RUNTIME_REQUIRED')
    count, first, last = EXPECTED[stage]
    context_start = datetime.fromisoformat(report['input']['start']).date()
    context_end = datetime.fromisoformat(report['input']['end_exclusive']).date()-timedelta(days=1)
    calendar = load_xnys_calendar(context_start, context_end)
    require(calendar.calendar_version == report['calendar_version'], 'SEALED_CALENDAR_MISMATCH')
    sessions = {s.session_id:s for s in calendar.sessions if first <= s.session_id <= last}
    daily = read(artifacts/'R1-daily.json')
    require(len(daily) == count and [d['session'] for d in daily] == list(sessions), 'DAILY_CALENDAR_MISMATCH')
    expected = {f['session']:f for f in read(artifacts/'R1-fills.json') if f['reason']=='ENTRY'}
    expected_decisions = read(artifacts/'R1-decisions.json')
    prefixes = {s:[None]*7 for s in sessions}
    # Only known scheduled prefix timestamps are admitted; no later bars go to the model.
    slots = {s.opens_at+timedelta(minutes=i):(day,i) for day,s in sessions.items() for i in range(7)}
    with Path(csv_path).open(newline='') as source:
        for row in csv.DictReader(source):
            if row['symbol'] != 'QQQ': continue
            at = datetime.fromisoformat(row['timestamp'])
            if at not in slots: continue
            day, i = slots[at]
            require(prefixes[day][i] is None, 'DUPLICATE_PREFIX_MINUTE')
            prefixes[day][i] = MarketContext('QQQ',at,'1m',*(float(row[k]) for k in ('open','high','low','close','volume')))
    require(all(all(b is not None for b in rows) for rows in prefixes.values()), 'MISSING_PREFIX_MINUTE')
    output.mkdir(parents=True, exist_ok=False)
    results = []
    journal_path = output/'historical-intents.sqlite'
    with PaperIntentJournal(journal_path, 'HISTORICAL_REPLAY') as book:
        for day in daily:
            label = day['session']; session = sessions[label]
            r = record_historical_entry(book, session, prefixes[label], starting_cash=day['starting_equity'],
                feed='sip', source_sha256=report['input']['csv_sha256'])
            original = expected.get(label)
            require((r['intent'] is not None) == (original is not None), 'ENTRY_PRESENCE_MISMATCH')
            if original:
                require(r['intent']['quantity'] == original['quantity'] and r['intent']['side'] == original['side']
                    and r['modeled_entry_reference'] == original['reference']
                    and datetime.fromisoformat(r['modeled_entry_at']) == datetime.fromisoformat(original['at']),
                    'FROZEN_ENTRY_MISMATCH')
            prior = [d for d in expected_decisions if d['session']==label
                     and datetime.fromisoformat(d['at']) <= session.opens_at+timedelta(minutes=6)]
            actual = [(datetime.fromisoformat(d['at']),d['reason']) for d in r['decisions']]
            require(actual == [(datetime.fromisoformat(d['at']),d['reason']) for d in prior], 'FROZEN_DECISION_MISMATCH')
            results.append(r)
        before = book.summary()
    with PaperIntentJournal(journal_path, 'HISTORICAL_REPLAY') as book:
        for day, original in zip(daily, results):
            r = record_historical_entry(book, sessions[day['session']], prefixes[day['session']],
                starting_cash=day['starting_equity'], feed='sip', source_sha256=report['input']['csv_sha256'])
            require(r == original, 'RECOVERY_OUTPUT_CHANGED')
        require(book.summary() == before, 'RECOVERY_WROTE_DUPLICATE_INTENTS')
    (output/'private-session-results.json').write_text(json.dumps(results,indent=2)+'\n')
    summary = dict(status='PASS_HISTORICAL_PREFIX_CONFORMANCE', stage=stage, sessions=count,
        processed_prefix_minutes=count*7, entries_matched=len(expected), no_entry_sessions=count-len(expected),
        reasons=dict(Counter(d['reason'] for r in results for d in r['decisions'])),
        frozen_source_files_verified=len(report['source_files']),
        archived_starting_equity_used=True, capital_carry_resimulated=False,
        entries_and_decisions_match_sealed_artifacts=True, restart_replay_unchanged=True,
        journal_summary=before, report_sha256=REPORTS[stage], csv_sha256=report['input']['csv_sha256'],
        historical_entry_reference_clock='09:36 America/New_York',
        assumed_closed_bar_intent_availability='09:37 America/New_York',
        original_receipt_times_verified=False, actual_paper_intents_created=0,
        actual_strategy_paper_pnl=None, execution_enabled=False,
        live_signal_adapter_complete=False, new_effectiveness_evaluation=False)
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage', choices=['A','B'], required=True)
    p.add_argument('--csv', required=True); p.add_argument('--artifacts', required=True)
    p.add_argument('--output', required=True); p.add_argument('--root', default='.')
    a = p.parse_args()
    print(json.dumps(check(a.stage,a.csv,a.artifacts,a.output,root=a.root),indent=2))
