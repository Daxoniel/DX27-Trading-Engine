"""Standalone figure for the fixed earnings-blackout comparison."""
import argparse
from datetime import date
import json
from pathlib import Path


def plot(source, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    source = Path(source)
    report = json.loads((source/'report.json').read_text())
    original = json.loads(Path('work/soxl-reversal/attempt-3/GAP_DOWN_LONG-daily.json').read_text())
    labels = dict(ANNOUNCEMENT_AND_NEXT_SESSION='Release day + next session',
                  ANNOUNCEMENT_ONLY='Release day only', NEXT_SESSION_ONLY='Next session only')
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), layout='constrained')
    ledgers = [('Unfiltered', original)] + [(labels[m], json.loads((source/f'{m}-daily.json').read_text()))
                                          for m in labels]
    for label, rows in ledgers:
        equity = 100000.
        values = []
        for r in rows:
            equity *= 1+r['portfolio_return']
            values.append(equity)
        axes[0, 0].plot([date.fromisoformat(r['date']) for r in rows], values, label=label)
    axes[0, 0].set(title='Same selected SOXL sessions; independent compounding', ylabel='USD; initial 100,000')
    axes[0, 0].legend(fontsize=8)
    primary = report['results']['ANNOUNCEMENT_AND_NEXT_SESSION']['primary']['GAP_DOWN_LONG']
    groups = [('All baseline trades', primary['unfiltered']),
              ('Retained trades', primary['summary']), ('Removed trades', primary['removed_trades'])]
    axes[0, 1].bar([x[0] for x in groups], [100*x[1]['net_trade_win_rate'] for x in groups],
                   color=['#4477aa', '#cc6677', '#228833'])
    axes[0, 1].axhline(50, color='black', lw=.8)
    axes[0, 1].set(title='Release day + next session: removed trades were stronger', ylabel='Net trade win rate (%)')
    years = [str(y) for y in range(2016, 2026)]
    previous = json.loads(Path('docs/reports/soxl-reversal/report.json').read_text())
    before = previous['primary']['GAP_DOWN_LONG']['by_year_and_partition']
    after = primary['by_year_and_partition']
    for label, values in [('Unfiltered', before), ('Release day + next session', after)]:
        axes[1, 0].plot(years, [values[y]['mean_trade_return_bps'] for y in years], marker='o', label=label)
    axes[1, 0].axhline(0, color='black', lw=.8)
    axes[1, 0].set(title='Every year; early coverage limitations unchanged', ylabel='Mean net trade return (bp)')
    axes[1, 0].legend(fontsize=8)
    for mode, label in labels.items():
        axes[1, 1].plot([0, 2, 5, 10], [report['results'][mode]['cases'][f'{b}bps']['GAP_DOWN_LONG']
                      ['mean_trade_return_bps'] for b in (0, 2, 5, 10)], marker='o', label=label)
    axes[1, 1].axhline(0, color='black', lw=.8)
    axes[1, 1].set(title='All fixed exclusion-date conventions and costs',
                   xlabel='Adverse basis points per fill', ylabel='Mean net trade return (bp)')
    axes[1, 1].legend(fontsize=8)
    for ax in axes.flat:
        ax.grid(axis='y', alpha=.2)
    fig.suptitle('SOXL major-earnings blackout — retrospective event sensitivity\n09:32–10:00 NY, 25% notional, 5bp/side except cost panel; no orders', fontsize=13)
    fig.savefig(output, dpi=150)
    plt.close(fig)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    plot(args.source, args.output)
