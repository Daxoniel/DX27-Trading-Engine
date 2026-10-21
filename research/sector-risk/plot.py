"""Primary-case aggregate equity and drawdown; no raw prices or positions."""
import argparse
from datetime import datetime
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); results = json.loads(a.results.read_text())
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import PercentFormatter
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), layout='constrained', sharex=True)
    for row, mode in enumerate(('ordinary', 'relative')):
        for overlay, color in [('unmanaged', '#677987'), ('fixed_initial', '#247b60'), ('monthly_risk', '#bc6023')]:
            rows = results['runs'][f'{mode}-{overlay}-5bp']['nav']
            dates = [datetime.fromisoformat(n['date']) for n in rows]
            equity = [n['equity']/100000-1 for n in rows]
            peak = 100000.; dd = []
            for n in rows:
                peak = max(peak, n['equity']); dd.append(n['equity']/peak-1)
            axes[row, 0].plot(dates, equity, label=overlay, color=color, linewidth=1.5)
            axes[row, 1].plot(dates, dd, label=overlay, color=color, linewidth=1.5)
        axes[row, 0].set_title(mode+' · cumulative proxy return')
        axes[row, 1].set_title(mode+' · daily observed drawdown')
        for ax in axes[row]:
            ax.yaxis.set_major_formatter(PercentFormatter(1))
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b'))
            ax.grid(axis='y', alpha=.2); ax.spines[['top', 'right']].set_visible(False)
    axes[0, 0].legend(frameon=False, fontsize=9)
    fig.suptitle('High-beta momentum: risk reduction versus constant lower exposure')
    fig.supxlabel('2025 · 5 bp/side · Two-session lag · Adjusted-close proxies · No executable fills · Not out of sample', fontsize=9)
    fig.savefig(a.output)
    if a.output.suffix.lower() == '.svg':
        a.output.write_text('\n'.join(line.rstrip() for line in a.output.read_text().splitlines())+'\n')
    fig.savefig(a.output.with_suffix('.png'), dpi=150)
    plt.close(fig)


if __name__ == '__main__':
    main()
