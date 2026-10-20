from copy import deepcopy
import unittest

from example import fixture, intraday
from strategy import scan as scan_v1, seal
from strategy_v2 import scan, entry_signal
from scan_history_v2 import snapshot_for


class MappingTests(unittest.TestCase):
    def test_sector_peer_need_not_have_entry_setup(self):
        s = fixture()
        b = s['assets'][1]['daily'][-1]
        b['close'] *= 1.4
        b['high'] *= 2
        p = scan(s)
        self.assertEqual(p['sector_leaders']['TECH'], 2)
        self.assertIn('AAA', [c['symbol'] for c in p['watchlist']])
        self.assertNotIn('BBB', [c['symbol'] for c in p['watchlist']])
        self.assertEqual(next(x['reason'] for x in p['rejected'] if x['symbol']=='BBB'),
                         'NO_NEARBY_SUPPORT')

    def test_prior_ema_touch_not_universal_veto(self):
        s = fixture()
        s['assets'][0]['daily'][-8]['low'] *= .98
        self.assertNotIn('AAA', [c['symbol'] for c in scan_v1(s)['watchlist']])
        self.assertIn('AAA', [c['symbol'] for c in scan(s)['watchlist']])

    def test_alternative_support_signal_preserves_original_plan(self):
        p = scan(fixture())
        candidate = p['watchlist'][0]
        # Only one distinct support remains: mandatory two-indicator confluence
        # would fail, but a recovery at this known level remains admissible.
        candidate['support_levels'] = {'ema21':candidate['support']}
        bars = intraday(p)
        before = deepcopy(p)
        signal = entry_signal(p, candidate['symbol'], bars, bars[-1]['available_at'])
        self.assertIsNotNone(signal)
        self.assertEqual(signal['selected_support'], 'ema21')
        self.assertTrue(signal['client_order_id'].startswith('mlp2-'))
        self.assertEqual(signal['plan_sha256'], seal(p))
        self.assertEqual(p, before)
        self.assertFalse(signal['execution_enabled'])

    def test_missing_or_invalid_daily_records_are_explicit(self):
        prior = [dict(date='2025-04-25',open='2025-04-25T13:30:00Z',close='2025-04-25T20:00:00Z')]
        today = dict(date='2025-04-28',open='2025-04-28T13:30:00Z',close='2025-04-28T20:00:00Z')
        metadata = [dict(symbol='AAA',sector='TECH'),dict(symbol='BBB',sector='TECH')]
        source = {'AAA':{'2025-04-25':dict(t='2025-04-25',o=10,h=11,l=9,c=12,v=1)}}
        snapshot, excluded = snapshot_for(today,prior,metadata,source,{})
        self.assertEqual(snapshot['assets'], [])
        self.assertEqual({x['reason'] for x in excluded},
                         {'MISSING_DAILY_HISTORY','INVALID_DAILY_HISTORY'})

    def test_future_input_still_rejected(self):
        s = fixture()
        s['assets'][0]['known_at'] = '2026-01-01T00:00:00Z'
        with self.assertRaises(ValueError):
            scan(s)


if __name__ == '__main__':
    unittest.main()
