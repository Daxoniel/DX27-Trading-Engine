from copy import deepcopy
from datetime import date,timedelta
from hashlib import sha256
import json
import math
from pathlib import Path
import tempfile
import unittest

from audit import audit_case,verify_features
from study import beta,features,rebalance,run,targets

RULES=json.loads((Path(__file__).resolve().parents[2]/'docs/research/sector-momentum/protocol.json').read_text())


def fixture():
    calendar=[];day=date(2023,1,2)
    while day<=date(2025,12,31):
        if day.weekday()<5:calendar.append(day.isoformat())
        day+=timedelta(days=1)
    adj={'SPY':{}};raw={};cohort=[]
    for s in ['SPY']+[f'S{i:02d}' for i in range(24)]:
        price=50;adj[s]={};raw[s]={}
        for i,d in enumerate(calendar):
            market=.0003+.006*math.sin(i*.19)
            daily=market if s=='SPY' else 2*market+.00001*int(s[1:])
            price*=1+daily;adj[s][d]=price;raw[s][d]=(price,100000000)
        if s!='SPY':cohort.append(dict(symbol=s,sector='A' if int(s[1:])<12 else 'B'))
    return adj,raw,cohort,calendar


class MomentumTests(unittest.TestCase):
    def test_beta_is_covariance_ratio_not_volatility(self):
        x=[-.02,.01,.04,-.01];self.assertAlmostEqual(beta([2*a+.001 for a in x],x),2)
        with self.assertRaisesRegex(ValueError,'ZERO_MARKET_VARIANCE'):beta([1,2],[0,0])

    def test_momentum_skips_formation_month_and_excludes_self(self):
        adj,raw,c,cal=fixture();f=features('2025-04-30',adj,raw,c,cal,RULES)
        r=f['eligible'][0];self.assertEqual(r['momentum_start'],'2024-04-30');self.assertEqual(r['momentum_end'],'2025-03-31')
        peers=[p['momentum'] for p in f['base'] if p['sector']==r['sector'] and p['symbol']!=r['symbol']]
        self.assertEqual(r['peer_count'],11);self.assertAlmostEqual(r['relative'],r['momentum']-sum(peers)/11)
        self.assertEqual(verify_features([f],adj,raw,cal,RULES),24)

    def test_future_price_changes_cannot_change_formation(self):
        adj,raw,c,cal=fixture();before=features('2025-04-30',adj,raw,c,cal,RULES)
        for rows in adj.values():
            for d in rows:
                if d>'2025-04-30':rows[d]*=100
        self.assertEqual(before,features('2025-04-30',adj,raw,c,cal,RULES))

    def test_missing_past_return_not_forward_filled(self):
        adj,raw,c,cal=fixture();adj['S00'].pop('2025-04-29')
        f=features('2025-04-30',adj,raw,c,cal,RULES)
        self.assertNotIn('S00',{r['symbol'] for r in f['base']})

    def test_both_rankings_obey_same_sector_cap(self):
        adj,raw,c,cal=fixture();f=features('2025-04-30',adj,raw,c,cal,RULES)
        for mode in ('relative','ordinary'):
            w=targets(f,mode,RULES);self.assertEqual(len(w),4);self.assertAlmostEqual(sum(w.values()),.4)

    def test_costs_use_post_cost_target_equity(self):
        new,cash,cost=rebalance({},100,{'A':1.},.01)
        self.assertAlmostEqual(new['A'],100/1.01);self.assertAlmostEqual(cost,100-100/1.01);self.assertEqual(cash,0)
        new,cash,cost=rebalance({'A':100},0,{'B':1},.01)
        self.assertAlmostEqual(new['B'],100*.99/1.01);self.assertAlmostEqual(new['B']+cost,100)

    def test_drifted_weights_are_rebalanced_with_funding(self):
        new,cash,cost=rebalance({'A':70,'B':40},10,{'A':.5,'B':.5},.0025)
        self.assertAlmostEqual(new['A'],new['B']);self.assertAlmostEqual(sum(new.values())+cash+cost,120)
        self.assertGreater(cost,0)

    def test_second_later_session_entry_not_formation_close(self):
        adj,raw,c,cal=fixture();f=features('2025-04-30',adj,raw,c,cal,RULES)
        result=run(adj,cal,[f],'relative',5,RULES)
        self.assertEqual(result['events'][0]['date'],'2025-05-02')
        self.assertEqual(next(n['equity'] for n in result['nav'] if n['date']=='2025-05-01'),100000)

    def test_missing_held_close_halts_with_no_full_return(self):
        adj,raw,c,cal=fixture();f=features('2025-04-30',adj,raw,c,cal,RULES)
        s=next(iter(targets(f,'relative',RULES)));adj[s].pop('2025-05-05')
        r=run(adj,cal,[f],'relative',5,RULES)
        self.assertIsNone(r['summary']['proxy_return']);self.assertEqual(r['nav'][-1]['date'],'2025-05-02')

    def test_decimal_audit_detects_changed_cash(self):
        adj,raw,c,cal=fixture();f=features('2025-04-30',adj,raw,c,cal,RULES)
        r=run(adj,cal,[f],'relative',5,RULES);r['summary'].update(input_manifest_sha256='fixture',code_seal={})
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'case.json';p.write_text(json.dumps(r))
            self.assertEqual(audit_case(p,adj,cal,[f],RULES,'fixture',{})['status'],'PASS')
            r['events'][0]['new_cash']+=1;p.write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError,'INDEPENDENT_VALUE_MISMATCH'):audit_case(p,adj,cal,[f],RULES,'fixture',{})

    def test_no_unfunded_target(self):
        with self.assertRaisesRegex(ValueError,'UNFUNDED_TARGET'):rebalance({},100,{'A':1.1},.001)


if __name__=='__main__':unittest.main()
