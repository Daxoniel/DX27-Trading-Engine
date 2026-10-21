"""Aggregate 5bp proxy return and drawdown, showing any halted prefix."""
import argparse
from datetime import datetime
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); r = json.loads(a.results.read_text())
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import PercentFormatter
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), layout='constrained')
    for mode, color in [('parent_ordinary', '#7c8991'), ('matched_ordinary', '#2e72aa'),
                        ('matched_relative', '#549156'), ('matched_residual', '#c46c25')]:
        case = r['runs'][mode+'-5bp']; rows = case['nav']; peak = 100000; dd = []
        for row in rows:
            peak = max(peak, row['equity']); dd.append(row['equity']/peak-1)
        dates = [datetime.fromisoformat(n['date']) for n in rows]
        label = mode+(' (halted)' if case['summary']['halt'] else '')
        style = '--' if case['summary']['halt'] else '-'
        axes[0].plot(dates, [n['equity']/100000-1 for n in rows], label=label, color=color, linestyle=style)
        axes[1].plot(dates, dd, color=color, linestyle=style)
    for ax in axes:
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b'))
        ax.grid(axis='y', alpha=.2); ax.spines[['top', 'right']].set_visible(False)
    axes[0].set_title('Cumulative proxy return'); axes[1].set_title('Daily observed drawdown')
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle('Frozen FF3 momentum: Jan-Sep 2026 temporal validation')
    fig.supxlabel('2026 · 5 bp/side · Pure-long extension · Two-session lag · Not verified fills · Not certified blind/OOS', fontsize=9)
    fig.savefig(a.output)
    if a.output.suffix.lower() == '.svg':
        a.output.write_text('\n'.join(line.rstrip() for line in a.output.read_text().splitlines())+'\n')
    fig.savefig(a.output.with_suffix('.png'), dpi=150); plt.close(fig)


if __name__ == '__main__':
    main()
