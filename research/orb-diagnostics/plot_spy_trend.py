"""Standalone fixed-comparison chart from the private simulated daily ledgers."""
import argparse
from datetime import datetime
import json
from pathlib import Path


def plot(folder,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter,FuncFormatter
    data={a:json.loads((Path(folder)/f'ZERO_0bps-{a}-daily.json').read_text()) for a in ('HOLD','SMA10')}
    dates=[datetime.fromisoformat(r['date']) for r in data['HOLD']]
    colors={'HOLD':'#2459a6','SMA10':'#16805b'};labels={'HOLD':'SPY buy and hold','SMA10':'Monthly SMA10, next-open execution'}
    fig,axes=plt.subplots(3,1,figsize=(11,10),sharex=True,layout='constrained')
    for arm,ledger in data.items():
        axes[0].plot(dates,[r['total'] for r in ledger],label=labels[arm],color=colors[arm],linewidth=1.2)
        peak=1;dd=[]
        for r in ledger:peak=max(peak,r['unit_nav']);dd.append(r['unit_nav']/peak-1)
        axes[1].plot(dates,dd,color=colors[arm],linewidth=1)
        axes[2].plot(dates,[r['cash']/r['total'] for r in ledger],color=colors[arm],linewidth=1)
    axes[0].set_yscale('log');axes[0].yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'USD {v:,.0f}'))
    axes[0].set_ylabel('Portfolio value (log scale)');axes[0].legend(frameon=False,loc='upper left')
    axes[0].set_title('SPY monthly trend comparison, 2000–2025\nUSD 10,000 initially + USD 1,000/month; zero cash interest, zero trading friction',loc='left',fontsize=11)
    axes[1].set_ylabel('Unitized drawdown');axes[1].yaxis.set_major_formatter(PercentFormatter(1));axes[1].set_ylim(-.65,.03)
    axes[2].set_ylabel('Cash weight');axes[2].yaxis.set_major_formatter(PercentFormatter(1));axes[2].set_ylim(-.03,1.03)
    for ax in axes:ax.grid(alpha=.2);ax.spines[['top','right']].set_visible(False)
    fig.savefig(output,dpi=160);plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--folder',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();plot(a.folder,a.output)
