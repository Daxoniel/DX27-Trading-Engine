import unittest
from execution_timing import evaluate_timing


def trace():
    return dict(contract='ORB_OFFLINE_TIMING:1', observation_kind='SYNTHETIC', symbol='QQQ',
        side='BUY',quantity=10,required_feed='sip',signal_window_end='2026-07-01T13:35:00Z',
        last_input_available_at='2026-07-01T13:35:00.010000Z',
        last_input_received_at='2026-07-01T13:35:00.020000Z',decision_at='2026-07-01T13:35:00.030000Z',
        intent_ready_at='2026-07-01T13:35:00.040000Z')


def quote(seq=1, **changes):
    q=dict(quote_id=f'q{seq}',receipt_sequence=seq,symbol='QQQ',feed='sip',
        event_at='2026-07-01T13:35:00.050000Z',received_at='2026-07-01T13:35:00.060000Z',
        bid='100',ask='100.02',bid_size=20,ask_size=20,size_unit='SHARES')
    q.update(changes);return q


class TimingTests(unittest.TestCase):
    def evaluate(self, quotes, t=None):
        return evaluate_timing(t or trace(),quotes,max_quote_age_us=500000)

    def test_first_receipt_not_best_future_price(self):
        r=self.evaluate([quote(),quote(2,ask='100.01')])
        self.assertEqual(r['quote_id'],'q1');self.assertEqual(r['modeled_reference_price'],'100.02')
        self.assertFalse(r['execution_enabled']);self.assertFalse(r['actual_fill_verified'])

    def test_future_malformed_record_cannot_change_prefix_match(self):
        a=self.evaluate([quote()]);b=self.evaluate([quote(),{'future':'malformed'}])
        self.assertEqual(a,b)

    def test_reject_decision_before_input(self):
        t=trace();t['decision_at']='2026-07-01T13:34:59Z'
        with self.assertRaises(ValueError):self.evaluate([quote()],t)

    def test_unresolved_provider_clock_ahead_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'QUOTE_EVENT_AFTER_RECEIPT'):
            self.evaluate([quote(event_at='2026-07-01T13:35:00.070000Z')])

    def test_declared_intervals_preserved(self):
        r=self.evaluate([quote()])
        self.assertEqual(r['declared_intervals_us'],dict(input_available_after_window=10000,
            delivery_after_availability=10000,decision_after_receive=10000,
            intent_after_decision=10000,quote_wait_after_intent=20000))
        self.assertEqual(r['quote_age_us'],10000)

    def test_no_bar_open_backfill(self):
        r=self.evaluate([quote(event_at='2026-07-01T13:35:00Z')])
        self.assertEqual(r['status'],'NO_ELIGIBLE_QUOTE')
        self.assertEqual(r['skipped']['BEFORE_INTENT_READY'],1)

    def test_stale_and_insufficient_size_remain_visible(self):
        q1=quote(event_at='2026-07-01T13:35:00.050000Z',received_at='2026-07-01T13:35:01Z')
        q2=quote(2,event_at='2026-07-01T13:35:01Z',received_at='2026-07-01T13:35:01.010000Z',ask_size=9)
        r=self.evaluate([q1,q2]);self.assertEqual(r['status'],'NO_ELIGIBLE_QUOTE')
        self.assertEqual(r['skipped'],{'INSUFFICIENT_DISPLAYED_SIZE':1,'STALE_QUOTE':1})

    def test_no_iex_fallback(self):
        r=self.evaluate([quote(feed='iex')]);self.assertEqual(r['status'],'NO_ELIGIBLE_QUOTE')

    def test_sell_uses_bid_and_share_units_required(self):
        t=trace();t['side']='SELL'
        self.assertEqual(self.evaluate([quote()],t)['modeled_reference_price'],'100')
        with self.assertRaises(ValueError):self.evaluate([quote(size_unit='LOTS')])

    def test_crossed_nonfinite_and_bool_rejected(self):
        for change in ({'ask':'99'},{'ask':'NaN'},{'bid':True},{'ask_size':True}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.evaluate([quote(**change)])

    def test_missing_real_policy_does_not_default_to_zero(self):
        self.assertEqual(evaluate_timing(trace(),[],max_quote_age_us=None)['status'],
                         'BLOCKED_MISSING_QUOTE_FRESHNESS_POLICY')

    def test_duplicate_or_reordered_prefix_rejected(self):
        first=quote(feed='iex')
        for q in (quote(1),quote(2,received_at='2026-07-01T13:35:00.055000Z')):
            with self.assertRaises(ValueError):self.evaluate([first,q])

    def test_real_label_does_not_authenticate(self):
        t=trace();t['observation_kind']='RECORDED_OBSERVATION'
        r=self.evaluate([quote()],t)
        self.assertEqual(r['status'],'UNAUTHENTICATED_MODEL_MATCH')
        self.assertFalse(r['live_latency_verified']);self.assertFalse(r['authenticity_verified'])

    def test_nanosecond_truncation_or_naive_clock_rejected(self):
        for value in ('2026-07-01T13:35:00.050000001Z','2026-07-01T13:35:00.050000'):
            with self.assertRaises(ValueError):self.evaluate([quote(event_at=value)])


if __name__=='__main__':unittest.main()
