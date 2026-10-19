from contextlib import closing
from decimal import Decimal
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from paper_intents import PaperIntentJournal,NAMESPACE
from dx27.adapters.alpaca.paper_contract import timestamp_revision
from dx27.domains.intraday.order_lifecycle import OrderReport

CLOCK='2026-10-19T13:35:01Z'
CREATED='2026-10-19T13:35:02Z'
OBSERVED='2026-10-19T13:36:00Z'


def intent(key='entry',side='buy'):
    return dict(intent_id=key,signal_key='decision-'+key,session='2026-10-19',symbol='QQQ',side=side,
        quantity=10,signal_at='2026-10-19T13:35:00Z',intent_ready_at='2026-10-19T13:35:00.5Z',
        origin='SYNTHETIC',feed='sip',data_sha256='a'*64)


def report(cid,n=3,status='partial',quantity=4,notional='400',fee='0',side='buy',broker='broker-entry',eid=None):
    return OrderReport(eid or f'e{n}',cid,broker,timestamp_revision(f'2026-10-19T13:35:{n:02d}Z'),
        'QQQ',side,10,status,quantity,Decimal(notional),Decimal(fee))


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'journal.sqlite'
        self.book=PaperIntentJournal(self.path,'SYNTHETIC',synthetic_clock=lambda:CLOCK)
    def tearDown(self):self.book.close();self.temp.cleanup()
    def observe(self,r,known=False,created=CREATED):
        return self.book.observe(r,broker_created_at=created,observed_at=OBSERVED,fee_known=known)

    def test_intent_and_restart_idempotence(self):
        cid=self.book.register(intent());self.assertLessEqual(len(cid),48)
        self.assertEqual(cid,self.book.register(intent()))
        self.observe(report(cid));before=self.book.summary()
        self.book.close();self.book=PaperIntentJournal(self.path,'SYNTHETIC',synthetic_clock=lambda:CLOCK)
        self.assertEqual(cid,self.book.register(intent()))
        self.assertEqual(self.observe(report(cid)),'DUPLICATE')
        self.assertEqual(self.book.summary(),before)

    def test_equivalent_creation_timestamp_precision_is_idempotent(self):
        cid=self.book.register(intent());self.observe(report(cid))
        self.assertEqual(self.observe(report(cid),created='2026-10-19T13:35:02.000000000Z'),'DUPLICATE')

    def test_signal_alias_cannot_create_second_intent(self):
        self.book.register(intent());other=intent();other['intent_id']='alias'
        with self.assertRaisesRegex(ValueError,'SIGNAL_ALREADY_REGISTERED'):self.book.register(other)
        self.assertEqual(self.book.summary()['registered_intents'],1)

    def test_changed_payload_halts_registration(self):
        self.book.register(intent());other=intent();other['quantity']=9
        with self.assertRaisesRegex(ValueError,'IDENTITY_CONFLICT'):self.book.register(other)
        with self.assertRaisesRegex(ValueError,'REGISTRATION_HALTED'):self.book.register(intent('next'))

    def test_prefix_is_not_ownership_and_no_retroactive_claim(self):
        cid='orb-ppr1-'+hashlib.sha256((NAMESPACE+':entry').encode()).hexdigest()[:32]
        self.assertEqual(self.observe(report(cid)),'UNOWNED_NO_ATTRIBUTION')
        self.assertEqual(self.book.summary()['owned_gross_cash_delta'],'0')
        with self.assertRaisesRegex(ValueError,'RETROACTIVE_OWNERSHIP'):self.book.register(intent())

    def test_order_before_durable_intent_rejected(self):
        cid=self.book.register(intent())
        with self.assertRaisesRegex(ValueError,'ORDER_PRECEDES_DURABLE'):
            self.observe(report(cid),created='2026-10-19T13:35:00Z')

    def test_partial_full_stale_and_same_revision_do_not_double_count(self):
        cid=self.book.register(intent());self.observe(report(cid))
        self.observe(report(cid,4,'filled',10,'1000'))
        self.assertEqual(self.observe(report(cid,3,eid='late-old')),'STALE')
        self.assertEqual(self.observe(report(cid,4,'filled',10,'1000',eid='repeat-final')),'SAME_REVISION')
        s=self.book.summary();self.assertEqual(s['owned_gross_cash_delta'],'-1000')
        self.assertEqual(s['owned_inventory_contribution'],{'QQQ':10})

    def test_known_broker_order_cannot_be_relabelled_unowned(self):
        cid=self.book.register(intent());self.observe(report(cid))
        with self.assertRaisesRegex(ValueError,'BROKER_ORDER_OWNERSHIP_CONFLICT'):
            self.observe(report('external-client',4,eid='foreign-event'))

    def test_known_fee_cannot_regress_or_become_unknown(self):
        cid=self.book.register(intent());self.observe(report(cid,fee='.1'),known=True)
        with self.assertRaisesRegex(ValueError,'KNOWN_FEES_REGRESSED'):
            self.observe(report(cid,4,fee='0'),known=False)

    def test_cancel_then_late_full_fill_race(self):
        cid=self.book.register(intent());self.observe(report(cid,3,'canceled',4,'400'))
        self.observe(report(cid,4,'filled',10,'1000'))
        self.assertEqual(self.book.summary()['owned_inventory_contribution'],{'QQQ':10})

    def test_unknown_fees_remain_null_until_explicit_later_evidence(self):
        cid=self.book.register(intent());self.observe(report(cid,3,'filled',10,'1000'))
        self.assertIsNone(self.book.summary()['owned_cash_delta_including_all_recorded_fees'])
        self.observe(report(cid,4,'filled',10,'1000','.25'),known=True)
        self.assertEqual(self.book.summary()['owned_cash_delta_including_all_recorded_fees'],'-1000.25')
        self.assertIsNone(self.book.summary()['actual_strategy_paper_pnl'])

    def test_fee_cannot_be_silently_revised_at_same_order_revision(self):
        cid=self.book.register(intent());self.observe(report(cid))
        with self.assertRaisesRegex(ValueError,'REVISION_CONFLICT'):
            self.observe(report(cid,fee='.1',eid='new-fee'),known=True)

    def test_cumulative_reprice_and_known_fee_regression_rejected(self):
        cid=self.book.register(intent());self.observe(report(cid,fee='.1'),known=True)
        with self.assertRaisesRegex(ValueError,'REGRESSED_OR_REPRICED'):
            self.observe(report(cid,4,notional='401',fee='.1'),known=True)

    def test_conflicting_event_identity_rejected(self):
        cid=self.book.register(intent());self.observe(report(cid))
        with self.assertRaisesRegex(ValueError,'EVENT_IDENTITY_CONFLICT'):
            self.observe(report(cid,quantity=5,notional='500'))

    def test_buy_and_sell_contributions_reconcile_without_profit_claim(self):
        buy=self.book.register(intent());sell=self.book.register(intent('exit',side='sell'))
        self.observe(report(buy,3,'filled',10,'1000','.25'),known=True)
        self.observe(report(sell,4,'filled',10,'1010','.25',side='sell',broker='broker-exit'),known=True)
        s=self.book.summary();self.assertEqual(s['owned_cash_delta_including_all_recorded_fees'],'9.50')
        self.assertEqual(s['owned_inventory_contribution'],{})
        self.assertFalse(s['account_reconciliation_complete']);self.assertIsNone(s['actual_strategy_paper_pnl'])

    def test_synthetic_and_paper_modes_cannot_mix(self):
        self.book.close()
        with self.assertRaises(ValueError):PaperIntentJournal(self.path,'PAPER_OBSERVATION')

    def test_single_writer_and_hash_corruption(self):
        with self.assertRaises(sqlite3.OperationalError):
            PaperIntentJournal(self.path,'SYNTHETIC',synthetic_clock=lambda:CLOCK)
        self.book.close()
        with closing(sqlite3.connect(self.path)) as db:
            with db:db.execute("UPDATE metadata SET value='{}' WHERE key='state'")
        with self.assertRaisesRegex(ValueError,'integrity failure'):
            PaperIntentJournal(self.path,'SYNTHETIC',synthetic_clock=lambda:CLOCK)

    def test_historical_intent_not_registered_as_current_paper(self):
        p=Path(self.temp.name)/'actual.sqlite'
        with PaperIntentJournal(p,'PAPER_OBSERVATION') as book:
            row=intent();row['origin']='HISTORICAL_REPLAY'
            with self.assertRaisesRegex(ValueError,'HISTORICAL_OR_CROSS_MODE'):book.register(row)
            self.assertEqual(book.summary()['registered_intents'],0)


if __name__=='__main__':unittest.main()
