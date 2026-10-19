from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from paper_roundtrip import PaperRoundtrip,buy_payload,sell_payload
from paper_intents import utc_now


class PaperRoundtripTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict('os.environ',APCA_API_KEY_ID='test-key',APCA_API_SECRET_KEY='test-secret');self.env.start()
        self.book=PaperRoundtrip(Path(self.tmp.name)/'journal')
    def tearDown(self):self.book.close();self.env.stop();self.tmp.cleanup()
    def seed(self):
        s=deepcopy(self.book.journal.state);s['preflight']={'flat':True};s['source']={'provider_event_at':utc_now()}
        self.book.save(s,'TEST_SEED')

    def test_one_share_fixed_symbol_fok_entry_and_buy_cap(self):
        p=buy_payload('own','600.00')
        self.assertEqual((p['symbol'],p['qty'],p['type'],p['time_in_force']),('QQQ','1','limit','fok'))
        for v in ['1000.01','0','NaN','600.001']:
            with self.assertRaises(ValueError):buy_payload('own',v)
        self.assertEqual(sell_payload('exit')['qty'],'1')

    def test_no_unregistered_post_arbitrary_path_or_live_host(self):
        self.book.opener=Mock()
        for method,path,payload in [('POST','/v2/orders',buy_payload('own','600.00')),
                                    ('DELETE','/v2/orders',None),('GET','https://api.alpaca.markets/v2/account',None)]:
            with self.assertRaises(ValueError):self.book.request(method,path,payload)
        self.book.opener.open.assert_not_called()

    def test_unknown_post_persists_dispatch_and_next_submit_only_reconciles(self):
        self.seed();self.book.opener=Mock();self.book.opener.open.side_effect=OSError('lost response')
        p=buy_payload('own','600.00')
        with self.assertRaises(OSError):self.book.submit_once('buy',p)
        self.assertEqual(self.book.journal.state['legs']['buy']['status'],'DISPATCHED')
        with self.assertRaises(ValueError):self.book.request('POST','/v2/orders',p)
        self.book.reconcile=Mock(return_value={'status':'filled'})
        self.book.submit_once('buy',p);self.book.reconcile.assert_called_once_with('buy')
        self.assertEqual(self.book.opener.open.call_count,1)

    def test_sell_without_owned_filled_buy_is_blocked(self):
        self.seed();s=deepcopy(self.book.journal.state)
        s['legs']['buy']={'payload':buy_payload('own','600.00'),'order':{'status':'new','filled_qty':'0'}}
        self.book.save(s,'TEST_PENDING')
        with self.assertRaises(ValueError):self.book.submit_once('sell',sell_payload('exit'))

    def test_stale_entry_and_account_not_flat_are_blocked(self):
        self.seed();s=deepcopy(self.book.journal.state);s['source']['provider_event_at']='2025-01-01T00:00:00Z'
        self.book.save(s,'TEST_STALE')
        with self.assertRaisesRegex(ValueError,'QUOTE_EXPIRED'):self.book.submit_once('buy',buy_payload('own','600.00'))
        account=dict(status='ACTIVE',trading_blocked=False,account_blocked=False,currency='USD',buying_power='100000')
        self.book.request=Mock(side_effect=[account,{'is_open':True},[{'symbol':'QQQ','qty':'1'}],[]])
        with self.assertRaisesRegex(ValueError,'FLAT_ACCOUNT'):self.book.preflight()

    def test_order_identity_and_fractional_fill_require_review(self):
        self.seed();s=deepcopy(self.book.journal.state)
        s['legs']['buy']={'payload':buy_payload('own','600.00'),'status':'DISPATCHED'};self.book.save(s,'TEST_REGISTERED')
        o=dict(client_order_id='other',symbol='QQQ',side='buy',qty='1',filled_qty='1',id='broker')
        with self.assertRaises(ValueError):self.book.observe('buy',o)
        o['client_order_id']='own';o['filled_qty']='0.5'
        with self.assertRaises(ValueError):self.book.observe('buy',o)


if __name__=='__main__':unittest.main()
