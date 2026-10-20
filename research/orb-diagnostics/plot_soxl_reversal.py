"""Render the fixed SOXL study; matplotlib is an optional report-only dependency."""
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
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), layout='constrained')
    for arm in ('GAP_DOWN_LONG', 'ALWAYS_LONG', 'TWO_SIDED'):
        rows = json.loads((source/f'{arm}-daily.json').read_text())
        equity = 100000
        values = []
        for r in rows:
            equity *= 1+r['portfolio_return']
            values.append(equity)
        axes[0, 0].plot([date.fromisoformat(r['date']) for r in rows], values, label=arm)
    axes[0, 0].set(title='Selected-session NAV: 09:32–10:00, 5bp per side', ylabel='USD; initial 100,000')
    axes[0, 0].legend(fontsize=8)
    timings = ['09:30', '09:31', '09:32', '09:35']
    for bps in (0, 2, 5, 10):
        values = [report['cases'][f'{t}_{bps}bps']['GAP_DOWN_LONG']['mean_trade_return_bps'] for t in timings]
        axes[0, 1].plot(timings, values, marker='o', label=f'{bps}bp per side')
    axes[0, 1].axhline(0, color='black', lw=.8)
    axes[0, 1].set(title='Gap-down long: fixed delay/cost sensitivity', ylabel='Mean net trade return (bp)', xlabel='Entry NY time; 09:30 is idealized')
    axes[0, 1].legend(fontsize=8)
    years = [str(y) for y in range(2016, 2026)]
    stats = report['primary']['GAP_DOWN_LONG']['by_year_and_partition']
    values = [stats[y]['mean_trade_return_bps'] for y in years]
    axes[1, 0].bar(years, values, color=['#227d68' if v > 0 else '#bb4444' for v in values])
    axes[1, 0].axhline(0, color='black', lw=.8)
    axes[1, 0].set(title='Primary gap-down long: every year', ylabel='Mean net trade return (bp)')
    import exchange_calendars as xc
    cal = xc.get_calendar('XNYS', start='2016-01-01', end='2025-12-31')
    expected = [sum(d.year == int(y) for d in cal.sessions) for y in years]
    axes[1, 1].bar(years, expected, color='#dddddd', label='Calendar sessions')
    axes[1, 1].bar(years, [stats[y]['sessions'] for y in years], color='#4477aa', label='Common complete sample')
    axes[1, 1].set(title='Coverage: early years are heavily selected', ylabel='Sessions')
    axes[1, 1].legend(fontsize=8)
    for ax in axes.flat:
        ax.grid(axis='y', alpha=.2)
    fig.suptitle('SOXL overnight reversal — retrospective transfer test, not execution evidence\n25% portfolio notional; missing sessions excluded; no 2026 prices', fontsize=13)
    fig.savefig(output, dpi=150)
    plt.close(fig)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    plot(args.source, args.output)
