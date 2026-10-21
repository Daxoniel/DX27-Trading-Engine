"""Aggregate temporal-validation evidence, including any pre-score abort."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean

from validation import PROJECT, read_batches, rm


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    if (a.root/'integrity-v2.json').exists() or not (a.root/'results.json').exists():
        # An input abort never becomes a successful zero-return backtest.
        latest=a.root/('integrity-v2.json' if (a.root/'integrity-v2.json').exists() else 'integrity.json')
        result=json.loads(latest.read_text())
        (a.output/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    else:
        result=json.loads((a.root/'results.json').read_text())
        manifest=json.loads((a.root/'input-manifest.json').read_text())
        batch=read_batches(a.root,manifest['inputs']['adjusted_new'])
        prices={s:{r['t'][:10]:r['c'] for r in rows} for s,rows in batch.items()}
        cohort=json.loads((PROJECT/'work/mlp1-history/cohort.json').read_text())
        sectors={r['symbol']:r['sector'] for r in cohort}
        stats=rm.module('rv_parent_diagnostics',PROJECT/'research/residual-momentum/summarize.py')
        for key,case in result['runs'].items():
            path=a.root/(key+'.json'); private=json.loads(path.read_text())
            case['diagnostics']=stats.diagnostics(private,prices,sectors)
            case['summary']['mean_formation_weighted_spy_beta']=mean(e['ex_ante_weighted_beta'] for e in private['events']) if private['events'] else None
            case['private_ledger_sha256']=sha256(path.read_bytes()).hexdigest()
        (a.output/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    (a.output/'input-manifest.json').write_bytes((a.root/'input-manifest.json').read_bytes())
    print('Published status:',result.get('screen',result.get('status')))


if __name__=='__main__':
    main()
