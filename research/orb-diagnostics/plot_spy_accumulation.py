"""Standalone chart from local ledgers; requires optional matplotlib."""
import argparse
from datetime import datetime
import json
from pathlib import Path


def plot(folder,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter,FuncFormatter
    arms=('IMMEDIATE','DCA12','DIP5')
    data={a:json.loads((Path(folder)/f'ZERO_0bps-{a}-daily.json').read_text()) for a in arms}
    colors={'IMMEDIATE':'#2459a6','DCA12':'#d48b20','DIP5':'#16805b'}
    labels={'IMMEDIATE':'Invest on arrival','DCA12':'Initial cash phased over 12 months','DIP5':'Buy after 5% drawdown'}
    dates=[datetime.fromisoformat(x['date']) for x in data['IMMEDIATE']]
    fig,axes=plt.subplots(3,1,figsize=(11,10),sharex=True,layout='constrained')
    for arm,ledger in data.items():
        axes[0].plot(dates,[x['total'] for x in ledger],label=labels[arm],color=colors[arm],linewidth=1.2)
        peak=1;dd=[]
        for x in ledger:peak=max(peak,x['unit_nav']);dd.append(x['unit_nav']/peak-1)
        axes[2].plot(dates,dd,color=colors[arm],linewidth=1)
        if arm!='IMMEDIATE':
            axes[1].plot(dates,[x['total']/b['total']-1 for x,b in zip(ledger,data['IMMEDIATE'])],color=colors[arm],linewidth=1)
    axes[0].set_yscale('log');axes[0].yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'USD {v:,.0f}'))
    axes[0].set_ylabel('Portfolio value (log scale)');axes[0].legend(loc='upper left',frameon=False,fontsize=9)
    axes[0].set_title('SPY accumulation, 2000–2025 | USD 10,000 initially + USD 1,000/month\nDividend-adjusted proxy; zero cash interest, zero purchase friction; no sales',loc='left',fontsize=11)
    axes[1].axhline(0,color='#888888',linewidth=.7);axes[1].set_ylabel('Wealth vs invest on arrival')
    axes[1].yaxis.set_major_formatter(PercentFormatter(1))
    axes[2].set_ylabel('Unitized drawdown');axes[2].yaxis.set_major_formatter(PercentFormatter(1));axes[2].set_ylim(-.65,.03)
    for ax in axes:ax.grid(alpha=.2);ax.spines[['top','right']].set_visible(False)
    fig.savefig(output,dpi=160);plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--folder',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();plot(a.folder,a.output)
