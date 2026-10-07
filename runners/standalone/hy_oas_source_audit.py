"""Audit verified local public-source captures; no raw licensed series published."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import subprocess
from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.intelligence.sentinel.research.hy_oas_audit import summarize_exports


def run(captures,daily,output):
    if output.exists() and any(output.iterdir()):raise ValueError('new audit output directory required')
    root=Path(__file__).resolve().parents[2]
    report=summarize_exports(captures,daily,load_xnys_calendar(date(2026,1,1),date(2026,12,31)))
    report['runtime_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    report['capture_manifest_sha256']=hashlib.sha256((captures/'manifest.json').read_bytes()).hexdigest()
    report['daily_manifest_sha256']=hashlib.sha256((daily/'manifest.json').read_bytes()).hexdigest()
    output.mkdir(parents=True,exist_ok=True)
    (output/'audit_report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture-dir',type=Path,required=True);p.add_argument('--daily-dir',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
    r=run(a.capture_dir,a.daily_dir,a.output_dir)
    print(json.dumps({k:r[k] for k in ['audit_result','admission_result','expected_sessions','usable_archive_samples','archive_date_proxy_age0_fraction','actual_original_cutoff_coverage']},sort_keys=True))
