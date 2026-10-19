from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from dx27.intelligence.sentinel.session_calendar import TradingSession
from historical_signals import stamp
from observed_signals import ObservedSignalJournal

OPEN=datetime(2026,7,1,13,30,tzinfo=timezone.utc)
SESSION=TradingSession('2026-07-01',OPEN,OPEN+timedelta(minutes=390))


def bar(i):
    at=OPEN+timedelta(minutes=i)
    return dict(event_id=f'b{i}',receipt_sequence=i+1,received_at=stamp(at+timedelta(minutes=1,milliseconds=20)),
        feed='sip',kind='BAR',payload=dict(symbol='QQQ',timestamp=stamp(at),timeframe='1m',
            open=100,high=102,low=99,close=101,volume=10000))


def quote(seq=7,**changes):
    at=OPEN+timedelta(minutes=6,milliseconds=40+(seq-7)*20)
    e=dict(event_id=f'q{seq}',receipt_sequence=seq,received_at=stamp(at+timedelta(milliseconds=10)),
        feed='sip',kind='QUOTE',payload=dict(symbol='QQQ',event_at=stamp(at),bid='100',ask='100.02',
            bid_size=20,ask_size=20,size_unit='SHARES'))
    e['payload'].update(changes);return e


class ObservedSignalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'readiness.sqlite'
        self.now=stamp(OPEN)
        self.book=self.make()
    def make(self,**changes):
        kw=dict(mode='SYNTHETIC',probe_quantity=10,max_quote_age_us=500000,max_input_age_us=1000000,
                synthetic_clock=lambda:self.now);kw.update(changes)
        return ObservedSignalJournal(self.path,SESSION,**kw)
    def tearDown(self):self.book.close();self.tmp.cleanup()
    def accept(self,e,delay_ms=1):
        self.now=stamp(datetime.fromisoformat(e['received_at'])+timedelta(milliseconds=delay_ms))
        return self.book.accept(e)
    def prefix(self):
        for i in range(6):self.accept(bar(i))

    def test_closed_input_to_later_ask_has_processing_clock_and_no_order(self):
        self.prefix();s=self.book.summary()
        self.assertEqual(s['status'],'WAITING_FOR_POST_PROCESSING_QUOTE')
        self.assertEqual(s['trace']['intent_ready_at'],'2026-07-01T13:36:00.021000Z')
        self.accept(quote());s=self.book.summary()
        self.assertEqual(s['reference']['modeled_reference_price'],'100.02')
        self.assertEqual(s['reference']['reference_kind'],'ASK')
        self.assertEqual(s['actual_paper_intents_created'],0);self.assertFalse(s['execution_enabled'])

    def test_restart_and_duplicate_receipts_do_not_advance(self):
        self.prefix();before=self.book.summary();self.book.close();self.book=self.make()
        for i in range(6):self.assertEqual(self.book.accept(bar(i)),'DUPLICATE')
        self.assertEqual(self.book.summary(),before)
        self.accept(quote());before=self.book.summary();self.book.close();self.book=self.make()
        self.assertEqual(self.book.accept(quote()),'DUPLICATE');self.assertEqual(self.book.summary(),before)
        with self.assertRaisesRegex(ValueError,'ALREADY_FROZEN'):self.accept(quote(8,ask='100.01'))
        self.assertEqual(self.book.summary(),before)

    def test_changed_duplicate_persists_halt(self):
        self.accept(bar(0));changed=bar(0);changed['payload']['close']=100.5
        with self.assertRaisesRegex(ValueError,'IDENTITY_CONFLICT'):self.accept(changed)
        self.book.close();self.book=self.make()
        with self.assertRaisesRegex(ValueError,'HALTED'):self.accept(bar(1))

    def test_missing_receipt_sequence_is_not_silently_repaired(self):
        with self.assertRaisesRegex(ValueError,'SEQUENCE_GAP'):self.accept(bar(1))
        self.assertEqual(self.book.summary()['accepted_receipts'],0)

    def test_missing_or_wrong_scheduled_bar_does_not_become_signal(self):
        self.accept(bar(0));e=bar(2);e['receipt_sequence']=2
        with self.assertRaisesRegex(ValueError,'scheduled minute'):self.accept(e)
        self.assertEqual(self.book.summary()['closed_minutes'],1)

    def test_zero_volume_directionless_and_incomplete_prefixes_make_no_reference(self):
        for i in range(6):
            e=bar(i)
            if i==1:e['payload']['volume']=0
            self.accept(e)
        self.assertEqual(self.book.summary()['status'],'INVALID_OPENING_PREFIX')
        self.accept(quote());self.assertIsNone(self.book.summary()['reference'])

    def test_short_and_doji_preserve_frozen_no_long_decision(self):
        for close in (99.5,100):
            with tempfile.TemporaryDirectory() as tmp:
                with ObservedSignalJournal(Path(tmp)/'j',SESSION,mode='SYNTHETIC',probe_quantity=10,
                        synthetic_clock=lambda:self.now) as book:
                    for i in range(6):
                        e=bar(i)
                        if i==4:e['payload']['close']=close
                        self.now=e['received_at'];book.accept(e)
                    self.assertEqual(book.summary()['status'],'NO_LONG_DIRECTION')

    def test_missing_freshness_policy_is_explicitly_blocked(self):
        self.book.close();self.path=Path(self.tmp.name)/'no-policy';self.book=self.make(max_quote_age_us=None)
        self.prefix();self.accept(quote())
        self.assertEqual(self.book.summary()['status'],'BLOCKED_MISSING_FRESHNESS_POLICY')
        self.assertIsNone(self.book.summary()['reference'])

    def test_stale_bar_delivery_blocks_even_when_last_receipt_is_recent(self):
        for i in range(6):
            e=bar(i)
            if i==0:e['received_at']='2026-07-01T13:31:02Z'
            self.accept(e)
        self.assertEqual(self.book.summary()['status'],'BLOCKED_STALE_INPUT_RECEIPTS')

    def test_predecision_stale_small_and_processing_delayed_quotes_are_not_references(self):
        self.prefix()
        self.accept(quote(event_at='2026-07-01T13:36:00.020000Z'))
        self.accept(quote(8,event_at='2026-07-01T13:35:59Z'))
        self.accept(quote(9,ask_size=9))
        self.accept(quote(10),delay_ms=600)
        self.assertIsNone(self.book.summary()['reference'])
        fresh=quote(11);fresh['received_at']='2026-07-01T13:36:01Z';fresh['payload']['event_at']='2026-07-01T13:36:00.99Z'
        self.accept(fresh);s=self.book.summary()
        self.assertEqual(s['reference']['quote_id'],'q11')
        self.assertEqual(s['quotes_excluded_for_processing_delay'],1)

    def test_feed_invalid_quote_and_unresolved_clocks_are_rejected(self):
        e=bar(0);e['feed']='iex'
        with self.assertRaisesRegex(ValueError,'NO_FALLBACK'):self.accept(e)
        e=bar(0);e['received_at']='2026-07-01T13:30:30Z'
        with self.assertRaisesRegex(ValueError,'BEFORE_COMPLETION'):self.accept(e)
        self.prefix()
        for changes in [dict(ask='99'),dict(ask='NaN'),dict(size_unit='LOTS'),
                        dict(event_at='2026-07-01T13:36:01Z')]:
            with self.assertRaises(ValueError):self.accept(quote(**changes))
        self.assertEqual(self.book.summary()['accepted_receipts'],6)

    def test_future_receipt_and_processing_clock_regression_rejected(self):
        self.now=stamp(OPEN)
        with self.assertRaisesRegex(ValueError,'PROCESSING_FUTURE'):self.book.accept(bar(0))
        self.accept(bar(0),delay_ms=100)
        e=quote(2);e['received_at']=bar(0)['received_at'];e['payload']['event_at']=bar(0)['received_at']
        with self.assertRaisesRegex(ValueError,'PROCESSING_CLOCK_REGRESSED'):self.accept(e,delay_ms=1)

    def test_mode_policy_and_probe_size_cannot_change_on_reopen(self):
        self.book.close()
        for changes in [dict(mode='RECORDED_OBSERVATION',synthetic_clock=None),dict(probe_quantity=9),
                        dict(max_quote_age_us=400000)]:
            with self.assertRaises(ValueError):self.make(**changes)
        self.book=self.make()
        with self.assertRaisesRegex(ValueError,'NOT_INJECTABLE'):self.make(mode='RECORDED_OBSERVATION')

    def test_fresh_quote_cannot_revive_expired_signal(self):
        self.prefix();e=quote();e['received_at']='2026-07-01T14:00:00.010000Z'
        e['payload']['event_at']='2026-07-01T14:00:00Z'
        self.accept(e)
        self.assertEqual(self.book.summary()['status'],'BLOCKED_SIGNAL_EXPIRED')
        self.assertIsNone(self.book.summary()['reference'])

    def test_missing_policy_still_validates_quotes_and_bool_bar_rejected(self):
        e=bar(0);e['payload']['volume']=True
        with self.assertRaisesRegex(ValueError,'NUMERIC'):self.accept(e)
        self.book.close();self.path=Path(self.tmp.name)/'missing';self.book=self.make(max_quote_age_us=None)
        e=quote(1,ask='NaN')
        with self.assertRaises(ValueError):self.accept(e)
        self.assertEqual(self.book.summary()['accepted_receipts'],0)


if __name__=='__main__':unittest.main()
