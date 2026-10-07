"""6B-2I offline conformance and blocked-data checkpoint, not a Yahoo backtest."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np

from dx27.intelligence.sentinel.identity import canonical_json,stable_content_hash
from dx27.intelligence.sentinel.models import DataStatus
from dx27.intelligence.sentinel.research.sensor_protocol import verify_protocol_lock
from dx27.intelligence.sentinel.research.composite_reference import ReferenceBuilder
from dx27.intelligence.sentinel.research.reference_fixture import reference_fixture
from dx27.intelligence.sentinel.research.reference_library import validate_reference_library, references_for_sensor
from dx27.intelligence.sentinel.research.reference_scenarios import replace_measurements

ROOT=Path(__file__).resolve().parents[2]


def run(output):
    gdir=ROOT/'research/sentinel/6b-2g-contracts';verify_protocol_lock(gdir/'protocol.json',gdir/'protocol_lock.json')
    protocol=json.loads((gdir/'protocol.json').read_text())
    library=validate_reference_library(ROOT/'research/sentinel/references',protocol)
    ep=ROOT/'research/sentinel/6b-2i-reference';lock=json.loads((ep/'experiment_lock.json').read_text())
    for folder,file,key in [(ep,'experiment_protocol.json','protocol_file_sha256'),(ROOT/'research/sentinel/references','library.json','reference_library_sha256'),(ROOT/'research/sentinel/references','sensor_links.json','sensor_links_sha256')]:
        if hashlib.sha256((folder/file).read_bytes()).hexdigest()!=lock[key]:raise ValueError('experiment/reference lock mismatch')
    cal,builder,points=reference_fixture(protocol)
    states=tuple(builder.build(s.session_id,points) for s in cal.sessions[20:170])
    refs=ReferenceBuilder(cal);errors=[];mismatch=0;out=[]
    for i in range(126,len(states)):
        current=states[i];prior=states[:i];result=refs.build(current,states)
        mismatch+=result!=refs.build(current,prior)
        ranks={}
        for sensor in ('spy_return_20','rsp_return_20','spy_rv_20','vix_level','hy_oas_level'):
            a=np.array([x.measurement(sensor).value for x in prior])
            value=current.measurement(sensor).value
            ranks[sensor]=np.mean(a<value)+.5*np.mean(a==value)
        expected=100/3*((2-ranks['spy_return_20']-ranks['rsp_return_20'])/2+(ranks['spy_rv_20']+ranks['vix_level'])/2+ranks['hy_oas_level'])
        errors.append(abs(result[0].value-expected))
        zs=[]
        for sensor in ('rsp_spy_relative_20','qqq_spy_relative_20'):
            a=np.array([x.measurement(sensor).value for x in prior]);center=np.median(a)
            zs.append(abs((current.measurement(sensor).value-center)/(1.4826*np.median(abs(a-center)))))
        errors.append(abs(result[1].value-max(zs)))
        out.append(result)
    scenarios=[]
    for name,changes in [('CAP_WEIGHT_UP_EQUAL_WEIGHT_DOWN',{'spy_return_20':.1,'rsp_return_20':-.1,'rsp_spy_relative_20':-.2,'qqq_spy_relative_20':.15}),
                         ('QUIET_EQUITY_HIGH_VOL_CREDIT',{'spy_return_20':0.,'rsp_return_20':0.,'spy_rv_20':100.,'vix_level':100.,'hy_oas_level':2000.}),
                         ('BROAD_RALLY_LOW_PRESSURE',{'spy_return_20':.3,'rsp_return_20':.3,'spy_rv_20':.01,'vix_level':.01,'hy_oas_level':.01})]:
        current=states[-1];ms=tuple(replace(m,value=changes[m.sensor_id]) if m.sensor_id in changes else m for m in current.measurements)
        transformed=replace_measurements(current,ms)
        s,d=refs.build(transformed,states[:-1])
        scenarios.append({'scenario':name,'data_role':'SYNTHETIC_COUNTERFACTUAL_MEASUREMENTS','S':s.value,'D':d.value,'S_contributions':[vars(t) for t in s.group_contributions],'D_components':[vars(t) for t in d.group_contributions],'interpretation':'D reflects atypical relative performance; sign stays in components, no bearish/forecast classification.'})
    current=states[-1];day=current.snapshot.session_id
    from datetime import timedelta
    delayed=tuple(replace(p,first_seen_at=p.first_seen_at+timedelta(days=2)) if p.source_record_id==day and p.subject_ref.subject_id=='fixture:hy_oas' else p for p in points)
    s,d=refs.build(builder.build(day,delayed),states[:-1])
    scenarios.append({'scenario':'DELAYED_HY_PUBLICATION','S':s.value,'S_status':s.data_status.value,'S_usable':s.coverage.usable,'D_status':d.data_status.value,'interpretation':'No renormalization of missing credit; D has independent input coverage.'})
    sensitivity=[]
    s,d=out[-1]
    for factor in (.8,1.2):
        for group in s.group_contributions:
            score=sum(t.value*(factor if t.name==group.name else 1) for t in s.group_contributions)/(1+(factor-1)/3)
            sensitivity.append({'kind':'GROUP_WEIGHT','group':group.name,'relative_factor':factor,'S':score})
    for removed in ('spy_return_20','rsp_return_20','spy_rv_20','vix_level','hy_oas_level'):
        values=[]
        for term in s.group_contributions:
            retained=[v for k,v in term.signed_components if k!=removed]
            values.append(100/3*np.mean(retained) if retained else None)
        sensitivity.append({'kind':'LEAVE_ONE_SENSOR_OUT','removed':removed,'S':None if None in values else sum(values),'status':'UNAVAILABLE' if None in values else 'AVAILABLE_RESEARCH_SENSITIVITY'})
    for t in d.group_contributions:sensitivity.append({'kind':'D_SINGLE_PAIR_ABLATION','pair':t.name,'D':t.value})
    assert max(errors)<=1e-10 and mismatch==0 and scenarios[-1]['S'] is None and scenarios[-1]['S_status']=='STALE'
    report={'task_id':'6B-2I','runtime_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'data_role':'SYNTHETIC_FIXTURE_ONLY','synthetic_tape_digest':stable_content_hash(states),'implementation_correctness':'PASS','formula_comparisons':len(errors),'maximum_absolute_formula_error':max(errors),'prefix_replay_mismatches':mismatch,'library':library,'interpretation_scenarios':scenarios,'sensitivity':sensitivity,'real_source_admission':'BLOCKED_DATA','live_recorded_coverage':None,'incremental_effectiveness':'BLOCKED_DATA','prospective_confirmation':'INSUFFICIENT_EVIDENCE','prospective_sessions':0,'confirmation_started':False,'operational_reference_enabled':False,'forecast_enabled':False,'priority_enabled':False}
    output.mkdir(parents=True,exist_ok=True)
    (output/'reference_conformance_report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    (output/'reference_sample.json').write_text(canonical_json(out[-1])+'\n')
    (output/'sensor_reference_annotations.json').write_text(json.dumps([references_for_sensor(ROOT/'research/sentinel/references',protocol,d) for d in states[-1].descriptors],indent=2)+'\n')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.glob('*.json')) if p.name!='artifact_hashes.json'}
    (output/'artifact_hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args()
    report=run(args.output_dir)
    print(json.dumps({k:report[k] for k in ('task_id','implementation_correctness','formula_comparisons','maximum_absolute_formula_error','prefix_replay_mismatches','real_source_admission','incremental_effectiveness')},sort_keys=True))
