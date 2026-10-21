from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ledger import Journal, advance, digest, initialize, weights
from ledger_audit import audit
from ranking import finite_feature, select_independent

HASH = 'a'*64
DAYS = ['2026-01-05','2026-01-06','2026-01-07','2026-01-08']


def request(day, prices, targets=None):
    out = dict(date=day, closes=prices, source_sha256=HASH)
    if targets is not None:
        out.update(targets=targets, rank_plan_sha256=HASH)
    return out


def target(symbol): return dict(symbol=symbol,sector=symbol)


class ShadowTests(unittest.TestCase):
    def test_cash_funding_costs_sale_and_no_redistribution(self):
        state = initialize(DAYS,[DAYS[0],DAYS[2]],25)
        state,mark = advance(state, request(DAYS[0],{'A':100},[target('A')]))
        after = Decimal(mark['nav'])
        self.assertAlmostEqual(float(Decimal(mark['gross'])/after),.01)
        self.assertAlmostEqual(float(after),100000/(1+.0025*.01))
        state,mark = advance(state,request(DAYS[1],{'A':200}))
        self.assertGreater(float(Decimal(mark['gross'])/Decimal(mark['nav'])),.01)
        before = Decimal(state['last_nav']); held = Decimal(state['units']['A'])*200
        state,mark = advance(state,request(DAYS[2],{'A':200},[]))
        self.assertEqual(state['units'],{})
        self.assertAlmostEqual(float(Decimal(mark['cost'])),float(held*Decimal('.0025')))
        self.assertAlmostEqual(float(state['cash']),float(before-held*Decimal('.0025')))

    def test_halt_is_terminal_and_missing_never_filled(self):
        s = initialize(DAYS,[DAYS[0]],5)
        s,_ = advance(s,request(DAYS[0],{'A':100},[target('A')]))
        for bad in (None,0,'NaN','Infinity'):
            halted,mark = advance(s,request(DAYS[1],{'A':bad}))
            self.assertIsNone(mark['nav']); self.assertEqual(halted['units'],s['units'])
            with self.assertRaises(ValueError): advance(halted,request(DAYS[2],{'A':100}))
        halted,_ = advance(initialize(DAYS,[DAYS[0]],5),request(DAYS[0],{}))
        self.assertEqual(halted['halt']['code'],'RANK_PLAN_MISSING')

    def test_schedule_receipts_and_constraints_block(self):
        state=initialize(DAYS,[DAYS[0]],5)
        for bad in (request(DAYS[1],{}),dict(date=DAYS[0],closes={},source_sha256='bad'),
                    request(DAYS[0],{'SOXL':1},[])):
            with self.assertRaises(ValueError): advance(state,bad)
        for rows in ([target('A')]*2,[dict(symbol=str(i),sector='X') for i in range(3)],
                     [target(str(i)) for i in range(11)]):
            with self.assertRaises(ValueError): weights(rows)
        state,_=advance(state,request(DAYS[0],{},[]))
        with self.assertRaises(ValueError): advance(state,request(DAYS[1],{'B':1},[target('B')]))

    def test_journal_replay_and_independent_account_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'journal'; journal=Journal(root)
            journal.create(initialize(DAYS,[DAYS[0],DAYS[2]],5))
            journal.append(request(DAYS[0],{'A':100},[target('A')]))
            journal.append(request(DAYS[1],{'A':80}))
            journal.append(request(DAYS[2],{'A':90,'B':5},[target('B')]))
            journal.append(request(DAYS[3],{'B':6}))
            state,seal,count=journal.replay()
            self.assertEqual((count,state['marks'],state['rebalances']),(5,4,2))
            self.assertTrue(audit(root)['complete'])
            with self.assertRaises(FileExistsError): journal.create(state)
            with self.assertRaises(ValueError): journal.append(request('2026-01-09',{}))

    def test_mutation_detected_even_if_hash_chain_is_resealed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'j'; journal=Journal(root)
            journal.create(initialize(DAYS,[DAYS[0]],5))
            journal.append(request(DAYS[0],{'A':100},[target('A')]))
            path=root/'000001.json'; event=json.loads(path.read_text())
            event['mark']['cost']='0'; event.pop('sha256'); event['sha256']=digest(event)
            path.write_text(json.dumps(event))
            with self.assertRaises(ValueError): journal.replay()
            with self.assertRaises(ValueError): audit(root)
            path.unlink()
            (root/'000002.json').write_text('{}')
            with self.assertRaises(ValueError): journal.replay()

    def test_independent_rank_ties_sector_cap_and_nonfinite_guard(self):
        rows=[dict(symbol=s,sector='X' if s<'D' else s,score=1.) for s in 'DCBA']
        self.assertEqual([r['symbol'] for r in select_independent(rows,'score')],['A','B','D'])
        for feature in (dict(score=float('nan'),dispersion=1,coefficients=[0]*4),
                        dict(score=1,dispersion=1,coefficients=[0]*3)):
            with self.assertRaises(ValueError): finite_feature(feature)

    def test_independent_score_rank_disagreement_aborts(self):
        import ranking
        formation=dict(asof=DAYS[0],eligible=[dict(symbol='A',sector='X',momentum=2,relative=2),
                                              dict(symbol='B',sector='Y',momentum=1,relative=1)])
        # Independent score order opposite to QR; difference is deliberately tiny
        # and within value tolerance, but exact final rank/sector choices still matter.
        rows=[dict(symbol=str(i),sector=str(i),momentum=0,relative=0) for i in range(11)]
        formation['eligible']=rows
        def qr(symbol,*args): return dict(score=1,dispersion=1,coefficients=[0]*4)
        def dec(symbol,*args): return dict(score=1+(1e-10 if symbol=='9' else 0),dispersion=1,coefficients=[0]*4)
        with patch.object(ranking.parent,'features',return_value=formation), \
             patch.object(ranking.base_audit,'verify_features',return_value=11), \
             patch.object(ranking.primary,'score',side_effect=qr), \
             patch.object(ranking.independent,'independent_score',side_effect=dec), \
             patch.object(ranking.independent,'verify'):
            with self.assertRaisesRegex(ValueError,'INDEPENDENT_RANK_MISMATCH'):
                ranking.build(DAYS[0],{}, {}, [], [], {}, dict(position_count=10,maximum_names_per_sector=2,weight_per_slot=.1),{})


if __name__=='__main__': unittest.main()
