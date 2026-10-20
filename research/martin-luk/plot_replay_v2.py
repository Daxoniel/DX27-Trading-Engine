"""Plot aggregate account NAV, never underlying vendor price histories."""
import argparse
from datetime import datetime
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original',type=Path,required=True)
    p.add_argument('--quoted',type=Path,required=True)
    p.add_argument('--benchmark',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter
    fig,ax=plt.subplots(figsize=(10,5.3),layout='constrained')
    for path,label,color,style in ((a.original,'Original OHLC entry proxy — not accepted','#858585','--'),
            (a.quoted,'Quote-constrained entries; OHLC exits','#c74d2d','-')):
        days={}
        for n in json.loads(path.read_text()):days[n['at'][:10]]=n['equity']
        ax.plot([datetime.fromisoformat(d) for d in days],list(days.values()),label=label,color=color,linestyle=style,linewidth=1.8)
    benchmark=json.loads(a.benchmark.read_text())['benchmark']
    ax.scatter([datetime.fromisoformat(benchmark['end'])],[benchmark['terminal_equity']],
        color='#236fa1',s=75,marker='D',label='SPY ending equity only',zorder=5)
    ax.axhline(100000,color='#b9b9b9',linewidth=.8)
    ax.set(title='MLP2: execution assumptions reverse the historical result',ylabel='Account equity (USD)')
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b'))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x,pos:f'${x/1000:.0f}k'))
    ax.grid(axis='y',alpha=.2);ax.spines[['top','right']].set_visible(False)
    ax.legend(loc='upper left',frameon=False,fontsize=9)
    fig.supxlabel('2025 · 5 bp adverse cost per side · Gaps carried · Retrospective diagnostic, no orders',fontsize=9)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(a.output)
    fig.savefig(a.output.with_suffix('.png'),dpi=150)
    plt.close(fig)


if __name__=='__main__':main()
