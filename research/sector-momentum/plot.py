"""Plot aggregate proxy equity, explicitly showing the incomplete broad control."""
import argparse
from datetime import datetime
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--results',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=json.loads(a.results.read_text())
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter
    fig,ax=plt.subplots(figsize=(10,5.3),layout='constrained')
    for mode,color,style in [('ordinary','#2c6caa','-'),('relative','#d17024','-'),('broad','#738773','--'),('spy','#777777',':')]:
        case=r['runs'][mode+'-5bp'];rows=case['nav'];label=mode+(' (halted)' if case['summary']['halt'] else '')
        ax.plot([datetime.fromisoformat(x['date']) for x in rows],[x['equity'] for x in rows],
            label=label,color=color,linestyle=style,linewidth=1.6)
    ax.set(title='High-beta momentum: sector-relative versus ordinary ranking',ylabel='Adjusted-close proxy equity (USD)')
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v,pos:f'${v/1000:.0f}k'))
    ax.xaxis.set_major_locator(mdates.MonthLocator());ax.xaxis.set_major_formatter(mdates.DateFormatter('%b'))
    ax.legend(frameon=False);ax.grid(axis='y',alpha=.2);ax.spines[['top','right']].set_visible(False)
    fig.supxlabel('2025 · 5 bp/side · Two-session lag · Fixed cohort · Not executable fills · No orders',fontsize=9)
    fig.savefig(a.output);fig.savefig(a.output.with_suffix('.png'),dpi=150);plt.close(fig)
    if a.output.suffix.lower()=='.svg':
        a.output.write_text('\n'.join(line.rstrip() for line in a.output.read_text().splitlines())+'\n')


if __name__=='__main__':main()
