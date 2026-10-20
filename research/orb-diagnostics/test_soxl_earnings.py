from copy import deepcopy
import unittest

from soxl_earnings import apply_blackout, blackout_dates, latest_snapshot
from soxl_reversal import summarize


def snapshot(asof='2023-09-30', filed='2023-11-20', accession='old', symbols=None):
    return dict(asof=asof, filing_date=filed, accession=accession,
                top5=[dict(symbol=s) for s in (symbols or ['A', 'B', 'C', 'D', 'E'])])


def event(day='2024-01-05', symbol='A'):
    return dict(announcement_date=day, symbol=symbol, verified=True,
                source_url='https://example.test/release', source_sha256='a'*64)


class EarningsTests(unittest.TestCase):
    def test_filing_day_does_not_make_holdings_available_same_morning(self):
        old = snapshot()
        new = snapshot('2023-12-31', '2024-01-05', 'new', ['F', 'G', 'H', 'I', 'J'])
        self.assertEqual(latest_snapshot([old, new], '2024-01-05'), old)
        self.assertEqual(latest_snapshot([old, new], '2024-01-08'), new)

    def test_late_amendment_does_not_roll_back_to_older_holdings(self):
        newer = snapshot('2023-12-31', '2024-02-01', 'new')
        amended_old = snapshot('2023-09-30', '2024-03-01', 'late-old')
        self.assertEqual(latest_snapshot([newer, amended_old], '2024-03-04'), newer)

    def test_unknown_holdings_is_not_silently_treated_as_no_event(self):
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_HOLDINGS'):
            latest_snapshot([snapshot()], '2023-11-20')

    def test_weekend_and_holiday_reaction_uses_exchange_calendar(self):
        dates = ['2024-01-05', '2024-01-08', '2024-01-12', '2024-01-16']
        actual, _ = blackout_dates([event('2024-01-12')], [snapshot()], dates,
                                  'ANNOUNCEMENT_AND_NEXT_SESSION')
        self.assertEqual(actual, {'2024-01-12', '2024-01-16'})
        actual, _ = blackout_dates([event('2024-01-06')], [snapshot()], dates,
                                  'ANNOUNCEMENT_AND_NEXT_SESSION')
        self.assertEqual(actual, {'2024-01-08'})

    def test_three_date_conventions_are_distinct_and_fixed(self):
        calendar = ['2024-01-05', '2024-01-08']
        args = ([event()], [snapshot()], calendar)
        self.assertEqual(blackout_dates(*args, 'ANNOUNCEMENT_ONLY')[0], {'2024-01-05'})
        self.assertEqual(blackout_dates(*args, 'NEXT_SESSION_ONLY')[0], {'2024-01-08'})
        self.assertEqual(blackout_dates(*args, 'ANNOUNCEMENT_AND_NEXT_SESSION')[0], set(calendar))

    def test_major_membership_frozen_on_announcement_not_reaction_day(self):
        snapshots = [snapshot(), snapshot('2023-12-31', '2024-01-05', 'new', ['F', 'G', 'H', 'I', 'J'])]
        result, _ = blackout_dates([event()], snapshots, ['2024-01-05', '2024-01-08'],
                                  'ANNOUNCEMENT_AND_NEXT_SESSION')
        self.assertEqual(result, {'2024-01-05', '2024-01-08'})

    def test_nonmajor_and_unverified_events_are_not_accepted_as_major(self):
        self.assertEqual(blackout_dates([event(symbol='Z')], [snapshot()], ['2024-01-05'],
                                       'ANNOUNCEMENT_ONLY')[0], set())
        e = event();e['verified'] = False
        with self.assertRaisesRegex(ValueError, 'VERIFIED_EVENT'):
            blackout_dates([e], [snapshot()], ['2024-01-05'], 'ANNOUNCEMENT_ONLY')

    def test_overlapping_issuers_deduplicate_dates_and_reject_duplicate_records(self):
        result, evidence = blackout_dates([event(symbol='A'), event(symbol='B')], [snapshot()],
            ['2024-01-05', '2024-01-08'], 'ANNOUNCEMENT_AND_NEXT_SESSION')
        self.assertEqual(len(result), 2);self.assertEqual(len(evidence), 2)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            blackout_dates([event(), event()], [snapshot()], ['2024-01-05'], 'ANNOUNCEMENT_ONLY')

    def test_blackout_retains_calendar_does_not_mutate_baseline_and_recompounds(self):
        rows = [dict(date=f'2024-01-0{i}', side=1, trade_return=t,
                     gross_trade_return=t, portfolio_return=.25*t, mae=min(t, 0), mfe=max(t, 0))
                for i, t in [(3, .1), (4, -.2), (5, .1)]]
        original = deepcopy(rows)
        filtered = apply_blackout(rows, {'2024-01-04'})
        self.assertEqual(rows, original)
        self.assertEqual([r['date'] for r in filtered], [r['date'] for r in rows])
        self.assertEqual(filtered[1]['side'], 0)
        self.assertAlmostEqual(summarize(filtered)['final_equity'], 100000*1.025**2)
        self.assertEqual(summarize(filtered)['trades'], 2)


if __name__ == '__main__':
    unittest.main()
