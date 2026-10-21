"""Publish aggregate extensions and hashes, keeping per-name ledgers private."""
import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean

from runner import parent, PROJECT


def diagnostics(case, prices, sectors):
    events = case['events']; counts = []
    for i, event in enumerate(events):
        end = events[i+1]['date'] if i+1 < len(events) else case['nav'][-1]['date']
        if end > event['date']:
            counts.extend(prices[s][end] > prices[s][event['date']] for s in event['weights'])
    if len(counts) != case['summary']['stock_return_intervals'] or sum(counts) != case['summary']['positive_stock_return_intervals']:
        raise ValueError('INDEPENDENT_POSITIVE_INTERVAL_COUNT_FAILED')
    timeline = {e['date']: e for e in events}; units = {}; previous = {}; pnl = defaultdict(float)
    max_name = 0.; max_sector = 0.
    for row in case['nav']:
        day = row['date']; values = {s: q*prices[s][day] for s, q in units.items()}
        for s, value in values.items():
            pnl[s] += value-previous[s]
        if day in timeline:
            values = timeline[day]['new_values']; units = {s: v/prices[s][day] for s, v in values.items()}
        previous = values; groups = defaultdict(float)
        for s, value in values.items():
            groups[sectors[s]] += value
        max_name = max(max_name, max(values.values(), default=0)/row['equity'])
        max_sector = max(max_sector, max(groups.values(), default=0)/row['equity'])
    if abs(sum(pnl.values())-case['summary']['modeled_cost']-(case['nav'][-1]['equity']-100000)) > .001:
        raise ValueError('PATH_CONTRIBUTION_RECONCILIATION_FAILED')
    gains = sorted((v for v in pnl.values() if v > 0), reverse=True); positive = sum(gains)
    return dict(independent_gross_positive_intervals=sum(counts), independent_stock_intervals=len(counts),
        top_one_share_of_positive_path_dollar_contribution=gains[0]/positive if positive else None,
        top_three_share_of_positive_path_dollar_contribution=sum(gains[:3])/positive if positive else None,
        unique_selected_names=len({s for e in events for s in e['weights']}),
        maximum_drifted_name_weight=max_name, maximum_drifted_sector_weight=max_sector,
        note='Observed-path contribution, not leave-winner-out counterfactual or actual executed-trade profit.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); result = json.loads((a.root/'results.json').read_text())
    original = json.loads((PROJECT/'docs/research/sector-momentum/protocol.json').read_text())
    prices, _, cohort, _, _ = parent.load(a.root.parent/'sector-momentum/input-manifest.json', original)
    sectors = {r['symbol']: r['sector'] for r in cohort}
    for key, item in result['runs'].items():
        private = json.loads((a.root/(key+'.json')).read_text()); events = private['events']
        item['summary']['mean_formation_weighted_spy_beta'] = mean(e['ex_ante_weighted_beta'] for e in events) if events else None
        turnover = sum(sum(abs(e['new_values'].get(s, 0)-e['old_values'].get(s, 0))
            for s in set(e['new_values'])|set(e['old_values'])) for e in events)
        item['summary']['turnover_over_initial_capital'] = turnover/100000
        item['summary']['holding_interval_frequency_is_actual_trade_win_rate'] = False
        item['diagnostics'] = diagnostics(private, prices, sectors)
        item['private_ledger_sha256'] = sha256((a.root/(key+'.json')).read_bytes()).hexdigest()
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output/'results.json').write_text(json.dumps(result, indent=2)+'\n')
    (a.output/'input-manifest.json').write_bytes((a.root/'input-manifest.json').read_bytes())
    if (a.root/'paper.meta.json').exists():
        (a.output/'paper-receipt.json').write_bytes((a.root/'paper.meta.json').read_bytes())
    print('Published aggregate cases:', len(result['runs']))


if __name__ == '__main__':
    main()
