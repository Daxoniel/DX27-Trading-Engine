from copy import deepcopy
from datetime import timedelta
import unittest

from quote_history_v2 import quote_fill, nanos
from history_replay_quote import Replay
from strategy import stamp
from test_replay_v2 import market


def quote(at, ask=100, size=1):
    return dict(t=at,bp=ask*.999,ap=ask,**{'as':size},c=['R'])


class QuoteExecutionTests(unittest.TestCase):
    def test_no_future_quote_even_one_nanosecond(self):
        at='2025-04-28T14:00:00Z'
        intent=dict(limit_price=101,stop_price=99,quantity=200)
        q=quote('2025-04-28T14:00:00.000000001Z')
        fill,reason=quote_fill(q,at,intent,5)
        self.assertIsNone(fill)
        self.assertEqual(reason,'QUOTE_FUTURE_OR_STALE')
        self.assertEqual(nanos(q['t'])-nanos(at),1)

    def test_visible_partial_quantity_and_limits(self):
        at='2025-04-28T14:00:00Z'
        intent=dict(limit_price=101,stop_price=99,quantity=250)
        fill,reason=quote_fill(quote(at),at,intent,5)
        self.assertIsNone(reason)
        self.assertEqual(fill['quantity'],100)
        self.assertEqual(fill['unfilled_cancelled'],150)
        self.assertAlmostEqual(fill['price'],100.05)
        intent['limit_price']=100.01
        self.assertEqual(quote_fill(quote(at),at,intent,5)[1],'ASK_WITH_COST_ABOVE_LIMIT')

    def test_unknown_nonregular_stale_or_crossed_cannot_fill(self):
        at='2025-04-28T14:00:00Z';intent=dict(limit_price=200,stop_price=90,quantity=200)
        cases=[None,quote('2025-04-28T13:58:59Z'),dict(quote(at),c=['N']),dict(quote(at),bp=101)]
        for q in cases:self.assertIsNone(quote_fill(q,at,intent,5)[0])

    def test_gap_below_protection_cancelled_with_known_quote(self):
        at='2025-04-28T14:00:00Z';intent=dict(limit_price=101,stop_price=99,quantity=200)
        self.assertEqual(quote_fill(quote(at,90),at,intent,5)[1],'ASK_ALREADY_BELOW_PROTECTION')

    def test_bar_future_open_does_not_set_quote_entry_price(self):
        p,bs=market();calls=[]
        def source(s,at):
            calls.append((s,at))
            # The quote is known at the scheduled open; no later candle open.
            return quote(at,bs[s][3]['open']*.999,1)
        r=Replay(quote_source=source);r.session(p,bs,{})
        buys=[f for f in r.fills if f['side']=='buy']
        self.assertEqual(len(buys),4)
        self.assertTrue(all(f['quantity']==100 for f in buys))
        self.assertTrue(all(f['reason']=='DISPLAYED_ASK_AT_SCHEDULED_OPEN' for f in buys))
        changed=deepcopy(bs)
        for rows in changed.values():
            rows[4]['open']*=1.01;rows[4]['high']=max(rows[4]['high'],rows[4]['open'])
        other=Replay(quote_source=source);other.session(p,changed,{})
        self.assertEqual(buys,[f for f in other.fills if f['side']=='buy'])

    def test_missing_quote_never_falls_back_to_trade_bar_open(self):
        p,bs=market();r=Replay(quote_source=lambda s,at:None);r.session(p,bs,{})
        self.assertEqual(r.fills,[])
        self.assertEqual(sum(e['kind']=='QUOTE_ENTRY_REJECTED' for e in r.events),4)


if __name__=='__main__':unittest.main()
