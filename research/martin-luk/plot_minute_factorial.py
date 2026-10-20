"""Plot primary factorial aggregate NAV; no raw vendor stock/quote series."""
import argparse
from datetime import datetime
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=json.loads(a.results.read_text())
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter
    fig,ax=plt.subplots(figsize=(10,5.3),layout='constrained')
    for cell,color,style in [('5m-single','#236fa1','-'),('1m-single','#c74d2d','-'),
            ('5m-reentry','#287f67','--'),('1m-reentry','#8058a0','--')]:
        case=r['runs'][cell+'-5bp'];points=case['daily_equity']
        label=cell+(' (halted)' if case['summary']['halt'] else '')
        ax.plot([datetime.fromisoformat(p['date']) for p in points],[p['equity'] for p in points],
            label=label,color=color,linestyle=style,linewidth=1.6)
    ax.axhline(100000,color='#a9a9a9',linewidth=.8)
    ax.set(title='Minute signals × same-day fresh setups: matched 2×2 replay',ylabel='Account equity (USD)')
    ax.xaxis.set_major_locator(mdates.MonthLocator());ax.xaxis.set_major_formatter(mdates.DateFormatter('%b'))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v,pos:f'${v/1000:.0f}k'))
    ax.grid(axis='y',alpha=.2);ax.spines[['top','right']].set_visible(False)
    ax.legend(loc='best',frameon=False)
    fig.supxlabel('2025 · 5 bp/side · Common minute execution · Gaps carried · OHLC exits · No orders',fontsize=9)
    a.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.output);fig.savefig(a.output.with_suffix('.png'),dpi=150)
    plt.close(fig)


if __name__=='__main__':main()
