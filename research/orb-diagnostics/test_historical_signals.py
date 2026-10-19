from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from dx27.core.models.market_context import MarketContext
from dx27.intelligence.sentinel.session_calendar import TradingSession
from historical_signals import historical_entry, record_historical_entry
from paper_intents import PaperIntentJournal

UTC = timezone.utc
OPEN = datetime(2026, 10, 19, 13, 30, tzinfo=UTC)
SESSION = TradingSession('2026-10-19', OPEN, OPEN + timedelta(minutes=390))


def bars():
    return [MarketContext('QQQ', OPEN + timedelta(minutes=i), '1m', 100, 102, 99, 101, 10000)
            for i in range(7)]


class HistoricalSignalTests(unittest.TestCase):
    def run_prefix(self, rows=None, **kwargs):
        return historical_entry(SESSION, bars() if rows is None else rows,
            **(dict(starting_cash=100000, feed='sip', source_sha256='a'*64) | kwargs))

    def test_positive_prefix_preserves_frozen_sizing_and_distinguishes_clocks(self):
        r = self.run_prefix()
        self.assertEqual(r['intent']['quantity'], 100)  # prior-volume cap, not current minute
        self.assertEqual(r['intent']['signal_at'], '2026-10-19T13:35:00Z')
        self.assertEqual(r['modeled_entry_at'], '2026-10-19T13:36:00Z')
        self.assertEqual(r['intent']['intent_ready_at'], '2026-10-19T13:37:00Z')
        self.assertFalse(r['current_order_eligible']); self.assertIsNone(r['actual_strategy_paper_pnl'])

    def test_current_minute_volume_does_not_size_entry(self):
        rows = bars(); rows[6] = replace(rows[6], volume=1)
        self.assertEqual(self.run_prefix(rows)['intent']['quantity'], 100)
        rows[5] = replace(rows[5], volume=100)
        self.assertEqual(self.run_prefix(rows)['intent']['quantity'], 1)

    def test_short_doji_and_nonpositive_r_have_no_entry(self):
        for close, reason in [(99.5, 'SHORT_DISABLED'), (100, 'DOJI')]:
            rows = bars(); rows[4] = replace(rows[4], close=close)
            r = self.run_prefix(rows)
            self.assertIsNone(r['intent']); self.assertIn(reason, [d['reason'] for d in r['decisions']])
        rows = bars(); rows[6] = replace(rows[6], open=98, low=98)
        r = self.run_prefix(rows); self.assertIsNone(r['intent'])
        self.assertIn('NONPOSITIVE_R', [d['reason'] for d in r['decisions']])

    def test_every_missing_or_zero_volume_minute_blocks_intent(self):
        for i in range(7):
            for missing in (True, False):
                rows = bars(); rows[i] = None if missing else replace(rows[i], volume=0)
                r = self.run_prefix(rows)
                self.assertEqual(r['outcome'], 'INVALID_PREFIX'); self.assertIsNone(r['intent'])

    def test_only_exact_ordered_seven_minute_prefix_is_accepted(self):
        for rows in (bars()[:6], bars()+[bars()[-1]], list(reversed(bars()))):
            with self.assertRaises(ValueError): self.run_prefix(rows)
        rows = bars(); rows[2] = rows[1]
        with self.assertRaises(ValueError): self.run_prefix(rows)

    def test_feed_symbol_timeframe_and_invalid_ohlc_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'NO_FALLBACK'): self.run_prefix(feed='iex')
        for change in [dict(symbol='SPY'), dict(timeframe='5m'), dict(high=90), dict(close=float('nan'))]:
            rows = bars(); rows[0] = replace(rows[0], **change)
            with self.assertRaises(ValueError): self.run_prefix(rows)

    def test_seal_and_capital_are_required_and_affect_identity(self):
        r = self.run_prefix()
        for kw in [dict(source_sha256='bad'), dict(starting_cash=0), dict(starting_cash=float('inf'))]:
            with self.assertRaises(ValueError): self.run_prefix(**kw)
        self.assertNotEqual(r['prefix_sha256'], self.run_prefix(starting_cash=90000)['prefix_sha256'])
        self.assertNotEqual(r['prefix_sha256'], self.run_prefix(source_sha256='b'*64)['prefix_sha256'])

    def test_timezone_equivalence_and_dst_are_explicit(self):
        rows = [replace(b, timestamp=b.timestamp.astimezone(timezone(timedelta(hours=2)))) for b in bars()]
        self.assertEqual(self.run_prefix(rows), self.run_prefix())
        winter = TradingSession('2026-11-02', datetime(2026,11,2,14,30,tzinfo=UTC),
                                datetime(2026,11,2,21,tzinfo=UTC))
        winter_rows = [replace(b, timestamp=winter.opens_at+timedelta(minutes=i)) for i,b in enumerate(bars())]
        r = historical_entry(winter, winter_rows, starting_cash=100000, feed='sip', source_sha256='a'*64)
        self.assertEqual(r['intent']['intent_ready_at'], '2026-11-02T14:37:00Z')

    def test_restart_is_idempotent_and_historical_ids_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'history.sqlite'
            def record(book):
                return record_historical_entry(book, SESSION, bars(), starting_cash=100000,
                                               feed='sip', source_sha256='a'*64)
            with PaperIntentJournal(p, 'HISTORICAL_REPLAY', synthetic_clock=lambda:'2026-11-03T00:00:00Z') as book:
                r = record(book); before = book.summary()
                self.assertTrue(r['client_order_id'].startswith('orb-hst1-'))
                self.assertEqual(book.summary()['observed_owned_orders'], 0)
            with PaperIntentJournal(p, 'HISTORICAL_REPLAY', synthetic_clock=lambda:'2026-11-03T00:00:00Z') as book:
                self.assertEqual(record(book), r); self.assertEqual(book.summary(), before)
                with self.assertRaisesRegex(ValueError, 'CANNOT_OBSERVE'):
                    book.observe(None, broker_created_at='', observed_at='', fee_known=False)
            for mode in ('SYNTHETIC', 'PAPER_OBSERVATION'):
                with self.assertRaises(ValueError): PaperIntentJournal(p, mode)

    def test_paper_and_synthetic_journals_cannot_receive_bridge_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ('PAPER_OBSERVATION', 'SYNTHETIC'):
                with PaperIntentJournal(Path(tmp)/mode, mode) as book:
                    with self.assertRaisesRegex(ValueError, 'HISTORICAL_JOURNAL_REQUIRED'):
                        record_historical_entry(book, SESSION, bars())
                    with self.assertRaisesRegex(ValueError, 'CROSS_MODE'):
                        book.register(self.run_prefix()['intent'])
                    self.assertEqual(book.summary()['registered_intents'], 0)

    def test_changed_input_for_registered_session_halts_even_when_entry_disappears(self):
        with tempfile.TemporaryDirectory() as tmp:
            for case in ('different_seal', 'no_entry'):
                with PaperIntentJournal(Path(tmp)/case, 'HISTORICAL_REPLAY', synthetic_clock=lambda:'2026-11-03T00:00:00Z') as book:
                    kw = dict(starting_cash=100000, feed='sip', source_sha256='a'*64)
                    record_historical_entry(book, SESSION, bars(), **kw)
                    rows = bars()
                    if case == 'different_seal': kw['source_sha256'] = 'b'*64
                    else: rows[4] = replace(rows[4], close=99.5)
                    with self.assertRaises(ValueError): record_historical_entry(book, SESSION, rows, **kw)
                    self.assertIsNotNone(book.summary()['integrity_halt'])
                    self.assertEqual(book.summary()['registered_intents'], 1)


if __name__ == '__main__': unittest.main()
