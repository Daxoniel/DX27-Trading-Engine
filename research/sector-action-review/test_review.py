from copy import deepcopy
from decimal import Decimal as D
import unittest

from diagnose import classify, coverage
from entitlement import Ledger


class CoverageTests(unittest.TestCase):
    def test_checks_old_exit_day_and_new_entry_day(self):
        cal = ['2025-01-01', '2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07']
        forms = [dict(asof=cal[0], eligible=[dict(symbol='A', sector='X', momentum=1)]),
                 dict(asof=cal[2], eligible=[dict(symbol='B', sector='X', momentum=1)])]
        rules = dict(mark_end=cal[-1], position_count=1, maximum_names_per_sector=1, weight_per_slot=1)
        adj = {'A': {cal[2]: 10, cal[3]: 10}, 'B': {cal[-1]: 20}}
        result = coverage(adj, cal, forms, 'ordinary', rules)
        self.assertEqual(result['planned_symbol_session_checks'], 4)
        self.assertEqual(result['gaps'][0]['symbol'], 'A')
        self.assertEqual(result['gaps'][0]['first_missing'], cal[-1])
        adj['B'] = {}
        self.assertEqual(len(coverage(adj, cal, forms, 'ordinary', rules)['gaps']), 2)

    def test_invalid_close_is_not_accepted(self):
        cal = ['2025-01-01', '2025-01-02', '2025-01-03']
        forms = [dict(asof=cal[0], eligible=[])]
        for price in (None, 0, -1, float('nan')):
            result = coverage({'SPY': {cal[2]: price}}, cal, forms, 'spy', dict(mark_end=cal[-1]))
            self.assertEqual(result['gaps'][0]['missing_sessions'], 1)

    def test_matching_terms_do_not_erase_date_conflict_or_receipt_gate(self):
        official = dict(symbol='A', cusip='111', right_cusip='222', cash_per_share=14.5,
                        legal_effective_date='2025-10-30', right_tradable=False)
        record = dict(acquiree_symbol='A', acquiree_cusip='111', acquirer_cusip='222',
                      cash_rate=14.5, acquiree_rate=1, acquirer_rate=1, effective_date='2025-11-03')
        r = classify(record, official)
        self.assertTrue(r['identity_matches'] and r['terms_match'] and r['date_conflict'])
        self.assertFalse(r['automatic_resume_allowed'] or r['broker_receipt_verified'])
        record['acquiree_cusip'] = 'WRONG'
        self.assertFalse(classify(record, official)['identity_matches'])
        official['right_tradable'] = True
        with self.assertRaisesRegex(ValueError, 'NONTRADABLE_RIGHT'):
            classify(record, official)


class EntitlementTests(unittest.TestCase):
    def ledger(self):
        return Ledger(D('7'), {'A': D('10')})

    def convert(self, ledger):
        ledger.convert('E', 'A', 'RIGHT', '2025-10-30', D('14.50'),
                       raw_shares_verified=True, legal_terms_verified=True)

    def test_cancel_stock_and_keep_receivable_and_right_out_of_cash(self):
        ledger = self.ledger(); self.convert(ledger)
        self.assertNotIn('A', ledger.shares)
        self.assertEqual(ledger.cash, D('7'))
        self.assertEqual(ledger.receivables['E']['amount'], D('145'))
        self.assertEqual(ledger.rights['RIGHT'], D('10'))
        with self.assertRaisesRegex(ValueError, 'UNPRICED_ASSETS'):
            ledger.equity()

    def test_payable_date_does_not_credit_cash(self):
        ledger = self.ledger(); self.convert(ledger)
        with self.assertRaisesRegex(ValueError, 'OBSERVED_RECEIPT'):
            ledger.receive('E', '2025-11-03', D('145'))
        self.assertEqual(ledger.cash, D('7'))
        ledger.receive('E', '2025-11-04', D('145'), receipt_verified=True)
        self.assertEqual(ledger.cash, D('152'))
        self.assertFalse(ledger.receivables)
        self.assertEqual(ledger.rights['RIGHT'], D('10'))
        with self.assertRaisesRegex(ValueError, 'UNPRICED_ASSETS'):
            ledger.equity()

    def test_unverified_adjusted_units_and_duplicate_conversion_rejected(self):
        ledger = self.ledger()
        with self.assertRaisesRegex(ValueError, 'VERIFIED_RAW'):
            ledger.convert('E', 'A', 'RIGHT', '2025-10-30', D('14.50'), legal_terms_verified=True)
        self.convert(ledger)
        before = deepcopy(ledger)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            self.convert(ledger)
        self.assertEqual(ledger, before)

    def test_wrong_amount_early_and_duplicate_receipt_rejected(self):
        ledger = self.ledger(); self.convert(ledger)
        for day, money in [('2025-10-29', D('145')), ('2025-11-03', D('144'))]:
            with self.assertRaisesRegex(ValueError, 'MISMATCH'):
                ledger.receive('E', day, money, receipt_verified=True)
        self.assertEqual(ledger.cash, D('7'))
        ledger.receive('E', '2025-11-03', D('145'), receipt_verified=True)
        with self.assertRaises(KeyError):
            ledger.receive('E', '2025-11-03', D('145'), receipt_verified=True)
        self.assertEqual(ledger.cash, D('152'))

    def test_invalid_or_unowned_quantity_rejected(self):
        for quantity in (D('-1'), D('NaN'), D('Infinity'), 1.0):
            with self.assertRaises(ValueError):
                Ledger(D('7'), {'A': quantity})
        ledger = Ledger(D('7'), {})
        with self.assertRaisesRegex(ValueError, 'OWNED_SHARES'):
            self.convert(ledger)


if __name__ == '__main__':
    unittest.main()
